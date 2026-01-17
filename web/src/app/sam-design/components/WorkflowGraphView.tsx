"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from "react";
import { ReactFlow, Node, Edge, useNodesState, useEdgesState, Controls, Background, BackgroundVariant, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { StartNode } from "~/components/workflow/editor/nodes/StartNode";
import { EndNode } from "~/components/workflow/editor/nodes/EndNode";
import { LLMNode } from "~/components/workflow/editor/nodes/LLMNode";
import { ToolNode } from "~/components/workflow/editor/nodes/ToolNode";
import { ConditionNode } from "~/components/workflow/editor/nodes/ConditionNode";
import { LoopNode } from "~/components/workflow/editor/nodes/LoopNode";

const nodeTypes = {
  start: StartNode,
  end: EndNode,
  llm: LLMNode,
  tool: ToolNode,
  condition: ConditionNode,
  loop: LoopNode,
};

interface WorkflowGraphViewProps {
  graph: { nodes: any[]; edges: any[] };
  nodeOutputs: Record<string, any>;
  runningNodeIds?: Set<string>;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 工作流图可视化组件
 */
function WorkflowGraphViewInner({
  graph,
  nodeOutputs,
  runningNodeIds = new Set(),
  executionState,
}: WorkflowGraphViewProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // 更新节点执行状态（参考 Step2RunDesignLab 的实现）
  const updateNodeExecutionStatus = useCallback((
    nodeId: string,
    status: "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled",
    data?: any
  ) => {
    setNodes((nds) =>
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
  }, [setNodes]);

  // 加载图形
  useEffect(() => {
    if (graph) {
      const workflowNodes: Node[] = (graph.nodes || []).map((node: any) => ({
        ...node,
        data: {
          ...node.data,
          executionStatus: "pending",
        },
      }));
      const workflowEdges: Edge[] = graph.edges || [];
      
      setNodes(workflowNodes);
      setEdges(workflowEdges);
    }
  }, [graph, setNodes, setEdges]);

  // 更新节点执行状态（基于 runningNodeIds 和 nodeOutputs）
  useEffect(() => {
    setNodes((nds) =>
      nds.map((node) => {
        // 优先检查是否正在执行
        if (runningNodeIds.has(node.id)) {
          return {
            ...node,
            data: {
              ...node.data,
              executionStatus: "running",
            },
          };
        }
        // 检查是否已完成
        if (nodeOutputs[node.id]) {
          return {
            ...node,
            data: {
              ...node.data,
              executionStatus: "success",
              executionResult: nodeOutputs[node.id],
            },
          };
        }
        // 保持当前状态（如果已经是 success，不重置为 pending）
        return node;
      })
    );
  }, [nodeOutputs, runningNodeIds, setNodes]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.1}
        maxZoom={2}
      >
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        <Controls />
      </ReactFlow>
    </div>
  );
}

export function WorkflowGraphView(props: WorkflowGraphViewProps) {
  return (
    <ReactFlowProvider>
      <WorkflowGraphViewInner {...props} />
    </ReactFlowProvider>
  );
}
