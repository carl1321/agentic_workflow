// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Badge } from "~/components/ui/badge";
import { format } from "date-fns";

interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
}

export default function AdminWorkflowsPage() {
  const router = useRouter();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch("/api/workflows?limit=100");
      if (!response.ok) {
        throw new Error("加载工作流列表失败");
      }
      const data = await response.json();
      setWorkflows(data.workflows || []);
    } catch (err: any) {
      setError(err.message || "加载工作流列表失败");
      console.error("Error loading workflows:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = () => {
    // 创建新工作流，跳转到编辑器
    router.push("/admin/workflows/new");
  };

  const handleEdit = (workflowId: string) => {
    router.push(`/admin/workflows/${workflowId}/editor`);
  };

  const handleViewRuns = (workflowId: string) => {
    router.push(`/workflow/${workflowId}/runs`);
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
    <div className="container mx-auto p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">工作流管理</h1>
          <p className="text-muted-foreground">创建和管理工作流</p>
        </div>
        <Button onClick={handleCreate}>创建工作流</Button>
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
            <Button className="mt-4" onClick={handleCreate}>
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
                  <CardTitle className="text-lg">{workflow.name}</CardTitle>
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
                    创建时间: {workflow.created_at ? format(new Date(workflow.created_at), "yyyy-MM-dd HH:mm:ss") : "N/A"}
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
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

