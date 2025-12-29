// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useMemo, useState } from "react";
import { Node } from "@xyflow/react";
import { Button } from "~/components/ui/button";
import { ScrollArea } from "~/components/ui/scroll-area";
import { ChevronRight, ChevronDown, Play, Brain, Wrench, GitBranch, RotateCcw } from "lucide-react";
import { cn } from "~/lib/utils";

interface LoopBodyNodeSelectorProps {
  loopNodeId: string;
  nodes: Node[];
  onSelect: (variablePath: string) => void;
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
// 对于循环体节点选择器，只返回 output 字段，自定义字段作为 output 的嵌套字段显示
const getNodeOutputFields = (node: Node): string[] => {
  // 始终只返回 output 字段，自定义字段会作为 output 的嵌套字段显示
  return ["output"];
};

// 获取节点定义的输出字段列表（用于显示嵌套字段）
const getNodeDefinedFields = (node: Node): Array<{ name: string; type: string }> => {
  const outputFields = node.data?.outputFields || node.data?.output_fields || [];
  if (Array.isArray(outputFields) && outputFields.length > 0) {
    return outputFields
      .filter((field: any) => field && field.name && typeof field.name === 'string')
      .map((field: any) => ({
        name: field.name,
        type: field.type || "String"
      }));
  }
  return [];
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

// 递归获取嵌套字段
const getNestedFields = (obj: any, prefix: string = "", maxDepth: number = 3, currentDepth: number = 0): Array<{ path: string; value: any }> => {
  if (currentDepth >= maxDepth || !obj || typeof obj !== "object") {
    return [];
  }
  
  const fields: Array<{ path: string; value: any }> = [];
  
  for (const [key, value] of Object.entries(obj)) {
    const fullPath = prefix ? `${prefix}.${key}` : key;
    
    if (value && typeof value === "object" && !Array.isArray(value)) {
      // 递归获取嵌套字段
      fields.push(...getNestedFields(value, fullPath, maxDepth, currentDepth + 1));
    } else {
      // 叶子节点
      fields.push({ path: fullPath, value });
    }
  }
  
  return fields;
};

export function LoopBodyNodeSelector({
  loopNodeId,
  nodes,
  onSelect,
  onClose,
}: LoopBodyNodeSelectorProps) {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set());

  // 筛选循环体内的节点
  const bodyNodes = useMemo(() => {
    return nodes.filter(
      (node) => 
        (node.data?.loopId === loopNodeId || node.data?.loop_id === loopNodeId) && 
        node.id !== loopNodeId &&
        node.type !== "start" && 
        node.type !== "end"
    );
  }, [nodes, loopNodeId]);

  // 生成节点唯一标识（使用节点名称 taskName）
  const getNodeIdentifier = (node: Node): string => {
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

  const toggleField = (fieldPath: string) => {
    setExpandedFields((prev) => {
      const next = new Set(prev);
      if (next.has(fieldPath)) {
        next.delete(fieldPath);
      } else {
        next.add(fieldPath);
      }
      return next;
    });
  };

  const handleFieldSelect = (node: Node, fieldPath: string) => {
    const nodeIdentifier = getNodeIdentifier(node);
    const template = `{{${nodeIdentifier}.${fieldPath}}}`;
    onSelect(template);
    onClose();
  };

  if (bodyNodes.length === 0) {
    return (
      <div className="w-80 p-4">
        <div className="text-sm text-muted-foreground text-center py-8">
          循环体内暂无节点
        </div>
      </div>
    );
  }

  return (
    <div className="w-80 flex flex-col">
      <div className="p-3 border-b border-border">
        <h3 className="text-sm font-semibold">选择循环体内节点</h3>
        <p className="text-xs text-muted-foreground mt-1">
          选择节点和字段，将在光标位置插入变量引用
        </p>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {bodyNodes.map((node) => {
            const Icon = getNodeIcon(node.type || "start");
            const isExpanded = expandedNodes.has(node.id);
            const outputFields = getNodeOutputFields(node);
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
                    {outputFields.map((field) => {
                      const fieldPath = field;
                      const isFieldExpanded = expandedFields.has(`${node.id}.${fieldPath}`);
                      
                      // 获取节点定义的字段列表
                      const definedFields = getNodeDefinedFields(node);
                      
                      // 如果字段是 output 且有定义的字段，可以展开显示嵌套字段
                      // 对于自定义字段，直接选择，不需要展开
                      const hasNestedFields = field === "output" && definedFields.length > 0;
                      
                      return (
                        <div key={field}>
                          <div className="flex items-center">
                            <button
                              onClick={() => {
                                if (hasNestedFields) {
                                  toggleField(`${node.id}.${fieldPath}`);
                                } else {
                                  handleFieldSelect(node, fieldPath);
                                }
                              }}
                              className="flex-1 flex items-center gap-2 px-6 py-2 text-sm hover:bg-accent transition-colors text-left"
                            >
                              <span className="text-muted-foreground">└─</span>
                              <span className="font-mono text-xs">{field}</span>
                              {hasNestedFields && (
                                <span className="ml-auto">
                                  {isFieldExpanded ? (
                                    <ChevronDown className="h-3 w-3 text-muted-foreground" />
                                  ) : (
                                    <ChevronRight className="h-3 w-3 text-muted-foreground" />
                                  )}
                                </span>
                              )}
                              {!hasNestedFields && (
                                <span className="text-xs text-muted-foreground ml-auto">
                                  {`{{${nodeIdentifier}.${field}}}`}
                                </span>
                              )}
                            </button>
                          </div>
                          {hasNestedFields && isFieldExpanded && (
                            <div className="bg-muted/20 pl-8">
                              {/* 显示节点定义的字段 */}
                              {definedFields.map((definedField) => (
                                <button
                                  key={definedField.name}
                                  onClick={() => handleFieldSelect(node, `${fieldPath}.${definedField.name}`)}
                                  className="w-full flex items-center gap-2 px-4 py-1.5 text-xs hover:bg-accent transition-colors text-left"
                                >
                                  <span className="text-muted-foreground">└─</span>
                                  <span className="font-mono">{definedField.name}</span>
                                  <span className="text-xs text-muted-foreground ml-auto">
                                    ({definedField.type})
                                  </span>
                                  <span className="text-xs text-muted-foreground ml-auto">
                                    {`{{${nodeIdentifier}.${fieldPath}.${definedField.name}}}`}
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </ScrollArea>
      <div className="p-3 border-t border-border">
        <Button variant="outline" size="sm" onClick={onClose} className="w-full">
          取消
        </Button>
      </div>
    </div>
  );
}

