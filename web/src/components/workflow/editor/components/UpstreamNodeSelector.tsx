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

// 定义各节点类型的输出字段
const getNodeOutputFields = (nodeType: string): string[] => {
  switch (nodeType) {
    case "start":
      return ["inputs", "input"];
    case "llm":
      return ["response", "content", "output"];
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
  const upstreamNodes = useMemo(() => {
    const sourceNodeIds = edges
      .filter((edge) => edge.target === currentNodeId)
      .map((edge) => edge.source);
    
    return nodes.filter((node) => sourceNodeIds.includes(node.id));
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
            const outputFields = getNodeOutputFields(node.type || "start");
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

