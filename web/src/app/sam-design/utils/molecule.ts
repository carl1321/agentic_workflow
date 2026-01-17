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
  const surfaceMatch =
    // 允许 “表面锚定强度...（7分）” 中间插入少量描述文字
    optDes.match(new RegExp(`表面锚定(?:强度)?[^\\d]{0,20}[（(：:\\s]\\s*${number}\\s*(?:分|score)?\\s*[)）]?`, "i")) ||
    optDes.match(new RegExp(`表面锚定(?:强度)?[^\\d]{0,12}(?:得分为|为)\\s*${number}`, "i")) ||
    optDes.match(new RegExp(`surface\\s*anchoring\\s*[=:：\\s]\\s*${number}`, "i"));
  if (surfaceMatch) {
    scores.surfaceAnchoring = parseFloat(surfaceMatch[1]) || 0;
  }

  const energyMatch =
    // 允许 “能级匹配度优异（8分）” 这种中间带“度优异”的写法
    optDes.match(new RegExp(`能级匹配[^\\d]{0,20}[（(：:\\s]\\s*${number}\\s*(?:分|score)?\\s*[)）]?`, "i")) ||
    optDes.match(new RegExp(`能级匹配[^\\d]{0,12}(?:得分为|为)\\s*${number}`, "i")) ||
    optDes.match(new RegExp(`energy\\s*level\\s*(?:match(?:ing)?)?\\s*[=:：\\s]\\s*${number}`, "i"));
  if (energyMatch) {
    scores.energyLevel = parseFloat(energyMatch[1]) || 0;
  }

  const packingMatch =
    optDes.match(new RegExp(`膜致密度(?:与稳定性)?[^\\d]{0,20}[（(：:\\s]\\s*${number}\\s*(?:分|score)?\\s*[)）]?`, "i")) ||
    optDes.match(new RegExp(`膜致密度(?:与稳定性)?[^\\d]{0,12}(?:得分为|为)\\s*${number}`, "i")) ||
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
  energyLevel?: number;
  packingDensity?: number;
}> {
  const result = new Map<string | number, { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number }>();
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
      const id = item.id as (string | number | undefined);
      const aspect = String(item.critic_aspect || item.criticAspect || "").trim();
      const score = typeof item.score === "number" ? item.score : parseFloat(String(item.score ?? ""));
      if (id === undefined || Number.isNaN(score)) continue;

      const existing = result.get(id) || {};
      if (aspect.includes("表面锚定")) {
        existing.surfaceAnchoring = score;
      } else if (aspect.includes("能级")) {
        existing.energyLevel = score;
      } else if (aspect.includes("膜致密度")) {
        existing.packingDensity = score;
      }
      result.set(id, existing);
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
  energyLevel_best: number;
  packingDensity_best: number;
}

/**
 * 单个候选分子在各轮迭代的总分趋势数据点
 */
export interface CandidateTrendPoint {
  moleculeId: number | string;
  smiles?: string;
  scoresByIter: Map<number, number>; // iter -> total score
}

/**
 * Pareto 数据点
 */
export interface ParetoDataPoint {
  energyLevel: number;
  surfaceAnchoring: number;
  packingDensity: number;
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
    dimsById: Map<string | number, { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number }>;
  } => {
    const dimsById = new Map<string | number, { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number }>();
    const candidates: Array<{ id: number | string; score: number; smiles?: string; opt_des?: string }> = [];

    const iterOutputs = iterationNodeOutputs?.get(iter);
    if (!iterOutputs) return { candidates, dimsById };

    // 1) 先抓 candidates（通常在某个总结节点的 outputs.output 里）
    for (const nodeOutput of Object.values(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      if (Array.isArray((nodeOutput as any).output)) {
        for (const item of (nodeOutput as any).output) {
          if (!item || typeof item !== "object") continue;
          const id = (item as any).id;
          const scoreNum = typeof (item as any).score === "number" ? (item as any).score : parseFloat(String((item as any).score ?? ""));
          if (id === undefined || Number.isNaN(scoreNum)) continue;
          candidates.push({ id, score: scoreNum, smiles: (item as any).smiles || (item as any).SMILES, opt_des: (item as any).opt_des });
        }
      }
    }

    // 2) 再抓 dims（优先从 iteration_outputs[iter].resolved_inputs.prompt 解析）
    for (const nodeOutput of Object.values(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      const iterationOutputs = (nodeOutput as any).iteration_outputs;
      if (Array.isArray(iterationOutputs)) {
        const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
        const promptText = entry?.resolved_inputs?.prompt;
        if (typeof promptText === "string" && promptText.length > 0) {
          const m = extractDimScoresFromResolvedInputsPrompt(promptText);
          if (m.size > 0) return { candidates, dimsById: m };
        }
      }
    }

    // 3) 兜底：从 candidates 的 opt_des 文本解析维度分（不如 prompt 可靠）
    for (const c of candidates) {
      if (typeof c.opt_des === "string") {
        const ds = parseDimensionScoresFromOptDes(c.opt_des);
        if (ds) {
          dimsById.set(c.id, {
            surfaceAnchoring: ds.surfaceAnchoring,
            energyLevel: ds.energyLevel,
            packingDensity: ds.packingDensity,
          });
        }
      }
    }

    return { candidates, dimsById };
  };

  // 优先使用 iterationSnapshots（如果提供）
  if (iterationSnapshots && iterationSnapshots.length > 0) {
    for (const snapshot of iterationSnapshots) {
      const iter = snapshot.iter;

      const { candidates, dimsById } = getIterSummary(iter);

      // 关键：趋势图的 total_best 必须从 node_end/总结节点每轮迭代给出的 score（确定的）
      // 而不是从多个候选里算统计值
      let total_best = 0;
      let surfaceAnchoring_best = 0;
      let energyLevel_best = 0;
      let packingDensity_best = 0;

      // 优先从总结节点的 output 里取每轮迭代确定的 score（这是 node_end 给出的）
      if (candidates.length > 0) {
        // 取 score 最高的作为 best（这是总结节点给出的确定总分）
        const best = candidates.reduce((a, b) => (b.score > a.score ? b : a), candidates[0]);
        total_best = best.score || 0; // 直接用总结节点给出的 score，不重新计算
        const dims = dimsById.get(best.id);
        surfaceAnchoring_best = dims?.surfaceAnchoring || 0;
        energyLevel_best = dims?.energyLevel || 0;
        packingDensity_best = dims?.packingDensity || 0;
      } else if (snapshot.best?.score) {
        // 兜底：没有 candidates 时，用 snapshot.best（可能缺维度分）
        total_best = snapshot.best.score.total || 0;
        surfaceAnchoring_best = snapshot.best.score.surfaceAnchoring || 0;
        energyLevel_best = snapshot.best.score.energyLevel || 0;
        packingDensity_best = snapshot.best.score.packingDensity || 0;
      }
      
      // 添加到趋势数据（total_best 来自 node_end/总结节点确定的 score）
      trend.push({
        iter,
        total_best,
        surfaceAnchoring_best,
        energyLevel_best,
        packingDensity_best,
      });
      
      // 添加到 Pareto 点集：使用 candidates + dimsById（按分子 id 对齐）
      // 每个候选的 total 也是从总结节点给出的 score（确定的）
      for (const c of candidates) {
        const dims = dimsById.get(c.id);
        paretoPoints.push({
          energyLevel: dims?.energyLevel || 0,
          surfaceAnchoring: dims?.surfaceAnchoring || 0,
          packingDensity: dims?.packingDensity || 0,
          total: c.score || 0, // 直接用总结节点给出的 score
          iter,
          smiles: c.smiles,
          moleculeId: c.id,
        });
      }

      if (total_best > 0) {
        hasData = true;
      }
    }
    
    // 构建每个候选分子的总分趋势（跨迭代）
    const candidateTrendMap = new Map<number | string, Map<number, number>>();
    for (const p of paretoPoints) {
      if (typeof p.iter !== "number" || p.moleculeId === undefined) continue;
      const total = typeof p.total === "number" ? p.total : 0;
      if (total <= 0) continue;
      
      if (!candidateTrendMap.has(p.moleculeId)) {
        candidateTrendMap.set(p.moleculeId, new Map());
      }
      candidateTrendMap.get(p.moleculeId)!.set(p.iter, total);
    }
    
    for (const [moleculeId, scoresByIter] of candidateTrendMap.entries()) {
      const firstPoint = Array.from(scoresByIter.entries())[0];
      if (!firstPoint) continue;
      
      candidateTrends.push({
        moleculeId,
        smiles: paretoPoints.find((p) => p.moleculeId === moleculeId)?.smiles,
        scoresByIter,
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
          }

          // 计算该迭代的最佳值
          let total_best = 0;
          let surfaceAnchoring_best = 0;
          let energyLevel_best = 0;
          let packingDensity_best = 0;

          if (iterMolecules.length > 0) {
            // 找到总分最高的分子
            const bestMol = iterMolecules.reduce((best, mol) => {
              const bestScore = best.score?.total || 0;
              const molScore = mol.score?.total || 0;
              return molScore > bestScore ? mol : best;
            }, iterMolecules[0]);

            total_best = bestMol.score?.total || 0;
            surfaceAnchoring_best = bestMol.score?.surfaceAnchoring || 0;
            energyLevel_best = bestMol.score?.energyLevel || 0;
            packingDensity_best = bestMol.score?.packingDensity || 0;

            // 添加到 Pareto 点集
            iterMolecules.forEach((mol) => {
              if (mol.score) {
                const moleculeId = (mol as any).id ?? (mol as any).moleculeId ?? mol.index ?? mol.smiles;
                paretoPoints.push({
                  energyLevel: mol.score.energyLevel || 0,
                  surfaceAnchoring: mol.score.surfaceAnchoring || 0,
                  packingDensity: mol.score.packingDensity || 0,
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
            energyLevel_best,
            packingDensity_best,
          });
        });
      }
    }
  }

  // 如果没有从 iterations 提取到数据，尝试从最终 molecules 生成一个数据点
  if (!hasData && molecules && molecules.length > 0) {
    const bestMol = molecules.reduce((best, mol) => {
      const bestScore = best.score?.total || 0;
      const molScore = mol.score?.total || 0;
      return molScore > bestScore ? mol : best;
    }, molecules[0]);

    if (bestMol.score) {
      trend.push({
        iter: 1,
        total_best: bestMol.score.total || 0,
        surfaceAnchoring_best: bestMol.score.surfaceAnchoring || 0,
        energyLevel_best: bestMol.score.energyLevel || 0,
        packingDensity_best: bestMol.score.packingDensity || 0,
      });

      molecules.forEach((mol) => {
        if (mol.score) {
          const moleculeId = (mol as any).id ?? (mol as any).moleculeId ?? mol.index ?? mol.smiles;
          paretoPoints.push({
            energyLevel: mol.score.energyLevel || 0,
            surfaceAnchoring: mol.score.surfaceAnchoring || 0,
            packingDensity: mol.score.packingDensity || 0,
            total: mol.score.total || 0,
            smiles: mol.smiles,
            moleculeId,
          });
        }
      });
    }
  }

  // 构建每个候选分子的总分趋势（跨迭代）- 回退逻辑
  const candidateTrendMap = new Map<number | string, Map<number, number>>();
  for (const p of paretoPoints) {
    if (typeof p.iter !== "number" || p.moleculeId === undefined) continue;
    const total = typeof p.total === "number" ? p.total : 0;
    if (total <= 0) continue;
    
    if (!candidateTrendMap.has(p.moleculeId)) {
      candidateTrendMap.set(p.moleculeId, new Map());
    }
    candidateTrendMap.get(p.moleculeId)!.set(p.iter, total);
  }
  
  for (const [moleculeId, scoresByIter] of candidateTrendMap.entries()) {
    const firstPoint = Array.from(scoresByIter.entries())[0];
    if (!firstPoint) continue;
    
    candidateTrends.push({
      moleculeId,
      smiles: paretoPoints.find((p) => p.moleculeId === moleculeId)?.smiles,
      scoresByIter,
    });
  }

  return {
    trend,
    paretoPoints,
    candidateTrends,
    hasData: trend.length > 0 || candidateTrends.length > 0,
  };
}

