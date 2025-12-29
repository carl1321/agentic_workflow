// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Square, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "~/lib/utils";

type ExecutionStatus = "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled";

export function EndNode({ data, selected }: NodeProps) {
  const executionStatus: ExecutionStatus = data.executionStatus || "pending";
  const statusColors = {
    pending: "border-red-500",
    ready: "border-blue-500 animate-pulse",
    running: "border-yellow-500",
    success: "border-green-500",
    error: "border-red-500",
    skipped: "border-gray-400",
    cancelled: "border-gray-500",
  };
  
  const borderColor = selected
    ? "border-primary shadow-md"
    : `${statusColors[executionStatus] || statusColors.pending} hover:border-red-600`;

  const statusIcons = {
    pending: null,
    ready: <Loader2 className="h-2.5 w-2.5 text-blue-500" />,
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

  return (
    <div
      className={cn(
        "rounded-lg border-2 p-1.5 shadow-sm transition-all bg-card",
        borderColor
      )}
      style={{ width: "140px" }}
    >
      <div className="flex items-center gap-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded bg-red-100 dark:bg-red-900/30">
          <Square className="h-2.5 w-2.5 text-red-600 dark:text-red-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-1">
            <div className="font-semibold text-xs truncate text-foreground flex-1">{data.displayName || data.label || "结束"}</div>
            {statusIcons[executionStatus]}
          </div>
          {duration && (
            <div className="text-[10px] text-muted-foreground text-right">
              {duration}
            </div>
          )}
        </div>
      </div>
      <Handle 
        type="target" 
        position={Position.Left}
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
    </div>
  );
}

