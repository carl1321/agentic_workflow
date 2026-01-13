"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "~/components/ui/card";
import { Button } from "~/components/ui/button";
import { Label } from "~/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { ArrowLeft, Play, Loader2, CheckCircle2, XCircle, Workflow } from "lucide-react";
import { ModelSelector } from "~/components/workflow/editor/components/ModelSelector";
import { listWorkflows, getDraft, executeWorkflowStream, type Workflow, type WorkflowExecutionEvent } from "~/core/api/workflow";
import { executeTool } from "~/core/api/tools";
import { apiRequest } from "~/core/api/api-client";
import { useStore } from "~/core/store";
import { parseSMILESFromText, extractMoleculesFromWorkflowResult } from "../utils/molecule";
import type { DesignObjective, Constraint, ExecutionMode, ExecutionResult, Molecule } from "../types";
import { ReactFlow, Node, Edge, useNodesState, useEdgesState, Controls, Background, BackgroundVariant, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { StartNode } from "~/components/workflow/editor/nodes/StartNode";
import { EndNode } from "~/components/workflow/editor/nodes/EndNode";
import { LLMNode } from "~/components/workflow/editor/nodes/LLMNode";
import { ToolNode } from "~/components/workflow/editor/nodes/ToolNode";
import { ConditionNode } from "~/components/workflow/editor/nodes/ConditionNode";
import { LoopNode } from "~/components/workflow/editor/nodes/LoopNode";
import { toast } from "sonner";

const nodeTypes = {
  start: StartNode,
  end: EndNode,
  llm: LLMNode,
  tool: ToolNode,
  condition: ConditionNode,
  loop: LoopNode,
};

interface Step2RunDesignLabProps {
  /** 上一步回调 */
  onBack: () => void;
  /** 研究目标 */
  objective: DesignObjective;
  /** 约束条件 */
  constraints: Constraint[];
  /** 执行完成回调 */
  onExecutionComplete: (result: ExecutionResult) => void;
  /** 右上角操作区（例如：运行历史按钮） */
  headerRight?: React.ReactNode;
}

/**
 * Step 2: 运行设计实验室
 */
export function Step2RunDesignLab({
  onBack,
  objective,
  constraints,
  onExecutionComplete,
  headerRight,
}: Step2RunDesignLabProps) {
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("model");
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>("");
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(false);
  const [executionState, setExecutionState] = useState<"idle" | "running" | "completed" | "failed">("idle");
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [modelResult, setModelResult] = useState<string | null>(null);
  const [workflowRunId, setWorkflowRunId] = useState<string | null>(null);
  const workflowNodeOutputsRef = useRef<Record<string, any>>({});
  
  // 工作流可视化相关状态
  const [workflowNodes, setWorkflowNodes, onNodesChange] = useNodesState([]);
  const [workflowEdges, setWorkflowEdges, onEdgesChange] = useEdgesState([]);
  const [workflowLoaded, setWorkflowLoaded] = useState(false);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);

  const selectedModel = useStore((state) => state.selectedModel);
  // 模型执行：评估模型（可与生成模型不同）
  const [modelEvaluationModel, setModelEvaluationModel] = useState<string>("");
  const hasTouchedModelEvalRef = useRef(false);
  // 工作流执行：评估模型（用于Step3评估），默认 Qwen-235B-Instruct
  const [workflowEvaluationModel, setWorkflowEvaluationModel] = useState<string>("Qwen-235B-Instruct");

  // 默认让“模型评估模型”跟随“生成模型”，但一旦用户手动改过就不再自动覆盖
  useEffect(() => {
    if (!hasTouchedModelEvalRef.current && selectedModel && selectedModel.length > 0) {
      setModelEvaluationModel(selectedModel);
    }
  }, [selectedModel]);

  // 将 Step1 的研究目标 + 关键约束拼成工作流 start 节点的输入（用于 {{start.output}} 动态替换）
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
    if (executionMode === "workflow") {
      loadWorkflows();
    }
  }, [executionMode]);

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
        // 转换节点和边
        const nodes: Node[] = (draft.graph.nodes || []).map((node: any) => ({
          ...node,
          data: {
            ...node.data,
            executionStatus: "pending",
          },
        }));
        const edges: Edge[] = draft.graph.edges || [];
        
        setWorkflowNodes(nodes);
        setWorkflowEdges(edges);
        setWorkflowLoaded(true);
      }
    } catch (error: any) {
      console.error("Failed to load workflow:", error);
      toast.error("加载工作流失败");
      setLoadingWorkflow(false);
    } finally {
      setLoadingWorkflow(false);
    }
  }, [selectedWorkflowId, setWorkflowNodes, setWorkflowEdges]);

  // 当选择工作流时自动加载
  useEffect(() => {
    if (executionMode === "workflow" && selectedWorkflowId) {
      loadSelectedWorkflow();
    }
  }, [executionMode, selectedWorkflowId, loadSelectedWorkflow]);

  // 更新节点执行状态
  const updateNodeExecutionStatus = useCallback((
    nodeId: string,
    status: "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled",
    data?: any
  ) => {
    setWorkflowNodes((nds) =>
      nds.map((node) => {
        if (node.id === nodeId) {
          return {
            ...node,
            data: {
              ...node.data,
              executionStatus: status,
              executionResult: data,
            },
          };
        }
        return node;
      })
    );
  }, [setWorkflowNodes]);

  // 执行模型
  const executeModel = async () => {
    const generationModel = selectedModel;
    const evaluationModel = modelEvaluationModel || generationModel;

    if (!generationModel) {
      toast.error("请先选择模型");
      return;
    }
    if (!evaluationModel) {
      toast.error("请先选择评估模型");
      return;
    }

    try {
      setExecutionState("running");
      setExecutionError(null);
      setModelResult(null);

      // 使用选择的LLM模型生成分子，将objective和constraints作为prompt
      console.log("Executing model with:", {
        model: generationModel,
        objective: objective.text.substring(0, 50) + "...",
        constraintsCount: constraints.length,
        evaluationModel,
      });
      
      const generateResult = await apiRequest<{
        success: boolean;
        result: string;
      }>("sam-design/generate-molecules", {
        method: "POST",
        body: JSON.stringify({
          model: generationModel,
          objective: objective.text,
          constraints: constraints.map((c) => ({
            name: c.name,
            value: c.value,
            enabled: c.enabled,
          })),
        }),
      });
      
      console.log("Model execution result:", {
        success: generateResult.success,
        resultLength: generateResult.result?.length || 0,
      });

      if (!generateResult.success || !generateResult.result || generateResult.result.trim().length === 0) {
        throw new Error("模型执行返回空结果");
      }

      const result = generateResult.result;

      // 解析结果为分子数组
      const smilesList = parseSMILESFromText(result);
      const molecules: Partial<Molecule>[] = smilesList.map((smiles, index) => ({
        index: index + 1,
        smiles,
      }));

      if (molecules.length === 0) {
        throw new Error("未能从模型响应中解析出任何SMILES分子");
      }

      setModelResult(result);
      setExecutionState("completed");
      toast.success(`模型执行完成，生成了 ${molecules.length} 个分子`);

      // 通知父组件
      onExecutionComplete({
        mode: "model",
        // selectedModel 兼容旧逻辑：表示评估模型
        selectedModel: evaluationModel || undefined,
        generationModel: generationModel || undefined,
        evaluationModel: evaluationModel || undefined,
        modelResult: {
          state: "completed",
          result: result,
          molecules: molecules,
        },
      });
    } catch (error: any) {
      console.error("Model execution failed:", error);
      const errorMessage = error?.message || error?.toString() || "模型执行失败，请稍后重试";
      setExecutionError(errorMessage);
      setExecutionState("failed");
      toast.error(errorMessage);
      
      onExecutionComplete({
        mode: "model",
        selectedModel: (modelEvaluationModel || selectedModel) || undefined,
        generationModel: selectedModel || undefined,
        evaluationModel: (modelEvaluationModel || selectedModel) || undefined,
        modelResult: {
          state: "failed",
          error: errorMessage,
        },
      });
    }
  };

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
      setExecutionState("running");
      setExecutionError(null);
      workflowNodeOutputsRef.current = {}; // 重置节点输出
      
      // 重置所有节点状态
      setWorkflowNodes((nds) =>
        nds.map((node) => ({
          ...node,
          data: {
            ...node.data,
            executionStatus: "pending",
          },
        }))
      );

      // 准备输入参数
      const startInput = buildWorkflowStartInput();
      const inputs: Record<string, any> = {
        // start 节点优先读取 inputs.input，并将其作为 start.output（用于工作流 prompt 模板 {{start.output}}）
        input: startInput,
        // 额外保留结构化字段，方便工作流里有节点想引用（例如通过工具/模板解析 start.output 或未来扩展）
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
      
      try {
        for await (const event of executeWorkflowStream({
          workflowId: selectedWorkflowId,
          inputs,
        })) {
          if (event.type === "run_start") {
            runId = event.run_id || null;
            setWorkflowRunId(runId);
            toast.success("工作流运行已启动");
          } else if (event.type === "log") {
            const logEvent = event.event;
            const nodeId = event.node_id;

            if (nodeId) {
              if (logEvent === "node_ready") {
                updateNodeExecutionStatus(nodeId, "ready");
              } else if (logEvent === "node_start") {
                updateNodeExecutionStatus(nodeId, "running", {
                  startTime: event.time,
                  inputs: event.payload?.inputs,
                });
              } else if (logEvent === "node_end") {
                const payload = event.payload || {};
                if (payload.status === "success") {
                  updateNodeExecutionStatus(nodeId, "success", {
                    endTime: event.time,
                    outputs: payload.outputs,
                    metrics: payload.metrics,
                  });
                  
                  // 收集节点输出，用于后续提取分子数据（使用ref确保同步访问）
                  workflowNodeOutputsRef.current[nodeId] = payload.outputs || {};
                } else {
                  updateNodeExecutionStatus(nodeId, "error", {
                    endTime: event.time,
                    error: payload.error,
                  });
                  hasError = true;
                }
              } else if (logEvent === "node_error") {
                updateNodeExecutionStatus(nodeId, "error", {
                  endTime: event.time,
                  error: event.payload?.error,
                });
                hasError = true;
              } else if (logEvent === "node_skipped") {
                updateNodeExecutionStatus(nodeId, "skipped");
              }
            }
          } else if (event.type === "run_end") {
            setExecutionState(event.success ? "completed" : "failed");
            
            // 重要：Step2(workflow) 的最终 output 需要作为 Step3 的分子生成数据来源
            // 这里从“最终 workflow outputs / node_outputs”中提取结构化 smiles 数组
            let molecules: Partial<Molecule>[] | undefined;
            if (event.success && Object.keys(workflowNodeOutputsRef.current).length > 0) {
              try {
                molecules = extractMoleculesFromWorkflowResult(workflowNodeOutputsRef.current);
                if (molecules.length > 0) {
                  console.log(`Extracted ${molecules.length} molecules from workflow node_outputs`);
                }
              } catch (err) {
                console.warn("Failed to extract molecules from workflow result:", err);
              }
            }
            if (event.success && (!molecules || molecules.length === 0)) {
              console.warn("Workflow completed but no molecules were extracted from workflow outputs. Please check workflow end/loop output structure.");
            }
            
            if (event.success) {
              toast.success(`工作流执行完成${molecules && molecules.length > 0 ? `，提取了 ${molecules.length} 个分子` : ""}`);
              onExecutionComplete({
                mode: "workflow",
                // selectedModel 兼容旧逻辑：表示评估模型
                selectedModel: workflowEvaluationModel || undefined,
                evaluationModel: workflowEvaluationModel || undefined,
                workflowResult: {
                  state: "completed",
                  workflowId: selectedWorkflowId,
                  runId: runId || undefined,
                  molecules: molecules,
                },
              });
            } else {
              const errorMsg = "工作流执行失败";
              setExecutionError(errorMsg);
              toast.error(errorMsg);
              onExecutionComplete({
                mode: "workflow",
                selectedModel: workflowEvaluationModel || undefined,
                evaluationModel: workflowEvaluationModel || undefined,
                workflowResult: {
                  state: "failed",
                  workflowId: selectedWorkflowId,
                  runId: runId || undefined,
                  error: errorMsg,
                },
              });
            }
            break;
          } else if (event.type === "error") {
            const errorMsg = event.error || "工作流执行失败";
            setExecutionError(errorMsg);
            setExecutionState("failed");
            toast.error(errorMsg);
            onExecutionComplete({
              mode: "workflow",
              selectedModel: workflowEvaluationModel || undefined,
              evaluationModel: workflowEvaluationModel || undefined,
              workflowResult: {
                state: "failed",
                workflowId: selectedWorkflowId,
                runId: runId || undefined,
                error: errorMsg,
              },
            });
            break;
          }
        }
      } catch (streamError: any) {
        // 流式执行过程中的错误
        throw new Error(`流式执行错误: ${streamError?.message || "未知错误"}`);
      }
    } catch (error: any) {
      console.error("Workflow execution failed:", error);
      const errorMessage = error?.message || error?.toString() || "工作流执行失败，请稍后重试";
      setExecutionError(errorMessage);
      setExecutionState("failed");
      toast.error(errorMessage);
      onExecutionComplete({
        mode: "workflow",
        selectedModel: workflowEvaluationModel || undefined,
        evaluationModel: workflowEvaluationModel || undefined,
        workflowResult: {
          state: "failed",
          error: errorMessage,
        },
      });
    }
  };

  const handleStartDesign = () => {
    if (executionMode === "model") {
      executeModel();
    } else {
      executeWorkflow();
    }
  };

  const selectedWorkflow = workflows.find((w) => w.id === selectedWorkflowId);
  const canStart = executionMode === "model" 
    ? selectedModel !== null
    : selectedWorkflowId !== "";

  return (
    <div className="flex flex-col gap-6">
      {/* 顶部：标题 */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100 sm:text-xl">
            运行设计实验室
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            选择执行方式：使用模型直接生成或通过工作流执行
          </p>
        </div>
        {headerRight ? <div className="pt-1">{headerRight}</div> : null}
      </div>

      {/* 主要内容 */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">执行方式</CardTitle>
          <CardDescription className="text-sm">
            选择使用模型直接执行或通过工作流执行
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* 执行模式选择 */}
          <Tabs
            value={executionMode}
            onValueChange={(value) => {
              setExecutionMode(value as ExecutionMode);
              setExecutionState("idle");
              setExecutionError(null);
              setModelResult(null);
              setWorkflowRunId(null);
            }}
            className="w-full"
          >
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="model">模型执行</TabsTrigger>
              <TabsTrigger value="workflow">工作流执行</TabsTrigger>
            </TabsList>

            {/* 模型选择 */}
            <TabsContent value="model" className="space-y-4 mt-4">
            <div className="space-y-3">
              <Label className="text-sm font-medium">生成模型</Label>
              <ModelSelector
                value={selectedModel || ""}
                onChange={(value) => {
                  useStore.getState().setSelectedModel(value);
                }}
              />
              {selectedModel && (
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  将使用该模型生成分子
                </p>
              )}
            </div>
            <div className="space-y-3">
              <Label className="text-sm font-medium">评估模型</Label>
              <ModelSelector
                value={modelEvaluationModel || ""}
                onChange={(value) => {
                  hasTouchedModelEvalRef.current = true;
                  setModelEvaluationModel(value);
                }}
              />
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Step 3 将使用该模型对候选分子进行评估与打分
              </p>
            </div>
          </TabsContent>

          {/* 工作流选择 */}
          <TabsContent value="workflow" className="space-y-4 mt-4">
            <div className="space-y-3">
              <Label className="text-sm font-medium">选择工作流</Label>
              <Select
                value={selectedWorkflowId}
                onValueChange={setSelectedWorkflowId}
                disabled={loadingWorkflows}
              >
                <SelectTrigger>
                  <SelectValue placeholder={loadingWorkflows ? "加载中..." : "请选择工作流"} />
                </SelectTrigger>
                <SelectContent>
                  {workflows.map((workflow) => (
                    <SelectItem key={workflow.id} value={workflow.id}>
                      <div className="flex flex-col">
                        <span className="font-medium">{workflow.name}</span>
                        {workflow.description && (
                          <span className="text-xs text-muted-foreground">
                            {workflow.description}
                          </span>
                        )}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedWorkflow && (
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-3">
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                    {selectedWorkflow.name}
                  </p>
                  {selectedWorkflow.description && (
                    <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                      {selectedWorkflow.description}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-medium">评估模型</Label>
              <ModelSelector
                value={workflowEvaluationModel || ""}
                onChange={(value) => setWorkflowEvaluationModel(value)}
              />
              <p className="text-xs text-slate-500 dark:text-slate-400">
                工作流执行完成后，Step 3 将使用该模型对最终输出的分子进行评估与打分
              </p>
            </div>

            {/* 工作流可视化 */}
            {selectedWorkflowId && (
              <div className="space-y-3">
                <Label className="text-sm font-medium">工作流预览</Label>
                <div className="h-[400px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 relative overflow-hidden">
                  {loadingWorkflow ? (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-50 dark:bg-slate-900">
                      <div className="flex flex-col items-center gap-3">
                        <Loader2 className="h-6 w-6 animate-spin text-blue-600 dark:text-blue-400" />
                        <p className="text-sm text-slate-600 dark:text-slate-400">加载工作流中...</p>
                      </div>
                    </div>
                  ) : workflowLoaded ? (
                    <ReactFlowProvider>
                      <ReactFlow
                        nodes={workflowNodes}
                        edges={workflowEdges}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        nodeTypes={nodeTypes}
                        fitView
                        minZoom={0.1}
                        maxZoom={2}
                        className="bg-slate-50 dark:bg-slate-900"
                      >
                        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
                        <Controls className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm" />
                      </ReactFlow>
                    </ReactFlowProvider>
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-50 dark:bg-slate-900">
                      <p className="text-sm text-slate-500 dark:text-slate-400">请选择工作流</p>
                    </div>
                  )}
                </div>
              </div>
            )}
            </TabsContent>
          </Tabs>

          {/* 执行状态 */}
          {executionState === "running" && (
            <div className="flex items-center gap-3 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 p-4">
              <Loader2 className="h-5 w-5 animate-spin text-blue-600 dark:text-blue-400" />
              <div className="flex-1">
                <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
                  {executionMode === "model" ? "模型执行中..." : "工作流执行中..."}
                </p>
                <p className="text-xs text-blue-700 dark:text-blue-300 mt-1">
                  请稍候，正在处理您的请求
                </p>
              </div>
            </div>
          )}

          {executionState === "completed" && (
            <div className="flex items-center gap-3 rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 p-4">
              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
              <div className="flex-1">
                <p className="text-sm font-medium text-green-900 dark:text-green-100">
                  执行完成
                </p>
                {modelResult && (
                  <p className="text-xs text-green-700 dark:text-green-300 mt-1 line-clamp-2">
                    {modelResult.substring(0, 100)}...
                  </p>
                )}
              </div>
            </div>
          )}

          {executionState === "failed" && executionError && (
            <div className="flex items-center gap-3 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4">
              <XCircle className="h-5 w-5 text-red-600 dark:text-red-400" />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-900 dark:text-red-100">
                  执行失败
                </p>
                <p className="text-xs text-red-700 dark:text-red-300 mt-1">
                  {executionError}
                </p>
              </div>
            </div>
          )}

          {/* 操作按钮 */}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between pt-4 border-t">
            <Button type="button" variant="outline" onClick={onBack} className="w-full sm:w-auto">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回上一步
            </Button>
            <Button
              type="button"
              onClick={handleStartDesign}
              disabled={!canStart || executionState === "running" || loadingWorkflow}
              className="w-full sm:w-auto"
            >
              {executionState === "running" ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  执行中...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  开始设计
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
