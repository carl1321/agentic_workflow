// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useCallback, useState, useMemo } from "react";
import { Play, Square, Brain, Wrench, GitBranch, RotateCcw } from "lucide-react";
import { Input } from "~/components/ui/input";
import { Button } from "~/components/ui/button";
import { cn } from "~/lib/utils";

interface NodeTemplate {
  type: string;
  label: string;
  description?: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  category: string;
}

type NodeCategory = "基础" | "AI" | "控制流";

const nodeTemplates: NodeTemplate[] = [
  { 
    type: "start", 
    label: "开始", 
    description: "工作流的起始节点",
    icon: Play, 
    color: "text-green-600",
    category: "基础"
  },
  { 
    type: "end", 
    label: "结束", 
    description: "工作流的结束节点",
    icon: Square, 
    color: "text-red-600",
    category: "基础"
  },
  { 
    type: "llm", 
    label: "LLM", 
    description: "调用大语言模型",
    icon: Brain, 
    color: "text-purple-600",
    category: "AI"
  },
  { 
    type: "tool", 
    label: "工具", 
    description: "执行计算工具或函数",
    icon: Wrench, 
    color: "text-blue-600",
    category: "AI"
  },
  { 
    type: "condition", 
    label: "条件", 
    description: "根据条件分支执行",
    icon: GitBranch, 
    color: "text-indigo-600",
    category: "控制流"
  },
  { 
    type: "loop", 
    label: "循环", 
    description: "循环执行节点组",
    icon: RotateCcw, 
    color: "text-orange-600",
    category: "控制流"
  },
];

const categories: NodeCategory[] = ["基础", "AI", "控制流"];

interface NodePaletteProps {
  onNodeTypeSelect?: (type: string) => void;
}

export function NodePalette({ onNodeTypeSelect }: NodePaletteProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<NodeCategory | "全部">("全部");

  const handleDragStart = useCallback(
    (event: React.DragEvent, template: NodeTemplate) => {
      event.dataTransfer.setData("application/reactflow", template.type);
      event.dataTransfer.effectAllowed = "move";
    },
    []
  );

  // 过滤节点
  const filteredTemplates = useMemo(() => {
    return nodeTemplates.filter((template) => {
      const matchesSearch = 
        !searchQuery || 
        template.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
        template.description?.toLowerCase().includes(searchQuery.toLowerCase());
      
      const matchesCategory = 
        selectedCategory === "全部" || 
        template.category === selectedCategory;
      
      return matchesSearch && matchesCategory;
    });
  }, [searchQuery, selectedCategory]);

  // 按分类分组
  const groupedTemplates = useMemo(() => {
    const grouped: Record<string, NodeTemplate[]> = {};
    filteredTemplates.forEach((template) => {
      if (!grouped[template.category]) {
        grouped[template.category] = [];
      }
      grouped[template.category].push(template);
    });
    return grouped;
  }, [filteredTemplates]);

  return (
    <div className="flex h-full w-64 flex-col border-r border-border bg-card">
      {/* 头部 */}
      <div className="border-b border-border p-3">
        <h2 className="text-sm font-semibold text-foreground">节点库</h2>
        <p className="text-xs text-muted-foreground mt-1">拖拽节点到画布</p>
      </div>

      {/* 搜索框 */}
      <div className="border-b border-border p-3">
        <Input
          placeholder="搜索节点..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="h-8 text-xs"
        />
      </div>

      {/* 分类筛选 */}
      <div className="border-b border-border p-2 flex gap-1 flex-wrap">
        <Button
          variant={selectedCategory === "全部" ? "default" : "ghost"}
          size="sm"
          className="h-6 text-xs px-2"
          onClick={() => setSelectedCategory("全部")}
        >
          全部
        </Button>
        {categories.map((category) => (
          <Button
            key={category}
            variant={selectedCategory === category ? "default" : "ghost"}
            size="sm"
            className="h-6 text-xs px-2"
            onClick={() => setSelectedCategory(category)}
          >
            {category}
          </Button>
        ))}
      </div>

      {/* 节点列表 */}
      <div className="flex-1 overflow-y-auto p-2">
        {Object.entries(groupedTemplates).map(([category, templates]) => (
          <div key={category} className="mb-4">
            <h3 className="text-xs font-semibold text-muted-foreground mb-2 px-1">
              {category}
            </h3>
            <div className="space-y-1">
              {templates.map((template) => {
                const Icon = template.icon;
                return (
                  <div
                    key={template.type}
                    draggable
                    onDragStart={(e) => handleDragStart(e, template)}
                    onClick={() => onNodeTypeSelect?.(template.type)}
                    className={cn(
                      "flex items-center gap-2 p-2 rounded-md cursor-move",
                      "hover:bg-accent transition-colors",
                      "border border-transparent hover:border-border"
                    )}
                  >
                    <Icon className={cn("h-4 w-4 flex-shrink-0", template.color)} />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium text-foreground truncate">
                        {template.label}
                      </div>
                      {template.description && (
                        <div className="text-xs text-muted-foreground truncate">
                          {template.description}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {filteredTemplates.length === 0 && (
          <div className="text-center text-xs text-muted-foreground py-8">
            未找到匹配的节点
          </div>
        )}
      </div>
    </div>
  );
}

