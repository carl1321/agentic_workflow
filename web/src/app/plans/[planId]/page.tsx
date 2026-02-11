// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Button } from "~/components/ui/button";
import { Textarea } from "~/components/ui/textarea";
import { Badge } from "~/components/ui/badge";
import {
  answerClarify,
  finalizePlan,
  getArtifactContent,
  getClarify,
  getPlan,
  listPlanLogs,
  restartPlan,
  runPlan,
  type PlanDetail,
  type PlanLogItem,
} from "~/core/api/plans";

export default function PlanDetailPage() {
  const params = useParams<{ planId: string }>();
  const router = useRouter();
  const planId = params.planId;

  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [logs, setLogs] = useState<PlanLogItem[]>([]);
  const [question, setQuestion] = useState<string | null>(null);
  const [clarifyRound, setClarifyRound] = useState(0);
  const [clarifyDone, setClarifyDone] = useState(false);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifactPreview, setArtifactPreview] = useState<{ title: string; content: string } | null>(null);

  const canFinalize = useMemo(() => {
    return !!plan && !question && clarifyDone && (plan.status === "draft" || plan.status === "active");
  }, [plan, question, clarifyDone]);

  const displayLogs = useMemo(
    () => logs.filter((l) => l.event !== "plan_message"),
    [logs]
  );

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await getPlan(planId);
      setPlan(p.plan);
      const l = await listPlanLogs(planId, 500, 0);
      setLogs(l.logs || []);
      const c = await getClarify(planId);
      setClarifyRound(c.round);
      setQuestion(c.question ?? null);
      setClarifyDone(c.done);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(() => {
      // 轮询任务状态/日志（MVP）
      refresh().catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  const onSubmitAnswer = async () => {
    const a = answer.trim();
    if (!a) return;
    setLoading(true);
    setError(null);
    try {
      const res = await answerClarify(planId, a);
      setAnswer("");
      setClarifyRound(res.round);
      setQuestion(res.question ?? null);
      setClarifyDone(res.done);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const onFinalize = async () => {
    setLoading(true);
    setError(null);
    try {
      await finalizePlan(planId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const onRun = async () => {
    setLoading(true);
    setError(null);
    try {
      if (plan?.status === "running" || plan?.status === "failed") {
        await restartPlan(planId, "uncompleted_only");
      } else {
        await runPlan(planId);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const showRestartLabel = plan?.status === "running" || plan?.status === "failed";
  const hasFailedTasks = plan?.tasks?.some((t) => t.status === "failed") ?? false;

  const onPreviewArtifact = async (artifactId: string, title: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getArtifactContent(planId, artifactId);
      setArtifactPreview({ title, content: res.content });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container mx-auto max-w-5xl p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="text-lg font-semibold">计划详情</div>
          <div className="text-xs text-slate-500">{planId}</div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => router.push("/plans")}>
            返回列表
          </Button>
          <Button variant="outline" onClick={refresh} disabled={loading}>
            刷新
          </Button>
        </div>
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">{plan?.title || "未命名计划"}</CardTitle>
          <Badge variant="secondary">{plan?.status || "loading"}</Badge>
        </CardHeader>
        <CardContent className="space-y-2">
          {plan?.rawGoal && (
            <div className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
              {plan.rawGoal}
            </div>
          )}
          <div className="flex gap-2">
            <Button onClick={onFinalize} disabled={loading || !canFinalize}>
              生成任务（Finalize）
            </Button>
            <Button
              onClick={onRun}
              disabled={
                loading ||
                !plan ||
                (plan.status !== "active" && plan.status !== "running" && plan.status !== "failed")
              }
            >
              {showRestartLabel ? "仅重跑未完成/失败的任务" : "运行计划"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 澄清区 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">目标澄清（最多 3 轮）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-xs text-slate-500">当前轮次：{clarifyRound}</div>
          {question ? (
            <>
              <div className="text-sm font-medium">问题</div>
              <div className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">{question}</div>
              <Textarea
                placeholder="输入你的回答"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={3}
              />
              <Button onClick={onSubmitAnswer} disabled={loading || answer.trim().length === 0}>
                提交回答
              </Button>
            </>
          ) : (
            <div className="text-sm text-slate-500">{clarifyDone ? "澄清完成，可以生成任务。" : "暂无问题"}</div>
          )}
        </CardContent>
      </Card>

      {/* 任务列表 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">任务列表</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {!plan ? (
            <div className="text-sm text-slate-500">加载中...</div>
          ) : plan.tasks.length === 0 ? (
            <div className="text-sm text-slate-500">尚未生成任务</div>
          ) : (
            <div className="space-y-2">
              {plan.tasks.map((t) => (
                <div
                  key={t.id}
                  className="rounded border border-slate-200 dark:border-slate-700 px-3 py-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">{t.name}</div>
                    <Badge variant="secondary">{t.status}</Badge>
                  </div>
                  {t.description && <div className="text-xs text-slate-500 mt-1">{t.description}</div>}
                  {t.acceptanceCriteria && (
                    <div className="text-xs text-slate-500 mt-1 whitespace-pre-wrap">
                      验收：{t.acceptanceCriteria}
                    </div>
                  )}
                  {t.status === "failed" && (
                    <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                      失败任务将在点击「仅重跑未完成/失败的任务」后重试；可查看下方日志中的失败原因与解决方案摘要。
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {hasFailedTasks && (
            <p className="text-xs text-slate-500 mt-2">
              日志中的「已根据失败原因搜索解决方案」或「已根据验收失败原因搜索解决方案」可提供处理建议。
            </p>
          )}
        </CardContent>
      </Card>

      {/* 产物 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">产物</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {!plan ? (
            <div className="text-sm text-slate-500">加载中...</div>
          ) : plan.artifacts.length === 0 ? (
            <div className="text-sm text-slate-500">暂无产物</div>
          ) : (
            <div className="space-y-2">
              {plan.artifacts.map((a) => (
                <div
                  key={a.id}
                  className="rounded border border-slate-200 dark:border-slate-700 px-3 py-2 flex items-center justify-between"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{a.meta?.relpath ? String(a.meta.relpath) : a.id}</div>
                    <div className="text-xs text-slate-500 truncate">{a.filePath}</div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onPreviewArtifact(a.id, a.meta?.relpath ? String(a.meta.relpath) : a.id)}
                  >
                    预览
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 日志 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">日志</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {displayLogs.length === 0 ? (
            <div className="text-sm text-slate-500">暂无日志</div>
          ) : (
            <div className="max-h-80 overflow-y-auto space-y-1 text-xs font-mono">
              {displayLogs.map((l) => (
                <div key={l.id} className="text-slate-600 dark:text-slate-400">
                  [{l.createdAt || ""}] {l.level} {l.event} {l.taskId ? `task=${l.taskId}` : ""}{" "}
                  {Object.keys(l.payload || {}).length ? JSON.stringify(l.payload) : ""}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 产物预览弹层（简单实现） */}
      {artifactPreview && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">预览：{artifactPreview.title}</CardTitle>
            <Button variant="outline" size="sm" onClick={() => setArtifactPreview(null)}>
              关闭预览
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap break-words">{artifactPreview.content}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

