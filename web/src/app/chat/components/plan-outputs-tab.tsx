// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, FileText, Folder, RefreshCw } from "lucide-react";

import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { cn } from "~/lib/utils";
import { getPlanOutputPreview, getPlanOutputDownloadUrl, listPlanOutputs } from "~/core/api/plans";

type OutputItem = {
  relpath: string;
  isDir: boolean;
  size: number;
  mtime: string | null;
};

function isProbablyText(path: string) {
  const p = path.toLowerCase();
  return (
    p.endsWith(".md") ||
    p.endsWith(".txt") ||
    p.endsWith(".json") ||
    p.endsWith(".yaml") ||
    p.endsWith(".yml") ||
    p.endsWith(".csv") ||
    p.endsWith(".log") ||
    p.endsWith(".py") ||
    p.endsWith(".ts") ||
    p.endsWith(".tsx") ||
    p.endsWith(".js") ||
    p.endsWith(".html")
  );
}

export function PlanOutputsTab({ planId }: { planId: string }) {
  const [items, setItems] = useState<OutputItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<OutputItem | null>(null);
  const [preview, setPreview] = useState<{ content: string; truncated: boolean } | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const res = await listPlanOutputs(planId);
      setItems(res.items || []);
    } catch (e) {
      console.error("Failed to load plan outputs:", e);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  const selectedIsText = useMemo(() => (selected ? isProbablyText(selected.relpath) && !selected.isDir : false), [selected]);

  useEffect(() => {
    let cancelled = false;
    async function loadPreview() {
      if (!selected || selected.isDir) {
        setPreview(null);
        return;
      }
      if (!isProbablyText(selected.relpath)) {
        setPreview(null);
        return;
      }
      try {
        const res = await getPlanOutputPreview(planId, selected.relpath);
        if (cancelled) return;
        setPreview({ content: res.content || "", truncated: Boolean(res.truncated) });
      } catch (e) {
        if (!cancelled) console.error("Failed to preview output:", e);
        setPreview(null);
      }
    }
    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [planId, selected]);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">文件列表</CardTitle>
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-1">
          {items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-4 py-8 text-center text-sm text-slate-500">
              暂无产物（任务执行后会自动落盘到 outputs）
            </div>
          ) : (
            <div className="max-h-[520px] overflow-auto pr-1">
              {items.map((it) => (
                <button
                  key={it.relpath}
                  type="button"
                  onClick={() => setSelected(it)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded px-2 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800/60",
                    selected?.relpath === it.relpath && "bg-slate-100 dark:bg-slate-800/60"
                  )}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {it.isDir ? (
                      <Folder className="h-4 w-4 shrink-0 text-slate-500" />
                    ) : (
                      <FileText className="h-4 w-4 shrink-0 text-slate-500" />
                    )}
                    <span className="truncate">{it.relpath}</span>
                  </div>
                  {!it.isDir ? (
                    <span className="shrink-0 text-xs text-slate-400">{Math.round((it.size || 0) / 1024)}KB</span>
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">预览 / 下载</CardTitle>
          {selected && !selected.isDir ? (
            <Button asChild variant="outline" size="sm">
              <a href={getPlanOutputDownloadUrl(planId, selected.relpath)} target="_blank" rel="noreferrer">
                <Download className="h-4 w-4 mr-2" />
                下载
              </a>
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {!selected ? (
            <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-4 py-10 text-center text-sm text-slate-500">
              请选择一个文件以预览或下载
            </div>
          ) : selected.isDir ? (
            <div className="text-sm text-slate-500">这是一个目录：{selected.relpath}</div>
          ) : selectedIsText ? (
            <div className="space-y-2">
              <div className="text-xs text-slate-500">{selected.relpath}</div>
              <pre className="max-h-[520px] overflow-auto rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-3 text-xs text-slate-800 dark:text-slate-200 whitespace-pre-wrap">
                {preview?.content || "（加载中或无内容）"}
              </pre>
              {preview?.truncated ? (
                <div className="text-xs text-slate-500">内容过大，已截断预览。可点击下载查看完整文件。</div>
              ) : null}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs text-slate-500">{selected.relpath}</div>
              <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 px-4 py-10 text-center text-sm text-slate-500">
                暂不支持该类型在线预览，请点击右上角下载
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

