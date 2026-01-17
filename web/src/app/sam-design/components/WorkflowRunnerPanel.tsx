"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback, useRef } from "react";
import { Button } from "~/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Play, Loader2 } from "lucide-react";
import { listWorkflows, getDraft, executeWorkflowStream, type Workflow, type WorkflowExecutionEvent } from "~/core/api/workflow";
import { extractMoleculesFromWorkflowResult, extractMoleculesFromEndNode } from "../utils/molecule";
import { toast } from "sonner";
import type { DesignObjective, Constraint, ExecutionResult, Molecule } from "../types";

interface WorkflowRunnerPanelProps {
  objective: DesignObjective;
  constraints: Constraint[];
  onExecutionStart: (workflowId: string, runId: string) => void;
  onExecutionComplete: (result: ExecutionResult, molecules: Molecule[], nodeOutputs: Record<string, any>) => void;
  onExecutionError: (error: string) => void;
  onLogUpdate: (lines: string[]) => void;
  onNodeOutputsUpdate: (outputs: Record<string, any>) => void;
  onNodeStart?: (nodeId: string) => void;
  onNodeEnd?: (nodeId: string, iteration?: number, loopId?: string) => void;
  onIterationNodeOutputsUpdate?: (iterationNodeOutputs: Map<number, Record<string, any>>) => void;
  onWorkflowGraphLoad: (graph: { nodes: any[]; edges: any[] }) => void;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 工作流运行器面板（顶部：工作流选择 + 执行按钮）
 */
export function WorkflowRunnerPanel({
  objective,
  constraints,
  onExecutionStart,
  onExecutionComplete,
  onExecutionError,
  onLogUpdate,
  onNodeOutputsUpdate,
  onNodeStart,
  onNodeEnd,
  onIterationNodeOutputsUpdate,
  onWorkflowGraphLoad,
  executionState,
}: WorkflowRunnerPanelProps) {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>("");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(false);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);
  const [workflowLoaded, setWorkflowLoaded] = useState(false);
  const workflowNodeOutputsRef = useRef<Record<string, any>>({});
  const iterationNodeOutputsRef = useRef<Map<number, Record<string, any>>>(new Map());
  const workflowGraphRef = useRef<{ nodes: any[]; edges: any[] } | null>(null);
  const [workflowEvaluationModel, setWorkflowEvaluationModel] = useState<string>("Qwen-235B-Instruct");

  // 构建工作流输入
  const buildWorkflowStartInput = useCallback(() => {
    const enabledConstraints = constraints.filter((c) => c.enabled);
    const constraintsText =
      enabledConstraints.length === 0
        ? "（无）"
        : enabledConstraints
            .map((c, idx) => {
              const valueText =
                typeof c.value === "string" || typeof c.value === "number"
                  ? String(c.value)
                  : `min=${c.value.min}, max=${c.value.max}${c.unit ? ` ${c.unit}` : ""}`;
              return `${idx + 1}. ${c.name}: ${valueText}`;
            })
            .join("\n");

    return `研究目标：\n${objective.text}\n\n关键约束：\n${constraintsText}\n`;
  }, [objective.text, constraints]);

  // 加载工作流列表
  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      setLoadingWorkflows(true);
      const response = await listWorkflows({ limit: 100 });
      setWorkflows(response.workflows || []);
    } catch (error: any) {
      console.error("Failed to load workflows:", error);
      toast.error("加载工作流列表失败");
    } finally {
      setLoadingWorkflows(false);
    }
  };

  // 加载选中的工作流
  const loadSelectedWorkflow = useCallback(async () => {
    if (!selectedWorkflowId) return;
    
    try {
      setLoadingWorkflow(true);
      setWorkflowLoaded(false);
      const draft = await getDraft(selectedWorkflowId);
      
      if (draft.graph) {
        const graph = {
          nodes: draft.graph.nodes || [],
          edges: draft.graph.edges || [],
        };
        workflowGraphRef.current = graph;
        onWorkflowGraphLoad(graph);
        setWorkflowLoaded(true);
      }
    } catch (error: any) {
      console.error("Failed to load workflow:", error);
      toast.error("加载工作流失败");
      setLoadingWorkflow(false);
    } finally {
      setLoadingWorkflow(false);
    }
  }, [selectedWorkflowId, onWorkflowGraphLoad]);

  // 当选择工作流时自动加载
  useEffect(() => {
    if (selectedWorkflowId) {
      loadSelectedWorkflow();
    }
  }, [selectedWorkflowId, loadSelectedWorkflow]);

  // 执行工作流
  const executeWorkflow = async () => {
    if (!selectedWorkflowId) {
      toast.error("请先选择工作流");
      return;
    }

    if (!workflowLoaded) {
      toast.error("工作流尚未加载完成，请稍候");
      return;
    }

    try {
      workflowNodeOutputsRef.current = {}; // 重置节点输出
      
      // 准备输入参数
      const startInput = buildWorkflowStartInput();
      const inputs: Record<string, any> = {
        input: startInput,
        objective: objective.text,
        constraints: constraints.map((c) => ({
          name: c.name,
          type: c.type,
          value: c.value,
          enabled: c.enabled,
        })),
      };

      // 流式执行工作流
      let runId: string | null = null;
      let hasError = false;
      workflowNodeOutputsRef.current = {}; // 重置节点输出
      iterationNodeOutputsRef.current.clear(); // 重置迭代节点输出
      // 立刻同步清空前端（避免复用旧 Map 引用/旧迭代残留）
      if (onIterationNodeOutputsUpdate) {
        onIterationNodeOutputsUpdate(new Map());
      }
      
      try {
        for await (const event of executeWorkflowStream({
          workflowId: selectedWorkflowId,
          inputs,
          // 默认使用草稿执行，避免“改了迭代次数仍执行旧发布版本”
          useDraft: true,
        })) {
          if (event.type === "run_start") {
            runId = event.run_id || null;
            if (runId) {
              onExecutionStart(selectedWorkflowId, runId);
              // 工作流启动日志（调试用，主日志会显示更友好的信息）
              // onLogUpdate([`>>> 工作流运行已启动 (run_id: ${runId})`]);
            }
            toast.success("工作流运行已启动");
          } else if (event.type === "log") {
            const logEvent = event.event;
            const nodeId = event.node_id;

            if (nodeId) {
              if (logEvent === "node_start") {
                // 通知节点开始执行
                if (onNodeStart) {
                  onNodeStart(nodeId);
                }
              } else if (logEvent === "node_end") {
                const payload = event.payload || {};
                if (payload.status === "success") {
                  // 收集节点输出
                  const outputs = payload.outputs || {};
                  workflowNodeOutputsRef.current[nodeId] = outputs;
                  
                  // 展开 outputs 的内部 key（解决循环节点输出的嵌套问题）
                  const flattenedOutputs: Record<string, any> = { [nodeId]: outputs };
                  if (outputs && typeof outputs === "object") {
                    for (const [innerKey, innerValue] of Object.entries(outputs)) {
                      if (innerValue && typeof innerValue === "object") {
                        if ("passed_items" in innerValue || "pending_items" in innerValue || "iterations" in innerValue) {
                          workflowNodeOutputsRef.current[innerKey] = innerValue;
                          flattenedOutputs[innerKey] = innerValue;
                        }
                      }
                    }
                  }
                  
                  // 从 payload 中提取迭代信息
                  const iteration = payload.iteration !== undefined ? payload.iteration : null;
                  const loopId = payload.loop_id || null;
                  
                  // 如果节点属于某个迭代，将其输出添加到对应迭代的集合中
                  if (iteration !== null && typeof iteration === "number") {
                    if (!iterationNodeOutputsRef.current.has(iteration)) {
                      iterationNodeOutputsRef.current.set(iteration, {});
                    }
                    const iterOutputs = iterationNodeOutputsRef.current.get(iteration)!;
                    iterOutputs[nodeId] = outputs;
                    // 同时展开内部 key
                    if (outputs && typeof outputs === "object") {
                      for (const [innerKey, innerValue] of Object.entries(outputs)) {
                        if (innerValue && typeof innerValue === "object") {
                          if ("passed_items" in innerValue || "pending_items" in innerValue || "iterations" in innerValue) {
                            iterOutputs[innerKey] = innerValue;
                          }
                        }
                      }
                    }
                    
                    // 通知迭代节点输出更新
                    if (onIterationNodeOutputsUpdate) {
                      onIterationNodeOutputsUpdate(new Map(iterationNodeOutputsRef.current));
                    }
                  }
                  
                  // 通知节点执行完成
                  if (onNodeEnd) {
                    onNodeEnd(nodeId, iteration !== null ? iteration : undefined, loopId || undefined);
                  }
                  
                  onNodeOutputsUpdate(flattenedOutputs);
                } else {
                  onLogUpdate([`>>> 节点 ${nodeId} 执行失败: ${payload.error || "未知错误"}`]);
                  hasError = true;
                }
              } else if (logEvent === "node_error") {
                onLogUpdate([`>>> 节点 ${nodeId} 发生错误: ${event.payload?.error || "未知错误"}`]);
                hasError = true;
              }
            }
          } else if (event.type === "run_end") {
            if (event.success) {
              // 从end节点提取最终候选分子
              let molecules: Molecule[] = [];
              if (Object.keys(workflowNodeOutputsRef.current).length > 0) {
                try {
                  // 优先从end节点提取
                  const partialMolecules = extractMoleculesFromEndNode(
                    workflowNodeOutputsRef.current,
                    workflowGraphRef.current
                  );
                  
                  // 如果从end节点没提取到，回退到原来的方法（兼容性）
                  const finalMolecules = partialMolecules.length > 0 
                    ? partialMolecules 
                    : extractMoleculesFromWorkflowResult(workflowNodeOutputsRef.current);
                  
                  // 过滤：只保留评分 >= 7 的分子
                  const filteredMolecules = finalMolecules.filter((m) => {
                    const score = m.score?.total || 0;
                    return score >= 7;
                  });
                  
                  molecules = filteredMolecules.map((m, idx) => ({
                    index: idx + 1,
                    smiles: m.smiles || "",
                    scaffoldCondition: m.scaffoldCondition,
                    scaffoldSmiles: m.scaffoldSmiles,
                    imageUrl: m.imageUrl,
                    properties: m.properties,
                    score: m.score,
                    analysis: m.analysis,
                  })) as Molecule[];
                  
                  if (molecules.length > 0) {
                    onLogUpdate([`>>> 从end节点提取了 ${molecules.length} 个候选分子（评分 >= 7）`]);
                  } else if (finalMolecules.length > 0) {
                    onLogUpdate([`>>> 从end节点提取了 ${finalMolecules.length} 个分子，但均未达到7分阈值`]);
                  }
                } catch (err) {
                  console.warn("Failed to extract molecules from end node:", err);
                }
              }
              
              // 工作流完成日志（调试用，主日志会显示更友好的信息）
              // onLogUpdate([`>>> 工作流执行完成`]);
              toast.success(`工作流执行完成${molecules.length > 0 ? `，提取了 ${molecules.length} 个分子` : ""}`);
              
              onExecutionComplete(
                {
                  mode: "workflow",
                  evaluationModel: workflowEvaluationModel || undefined,
                  workflowResult: {
                    state: "completed",
                    workflowId: selectedWorkflowId,
                    runId: runId || undefined,
                    molecules: molecules,
                  },
                },
                molecules,
                workflowNodeOutputsRef.current
              );
            } else {
              const errorMsg = event.error || "工作流执行失败";
              onLogUpdate([`>>> ${errorMsg}`]);
              onExecutionError(errorMsg);
            }
          } else if (event.type === "error") {
            const errorMsg = event.error || "工作流执行出错";
            onLogUpdate([`>>> 错误: ${errorMsg}`]);
            onExecutionError(errorMsg);
          }
        }
      } catch (streamError: any) {
        const errorMsg = streamError?.message || "工作流流式执行失败";
        onLogUpdate([`>>> 流式执行错误: ${errorMsg}`]);
        onExecutionError(errorMsg);
      }
    } catch (error: any) {
      const errorMsg = error?.message || "执行工作流失败";
      onExecutionError(errorMsg);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Select
        value={selectedWorkflowId}
        onValueChange={setSelectedWorkflowId}
        disabled={executionState === "running" || loadingWorkflows}
      >
        <SelectTrigger className="w-[200px]">
          <SelectValue placeholder={loadingWorkflows ? "加载中..." : "选择工作流"} />
        </SelectTrigger>
        <SelectContent>
          {workflows.map((wf) => (
            <SelectItem key={wf.id} value={wf.id}>
              {wf.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      
      <Button
        onClick={executeWorkflow}
        disabled={!selectedWorkflowId || !workflowLoaded || executionState === "running"}
        size="sm"
        className="flex items-center gap-2"
      >
        {executionState === "running" ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            执行中
          </>
        ) : (
          <>
            <Play className="h-4 w-4" />
            执行
          </>
        )}
      </Button>
    </div>
  );
}
