// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Check, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, useEffect } from "react";

import { Button } from "~/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "~/components/ui/dropdown-menu";
import { useConfig } from "~/core/api/hooks";
import { useStore } from "~/core/store";
import { cn } from "~/lib/utils";

import type { ModelInfo } from "~/core/config/types";

export function ModelSelector() {
  const t = useTranslations("chat.modelSelector");
  const { config, loading } = useConfig();
  const selectedModel = useStore((state) => state.selectedModel);
  const setSelectedModel = useStore((state) => state.setSelectedModel);
  const [open, setOpen] = useState(false);

  // Get all available models from config
  const availableModels: ModelInfo[] = [];
  if (config?.models) {
    Object.values(config.models).forEach((modelList) => {
      if (Array.isArray(modelList)) {
        modelList.forEach((model) => {
          if (typeof model === "object" && model !== null && "name" in model) {
            availableModels.push(model as ModelInfo);
          }
        });
      }
    });
  }

  // Set default model to first model in MODELS when config is loaded and no model is selected
  useEffect(() => {
    if (!loading && availableModels.length > 0 && selectedModel === null) {
      // Select first model in MODELS as default
      setSelectedModel(availableModels[0].name);
    }
  }, [loading, availableModels, selectedModel, setSelectedModel]);

  // Find current model display name
  const currentModel = availableModels.find((m) => m.name === selectedModel);
  const displayName = currentModel
    ? `${currentModel.name} (${currentModel.model})`
    : availableModels.length > 0
    ? `${availableModels[0].name} (${availableModels[0].model})`
    : "选择模型";

  if (loading || availableModels.length === 0) {
    return null;
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-9 min-w-[240px] justify-between gap-2 border-slate-200 bg-white/90 backdrop-blur-sm hover:bg-white shadow-sm transition-colors dark:border-slate-700 dark:bg-slate-800/90 dark:hover:bg-slate-800"
        >
          <span className="truncate text-sm font-medium">{displayName}</span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50 transition-transform" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="min-w-[240px] p-0 shadow-lg" align="start">
        <DropdownMenuLabel>{t("selectModel")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {availableModels.map((model) => (
          <DropdownMenuItem
            key={model.name}
            onSelect={() => {
              setSelectedModel(model.name);
              setOpen(false);
            }}
            className={cn(
              "cursor-pointer",
              selectedModel === model.name && "bg-accent"
            )}
          >
            <Check
              className={cn(
                "mr-2 h-4 w-4",
                selectedModel === model.name ? "opacity-100" : "opacity-0"
              )}
            />
            <div className="flex flex-col">
              <span className="font-medium">{model.name}</span>
              <span className="text-xs text-muted-foreground">
                {model.model}
              </span>
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

