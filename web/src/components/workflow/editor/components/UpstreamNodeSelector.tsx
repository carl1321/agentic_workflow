// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useMemo, useState } from "react";
import { Node, Edge } from "@xyflow/react";
import { Button } from "~/components/ui/button";
import { ScrollArea } from "~/components/ui/scroll-area";
import { ChevronRight, ChevronDown, Play, Brain, Wrench, GitBranch, RotateCcw, Database } from "lucide-react";
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
// 返回格式：{ field: string, displayName: string, isNested: boolean }
const getNodeOutputFields = (node: Node): Array<{ field: string; displayName: string; isNested: boolean }> => {
  const nodeType = node.type || "start";
  const outputFormat = node.data?.outputFormat || node.data?.output_format || "array";
  const outputFields = node.data?.outputFields || node.data?.output_fields || [];
  
  const fields: Array<{ field: string; displayName: string; isNested: boolean }> = [];
  
  // 始终包含 output 字段（原始输出）
  fields.push({ field: "output", displayName: "output", isNested: false });
  
  // 如果定义了输出字段，添加这些字段（作为 output 的嵌套字段）
  if (Array.isArray(outputFields) && outputFields.length > 0) {
    outputFields.forEach((field: any) => {
      if (field && field.name && typeof field.name === 'string') {
        // 自定义字段应该通过 output.字段名 访问
        fields.push({
          field: `output.${field.name}`,
          displayName: field.name,
          isNested: true,
        });
      }
    });
  } else {
    // 如果没有定义字段，返回默认字段（针对特定节点类型）
    if (nodeType === "start") {
      fields.push({ field: "inputs", displayName: "inputs", isNested: false });
      fields.push({ field: "input", displayName: "input", isNested: false });
    } else if (nodeType === "tool") {
      fields.push({ field: "result", displayName: "result", isNested: false });
    } else if (nodeType === "condition") {
      fields.push({ field: "result", displayName: "result", isNested: false });
      fields.push({ field: "conditionResult", displayName: "conditionResult", isNested: false });
    } else if (nodeType === "loop") {
      fields.push({ field: "iterations", displayName: "iterations", isNested: false });
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
  const [expandedLoopVars, setExpandedLoopVars] = useState(false);

  // 检查当前节点是否在循环体内
  const currentNode = useMemo(() => {
    return nodes.find((n) => n.id === currentNodeId);
  }, [currentNodeId, nodes]);

  const currentLoopId = currentNode?.data?.loopId || currentNode?.data?.loop_id;
  const isInLoop = !!currentLoopId;

  // 查找所有连接到当前节点的上游节点
  // 对于循环体内的节点，还需要包含：
  // 1. 连接到循环体的节点（循环体外的节点）
  // 2. 循环体内的其他节点
  const upstreamNodes = useMemo(() => {
    if (!currentNode) return [];
    
    // 1. 通过边连接的上游节点
    const sourceNodeIds = edges
      .filter((edge) => edge.target === currentNodeId)
      .map((edge) => edge.source);
    
    let upstreamNodeIds = new Set(sourceNodeIds);
    
    // 2. 如果当前节点在循环体内，添加循环体外的节点（连接到循环体的节点）
    if (isInLoop && currentLoopId) {
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
  }, [currentNode, nodes, edges, isInLoop, currentLoopId]);

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

  const handleFieldSelect = (node: Node, fieldInfo: { field: string; displayName: string; isNested: boolean }) => {
    const nodeIdentifier = getNodeIdentifier(node);
    // 确保 nodeIdentifier 是字符串
    const identifier = typeof nodeIdentifier === 'string' ? nodeIdentifier : String(nodeIdentifier);
    const template = `{{${identifier}.${fieldInfo.field}}}`;
    onSelect(template);
    onClose();
  };

  const handleLoopVariableSelect = (variablePath: string) => {
    const template = `{{loop.variables.${variablePath}}}`;
    onSelect(template);
    onClose();
  };

  // 从 exit_node 获取输出字段，动态生成循环变量字段列表
  const loopVariableFields = useMemo(() => {
    if (!isInLoop || !currentLoopId) {
      return [];
    }

    // 找到循环体内的所有节点
    const loopBodyNodes = nodes.filter(
      (n) =>
        (n.data?.loopId === currentLoopId || n.data?.loop_id === currentLoopId) &&
        n.id !== currentLoopId &&
        n.type !== "start" &&
        n.type !== "end"
    );

    // 找到 exit_node（循环体内没有下游连接的节点）
    const exitNodes = loopBodyNodes.filter((node) => {
      // 检查是否有下游连接（连接到循环体内的其他节点）
      const hasDownstream = edges.some(
        (edge) =>
          edge.source === node.id &&
          loopBodyNodes.some((n) => n.id === edge.target)
      );
      return !hasDownstream;
    });

    // 使用第一个 exit_node（如果有多个，优先使用第一个）
    const exitNode = exitNodes[0];
    if (!exitNode) {
      // 如果没有 exit_node，只返回基础字段
      return [
        { path: "pending_items", label: "pending_items" },
        { path: "iteration", label: "iteration" },
      ];
    }

    // 获取 exit_node 的输出字段
    const outputFields = getNodeOutputFields(exitNode);
    const outputFieldsConfig = exitNode.data?.outputFields || exitNode.data?.output_fields || [];

    // 构建字段列表
    const fields: Array<{ path: string; label: string }> = [];

    // 添加基础字段
    fields.push({ path: "pending_items", label: "pending_items" });
    fields.push({ path: "iteration", label: "iteration" });

    // 从 exit_node 的输出字段中提取字段名
    // 如果定义了 outputFields，使用定义的字段
    if (Array.isArray(outputFieldsConfig) && outputFieldsConfig.length > 0) {
      outputFieldsConfig.forEach((field: any) => {
        if (field && field.name && typeof field.name === "string") {
          fields.push({
            path: `pending_items.${field.name}`,
            label: field.name,
          });
        }
      });
    } else {
      // 如果没有定义字段，尝试从 output 字段中推断
      // 这里只添加 output 字段，因为无法知道具体的嵌套字段结构
      if (outputFields.includes("output")) {
        fields.push({
          path: "pending_items.output",
          label: "output",
        });
      }
    }

    return fields;
  }, [isInLoop, currentLoopId, nodes, edges]);

  if (upstreamNodes.length === 0 && !isInLoop) {
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
        <h3 className="text-sm font-semibold">选择变量</h3>
        <p className="text-xs text-muted-foreground mt-1">
          选择节点和字段，将在光标位置插入变量引用
        </p>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {/* 循环变量选项（如果当前节点在循环体内） */}
          {isInLoop && (
            <div className="border border-border rounded-md">
              <button
                onClick={() => setExpandedLoopVars(!expandedLoopVars)}
                className="w-full flex items-center gap-2 p-2 hover:bg-accent transition-colors"
              >
                {expandedLoopVars ? (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                )}
                <Database className="h-4 w-4 text-muted-foreground" />
                <span className="flex-1 text-left text-sm font-medium">
                  循环变量
                </span>
              </button>
              {expandedLoopVars && (
                <div className="border-t border-border bg-muted/30">
                  {loopVariableFields.map((field) => (
                    <button
                      key={field.path}
                      onClick={() => handleLoopVariableSelect(field.path)}
                      className="w-full flex items-center gap-2 px-6 py-2 text-sm hover:bg-accent transition-colors text-left"
                    >
                      <span className="text-muted-foreground">└─</span>
                      <span className="font-mono text-xs">{field.label}</span>
                      <span className="text-xs text-muted-foreground ml-auto">
                        {`{{loop.variables.${field.path}}}`}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          
          {/* 上游节点选项 */}
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
                    {outputFields.map((fieldInfo) => (
                      <button
                        key={fieldInfo.field}
                        onClick={() => handleFieldSelect(node, fieldInfo)}
                        className="w-full flex items-center gap-2 px-6 py-2 text-sm hover:bg-accent transition-colors text-left"
                      >
                        <span className="text-muted-foreground">└─</span>
                        <span className="font-mono text-xs">{fieldInfo.displayName}</span>
                        <span className="text-xs text-muted-foreground ml-auto">
                          {`{{${nodeIdentifier}.${fieldInfo.field}}}`}
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

