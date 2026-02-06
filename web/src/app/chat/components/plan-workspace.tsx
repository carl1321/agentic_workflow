// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { FileText, ListChecks, MessageCircle } from "lucide-react";

import { Badge } from "~/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { getPlan, streamPlanEvents, type PlanDetail } from "~/core/api/plans";

import { PlanMessagesBlock } from "./plan-messages-block";
import { PlanOutputsTab } from "./plan-outputs-tab";
import { PlanTasksTab } from "./plan-tasks-tab";

export function PlanWorkspace({ planId }: { planId: string }) {
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const title = plan?.title || "长期计划";
  const status = plan?.status || "draft";

  /** 当前阶段说明，便于用户区分是澄清未展示还是规划/执行日志未同步 */
  const phaseLabel =
    status === "draft"
      ? "澄清中"
      : status === "active"
        ? "规划中"
        : status === "running"
          ? "执行中"
          : status === "terminated" || status === "canceled"
            ? "已终止"
            : status === "completed"
              ? "已完成"
              : status;

  // 初次加载计划详情
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await getPlan(planId);
        if (cancelled) return;
        setPlan(res.plan);
      } catch (e) {
        console.error("Failed to load plan:", e);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [planId]);

  // 监听日志变更，刷新 plan（任务状态/计划状态会变）
  useEffect(() => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    let stopped = false;
    async function run() {
      try {
        for await (const ev of streamPlanEvents(planId, { abortSignal: ac.signal })) {
          if (stopped) return;
          if (ev.type !== "log") continue;
          // 轻量刷新（不做复杂 diff；MVP 足够）
          getPlan(planId).then((res) => setPlan(res.plan)).catch(() => {});
        }
      } catch (e) {
        if (!ac.signal.aborted && !stopped) console.error("plan workspace stream error:", e);
      }
    }
    void run();
    return () => {
      stopped = true;
      ac.abort();
    };
  }, [planId]);

  const rawGoal = useMemo(() => plan?.rawGoal || "", [plan?.rawGoal]);

  return (
    <div className="flex w-full max-w-5xl flex-1 flex-col px-4 pt-4 pb-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-slate-800 dark:text-slate-100">{title}</div>
          {rawGoal ? (
            <div className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400 whitespace-pre-wrap">
              {rawGoal}
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-500 dark:text-slate-400">当前阶段：{phaseLabel}</span>
          <Badge variant="secondary">{status}</Badge>
        </div>
      </div>

      <Tabs defaultValue="chat" className="flex-1">
        <TabsList className="w-full">
          <TabsTrigger value="chat" className="gap-2">
            <MessageCircle className="h-4 w-4" />
            对话
          </TabsTrigger>
          <TabsTrigger value="tasks" className="gap-2">
            <ListChecks className="h-4 w-4" />
            任务
          </TabsTrigger>
          <TabsTrigger value="outputs" className="gap-2">
            <FileText className="h-4 w-4" />
            产物
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chat" className="mt-2 flex-1">
          <div className="h-[calc(100vh-190px)] min-h-[520px]">
            <PlanMessagesBlock planId={planId} planStatus={status} className="h-full" />
          </div>
        </TabsContent>

        <TabsContent value="tasks" className="mt-2 flex-1">
          <PlanTasksTab plan={plan} />
        </TabsContent>

        <TabsContent value="outputs" className="mt-2 flex-1">
          <PlanOutputsTab planId={planId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

