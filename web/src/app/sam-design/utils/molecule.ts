// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { Molecule, MolecularProperties } from "../types";

/**
 * 从模型执行的文本结果中解析SMILES字符串
 * 支持格式：
 * - "1. SMILES: xxx"
 * - "SMILES: xxx"
 * - "xxx" (纯SMILES字符串)
 */
export function parseSMILESFromText(text: string): string[] {
  if (!text || text.trim().length === 0) {
    return [];
  }

  const smilesList: string[] = [];
  
  // 匹配格式：1. SMILES: xxx 或 SMILES: xxx
  const numberedPattern = /\d+\.\s*SMILES:\s*`?([^`\n]+)`?/gi;
  const matches = text.matchAll(numberedPattern);
  
  for (const match of matches) {
    const smiles = match[1]?.trim();
    if (smiles && smiles.length > 0) {
      smilesList.push(smiles);
    }
  }

  // 如果没有找到编号格式，尝试匹配 "SMILES: xxx"
  if (smilesList.length === 0) {
    const simplePattern = /SMILES:\s*`?([^`\n]+)`?/gi;
    const simpleMatches = text.matchAll(simplePattern);
    for (const match of simpleMatches) {
      const smiles = match[1]?.trim();
      if (smiles && smiles.length > 0) {
        smilesList.push(smiles);
      }
    }
  }

  // 如果还是没有找到，尝试从行中提取可能的SMILES
  if (smilesList.length === 0) {
    const lines = text.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      // 简单的SMILES验证：包含字母、数字、括号、等号等
      if (trimmed.length > 5 && /^[A-Za-z0-9=()\[\]+\-.,@#]+$/.test(trimmed)) {
        // 排除明显不是SMILES的行（如"成功生成"等）
        if (!trimmed.includes('成功') && !trimmed.includes('生成') && !trimmed.includes('骨架')) {
          smilesList.push(trimmed);
        }
      }
    }
  }

  return smilesList;
}

/**
 * 从end节点的output中提取最终候选分子
 * end节点的output包含所有上游节点的输出，格式为 { source_id: source_outputs }
 */
export function extractMoleculesFromEndNode(
  nodeOutputs: Record<string, any>,
  workflowGraph?: { nodes: any[]; edges: any[] } | null
): Partial<Molecule>[] {
  const moleculeMap = new Map<string, Partial<Molecule>>();
  const imageUrlMap = new Map<string, string>();
  
  const normalizeSmiles = (s: string) => s.trim();
  
  const tryCollectFromObject = (obj: any) => {
    if (!obj || typeof obj !== "object") return;
    
    const rawSmiles = typeof obj.smiles === "string" ? obj.smiles : (typeof obj.SMILES === "string" ? obj.SMILES : null);
    if (rawSmiles) {
      const smiles = normalizeSmiles(rawSmiles);
      const existing = moleculeMap.get(smiles) || { smiles };
      
      // 解析分数：优先从 opt_des 解析三维分数
      if (obj.opt_des && typeof obj.opt_des === "string") {
        const dimScores = parseDimensionScoresFromOptDes(obj.opt_des);
        if (dimScores) {
          const totalScore = typeof obj.score === "number" ? obj.score : 
            (dimScores.surfaceAnchoring + dimScores.energyLevel + dimScores.packingDensity) / 3;
          existing.score = {
            total: totalScore,
            surfaceAnchoring: dimScores.surfaceAnchoring,
            energyLevel: dimScores.energyLevel,
            packingDensity: dimScores.packingDensity,
          };
        } else if (typeof obj.score === "number") {
          existing.score = { total: obj.score };
        }
      } else if (typeof obj.score === "number") {
        existing.score = { total: obj.score };
      }
      
      // 解析分析描述
      if (obj.opt_des && typeof obj.opt_des === "string") {
        existing.analysis = {
          description: obj.opt_des,
          explanation: obj.opt_des,
        };
      }
      
      if (typeof obj.imageUrl === "string" && obj.imageUrl.includes("/molecular_images/")) {
        imageUrlMap.set(smiles, obj.imageUrl);
        existing.imageUrl = obj.imageUrl;
      }
      if (obj.properties && typeof obj.properties === "object") {
        existing.properties = { ...(existing.properties || {}), ...(obj.properties as MolecularProperties) };
      }
      
      moleculeMap.set(smiles, existing);
    }
  };
  
  const extractFromArray = (arr: any[]) => {
    for (const item of arr) {
      if (Array.isArray(item)) {
        extractFromArray(item);
      } else if (item && typeof item === "object") {
        tryCollectFromObject(item);
      }
    }
  };
  
  // 找到end节点
  let endNodeId: string | null = null;
  if (workflowGraph && workflowGraph.nodes) {
    const endNode = workflowGraph.nodes.find((n: any) => n.type === "end");
    if (endNode) {
      endNodeId = endNode.id;
    }
  }
  
  // 如果找到了end节点，从end节点的output中提取
  if (endNodeId && nodeOutputs[endNodeId]) {
    const endNodeOutput = nodeOutputs[endNodeId];
    
    // end节点的output是一个对象，包含所有上游节点的输出
    // 格式：{ source_id: source_outputs }
    if (endNodeOutput && typeof endNodeOutput === "object") {
      // 先找到总结节点（LLM4）的输出，它包含最终的评估结果
      let summaryNodeOutput: any = null;
      let summaryNodeId: string | null = null;
      
      // 遍历所有上游节点的输出，找到总结节点
      for (const [sourceId, sourceOutput] of Object.entries(endNodeOutput)) {
        if (!sourceOutput || typeof sourceOutput !== "object") continue;
        
        // 检查节点名称（通过workflowGraph）
        if (workflowGraph && workflowGraph.nodes) {
          const sourceNode = workflowGraph.nodes.find((n: any) => n.id === sourceId);
          if (sourceNode) {
            const nodeName = (sourceNode.data?.displayName || "").toLowerCase();
            // 识别总结节点（LLM4或包含"总结"/"summary"）
            if (nodeName.includes("llm4") || nodeName.includes("总结") || nodeName.includes("summary")) {
              summaryNodeOutput = sourceOutput;
              summaryNodeId = sourceId;
              break;
            }
          }
        }
      }
      
      // 如果找到了总结节点，从总结节点的output中提取最终候选分子
      if (summaryNodeOutput && summaryNodeOutput.output) {
        if (Array.isArray(summaryNodeOutput.output)) {
          // 数组格式：每个元素是最终候选分子的完整评估结果
          for (const item of summaryNodeOutput.output) {
            if (item && typeof item === "object") {
              const rawSmiles = item.smiles || item.SMILES;
              if (rawSmiles) {
                const smiles = normalizeSmiles(rawSmiles);
                const mol: Partial<Molecule> = { smiles };
                
                // 从总结节点输出中提取完整的评估信息
                // 维度评分
                if (item.surfaceAnchoring !== undefined || item.energyLevel !== undefined || item.packingDensity !== undefined) {
                  const sa = typeof item.surfaceAnchoring === "number" ? item.surfaceAnchoring : undefined;
                  const el = typeof item.energyLevel === "number" ? item.energyLevel : undefined;
                  const pd = typeof item.packingDensity === "number" ? item.packingDensity : undefined;

                  // 总分必须按三维均值计算（与你的 system_prompt 一致），避免模型给出不一致的 total
                  const dims = [sa, el, pd].filter((v) => typeof v === "number") as number[];
                  const computedTotal = dims.length > 0 ? Math.round((dims.reduce((a, b) => a + b, 0) / dims.length) * 10) / 10 : 0;
                  const rawTotal =
                    typeof item.total_score === "number"
                      ? item.total_score
                      : (typeof item.score === "number" ? item.score : undefined);

                  mol.score = {
                    total: computedTotal || rawTotal || 0,
                    surfaceAnchoring: sa,
                    energyLevel: el,
                    packingDensity: pd,
                  };
                } else if (item.score !== undefined) {
                  mol.score = { total: typeof item.score === "number" ? item.score : 0 };
                } else if (item.opt_des && typeof item.opt_des === "string") {
                  // 尝试从opt_des解析
                  const dimScores = parseDimensionScoresFromOptDes(item.opt_des);
                  if (dimScores) {
                    mol.score = {
                      total: Math.round(((dimScores.surfaceAnchoring + dimScores.energyLevel + dimScores.packingDensity) / 3) * 10) / 10,
                      surfaceAnchoring: dimScores.surfaceAnchoring,
                      energyLevel: dimScores.energyLevel,
                      packingDensity: dimScores.packingDensity,
                    };
                  }
                }
                
                // 性质预测（HOMO/LUMO等）
                if (item.HOMO !== undefined || item.LUMO !== undefined || item.dipole !== undefined) {
                  mol.properties = {
                    HOMO: item.HOMO,
                    LUMO: item.LUMO,
                    DM: item.dipole || item.DM,
                  };
                }
                
                // 评估说明
                if (item.description || item.opt_des) {
                  mol.analysis = {
                    description: item.description || item.opt_des || "",
                    explanation: item.explanation || item.description || item.opt_des || "",
                  };
                }
                
                moleculeMap.set(smiles, mol);
              }
            }
          }
        } else if (typeof summaryNodeOutput.output === "string") {
          // 字符串格式：尝试解析SMILES和评估信息
          const summaryText = summaryNodeOutput.output;
          const smilesList = parseSMILESFromText(summaryText);
          
          // 如果文本中包含多个分子，需要为每个分子分别提取评估信息
          // 尝试按分子分组提取（通过SMILES附近的文本）
          for (const smiles of smilesList) {
            const normalizedSmiles = normalizeSmiles(smiles);
            const mol: Partial<Molecule> = { smiles: normalizedSmiles };
            
            // 找到该SMILES在文本中的位置，提取附近的评估信息
            const smilesIndex = summaryText.indexOf(smiles);
            if (smilesIndex >= 0) {
              // 提取该SMILES附近500字符的文本
              const contextStart = Math.max(0, smilesIndex - 100);
              const contextEnd = Math.min(summaryText.length, smilesIndex + smiles.length + 500);
              const contextText = summaryText.substring(contextStart, contextEnd);
              
              // 从上下文中提取评分信息
              const scoreMatch = contextText.match(/总分[：:]\s*(\d+\.?\d*)|总评分[：:]\s*(\d+\.?\d*)/i);
              const dimMatches = [
                contextText.match(/表面锚定[强度]*[：:]\s*(\d+\.?\d*)/i),
                contextText.match(/能级匹配[：:]\s*(\d+\.?\d*)/i),
                contextText.match(/膜致密度[：:]\s*(\d+\.?\d*)/i),
              ];
              
              if (dimMatches.some(m => m) || scoreMatch) {
                mol.score = {
                  total: scoreMatch ? parseFloat(scoreMatch[1] || scoreMatch[2] || "0") : 0,
                  surfaceAnchoring: dimMatches[0] ? parseFloat(dimMatches[0][1]) : undefined,
                  energyLevel: dimMatches[1] ? parseFloat(dimMatches[1][1]) : undefined,
                  packingDensity: dimMatches[2] ? parseFloat(dimMatches[2][1]) : undefined,
                };
              }
              
              // 提取性质预测
              const homoMatch = contextText.match(/HOMO[：:]\s*([-]?\d+\.?\d*)/i);
              const lumoMatch = contextText.match(/LUMO[：:]\s*([-]?\d+\.?\d*)/i);
              const dipoleMatch = contextText.match(/偶极矩[：:]\s*(\d+\.?\d*)/i);
              if (homoMatch || lumoMatch || dipoleMatch) {
                mol.properties = {
                  HOMO: homoMatch ? parseFloat(homoMatch[1]) : undefined,
                  LUMO: lumoMatch ? parseFloat(lumoMatch[1]) : undefined,
                  DM: dipoleMatch ? parseFloat(dipoleMatch[1]) : undefined,
                };
              }
              
              // 提取评估说明（该SMILES附近的描述文本）
              const descMatch = contextText.match(new RegExp(`${smiles.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]{0,300}([^\\n]{50,200})`, "i"));
              if (descMatch && descMatch[1]) {
                mol.analysis = {
                  description: descMatch[1].trim(),
                  explanation: descMatch[1].trim(),
                };
              }
            } else {
              // 如果找不到SMILES位置，从整个文本中提取通用信息
              const scoreMatch = summaryText.match(/总分[：:]\s*(\d+\.?\d*)/i);
              if (scoreMatch) {
                mol.score = { total: parseFloat(scoreMatch[1]) };
              }
            }
            
            moleculeMap.set(normalizedSmiles, mol);
          }
        }
      }
      
      // 如果从总结节点没提取到，尝试从其他上游节点提取（兼容性）
      if (moleculeMap.size === 0) {
        for (const [sourceId, sourceOutput] of Object.entries(endNodeOutput)) {
          if (!sourceOutput || typeof sourceOutput !== "object") continue;
          
          // 检查是否有output字段（数组格式的分子列表）
          if (sourceOutput.output && Array.isArray(sourceOutput.output)) {
            extractFromArray(sourceOutput.output);
          }
          
          // 检查是否有passed_items（最终通过的候选分子）
          if (sourceOutput.passed_items && Array.isArray(sourceOutput.passed_items)) {
            extractFromArray(sourceOutput.passed_items);
          }
          
          // 也检查直接包含smiles的对象
          if (sourceOutput.smiles || sourceOutput.SMILES) {
            tryCollectFromObject(sourceOutput);
          }
        }
      }
    }
  }
  
  // 如果没找到end节点或end节点没有输出，尝试从所有节点中查找end节点类型的输出
  if (moleculeMap.size === 0) {
    for (const [nodeId, nodeOutput] of Object.entries(nodeOutputs)) {
      // 检查节点类型（如果workflowGraph可用）
      if (workflowGraph && workflowGraph.nodes) {
        const node = workflowGraph.nodes.find((n: any) => n.id === nodeId);
        if (node && node.type === "end") {
          // 这是end节点，从它的output中提取
          if (nodeOutput && typeof nodeOutput === "object") {
            for (const [sourceId, sourceOutput] of Object.entries(nodeOutput)) {
              if (sourceOutput && typeof sourceOutput === "object") {
                if (sourceOutput.output && Array.isArray(sourceOutput.output)) {
                  extractFromArray(sourceOutput.output);
                }
                if (sourceOutput.passed_items && Array.isArray(sourceOutput.passed_items)) {
                  extractFromArray(sourceOutput.passed_items);
                }
              }
            }
          }
        }
      }
    }
  }
  
  const molecules: Partial<Molecule>[] = Array.from(moleculeMap.values()).map((m, i) => ({
    index: i + 1,
    ...m,
  }));
  
  // 附加图片URL
  for (const mol of molecules) {
    if (mol.smiles && imageUrlMap.has(mol.smiles)) {
      mol.imageUrl = imageUrlMap.get(mol.smiles);
    }
  }
  
  return molecules;
}

/**
 * 从工作流执行的node_outputs中提取分子数据
 * 只从循环节点的 output 字段中提取，忽略其他节点的输出
 */
export function extractMoleculesFromWorkflowResult(
  nodeOutputs: Record<string, any>
): Partial<Molecule>[] {
  const moleculeMap = new Map<string, Partial<Molecule>>();
  const imageUrlMap = new Map<string, string>(); // smiles -> imageUrl（如果输出里带了）

  const normalizeSmiles = (s: string) => s.trim();

  const tryCollectFromObject = (obj: any) => {
    if (!obj || typeof obj !== "object") return;

    // 常见字段：smiles / SMILES
    const rawSmiles = typeof obj.smiles === "string" ? obj.smiles : (typeof obj.SMILES === "string" ? obj.SMILES : null);
    if (rawSmiles) {
      const smiles = normalizeSmiles(rawSmiles);
      const existing = moleculeMap.get(smiles) || { smiles };
      
      // 解析分数：优先从 opt_des 解析三维分数
      if (obj.opt_des && typeof obj.opt_des === "string") {
        const dimScores = parseDimensionScoresFromOptDes(obj.opt_des);
        if (dimScores) {
          const totalScore = typeof obj.score === "number" ? obj.score : 
            (dimScores.surfaceAnchoring + dimScores.energyLevel + dimScores.packingDensity) / 3;
          existing.score = {
            total: totalScore,
            surfaceAnchoring: dimScores.surfaceAnchoring,
            energyLevel: dimScores.energyLevel,
            packingDensity: dimScores.packingDensity,
          };
        } else if (typeof obj.score === "number") {
          // 如果无法解析 opt_des，但有一个总分数，使用它
          existing.score = { total: obj.score };
        }
      } else if (typeof obj.score === "number") {
        existing.score = { total: obj.score };
      }
      
      // 解析分析描述
      if (obj.opt_des && typeof obj.opt_des === "string") {
        existing.analysis = {
          description: obj.opt_des,
          explanation: obj.opt_des,
        };
      }
      
      // 可选：如果对象自带图像URL
      if (typeof obj.imageUrl === "string" && obj.imageUrl.includes("/molecular_images/")) {
        imageUrlMap.set(smiles, obj.imageUrl);
        existing.imageUrl = obj.imageUrl;
      }
      if (typeof obj.image_url === "string" && obj.image_url.includes("/molecular_images/")) {
        imageUrlMap.set(smiles, obj.image_url);
        existing.imageUrl = obj.image_url;
      }
      // 可选：如果对象带 properties
      if (obj.properties && typeof obj.properties === "object") {
        existing.properties = { ...(existing.properties || {}), ...(obj.properties as MolecularProperties) };
      }
      
      moleculeMap.set(smiles, existing);
    }
  };

  // 从数组中提取分子
  const extractFromArray = (arr: any[]) => {
    for (const item of arr) {
      if (Array.isArray(item)) {
        extractFromArray(item);
      } else if (item && typeof item === "object") {
        tryCollectFromObject(item);
      }
    }
  };

  // 只从循环节点的 output 字段中提取
  // 循环节点的特征：有 passed_items 或 pending_items 字段，或者有 iterations 字段
  for (const [nodeId, nodeOutput] of Object.entries(nodeOutputs)) {
    if (!nodeOutput || typeof nodeOutput !== "object") continue;

    // 检查是否是循环节点：有 passed_items、pending_items 或 iterations 字段
    const isLoopNode = 
      "passed_items" in nodeOutput || 
      "pending_items" in nodeOutput || 
      "iterations" in nodeOutput;

    if (isLoopNode) {
      // 从循环节点的 output、passed_items、pending_items 中提取
      const sources = [
        nodeOutput.output,
        nodeOutput.passed_items,
        nodeOutput.pending_items,
      ].filter(Boolean);
      
      for (const source of sources) {
        if (Array.isArray(source)) {
          extractFromArray(source);
        } else if (source && typeof source === "object") {
          tryCollectFromObject(source);
        }
      }
    }
  }

  // 如果没提取到结构化 smiles，尝试退化到文本解析（兼容老的工具输出）
  if (moleculeMap.size === 0) {
    // 只从循环节点的 output 中尝试文本解析
    for (const [nodeId, nodeOutput] of Object.entries(nodeOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      
      const isLoopNode = 
        "passed_items" in nodeOutput || 
        "pending_items" in nodeOutput || 
        "iterations" in nodeOutput;

      if (isLoopNode && nodeOutput.output) {
        const outputText = typeof nodeOutput.output === "string" 
          ? nodeOutput.output 
          : JSON.stringify(nodeOutput.output);
        const smilesList = parseSMILESFromText(outputText);
        for (const smiles of smilesList) {
          const key = normalizeSmiles(smiles);
          if (!moleculeMap.has(key)) {
            moleculeMap.set(key, { smiles: key });
          }
        }
      }
    }
  }

  const molecules: Partial<Molecule>[] = Array.from(moleculeMap.values()).map((m, i) => ({
    index: i + 1,
    ...m,
  }));

  // 附加图片URL（如果有）
  for (const mol of molecules) {
    if (mol.smiles && imageUrlMap.has(mol.smiles)) {
      mol.imageUrl = imageUrlMap.get(mol.smiles);
    }
  }

  return molecules;
}

/**
 * 从 opt_des 文本中解析三维分数
 * 例如："表面锚定强度（7分）、能级匹配（8分）和膜致密度与稳定性（8分）"
 */
export function parseDimensionScoresFromOptDes(optDes: string): {
  surfaceAnchoring: number;
  energyLevel: number;
  packingDensity: number;
} | null {
  if (!optDes || typeof optDes !== "string") return null;

  const scores = {
    surfaceAnchoring: 0,
    energyLevel: 0,
    packingDensity: 0,
  };

  // 兜底：文案里只给出“均得分为 X / 三个维度均为 X”
  // 例：“三个维度均得分为7”“表面锚定强度、能级匹配和膜致密度与稳定性三个维度均得分为7”
  const allSameMatch =
    optDes.match(/(?:三个维度|三项|三个维度评分|三个维度均)(?:均)?(?:得分为|为)\s*([-+]?\d+(?:\.\d+)?)/) ||
    optDes.match(/(?:表面锚定|能级匹配|膜致密度)[^。\n]{0,50}三个维度[^。\n]{0,20}(?:均)?(?:得分为|为)\s*([-+]?\d+(?:\.\d+)?)/);
  if (allSameMatch) {
    const v = parseFloat(allSameMatch[1]) || 0;
    if (v > 0) {
      return { surfaceAnchoring: v, energyLevel: v, packingDensity: v };
    }
  }

  // 兼容多种输出格式（括号/冒号/空格、整数/小数、分/score）
  // 例：
  // - 表面锚定强度（7分）
  // - 表面锚定强度: 7.0
  // - 表面锚定: 0.7
  // - 能级匹配（8分） / 能级匹配: 8
  // - 膜致密度与稳定性（8分） / 膜致密度: 8.0
  const number = "([-+]?\\d+(?:\\.\\d+)?)";
  const scoreLabel = "(?:评分|得分)?";
  const surfaceMatch =
    // 允许 “表面锚定强度...（7分）” 中间插入少量描述文字
    optDes.match(new RegExp(`表面锚定(?:强度)?[^\\d]{0,20}[（(：:\\s]\\s*${scoreLabel}\\s*${number}\\s*(?:分|score)?\\s*[)）]?`, "i")) ||
    optDes.match(new RegExp(`表面锚定(?:强度)?[^\\d]{0,12}(?:得分为|为)\\s*${number}`, "i")) ||
    // 允许 “表面锚定强度8分 / 表面锚定8分” 这种无括号写法
    optDes.match(new RegExp(`表面锚定(?:强度)?[^\\d]{0,12}${scoreLabel}\\s*${number}\\s*(?:分|score)`, "i")) ||
    optDes.match(new RegExp(`surface\\s*anchoring\\s*[=:：\\s]\\s*${number}`, "i"));
  if (surfaceMatch) {
    scores.surfaceAnchoring = parseFloat(surfaceMatch[1]) || 0;
  }

  const energyMatch =
    // 允许 “能级匹配度优异（8分）” 这种中间带“度优异”的写法
    optDes.match(new RegExp(`能级匹配(?:度)?[^\\d]{0,20}[（(：:\\s]\\s*${scoreLabel}\\s*${number}\\s*(?:分|score)?\\s*[)）]?`, "i")) ||
    optDes.match(new RegExp(`能级匹配(?:度)?[^\\d]{0,12}(?:得分为|为)\\s*${number}`, "i")) ||
    // 允许 “能级匹配9分 / 能级匹配度9分 / 能级匹配评分9分” 这种无括号写法
    optDes.match(new RegExp(`能级匹配(?:度)?[^\\d]{0,12}${scoreLabel}\\s*${number}\\s*(?:分|score)`, "i")) ||
    optDes.match(new RegExp(`energy\\s*level\\s*(?:match(?:ing)?)?\\s*[=:：\\s]\\s*${number}`, "i"));
  if (energyMatch) {
    scores.energyLevel = parseFloat(energyMatch[1]) || 0;
  }

  const packingMatch =
    optDes.match(new RegExp(`膜致密度(?:与稳定性)?[^\\d]{0,20}[（(：:\\s]\\s*${scoreLabel}\\s*${number}\\s*(?:分|score)?\\s*[)）]?`, "i")) ||
    optDes.match(new RegExp(`膜致密度(?:与稳定性)?[^\\d]{0,12}(?:得分为|为)\\s*${number}`, "i")) ||
    // 允许 “膜致密度与稳定性8分 / 膜致密度8分 / 膜稳定性8分” 这种无括号写法
    optDes.match(new RegExp(`(?:膜致密度(?:与稳定性)?|膜稳定性)[^\\d]{0,12}${scoreLabel}\\s*${number}\\s*(?:分|score)`, "i")) ||
    optDes.match(new RegExp(`packing\\s*density\\s*[=:：\\s]\\s*${number}`, "i"));
  if (packingMatch) {
    scores.packingDensity = parseFloat(packingMatch[1]) || 0;
  }

  // 如果至少解析到一个分数，返回结果
  if (scores.surfaceAnchoring > 0 || scores.energyLevel > 0 || scores.packingDensity > 0) {
    return scores;
  }

  return null;
}

/**
 * 从 resolved_inputs.prompt 里解析三段 JSON 数组（表面锚定/能级/膜致密度）
 * 返回按分子 id 聚合的三维分数映射。
 *
 * 你提供的真实格式类似：
 * "##输入数据:\n[...surface...][...energy...][...packing...]"
 */
export function extractDimScoresFromResolvedInputsPrompt(promptText: string): Map<string | number, {
  surfaceAnchoring?: number;
  chemistryValidity?: number;
  defectPassivation?: number;
}> {
  const result = new Map<string | number, { surfaceAnchoring?: number; chemistryValidity?: number; defectPassivation?: number }>();
  if (!promptText || typeof promptText !== "string") return result;

  // 抽取所有顶层 JSON 数组片段（通过 [] 深度计数，避免正则匹配不平衡括号）
  const arrays: string[] = [];
  let start = -1;
  let depth = 0;
  for (let i = 0; i < promptText.length; i++) {
    const ch = promptText[i];
    if (ch === "[") {
      if (depth === 0) start = i;
      depth += 1;
    } else if (ch === "]") {
      if (depth > 0) depth -= 1;
      if (depth === 0 && start >= 0) {
        arrays.push(promptText.slice(start, i + 1));
        start = -1;
      }
    }
  }

  for (const arrText of arrays) {
    let arr: any;
    try {
      arr = JSON.parse(arrText);
    } catch {
      continue;
    }
    if (!Array.isArray(arr)) continue;

    for (const item of arr) {
      if (!item || typeof item !== "object") continue;
      // 维度趋势严格以 generation_id 为唯一匹配 key（不再使用 id / smiles 兜底）
      const key = (item.generation_id ?? item.generationId) as (string | number | undefined);
      const aspect = String(item.critic_aspect || item.criticAspect || "").trim();
      const score = typeof item.score === "number" ? item.score : parseFloat(String(item.score ?? ""));
      if (key === undefined || Number.isNaN(score)) continue;

      const existing = result.get(key) || {};
      // 支持中英文关键词匹配（转换为小写进行匹配，避免大小写问题）
      const aspectLower = aspect.toLowerCase();
      if (aspect.includes("表面锚定") || aspectLower.includes("anchoring") || aspectLower.includes("interface-binding")) {
        existing.surfaceAnchoring = score;
        console.log(`[extractDimScoresFromResolvedInputsPrompt] Molecule ${key}: set surfaceAnchoring=${score} from critic_aspect="${aspect}"`);
      } else if (aspect.includes("化学有效性") || aspectLower.includes("chemistry") || aspectLower.includes("chemistry-validity") || aspectLower.includes("structural sanity")) {
        existing.chemistryValidity = score;
        console.log(`[extractDimScoresFromResolvedInputsPrompt] Molecule ${key}: set chemistryValidity=${score} from critic_aspect="${aspect}"`);
      } else if (aspect.includes("缺陷评估") || aspect.includes("缺陷") || aspectLower.includes("defect") || aspectLower.includes("defect-passivation") || aspectLower.includes("interface-defect") || aspectLower.includes("passivation")) {
        existing.defectPassivation = score;
        console.log(`[extractDimScoresFromResolvedInputsPrompt] Molecule ${key}: set defectPassivation=${score} from critic_aspect="${aspect}"`);
      } else {
        console.warn(`[extractDimScoresFromResolvedInputsPrompt] Molecule ${key}: unknown critic_aspect="${aspect}", score=${score}`);
      }
      result.set(key, existing);
    }
  }

  return result;
}

/**
 * 格式化评分显示
 */
export function formatScore(score: number): string {
  return score.toFixed(1);
}

/**
 * 获取评分颜色
 */
export function getScoreColor(score: number): string {
  // 兼容 0-10 与 0-100 两种尺度
  if (score <= 10) {
    if (score >= 8) return "text-green-600 dark:text-green-400";
    if (score >= 6) return "text-yellow-600 dark:text-yellow-400";
    return "text-red-600 dark:text-red-400";
  }
  if (score >= 80) return "text-green-600 dark:text-green-400";
  if (score >= 60) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

/**
 * 迭代分析数据点（已废弃三维维度，只保留 total_best 用于兼容）
 */
export interface IterationDataPoint {
  iter: number;
  total_best: number;
  surfaceAnchoring_best: number;
  chemistryValidity_best: number;
  defectPassivation_best: number;
}

/**
 * 单个候选分子在各轮迭代的总分趋势数据点
 */
export interface CandidateTrendPoint {
  moleculeId: number | string;
  smiles?: string;
  scoresByIter: Map<number, number>; // iter -> total score
  /** 维度分数趋势（按迭代轮次） */
  dimensionScoresByIter: Map<number, {
    surfaceAnchoring?: number;
    chemistryValidity?: number;
    defectPassivation?: number;
  }>;
}

/**
 * Pareto 数据点
 */
export interface ParetoDataPoint {
  surfaceAnchoring?: number;
  chemistryValidity?: number;
  defectPassivation?: number;
  total: number;
  iter?: number;
  smiles?: string;
  moleculeId?: number | string;
}

/**
 * 迭代分析结果
 */
export interface IterationAnalytics {
  trend: IterationDataPoint[]; // 保留用于兼容，但不再使用三维字段
  paretoPoints: ParetoDataPoint[];
  /** 每个候选分子的总分趋势（按 moleculeId 分组） */
  candidateTrends: CandidateTrendPoint[];
  hasData: boolean;
}

/**
 * 从工作流 nodeOutputs 中提取迭代分析数据
 */
export function extractIterationAnalytics(
  nodeOutputs: Record<string, any>,
  molecules?: Partial<Molecule>[],
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>,
  iterationNodeOutputs?: Map<number, Record<string, any>>,
  workflowGraph?: { nodes: any[]; edges: any[] } | null
): IterationAnalytics {
  const trend: IterationDataPoint[] = [];
  const paretoPoints: ParetoDataPoint[] = [];
  const candidateTrends: CandidateTrendPoint[] = [];
  let hasData = false;

  // 尝试从当前迭代的节点输出中定位“汇总/评估结果”结构：
  // - outputs.output: [{id, score, smiles, opt_des}, ...]
  // - outputs.iteration_outputs: [{iteration, resolved_inputs:{prompt}, output:[...]} , ...]
  const getIterSummary = (iter: number): {
    candidates: Array<{ id: number | string; score: number; smiles?: string; opt_des?: string }>;
    dimsById: Map<string | number, { surfaceAnchoring?: number; chemistryValidity?: number; defectPassivation?: number }>;
  } => {
    const dimsById = new Map<string | number, { surfaceAnchoring?: number; chemistryValidity?: number; defectPassivation?: number }>();
    const candidates: Array<{ id: number | string; score: number; smiles?: string; opt_des?: string }> = [];

    const iterOutputs = iterationNodeOutputs?.get(iter);
    if (!iterOutputs) {
      console.log(`[extractIterationAnalytics] Iter ${iter}: no iterOutputs`);
      return { candidates, dimsById };
    }

    // 1) 先抓 candidates（通常在某个总结节点的 outputs.output 里）
    for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      const output = (nodeOutput as any).output;
      
      // 调试：打印节点输出结构
      if (output && (Array.isArray(output) || (typeof output === "object" && (output.id || output.generation_id)))) {
        console.log(`[extractIterationAnalytics] Iter ${iter}, Node ${nodeId}: found output`, {
          isArray: Array.isArray(output),
          hasId: !!(output.id || output.generation_id),
          keys: Array.isArray(output) ? `array[${output.length}]` : Object.keys(output),
        });
      }
      
      // 处理数组格式
      if (Array.isArray(output)) {
        for (const item of output) {
          if (!item || typeof item !== "object") continue;
          // 维度趋势严格以 generation_id 为唯一匹配 key（这里 candidates.id 实际承载 generation_id）
          // 总结节点可能使用 id 或 generation_id
          const id = (item as any).generation_id ?? (item as any).generationId ?? (item as any).id;
          const scoreNum = typeof (item as any).score === "number" ? (item as any).score : parseFloat(String((item as any).score ?? ""));
          if (id === undefined || Number.isNaN(scoreNum)) continue;
          candidates.push({ id, score: scoreNum, smiles: (item as any).smiles || (item as any).SMILES, opt_des: (item as any).opt_des });
        }
      } 
      // 处理单个对象格式（总结节点可能返回单个对象而不是数组）
      else if (output && typeof output === "object") {
        // 维度趋势严格以 generation_id 为唯一匹配 key（这里 candidates.id 实际承载 generation_id）
        // 总结节点可能使用 id 或 generation_id
        const id = (output as any).generation_id ?? (output as any).generationId ?? (output as any).id;
        const scoreNum = typeof (output as any).score === "number" ? (output as any).score : parseFloat(String((output as any).score ?? ""));
        if (id !== undefined && !Number.isNaN(scoreNum)) {
          candidates.push({ 
            id, 
            score: scoreNum, 
            smiles: (output as any).smiles || (output as any).SMILES, 
            opt_des: (output as any).opt_des 
          });
        }
      }
    }

    // 候选分子集合（key= generation_id）
    const candidateIdSet = new Set<string | number>(candidates.map((c) => c.id));
    
    // 调试：打印候选分子和ID集合
    console.log(`[extractIterationAnalytics] Iter ${iter}: candidates extracted:`, {
      count: candidates.length,
      ids: candidates.map(c => ({ id: c.id, score: c.score, hasSmiles: !!c.smiles })),
      candidateIdSet: Array.from(candidateIdSet),
    });

    // 2) 再抓 dims（优先从 iteration_outputs[iter].resolved_inputs.prompt 解析）
    for (const nodeOutput of Object.values(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      const iterationOutputs = (nodeOutput as any).iteration_outputs;
      if (Array.isArray(iterationOutputs)) {
        const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
        const promptText = entry?.resolved_inputs?.prompt;
        if (typeof promptText === "string" && promptText.length > 0) {
          const m = extractDimScoresFromResolvedInputsPrompt(promptText);
          if (m.size > 0) {
            // 合并到 dimsById（不直接返回，继续查找其他来源）
            for (const [genId, dims] of m.entries()) {
              if (!candidateIdSet.has(genId)) continue;
              const existing = dimsById.get(genId) || {};
              dimsById.set(genId, {
                surfaceAnchoring: dims.surfaceAnchoring ?? existing.surfaceAnchoring,
                chemistryValidity: dims.chemistryValidity ?? existing.chemistryValidity,
                defectPassivation: dims.defectPassivation ?? existing.defectPassivation,
              });
            }
          }
        }
      }
    }

    // 2.5) 从评估节点的直接输出中提取维度分数（如果 prompt 中没有找到或数据不完整）
    // 评估节点的 output 包含 critic_aspect 和 score 字段
      // 首先从当前迭代的 output 中提取
      for (const nodeOutput of Object.values(iterOutputs)) {
        if (!nodeOutput || typeof nodeOutput !== "object") continue;
        const output = (nodeOutput as any).output;
        
        // 处理数组格式
        if (Array.isArray(output)) {
          for (const item of output) {
            if (!item || typeof item !== "object") continue;
            // 维度趋势严格以 generation_id 为唯一匹配 key
            const id = (item as any).generation_id ?? (item as any).generationId;
            const criticAspect = String((item as any).critic_aspect || (item as any).criticAspect || "").trim();
            const score = typeof (item as any).score === "number" ? (item as any).score : parseFloat(String((item as any).score ?? ""));
            
            if (id === undefined || Number.isNaN(score) || !criticAspect) continue;
            if (!candidateIdSet.has(id)) continue;
          
          const existing = dimsById.get(id) || {};
          // 支持中英文关键词匹配（转换为小写进行匹配，避免大小写问题）
          const aspectLower = criticAspect.toLowerCase();
          if (criticAspect.includes("表面锚定") || aspectLower.includes("anchoring") || aspectLower.includes("interface-binding")) {
            existing.surfaceAnchoring = score;
            console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set surfaceAnchoring=${score} from critic_aspect="${criticAspect}"`);
          } else if (criticAspect.includes("化学有效性") || aspectLower.includes("chemistry") || aspectLower.includes("chemistry-validity") || aspectLower.includes("structural sanity")) {
            existing.chemistryValidity = score;
            console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set chemistryValidity=${score} from critic_aspect="${criticAspect}"`);
          } else if (criticAspect.includes("缺陷评估") || criticAspect.includes("缺陷") || aspectLower.includes("defect") || aspectLower.includes("defect-passivation") || aspectLower.includes("interface-defect") || aspectLower.includes("passivation")) {
            existing.defectPassivation = score;
            console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set defectPassivation=${score} from critic_aspect="${criticAspect}"`);
          } else {
            console.warn(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: unknown critic_aspect="${criticAspect}", score=${score}`);
          }
          dimsById.set(id, existing);
        }
      }
      // 处理单个对象格式（评估节点可能返回单个对象而不是数组）
      else if (output && typeof output === "object" && !Array.isArray(output)) {
        // 维度趋势严格以 generation_id 为唯一匹配 key
        const id = (output as any).generation_id ?? (output as any).generationId;
        const criticAspect = String((output as any).critic_aspect || (output as any).criticAspect || "").trim();
        const score = typeof (output as any).score === "number" ? (output as any).score : parseFloat(String((output as any).score ?? ""));
        
        if (id !== undefined && !Number.isNaN(score) && criticAspect && candidateIdSet.has(id)) {
          const existing = dimsById.get(id) || {};
          // 支持中英文关键词匹配（转换为小写进行匹配，避免大小写问题）
          const aspectLower = criticAspect.toLowerCase();
          if (criticAspect.includes("表面锚定") || aspectLower.includes("anchoring") || aspectLower.includes("interface-binding")) {
            existing.surfaceAnchoring = score;
            console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set surfaceAnchoring=${score} from critic_aspect="${criticAspect}" (single object)`);
          } else if (criticAspect.includes("化学有效性") || aspectLower.includes("chemistry") || aspectLower.includes("chemistry-validity") || aspectLower.includes("structural sanity")) {
            existing.chemistryValidity = score;
            console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set chemistryValidity=${score} from critic_aspect="${criticAspect}" (single object)`);
          } else if (criticAspect.includes("缺陷评估") || criticAspect.includes("缺陷") || aspectLower.includes("defect") || aspectLower.includes("defect-passivation") || aspectLower.includes("interface-defect") || aspectLower.includes("passivation")) {
            existing.defectPassivation = score;
            console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set defectPassivation=${score} from critic_aspect="${criticAspect}" (single object)`);
          } else {
            console.warn(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: unknown critic_aspect="${criticAspect}", score=${score} (single object)`);
          }
          dimsById.set(id, existing);
        }
      }
      
      // 也从 iteration_outputs 数组中提取（评估节点的历史输出）
      const iterationOutputs = (nodeOutput as any).iteration_outputs;
      if (Array.isArray(iterationOutputs)) {
        const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
        if (entry) {
          const entryOutput = entry.output;
          // 处理数组格式
          if (Array.isArray(entryOutput)) {
            for (const item of entryOutput) {
              if (!item || typeof item !== "object") continue;
              // 维度趋势严格以 generation_id 为唯一匹配 key
              const id = (item as any).generation_id ?? (item as any).generationId;
              const criticAspect = String((item as any).critic_aspect || (item as any).criticAspect || "").trim();
              const score = typeof (item as any).score === "number" ? (item as any).score : parseFloat(String((item as any).score ?? ""));
              
              if (id === undefined || Number.isNaN(score) || !criticAspect) continue;
              if (!candidateIdSet.has(id)) continue;
              
              const existing = dimsById.get(id) || {};
              // 支持中英文关键词匹配（转换为小写进行匹配，避免大小写问题）
              const aspectLower = criticAspect.toLowerCase();
              if (criticAspect.includes("表面锚定") || aspectLower.includes("anchoring") || aspectLower.includes("interface-binding")) {
                existing.surfaceAnchoring = score;
                console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set surfaceAnchoring=${score} from critic_aspect="${criticAspect}"`);
              } else if (criticAspect.includes("化学有效性") || aspectLower.includes("chemistry") || aspectLower.includes("chemistry-validity") || aspectLower.includes("structural sanity")) {
                existing.chemistryValidity = score;
                console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set chemistryValidity=${score} from critic_aspect="${criticAspect}"`);
              } else if (criticAspect.includes("缺陷评估") || criticAspect.includes("缺陷") || aspectLower.includes("defect") || aspectLower.includes("defect-passivation") || aspectLower.includes("interface-defect") || aspectLower.includes("passivation")) {
                existing.defectPassivation = score;
                console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set defectPassivation=${score} from critic_aspect="${criticAspect}"`);
              } else {
                console.warn(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: unknown critic_aspect="${criticAspect}", score=${score}`);
              }
              dimsById.set(id, existing);
            }
          }
          // 处理单个对象格式
          else if (entryOutput && typeof entryOutput === "object" && !Array.isArray(entryOutput)) {
            // 维度趋势严格以 generation_id 为唯一匹配 key
            const id = (entryOutput as any).generation_id ?? (entryOutput as any).generationId;
            const criticAspect = String((entryOutput as any).critic_aspect || (entryOutput as any).criticAspect || "").trim();
            const score = typeof (entryOutput as any).score === "number" ? (entryOutput as any).score : parseFloat(String((entryOutput as any).score ?? ""));
            
            if (id !== undefined && !Number.isNaN(score) && criticAspect && candidateIdSet.has(id)) {
              const existing = dimsById.get(id) || {};
              // 支持中英文关键词匹配（转换为小写进行匹配，避免大小写问题）
              const aspectLower = criticAspect.toLowerCase();
              if (criticAspect.includes("表面锚定") || aspectLower.includes("anchoring") || aspectLower.includes("interface-binding")) {
                existing.surfaceAnchoring = score;
                console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set surfaceAnchoring=${score} from critic_aspect="${criticAspect}" (iteration_outputs, single object)`);
              } else if (criticAspect.includes("化学有效性") || aspectLower.includes("chemistry") || aspectLower.includes("chemistry-validity") || aspectLower.includes("structural sanity")) {
                existing.chemistryValidity = score;
                console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set chemistryValidity=${score} from critic_aspect="${criticAspect}" (iteration_outputs, single object)`);
              } else if (criticAspect.includes("缺陷评估") || criticAspect.includes("缺陷") || aspectLower.includes("defect") || aspectLower.includes("defect-passivation") || aspectLower.includes("interface-defect") || aspectLower.includes("passivation")) {
                existing.defectPassivation = score;
                console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: set defectPassivation=${score} from critic_aspect="${criticAspect}" (iteration_outputs, single object)`);
              } else {
                console.warn(`[extractIterationAnalytics] Iter ${iter}, Molecule ${id}: unknown critic_aspect="${criticAspect}", score=${score} (iteration_outputs, single object)`);
              }
              dimsById.set(id, existing);
            }
          }
        }
      }
    }

    // 3) 兜底：从 candidates 的 opt_des 文本解析维度分（不如 prompt 可靠）
    // 注意：parseDimensionScoresFromOptDes 返回的是旧维度名称，但这里我们只使用 surfaceAnchoring
    // chemistryValidity 和 defectPassivation 需要从评估节点输出中提取
    for (const c of candidates) {
      if (typeof c.opt_des === "string") {
        const ds = parseDimensionScoresFromOptDes(c.opt_des);
        if (ds) {
          const existing = dimsById.get(c.id) || {};
          dimsById.set(c.id, {
            surfaceAnchoring: ds.surfaceAnchoring || existing.surfaceAnchoring,
            chemistryValidity: existing.chemistryValidity, // 不从 opt_des 解析，只从评估节点提取
            defectPassivation: existing.defectPassivation, // 不从 opt_des 解析，只从评估节点提取
          });
        }
      }
    }

    // 调试：打印提取结果
    if (candidates.length > 0 || dimsById.size > 0) {
      console.log(`[extractIterationAnalytics] Iter ${iter}: extracted`, {
        candidatesCount: candidates.length,
        dimsCount: dimsById.size,
        candidateIds: candidates.map(c => c.id),
        dimIds: Array.from(dimsById.keys()),
        dimsDetails: Array.from(dimsById.entries()).map(([id, dims]) => ({
          id,
          surfaceAnchoring: dims.surfaceAnchoring,
          chemistryValidity: dims.chemistryValidity,
          defectPassivation: dims.defectPassivation,
        })),
        // 检查ID匹配情况
        idMismatch: candidates.filter(c => !dimsById.has(c.id)).map(c => ({ id: c.id, score: c.score })),
      });
    } else {
      console.warn(`[extractIterationAnalytics] Iter ${iter}: NO candidates or dims extracted!`, {
        iterOutputsKeys: Object.keys(iterOutputs || {}),
      });
    }
    
    return { candidates, dimsById };
  };

  // 优先使用 iterationSnapshots（如果提供）
  if (iterationSnapshots && iterationSnapshots.length > 0) {
    console.log(`[extractIterationAnalytics] Using iterationSnapshots, count: ${iterationSnapshots.length}`);
    for (const snapshot of iterationSnapshots) {
      const iter = snapshot.iter;

      const { candidates, dimsById } = getIterSummary(iter);
      
      console.log(`[extractIterationAnalytics] Iter ${iter} summary:`, {
        candidatesCount: candidates.length,
        dimsCount: dimsById.size,
        snapshotBest: snapshot.best?.score?.total,
      });

      // 关键：趋势图的 total_best 必须从 node_end/总结节点每轮迭代给出的 score（确定的）
      // 而不是从多个候选里算统计值
      let total_best = 0;
      let surfaceAnchoring_best = 0;
      let chemistryValidity_best = 0;
      let defectPassivation_best = 0;

      // 优先从总结节点的 output 里取每轮迭代确定的 score（这是 node_end 给出的）
      if (candidates.length > 0) {
        // 取 score 最高的作为 best（这是总结节点给出的确定总分）
        const best = candidates.length > 0 
          ? candidates.reduce((a, b) => {
              if (!a) return b;
              return b.score > a.score ? b : a;
            }, candidates[0] as { id: number | string; score: number; smiles?: string; opt_des?: string })
          : null;
        if (best) {
          total_best = best.score || 0; // 直接用总结节点给出的 score，不重新计算
          const dims = dimsById.get(best.id);
          surfaceAnchoring_best = dims?.surfaceAnchoring ?? 0;
          chemistryValidity_best = dims?.chemistryValidity ?? 0;
          defectPassivation_best = dims?.defectPassivation ?? 0;
        }
      } else if (snapshot.best?.score) {
        // 兜底：没有 candidates 时，用 snapshot.best（可能缺维度分）
        // 注意：snapshot.best.score 可能还是旧的字段名，需要兼容处理
        const bestScore = snapshot.best.score as any;
        total_best = bestScore.total || 0;
        surfaceAnchoring_best = bestScore.surfaceAnchoring ?? 0;
        chemistryValidity_best = bestScore.chemistryValidity ?? 0;
        defectPassivation_best = bestScore.defectPassivation ?? 0;
      }
      
      // 添加到趋势数据（total_best 来自 node_end/总结节点确定的 score）
      trend.push({
        iter,
        total_best,
        surfaceAnchoring_best,
        chemistryValidity_best,
        defectPassivation_best,
      });
      
      // 添加到 Pareto 点集：使用 candidates + dimsById（按分子 id 对齐）
      // 每个候选的 total 也是从总结节点给出的 score（确定的）
      for (const c of candidates) {
        const dims = dimsById.get(c.id);
        // 只有当维度分数存在时才使用，避免0值覆盖undefined
        // 使用 undefined 而不是 0，这样在构建 dimensionScoresByIter 时可以区分"数据缺失"和"有效0值"
        const paretoPoint = {
          surfaceAnchoring: dims?.surfaceAnchoring,
          chemistryValidity: dims?.chemistryValidity,
          defectPassivation: dims?.defectPassivation,
          total: c.score || 0, // 直接用总结节点给出的 score
          iter,
          smiles: c.smiles,
          moleculeId: c.id,
        };
        
        // 调试：打印维度分数提取情况
        if (dims && (dims.surfaceAnchoring !== undefined || dims.chemistryValidity !== undefined || dims.defectPassivation !== undefined)) {
          console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${c.id}: found dims`, dims);
        } else {
          console.log(`[extractIterationAnalytics] Iter ${iter}, Molecule ${c.id}: no dims found, dimsById size:`, dimsById.size, 'keys:', Array.from(dimsById.keys()));
        }
        
        paretoPoints.push(paretoPoint);
      }

      if (total_best > 0) {
        hasData = true;
      }
    }
    
    // 构建每个候选分子的总分趋势和维度分数趋势（跨迭代）
    const candidateTrendMap = new Map<number | string, Map<number, number>>();
    const candidateDimensionMap = new Map<number | string, Map<number, {
      surfaceAnchoring?: number;
      chemistryValidity?: number;
      defectPassivation?: number;
    }>>();
    
    for (const p of paretoPoints) {
      if (typeof p.iter !== "number" || p.moleculeId === undefined) continue;
      const total = typeof p.total === "number" ? p.total : 0;
      
      // 构建总分趋势
      if (total > 0) {
        if (!candidateTrendMap.has(p.moleculeId)) {
          candidateTrendMap.set(p.moleculeId, new Map());
        }
        candidateTrendMap.get(p.moleculeId)!.set(p.iter, total);
      }
      
      // 构建维度分数趋势
      if (!candidateDimensionMap.has(p.moleculeId)) {
        candidateDimensionMap.set(p.moleculeId, new Map());
      }
      const dimensionMap = candidateDimensionMap.get(p.moleculeId)!;
      // 只有当维度分数存在时才设置（避免undefined覆盖已有值）
      const existing = dimensionMap.get(p.iter) || {};
      const newDims = {
        surfaceAnchoring: p.surfaceAnchoring !== undefined && p.surfaceAnchoring !== null
          ? p.surfaceAnchoring 
          : existing.surfaceAnchoring,
        chemistryValidity: p.chemistryValidity !== undefined && p.chemistryValidity !== null
          ? p.chemistryValidity 
          : existing.chemistryValidity,
        defectPassivation: p.defectPassivation !== undefined && p.defectPassivation !== null
          ? p.defectPassivation 
          : existing.defectPassivation,
      };
      
      // 调试：打印维度分数设置情况
      if (p.surfaceAnchoring !== undefined || p.chemistryValidity !== undefined || p.defectPassivation !== undefined) {
        console.log(`[extractIterationAnalytics] Setting dims for molecule ${p.moleculeId}, iter ${p.iter}:`, newDims);
      }
      
      dimensionMap.set(p.iter, newDims);
    }
    
    // 获取所有迭代轮次（用于补齐缺失的数据点）
    const allIters = new Set<number>();
    if (iterationSnapshots && iterationSnapshots.length > 0) {
      iterationSnapshots.forEach(s => allIters.add(s.iter));
    } else {
      trend.forEach(t => allIters.add(t.iter));
    }
    const sortedIters = Array.from(allIters).sort((a, b) => a - b);
    
    // 构建分子ID到SMILES的映射（用于在snapshots中查找）
    const moleculeIdToSmiles = new Map<number | string, string>();
    for (const p of paretoPoints) {
      if (p.moleculeId && p.smiles) {
        moleculeIdToSmiles.set(p.moleculeId, p.smiles);
      }
    }
    
    for (const [moleculeId, scoresByIter] of candidateTrendMap.entries()) {
      const firstPoint = Array.from(scoresByIter.entries())[0];
      if (!firstPoint) continue;
      
      const dimensionScoresByIter = candidateDimensionMap.get(moleculeId) || new Map();
      
      // 自动补齐逻辑：保持趋势连续性
      // 优先使用"达到要求"的迭代数据，如果没有达到要求的迭代，则使用最后一次有数据的迭代
      const allScores = Array.from(scoresByIter.entries()).sort((a, b) => a[0] - b[0]);
      
      // 首先尝试找到首次达到要求的迭代
      let qualifiedIter: number | null = null;
      let qualifiedScore: number | null = null;
      let qualifiedDimScores: { surfaceAnchoring?: number; chemistryValidity?: number; defectPassivation?: number } = {};
      
      for (const [iter, score] of allScores) {
        // 判断是否达到要求：分数 >= 7 或在 passed 列表中
        let isQualified = score >= 7;
        if (!isQualified && iterationSnapshots && iterationSnapshots.length > 0) {
          const snapshot = iterationSnapshots.find(s => s.iter === iter);
          if (snapshot) {
            const smiles = moleculeIdToSmiles.get(moleculeId);
            if (smiles) {
              // 检查该分子是否在 passed 列表中
              // 维度趋势严格以 generation_id 为唯一匹配 key
              isQualified = snapshot.passed.some(m => (m as any).generation_id === moleculeId);
            }
          }
        }
        
        // 如果达到要求，记录该迭代的分数和维度分数
        if (isQualified) {
          qualifiedIter = iter;
          qualifiedScore = score;
          qualifiedDimScores = dimensionScoresByIter.get(iter) || {};
          break; // 找到首次达到要求的迭代后退出
        }
      }
      
      // 如果没有找到达到要求的迭代，使用最后一次有数据的迭代
      if (qualifiedIter === null && allScores.length > 0) {
        const lastScore = allScores[allScores.length - 1];
        if (lastScore) {
          qualifiedIter = lastScore[0];
          qualifiedScore = lastScore[1];
          qualifiedDimScores = dimensionScoresByIter.get(qualifiedIter) || {};
        }
      }
      
      // 补齐后续所有缺失迭代的数据点（保持趋势连续性）
      if (qualifiedIter !== null && qualifiedScore !== null) {
        for (const iter of sortedIters) {
          // 如果该迭代已经有数据，跳过
          if (scoresByIter.has(iter)) continue;
          
          // 如果该迭代在最后一次有数据的迭代之后，则补齐
          if (iter > qualifiedIter) {
            scoresByIter.set(iter, qualifiedScore);
            
            // 同时补齐维度分数（即使维度分数为空对象，也要补齐以保持结构一致）
            dimensionScoresByIter.set(iter, { ...qualifiedDimScores });
          }
        }
      }
      
      candidateTrends.push({
        moleculeId,
        smiles: paretoPoints.find((p) => p.moleculeId === moleculeId)?.smiles,
        scoresByIter,
        dimensionScoresByIter,
      });
    }
    
    return {
      trend,
      paretoPoints,
      candidateTrends,
      hasData: trend.length > 0 || candidateTrends.length > 0,
    };
  }

  // 如果没有 iterationSnapshots，回退到原来的逻辑
  // 查找循环节点的 iterations
  for (const [nodeId, nodeOutput] of Object.entries(nodeOutputs)) {
    if (!nodeOutput || typeof nodeOutput !== "object") continue;

    // 检查是否是循环节点
    const isLoopNode =
      "passed_items" in nodeOutput ||
      "pending_items" in nodeOutput ||
      "iterations" in nodeOutput;

    if (isLoopNode) {
      // 尝试从 iterations 字段提取
      if (nodeOutput.iterations && Array.isArray(nodeOutput.iterations)) {
        hasData = true;
        nodeOutput.iterations.forEach((iterData: any, idx: number) => {
          const iter = idx + 1;
          
          // 尝试从迭代数据中提取分子和评分
          let iterMolecules: Partial<Molecule>[] = [];
          if (Array.isArray(iterData)) {
            iterMolecules = iterData;
          } else if (iterData.molecules && Array.isArray(iterData.molecules)) {
            iterMolecules = iterData.molecules;
          } else if (iterData.output && Array.isArray(iterData.output)) {
            iterMolecules = iterData.output;
          } else if (iterData.output && typeof iterData.output === "object" && (iterData.output.smiles || iterData.output.SMILES)) {
            // 处理单个对象格式（生成节点可能返回单个对象而不是数组）
            iterMolecules = [iterData.output];
          }

          // 计算该迭代的最佳值
          let total_best = 0;
          let surfaceAnchoring_best = 0;
          let chemistryValidity_best = 0;
          let defectPassivation_best = 0;

          if (iterMolecules.length > 0) {
            // 找到总分最高的分子
            const bestMol = iterMolecules.reduce((best, mol) => {
              if (!best) return mol;
              const bestScore = best.score?.total || 0;
              const molScore = mol.score?.total || 0;
              return molScore > bestScore ? mol : best;
            }, iterMolecules[0] as Partial<Molecule> | undefined);

            if (bestMol) {
              total_best = bestMol.score?.total || 0;
              surfaceAnchoring_best = bestMol.score?.surfaceAnchoring ?? 0;
              // 注意：molecule.score 可能还是旧的字段名，需要兼容处理
              const score = bestMol.score as any;
              chemistryValidity_best = score.chemistryValidity ?? 0;
              defectPassivation_best = score.defectPassivation ?? 0;
            }

            // 添加到 Pareto 点集
            iterMolecules.forEach((mol) => {
              if (mol.score) {
                const moleculeId = (mol as any).id ?? (mol as any).moleculeId ?? mol.index ?? mol.smiles;
                // 注意：molecule.score 可能还是旧的字段名，需要兼容处理
                const score = mol.score as any;
                paretoPoints.push({
                  surfaceAnchoring: score.surfaceAnchoring ?? 0,
                  chemistryValidity: score.chemistryValidity ?? 0,
                  defectPassivation: score.defectPassivation ?? 0,
                  total: mol.score.total || 0,
                  iter,
                  smiles: mol.smiles,
                  moleculeId,
                });
              }
            });
          }

          trend.push({
            iter,
            total_best,
            surfaceAnchoring_best,
            chemistryValidity_best,
            defectPassivation_best,
          });
        });
      }
    }
  }

  // 如果没有从 iterations 提取到数据，尝试从最终 molecules 生成一个数据点
  if (!hasData && molecules && molecules.length > 0) {
    const bestMol = molecules.reduce((best, mol) => {
      if (!best) return mol;
      const bestScore = best.score?.total || 0;
      const molScore = mol.score?.total || 0;
      return molScore > bestScore ? mol : best;
    }, molecules[0] as Partial<Molecule> | undefined);

    if (bestMol && bestMol.score) {
      // 注意：molecule.score 可能还是旧的字段名，需要兼容处理
      const score = bestMol.score as any;
      trend.push({
        iter: 1,
        total_best: bestMol.score.total || 0,
        surfaceAnchoring_best: score.surfaceAnchoring ?? 0,
        chemistryValidity_best: score.chemistryValidity ?? 0,
        defectPassivation_best: score.defectPassivation ?? 0,
      });

      molecules.forEach((mol) => {
        if (mol.score) {
          const moleculeId = (mol as any).id ?? (mol as any).moleculeId ?? mol.index ?? mol.smiles;
          // 注意：molecule.score 可能还是旧的字段名，需要兼容处理
          const score = mol.score as any;
          paretoPoints.push({
            surfaceAnchoring: score.surfaceAnchoring ?? 0,
            chemistryValidity: score.chemistryValidity ?? 0,
            defectPassivation: score.defectPassivation ?? 0,
            total: mol.score.total || 0,
            smiles: mol.smiles,
            moleculeId,
          });
        }
      });
    }
  }

  // 构建每个候选分子的总分趋势和维度分数趋势（跨迭代）- 回退逻辑
  const candidateTrendMap = new Map<number | string, Map<number, number>>();
    const candidateDimensionMap = new Map<number | string, Map<number, {
      surfaceAnchoring?: number;
      chemistryValidity?: number;
      defectPassivation?: number;
    }>>();
  
  for (const p of paretoPoints) {
    if (typeof p.iter !== "number" || p.moleculeId === undefined) continue;
    const total = typeof p.total === "number" ? p.total : 0;
    
    // 构建总分趋势
    if (total > 0) {
      if (!candidateTrendMap.has(p.moleculeId)) {
        candidateTrendMap.set(p.moleculeId, new Map());
      }
      candidateTrendMap.get(p.moleculeId)!.set(p.iter, total);
    }
    
    // 构建维度分数趋势
    if (!candidateDimensionMap.has(p.moleculeId)) {
      candidateDimensionMap.set(p.moleculeId, new Map());
    }
    const dimensionMap = candidateDimensionMap.get(p.moleculeId)!;
    const existing = dimensionMap.get(p.iter) || {};
    const sa = p.surfaceAnchoring;
    const cv = p.chemistryValidity;
    const dp = p.defectPassivation;
    dimensionMap.set(p.iter, {
      surfaceAnchoring: (sa !== undefined && sa !== null && sa > 0) 
        ? sa 
        : existing.surfaceAnchoring,
      chemistryValidity: (cv !== undefined && cv !== null && cv > 0)
        ? cv 
        : existing.chemistryValidity,
      defectPassivation: (dp !== undefined && dp !== null && dp > 0)
        ? dp 
        : existing.defectPassivation,
    });
  }
  
  // 获取所有迭代轮次（用于补齐缺失的数据点）
  const allItersFallback = new Set<number>();
  paretoPoints.forEach(p => {
    if (typeof p.iter === "number") {
      allItersFallback.add(p.iter);
    }
  });
  const sortedItersFallback = Array.from(allItersFallback).sort((a, b) => a - b);
  
  for (const [moleculeId, scoresByIter] of candidateTrendMap.entries()) {
    const firstPoint = Array.from(scoresByIter.entries())[0];
    if (!firstPoint) continue;
    
    const dimensionScoresByIter = candidateDimensionMap.get(moleculeId) || new Map();
    
    // 自动补齐逻辑：保持趋势连续性（回退逻辑：使用最后一次有数据的迭代）
    const allScores = Array.from(scoresByIter.entries()).sort((a, b) => a[0] - b[0]);
    if (allScores.length > 0) {
      const lastScore = allScores[allScores.length - 1];
      if (lastScore) {
        const lastIter = lastScore[0];
        const lastScoreValue = lastScore[1];
        const lastDimScores = dimensionScoresByIter.get(lastIter) || {};
        
        // 补齐后续所有缺失迭代的数据点
        for (const iter of sortedItersFallback) {
          // 如果该迭代已经有数据，跳过
          if (scoresByIter.has(iter)) continue;
          
          // 如果该迭代在最后一次有数据的迭代之后，则补齐
          if (iter > lastIter) {
            scoresByIter.set(iter, lastScoreValue);
            // 同时补齐维度分数
            dimensionScoresByIter.set(iter, { ...lastDimScores });
          }
        }
      }
    }
    
    candidateTrends.push({
      moleculeId,
      smiles: paretoPoints.find((p) => p.moleculeId === moleculeId)?.smiles,
      scoresByIter,
      dimensionScoresByIter,
    });
  }

  return {
    trend,
    paretoPoints,
    candidateTrends,
    hasData: trend.length > 0 || candidateTrends.length > 0,
  };
}

