// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useState, useEffect, useCallback } from "react";
import { BookOpen, X, Search, Loader2 } from "lucide-react";
import { queryRAGResources } from "~/core/api/rag";
import type { Resource } from "~/core/messages";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "~/components/ui/popover";
import { Badge } from "~/components/ui/badge";
import { cn } from "~/lib/utils";

interface KnowledgeSelectorProps {
  value?: Array<{ uri: string; title: string; description?: string }>;
  onChange: (resources: Array<{ uri: string; title: string; description?: string }>) => void;
}

export function KnowledgeSelector({
  value = [],
  onChange,
}: KnowledgeSelectorProps) {
  // 确保 value 始终是一个数组，防止 null 或 undefined
  const safeValue = Array.isArray(value) ? value : [];
  
  const [open, setOpen] = useState(false);
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const loadResources = useCallback(async (query: string = "") => {
    try {
      setLoading(true);
      const results = await queryRAGResources(query);
      setResources(results);
    } catch (error) {
      console.error("Failed to load resources:", error);
      setResources([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      loadResources(searchQuery);
    }
  }, [open, searchQuery, loadResources]);

  const handleSelectResource = (resource: Resource) => {
    const isSelected = safeValue.some((r) => r.uri === resource.uri);
    if (isSelected) {
      onChange(safeValue.filter((r) => r.uri !== resource.uri));
    } else {
      onChange([
        ...safeValue,
        {
          uri: resource.uri,
          title: resource.title,
          description: resource.description,
        },
      ]);
    }
  };

  const handleRemoveResource = (uri: string) => {
    onChange(safeValue.filter((r) => r.uri !== uri));
  };

  const isResourceSelected = (uri: string) => {
    return safeValue.some((r) => r.uri === uri);
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-start"
          >
            <BookOpen className="mr-2 h-4 w-4" />
            选择知识库
            {safeValue.length > 0 && (
              <Badge variant="secondary" className="ml-2">
                {safeValue.length}
              </Badge>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-96 p-0" align="start">
          <div className="p-3 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="text"
                placeholder="搜索知识库..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>
          <div className="max-h-80 overflow-y-auto p-2">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : resources.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                {searchQuery ? "未找到匹配的资源" : "暂无知识库资源"}
              </div>
            ) : (
              <div className="space-y-1">
                {resources.map((resource) => {
                  const selected = isResourceSelected(resource.uri);
                  return (
                    <button
                      key={resource.uri}
                      onClick={() => handleSelectResource(resource)}
                      className={cn(
                        "w-full rounded-lg border p-3 text-left transition-colors",
                        selected
                          ? "border-primary bg-primary/5"
                          : "border-border hover:bg-accent"
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <BookOpen
                          className={cn(
                            "mt-0.5 h-4 w-4 flex-shrink-0",
                            selected ? "text-primary" : "text-muted-foreground"
                          )}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-sm text-foreground">
                            {resource.title}
                          </div>
                          {resource.description && (
                            <div className="mt-1 text-xs text-muted-foreground line-clamp-2">
                              {resource.description}
                            </div>
                          )}
                          <div className="mt-1 text-xs font-mono text-muted-foreground truncate">
                            {resource.uri.replace("rag://dataset/", "")}
                          </div>
                        </div>
                        {selected && (
                          <div className="flex-shrink-0 text-primary">✓</div>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {/* 已选择的知识库列表 */}
      {safeValue.length > 0 && (
        <div className="space-y-1">
          {safeValue.map((resource) => (
            <div
              key={resource.uri}
              className="flex items-center justify-between rounded-lg border border-border bg-muted/50 p-2"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <BookOpen className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                <span className="text-sm text-foreground truncate">
                  {resource.title}
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 flex-shrink-0"
                onClick={() => handleRemoveResource(resource.uri)}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

