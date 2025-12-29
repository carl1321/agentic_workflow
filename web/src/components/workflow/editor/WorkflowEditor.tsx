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
  
  // 检测节点是否在循环节点内容区域内（考虑 LOOP_PADDING）
  // 参考 szlabAgent：使用内容区域而不是整个循环体区域
  const isNodeInLoopContainer = useCallback((node: Node, loopNode: Node): boolean => {
    const loopWidth = loopNode.data?.loopWidth || loopNode.data?.loop_width || loopNode.width || 600;
    const loopHeight = loopNode.data?.loopHeight || loopNode.data?.loop_height || loopNode.height || 400;
    
    // 节点中心点
    const nodeWidth = node.width || 160; // 默认节点宽度
    const nodeHeight = node.height || 60; // 默认节点高度
    const nodeCenterX = node.position.x + nodeWidth / 2;
    const nodeCenterY = node.position.y + nodeHeight / 2;
    
    // 循环体内容区域边界（考虑 LOOP_PADDING）
    // 参考 szlabAgent：内容区域从 LOOP_PADDING.left 和 LOOP_PADDING.top 开始
    const contentLeft = loopNode.position.x + LOOP_PADDING.left;
    const contentTop = loopNode.position.y + LOOP_PADDING.top;
    const contentRight = loopNode.position.x + loopWidth - LOOP_PADDING.right;
    const contentBottom = loopNode.position.y + loopHeight - LOOP_PADDING.bottom;
    
    // 检查节点中心是否在内容区域内
    return (
      nodeCenterX >= contentLeft &&
      nodeCenterX <= contentRight &&
      nodeCenterY >= contentTop &&
      nodeCenterY <= contentBottom
    );
  }, []);

  // 包装 onNodesChange，确保节点更新后规范化，并处理循环体拖入
  const onNodesChange = useCallback(
    (changes: any) => {
      // 注意：使用 parentId 后，ReactFlow 会自动处理子节点的拖动
      // 子节点可以独立拖动，但受 extent 限制在循环体内
      // 不需要阻止循环体内节点的拖动
      
      onNodesChangeRaw(changes);
      // 使用 requestAnimationFrame 在下一个渲染周期规范化节点和处理循环体
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
          
          // 处理节点拖入循环体和循环节点拖拽
          const updatedNodes = normalized.map((node) => {
            // 如果是循环节点被拖拽，不需要特殊处理（ReactFlow会自动更新position）
            // 循环体内节点的位置会在useMemo中自动更新
            if (node.type === "loop") {
              return node;
            }
            
            // 跳过开始/结束节点
            if (node.type === "start" || node.type === "end") {
              return node;
            }
            
            // 如果节点已经有 parentId，说明它在循环体内
            // 此时 node.position 是相对于父节点的位置
            // 我们需要计算绝对位置来检查是否还在循环体内
            const currentLoopId = node.data?.loopId || node.data?.loop_id;
            const currentParentId = node.parentId;
            
            // 查找所有循环节点
            const loopNodes = normalized.filter(n => n.type === "loop");
            
            // 检查节点是否在任何循环节点内
            let newLoopId: string | undefined = undefined;
            let relativeX: number | undefined = undefined;
            let relativeY: number | undefined = undefined;
            
            for (const loopNode of loopNodes) {
              // 计算节点的绝对位置
              let absoluteX = node.position.x;
              let absoluteY = node.position.y;
              
              // 如果节点有 parentId，position 是相对位置，需要转换为绝对位置
              if (currentParentId === loopNode.id) {
                absoluteX = loopNode.position.x + node.position.x;
                absoluteY = loopNode.position.y + node.position.y;
              }
              
              // 使用绝对位置检查节点是否在循环体内
              const nodeWidth = node.width || 160;
              const nodeHeight = node.height || 60;
              const nodeCenterX = absoluteX + nodeWidth / 2;
              const nodeCenterY = absoluteY + nodeHeight / 2;
              
              const contentLeft = loopNode.position.x + LOOP_PADDING.left;
              const contentTop = loopNode.position.y + LOOP_PADDING.top;
              const loopWidth = loopNode.data?.loopWidth || loopNode.data?.loop_width || loopNode.width || 600;
              const loopHeight = loopNode.data?.loopHeight || loopNode.data?.loop_height || loopNode.height || 400;
              const contentRight = loopNode.position.x + loopWidth - LOOP_PADDING.right;
              const contentBottom = loopNode.position.y + loopHeight - LOOP_PADDING.bottom;
              
              if (
                nodeCenterX >= contentLeft &&
                nodeCenterX <= contentRight &&
                nodeCenterY >= contentTop &&
                nodeCenterY <= contentBottom
              ) {
                newLoopId = loopNode.id;
                // 计算相对坐标（相对于循环体容器内部）
                // 如果节点已经有 parentId，使用当前的相对位置
                if (currentParentId === loopNode.id) {
                  relativeX = node.position.x - LOOP_PADDING.left;
                  relativeY = node.position.y - LOOP_PADDING.top;
                } else {
                  // 否则从绝对位置计算相对位置
                  relativeX = absoluteX - loopNode.position.x - LOOP_PADDING.left;
                  relativeY = absoluteY - loopNode.position.y - LOOP_PADDING.top;
                }
                // 确保相对位置不为负数
                relativeX = Math.max(0, relativeX);
                relativeY = Math.max(0, relativeY);
                break;
              }
            }
            
            // 如果节点不在任何循环内，清除 loopId 和 parentId
            if (!newLoopId && currentLoopId) {
              // 节点被拖出循环体
              // 需要将相对位置转换为绝对位置（因为移除了 parentId）
              const loopNode = normalized.find(n => n.id === currentLoopId && n.type === "loop");
              let absolutePosition = node.position;
              
              if (loopNode && node.parentId === currentLoopId) {
                // 如果之前有 parentId，position 是相对于父节点的，需要转换为绝对位置
                const relativeX = node.data?.relativeX ?? node.data?.relative_x ?? 0;
                const relativeY = node.data?.relativeY ?? node.data?.relative_y ?? 0;
                absolutePosition = {
                  x: loopNode.position.x + LOOP_PADDING.left + relativeX,
                  y: loopNode.position.y + LOOP_PADDING.top + relativeY,
                };
              }
              
              return {
                ...node,
                parentId: undefined, // 清除 parentId
                position: absolutePosition,
                extent: undefined, // 清除 extent 限制
                data: {
                  ...node.data,
                  loopId: undefined,
                  loop_id: undefined,
                  relativeX: undefined,
                  relativeY: undefined,
                  relative_x: undefined,
                  relative_y: undefined,
                },
              };
            } else if (newLoopId && newLoopId !== currentLoopId) {
              // 节点被拖入循环体或移动到另一个循环体
              // 需要设置 parentId 和 extent，并转换位置
              const loopNode = normalized.find(n => n.id === newLoopId && n.type === "loop");
              if (loopNode) {
                const loopWidth = loopNode.data?.loopWidth || loopNode.data?.loop_width || loopNode.width || 600;
                const loopHeight = loopNode.data?.loopHeight || loopNode.data?.loop_height || loopNode.height || 400;
                
                // 确保相对位置在有效范围内
                const maxRelativeX = loopWidth - LOOP_PADDING.left - LOOP_PADDING.right;
                const maxRelativeY = loopHeight - LOOP_PADDING.top - LOOP_PADDING.bottom;
                const clampedRelativeX = Math.max(0, Math.min(relativeX!, maxRelativeX));
                const clampedRelativeY = Math.max(0, Math.min(relativeY!, maxRelativeY));
                
                return {
                  ...node,
                  parentId: newLoopId, // 设置 parentId 建立父子关系
                  position: {
                    x: LOOP_PADDING.left + clampedRelativeX,
                    y: LOOP_PADDING.top + clampedRelativeY,
                  },
                  extent: [
                    [LOOP_PADDING.left, LOOP_PADDING.top],
                    [loopWidth - LOOP_PADDING.right, loopHeight - LOOP_PADDING.bottom],
                  ],
                  style: {
                    ...node.style,
                    zIndex: 15,
                    pointerEvents: "auto",
                  },
                  data: {
                    ...node.data,
                    loopId: newLoopId,
                    loop_id: newLoopId,
                    relativeX: clampedRelativeX,
                    relativeY: clampedRelativeY,
                    relative_x: clampedRelativeX,
                    relative_y: clampedRelativeY,
                  },
                };
              }
            } else if (newLoopId && newLoopId === currentLoopId) {
              // 节点在循环体内移动，更新相对坐标
              // 参考 szlabAgent：使用 parentId 后，node.position 是相对于父节点的位置
              // 需要从相对于父节点的位置转换为相对于循环体容器的位置
              const calculatedRelativeX = node.position.x - LOOP_PADDING.left;
              const calculatedRelativeY = node.position.y - LOOP_PADDING.top;
              
              // 确保相对位置在有效范围内
              const loopNode = normalized.find(n => n.id === newLoopId && n.type === "loop");
              if (loopNode) {
                const loopWidth = loopNode.data?.loopWidth || loopNode.data?.loop_width || loopNode.width || 600;
                const loopHeight = loopNode.data?.loopHeight || loopNode.data?.loop_height || loopNode.height || 400;
                const maxRelativeX = loopWidth - LOOP_PADDING.left - LOOP_PADDING.right;
                const maxRelativeY = loopHeight - LOOP_PADDING.top - LOOP_PADDING.bottom;
                
                const clampedRelativeX = Math.max(0, Math.min(calculatedRelativeX, maxRelativeX));
                const clampedRelativeY = Math.max(0, Math.min(calculatedRelativeY, maxRelativeY));
                
                const currentRelativeX = node.data?.relativeX ?? node.data?.relative_x;
                const currentRelativeY = node.data?.relativeY ?? node.data?.relative_y;
                
                // 只有当相对位置发生变化时才更新
                if (currentRelativeX !== clampedRelativeX || currentRelativeY !== clampedRelativeY) {
                  return {
                    ...node,
                    // 确保 position 正确（相对于父节点）
                    position: {
                      x: LOOP_PADDING.left + clampedRelativeX,
                      y: LOOP_PADDING.top + clampedRelativeY,
                    },
                    data: {
                      ...node.data,
                      relativeX: clampedRelativeX,
                      relativeY: clampedRelativeY,
                      relative_x: clampedRelativeX,
                      relative_y: clampedRelativeY,
                    },
                  };
                }
              }
            }
            
            return node;
          });
          
          return needsUpdate || updatedNodes.some((n, idx) => n !== normalized[idx]) ? updatedNodes : normalized;
        });
      });
    },
    [onNodesChangeRaw, setNodes, normalizeNodes, isNodeInLoopContainer]
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
        
      const nodeName = generateNodeName(nodeTypeToAdd, nodes);
      const newNode: Node = {
        id: nanoid(),
        type: nodeTypeToAdd,
        position,
        data: { 
          taskName: nodeName,
          displayName: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName,
          label: nodeName === "start" ? "开始" : nodeName === "end" ? "结束" : nodeName, // 兼容旧数据
          ...(nodeTypeToAdd === "loop" ? { loopCount: 3, loop_count: 3 } : {}),
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
          ...(type === "loop" ? { loopCount: 3, loop_count: 3 } : {}),
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

  // 处理循环体内节点的位置：将相对坐标转换为绝对坐标
  const processedNodes = useMemo(() => {
    return nodes.map((node) => {
      const loopId = node.data?.loopId || node.data?.loop_id;
      if (!loopId) {
        return node; // 不在循环体内的节点，保持原位置
      }
      
      // 查找循环节点
      const loopNode = nodes.find(n => n.id === loopId && n.type === "loop");
      if (!loopNode) {
        return node; // 找不到循环节点，保持原位置
      }
      
      // 获取相对坐标
      const relativeX = node.data?.relativeX || node.data?.relative_x || 0;
      const relativeY = node.data?.relativeY || node.data?.relative_y || 0;
      const headerHeight = 40; // 循环节点头部高度
      
      // 计算绝对位置（相对于循环节点，考虑头部）
      const absoluteX = loopNode.position.x + relativeX;
      const absoluteY = loopNode.position.y + headerHeight + relativeY;
      
      return {
        ...node,
        position: {
          x: absoluteX,
          y: absoluteY,
        },
      };
    });
  }, [nodes]);

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
        <div className="relative flex-1 bg-app">
          <ReactFlow
            nodes={useMemo(() => {
              // 确保所有节点在渲染前都经过规范化
              const normalized = normalizeNodes(nodes);
              
              // 处理循环体内节点的位置：将相对坐标转换为绝对坐标
              const processedNodes = normalized.map((node) => {
                const nodeData = node.data || {};
                const loopId = nodeData.loopId || nodeData.loop_id;
                
                // 处理节点数据规范化
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
                
                // 如果节点在循环体内，使用 ReactFlow 的 parentId 和 extent 来实现父子关系
                // 参考 szlabAgent 的实现：使用 parentId 让 ReactFlow 自动处理父子节点的拖动
                if (loopId) {
                  const loopNode = normalized.find(n => n.id === loopId && n.type === "loop");
                  if (loopNode) {
                    // 参考 szlabAgent 的 LOOP_PADDING 常量
                    const LOOP_PADDING = {
                      top: 65, // 头部高度(40) + 内边距(25)
                      right: 16,
                      bottom: 20,
                      left: 16,
                    };
                    
                    // 获取循环节点的实际尺寸（从节点数据或默认值）
                    const loopWidth = loopNode.data?.loopWidth || loopNode.data?.loop_width || loopNode.width || 600;
                    const loopHeight = loopNode.data?.loopHeight || loopNode.data?.loop_height || loopNode.height || 400;
                    
                    // 获取或计算相对位置
                    const relativeX = nodeData.relativeX ?? nodeData.relative_x;
                    const relativeY = nodeData.relativeY ?? nodeData.relative_y;
                    
                    let position = node.position;
                    if (relativeX !== undefined && relativeY !== undefined) {
                      // 使用保存的相对位置（相对于循环体容器内部）
                      // 参考 szlabAgent：子节点的 position 是相对于父节点的，从 LOOP_PADDING.left 和 LOOP_PADDING.top 开始
                      position = {
                        x: LOOP_PADDING.left + relativeX,
                        y: LOOP_PADDING.top + relativeY,
                      };
                    } else {
                      // 首次计算相对位置
                      // 从绝对位置转换为相对于循环体容器的位置
                      let calculatedRelativeX = node.position.x - loopNode.position.x - LOOP_PADDING.left;
                      let calculatedRelativeY = node.position.y - loopNode.position.y - LOOP_PADDING.top;
                      
                      // 确保相对位置在有效范围内
                      calculatedRelativeX = Math.max(0, calculatedRelativeX);
                      calculatedRelativeY = Math.max(0, calculatedRelativeY);
                      
                      // 保存相对位置到节点数据
                      nodeData.relativeX = calculatedRelativeX;
                      nodeData.relativeY = calculatedRelativeY;
                      
                      // 设置相对于父节点的位置
                      position = {
                        x: LOOP_PADDING.left + calculatedRelativeX,
                        y: LOOP_PADDING.top + calculatedRelativeY,
                      };
                    }
                    
                    // 设置 parentId，让 ReactFlow 自动处理父子关系
                    // 这样当循环节点被拖拽时，子节点会自动跟随移动
                    // 子节点可以独立拖动，但受 extent 限制在循环体内
                    return {
                      ...node,
                      parentId: loopNode.id,
                      position,
                      draggable: true, // 确保子节点可以拖动
                      // 设置 extent，限制子节点只能在循环体容器内移动
                      // extent 是相对于父节点的边界，格式：[[minX, minY], [maxX, maxY]]
                      extent: [
                        [LOOP_PADDING.left, LOOP_PADDING.top],
                        [loopWidth - LOOP_PADDING.right, loopHeight - LOOP_PADDING.bottom],
                      ],
                      style: {
                        ...node.style,
                        zIndex: 15, // 确保循环体内的节点在 Loop 节点上方，可以接收事件
                        pointerEvents: "auto", // 确保可以接收鼠标事件
                      },
                      // ReactFlow 可能直接访问节点的 label 属性
                      label: nodeLabel,
                      // 移除 nodeName 属性，避免被浏览器插件误认为是 DOM 节点
                      nodeName: undefined, 
                      data: {
                        ...nodeData,
                        taskName: taskName,
                        displayName: displayName,
                        label: nodeLabel,
                        relativeX: nodeData.relativeX ?? nodeData.relative_x,
                        relativeY: nodeData.relativeY ?? nodeData.relative_y,
                        // 确保不包含 nodeName 属性
                        nodeName: undefined,
                      },
                    };
                  }
                }
                
                // 如果是循环节点，确保 width 和 height 属性被正确设置
                // 这样 ReactFlow 才能正确计算 Handle 的位置
                if (node.type === "loop") {
                  const loopWidth = nodeData.loopWidth || nodeData.loop_width || 600;
                  const loopHeight = nodeData.loopHeight || nodeData.loop_height || 400;
                  return {
                    ...node,
                    width: loopWidth,
                    height: loopHeight,
                    position: node.position,
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
                }
                
                return {
                  ...node,
                  position: node.position,
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
              
              return processedNodes;
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
            onNodeDrag={(event, node) => {
              // 当循环节点被拖拽时，循环体内节点的位置会在useMemo中自动更新
              // 因为nodes数组会变化，useMemo会重新计算循环体内节点的绝对位置
            }}
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

