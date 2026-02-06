// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Badge } from "~/components/ui/badge";
import { Card, CardContent } from "~/components/ui/card";
import type { PlanDetail } from "~/core/api/plans";

export function PlanTasksTab({ plan }: { plan: PlanDetail | null }) {
  if (!plan) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-4 py-8 text-center text-sm text-slate-500">
        正在加载任务…
      </div>
    );
  }

  if (!plan.tasks || plan.tasks.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-4 py-8 text-center text-sm text-slate-500">
        尚未生成任务（可能正在澄清目标）
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="pt-4 space-y-2">
        {plan.tasks.map((t, i) => (
          <div key={t.id} className="rounded border border-slate-200 dark:border-slate-700 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">
                  {i + 1}. {t.name}
                </div>
                {t.description ? (
                  <div className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{t.description}</div>
                ) : null}
              </div>
              <Badge variant="secondary" className="shrink-0">
                {t.status}
              </Badge>
            </div>
            {t.dependsOn?.length ? (
              <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                依赖：{t.dependsOn.join(", ")}
              </div>
            ) : null}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

