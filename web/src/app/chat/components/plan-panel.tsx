// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "~/components/ui/collapsible";
import {
  getArtifactContent,
  getPlan,
  streamPlanEvents,
  type PlanDetail,
  type PlanLogItem,
} from "~/core/api/plans";

function LogBlock({ log }: { log: PlanLogItem }) {
  const payload = log.payload || {};
  const title = payload.title as string | undefined;
  const icon = payload.icon as string | undefined;
  const bullets = payload.bullets as string[] | undefined;
  const isBlock = Boolean(title && (icon || bullets?.length));

  if (!isBlock) {
    return (
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30 px-3 py-2 text-xs font-mono text-slate-600 dark:text-slate-400">
        {log.level} {log.event}{" "}
        {log.taskId ? `task=${log.taskId}` : ""}
        {Object.keys(payload).length ? ` ${JSON.stringify(payload)}` : ""}
      </div>
    );
  }

  const IconComponent =
    icon === "success"
      ? CheckCircle2
      : icon === "error"
        ? XCircle
        : Info;
  const iconClass =
    icon === "success"
      ? "text-emerald-600 dark:text-emerald-400"
      : icon === "error"
        ? "text-red-600 dark:text-red-400"
        : "text-slate-500 dark:text-slate-400";

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/50 px-4 py-3 shadow-sm">
      <div className="flex items-start gap-3">
        <IconComponent className={`h-5 w-5 shrink-0 mt-0.5 ${iconClass}`} />
        <div className="min-w-0 flex-1">
          <div className="font-medium text-slate-800 dark:text-slate-200">{title}</div>
          {bullets && bullets.length > 0 && (
            <ul className="mt-2 list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              {bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export function PlanPanel({ planId }: { planId: string }) {
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [logs, setLogs] = useState<PlanLogItem[]>([]);
  const [artifactPreview, setArtifactPreview] = useState<{ title: string; content: string } | null>(null);
  const [stepsOpen, setStepsOpen] = useState(true);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const title = plan?.title || "长期计划";
  const stepCount = plan?.tasks?.length ?? 0;

  // 初次加载详情
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await getPlan(planId);
        if (cancelled) return;
        setPlan(res.plan);
      } catch (e) {
        console.error("Failed to load plan detail:", e);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [planId]);

  // SSE：实时追加日志，并刷新 plan
  useEffect(() => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    let stopped = false;
    async function run() {
      try {
        for await (const ev of streamPlanEvents(planId, { since: undefined, abortSignal: ac.signal })) {
          if (stopped) return;
          if (ev.type === "log") {
            setLogs((prev) => {
              const data = (ev as any).data;
              if (prev.some((x) => x.id === data.id)) return prev;
              return [...prev, data];
            });
            getPlan(planId).then((res) => setPlan(res.plan)).catch(() => {});
          }
        }
      } catch (e) {
        if (!stopped) console.error("plan events stream error:", e);
      }
    }
    void run();
    return () => {
      stopped = true;
      ac.abort();
    };
  }, [planId]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  async function onPreviewArtifact(artifactId: string, title: string) {
    try {
      const res = await getArtifactContent(planId, artifactId);
      setArtifactPreview({ title, content: res.content });
    } catch (e) {
      console.error("Failed to preview artifact:", e);
    }
  }

  // 过滤掉“澄清提问”类日志，澄清对话交给聊天区展示
  const displayLogs = logs.filter((l) => l.event !== "clarify_question");

  return (
    <div className="w-full h-full pb-4 overflow-y-auto">
      {/* 顶部：目标气泡 */}
      {plan?.rawGoal && (
        <div className="mb-4 rounded-xl bg-slate-100 dark:bg-slate-800/80 px-4 py-3 text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap">
          {plan.rawGoal}
        </div>
      )}

      {/* 可折叠：共 N 个步骤 */}
      {stepCount > 0 && (
        <Collapsible open={stepsOpen} onOpenChange={setStepsOpen} className="mb-4">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/60"
            >
              {stepsOpen ? (
                <ChevronDown className="h-4 w-4 shrink-0" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0" />
              )}
              <span>
                {plan?.title || "本计划"} 共 {stepCount} 个步骤
              </span>
              <Badge variant="secondary" className="ml-auto">{plan?.status || "—"}</Badge>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-2 space-y-1 pl-6">
              {plan?.tasks?.map((t, i) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between rounded border border-slate-200 dark:border-slate-700 px-3 py-2 text-sm"
                >
                  <span className="text-slate-700 dark:text-slate-300">
                    {i + 1}. {t.name}
                  </span>
                  <Badge variant="secondary">{t.status}</Badge>
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* 主内容区：执行状态（按块展示） */}
      <div className="mb-4">
        <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">执行状态</div>
        {displayLogs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-4 py-6 text-center text-sm text-slate-500">
            暂无执行日志，任务将按依赖顺序自动执行
          </div>
        ) : (
          <div className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
            {displayLogs.map((l) => (
              <LogBlock key={l.id} log={l} />
            ))}
            <div ref={logEndRef} />
          </div>
        )}
      </div>

      {/* 可折叠：任务列表 */}
      <Collapsible open={tasksOpen} onOpenChange={setTasksOpen} className="mb-4">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 px-4 py-2 text-left text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/60"
          >
            {tasksOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            任务列表
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Card className="mt-2">
            <CardContent className="pt-3 space-y-2">
              {!plan ? (
                <div className="text-sm text-slate-500">加载中…</div>
              ) : plan.tasks.length === 0 ? (
                <div className="text-sm text-slate-500">尚未生成任务</div>
              ) : (
                plan.tasks.map((t) => (
                  <div key={t.id} className="rounded border border-slate-200 dark:border-slate-700 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium truncate">{t.name}</div>
                      <Badge variant="secondary">{t.status}</Badge>
                    </div>
                    {t.description && <div className="text-xs text-slate-500 mt-1">{t.description}</div>}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>

      {/* 可折叠：产物 */}
      <Collapsible open={artifactsOpen} onOpenChange={setArtifactsOpen} className="mb-4">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 px-4 py-2 text-left text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/60"
          >
            {artifactsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            产物
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Card className="mt-2">
            <CardContent className="pt-3 space-y-2">
              {!plan ? (
                <div className="text-sm text-slate-500">加载中…</div>
              ) : plan.artifacts.length === 0 ? (
                <div className="text-sm text-slate-500">暂无产物</div>
              ) : (
                plan.artifacts.map((a) => (
                  <div
                    key={a.id}
                    className="rounded border border-slate-200 dark:border-slate-700 px-3 py-2 flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{(a.meta as any)?.relpath ? String((a.meta as any).relpath) : a.id}</div>
                      <div className="text-xs text-slate-500 truncate">{a.filePath}</div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onPreviewArtifact(a.id, (a.meta as any)?.relpath ? String((a.meta as any).relpath) : a.id)}
                    >
                      预览
                    </Button>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>

      {artifactPreview && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base truncate">预览：{artifactPreview.title}</CardTitle>
            <Button variant="outline" size="sm" onClick={() => setArtifactPreview(null)}>
              关闭
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap break-words max-h-64 overflow-y-auto">{artifactPreview.content}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
