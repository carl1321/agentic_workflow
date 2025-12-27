// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { cn } from "~/lib/utils";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Badge } from "~/components/ui/badge";
import { Plus, Edit, Play, History, Trash2 } from "lucide-react";
import { listWorkflows, deleteWorkflow } from "~/core/api/workflow";
import type { Workflow } from "~/core/api/workflow";
import { resolveServiceURL } from "~/core/api/resolve-service-url";


interface WorkflowListProps {
  onWorkflowSelect?: (workflow: Workflow) => void;
  onEdit?: (workflowId: string) => void;
  onViewRuns?: (workflowId: string) => void;
}

export function WorkflowList({ onWorkflowSelect, onEdit, onViewRuns }: WorkflowListProps) {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listWorkflows({ limit: 100 });
      setWorkflows(data.workflows || []);
    } catch (err: any) {
      setError(err.message || "加载工作流列表失败");
      console.error("Error loading workflows:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (workflowId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("确定要删除这个工作流吗？此操作不可恢复。")) {
      return;
    }

    try {
      setDeletingId(workflowId);
      await deleteWorkflow(workflowId);
      setWorkflows((prev) => prev.filter((w) => w.id !== workflowId));
    } catch (err: any) {
      setError(err.message || "删除工作流失败");
      console.error("Error deleting workflow:", err);
    } finally {
      setDeletingId(null);
    }
  };

  const handleCreate = () => {
    // 创建新工作流，跳转到编辑器
    window.open("/workflows/new", "_blank");
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      draft: "secondary",
      published: "default",
      archived: "outline",
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">工作流管理</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">创建和管理工作流</p>
          </div>
          <Button onClick={handleCreate} size="sm">
            <Plus className="h-4 w-4 mr-2" />
            创建工作流
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 rounded bg-destructive/10 p-4 text-destructive text-sm">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-sm text-slate-500 dark:text-slate-400">加载中...</div>
          </div>
        ) : workflows.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="p-4 rounded-lg bg-slate-100 dark:bg-slate-800 w-fit mb-4">
              <Plus className="h-8 w-8 text-slate-400 dark:text-slate-500" />
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">暂无工作流</p>
            <Button onClick={handleCreate} size="sm">
              <Plus className="h-4 w-4 mr-2" />
              创建工作流
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {workflows.map((workflow) => (
              <motion.div
                key={workflow.id}
                whileHover={{ scale: 1.02, y: -2 }}
                whileTap={{ scale: 0.98 }}
                className="group"
              >
                <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base line-clamp-1">{workflow.name}</CardTitle>
                      {getStatusBadge(workflow.status)}
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {workflow.description && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                          {workflow.description}
                        </p>
                      )}
                      <div className="text-xs text-slate-400 dark:text-slate-500">
                        创建时间: {workflow.created_at ? new Date(workflow.created_at).toLocaleString("zh-CN", {
                          year: "numeric",
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        }) : "N/A"}
                      </div>
                      <div className="flex gap-2 pt-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="flex-1 text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            onEdit?.(workflow.id);
                          }}
                        >
                          <Edit className="h-3 w-3 mr-1" />
                          编辑
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="flex-1 text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            onViewRuns?.(workflow.id);
                          }}
                        >
                          <History className="h-3 w-3 mr-1" />
                          运行历史
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs text-destructive hover:text-destructive"
                          onClick={(e) => handleDelete(workflow.id, e)}
                          disabled={deletingId === workflow.id}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

