// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Wrench, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "~/lib/utils";

type ExecutionStatus = "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled";

export function ToolNode({ data, selected }: NodeProps) {
  const executionStatus: ExecutionStatus = data.executionStatus || "pending";
  const statusColors = {
    pending: "border-purple-500",
    ready: "border-blue-500 animate-pulse",
    running: "border-yellow-500",
    success: "border-green-500",
    error: "border-red-500",
    skipped: "border-gray-400",
    cancelled: "border-gray-500",
  };
  
  const borderColor = selected
    ? "border-primary shadow-md"
    : `${statusColors[executionStatus] || statusColors.pending} hover:border-purple-600`;

  const statusIcons = {
    pending: null,
    ready: <Loader2 className="h-3 w-3 text-blue-500" />,
    running: <Loader2 className="h-3 w-3 animate-spin text-yellow-500" />,
    success: <CheckCircle2 className="h-3 w-3 text-green-500" />,
    error: <XCircle className="h-3 w-3 text-red-500" />,
    skipped: <span className="text-xs text-gray-500">⏭</span>,
    cancelled: <span className="text-xs text-gray-500">✕</span>,
  };

  const result = data.executionResult;
  const duration = result?.startTime && result?.endTime 
    ? ((new Date(result.endTime).getTime() - new Date(result.startTime).getTime()) / 1000).toFixed(2) + "s"
    : null;

  return (
    <div
      className={cn(
        "rounded-lg border-2 p-2 shadow-sm transition-all bg-card",
        borderColor
      )}
      style={{ width: "200px" }}
    >
      <div className="flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded bg-purple-100 dark:bg-purple-900/30">
          <Wrench className="h-3 w-3 text-purple-600 dark:text-purple-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-1">
            <div className="font-semibold text-xs truncate text-foreground flex-1">{data.displayName || data.label || "工具"}</div>
            {statusIcons[executionStatus]}
          </div>
          <div className="text-[10px] text-muted-foreground truncate flex justify-between">
            <span>{data.toolName}</span>
            {duration && <span>{duration}</span>}
          </div>
        </div>
      </div>
      <Handle 
        type="target" 
        position={Position.Left}
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
      <Handle 
        type="source" 
        position={Position.Right}
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
    </div>
  );
}

