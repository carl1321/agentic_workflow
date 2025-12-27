// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Edge } from "@xyflow/react";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

interface EdgeConfigPanelProps {
  edge: Edge;
  onUpdate: (edgeId: string, data: any) => void;
  onClose: () => void;
}

export function EdgeConfigPanel({ edge, onUpdate, onClose }: EdgeConfigPanelProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">边配置</h3>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          从 {edge.source} 到 {edge.target}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {edge.condition && (
          <div>
            <Label>条件分支</Label>
            <Input value={edge.condition} disabled />
            <p className="mt-1 text-xs text-muted-foreground">
              条件节点的分支标识
            </p>
          </div>
        )}
        {!edge.condition && (
          <div className="text-sm text-muted-foreground text-center py-8">
            此边无需额外配置
            <p className="mt-2 text-xs">
              参数映射已在节点配置中通过变量引用实现
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

