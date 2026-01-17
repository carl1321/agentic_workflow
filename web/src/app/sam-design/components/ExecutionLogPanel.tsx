"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "~/components/ui/collapsible";
import { Button } from "~/components/ui/button";
import { ChevronDown } from "lucide-react";
import { parseDimensionScoresFromOptDes, parseSMILESFromText } from "../utils/molecule";
import type { DesignObjective, Constraint, Molecule } from "../types";

interface ExecutionLogPanelProps {
  objective: DesignObjective;
  constraints: Constraint[];
  logLines: string[];
  molecules: Molecule[];
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>;
  nodeOutputs?: Record<string, any>;
  iterationNodeOutputs?: Map<number, Record<string, any>>;
  workflowGraph?: { nodes: any[]; edges: any[] } | null;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 执行日志面板（左列）
 */
export function ExecutionLogPanel({
  objective,
  constraints,
  logLines,
  molecules,
  iterationSnapshots = [],
  nodeOutputs = {},
  iterationNodeOutputs = new Map(),
  workflowGraph,
  executionState,
}: ExecutionLogPanelProps) {
  const logRef = useRef<HTMLPreElement>(null);
  const [showDebugLogs, setShowDebugLogs] = useState(false);

  // 自动滚动到底部
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logLines, molecules, iterationSnapshots]);

  // 获取工作流名称
  const getWorkflowName = (): string => {
    if (workflowGraph?.nodes && workflowGraph.nodes.length > 0) {
      // 尝试从节点数据中获取工作流名称
      const startNode = workflowGraph.nodes.find((n: any) => n.type === "start");
      if (startNode?.data?.label) {
        return startNode.data.label;
      }
    }
    return "工作流";
  };

  // 生成用户可读的日志文本
  const generateLogText = (): string => {
    const lines: string[] = [];

    // 研究目标
    lines.push("═══════════════════════════════════");
    lines.push("研究目标");
    lines.push("═══════════════════════════════════");
    lines.push(objective.text || "(未设置)");
    lines.push("");

    // 关键约束
    lines.push("关键约束条件");
    lines.push("───────────────────────────────────");
    const enabledConstraints = constraints.filter((c) => c.enabled);
    if (enabledConstraints.length === 0) {
      lines.push("(无约束条件)");
    } else {
      enabledConstraints.forEach((c, idx) => {
        const valueText =
          typeof c.value === "string" || typeof c.value === "number"
            ? String(c.value)
            : `范围: [${c.value.min}, ${c.value.max}]${c.unit ? ` ${c.unit}` : ""}`;
        lines.push(`  • ${c.name}: ${valueText}`);
      });
    }
    lines.push("");

    // 工作流执行开始
    if (executionState !== "idle") {
      lines.push("工作流执行状态");
      lines.push("───────────────────────────────────");
      lines.push(`  工作流: ${getWorkflowName()}`);
      if (executionState === "running") {
        lines.push("  状态: ⏳ 执行中...");
      } else if (executionState === "completed") {
        lines.push("  状态: ✅ 执行完成");
      } else if (executionState === "failed") {
        lines.push("  状态: ❌ 执行失败");
      }
      lines.push("");
    }

    // 迭代过程（基于 iterationSnapshots 和 iterationNodeOutputs）
    if (iterationSnapshots.length > 0 || iterationNodeOutputs.size > 0) {
      lines.push("═══════════════════════════════════");
      lines.push("迭代优化过程");
      lines.push("═══════════════════════════════════");
      
      // 优先使用 iterationSnapshots（已处理好的数据）
      if (iterationSnapshots.length > 0) {
        for (const snapshot of iterationSnapshots) {
          lines.push(`\n┌─ 第 ${snapshot.iter} 轮迭代 ─────────────────────────┐`);
          
          // 从 iterationNodeOutputs 获取该迭代的节点输出
          const iterOutputs = iterationNodeOutputs.get(snapshot.iter);
          if (iterOutputs && workflowGraph) {
            // 按节点执行顺序展示节点输出
            const nodeMap = new Map(workflowGraph.nodes.map((n: any) => [n.id, n]));
            
            // 先收集所有节点输出，按类型分组
            const generationNodes: Array<{ name: string; output: any }> = [];
            const evaluationNodes: Array<{ name: string; output: any }> = [];
            const summaryNodes: Array<{ name: string; output: any }> = [];
            
            for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
              const node = nodeMap.get(nodeId);
              if (!node) continue;
              
              const nodeName = node.data?.displayName || nodeId;
              const nodeType = node.type || "unknown";
              
              // 跳过循环节点、开始节点、结束节点
              if (nodeType === "loop" || nodeType === "start" || nodeType === "end") {
                continue;
              }
              
              // 根据节点名称判断类型（生成/评估/总结）
              const nameLower = nodeName.toLowerCase();
              // 检查节点输出是否存在
              const hasOutput = nodeOutput && (nodeOutput.output !== undefined || Object.keys(nodeOutput).length > 0);
              
              if (nameLower.includes("生成") || nameLower.includes("generation") || 
                  (nodeType === "tool" && Array.isArray(nodeOutput.output))) {
                generationNodes.push({ name: nodeName, output: nodeOutput });
              } else if (nameLower.includes("评估") || nameLower.includes("evaluation") || 
                         nameLower.includes("llm1") || nameLower.includes("llm2") || nameLower.includes("llm3") ||
                         (nodeType === "llm" && !nameLower.includes("总结") && !nameLower.includes("summary") && !nameLower.includes("llm4"))) {
                // LLM节点默认归类为评估节点（除非明确是总结节点）
                evaluationNodes.push({ name: nodeName, output: nodeOutput });
              } else if (nameLower.includes("总结") || nameLower.includes("summary") || 
                         nameLower.includes("llm4")) {
                summaryNodes.push({ name: nodeName, output: nodeOutput });
              } else {
                // 其他节点根据输出类型判断
                if (Array.isArray(nodeOutput.output)) {
                  generationNodes.push({ name: nodeName, output: nodeOutput });
                } else if (typeof nodeOutput.output === "string" && nodeOutput.output.length > 200) {
                  summaryNodes.push({ name: nodeName, output: nodeOutput });
                } else if (hasOutput) {
                  // 有输出但不确定类型，默认归类为评估节点
                  evaluationNodes.push({ name: nodeName, output: nodeOutput });
                }
              }
            }
            
            // 展示生成节点输出
            if (generationNodes.length > 0) {
              lines.push("\n  【分子生成】");
              for (const { name, output } of generationNodes) {
                if (Array.isArray(output.output)) {
                  const molecules = output.output.filter((item: any) => item?.smiles);
                  if (molecules.length > 0) {
                    lines.push(`    ${name}: 生成 ${molecules.length} 个候选分子`);
                    // 只显示前5个分子的SMILES
                    molecules.slice(0, 5).forEach((item: any, idx: number) => {
                      lines.push(`      ${idx + 1}. ${item.smiles}`);
                    });
                    if (molecules.length > 5) {
                      lines.push(`      ... (还有 ${molecules.length - 5} 个分子)`);
                    }
                  }
                }
              }
            }
            
            // 展示评估节点输出
            if (evaluationNodes.length > 0) {
              lines.push("\n  【分子评估】");
              for (const { name, output } of evaluationNodes) {
                if (output.output !== undefined) {
                  if (typeof output.output === "string") {
                    // 字符串格式：提取评分和描述
                    const outputText = output.output;
                    if (outputText.trim().length > 0) {
                      lines.push(`    ${name}:`);
                      
                      // 查找评分信息
                      const scoreMatch = outputText.match(/总分[：:]\s*(\d+\.?\d*)|总评分[：:]\s*(\d+\.?\d*)|score[：:]\s*(\d+\.?\d*)/i);
                      const dimMatches = [
                        outputText.match(/表面锚定[强度]*[：:]\s*(\d+\.?\d*)/i),
                        outputText.match(/能级匹配[：:]\s*(\d+\.?\d*)/i),
                        outputText.match(/膜致密度[：:]\s*(\d+\.?\d*)/i),
                      ];
                      
                      // 显示评分信息
                      if (scoreMatch || dimMatches.some(m => m)) {
                        if (scoreMatch) {
                          const score = parseFloat(scoreMatch[1] || scoreMatch[2] || scoreMatch[3] || "0");
                          // 这里的“分子评估”多为单维度评估节点，避免误导为总分
                          lines.push(`      该维度得分: ${score.toFixed(1)}`);
                        }
                        dimMatches.forEach((match, idx) => {
                          if (match) {
                            const labels = ["表面锚定强度", "能级匹配", "膜致密度"];
                            lines.push(`      ${labels[idx]}: ${parseFloat(match[1]).toFixed(1)}`);
                          }
                        });
                      }
                      
                      // 提取并显示描述信息（去除评分部分后的内容）
                      let descriptionText = outputText;
                      // 移除评分相关的行
                      const scorePattern = /(总分|总评分|score|表面锚定|能级匹配|膜致密度)[：:]\s*\d+\.?\d*/gi;
                      descriptionText = descriptionText.replace(scorePattern, "");
                      
                      // 如果还有内容，显示描述
                      const descLines = descriptionText.split('\n').filter((l: string) => {
                        const trimmed = l.trim();
                        return trimmed.length > 0 && 
                               !trimmed.match(/^[0-9]+\.?\s*$/); // 排除纯数字行
                      });
                      
                      if (descLines.length > 0) {
                        lines.push(`      评估说明:`);
                        descLines.forEach((line: string) => {
                          const trimmed = line.trim();
                          if (trimmed.length > 0) {
                            lines.push(`        ${trimmed}`);
                          }
                        });
                      } else {
                        // 如果没有找到描述，显示完整输出（最多10行）
                        const allLines = outputText.split('\n').filter((l: string) => l.trim());
                        if (allLines.length > 0) {
                          lines.push(`      评估说明:`);
                          allLines.slice(0, 10).forEach((line: string) => {
                            lines.push(`        ${line.trim()}`);
                          });
                          if (allLines.length > 10) {
                            lines.push(`        ... (还有 ${allLines.length - 10} 行)`);
                          }
                        }
                      }
                    } else {
                      lines.push(`    ${name}: (输出为空)`);
                    }
                  } else if (Array.isArray(output.output)) {
                    // 数组格式：每个元素是分子的评估结果
                    lines.push(`    ${name}: 评估了 ${output.output.length} 个分子`);
                    output.output.forEach((item: any, idx: number) => {
                      if (item && typeof item === "object") {
                        lines.push(`\n      分子 ${idx + 1}:`);
                        if (item.smiles) {
                          lines.push(`        SMILES: ${item.smiles}`);
                        }
                        if (typeof item.score === "number") {
                          // 数组格式的评估节点通常是“单维度评分”，这里明确标注
                          lines.push(`        该维度得分: ${item.score.toFixed(1)}`);
                        }
                        // 解析维度评分
                        if (item.opt_des && typeof item.opt_des === "string") {
                          const dimScores = parseDimensionScoresFromOptDes(item.opt_des);
                          if (dimScores) {
                            lines.push(`        表面锚定强度: ${dimScores.surfaceAnchoring.toFixed(1)}`);
                            lines.push(`        能级匹配: ${dimScores.energyLevel.toFixed(1)}`);
                            lines.push(`        膜致密度: ${dimScores.packingDensity.toFixed(1)}`);
                          }
                        }
                        // 显示描述
                        if (item.description && typeof item.description === "string") {
                          lines.push(`        评估说明:`);
                          const descLines = item.description.split('\n').filter((l: string) => l.trim());
                          descLines.forEach((line: string) => {
                            lines.push(`          ${line.trim()}`);
                          });
                        } else if (item.opt_des && typeof item.opt_des === "string") {
                          // 如果没有description，使用opt_des作为描述
                          lines.push(`        评估说明:`);
                          const descLines = item.opt_des.split('\n').filter((l: string) => l.trim());
                          descLines.forEach((line: string) => {
                            lines.push(`          ${line.trim()}`);
                          });
                        }
                      }
                    });
                  } else if (output.output && typeof output.output === "object") {
                    // 对象格式
                    lines.push(`    ${name}:`);
                    if (output.output.score !== undefined) {
                      lines.push(`      总分: ${output.output.score}`);
                    }
                    if (output.output.description) {
                      lines.push(`      评估说明:`);
                      const descLines = output.output.description.split('\n').filter((l: string) => l.trim());
                      descLines.forEach((line: string) => {
                        lines.push(`        ${line.trim()}`);
                      });
                    }
                  } else {
                    lines.push(`    ${name}: ${JSON.stringify(output.output).substring(0, 100)}...`);
                  }
                } else {
                  lines.push(`    ${name}: (无输出)`);
                }
              }
            }
            
            // 展示总结节点输出
            if (summaryNodes.length > 0) {
              lines.push("\n  【迭代总结】");
              for (const { name, output } of summaryNodes) {
                if (output.output !== undefined) {
                  if (typeof output.output === "string") {
                    const summaryText = output.output.trim();
                    if (summaryText.length > 0) {
                      lines.push(`    ${name}:`);
                      
                      // 提取维度评分信息
                      const scoreMatch = summaryText.match(/总分[：:]\s*(\d+\.?\d*)|总评分[：:]\s*(\d+\.?\d*)|score[：:]\s*(\d+\.?\d*)/i);
                      const dimMatches = [
                        summaryText.match(/表面锚定[强度]*[：:]\s*(\d+\.?\d*)/i),
                        summaryText.match(/能级匹配[：:]\s*(\d+\.?\d*)/i),
                        summaryText.match(/膜致密度[：:]\s*(\d+\.?\d*)/i),
                      ];
                      
                      // 提取性质预测信息（HOMO/LUMO等）
                      const homoMatch = summaryText.match(/HOMO[：:]\s*([-]?\d+\.?\d*)/i);
                      const lumoMatch = summaryText.match(/LUMO[：:]\s*([-]?\d+\.?\d*)/i);
                      const dipoleMatch = summaryText.match(/偶极矩[：:]\s*(\d+\.?\d*)/i);
                      
                      // 显示维度评分
                      if (scoreMatch || dimMatches.some(m => m)) {
                        lines.push(`      维度评分:`);
                        if (scoreMatch) {
                          const score = parseFloat(scoreMatch[1] || scoreMatch[2] || scoreMatch[3] || "0");
                          lines.push(`        总分: ${score.toFixed(1)}`);
                        }
                        dimMatches.forEach((match, idx) => {
                          if (match) {
                            const labels = ["表面锚定强度", "能级匹配", "膜致密度"];
                            lines.push(`        ${labels[idx]}: ${parseFloat(match[1]).toFixed(1)}`);
                          } else {
                            const labels = ["表面锚定强度", "能级匹配", "膜致密度"];
                            lines.push(`        ${labels[idx]}: 缺少${labels[idx]}评分数据`);
                          }
                        });
                      }
                      
                      // 显示性质预测
                      if (homoMatch || lumoMatch || dipoleMatch) {
                        lines.push(`      性质预测:`);
                        if (homoMatch) {
                          lines.push(`        HOMO: ${parseFloat(homoMatch[1]).toFixed(3)} eV`);
                        } else {
                          lines.push(`        HOMO: 缺少能级数据（HOMO/LUMO）`);
                        }
                        if (lumoMatch) {
                          lines.push(`        LUMO: ${parseFloat(lumoMatch[1]).toFixed(3)} eV`);
                        } else if (!homoMatch) {
                          lines.push(`        LUMO: 缺少能级数据（HOMO/LUMO）`);
                        }
                        if (dipoleMatch) {
                          lines.push(`        偶极矩: ${parseFloat(dipoleMatch[1]).toFixed(3)} Debye`);
                        }
                      } else {
                        // 如果没有找到性质预测，检查是否有相关提示
                        if (summaryText.includes("能级") || summaryText.includes("HOMO") || summaryText.includes("LUMO")) {
                          lines.push(`      性质预测: 缺少能级数据（HOMO/LUMO）`);
                        }
                      }
                      
                      // 显示完整总结内容
                      const summaryLines = summaryText.split('\n').filter((l: string) => l.trim());
                      if (summaryLines.length > 0) {
                        lines.push(`      总结说明:`);
                        summaryLines.forEach((line: string) => {
                          lines.push(`        ${line.trim()}`);
                        });
                      }
                    } else {
                      lines.push(`    ${name}: (输出为空)`);
                    }
                  } else if (Array.isArray(output.output)) {
                    lines.push(`    ${name}:`);
                    output.output.forEach((item: any, idx: number) => {
                      if (item && typeof item === "object") {
                        // 显示分子SMILES
                        if (item.smiles) {
                          lines.push(`      分子 ${idx + 1}: ${item.smiles}`);
                        } else if (item.SMILES) {
                          lines.push(`      分子 ${idx + 1}: ${item.SMILES}`);
                        } else {
                          lines.push(`      项目 ${idx + 1}:`);
                        }
                        
                        if (item.score !== undefined) {
                          lines.push(`        总分: ${typeof item.score === "number" ? item.score.toFixed(1) : item.score}`);
                        }
                        if (item.surfaceAnchoring !== undefined || item.energyLevel !== undefined || item.packingDensity !== undefined) {
                          lines.push(`        维度评分:`);
                          if (item.surfaceAnchoring !== undefined) {
                            lines.push(`          表面锚定强度: ${item.surfaceAnchoring.toFixed(1)}`);
                          } else {
                            lines.push(`          表面锚定强度: 缺少表面锚定强度评分数据`);
                          }
                          if (item.energyLevel !== undefined) {
                            lines.push(`          能级匹配: ${item.energyLevel.toFixed(1)}`);
                          } else {
                            lines.push(`          能级匹配: 缺少能级数据（HOMO/LUMO）`);
                          }
                          if (item.packingDensity !== undefined) {
                            lines.push(`          膜致密度: ${item.packingDensity.toFixed(1)}`);
                          } else {
                            lines.push(`          膜致密度: 缺少膜致密度评分数据`);
                          }
                        }
                        if (item.HOMO !== undefined || item.LUMO !== undefined) {
                          lines.push(`        性质预测:`);
                          if (item.HOMO !== undefined) {
                            lines.push(`          HOMO: ${item.HOMO.toFixed(3)} eV`);
                          } else {
                            lines.push(`          HOMO: 缺少能级数据（HOMO/LUMO）`);
                          }
                          if (item.LUMO !== undefined) {
                            lines.push(`          LUMO: ${item.LUMO.toFixed(3)} eV`);
                          } else if (item.HOMO === undefined) {
                            lines.push(`          LUMO: 缺少能级数据（HOMO/LUMO）`);
                          }
                        }
                      } else {
                        const itemStr = typeof item === "string" ? item : JSON.stringify(item);
                        lines.push(`      ${idx + 1}. ${itemStr}`);
                      }
                    });
                  } else if (output.output && typeof output.output === "object") {
                    lines.push(`    ${name}:`);
                    // 显示维度评分
                    if (output.output.score !== undefined || output.output.surfaceAnchoring !== undefined || 
                        output.output.energyLevel !== undefined || output.output.packingDensity !== undefined) {
                      lines.push(`      维度评分:`);
                      if (output.output.score !== undefined) {
                        lines.push(`        总分: ${output.output.score}`);
                      }
                      if (output.output.surfaceAnchoring !== undefined) {
                        lines.push(`        表面锚定强度: ${output.output.surfaceAnchoring.toFixed(1)}`);
                      } else {
                        lines.push(`        表面锚定强度: 缺少表面锚定强度评分数据`);
                      }
                      if (output.output.energyLevel !== undefined) {
                        lines.push(`        能级匹配: ${output.output.energyLevel.toFixed(1)}`);
                      } else {
                        lines.push(`        能级匹配: 缺少能级数据（HOMO/LUMO）`);
                      }
                      if (output.output.packingDensity !== undefined) {
                        lines.push(`        膜致密度: ${output.output.packingDensity.toFixed(1)}`);
                      } else {
                        lines.push(`        膜致密度: 缺少膜致密度评分数据`);
                      }
                    }
                    // 显示性质预测
                    if (output.output.HOMO !== undefined || output.output.LUMO !== undefined || output.output.dipole !== undefined) {
                      lines.push(`      性质预测:`);
                      if (output.output.HOMO !== undefined) {
                        lines.push(`        HOMO: ${output.output.HOMO.toFixed(3)} eV`);
                      } else {
                        lines.push(`        HOMO: 缺少能级数据（HOMO/LUMO）`);
                      }
                      if (output.output.LUMO !== undefined) {
                        lines.push(`        LUMO: ${output.output.LUMO.toFixed(3)} eV`);
                      } else if (output.output.HOMO === undefined) {
                        lines.push(`        LUMO: 缺少能级数据（HOMO/LUMO）`);
                      }
                      if (output.output.dipole !== undefined) {
                        lines.push(`        偶极矩: ${output.output.dipole.toFixed(3)} Debye`);
                      }
                    }
                    // 显示总结说明
                    if (output.output.summary || output.output.description) {
                      lines.push(`      总结说明:`);
                      const summaryContent = output.output.summary || output.output.description;
                      const summaryLines = summaryContent.split('\n').filter((l: string) => l.trim());
                      summaryLines.forEach((line: string) => {
                        lines.push(`        ${line.trim()}`);
                      });
                    }
                  } else {
                    lines.push(`    ${name}: ${JSON.stringify(output.output)}`);
                  }
                } else {
                  lines.push(`    ${name}: (无输出)`);
                }
              }
            }
          }
          
          // 本轮最佳分子：优先从总结节点中获取，确保与【迭代总结】的分数一致
          let bestMolecule: Partial<Molecule> | null = null;
          
          // 重新获取总结节点（因为summaryNodes在循环内定义，需要重新查找）
          const currentSummaryNodes: Array<{ name: string; output: any }> = [];
          if (iterOutputs && workflowGraph) {
            const nodeMap = new Map(workflowGraph.nodes.map((n: any) => [n.id, n]));
            for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
              const node = nodeMap.get(nodeId);
              if (node) {
                const nodeName = node.data?.displayName || node.data?.taskName || node.data?.label || nodeId;
                const nameLower = nodeName.toLowerCase();
                if (nameLower.includes("总结") || nameLower.includes("summary") || nameLower.includes("llm4")) {
                  currentSummaryNodes.push({ name: nodeName, output: nodeOutput });
                }
              }
            }
          }
          
          // 先尝试从总结节点中获取最佳分子（分数最高的）
          if (currentSummaryNodes.length > 0) {
            for (const { output } of currentSummaryNodes) {
              if (output.output !== undefined) {
                let candidates: Array<{ smiles: string; score: number }> = [];
                
                if (Array.isArray(output.output)) {
                  // 数组格式：提取所有分子及其分数
                  for (const item of output.output) {
                    if (item && typeof item === "object") {
                      const smiles = item.smiles || item.SMILES;
                      if (smiles) {
                        const score = item.score || item.total_score || 
                          (item.surfaceAnchoring !== undefined && item.energyLevel !== undefined && item.packingDensity !== undefined
                            ? (item.surfaceAnchoring + item.energyLevel + item.packingDensity) / 3
                            : 0);
                        candidates.push({ smiles, score });
                      }
                    }
                  }
                } else if (typeof output.output === "string") {
                  // 字符串格式：解析SMILES和分数
                  const summaryText = output.output;
                  const smilesList = parseSMILESFromText(summaryText);
                  
                  for (const smiles of smilesList) {
                    // 找到该SMILES对应的分数
                    const smilesIndex = summaryText.indexOf(smiles);
                    if (smilesIndex >= 0) {
                      const contextStart = Math.max(0, smilesIndex - 100);
                      const contextEnd = Math.min(summaryText.length, smilesIndex + smiles.length + 500);
                      const contextText = summaryText.substring(contextStart, contextEnd);
                      
                      const scoreMatch = contextText.match(/总分[：:]\s*(\d+\.?\d*)|总评分[：:]\s*(\d+\.?\d*)/i);
                      const score = scoreMatch ? parseFloat(scoreMatch[1] || scoreMatch[2] || "0") : 0;
                      candidates.push({ smiles, score });
                    }
                  }
                }
                
                // 找到分数最高的分子
                if (candidates.length > 0) {
                  const bestCandidate = candidates.reduce((best, curr) => 
                    curr.score > best.score ? curr : best
                  );
                  
                  // 从总结节点输出中构建完整的best分子信息
                  if (Array.isArray(output.output)) {
                    const bestItem = output.output.find((item: any) => 
                      (item.smiles || item.SMILES) === bestCandidate.smiles
                    );
                    if (bestItem) {
                      bestMolecule = {
                        smiles: bestCandidate.smiles,
                        score: {
                          total: bestCandidate.score,
                          surfaceAnchoring: bestItem.surfaceAnchoring,
                          energyLevel: bestItem.energyLevel,
                          packingDensity: bestItem.packingDensity,
                        },
                        analysis: bestItem.description || bestItem.opt_des ? {
                          description: bestItem.description || bestItem.opt_des || "",
                          explanation: bestItem.explanation || bestItem.description || bestItem.opt_des || "",
                        } : undefined,
                      };
                    } else {
                      bestMolecule = {
                        smiles: bestCandidate.smiles,
                        score: { total: bestCandidate.score },
                      };
                    }
                  } else if (typeof output.output === "string") {
                    // 字符串格式：需要从文本中提取更多信息
                    const summaryText = output.output;
                    const smilesIndex = summaryText.indexOf(bestCandidate.smiles);
                    if (smilesIndex >= 0) {
                      const contextStart = Math.max(0, smilesIndex - 100);
                      const contextEnd = Math.min(summaryText.length, smilesIndex + bestCandidate.smiles.length + 500);
                      const contextText = summaryText.substring(contextStart, contextEnd);
                      
                      const dimMatches = [
                        contextText.match(/表面锚定[强度]*[：:]\s*(\d+\.?\d*)/i),
                        contextText.match(/能级匹配[：:]\s*(\d+\.?\d*)/i),
                        contextText.match(/膜致密度[：:]\s*(\d+\.?\d*)/i),
                      ];
                      
                      bestMolecule = {
                        smiles: bestCandidate.smiles,
                        score: {
                          total: bestCandidate.score,
                          surfaceAnchoring: dimMatches[0] ? parseFloat(dimMatches[0][1]) : undefined,
                          energyLevel: dimMatches[1] ? parseFloat(dimMatches[1][1]) : undefined,
                          packingDensity: dimMatches[2] ? parseFloat(dimMatches[2][1]) : undefined,
                        },
                      };
                    }
                  }
                  break; // 找到最佳分子后退出循环
                }
              }
            }
          }
          
          // 如果从总结节点没找到，使用snapshot.best作为后备
          if (!bestMolecule && snapshot.best) {
            bestMolecule = snapshot.best;
          }
          
          // 显示最佳候选分子
          if (bestMolecule) {
            lines.push("\n  【最佳候选分子】");
            lines.push(`    SMILES: ${bestMolecule.smiles}`);
            if (bestMolecule.score) {
              lines.push(`    总分: ${bestMolecule.score.total.toFixed(1)}`);
              if (bestMolecule.score.surfaceAnchoring !== undefined) {
                lines.push(`    表面锚定强度: ${bestMolecule.score.surfaceAnchoring.toFixed(1)}`);
              }
              if (bestMolecule.score.energyLevel !== undefined) {
                lines.push(`    能级匹配: ${bestMolecule.score.energyLevel.toFixed(1)}`);
              }
              if (bestMolecule.score.packingDensity !== undefined) {
                lines.push(`    膜致密度: ${bestMolecule.score.packingDensity.toFixed(1)}`);
              }
            }
            if (bestMolecule.analysis?.description) {
              lines.push(`    评估说明: ${bestMolecule.analysis.description}`);
            }
          }
          
          lines.push("└────────────────────────────────────────────────────┘");
        }
      } else {
        // 如果没有 iterationSnapshots，直接从 iterationNodeOutputs 展示
        const sortedIterations = Array.from(iterationNodeOutputs.keys()).sort((a, b) => a - b);
        for (const iter of sortedIterations) {
          lines.push(`\n┌─ 第 ${iter} 轮迭代 ─────────────────────────┐`);
          const iterOutputs = iterationNodeOutputs.get(iter);
          if (iterOutputs && workflowGraph) {
            const nodeMap = new Map(workflowGraph.nodes.map((n: any) => [n.id, n]));
            
            // 按节点类型分组展示
            for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
              const node = nodeMap.get(nodeId);
              const nodeName = node?.data?.displayName || nodeId;
              const nodeType = node?.type || "unknown";
              
              // 跳过循环节点、开始节点、结束节点
              if (nodeType === "loop" || nodeType === "start" || nodeType === "end") {
                continue;
              }
              
              if (nodeType === "tool" || nodeType === "llm") {
                if (nodeOutput.output !== undefined) {
                  if (Array.isArray(nodeOutput.output)) {
                    const molecules = nodeOutput.output.filter((item: any) => item?.smiles);
                    if (molecules.length > 0) {
                      lines.push(`\n  【${nodeName}】生成 ${molecules.length} 个候选分子`);
                      molecules.slice(0, 5).forEach((item: any, idx: number) => {
                        lines.push(`    ${idx + 1}. ${item.smiles}`);
                      });
                      if (molecules.length > 5) {
                        lines.push(`    ... (还有 ${molecules.length - 5} 个分子)`);
                      }
                    }
                  } else if (typeof nodeOutput.output === "string") {
                    lines.push(`\n  【${nodeName}】`);
                    const outputLines = nodeOutput.output.split('\n').filter((l: string) => l.trim()).slice(0, 5);
                    outputLines.forEach((line: string) => {
                      lines.push(`    ${line.substring(0, 100).trim()}`);
                    });
                  }
                }
              }
            }
          }
          lines.push("└────────────────────────────────────────────────────┘");
        }
      }
      lines.push("");
    }
    
    // 非迭代节点的输出（不在任何迭代中的节点）
    if (workflowGraph && Object.keys(nodeOutputs).length > 0) {
      const nodeMap = new Map(workflowGraph.nodes.map((n: any) => [n.id, n]));
      const nonIterationNodes: Array<{ nodeId: string; nodeName: string; nodeType: string; output: any }> = [];
      
      for (const [nodeId, nodeOutput] of Object.entries(nodeOutputs)) {
        // 检查该节点是否属于某个迭代
        let isInIteration = false;
        for (const iterOutputs of iterationNodeOutputs.values()) {
          if (iterOutputs[nodeId]) {
            isInIteration = true;
            break;
          }
        }
        
        if (!isInIteration) {
          const node = nodeMap.get(nodeId);
          const nodeType = node?.type || "unknown";
          // 跳过循环节点、开始节点、结束节点
          if (nodeType !== "loop" && nodeType !== "start" && nodeType !== "end") {
            nonIterationNodes.push({
              nodeId,
              nodeName: node?.data?.displayName || nodeId,
              nodeType,
              output: nodeOutput,
            });
          }
        }
      }
      
      if (nonIterationNodes.length > 0) {
        lines.push("=== 节点输出 ===");
        for (const { nodeName, nodeType, output } of nonIterationNodes) {
          if (nodeType === "tool" || nodeType === "llm") {
            if (output.output !== undefined) {
              if (Array.isArray(output.output)) {
                lines.push(`\n[${nodeName}] 输出:`);
                output.output.forEach((item: any, idx: number) => {
                  if (item && typeof item === "object" && item.smiles) {
                    const scoreText = item.score 
                      ? `总分: ${item.score.toFixed(1)}` 
                      : "未评分";
                    lines.push(`  分子 ${idx + 1}: ${item.smiles.substring(0, 50)}... [${scoreText}]`);
                  }
                });
              } else if (typeof output.output === "string") {
                lines.push(`\n[${nodeName}] 输出:`);
                const outputLines = output.output.split('\n').slice(0, 10);
                outputLines.forEach((line: string) => {
                  lines.push(`  ${line.substring(0, 120)}`);
                });
                if (output.output.split('\n').length > 10) {
                  lines.push(`  ... (还有 ${output.output.split('\n').length - 10} 行)`);
                }
              } else {
                const outputStr = JSON.stringify(output.output).substring(0, 200);
                lines.push(`\n[${nodeName}] 输出: ${outputStr}${outputStr.length >= 200 ? "..." : ""}`);
              }
            }
          } else if (nodeType === "condition") {
            if (output.output !== undefined) {
              lines.push(`\n[${nodeName}] 条件判断: ${output.output ? "通过" : "未通过"}`);
            }
          } else {
            if (output.output !== undefined) {
              const outputStr = typeof output.output === "string" 
                ? output.output.substring(0, 200) 
                : JSON.stringify(output.output).substring(0, 200);
              lines.push(`\n[${nodeName}] 输出: ${outputStr}${outputStr.length >= 200 ? "..." : ""}`);
            }
          }
        }
        lines.push("");
      }
    }

    // 最终候选（TopK，按总分排序）
    if (molecules.length > 0) {
      const sorted = [...molecules].sort((a, b) => (b.score?.total || 0) - (a.score?.total || 0));
      const topK = sorted.slice(0, Math.min(10, sorted.length));
      
      lines.push("\n═══════════════════════════════════");
      lines.push("最终候选分子（Top 10）");
      lines.push("═══════════════════════════════════");
      
      topK.forEach((mol, idx) => {
        lines.push(`\n【候选 ${idx + 1}】`);
        lines.push(`  SMILES: ${mol.smiles}`);
        if (mol.score) {
          lines.push(`  综合评分: ${mol.score.total.toFixed(1)}`);
          if (mol.score.surfaceAnchoring !== undefined || 
              mol.score.energyLevel !== undefined || 
              mol.score.packingDensity !== undefined) {
            lines.push(`  维度评分:`);
            if (mol.score.surfaceAnchoring !== undefined) {
              lines.push(`    表面锚定强度: ${mol.score.surfaceAnchoring.toFixed(1)}`);
            }
            if (mol.score.energyLevel !== undefined) {
              lines.push(`    能级匹配: ${mol.score.energyLevel.toFixed(1)}`);
            }
            if (mol.score.packingDensity !== undefined) {
              lines.push(`    膜致密度: ${mol.score.packingDensity.toFixed(1)}`);
            }
          }
        }
        if (mol.analysis?.description) {
          const desc = mol.analysis.description.trim();
          if (desc.length > 0) {
            lines.push(`  评估说明: ${desc.substring(0, 150)}${desc.length > 150 ? "..." : ""}`);
          }
        }
      });
    }

    return lines.join("\n");
  };

  // 生成调试日志（节点ID级别的日志）
  const generateDebugLogText = (): string => {
    if (logLines.length === 0) return "(无调试日志)";
    return logLines.join("\n");
  };

  return (
    <div className="flex h-full flex-col bg-white dark:bg-slate-900">
      <div className="border-b border-slate-200 px-4 py-2 dark:border-slate-700">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">执行日志</h3>
          {logLines.length > 0 && (
            <Collapsible open={showDebugLogs} onOpenChange={setShowDebugLogs}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="h-6 text-xs">
                  调试日志
                  <ChevronDown className={`ml-1 h-3 w-3 transition-transform ${showDebugLogs ? "rotate-180" : ""}`} />
                </Button>
              </CollapsibleTrigger>
            </Collapsible>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4">
        <pre
          ref={logRef}
          className="font-mono text-xs leading-relaxed text-slate-900 dark:text-slate-100 whitespace-pre-wrap break-words"
        >
          {generateLogText()}
        </pre>
        {logLines.length > 0 && (
          <Collapsible open={showDebugLogs} onOpenChange={setShowDebugLogs}>
            <CollapsibleContent className="mt-2">
              <div className="rounded-md bg-slate-50 dark:bg-slate-800 p-2">
                <div className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">调试日志（节点执行详情）:</div>
                <pre className="font-mono text-[10px] leading-relaxed text-slate-600 dark:text-slate-400 whitespace-pre-wrap break-words">
                  {generateDebugLogText()}
                </pre>
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  );
}
