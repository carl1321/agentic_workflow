// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useMemo } from "react";
import { Handle, Position, type NodeProps, NodeResizeControl, type OnResize, useReactFlow } from "@xyflow/react";
import { RotateCcw, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "~/lib/utils";

type ExecutionStatus = "pending" | "ready" | "running" | "success" | "error" | "skipped" | "cancelled";

export function LoopNode({ id, data, selected, width, height }: NodeProps) {
  const { updateNode, getNodes } = useReactFlow();
  const executionStatus: ExecutionStatus = data.executionStatus || "pending";
  const loopCount = data.loopCount || data.loop_count;
  const breakConditions = data.breakConditions || data.break_conditions || [];
  
  // 获取循环容器尺寸，优先使用 ReactFlow 传入的 width/height，否则使用 data 中的值
  const loopWidth = width || data.loopWidth || data.loop_width || 600;
  const loopHeight = height || data.loopHeight || data.loop_height || 400;
  const minWidth = 400;
  const minHeight = 300;
  
  // 获取循环体内的节点数量
  // 使用 getNodes() 直接获取最新节点列表，确保实时更新
  const nodes = getNodes();
  const loopBodyNodeCount = nodes.filter(
    (n) => (n.data?.loopId === id || n.data?.loop_id === id) && n.id !== id
  ).length;
  
  // 处理大小调整 - 使用 ReactFlow 的 NodeResizeControl
  const handleResize: OnResize = useMemo(() => {
    return (_, params) => {
      const { width, height } = params;
      updateNode(id, {
        width,
        height,
        data: {
          ...data,
          loopWidth: width,
          loopHeight: height,
          loop_width: width,
          loop_height: height,
        },
      });
    };
  }, [id, data, updateNode]);
  
  const statusColors = {
    pending: "border-orange-500",
    ready: "border-blue-500 animate-pulse",
    running: "border-yellow-500",
    success: "border-green-500",
    error: "border-red-500",
    skipped: "border-gray-400",
    cancelled: "border-gray-500",
  };
  
  const borderColor = selected
    ? "border-primary shadow-md"
    : `${statusColors[executionStatus] || statusColors.pending} hover:border-orange-600`;

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
        "rounded-lg border-2 shadow-sm transition-all",
        "relative overflow-visible group",
        borderColor
      )}
      style={{ 
        width: `${loopWidth}px`, 
        height: `${loopHeight}px`,
        minWidth: `${minWidth}px`,
        minHeight: `${minHeight}px`,
        background: "transparent", // 容器背景完全透明，不遮挡子节点
        zIndex: 1, // 循环节点在底层
        pointerEvents: "none", // 背景不可交互，让子节点可以交互
      }}
    >
      {/* 循环节点头部 */}
      <div 
        className="absolute top-0 left-0 right-0 h-10 border-b border-border/50 bg-card/80 backdrop-blur-sm rounded-t-lg flex items-center gap-1.5 px-2 z-10"
        style={{ pointerEvents: "auto" }} // 头部可交互
      >
        <div className="flex h-5 w-5 items-center justify-center rounded bg-orange-100 dark:bg-orange-900/30">
          <RotateCcw className="h-2.5 w-2.5 text-orange-600 dark:text-orange-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <div className="font-semibold text-xs truncate text-foreground">
              {data.displayName || data.label || "loop"}
            </div>
            {statusIcons[executionStatus]}
          </div>
          <div className="text-[10px] text-muted-foreground truncate">
            {loopCount ? `最多${loopCount}次` : breakConditions.length > 0 ? `${breakConditions.length}个条件` : "未配置"} · {loopBodyNodeCount} 个节点
          </div>
        </div>
      </div>
      
      {/* 循环体内容区域 - 完全透明，不遮挡子节点 */}
      <div 
        className="absolute top-10 left-0 right-0 bottom-0 rounded-b-lg"
        style={{ 
          width: "100%",
          height: `${loopHeight - 40}px`, // 减去头部高度
          background: "transparent", // 内容区域完全透明
          pointerEvents: "none", // 内容区域不可交互，让循环体内的节点可以交互
        }}
      >
        {/* 这里可以显示循环体内的节点提示 */}
        {data.bodyNodesCount === 0 && (
          <div className="p-4 text-xs text-muted-foreground pointer-events-none">
            将节点拖入此区域以添加到循环体
          </div>
        )}
      </div>
      
      {/* 大小调整手柄 - 使用 ReactFlow 的 NodeResizeControl */}
      <div 
        className={cn(
          "absolute bottom-0 right-0",
          "hidden group-hover:block", 
          selected && "!block"
        )}
        style={{ 
          pointerEvents: "auto",
          zIndex: 30,
        }}
      >
        <NodeResizeControl
          position="bottom-right"
          className="!border-none !bg-transparent hover:opacity-100"
          onResize={handleResize}
          minWidth={minWidth}
          minHeight={minHeight}
          style={{
            cursor: "nwse-resize",
          }}
        >
          <div 
            className="absolute bottom-[1px] right-[1px] cursor-nwse-resize hover:opacity-100 transition-opacity"
            style={{
              width: "16px",
              height: "16px",
              opacity: selected ? 1 : 0.6,
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path 
                d="M5.19009 11.8398C8.26416 10.6196 10.7144 8.16562 11.9297 5.08904" 
                stroke="currentColor" 
                strokeOpacity={selected ? "0.3" : "0.16"} 
                strokeWidth="2" 
                strokeLinecap="round" 
              />
            </svg>
          </div>
        </NodeResizeControl>
      </div>
      
      {/* 连接点 */}
      <Handle 
        type="target" 
        position={Position.Left}
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair !top-1/2 z-30" 
        style={{ top: "50%" }}
      />
      <Handle 
        type="source" 
        position={Position.Right}
        className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-card !cursor-crosshair !top-1/2 z-30" 
        style={{ top: "50%" }}
      />
    </div>
  );
}

