"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { parseDimensionScoresFromOptDes, extractDimScoresFromResolvedInputsPrompt } from "../utils/molecule";
import type { Molecule } from "../types";

interface MoleculeOptimizationHistoryProps {
  molecule: Molecule;
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>;
  iterationNodeOutputs?: Map<number, Record<string, any>>;
  workflowGraph?: { nodes: any[]; edges: any[] } | null;
}

/**
 * 分子优化历史（同次运行内的迭代轨迹）
 */
export function MoleculeOptimizationHistory({
  molecule,
  iterationSnapshots = [],
  iterationNodeOutputs = new Map(),
  workflowGraph,
}: MoleculeOptimizationHistoryProps) {
  if (!molecule.smiles) {
    return (
      <div className="text-xs text-slate-500 dark:text-slate-400">
        无分子数据
      </div>
    );
  }

  // 构建分子演化链：从最早到当前迭代
  interface MoleculeHistoryEntry {
    iter: number;
    smiles: string;
    moleculeId?: number | string; // 分子ID
    status: "passed" | "pending";
    score: {
      total: number;
      surfaceAnchoring?: number;
      energyLevel?: number;
      packingDensity?: number;
    };
    description?: string; // 评估说明
  }

  // 从工作流节点输出中获取分子的ID和前身ID
  const getMoleculeIdFromWorkflow = (iter: number, smiles: string): {
    id?: number | string;
    previousId?: number | string;
  } => {
    const iterOutputs = iterationNodeOutputs.get(iter);
    if (!iterOutputs || !workflowGraph) return {};
    
    const nodeMap = new Map(workflowGraph.nodes.map((n: any) => [n.id, n]));
    
    // 遍历所有节点输出，查找包含该SMILES的分子对象
    for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      
      // 检查 passed_items
      if (Array.isArray(nodeOutput.passed_items)) {
        for (const item of nodeOutput.passed_items) {
          if (item && typeof item === "object" && (item.smiles === smiles || item.SMILES === smiles)) {
            return {
              id: item.id,
              previousId: item.previous_id || item.parent_id || item.previousId || item.parentId,
            };
          }
        }
      }
      
      // 检查 pending_items
      if (Array.isArray(nodeOutput.pending_items)) {
        for (const item of nodeOutput.pending_items) {
          if (item && typeof item === "object" && (item.smiles === smiles || item.SMILES === smiles)) {
            return {
              id: item.id,
              previousId: item.previous_id || item.parent_id || item.previousId || item.parentId,
            };
          }
        }
      }
      
      // 检查 output
      if (Array.isArray(nodeOutput.output)) {
        for (const item of nodeOutput.output) {
          if (item && typeof item === "object" && (item.smiles === smiles || item.SMILES === smiles)) {
            return {
              id: item.id,
              previousId: item.previous_id || item.parent_id || item.previousId || item.parentId,
            };
          }
        }
      }
    }
    
    return {};
  };

  // 根据分子ID查找分子
  const findMoleculeById = (iter: number, moleculeId: number | string): Partial<Molecule> | null => {
    const iterOutputs = iterationNodeOutputs.get(iter);
    if (!iterOutputs) return null;
    
    // 遍历所有节点输出，查找匹配ID的分子
    for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      
      // 检查 passed_items
      if (Array.isArray(nodeOutput.passed_items)) {
        for (const item of nodeOutput.passed_items) {
          if (item && typeof item === "object" && item.id === moleculeId) {
            return {
              smiles: item.smiles || item.SMILES,
              index: item.id,
            };
          }
        }
      }
      
      // 检查 pending_items
      if (Array.isArray(nodeOutput.pending_items)) {
        for (const item of nodeOutput.pending_items) {
          if (item && typeof item === "object" && item.id === moleculeId) {
            return {
              smiles: item.smiles || item.SMILES,
              index: item.id,
            };
          }
        }
      }
      
      // 检查 output
      if (Array.isArray(nodeOutput.output)) {
        for (const item of nodeOutput.output) {
          if (item && typeof item === "object" && item.id === moleculeId) {
            return {
              smiles: item.smiles || item.SMILES,
              index: item.id,
            };
          }
        }
      }
    }
    
    return null;
  };

  // 查找该分子在哪些迭代中出现
  const moleculeHistory: MoleculeHistoryEntry[] = [];
  
  // 构建演化链：根据分子ID追溯前身
  const buildEvolutionChain = (targetSmiles: string): MoleculeHistoryEntry[] => {
    const chain: MoleculeHistoryEntry[] = [];
    let currentSmiles = targetSmiles;
    let currentId: number | string | undefined;
    
    // 从后往前遍历迭代，构建演化链
    for (let i = iterationSnapshots.length - 1; i >= 0; i--) {
      const snapshot = iterationSnapshots[i];
      const allMolecules = [...snapshot.passed, ...snapshot.pending];
      
      // 查找当前SMILES是否在这一轮出现
      const found = allMolecules.find((m) => m.smiles === currentSmiles);
      if (found) {
        // 从工作流获取分子ID和前身ID
        const idInfo = getMoleculeIdFromWorkflow(snapshot.iter, currentSmiles);
        if (idInfo.id) {
          currentId = idInfo.id;
        }
        
        // 从工作流评估节点获取评分和描述
        const evalInfo = getEvaluationFromWorkflow(snapshot.iter, currentSmiles);
        const finalScore = evalInfo.score || found.score || { total: 0 };
        
        chain.unshift({
          iter: snapshot.iter,
          smiles: currentSmiles,
          moleculeId: currentId,
          status: snapshot.passed.some((m) => m.smiles === currentSmiles) ? "passed" : "pending",
          score: {
            total: finalScore.total || 0,
            surfaceAnchoring: finalScore.surfaceAnchoring,
            energyLevel: finalScore.energyLevel,
            packingDensity: finalScore.packingDensity,
          },
          description: evalInfo.description,
        });
        
        // 根据前身ID查找前身分子
        if (idInfo.previousId && i > 0) {
          const previousMol = findMoleculeById(i - 1, idInfo.previousId);
          if (previousMol && previousMol.smiles) {
            currentSmiles = previousMol.smiles;
            currentId = idInfo.previousId;
          }
        } else if (i > 0) {
          // 如果没有前身ID，回退到原来的逻辑：在上一轮迭代中查找可能的来源分子
          const prevSnapshot = iterationSnapshots[i - 1];
          const prevMolecules = [...prevSnapshot.passed, ...prevSnapshot.pending];
          
          if (prevSnapshot.best && prevSnapshot.best.smiles && prevSnapshot.best.smiles !== currentSmiles) {
            currentSmiles = prevSnapshot.best.smiles;
          } else if (prevMolecules.length > 0) {
            const firstPrev = prevMolecules.find((m) => m.smiles && m.smiles !== currentSmiles);
            if (firstPrev && firstPrev.smiles) {
              currentSmiles = firstPrev.smiles;
            }
          }
        }
      }
    }
    
    return chain;
  };

  // 从工作流的总结节点（node_end）中提取评分和描述信息
  // 确保与执行日志和趋势图使用相同的数据源
  const getEvaluationFromWorkflow = (iter: number, smiles: string): {
    score?: {
      total: number;
      surfaceAnchoring?: number;
      energyLevel?: number;
      packingDensity?: number;
    };
    description?: string;
  } => {
    const iterOutputs = iterationNodeOutputs.get(iter);
    if (!iterOutputs || !workflowGraph) return {};
    
    const nodeMap = new Map(workflowGraph.nodes.map((n: any) => [n.id, n]));
    
    // 1. 优先从总结节点（通常是循环的退出节点，包含 output 字段）获取分数
    // 总结节点的 output 包含 [{id, score, smiles, opt_des}, ...]
    // 识别总结节点：节点名称包含"总结"、"summary"或"llm4"
    for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      
      const node = nodeMap.get(nodeId);
      const nodeName = node ? (node.data?.displayName || node.data?.taskName || node.data?.label || nodeId).toLowerCase() : "";
      const isSummaryNode = nodeName.includes("总结") || nodeName.includes("summary") || nodeName.includes("llm4");
      
      // 查找总结节点：通常包含 output 数组，且每个 item 有 id、score、smiles
      // 优先查找明确标识为总结节点的节点
      if (Array.isArray((nodeOutput as any).output) && isSummaryNode) {
        for (const item of (nodeOutput as any).output) {
          if (item && typeof item === "object" && (item.smiles === smiles || item.SMILES === smiles)) {
            const result: any = {};
            
            // 从总结节点获取总分（这是确定的）
            const totalScore = typeof item.score === "number" ? item.score : 0;
            
            // 2. 优先从 iteration_outputs[iter].resolved_inputs.prompt 解析维度分数
            let dimScores: { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number } | undefined;
            
            // 查找包含该迭代的 iteration_outputs
            const iterationOutputs = (nodeOutput as any).iteration_outputs;
            if (Array.isArray(iterationOutputs)) {
              const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
              const promptText = entry?.resolved_inputs?.prompt;
              if (typeof promptText === "string" && promptText.length > 0) {
                const dimsById = extractDimScoresFromResolvedInputsPrompt(promptText);
                const moleculeId = item.id;
                if (moleculeId !== undefined && dimsById.has(moleculeId)) {
                  dimScores = dimsById.get(moleculeId);
                }
              }
            }
            
            // 3. 如果没有从 prompt 获取到，尝试从 opt_des 解析（兜底）
            if (!dimScores && item.opt_des && typeof item.opt_des === "string") {
              const parsed = parseDimensionScoresFromOptDes(item.opt_des);
              if (parsed) {
                dimScores = parsed;
              }
            }
            
            // 构建结果
            if (totalScore > 0 || dimScores) {
              result.score = {
                total: totalScore || (dimScores ? 
                  Math.round(((dimScores.surfaceAnchoring || 0) + (dimScores.energyLevel || 0) + (dimScores.packingDensity || 0)) / 3 * 10) / 10 : 0),
                surfaceAnchoring: dimScores?.surfaceAnchoring,
                energyLevel: dimScores?.energyLevel,
                packingDensity: dimScores?.packingDensity,
              };
            }
            
            // 提取描述
            if (item.description || item.opt_des) {
              result.description = item.description || item.opt_des;
            }
            
            if (result.score || result.description) {
              return result;
            }
          }
        }
      }
    }
    
    // 2. 如果明确标识的总结节点没找到，尝试从所有包含 output 数组的节点中查找（兜底）
    for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
      if (!nodeOutput || typeof nodeOutput !== "object") continue;
      
      // 查找包含 output 数组的节点（可能是总结节点但名称不明确）
      if (Array.isArray((nodeOutput as any).output)) {
        for (const item of (nodeOutput as any).output) {
          if (item && typeof item === "object" && (item.smiles === smiles || item.SMILES === smiles)) {
            const result: any = {};
            
            // 从节点获取总分
            const totalScore = typeof item.score === "number" ? item.score : 0;
            
            // 尝试从 iteration_outputs 中获取维度分数
            let dimScores: { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number } | undefined;
            const iterationOutputs = (nodeOutput as any).iteration_outputs;
            if (Array.isArray(iterationOutputs)) {
              const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
              const promptText = entry?.resolved_inputs?.prompt;
              if (typeof promptText === "string" && promptText.length > 0) {
                const dimsById = extractDimScoresFromResolvedInputsPrompt(promptText);
                const moleculeId = item.id;
                if (moleculeId !== undefined && dimsById.has(moleculeId)) {
                  dimScores = dimsById.get(moleculeId);
                }
              }
            }
            
            // 如果没有从 prompt 获取到，尝试从 opt_des 解析
            if (!dimScores && item.opt_des && typeof item.opt_des === "string") {
              const parsed = parseDimensionScoresFromOptDes(item.opt_des);
              if (parsed) {
                dimScores = parsed;
              }
            }
            
            // 构建结果
            if (totalScore > 0 || dimScores) {
              result.score = {
                total: totalScore || (dimScores ? 
                  Math.round(((dimScores.surfaceAnchoring || 0) + (dimScores.energyLevel || 0) + (dimScores.packingDensity || 0)) / 3 * 10) / 10 : 0),
                surfaceAnchoring: dimScores?.surfaceAnchoring,
                energyLevel: dimScores?.energyLevel,
                packingDensity: dimScores?.packingDensity,
              };
            }
            
            // 提取描述
            if (item.description || item.opt_des) {
              result.description = item.description || item.opt_des;
            }
            
            if (result.score || result.description) {
              return result;
            }
          }
        }
      }
    }
    
    // 3. 如果总结节点没找到，尝试从评估节点的 iteration_outputs 中获取维度分数
    // （但总分仍然应该从总结节点获取，这里只作为维度分数的兜底）
    for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
      const node = nodeMap.get(nodeId);
      if (!node) continue;
      
      const nodeName = (node.data?.displayName || "").toLowerCase();
      // 识别评估节点（LLM1/2/3）
      if (nodeName.includes("llm1") || nodeName.includes("llm2") || nodeName.includes("llm3") ||
          nodeName.includes("评估") || nodeName.includes("evaluation")) {
        // 从 iteration_outputs 中提取维度分数
        const iterationOutputs = (nodeOutput as any).iteration_outputs;
        if (Array.isArray(iterationOutputs)) {
          const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
          const promptText = entry?.resolved_inputs?.prompt;
          if (typeof promptText === "string" && promptText.length > 0) {
            const dimsById = extractDimScoresFromResolvedInputsPrompt(promptText);
            // 查找匹配的分子ID
            for (const [moleculeId, dims] of dimsById.entries()) {
              // 需要通过 moleculeId 找到对应的 SMILES（这里简化处理，如果找不到就跳过）
              // 实际上应该从其他节点输出中查找 moleculeId 对应的 SMILES
            }
          }
        }
      }
    }
    
    return {};
  };

  // 构建演化链
  moleculeHistory.push(...buildEvolutionChain(molecule.smiles));

  if (moleculeHistory.length === 0) {
    return (
      <div className="text-xs text-slate-500 dark:text-slate-400">
        该分子在本次运行的迭代过程中未出现
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
        迭代轨迹（在 {moleculeHistory.length} 轮迭代中出现）
      </div>
      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {moleculeHistory.map((entry, idx) => (
          <div
            key={`${entry.iter}-${idx}`}
            className="rounded border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800"
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] font-medium text-slate-900 dark:text-slate-100">
                第 {entry.iter} 轮迭代
              </span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                entry.status === "passed"
                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                  : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
              }`}>
                {entry.status === "passed" ? "已通过" : "待改进"}
              </span>
            </div>
            <div className="space-y-1 text-[10px] text-slate-600 dark:text-slate-400">
              <div className="font-medium text-slate-700 dark:text-slate-300">分子</div>
              <div className="pl-2 space-y-0.5">
                <div className="font-mono text-[9px] break-all">{entry.smiles}</div>
                <div className="font-medium text-slate-700 dark:text-slate-300 mt-1">评分</div>
                <div>总分: {entry.score.total.toFixed(1)}</div>
                {entry.score.surfaceAnchoring !== undefined && (
                  <div>表面锚定: {entry.score.surfaceAnchoring.toFixed(1)}</div>
                )}
                {entry.score.energyLevel !== undefined && (
                  <div>能级匹配: {entry.score.energyLevel.toFixed(1)}</div>
                )}
                {entry.score.packingDensity !== undefined && (
                  <div>膜致密度: {entry.score.packingDensity.toFixed(1)}</div>
                )}
              </div>
              
              {entry.description && (
                <div className="mt-1">
                  <div className="font-medium text-slate-700 dark:text-slate-300">评估说明</div>
                  <div className="pl-2 text-[9px] text-slate-500 dark:text-slate-400 line-clamp-3">
                    {entry.description}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
