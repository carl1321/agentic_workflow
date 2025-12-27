// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useState, useEffect, useMemo } from "react";
import { Check, ChevronsUpDown, Loader2 } from "lucide-react";
import { Button } from "~/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { useConfig } from "~/core/api/hooks";
import type { ModelInfo } from "~/core/config/types";
import { cn } from "~/lib/utils";

interface ModelSelectorProps {
  value?: string;
  onChange: (modelName: string) => void;
  className?: string;
}

export function ModelSelector({ value, onChange, className }: ModelSelectorProps) {
  const { config, loading } = useConfig();
  const [open, setOpen] = useState(false);

  // 获取所有可用模型
  const availableModels = useMemo(() => {
    const models: ModelInfo[] = [];
    if (config?.models) {
      Object.values(config.models).forEach((modelList) => {
        if (Array.isArray(modelList)) {
          modelList.forEach((model) => {
            if (typeof model === "object" && model !== null && "name" in model) {
              models.push(model as ModelInfo);
            }
          });
        }
      });
    }
    return models;
  }, [config]);

  // 如果已有模型名称但不在列表中，保留它（向后兼容）
  const currentModel = availableModels.find((m) => m.name === value);
  const displayValue = currentModel
    ? `${currentModel.name}${currentModel.model ? ` (${currentModel.model})` : ""}`
    : value || "未选择模型";

  if (loading) {
    return (
      <div className={cn("flex items-center gap-2", className)}>
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        <span className="text-sm text-muted-foreground">加载模型中...</span>
      </div>
    );
  }

  if (availableModels.length === 0) {
    return (
      <div className={cn("text-sm text-muted-foreground", className)}>
        没有可用模型
      </div>
    );
  }

  return (
    <Select
      value={value || ""}
      onValueChange={(newValue) => {
        onChange(newValue);
      }}
      open={open}
      onOpenChange={setOpen}
    >
      <SelectTrigger className={className}>
        <SelectValue placeholder="选择模型">
          {displayValue}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {availableModels.map((model) => (
          <SelectItem key={model.name} value={model.name}>
            <div className="flex items-center gap-2">
              {value === model.name && (
                <Check className="h-4 w-4 text-primary" />
              )}
              <div className="flex flex-col">
                <span className="font-medium">{model.name}</span>
                {model.model && (
                  <span className="text-xs text-muted-foreground">
                    {model.model}
                  </span>
                )}
              </div>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

