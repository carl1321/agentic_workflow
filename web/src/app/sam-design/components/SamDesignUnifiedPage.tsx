"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect, useRef } from "react";
import { ExecutionHistoryDialog } from "~/app/newSam/components/ExecutionHistoryDialog";
import { getExecutionHistory, saveExecutionHistory } from "~/core/api/new-sam";
import { extractIterationAnalytics } from "../utils/molecule";
import { toast } from "sonner";
import { Button } from "~/components/ui/button";
import { History, Edit2 } from "lucide-react";
import type { DesignObjective, Constraint, ExecutionResult, DesignHistory, Molecule } from "../types";
import { ExecutionLogPanel } from "./ExecutionLogPanel";
import { WorkflowRunnerPanel } from "./WorkflowRunnerPanel";
import { WorkflowGraphView } from "./WorkflowGraphView";
import { IterationAnalyticsPanel } from "./IterationAnalyticsPanel";
import { CandidateListPanel } from "./CandidateListPanel";
import { extractMoleculesFromWorkflowResult, parseDimensionScoresFromOptDes } from "../utils/molecule";
import type { MoleculeScore } from "../types";

interface SamDesignUnifiedPageProps {
  objective: DesignObjective;
  onObjectiveChange: (objective: DesignObjective) => void;
  constraints: Constraint[];
  onConstraintsChange: (constraints: Constraint[]) => void;
  onEditObjective?: () => void;
}

/**
 * SAM 分子设计统一页面（单页三列布局）
 */
export function SamDesignUnifiedPage({
  objective,
  onObjectiveChange,
  constraints,
  onConstraintsChange,
  onEditObjective,
}: SamDesignUnifiedPageProps) {
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [executionState, setExecutionState] = useState<"idle" | "running" | "completed" | "failed">("idle");
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [nodeOutputs, setNodeOutputs] = useState<Record<string, any>>({});
  const [molecules, setMolecules] = useState<Molecule[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>("");
  const [workflowGraph, setWorkflowGraph] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [historyMolecules, setHistoryMolecules] = useState<Molecule[] | undefined>(undefined);
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());
  const [iterationNodeOutputs, setIterationNodeOutputs] = useState<Map<number, Record<string, any>>>(new Map());
  
  // 迭代快照：每轮迭代的分子数据
  const [iterationSnapshots, setIterationSnapshots] = useState<Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>>([]);

  // 用于跟踪是否已经保存过历史（避免重复保存）
  const hasSavedHistoryRef = useRef(false);
  const executionStartTimeRef = useRef<Date | null>(null);

  // 处理执行完成
  const handleExecutionComplete = (result: ExecutionResult, finalMolecules: Molecule[], finalNodeOutputs: Record<string, any>) => {
    setExecutionResult(result);
    setMolecules(finalMolecules);
    setNodeOutputs(finalNodeOutputs);
    setExecutionState("completed");
    hasSavedHistoryRef.current = false; // 重置标志，允许保存
  };

  // 自动保存执行历史（当执行完成且所有数据就绪时）
  useEffect(() => {
    const saveHistory = async () => {
      // 只在执行完成且尚未保存时保存
      if (executionState !== "completed" || hasSavedHistoryRef.current || !runId || !selectedWorkflowId) {
        return;
      }

      // 确保有必要的数据
      if (!molecules.length && !iterationSnapshots.length) {
        return;
      }

      try {
        hasSavedHistoryRef.current = true; // 标记为已保存，避免重复保存

        // 提取迭代分析数据
        const analytics = extractIterationAnalytics(
          nodeOutputs,
          molecules,
          iterationSnapshots,
          iterationNodeOutputs,
          workflowGraph
        );

        // 保存执行历史
        await saveExecutionHistory(
          runId,
          selectedWorkflowId,
          undefined, // 自动生成名称
          objective,
          constraints,
          executionState,
          executionStartTimeRef.current?.toISOString(),
          new Date().toISOString(),
          logLines,
          nodeOutputs,
          iterationNodeOutputs,
          iterationSnapshots,
          workflowGraph || undefined,
          analytics,
          molecules,
        );

        console.log("[SamDesignUnifiedPage] Execution history saved automatically");
      } catch (error: any) {
        console.error("[SamDesignUnifiedPage] Failed to save execution history:", error);
        hasSavedHistoryRef.current = false; // 保存失败，允许重试
        // 不显示错误提示，避免干扰用户
      }
    };

    // 延迟保存，确保所有状态都已更新
    const timer = setTimeout(saveHistory, 500);
    return () => clearTimeout(timer);
  }, [executionState, runId, selectedWorkflowId, molecules, nodeOutputs, iterationNodeOutputs, iterationSnapshots, workflowGraph, logLines, objective, constraints]);

  // 处理执行开始
  const handleExecutionStart = (workflowId: string, runId: string) => {
    setSelectedWorkflowId(workflowId);
    setRunId(runId);
    setExecutionState("running");
    setLogLines([]);
    setMolecules([]);
    setNodeOutputs({});
    setIterationSnapshots([]);
    setRunningNodeIds(new Set());
    setIterationNodeOutputs(new Map());
    hasSavedHistoryRef.current = false; // 重置保存标志
    executionStartTimeRef.current = new Date(); // 记录开始时间
  };
  
  // 处理节点开始执行
  const handleNodeStart = (nodeId: string) => {
    setRunningNodeIds((prev) => new Set(prev).add(nodeId));
  };
  
  // 处理节点执行完成
  const handleNodeEnd = (nodeId: string, iteration?: number, loopId?: string) => {
    setRunningNodeIds((prev) => {
      const next = new Set(prev);
      next.delete(nodeId);
      return next;
    });
  };
  
  // 处理迭代节点输出更新
  const handleIterationNodeOutputsUpdate = (newIterationNodeOutputs: Map<number, Record<string, any>>) => {
    setIterationNodeOutputs(newIterationNodeOutputs);
    
    // 从迭代节点输出中提取迭代快照
    const snapshots: Array<{
      iter: number;
      passed: Partial<Molecule>[];
      pending: Partial<Molecule>[];
      best: Partial<Molecule> | null;
    }> = [];
    
    // 按迭代轮次排序
    const sortedIterations = Array.from(newIterationNodeOutputs.keys()).sort((a, b) => a - b);
    
    for (const iter of sortedIterations) {
      const iterOutputs = newIterationNodeOutputs.get(iter);
      if (!iterOutputs) continue;
      
      const passed: Partial<Molecule>[] = [];
      const pending: Partial<Molecule>[] = [];
      
      // 遍历该迭代的所有节点输出，查找分子和评分
      for (const [nodeId, nodeOutput] of Object.entries(iterOutputs)) {
        if (!nodeOutput || typeof nodeOutput !== "object") continue;
        
        // 检查是否是循环节点输出（有 passed_items/pending_items）
        if ("passed_items" in nodeOutput && Array.isArray(nodeOutput.passed_items)) {
          for (const item of nodeOutput.passed_items) {
            if (item && typeof item === "object" && item.smiles) {
              const mol: Partial<Molecule> = {
                smiles: item.smiles,
                index: item.id || passed.length + 1,
              };
              
              // 解析分数
              if (item.opt_des && typeof item.opt_des === "string") {
                const dimScores = parseDimensionScoresFromOptDes(item.opt_des);
                if (dimScores) {
                  const totalScore = typeof item.score === "number" ? item.score :
                    (dimScores.surfaceAnchoring + dimScores.energyLevel + dimScores.packingDensity) / 3;
                  mol.score = {
                    total: totalScore,
                    surfaceAnchoring: dimScores.surfaceAnchoring,
                    energyLevel: dimScores.energyLevel,
                    packingDensity: dimScores.packingDensity,
                  } as MoleculeScore;
                } else if (typeof item.score === "number") {
                  mol.score = { total: item.score } as MoleculeScore;
                }
              } else if (typeof item.score === "number") {
                mol.score = { total: item.score } as MoleculeScore;
              }
              
              // 解析分析描述
              if (item.opt_des && typeof item.opt_des === "string") {
                mol.analysis = {
                  description: item.opt_des,
                  explanation: item.opt_des,
                };
              }
              
              passed.push(mol);
            }
          }
        }
        
        if ("pending_items" in nodeOutput && Array.isArray(nodeOutput.pending_items)) {
          for (const item of nodeOutput.pending_items) {
            if (item && typeof item === "object" && item.smiles) {
              const mol: Partial<Molecule> = {
                smiles: item.smiles,
                index: item.id || pending.length + 1,
              };
              
              // 解析分数
              if (item.opt_des && typeof item.opt_des === "string") {
                const dimScores = parseDimensionScoresFromOptDes(item.opt_des);
                if (dimScores) {
                  const totalScore = typeof item.score === "number" ? item.score :
                    (dimScores.surfaceAnchoring + dimScores.energyLevel + dimScores.packingDensity) / 3;
                  mol.score = {
                    total: totalScore,
                    surfaceAnchoring: dimScores.surfaceAnchoring,
                    energyLevel: dimScores.energyLevel,
                    packingDensity: dimScores.packingDensity,
                  } as MoleculeScore;
                } else if (typeof item.score === "number") {
                  mol.score = { total: item.score } as MoleculeScore;
                }
              } else if (typeof item.score === "number") {
                mol.score = { total: item.score } as MoleculeScore;
              }
              
              // 解析分析描述
              if (item.opt_des && typeof item.opt_des === "string") {
                mol.analysis = {
                  description: item.opt_des,
                  explanation: item.opt_des,
                };
              }
              
              pending.push(mol);
            }
          }
        }
        
        // 检查节点输出中是否有 output 字段（生成节点的输出）
        if ("output" in nodeOutput && Array.isArray(nodeOutput.output)) {
          for (const item of nodeOutput.output) {
            if (item && typeof item === "object" && item.smiles) {
              const mol: Partial<Molecule> = {
                smiles: item.smiles,
                index: item.id || (passed.length + pending.length + 1),
              };
              
              // 解析分数
              if (item.opt_des && typeof item.opt_des === "string") {
                const dimScores = parseDimensionScoresFromOptDes(item.opt_des);
                if (dimScores) {
                  const totalScore = typeof item.score === "number" ? item.score :
                    (dimScores.surfaceAnchoring + dimScores.energyLevel + dimScores.packingDensity) / 3;
                  mol.score = {
                    total: totalScore,
                    surfaceAnchoring: dimScores.surfaceAnchoring,
                    energyLevel: dimScores.energyLevel,
                    packingDensity: dimScores.packingDensity,
                  } as MoleculeScore;
                } else if (typeof item.score === "number") {
                  mol.score = { total: item.score } as MoleculeScore;
                }
              } else if (typeof item.score === "number") {
                mol.score = { total: item.score } as MoleculeScore;
              }
              
              // 解析分析描述
              if (item.opt_des && typeof item.opt_des === "string") {
                mol.analysis = {
                  description: item.opt_des,
                  explanation: item.opt_des,
                };
              }
              
              // 根据是否在 passed_items 中决定添加到 passed 还是 pending
              const isInPassed = passed.some((m) => m.smiles === item.smiles);
              if (!isInPassed) {
                pending.push(mol);
              }
            }
          }
        }
      }
      
      // 找到最佳分子
      const allMolecules = [...passed, ...pending];
      const best = allMolecules.reduce((bestMol, mol) => {
        const bestScore = bestMol?.score?.total || 0;
        const molScore = mol?.score?.total || 0;
        return molScore > bestScore ? mol : bestMol;
      }, null as Partial<Molecule> | null);
      
      snapshots.push({ iter, passed, pending, best });
    }
    
    setIterationSnapshots(snapshots);
  };

  // 处理执行错误
  const handleExecutionError = (error: string) => {
    setExecutionState("failed");
    toast.error(error);
  };

  // 处理日志更新
  const handleLogUpdate = (newLines: string[]) => {
    setLogLines((prev) => [...prev, ...newLines]);
  };

  // 处理节点输出更新（用于工作流图状态更新）
  const handleNodeOutputsUpdate = (outputs: Record<string, any>) => {
    setNodeOutputs((prev) => ({ ...prev, ...outputs }));
  };

  // 处理选择历史记录 - 从执行历史还原完整状态
  const handleSelectHistory = async (historyId: string) => {
    try {
      const result = await getExecutionHistory(historyId);
      if (result.success && result.history) {
        const history = result.history;
        
        // 还原基本信息
        onObjectiveChange(history.objective);
        onConstraintsChange(history.constraints);
        setRunId(history.runId);
        setSelectedWorkflowId(history.workflowId);
        
        // 还原执行状态
        setExecutionState(history.executionState);
        
        // 还原执行日志
        if (history.executionLogs) {
          setLogLines(history.executionLogs);
        }
        
        // 还原节点输出
        if (history.nodeOutputs) {
          setNodeOutputs(history.nodeOutputs);
        }
        
        // 还原迭代节点输出（将对象转换回 Map）
        if (history.iterationNodeOutputs) {
          const iterationNodeOutputsMap = new Map<number, Record<string, any>>();
          for (const [iterStr, outputs] of Object.entries(history.iterationNodeOutputs)) {
            const iter = parseInt(iterStr, 10);
            if (!isNaN(iter)) {
              iterationNodeOutputsMap.set(iter, outputs as Record<string, any>);
            }
          }
          setIterationNodeOutputs(iterationNodeOutputsMap);
        }
        
        // 还原迭代快照
        if (history.iterationSnapshots) {
          setIterationSnapshots(history.iterationSnapshots);
        }
        
        // 还原工作流图
        if (history.workflowGraph) {
          setWorkflowGraph(history.workflowGraph);
        }
        
        // 还原候选分子
        if (history.candidateMolecules) {
          setMolecules(history.candidateMolecules);
          setHistoryMolecules(history.candidateMolecules);
        }
        
        // 构建 executionResult（用于兼容性）
        if (history.executionState === "completed" && history.candidateMolecules) {
          setExecutionResult({
            mode: "workflow",
            workflowResult: {
              state: "completed",
              workflowId: history.workflowId,
              runId: history.runId,
              molecules: history.candidateMolecules,
            },
          });
        }
        
        toast.success("历史记录加载成功");
      } else {
        toast.error("加载历史记录失败");
      }
    } catch (error: any) {
      console.error("Failed to load execution history:", error);
      toast.error(`加载历史记录失败: ${error.message}`);
    }
  };

  // 格式化约束摘要（用于顶部显示）
  const formatConstraintsSummary = (): string => {
    const enabled = constraints.filter((c) => c.enabled);
    if (enabled.length === 0) return "无约束";
    return enabled.map((c) => c.name).join("、");
  };

  // 格式化目标摘要（用于顶部显示）
  const formatObjectiveSummary = (): string => {
    const text = objective.text.trim();
    if (text.length === 0) return "未设置研究目标";
    if (text.length > 60) return text.substring(0, 60) + "...";
    return text;
  };

  return (
    <div className="flex h-screen flex-col bg-slate-50 dark:bg-slate-950">
      {/* 顶部信息条 */}
      <div className="flex-shrink-0 border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
        <div className="container mx-auto max-w-[1920px] px-4 py-3">
          <div className="flex items-center gap-4">
            {/* 研究目标摘要 */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">研究目标：</span>
                <span className="truncate text-sm text-slate-900 dark:text-slate-100" title={objective.text}>
                  {formatObjectiveSummary()}
                </span>
                    {onEditObjective && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={onEditObjective}
                        title="编辑研究目标"
                      >
                        <Edit2 className="h-3 w-3" />
                      </Button>
                    )}
              </div>
            </div>

            {/* 工作流选择 + 执行按钮 */}
            <div className="flex items-center gap-2">
              <WorkflowRunnerPanel
                objective={objective}
                constraints={constraints}
                onExecutionStart={handleExecutionStart}
                onExecutionComplete={handleExecutionComplete}
                onExecutionError={handleExecutionError}
                onLogUpdate={handleLogUpdate}
                onNodeOutputsUpdate={handleNodeOutputsUpdate}
                onNodeStart={handleNodeStart}
                onNodeEnd={handleNodeEnd}
                onIterationNodeOutputsUpdate={handleIterationNodeOutputsUpdate}
                onWorkflowGraphLoad={setWorkflowGraph}
                executionState={executionState}
              />
            </div>

            {/* 运行历史按钮 */}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setHistoryDialogOpen(true)}
              className="flex items-center gap-2"
            >
              <History className="h-4 w-4" />
              运行历史
            </Button>
          </div>
        </div>
      </div>

      {/* 三列主体区域 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左列：执行日志 */}
        <div className="w-80 flex-shrink-0 border-r border-slate-200 dark:border-slate-700">
          <ExecutionLogPanel
            objective={objective}
            constraints={constraints}
            logLines={logLines}
            molecules={molecules}
            iterationSnapshots={iterationSnapshots}
            nodeOutputs={nodeOutputs}
            iterationNodeOutputs={iterationNodeOutputs}
            workflowGraph={workflowGraph}
            executionState={executionState}
          />
        </div>

        {/* 中列：工作流图 + 迭代分析 */}
        <div className="flex flex-1 flex-col overflow-hidden border-r border-slate-200 dark:border-slate-700">
          {/* 工作流图 */}
          <div className="h-1/2 flex-shrink-0 border-b border-slate-200 dark:border-slate-700">
            {workflowGraph ? (
              <WorkflowGraphView
                graph={workflowGraph}
                nodeOutputs={nodeOutputs}
                runningNodeIds={runningNodeIds}
                executionState={executionState}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-slate-400 dark:text-slate-500">
                <div className="text-center">
                  <p className="text-sm">请先选择并加载工作流</p>
                </div>
              </div>
            )}
          </div>

          {/* 迭代分析面板 */}
          <div className="flex-1 overflow-hidden">
          <IterationAnalyticsPanel
            nodeOutputs={nodeOutputs}
            molecules={molecules}
            iterationSnapshots={iterationSnapshots}
            iterationNodeOutputs={iterationNodeOutputs}
            workflowGraph={workflowGraph}
            executionState={executionState}
          />
          </div>
        </div>

        {/* 右列：候选分子详情 */}
        <div className="w-96 flex-shrink-0 overflow-y-auto">
          <CandidateListPanel
            molecules={molecules}
            constraints={constraints}
            executionState={executionState}
            initialMolecules={historyMolecules}
            objective={objective}
            evaluationModel={executionResult?.evaluationModel || executionResult?.selectedModel}
            iterationSnapshots={iterationSnapshots}
            iterationNodeOutputs={iterationNodeOutputs}
            workflowGraph={workflowGraph}
          />
        </div>
      </div>

      {/* 执行历史记录对话框 */}
      <ExecutionHistoryDialog
        open={historyDialogOpen}
        onClose={() => setHistoryDialogOpen(false)}
        onSelect={handleSelectHistory}
      />
    </div>
  );
}
