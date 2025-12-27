// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState, useMemo } from "react";
import { Search } from "lucide-react";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { apiRequest } from "~/core/api/api-client";

interface ToolDefinition {
  name: string;
  description: string;
  parameters: Array<{
    name: string;
    type: string;
    description?: string;
    required?: boolean;
  }>;
}

interface ToolSelectorProps {
  selectedTool?: string;
  onSelect: (toolName: string) => void;
  onClose: () => void;
}

export function ToolSelector({ selectedTool, onSelect, onClose }: ToolSelectorProps) {
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    loadTools();
  }, []);

  const loadTools = async () => {
    try {
      setLoading(true);
      const toolsData = await apiRequest<ToolDefinition[]>("workflow/tools");
      setTools(toolsData);
    } catch (error) {
      console.error("Error loading tools:", error);
    } finally {
      setLoading(false);
    }
  };

  const filteredTools = useMemo(() => {
    if (!searchQuery) return tools;
    const query = searchQuery.toLowerCase();
    return tools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(query) ||
        tool.description.toLowerCase().includes(query)
    );
  }, [tools, searchQuery]);

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold">选择工具</h3>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索工具..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="text-center text-sm text-muted-foreground py-8">加载中...</div>
        ) : filteredTools.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            {searchQuery ? "未找到匹配的工具" : "暂无可用工具"}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredTools.map((tool) => (
              <button
                key={tool.name}
                onClick={() => {
                  onSelect(tool.name);
                  onClose();
                }}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selectedTool === tool.name
                    ? "border-primary bg-primary/10"
                    : "border-border hover:bg-accent"
                }`}
              >
                <div className="font-medium text-sm">{tool.name}</div>
                <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                  {tool.description}
                </div>
                {tool.parameters.length > 0 && (
                  <div className="text-xs text-muted-foreground mt-2">
                    {tool.parameters.length} 个参数
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

