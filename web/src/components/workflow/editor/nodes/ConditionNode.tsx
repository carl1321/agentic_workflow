// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { GitBranch, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "~/lib/utils";

type ExecutionStatus = "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled";

export function ConditionNode({ data, selected }: NodeProps) {
  const executionStatus: ExecutionStatus = data.executionStatus || "pending";
  const statusColors = {
    pending: "border-yellow-500",
    ready: "border-blue-500 animate-pulse",
    running: "border-yellow-500",
    success: "border-green-500",
    error: "border-red-500",
    skipped: "border-gray-400",
    cancelled: "border-gray-500",
  };
  
  const borderColor = selected
    ? "border-primary shadow-md"
    : `${statusColors[executionStatus] || statusColors.pending} hover:border-yellow-600`;

  const statusIcons = {
    pending: null,
    ready: <Loader2 className="h-2.5 w-2.5 text-blue-500" />,
    running: <Loader2 className="h-2.5 w-2.5 animate-spin text-yellow-500" />,
    success: <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />,
    error: <XCircle className="h-2.5 w-2.5 text-red-500" />,
    skipped: <span className="text-[10px] text-gray-500">⏭</span>,
    cancelled: <span className="text-[10px] text-gray-500">✕</span>,
  };

  return (
    <div
      className={cn(
        "rounded-lg border-2 p-1.5 shadow-sm transition-all bg-card",
        borderColor
      )}
      style={{ width: "140px" }}
    >
      <div className="flex items-center gap-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded bg-yellow-100 dark:bg-yellow-900/30">
          <GitBranch className="h-2.5 w-2.5 text-yellow-600 dark:text-yellow-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <div className="font-semibold text-xs truncate text-foreground">{data.displayName || data.label || "条件"}</div>
            {statusIcons[executionStatus]}
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
        position={Position.Top}
        id="true"
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
      <Handle 
        type="source" 
        position={Position.Bottom}
        id="false"
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair" 
      />
    </div>
  );
}

