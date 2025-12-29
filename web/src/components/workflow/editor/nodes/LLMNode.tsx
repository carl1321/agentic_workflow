// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Brain, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "~/lib/utils";

// 简单的执行状态类型
type ExecutionStatus = "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled";

export function LLMNode({ data, selected }: NodeProps) {
  const executionStatus: ExecutionStatus = data.executionStatus || "pending";
  const statusColors = {
    pending: "border-border",
    ready: "border-blue-500 animate-pulse", // 蓝色边框，闪烁动画
    running: "border-yellow-500",
    success: "border-green-500",
    error: "border-red-500",
    skipped: "border-gray-400",
    cancelled: "border-gray-500",
  };
  
  const borderColor = selected
    ? "border-primary shadow-md"
    : `${statusColors[executionStatus] || statusColors.pending} hover:border-purple-400`;

  const statusIcons = {
    pending: null,
    ready: <Loader2 className="h-2.5 w-2.5 text-blue-500" />, // 蓝色加载图标
    running: <Loader2 className="h-2.5 w-2.5 animate-spin text-yellow-500" />,
    success: <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />,
    error: <XCircle className="h-2.5 w-2.5 text-red-500" />,
    skipped: <span className="text-[10px] text-gray-500">⏭</span>,
    cancelled: <span className="text-[10px] text-gray-500">✕</span>,
    };

    const result = data.executionResult;
    const duration = result?.startTime && result?.endTime 
      ? ((new Date(result.endTime).getTime() - new Date(result.startTime).getTime()) / 1000).toFixed(2) + "s"
      : null;
    const tokens = result?.metrics?.total_tokens;
    const hasResult = result && (result.outputs || result.error);

  return (
    <div
      className={cn(
        "rounded-lg border-2 p-1.5 shadow-sm transition-all bg-card",
        borderColor
      )}
      style={{ width: "160px" }}
    >
      <div className="flex items-center gap-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded bg-purple-100 dark:bg-purple-900/30">
          <Brain className="h-2.5 w-2.5 text-purple-600 dark:text-purple-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-1">
            <div className="font-semibold text-xs truncate text-foreground flex-1">{data.displayName || data.label || "LLM"}</div>
            {statusIcons[executionStatus]}
          </div>
          <div className="text-[10px] text-muted-foreground truncate flex justify-between">
            <span>{data.llmModel || "未选择模型"}</span>
            {duration && <span className="font-medium">{duration}</span>}
          </div>
          {tokens && (
             <div className="text-[10px] text-muted-foreground text-right">
                {tokens} tokens
             </div>
          )}
          {hasResult && executionStatus === "success" && (
            <div className="text-[10px] text-green-600 dark:text-green-400 mt-1 truncate" title="点击查看运行结果">
              ✓ 执行完成
            </div>
          )}
          {hasResult && executionStatus === "error" && (
            <div className="text-[10px] text-red-600 dark:text-red-400 mt-1 truncate" title="点击查看错误信息">
              ✗ 执行失败
            </div>
          )}
        </div>
      </div>
      <Handle 
        type="target" 
        position={Position.Left}
        id="input"
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
      <Handle 
        type="source" 
        position={Position.Right}
        id="output"
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
    </div>
  );
}
