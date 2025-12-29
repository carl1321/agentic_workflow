// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Badge } from "~/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

interface Run {
  id: string;
  status: string;
  input: any;
  output?: any;
  error?: any;
  created_at: string;
  started_at?: string;
  finished_at?: string;
}

interface Task {
  id: string;
  node_id: string;
  node_display_name?: string;  // 节点显示名称
  status: string;
  input?: any;
  output?: any;
  error?: any;
  started_at?: string;
  finished_at?: string;
}

interface Log {
  seq: number;
  level: string;
  event: string;
  payload?: any;
  node_id?: string;
  time: string;
}

export default function WorkflowRunDetailPage() {
  const params = useParams();
  const router = useRouter();
  const workflowId = params.id as string;
  const runId = params.runId as string;
  
  const [run, setRun] = useState<Run | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastSeq, setLastSeq] = useState(0);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    loadRun();
    loadTasks();
    loadLogs();
  }, [workflowId, runId]);

  useEffect(() => {
    if (run?.status === "running") {
      setPolling(true);
      const interval = setInterval(() => {
        loadRun();
        loadTasks();
        loadLogs(lastSeq);
      }, 2000);
      return () => {
        clearInterval(interval);
        setPolling(false);
      };
    }
  }, [run?.status, lastSeq]);

  const loadRun = async () => {
    try {
      const { resolveServiceURL } = await import("~/core/api/resolve-service-url");
      const url = resolveServiceURL(`workflows/${workflowId}/runs/${runId}`);
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to load run: ${response.status}`);
      }
      const data = await response.json();
      setRun(data);
    } catch (error) {
      console.error("Error loading run:", error);
    }
  };

  const loadTasks = async () => {
    try {
      const { resolveServiceURL } = await import("~/core/api/resolve-service-url");
      const url = resolveServiceURL(`workflows/${workflowId}/runs/${runId}/tasks`);
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to load tasks: ${response.status}`);
      }
      const data = await response.json();
      setTasks(data.tasks || []);
    } catch (error) {
      console.error("Error loading tasks:", error);
    }
  };

  const loadLogs = async (afterSeq?: number) => {
    try {
      const { resolveServiceURL } = await import("~/core/api/resolve-service-url");
      const url = afterSeq
        ? resolveServiceURL(`workflows/${workflowId}/runs/${runId}/logs?after_seq=${afterSeq}`)
        : resolveServiceURL(`workflows/${workflowId}/runs/${runId}/logs`);
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to load logs: ${response.status}`);
      }
      const data = await response.json();
      const newLogs = data.logs || [];
      if (afterSeq) {
        setLogs((prev) => [...prev, ...newLogs]);
      } else {
        setLogs(newLogs);
      }
      if (newLogs.length > 0) {
        setLastSeq(newLogs[newLogs.length - 1].seq);
      }
    } catch (error) {
      console.error("Error loading logs:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      const { resolveServiceURL } = await import("~/core/api/resolve-service-url");
      const url = resolveServiceURL(`workflows/${workflowId}/runs/${runId}/cancel`);
      const response = await fetch(url, {
        method: "POST",
      });
      if (response.ok) {
        toast.success("运行已取消");
        loadRun();
      }
    } catch (error) {
      console.error("Error canceling run:", error);
      toast.error("取消运行失败");
    }
  };

  const handleDelete = async () => {
    if (!confirm("确定要删除这个运行记录吗？此操作不可恢复。")) {
      return;
    }

    try {
      const { resolveServiceURL } = await import("~/core/api/resolve-service-url");
      const url = resolveServiceURL(`workflows/${workflowId}/runs/${runId}`);
      const response = await fetch(url, {
        method: "DELETE",
      });
      
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "删除失败");
      }
      
      toast.success("运行记录已删除");
      // 返回运行历史页面
      router.push(`/workflow/${workflowId}/runs`);
    } catch (error: any) {
      console.error("Error deleting run:", error);
      toast.error(error.message || "删除运行记录失败");
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

  if (loading) {
    return <div className="container mx-auto p-6">加载中...</div>;
  }

  if (!run) {
    return <div className="container mx-auto p-6">运行不存在</div>;
  }

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">运行详情</h1>
          <p className="text-muted-foreground">运行 ID: {runId}</p>
        </div>
        <div className="flex gap-2">
          {run.status === "running" && (
            <Button variant="destructive" onClick={handleCancel}>
              取消运行
            </Button>
          )}
          {run.status !== "running" && run.status !== "queued" && (
            <Button 
              variant="destructive" 
              onClick={handleDelete}
              className="gap-2"
            >
              <Trash2 className="h-4 w-4" />
              删除
            </Button>
          )}
          <Button variant="outline" onClick={() => router.back()}>
            返回
          </Button>
        </div>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>运行信息</CardTitle>
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
            {run.error && (
              <div className="mt-4">
                <div className="font-semibold text-destructive">错误信息:</div>
                <pre className="mt-2 rounded bg-destructive/10 p-2 text-xs">
                  {JSON.stringify(run.error, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="tasks" className="w-full">
        <TabsList>
          <TabsTrigger value="tasks">任务列表</TabsTrigger>
          <TabsTrigger value="logs">日志</TabsTrigger>
        </TabsList>
        <TabsContent value="tasks">
          <div className="space-y-4">
            {tasks.map((task) => (
              <Card key={task.id}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">节点: {task.node_display_name || task.node_id}</CardTitle>
                    {getStatusBadge(task.status)}
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    {task.started_at && <div>开始时间: {new Date(task.started_at).toLocaleString("zh-CN", {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}</div>}
                    {task.finished_at && <div>结束时间: {new Date(task.finished_at).toLocaleString("zh-CN", {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}</div>}
                    {task.input && (
                      <details className="mt-2">
                        <summary className="cursor-pointer font-semibold">输入</summary>
                        <pre className="mt-2 rounded bg-muted p-2 text-xs">
                          {JSON.stringify(task.input, null, 2)}
                        </pre>
                      </details>
                    )}
                    {task.output && (
                      <details className="mt-2">
                        <summary className="cursor-pointer font-semibold">输出</summary>
                        <pre className="mt-2 rounded bg-muted p-2 text-xs">
                          {JSON.stringify(task.output, null, 2)}
                        </pre>
                      </details>
                    )}
                    {task.error && (
                      <details className="mt-2">
                        <summary className="cursor-pointer font-semibold text-destructive">错误</summary>
                        <pre className="mt-2 rounded bg-destructive/10 p-2 text-xs">
                          {JSON.stringify(task.error, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>运行日志</CardTitle>
                {polling && <Badge variant="secondary">实时更新中...</Badge>}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {logs.map((log) => (
                  <div key={log.seq} className="rounded border p-2 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant={log.level === "error" ? "destructive" : "secondary"}>
                        {log.level}
                      </Badge>
                      <span className="font-mono text-xs text-muted-foreground">
                        {log.time ? new Date(log.time).toLocaleTimeString("zh-CN", {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        }) : ""}
                      </span>
                      <span className="font-semibold">{log.event}</span>
                      {log.node_id && (
                        <span className="text-muted-foreground">
                          ({tasks.find(t => t.node_id === log.node_id)?.node_display_name || log.node_id})
                        </span>
                      )}
                    </div>
                    {log.payload && (
                      <pre className="mt-1 rounded bg-muted p-2 text-xs">
                        {JSON.stringify(log.payload, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

