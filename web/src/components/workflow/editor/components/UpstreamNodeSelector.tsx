// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useMemo, useState } from "react";
import { Node, Edge } from "@xyflow/react";
import { Button } from "~/components/ui/button";
import { ScrollArea } from "~/components/ui/scroll-area";
import { ChevronRight, ChevronDown, Play, Brain, Wrench, GitBranch, RotateCcw } from "lucide-react";
import { cn } from "~/lib/utils";

interface UpstreamNodeSelectorProps {
  currentNodeId: string;
  nodes: Node[];
  edges: Edge[];
  onSelect: (template: string) => void;
  onClose: () => void;
}

// 定义各节点类型的默认输出字段
const getDefaultOutputFields = (nodeType: string): string[] => {
  switch (nodeType) {
    case "start":
      return ["inputs", "input"];
    case "llm":
      return ["output"];
    case "tool":
      return ["result", "output"];
    case "condition":
      return ["result", "conditionResult"];
    case "loop":
      return ["output", "iterations"];
    default:
      return ["output"];
  }
};

// 根据节点的输出格式和定义的字段返回对应的输出字段
const getNodeOutputFields = (node: Node): string[] => {
  const nodeType = node.type || "start";
  const outputFormat = node.data?.outputFormat || node.data?.output_format || "json";
  const outputFields = node.data?.outputFields || node.data?.output_fields || [];
  
  // 始终包含 output 字段（原始输出）
  const fields: string[] = ["output"];
  
  // 如果定义了输出字段，添加这些字段
  if (Array.isArray(outputFields) && outputFields.length > 0) {
    outputFields.forEach((field: any) => {
      if (field && field.name && typeof field.name === 'string') {
        fields.push(field.name);
      }
    });
  } else {
    // 如果没有定义字段，返回默认字段（针对特定节点类型）
    if (nodeType === "start") {
      fields.push("inputs", "input");
    } else if (nodeType === "tool") {
      fields.push("result");
    } else if (nodeType === "condition") {
      fields.push("result", "conditionResult");
    } else if (nodeType === "loop") {
      fields.push("iterations");
    }
  }
  
  return fields;
};

// 获取节点类型图标
const getNodeIcon = (nodeType: string) => {
  switch (nodeType) {
    case "start":
      return Play;
    case "llm":
      return Brain;
    case "tool":
      return Wrench;
    case "condition":
      return GitBranch;
    case "loop":
      return RotateCcw;
    default:
      return Play;
  }
};

export function UpstreamNodeSelector({
  currentNodeId,
  nodes,
  edges,
  onSelect,
  onClose,
}: UpstreamNodeSelectorProps) {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  // 查找所有连接到当前节点的上游节点
  // 对于循环体内的节点，还需要包含：
  // 1. 连接到循环体的节点（循环体外的节点）
  // 2. 循环体内的其他节点
  const upstreamNodes = useMemo(() => {
    const currentNode = nodes.find((n) => n.id === currentNodeId);
    if (!currentNode) return [];
    
    // 获取当前节点所在的循环体ID（如果有）
    const currentLoopId = currentNode.data?.loopId || currentNode.data?.loop_id;
    
    // 1. 通过边连接的上游节点
    const sourceNodeIds = edges
      .filter((edge) => edge.target === currentNodeId)
      .map((edge) => edge.source);
    
    let upstreamNodeIds = new Set(sourceNodeIds);
    
    // 2. 如果当前节点在循环体内，添加循环体外的节点（连接到循环体的节点）
    if (currentLoopId) {
      // 找到循环体节点
      const loopNode = nodes.find((n) => n.id === currentLoopId && n.type === "loop");
      if (loopNode) {
        // 找到所有连接到循环体的节点（循环体外的节点）
        const loopSourceNodeIds = edges
          .filter((edge) => edge.target === currentLoopId)
          .map((edge) => edge.source);
        
        loopSourceNodeIds.forEach((id) => upstreamNodeIds.add(id));
        
        // 3. 添加循环体内的其他节点（除了当前节点）
        const loopBodyNodeIds = nodes
          .filter(
            (n) =>
              (n.data?.loopId === currentLoopId || n.data?.loop_id === currentLoopId) &&
              n.id !== currentNodeId &&
              n.id !== currentLoopId
          )
          .map((n) => n.id);
        
        loopBodyNodeIds.forEach((id) => upstreamNodeIds.add(id));
      }
    }
    
    return nodes.filter((node) => upstreamNodeIds.has(node.id));
  }, [currentNodeId, nodes, edges]);

  // 生成节点唯一标识（使用节点名称 taskName）
  const getNodeIdentifier = (node: Node): string => {
    // 优先使用 taskName，如果没有则使用 nodeName，最后使用 label 或 id
    // 确保返回的是字符串类型
    const identifier = node.data?.taskName || node.data?.nodeName || node.data?.label || node.id;
    return typeof identifier === 'string' ? identifier : String(identifier);
  };

  const toggleNode = (nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const handleFieldSelect = (node: Node, field: string) => {
    const nodeIdentifier = getNodeIdentifier(node);
    // 确保 nodeIdentifier 是字符串
    const identifier = typeof nodeIdentifier === 'string' ? nodeIdentifier : String(nodeIdentifier);
    const template = `{{${identifier}.${field}}}`;
    onSelect(template);
    onClose();
  };

  if (upstreamNodes.length === 0) {
    return (
      <div className="w-80 p-4">
        <div className="text-sm text-muted-foreground text-center py-8">
          没有上游节点
        </div>
      </div>
    );
  }

  return (
    <div className="w-80 flex flex-col">
      <div className="p-3 border-b border-border">
        <h3 className="text-sm font-semibold">选择上游节点</h3>
        <p className="text-xs text-muted-foreground mt-1">
          选择节点和字段，将在光标位置插入变量引用
        </p>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {upstreamNodes.map((node) => {
            const Icon = getNodeIcon(node.type || "start");
            const isExpanded = expandedNodes.has(node.id);
            const outputFields = getNodeOutputFields(node);
            // 确保所有值都是字符串
            const nodeLabel = typeof node.data?.displayName === 'string' 
              ? node.data.displayName 
              : (typeof node.data?.label === 'string' ? node.data.label : String(node.id));
            const nodeIdentifier = getNodeIdentifier(node);

            return (
              <div key={node.id} className="border border-border rounded-md">
                <button
                  onClick={() => toggleNode(node.id)}
                  className="w-full flex items-center gap-2 p-2 hover:bg-accent transition-colors"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                  <Icon className="h-4 w-4 text-muted-foreground" />
                  <span className="flex-1 text-left text-sm font-medium">
                    {nodeLabel}
                  </span>
                </button>
                {isExpanded && (
                  <div className="border-t border-border bg-muted/30">
                    {outputFields.map((field) => (
                      <button
                        key={field}
                        onClick={() => handleFieldSelect(node, field)}
                        className="w-full flex items-center gap-2 px-6 py-2 text-sm hover:bg-accent transition-colors text-left"
                      >
                        <span className="text-muted-foreground">└─</span>
                        <span className="font-mono text-xs">{field}</span>
                        <span className="text-xs text-muted-foreground ml-auto">
                          {`{{${nodeIdentifier}.${field}}}`}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}

