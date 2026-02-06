// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Textarea } from "~/components/ui/textarea";
import { Badge } from "~/components/ui/badge";
import { createPlan, listPlans, type PlanSummary } from "~/core/api/plans";

export default function PlansPage() {
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [title, setTitle] = useState("");
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listPlans();
      setPlans(res.plans || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const onCreate = async () => {
    const g = goal.trim();
    if (!g) return;
    setCreating(true);
    setError(null);
    try {
      const res = await createPlan(g, title.trim() || undefined);
      router.push(`/plans/${res.planId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="container mx-auto max-w-5xl p-6 space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>长期计划（MVP）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 gap-3">
            <Input
              placeholder="（可选）计划标题，例如：修仙动画账号冷启动"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Textarea
              placeholder="输入你的目标（可以很模糊），例如：做一个修仙动画账号，每天发1条，想要涨粉"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={4}
            />
            <div className="flex gap-2">
              <Button onClick={onCreate} disabled={creating || goal.trim().length === 0}>
                {creating ? "创建中..." : "创建计划"}
              </Button>
              <Button variant="outline" onClick={refresh} disabled={loading}>
                刷新列表
              </Button>
              {error && <div className="text-sm text-red-600">{error}</div>}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>计划列表</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <div className="text-sm text-slate-500">加载中...</div>
          ) : plans.length === 0 ? (
            <div className="text-sm text-slate-500">暂无计划</div>
          ) : (
            <div className="space-y-2">
              {plans.map((p) => (
                <button
                  key={p.id}
                  className="w-full text-left rounded border border-slate-200 dark:border-slate-700 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800"
                  onClick={() => router.push(`/plans/${p.id}`)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">
                        {p.title || p.id}
                      </div>
                      <div className="text-xs text-slate-500 truncate">
                        {p.updatedAt ? `更新：${p.updatedAt}` : ""}
                      </div>
                    </div>
                    <Badge variant="secondary">{p.status}</Badge>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

