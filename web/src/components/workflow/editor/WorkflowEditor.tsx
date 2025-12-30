// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useCallback, useMemo, useState, useRef, useEffect } from "react";
import {
  ReactFlow,
  Node,
  Edge,
  Connection,
  addEdge,
  useNodesState,
  useEdgesState,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  NodeTypes,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Button } from "~/components/ui/button";
import { ArrowLeft, Save, Play } from "lucide-react";
import { useDebouncedCallback } from "use-debounce";
import { StartNode } from "./nodes/StartNode";
import { EndNode } from "./nodes/EndNode";
import { LLMNode } from "./nodes/LLMNode";
import { ToolNode } from "./nodes/ToolNode";
import { ConditionNode } from "./nodes/ConditionNode";
import { LoopNode } from "./nodes/LoopNode";
import { NodeConfigPanel } from "./NodeConfigPanel";
import { EdgeConfigPanel } from "./EdgeConfigPanel";
import { NodePalette } from "./NodePalette";
import { nanoid } from "nanoid";
import { useRouter } from "next/navigation";
import { createRelease, executeWorkflowStream, getRunStatus, getWorkflowRuns, type WorkflowExecutionEvent } from "~/core/api/workflow";
import { toast } from "sonner";

// 参考 szlabAgent 的 LOOP_PADDING 常量
const LOOP_PADDING = {
  top: 65,    // 头部高度(40) + 内边距(25)
  right: 16,
  bottom: 20,
  left: 16,
};

const nodeTypes: NodeTypes = {
  start: StartNode,
  end: EndNode,
  llm: LLMNode,
  tool: ToolNode,
  condition: ConditionNode,
  loop: LoopNode,
};

interface WorkflowEditorProps {
  workflowId: string;
  workflowName: string;
  initialNodes: Node[];
  initialEdges: Edge[];
  onSave: (graph: { nodes: Node[]; edges: Edge[] }, isAutosave?: boolean) => Promise<any>;
  onBack: () => void;
}

// 规范化节点数据的函数（移出组件以在初始化时使用）
const normalizeNodesData = (nodes: Node[]): Node[] => {
  return nodes.map((node) => {
    const nodeData = node.data || {};
    
    // 为所有节点确保 taskName 和 displayName 都是字符串
    let taskName: string;
    let displayName: string;
    
    // 优先使用 taskName，其次是 nodeName (旧数据兼容)
    if (nodeData.taskName) {
      taskName = typeof nodeData.taskName === 'string' ? nodeData.taskName : String(nodeData.taskName);
    } else if (nodeData.nodeName) {
      taskName = typeof nodeData.nodeName === 'string' ? nodeData.nodeName : String(nodeData.nodeName);
    } else {
      // 为旧数据生成 taskName
      if (node.type === "start") {
        taskName = "start";
      } else if (node.type === "end") {
        taskName = "end";
      } else {
        // 统计同类型节点数量
        const sameTypeNodes = nodes.filter(n => n.type === node.type);
        const typeLabels: Record<string, string> = {
          llm: "LLM",
          tool: "工具",
          condition: "条件",
          loop: "loop",
        };
        const baseName = typeLabels[node.type || ""] || node.type || "节点";
        const index = sameTypeNodes.findIndex(n => n.id === node.id);
        taskName = index === 0 ? baseName : `${baseName}${index}`;
      }
    }
    
    // 确保 displayName 是字符串
    if (node.type === "start") {
      displayName = "开始";
    } else if (node.type === "end") {
      displayName = "结束";
    } else {
      displayName = typeof nodeData.displayName === 'string' 
        ? nodeData.displayName 
        : (typeof nodeData.label === 'string' ? nodeData.label : taskName);
    }
    
    // 确保所有可能被 ReactFlow 访问的属性都是字符串
    const normalizedLabel = typeof nodeData.label === 'string' ? nodeData.label : String(displayName);
    const normalizedTaskName = String(taskName);
    const normalizedDisplayName = String(displayName);
    
    return {
      ...node,
      // ReactFlow 可能直接访问节点的 label 属性
      label: normalizedLabel,
      // 移除 nodeName 属性，避免被浏览器插件误认为是 DOM 节点
      data: {
        ...nodeData,
        taskName: normalizedTaskName, // 重命名为 taskName
        nodeName: undefined, // 显式移除 nodeName
        displayName: normalizedDisplayName,
        label: normalizedLabel,
      },
    };
  });
};

// 处理节点布局关系的函数（移出组件以在初始化时使用）
const processNodesLayout = (nodes: Node[]): Node[] => {
  // 1. 先进行基本的规范化
  const normalized = normalizeNodesData(nodes);
  
  // 2. 建立父子关系
  return normalized.map((node) => {
    // 循环节点本身不需要特殊处理，但要确保尺寸正确
    if (node.type === "loop") {
      const loopWidth = node.data?.loopWidth || node.data?.loop_width || 600;
      const loopHeight = node.data?.loopHeight || node.data?.loop_height || 400;
      return {
        ...node,
        width: loopWidth,
        height: loopHeight,
        style: {
          ...(node.style || {}),
          pointerEvents: "auto",
          zIndex: (node.style as any)?.zIndex ?? 1,
        },
      };
    }
    
    const loopId = node.data?.loopId || node.data?.loop_id;
    if (!loopId) {
      // 如果节点之前有 parentId 但现在没有 loopId，说明需要解除关系
      if (node.parentId) {
           return {
              ...node,
              parentId: undefined,
              extent: undefined,
              data: {
                  ...node.data,
                  isLoopChild: undefined
              }
           }
      }
      return node;
    }
    
    // 查找循环节点
    const loopNode = normalized.find(n => n.id === loopId && n.type === "loop");
    if (!loopNode) {
      // 有 loopId 但找不到对应的循环节点，可能是数据不一致，清除 loopId
      return {
        ...node,
        parentId: undefined,
        extent: undefined,
        data: {
          ...node.data,
          loopId: undefined,
          loop_id: undefined,
          isLoopChild: undefined
        }
      };
    }
    
    // 计算相对位置和 extent
    const loopWidth = loopNode.data?.loopWidth || loopNode.data?.loop_width || loopNode.width || 600;
    const loopHeight = loopNode.data?.loopHeight || loopNode.data?.loop_height || loopNode.height || 400;
    
    // 确定当前位置是否已经是相对位置
    // 如果有 parentId 且等于 loopId，认为是相对位置
    // 否则认为是绝对位置，需要转换
    let position = node.position;
    
    if (node.parentId !== loopNode.id) {
       // 转换为相对位置
       const relativeX = node.position.x - loopNode.position.x - LOOP_PADDING.left;
       const relativeY = node.position.y - loopNode.position.y - LOOP_PADDING.top;
       position = {
           x: LOOP_PADDING.left + Math.max(0, relativeX),
           y: LOOP_PADDING.top + Math.max(0, relativeY)
       };
    }

    return {
      ...node,
      parentId: loopNode.id,
      position,
      extent: "parent", 
      draggable: true,
      style: {
        ...node.style,
        zIndex: 15,
        pointerEvents: "auto",
      },
      data: {
        ...node.data,
        isLoopChild: true,
      }
    };
  });
};

function WorkflowEditorInner({
  workflowId,
  workflowName,
  initialNodes,
  initialEdges,
  onSave,
  onBack,
}: WorkflowEditorProps) {
  // 使用 useMemo 初始化节点状态，避免 useEffect 中的二次渲染导致的闪烁
  const initialProcessedNodes = useMemo(() => processNodesLayout(initialNodes), [initialNodes]);
  
  const [nodes, setNodes, onNodesChangeRaw] = useNodesState(initialProcessedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  
  // 保持 normalizeNodes 引用以兼容旧代码（虽然现在主要使用 normalizeNodesData）
  const normalizeNodes = useCallback((nodes: Node[]) => normalizeNodesData(nodes), []);

  // 包装 setNodes，确保所有节点更新都经过规范化
  const setNodesNormalized = useCallback(
    (updater: Node[] | ((nodes: Node[]) => Node[])) => {
      setNodes((nds) => {
        const newNodes = typeof updater === 'function' ? updater(nds) : updater;
        return normalizeNodesData(newNodes);
      });
    },
    [setNodes]
  );
  
  // 这里的 processNodes 仅仅是为了兼容可能的内部调用，实际逻辑已提取到 processNodesLayout
  const processNodes = useCallback((nodes: Node[]) => processNodesLayout(nodes), []);

  // 修改 onNodesChange 逻辑
  const onNodesChange = useCallback(
    (changes: any) => {
      onNodesChangeRaw(changes);
    },
    [onNodesChangeRaw]
  );

  // 处理拖拽结束，检测是否进入/离开循环
  const onNodeDragStop = useCallback((_: React.MouseEvent, node: Node) => {
      // 获取最新的节点列表（包括位置更新后的）
      // 注意：这里需要通过回调获取最新 state，或者依赖 nodes
      // 但 onNodeDragStop 的 node 参数是拖拽后的最新状态
      
      setNodes((nds) => {
          const currentNode = nds.find(n => n.id === node.id);
          if (!currentNode) return nds;
          
          // 如果节点是 loop，更新其尺寸数据（如果被resize）
          if (currentNode.type === "loop") return nds;
          
          // 查找所有循环节点
          const loopNodes = nds.filter(n => n.type === "loop");
          const nodeBounds = {
              x: node.position.x,
              y: node.position.y,
              width: node.width || 160,
              height: node.height || 60
          };
          
          // 如果节点已经有 parentId，position 是相对的，需要转绝对来检测是否拖出
          let absoluteX = node.position.x;
          let absoluteY = node.position.y;
          const currentParent = nds.find(n => n.id === node.parentId);
          
          if (currentParent) {
              absoluteX += currentParent.position.x;
              absoluteY += currentParent.position.y;
          }
          
          const centerX = absoluteX + nodeBounds.width / 2;
          const centerY = absoluteY + nodeBounds.height / 2;

          // 检测是否在某个 loop 内
          let targetLoop: Node | undefined;
          for (const loop of loopNodes) {
              const loopW = loop.data?.loopWidth || loop.width || 600;
              const loopH = loop.data?.loopHeight || loop.height || 400;
              
              if (
                  centerX >= loop.position.x + LOOP_PADDING.left &&
                  centerX <= loop.position.x + loopW - LOOP_PADDING.right &&
                  centerY >= loop.position.y + LOOP_PADDING.top &&
                  centerY <= loop.position.y + loopH - LOOP_PADDING.bottom
              ) {
                  targetLoop = loop;
                  break;
              }
          }
          
          // 状态更新
          if (targetLoop) {
              // 进入或仍在 Loop 中
              if (currentNode.parentId !== targetLoop.id) {
                  // 进入新 Loop
                  const relativeX = absoluteX - targetLoop.position.x;
                  const relativeY = absoluteY - targetLoop.position.y;
                  
                  return nds.map(n => n.id === node.id ? {
                      ...n,
                      parentId: targetLoop!.id,
                      position: { x: relativeX, y: relativeY },
                      extent: "parent",
                      data: { ...n.data, loopId: targetLoop!.id, loop_id: targetLoop!.id }
                  } : n);
              }
              // 仍在同一个 Loop 中，ReactFlow 已更新位置，不需要额外处理
              // 但可以强制更新 data.relativeX 等如果需要
              return nds; 
          } else {
              // 不在任何 Loop 中
              if (currentNode.parentId) {
                  // 刚刚拖出 Loop
                  return nds.map(n => n.id === node.id ? {
                      ...n,
                      parentId: undefined,
                      extent: undefined,
                      position: { x: absoluteX, y: absoluteY }, // 恢复绝对坐标
                      data: { 
                          ...n.data, 
                          loopId: undefined, 
                          loop_id: undefined, 
                          isLoopChild: undefined 
                       }
                  } : n);
              }
          }
          
          return nds;
      });
  }, [setNodes]);

  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [nodeTypeToAdd, setNodeTypeToAdd] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null); // 当前运行的 ID
  const [isReady, setIsReady] = useState(false); // 画布是否准备就绪
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isUpdatingRef = useRef(false); // 防止无限递归的标志
  const router = useRouter();
  const { screenToFlowPosition, addNodes, fitView } = useReactFlow();
  
  // 初始化画布视图：等待布局稳定后显示
  useEffect(() => {
    // 延迟一帧执行 fitView，确保 ReactFlow 内部节点已挂载
    const timer = requestAnimationFrame(() => {
      // 关闭动画，避免缩放过程带来的“先模糊后清晰”的视觉闪烁
      fitView({ padding: 0.2, duration: 0 });
      // 稍微延迟显示，让浏览器有时间渲染第一帧
      setTimeout(() => {
        setIsReady(true);
      }, 50);
    });
    
    return () => cancelAnimationFrame(timer);
  }, [fitView]);

  // 状态恢复：从 URL 参数或最新运行记录中恢复运行状态
  useEffect(() => {
    const initializeNodeStatuses = async () => {
      // 1. 尝试从 URL 参数获取 runId
      const urlParams = new URLSearchParams(window.location.search);
      const runId = urlParams.get('runId');
      
      const restoreRunStatus = async (runIdToRestore: string) => {
        try {
          setCurrentRunId(runIdToRestore);
          const status = await getRunStatus(workflowId, runIdToRestore);
          
          // 恢复节点状态
          setNodesNormalized((nds) =>
            nds.map((node) => {
              const nodeStatus = status.node_statuses[node.id];
              if (nodeStatus) {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    executionStatus: nodeStatus.status as any,
                    executionResult: {
                      outputs: nodeStatus.output,
                      error: nodeStatus.error,
                      metrics: nodeStatus.metrics,
                      startTime: nodeStatus.started_at,
                      endTime: nodeStatus.finished_at,
                    },
                  },
                };
              }
              return node;
            })
          );
          
          // 如果运行还在进行中，标记为运行中
          if (status.run_status === 'running') {
            setIsRunning(true);
          }
        } catch (error) {
          console.error("Failed to restore run status:", error);
          // 如果恢复失败，重置为初始状态
          resetAllNodeStatuses();
        }
      };
      
      if (runId) {
        // 使用 URL 中的 runId
        await restoreRunStatus(runId);
        return;
      }
      
      // 2. 获取最新运行记录
      try {
        const runs = await getWorkflowRuns(workflowId, { limit: 1 });
        if (runs.runs && runs.runs.length > 0) {
          const latestRun = runs.runs[0];
          await restoreRunStatus(latestRun.id);
        } else {
          // 3. 没有运行记录，恢复初始状态
          resetAllNodeStatuses();
        }
      } catch (error) {
        console.error("Failed to initialize node statuses:", error);
        // 如果获取运行记录失败，重置为初始状态
        resetAllNodeStatuses();
      }
    };
    
    initializeNodeStatuses();
  }, [workflowId, setNodesNormalized]);

  // 自动保存（防抖）- 增加延迟时间以减少保存频率
  const debouncedSave = useDebouncedCallback(
    async (graph: { nodes: Node[]; edges: Edge[] }) => {
      try {
        setSaveStatus("saving");
        await onSave(graph, true);
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } catch (error) {
        console.error("Auto-save failed:", error);
        setSaveStatus("error");
        setTimeout(() => setSaveStatus("idle"), 3000);
      }
    },
    2000 // 从 500ms 增加到 2000ms
  );

  // 当节点或边变化时，触发自动保存
  // 只在真正重要的变化时才保存（忽略位置变化）
  const prevGraphRef = useRef<{ 
    nodeIds: string[]; 
    edgeIds: string[];
    nodes: Node[]; // 保存之前的节点数据用于比较
  } | null>(null);
  
  useEffect(() => {
    // 计算当前图的结构（只关注节点和边的ID，忽略位置等）
    const currentGraph = {
      nodeIds: nodes.map(n => n.id).sort(),
      edgeIds: edges.map(e => `${e.source}-${e.target}`).sort(),
      nodes: nodes, // 保存当前节点数据
    };

    // 如果是首次渲染，只记录不保存
    if (!prevGraphRef.current) {
      prevGraphRef.current = currentGraph;
      return;
    }

    // 检查是否有结构性的变化（添加/删除节点或边）
    const hasStructuralChange = 
      JSON.stringify(currentGraph.nodeIds) !== JSON.stringify(prevGraphRef.current.nodeIds) ||
      JSON.stringify(currentGraph.edgeIds) !== JSON.stringify(prevGraphRef.current.edgeIds);

    // 检查是否有节点配置变化（通过比较节点的关键属性）
    const hasConfigChange = nodes.some((node) => {
      const prevNode = prevGraphRef.current?.nodes.find(n => n.id === node.id);
      if (!prevNode) return true; // 新节点
      
      // 比较关键配置属性（忽略位置、选择状态等）
      return (
        node.data?.taskName !== prevNode.data?.taskName ||
        node.data?.displayName !== prevNode.data?.displayName ||
        JSON.stringify(node.data?.llmPrompt) !== JSON.stringify(prevNode.data?.llmPrompt) ||
        JSON.stringify(node.data?.llmSystemPrompt) !== JSON.stringify(prevNode.data?.llmSystemPrompt) ||
        JSON.stringify(node.data?.llmModel) !== JSON.stringify(prevNode.data?.llmModel) ||
        JSON.stringify(node.data?.toolName) !== JSON.stringify(prevNode.data?.toolName) ||
        JSON.stringify(node.data?.toolParams) !== JSON.stringify(prevNode.data?.toolParams) ||
        JSON.stringify(node.data?.conditionExpression) !== JSON.stringify(prevNode.data?.conditionExpression) ||
        JSON.stringify(node.data?.startInputInfo) !== JSON.stringify(prevNode.data?.startInputInfo)
      );
    });

    // 只有在有结构性变化或配置变化时才保存
    if (hasStructuralChange || hasConfigChange) {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
      
      // 增加延迟时间，从 1000ms 增加到 3000ms
      saveTimeoutRef.current = setTimeout(() => {
        debouncedSave({ nodes, edges });
        prevGraphRef.current = currentGraph;
      }, 3000);
    } else {
      // 即使没有重要变化，也更新引用（避免位置变化触发保存）
      prevGraphRef.current = currentGraph;
    }

    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [nodes, edges, debouncedSave]);

  // 手动保存
  const handleManualSave = useCallback(async () => {
    try {
      setSaveStatus("saving");
      await onSave({ nodes, edges }, false);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (error) {
      console.error("Save failed:", error);
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("idle"), 3000);
    }
  }, [nodes, edges, onSave]);

  // 更新节点执行状态
  const updateNodeExecutionStatus = useCallback((nodeId: string, status: "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled", resultData?: any) => {
    setNodesNormalized((nds) => {
      const nodeExists = nds.find(n => n.id === nodeId);
      if (!nodeExists) {
        console.warn(`节点 ${nodeId} 不存在于当前工作流中，无法更新状态`);
        return nds; // 如果节点不存在，返回原数组
      }
      
      return nds.map((node) => {
        if (node.id === nodeId) {
          const newData: any = {
            ...node.data,
            executionStatus: status,
          };
          
          if (resultData) {
            const existingResult = node.data.executionResult || {};
            const newResult: any = {
              ...existingResult,
              ...resultData
            };
            
            // 如果是循环体内的节点，且payload包含iteration信息，需要合并iteration_outputs
            if (resultData.outputs?.iteration_outputs && Array.isArray(resultData.outputs.iteration_outputs)) {
              // 合并iteration_outputs数组
              const existingIterationOutputs = existingResult.outputs?.iteration_outputs || [];
              newResult.outputs = {
                ...existingResult.outputs,
                ...resultData.outputs,
                iteration_outputs: [...existingIterationOutputs, ...resultData.outputs.iteration_outputs]
              };
            } else if (resultData.outputs) {
              // 普通更新
              newResult.outputs = {
                ...existingResult.outputs,
                ...resultData.outputs
              };
            }
            
            newData.executionResult = newResult;
          }
          
          return {
            ...node,
            data: newData,
          };
        }
        return node;
      });
    });
    // 同时更新选中的节点
    setSelectedNode((prev) => {
      if (prev && prev.id === nodeId) {
        const newData: any = {
          ...prev.data,
          executionStatus: status,
        };
        
        if (resultData) {
          const existingResult = prev.data.executionResult || {};
          const newResult: any = {
            ...existingResult,
            ...resultData
          };
          
          // 如果是循环体内的节点，且payload包含iteration信息，需要合并iteration_outputs
          if (resultData.outputs?.iteration_outputs && Array.isArray(resultData.outputs.iteration_outputs)) {
            // 合并iteration_outputs数组
            const existingIterationOutputs = existingResult.outputs?.iteration_outputs || [];
            newResult.outputs = {
              ...existingResult.outputs,
              ...resultData.outputs,
              iteration_outputs: [...existingIterationOutputs, ...resultData.outputs.iteration_outputs]
            };
          } else if (resultData.outputs) {
            // 普通更新
            newResult.outputs = {
              ...existingResult.outputs,
              ...resultData.outputs
            };
          }
          
          newData.executionResult = newResult;
        }
        
        return {
          ...prev,
          data: newData,
        };
      }
      return prev;
    });
  }, [setNodesNormalized]);

  // 重置所有节点状态为初始 ready 状态
  const resetAllNodeStatuses = useCallback(() => {
    setNodesNormalized((nds) =>
      nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          executionStatus: "ready" as const, // 初始状态为 ready
          executionResult: undefined, // 清空执行结果
        },
      }))
    );
  }, [setNodesNormalized]);

  // 执行工作流（使用 SSE 流式执行）
  const handleRun = useCallback(async () => {
    try {
      setIsRunning(true);
      resetAllNodeStatuses();
      
      // 1. 先保存草稿
      setSaveStatus("saving");
      const draft = await onSave({ nodes, edges }, false);
      setSaveStatus("saved");

      // 2. 查找开始节点，获取输入信息
      const startNode = nodes.find((n) => n.type === "start");
      const startInputInfo = startNode?.data?.startInputInfo || "";
      
      // 3. 准备输入参数（使用开始节点的输入信息作为输入）
      const inputs: Record<string, any> = {};
      if (startInputInfo.trim()) {
        // 如果开始节点有输入信息，将其作为输入
        inputs["input"] = startInputInfo.trim();
        inputs["inputs"] = { "input": startInputInfo.trim() };
      }

      // 4. 创建工作流配置（spec）
      const spec = {
        name: workflowName || "未命名工作流",
        nodes: nodes.map((node) => ({
          id: node.id,
          type: node.type,
          position: node.position,
          data: {
            ...node.data,
            nodeName: node.data.taskName, // 映射回 nodeName
          },
        })),
        edges: edges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
          data: edge.data,
        })),
      };

      // 5. 计算校验和（简单使用 JSON 字符串的哈希）
      const specString = JSON.stringify(spec);
      const checksum = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(specString)
      ).then((hash) => {
        return Array.from(new Uint8Array(hash))
          .map((b) => b.toString(16).padStart(2, "0"))
          .join("");
      });

      // 6. 创建发布版本
      const release = await createRelease(workflowId, {
        source_draft_id: draft.id,
        spec,
        checksum,
      });

      // 7. 流式执行工作流并实时更新节点状态
      let runId: string | null = null;
      try {
        for await (const event of executeWorkflowStream({
          workflowId,
          inputs,
        })) {
          // 处理不同类型的事件
          if (event.type === "run_start") {
            runId = event.run_id || null;
            toast.success("工作流运行已启动");
          } else if (event.type === "log") {
            // 处理日志事件，其中包含节点状态更新
            const logEvent = event.event;
            const nodeId = event.node_id;
            
            // 调试日志
            console.log("收到日志事件:", { logEvent, nodeId, payload: event.payload, time: event.time });
            
            // 工作流级别的事件（workflow_start, workflow_end）没有 node_id，这是正常的
            if (logEvent === "workflow_start" || logEvent === "workflow_end") {
              // 这些是工作流级别的事件，不需要更新节点状态
              continue; // 使用 continue 而不是 return，避免提前结束循环
            }
            
            if (nodeId) {
              // 检查节点是否存在（使用最新的节点列表）
              // 注意：这里使用闭包中的 nodes，但为了确保准确性，我们直接更新状态
              // setNodesNormalized 会在更新时检查节点是否存在
              
              if (logEvent === "node_ready") {
                // 节点就绪（上游节点完成）
                console.log(`节点 ${nodeId} 就绪`, event.payload);
                updateNodeExecutionStatus(nodeId, "ready");
              } else if (logEvent === "node_start") {
                // 节点开始执行
                const payload = event.payload || {};
                console.log(`节点 ${nodeId} 开始执行`, payload);
                updateNodeExecutionStatus(nodeId, "running", {
                  startTime: event.time,
                  inputs: payload.inputs
                });
              } else if (logEvent === "node_end") {
                // 节点执行结束（成功）
                const payload = event.payload || {};
                console.log(`节点 ${nodeId} 执行结束`, payload);
                if (payload.status === "success") {
                  // 检查是否是循环体内的节点（有iteration信息）
                  const isLoopBodyNode = payload.loop_id || payload.iteration !== undefined;
                  
                  // 构建输出数据
                  const outputs: any = payload.outputs || {};
                  
                  // 如果是循环体内的节点，需要构建iteration_outputs结构
                  if (isLoopBodyNode && payload.iteration !== undefined) {
                    // 从node_outputs中提取该节点的输出（如果存在iteration_outputs）
                    // 注意：后端应该已经在node_outputs中包含了iteration_outputs
                    // 这里我们直接使用payload.outputs，它应该已经包含了iteration_outputs
                    if (!outputs.iteration_outputs && outputs.output) {
                      // 如果outputs中没有iteration_outputs，但node_outputs中有，需要从那里提取
                      // 实际上，后端应该已经在payload.outputs中包含了完整的输出结构
                    }
                  }
                  
                  updateNodeExecutionStatus(nodeId, "success", {
                    endTime: event.time,
                    outputs: outputs,
                    metrics: payload.metrics
                  });
                } else {
                  updateNodeExecutionStatus(nodeId, "error", {
                    endTime: event.time,
                    error: payload.error
                  });
                }
              } else if (logEvent === "node_error") {
                // 节点执行失败
                const payload = event.payload || {};
                console.log(`节点 ${nodeId} 执行失败`, payload);
                updateNodeExecutionStatus(nodeId, "error", {
                  endTime: event.time,
                  error: payload.error
                });
              } else if (logEvent === "node_skipped") {
                // 节点被跳过
                const payload = event.payload || {};
                console.log(`节点 ${nodeId} 被跳过`, payload);
                updateNodeExecutionStatus(nodeId, "skipped", {
                  reason: payload.reason
                });
              } else if (logEvent === "node_cancelled") {
                // 节点被取消
                const payload = event.payload || {};
                console.log(`节点 ${nodeId} 被取消`, payload);
                updateNodeExecutionStatus(nodeId, "cancelled", {
                  reason: payload.reason
                });
              }
            } else {
              // 只有节点级别的事件才需要 node_id
              if (logEvent && logEvent.startsWith("node_")) {
                console.warn("节点级别日志事件缺少 node_id:", event);
              }
            }
          } else if (event.type === "run_end") {
            // 工作流执行完成
            if (event.success) {
              toast.success("工作流执行完成");
              // 保存 runId 以便后续查看详情
              if (runId) {
                setCurrentRunId(runId);
              }
            } else {
              toast.error("工作流执行失败");
            }
            // 停留在当前页面，不跳转
            break;
          } else if (event.type === "error") {
            // 执行错误
            toast.error(event.error || "工作流执行失败");
            break;
          }
        }
      } catch (streamError: any) {
        console.error("Stream error:", streamError);
        toast.error(streamError.message || "流式执行失败");
      }
    } catch (error: any) {
      console.error("Run failed:", error);
      toast.error(error.message || "运行工作流失败");
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("idle"), 3000);
    } finally {
      setIsRunning(false);
    }
  }, [nodes, edges, onSave, workflowId, router, resetAllNodeStatuses, updateNodeExecutionStatus]);

  // 连接节点
  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) => addEdge(params, eds));
    },
    [setEdges]
  );

  // 选择节点
  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
    setSelectedEdge(null);
  }, []);

  // 选择边
  const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setSelectedEdge(edge);
    setSelectedNode(null);
  }, []);

  // 更新节点数据
  const handleNodeUpdate = useCallback(
    (nodeId: string, data: any) => {
      setNodesNormalized((nds) =>
        nds.map((node) => {
          if (node.id === nodeId) {
            const updatedData = {
              ...node.data,
              ...data,
            };
            // 确保 nodeName 和 displayName 始终是字符串
            if (updatedData.nodeName !== undefined && updatedData.nodeName !== null) {
              updatedData.nodeName = String(updatedData.nodeName);
            }
            if (updatedData.displayName !== undefined && updatedData.displayName !== null) {
              updatedData.displayName = String(updatedData.displayName);
            }
            // 确保 label 也是字符串（如果存在）
            if (updatedData.label !== undefined && updatedData.label !== null) {
              updatedData.label = String(updatedData.label);
            }
            return { ...node, data: updatedData };
          }
          return node;
        })
      );
      setSelectedNode((prev) => {
        if (prev && prev.id === nodeId) {
          const updatedData = {
            ...prev.data,
            ...data,
          };
          // 确保 nodeName 和 displayName 始终是字符串
          if (updatedData.taskName !== undefined && updatedData.taskName !== null) {
            updatedData.taskName = String(updatedData.taskName);
          }
          if (updatedData.displayName !== undefined && updatedData.displayName !== null) {
            updatedData.displayName = String(updatedData.displayName);
          }
          if (updatedData.label !== undefined && updatedData.label !== null) {
            updatedData.label = String(updatedData.label);
          }
          return { ...prev, data: updatedData };
        }
        return prev;
      });
    },
    [setNodes]
  );

  // 更新边数据
  const handleEdgeUpdate = useCallback(
    (edgeId: string, data: any) => {
      setEdges((eds) =>
        eds.map((edge) => (edge.id === edgeId ? { ...edge, data } : edge))
      );
      setSelectedEdge((prev) => (prev && prev.id === edgeId ? { ...prev, data } : prev));
    },
    [setEdges]
  );

  // 删除节点和边
  const onNodesDelete = useCallback((deleted: Node[]) => {
    // 检查是否有循环节点被删除
    const deletedLoopIds = deleted.filter((n) => n.type === "loop").map((n) => n.id);
    
    setNodesNormalized((nds) => {
      if (deletedLoopIds.length > 0) {
        // 如果循环节点被删除，需要一并删除循环体内的所有节点
        // 找出所有属于被删除循环体的子节点
        const childNodeIds = new Set<string>();
        deletedLoopIds.forEach((loopId) => {
          nds.forEach((node) => {
            const nodeLoopId = node.data?.loopId || node.data?.loop_id;
            if (nodeLoopId === loopId) {
              childNodeIds.add(node.id);
            }
          });
        });
        
        // 删除循环节点和所有子节点
        const allDeletedIds = new Set([
          ...deleted.map((n) => n.id),
          ...Array.from(childNodeIds),
        ]);
        
        return nds.filter((node) => !allDeletedIds.has(node.id));
      } else {
        // 普通节点删除
        return nds.filter((node) => !deleted.find((d) => d.id === node.id));
      }
    });
    
    // 删除相关的边
    setEdges((eds) =>
      eds.filter(
        (edge) =>
          !deleted.find((d) => d.id === edge.source || d.id === edge.target)
      )
    );
    // 清除选中状态
    if (selectedNode && deleted.find((d) => d.id === selectedNode.id)) {
      setSelectedNode(null);
    }
  }, [setNodes, setEdges, selectedNode]);

  // 添加键盘事件监听器处理 Delete 键和 Backspace 键
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // 检查是否在输入框、文本域等可编辑元素中
      const target = event.target as HTMLElement;
      const isEditable = 
        target.tagName === "INPUT" || 
        target.tagName === "TEXTAREA" || 
        target.isContentEditable;
      
      // 如果正在编辑文本，不处理删除操作
      if (isEditable) {
        return;
      }
      
      // 检查是否按下了 Delete 键或 Backspace 键
      if (event.key === "Delete" || event.key === "Backspace") {
        // 检查是否有选中的节点或边
        if (selectedNode) {
          event.preventDefault();
          event.stopPropagation();
          setNodesNormalized((nds) => nds.filter((node) => node.id !== selectedNode.id));
          setEdges((eds) =>
            eds.filter(
              (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id
            )
          );
          setSelectedNode(null);
        } else if (selectedEdge) {
          event.preventDefault();
          event.stopPropagation();
          setEdges((eds) => eds.filter((edge) => edge.id !== selectedEdge.id));
          setSelectedEdge(null);
        }
      }
    };
    
    // 使用全局 window 监听，确保能捕获到键盘事件
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [selectedNode, selectedEdge, setNodes, setEdges]);

  // 在画布上添加节点
  const onPaneClick = useCallback(
    (event: React.MouseEvent) => {
      if (nodeTypeToAdd) {
        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });
        
      // 检查新节点是否在某个循环节点内
      let parentId: string | undefined;
      let finalPosition = position;
      let extent: 'parent' | undefined;
      let loopId: string | undefined;

      const loopNodes = nodes.filter(n => n.type === "loop");
      for (const loopNode of loopNodes) {
        const loopWidth = loopNode.data?.loopWidth || loopNode.width || 600;
        const loopHeight = loopNode.data?.loopHeight || loopNode.height || 400;
        
        if (
            position.x >= loopNode.position.x + LOOP_PADDING.left &&
            position.x <= loopNode.position.x + loopWidth - LOOP_PADDING.right &&
            position.y >= loopNode.position.y + LOOP_PADDING.top &&
            position.y <= loopNode.position.y + loopHeight - LOOP_PADDING.bottom
        ) {
            parentId = loopNode.id;
            loopId = loopNode.id;
            extent = 'parent';
            
            // 计算相对位置
            finalPosition = {
                x: Math.max(0, position.x - loopNode.position.x - LOOP_PADDING.left),
                y: Math.max(0, position.y - loopNode.position.y - LOOP_PADDING.top)
            };
            break;
        }
      }

      const nodeName = generateNodeName(nodeTypeToAdd, nodes);
      const newNode: Node = {
        id: nanoid(),
        type: nodeTypeToAdd,
        position: finalPosition,
        parentId,
        extent,
        data: { 
          taskName: nodeName,
          displayName: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName,
          label: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName, // 兼容旧数据
          ...(nodeTypeToAdd === "loop" ? { loopCount: 3, loop_count: 3 } : {}),
          loopId,
          loop_id: loopId,
          isLoopChild: !!loopId,
        },
        style: loopId ? { zIndex: 15, pointerEvents: "auto" } : undefined,
      };
        
      addNodes(normalizeNodes([newNode])[0]);
      setNodeTypeToAdd(null);

      }
    },
    [nodeTypeToAdd, screenToFlowPosition, addNodes]
  );

  // 处理拖放
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData("application/reactflow");
      if (!type) {
        return;
      }

      // 检查开始和结束节点的唯一性
      if (type === "start") {
        const hasStart = nodes.some((n) => n.type === "start");
        if (hasStart) {
          return;
        }
      }
      if (type === "end") {
        const hasEnd = nodes.some((n) => n.type === "end");
        if (hasEnd) {
          return;
        }
      }

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      // 检查新节点是否在某个循环节点内
      let parentId: string | undefined;
      let finalPosition = position;
      let extent: 'parent' | undefined;
      let loopId: string | undefined;

      const loopNodes = nodes.filter(n => n.type === "loop");
      for (const loopNode of loopNodes) {
        const loopWidth = loopNode.data?.loopWidth || loopNode.width || 600;
        const loopHeight = loopNode.data?.loopHeight || loopNode.height || 400;
        
        if (
            position.x >= loopNode.position.x + LOOP_PADDING.left &&
            position.x <= loopNode.position.x + loopWidth - LOOP_PADDING.right &&
            position.y >= loopNode.position.y + LOOP_PADDING.top &&
            position.y <= loopNode.position.y + loopHeight - LOOP_PADDING.bottom
        ) {
            parentId = loopNode.id;
            loopId = loopNode.id;
            extent = 'parent';
            
            // 计算相对位置
            finalPosition = {
                x: Math.max(0, position.x - loopNode.position.x - LOOP_PADDING.left),
                y: Math.max(0, position.y - loopNode.position.y - LOOP_PADDING.top)
            };
            break;
        }
      }

      const nodeName = generateNodeName(type, nodes);
      const newNode: Node = {
        id: nanoid(),
        type,
        position: finalPosition,
        parentId,
        extent,
        data: { 
          taskName: nodeName,
          displayName: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName,
          label: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName, // 兼容旧数据
          ...(type === "loop" ? { loopCount: 3, loop_count: 3 } : {}),
          loopId,
          loop_id: loopId,
          isLoopChild: !!loopId,
        },
        style: loopId ? { zIndex: 15, pointerEvents: "auto" } : undefined,
      };

      addNodes(normalizeNodes([newNode])[0]);

    },
    [screenToFlowPosition, addNodes, nodes, normalizeNodes]
  );

  // 生成节点名称（用于程序运行和记录）
  const generateNodeName = useCallback((type: string, existingNodes: Node[]): string => {
    // 开始和结束节点固定名称
    if (type === "start") return "start";
    if (type === "end") return "end";
    
    // 获取节点类型的中文名称映射
    const typeLabels: Record<string, string> = {
      llm: "LLM",
      tool: "工具",
      condition: "条件",
      loop: "loop",
    };
    
    const baseName = typeLabels[type] || type;
    
    // 统计同类型节点的数量
    const sameTypeNodes = existingNodes.filter(n => n.type === type);
    const count = sameTypeNodes.length;
    
    // 第一个节点不加数字，后续加数字
    return count === 0 ? baseName : `${baseName}${count}`;
  }, []);

  // 获取节点显示名称（用于界面显示）
  const getNodeDisplayName = (node: Node): string => {
    return node.data?.displayName || node.data?.label || node.data?.nodeName || "未命名";
  };

  const saveStatusText = useMemo(() => {
    switch (saveStatus) {
      case "saving":
        return "保存中...";
      case "saved":
        return "已保存";
      case "error":
        return "保存失败";
      default:
        return "";
    }
  }, [saveStatus]);

  return (
    <div className="flex h-full w-full flex-col">
      {/* 顶部工具栏 */}
      <div className="flex h-16 items-center justify-between border-b border-border bg-card px-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex flex-col">
            <h1 className="text-lg font-semibold text-foreground">{workflowName}</h1>
            <p className="text-xs text-muted-foreground">工作流编辑器</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-sm text-muted-foreground">{saveStatusText}</div>
          <Button onClick={handleManualSave} size="sm" disabled={saveStatus === "saving"}>
            <Save className="h-4 w-4 mr-2" />
            保存
          </Button>
          <Button 
            onClick={handleRun} 
            size="sm" 
            variant="default"
            className="bg-blue-500 hover:bg-blue-600"
            disabled={isRunning || saveStatus === "saving"}
          >
            <Play className="h-4 w-4 mr-2" />
            {isRunning ? "执行中..." : "执行"}
          </Button>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* 节点库 */}
        <NodePalette onNodeTypeSelect={setNodeTypeToAdd} />

        {/* 画布 */}
        <div 
          className="relative flex-1 bg-app transition-opacity duration-300 ease-in-out"
          style={{ opacity: isReady ? 1 : 0 }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onNodesDelete={onNodesDelete}
            onPaneClick={onPaneClick}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeDragStop={onNodeDragStop}
            nodeTypes={nodeTypes}
            deleteKeyCode={[46, 8]} // 启用 Delete 键(46) 和 Backspace 键(8) 删除节点和边
            attributionPosition="bottom-left"
          >

            <Controls />
            <MiniMap />
            <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
          </ReactFlow>
        </div>

        {/* 配置面板 */}
        {(selectedNode || selectedEdge) && (
          <div className="w-80 border-l border-border bg-card">
            {selectedNode && (
              <NodeConfigPanel
                node={selectedNode}
                nodes={nodes}
                edges={edges}
                onUpdate={handleNodeUpdate}
                onClose={() => setSelectedNode(null)}
              />
            )}
            {selectedEdge && (
              <EdgeConfigPanel
                edge={selectedEdge}
                onUpdate={handleEdgeUpdate}
                onClose={() => setSelectedEdge(null)}
              />
            )}
          </div>
        )}
      </div>

    </div>
  );
}
export function WorkflowEditor(props: WorkflowEditorProps) {
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner {...props} />
    </ReactFlowProvider>
  );
}


