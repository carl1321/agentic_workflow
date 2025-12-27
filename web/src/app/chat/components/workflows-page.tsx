// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Badge } from "~/components/ui/badge";
import { createWorkflow, deleteWorkflow, listWorkflows, updateWorkflow } from "~/core/api/workflow";
import type { Workflow } from "~/core/api/workflow";
import { Trash2, Edit2 } from "lucide-react";
import { CreateWorkflowDialog } from "~/app/workflows/components/CreateWorkflowDialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Textarea } from "~/components/ui/textarea";

interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
}

export function WorkflowsPage() {
  const router = useRouter();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

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

  const handleCreate = async (name: string, description?: string) => {
    try {
      const newWorkflow = await createWorkflow({
        name,
        description: description || "",
        status: "draft",
      });
      router.push(`/workflows/${newWorkflow.id}/editor`);
    } catch (err: any) {
      setError(err.message || "创建工作流失败");
      console.error("Error creating workflow:", err);
    }
  };

  const handleEditName = (workflow: Workflow) => {
    setEditingWorkflow(workflow);
    setEditName(workflow.name);
    setEditDescription(workflow.description || "");
  };

  const handleSaveEdit = async () => {
    if (!editingWorkflow) return;
    if (!editName.trim()) {
      setError("工作流名称不能为空");
      return;
    }

    try {
      const updated = await updateWorkflow(editingWorkflow.id, {
        name: editName.trim(),
        description: editDescription.trim() || undefined,
      });
      setWorkflows((prev) =>
        prev.map((w) => (w.id === updated.id ? updated : w))
      );
      setEditingWorkflow(null);
      setEditName("");
      setEditDescription("");
      setError(null);
    } catch (err: any) {
      setError(err.message || "更新工作流失败");
      console.error("Error updating workflow:", err);
    }
  };

  const handleEdit = (workflowId: string) => {
    router.push(`/workflows/${workflowId}/editor`);
  };

  const handleViewRuns = (workflowId: string) => {
    router.push(`/workflow/${workflowId}/runs`);
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

  const getStatusBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      draft: "secondary",
      published: "default",
      archived: "outline",
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex-1 overflow-auto">
        <div className="container mx-auto p-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">工作流管理</h1>
              <p className="text-muted-foreground">创建和管理工作流</p>
            </div>
            <Button onClick={() => setShowCreateDialog(true)}>创建工作流</Button>
          </div>

          {error && (
            <div className="mb-4 rounded bg-destructive/10 p-4 text-destructive">
              {error}
            </div>
          )}

          {loading ? (
            <div>加载中...</div>
          ) : workflows.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <p className="text-muted-foreground">暂无工作流</p>
                <Button className="mt-4" onClick={() => setShowCreateDialog(true)}>
                  创建工作流
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {workflows.map((workflow) => (
                <Card key={workflow.id} className="hover:shadow-lg transition-shadow">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <CardTitle className="text-lg truncate">{workflow.name}</CardTitle>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 flex-shrink-0"
                          onClick={() => handleEditName(workflow)}
                          title="编辑名称"
                        >
                          <Edit2 className="h-3 w-3" />
                        </Button>
                      </div>
                      {getStatusBadge(workflow.status)}
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2 text-sm">
                      {workflow.description && (
                        <p className="text-muted-foreground line-clamp-2">
                          {workflow.description}
                        </p>
                      )}
                      <div className="text-muted-foreground">
                        创建时间: {workflow.created_at ? new Date(workflow.created_at).toLocaleString("zh-CN", {
                          year: "numeric",
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        }) : "N/A"}
                      </div>
                      <div className="flex gap-2 mt-4">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleEdit(workflow.id)}
                        >
                          编辑
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleViewRuns(workflow.id)}
                        >
                          运行历史
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(e) => handleDelete(workflow.id, e)}
                          disabled={deletingId === workflow.id}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 创建工作流对话框 */}
      <CreateWorkflowDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onCreate={handleCreate}
      />

      {/* 编辑工作流名称对话框 */}
      <Dialog open={!!editingWorkflow} onOpenChange={(open) => !open && setEditingWorkflow(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑工作流</DialogTitle>
            <DialogDescription>
              修改工作流的名称和描述
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">
                名称 <span className="text-red-500">*</span>
              </Label>
              <Input
                id="edit-name"
                value={editName}
                onChange={(e) => {
                  setEditName(e.target.value);
                  setError(null);
                }}
                placeholder="输入工作流名称"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSaveEdit();
                  }
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-description">描述</Label>
              <Textarea
                id="edit-description"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="输入工作流描述（可选）"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingWorkflow(null)}>
              取消
            </Button>
            <Button onClick={handleSaveEdit}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

