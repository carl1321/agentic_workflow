// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Badge } from "~/components/ui/badge";

interface Run {
  id: string;
  status: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  created_by_name?: string;
}

export default function WorkflowRunsPage() {
  const params = useParams();
  const router = useRouter();
  const workflowId = params.id as string;
  
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    loadRuns();
  }, [workflowId, offset]);

  const loadRuns = async () => {
    try {
      setLoading(true);
      const response = await fetch(`/api/workflows/${workflowId}/runs?limit=${limit}&offset=${offset}`);
      const data = await response.json();
      setRuns(data.runs || []);
      setTotal(data.total || 0);
    } catch (error) {
      console.error("Error loading runs:", error);
    } finally {
      setLoading(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      queued: "secondary",
      running: "default",
      success: "default",
      failed: "destructive",
      canceled: "outline",
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">运行历史</h1>
        <p className="text-muted-foreground">工作流 ID: {workflowId}</p>
      </div>

      {loading ? (
        <div>加载中...</div>
      ) : (
        <>
          <div className="space-y-4">
            {runs.map((run) => (
              <Card key={run.id} className="cursor-pointer hover:bg-accent" onClick={() => router.push(`/workflow/${workflowId}/runs/${run.id}`)}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">运行 {run.id.slice(0, 8)}</CardTitle>
                    {getStatusBadge(run.status)}
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    <div>创建时间: {run.created_at ? new Date(run.created_at).toLocaleString("zh-CN", {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    }) : "N/A"}</div>
                    {run.started_at && <div>开始时间: {new Date(run.started_at).toLocaleString("zh-CN", {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}</div>}
                    {run.finished_at && <div>结束时间: {new Date(run.finished_at).toLocaleString("zh-CN", {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}</div>}
                    {run.created_by_name && <div>创建者: {run.created_by_name}</div>}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="mt-6 flex items-center justify-between">
            <Button
              variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              上一页
            </Button>
            <div className="text-sm text-muted-foreground">
              显示 {offset + 1} - {Math.min(offset + limit, total)} / {total}
            </div>
            <Button
              variant="outline"
              disabled={offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
            >
              下一页
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

