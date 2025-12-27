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
import { createRelease, executeWorkflowStream, getRunStatus, type WorkflowExecutionEvent } from "~/core/api/workflow";
import { toast } from "sonner";

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

function WorkflowEditorInner({
  workflowId,
  workflowName,
  initialNodes,
  initialEdges,
  onSave,
  onBack,
}: WorkflowEditorProps) {
  // 兼容处理：为旧节点数据添加 taskName (原nodeName) 和 displayName
  const normalizeNodes = useCallback((nodes: Node[]): Node[] => {
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
            loop: "循环",
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
  }, []);
  // 规范化初始节点数据
  const normalizedInitialNodes = useMemo(() => normalizeNodes(initialNodes), [initialNodes, normalizeNodes]);
  
  const [nodes, setNodes, onNodesChangeRaw] = useNodesState(normalizedInitialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  
  // 包装 setNodes，确保所有节点更新都经过规范化
  const setNodesNormalized = useCallback(
    (updater: Node[] | ((nodes: Node[]) => Node[])) => {
      setNodes((nds) => {
        const newNodes = typeof updater === 'function' ? updater(nds) : updater;
        return normalizeNodes(newNodes);
      });
    },
    [setNodes, normalizeNodes]
  );
  
  // 包装 onNodesChange，确保节点更新后规范化
  const onNodesChange = useCallback(
    (changes: any) => {
      onNodesChangeRaw(changes);
      // 使用 requestAnimationFrame 在下一个渲染周期规范化节点
      requestAnimationFrame(() => {
        setNodes((nds) => {
          const normalized = normalizeNodes(nds);
  // 检查是否有节点需要规范化
  const needsUpdate = nds.some((node, idx) => {
    const normNode = normalized[idx];
    if (!normNode) return true;
    const taskName = node.data?.taskName;
    return typeof taskName !== 'string' || taskName !== normNode.data?.taskName;
  });
          return needsUpdate ? normalized : nds;
        });
      });
    },
    [onNodesChangeRaw, setNodes, normalizeNodes]
  );
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [nodeTypeToAdd, setNodeTypeToAdd] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null); // 当前运行的 ID
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const router = useRouter();
  const { screenToFlowPosition, addNodes } = useReactFlow();
  
  // 状态恢复：从 URL 参数中恢复运行状态
  useEffect(() => {
    const restoreRunStatus = async () => {
      // 检查 URL 参数中是否有 runId
      const urlParams = new URLSearchParams(window.location.search);
      const runId = urlParams.get('runId');
      
      if (runId) {
        try {
          setCurrentRunId(runId);
          const status = await getRunStatus(workflowId, runId);
          
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
        }
      }
    };
    
    restoreRunStatus();
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
            newData.executionResult = {
              ...(node.data.executionResult || {}),
              ...resultData
            };
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
          newData.executionResult = {
            ...(prev.data.executionResult || {}),
            ...resultData
          };
        }
        
        return {
          ...prev,
          data: newData,
        };
      }
      return prev;
    });
  }, [setNodesNormalized]);

  // 重置所有节点状态
  const resetAllNodeStatuses = useCallback(() => {
    setNodesNormalized((nds) =>
      nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          executionStatus: "pending" as const,
          executionResult: undefined, // 清空执行结果
        },
      }))
    );
  }, [setNodesNormalized]);

  // 试运行工作流（使用 SSE 流式执行）
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
                  updateNodeExecutionStatus(nodeId, "success", {
                    endTime: event.time,
                    outputs: payload.outputs,
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
            } else {
              toast.error("工作流执行失败");
            }
            // 执行完成后跳转到运行详情页面
            if (runId) {
              setTimeout(() => {
                router.push(`/workflow/${workflowId}/runs/${runId}`);
              }, 1000);
            }
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
    setNodesNormalized((nds) => nds.filter((node) => !deleted.find((d) => d.id === node.id)));
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
        
      const nodeName = generateNodeName(nodeTypeToAdd, nodes);
      const newNode: Node = {
        id: nanoid(),
        type: nodeTypeToAdd,
        position,
        data: { 
          taskName: nodeName,
          displayName: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName,
          label: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName, // 兼容旧数据
        },
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

      const nodeName = generateNodeName(type, nodes);
      const newNode: Node = {
        id: nanoid(),
        type,
        position,
        data: { 
          taskName: nodeName,
          displayName: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName,
          label: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName, // 兼容旧数据
        },
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
      loop: "循环",
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
            试运行
          </Button>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* 节点库 */}
        <NodePalette onNodeTypeSelect={setNodeTypeToAdd} />

        {/* 画布 */}
        <div className="relative flex-1 bg-app">
          <ReactFlow
            nodes={useMemo(() => {
              // 确保所有节点在渲染前都经过规范化
              const normalized = normalizeNodes(nodes);
              // 双重检查：确保每个节点的所有属性都是字符串类型
              return normalized.map((node) => {
                const nodeData = node.data || {};
                const taskName = typeof nodeData.taskName === 'string' 
                  ? nodeData.taskName 
                  : String(nodeData.taskName || node.id);
                const displayName = typeof nodeData.displayName === 'string'
                  ? nodeData.displayName
                  : String(nodeData.displayName || nodeData.label || taskName);
                const nodeLabel = typeof node.label === 'string' 
                  ? node.label 
                  : (typeof nodeData.label === 'string' 
                      ? nodeData.label 
                      : displayName);
                
                return {
                  ...node,
                  // ReactFlow 可能直接访问节点的 label 属性
                  label: nodeLabel,
                  // 移除 nodeName 属性，避免被浏览器插件误认为是 DOM 节点
                  nodeName: undefined, 
                  data: {
                    ...nodeData,
                    taskName: taskName,
                    displayName: displayName,
                    label: nodeLabel,
                    // 确保不包含 nodeName 属性
                    nodeName: undefined,
                  },
                };
              });
            }, [nodes, normalizeNodes])}
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
            nodeTypes={nodeTypes}
            deleteKeyCode={[46, 8]} // 启用 Delete 键(46) 和 Backspace 键(8) 删除节点和边
            fitView
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

