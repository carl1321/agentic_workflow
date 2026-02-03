"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * 3D 分子结构查看器：基于 3Dmol.js（CDN），支持旋转、缩放、平移。
 * 支持两种数据源：smiles（点击时按需调用后端生成 SDF）或 sdfUrl（从 URL 拉取 SDF）。
 */

import { useEffect, useRef, useState } from "react";
import Script from "next/script";
import { generate3DSdf } from "~/core/api/new-sam";

const CDN_3DMOL = "https://3Dmol.org/build/3Dmol-min.js";

/** 容器最小宽高（px），低于此值视为未完成布局，不创建 viewer */
const MIN_CONTAINER_SIZE = 10;
/** 等待容器尺寸的最长时间（ms），超时则报错 */
const SIZE_WAIT_TIMEOUT_MS = 5000;

declare global {
  interface Window {
    $3Dmol?: {
      createViewer: (element: HTMLElement, options?: Record<string, unknown>) => {
        addModel: (data: string, format: string) => void;
        setStyle: (selection: Record<string, unknown>, style: Record<string, unknown>) => void;
        zoomTo: () => void;
        render: () => void;
        clear: () => void;
        resize: () => void;
      };
    };
  }
}

export interface Molecule3DViewerProps {
  /** 3D SDF 文件 URL（可选，与 smiles 二选一） */
  sdfUrl?: string;
  /** SMILES 字符串，点击「3D 结构」时按需生成 SDF（与 sdfUrl 二选一，优先使用） */
  smiles?: string;
  /** 多分子 SDF 中要显示的分子索引，默认 0 */
  modelIndex?: number;
  /** 容器宽度，默认 100% */
  width?: string | number;
  /** 容器高度，默认 320 */
  height?: string | number;
  /** 背景色，默认透明 */
  backgroundColor?: string;
  onLoad?: () => void;
  onError?: (err: Error) => void;
}

export function Molecule3DViewer({
  sdfUrl,
  smiles,
  modelIndex = 0,
  width = "100%",
  height = 320,
  backgroundColor = "white",
  onLoad,
  onError,
}: Molecule3DViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<ReturnType<NonNullable<typeof window.$3Dmol>["createViewer"]> | null>(null);
  const [scriptReady, setScriptReady] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // 若脚本已加载（例如再次打开弹窗时），直接标记就绪
  useEffect(() => {
    if (typeof window !== "undefined" && window.$3Dmol?.createViewer) {
      setScriptReady(true);
    }
  }, []);

  useEffect(() => {
    const hasInput = (smiles?.trim() ?? "") !== "" || (sdfUrl?.trim() ?? "") !== "";
    if (!hasInput || !containerRef.current || !scriptReady) return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let timeoutId2: ReturnType<typeof setTimeout> | null = null;
    let resizeObserver: ResizeObserver | null = null;
    const sizeWaitCleanup = {
      resizeObserver: null as ResizeObserver | null,
      timeoutId: null as ReturnType<typeof setTimeout> | null,
      pollIntervalId: null as ReturnType<typeof setInterval> | null,
    };
    setStatus("loading");
    setErrorMessage(null);

    const initViewer = async () => {
      try {
        const $3Dmol = typeof window !== "undefined" ? window.$3Dmol : undefined;
        const createViewer = $3Dmol?.createViewer;
        if (typeof createViewer !== "function") {
          throw new Error("3Dmol 尚未加载完成，请稍候再试");
        }

        if (cancelled || !containerRef.current) return;

        let sdfText: string;
        if (smiles?.trim()) {
          const resp = await generate3DSdf(smiles.trim());
          // 注意：不要 trim() 掉开头空行。Mol/SDF 头部通常需要 3 行 header，
          // 用户侧常见返回是以 '\n' 开头（空行 + RDKit header + 空行 + counts line）。
          // 若 trim() 去掉开头空行，会导致 counts line 行号偏移，3Dmol 解析可能静默失败并显示空白。
          if (!resp?.sdf || resp.sdf.trim().length === 0) throw new Error("后端未能生成 3D 结构");
          sdfText = resp.sdf.trimEnd();
        } else if (sdfUrl?.trim()) {
          const base = typeof window !== "undefined" ? window.location.origin : "";
          const url = sdfUrl.startsWith("http") ? sdfUrl : `${base}${sdfUrl}`;
          const res = await fetch(url);
          if (!res.ok) throw new Error(`加载 3D 结构失败: ${res.status}，请确认已生成 3D 结构`);
          const raw = await res.text();
          if (raw.trim().length === 0) throw new Error("3D 结构内容为空");
          sdfText = raw.trimEnd();
        } else {
          throw new Error("请提供 smiles 或 sdfUrl");
        }
        if (cancelled) return;
        if (sdfText.trim().length === 0) throw new Error("3D 结构内容为空");

        // 3Dmol 需要容器有明确尺寸（见官方文档）
        const el = containerRef.current;
        const heightPx = typeof height === "number" ? `${height}px` : height;
        el.style.width = typeof width === "number" ? `${width}px` : String(width);
        el.style.height = heightPx;
        el.style.minHeight = heightPx;

        // 等待容器有有效尺寸再创建 viewer，避免在 0×0 下创建 WebGL 画布导致不显示
        await new Promise<void>((resolve, reject) => {
          const done = (success: boolean) => {
            sizeWaitCleanup.resizeObserver?.disconnect();
            sizeWaitCleanup.resizeObserver = null;
            if (sizeWaitCleanup.timeoutId) clearTimeout(sizeWaitCleanup.timeoutId);
            sizeWaitCleanup.timeoutId = null;
            if (sizeWaitCleanup.pollIntervalId) clearInterval(sizeWaitCleanup.pollIntervalId);
            sizeWaitCleanup.pollIntervalId = null;
            if (success) resolve();
            else reject(new Error("无法获取显示区域尺寸"));
          };
          const check = () => {
            const rect = el.getBoundingClientRect();
            return rect.width >= MIN_CONTAINER_SIZE && rect.height >= MIN_CONTAINER_SIZE;
          };
          if (check()) {
            done(true);
            return;
          }

          if (typeof ResizeObserver !== "undefined") {
            sizeWaitCleanup.resizeObserver = new ResizeObserver(() => {
              if (cancelled) return;
              if (check()) done(true);
            });
            sizeWaitCleanup.resizeObserver.observe(el);
          } else {
            sizeWaitCleanup.pollIntervalId = setInterval(() => {
              if (cancelled) return;
              if (check()) done(true);
            }, 50);
            sizeWaitCleanup.timeoutId = setTimeout(() => {
              if (!cancelled) done(false);
            }, SIZE_WAIT_TIMEOUT_MS);
            return;
          }
          sizeWaitCleanup.timeoutId = setTimeout(() => {
            if (cancelled) return;
            done(false);
          }, SIZE_WAIT_TIMEOUT_MS);
        });
        if (cancelled) return;

        const viewer = createViewer(el, {
          backgroundColor,
        }) as {
          addModel: (data: string, format: string) => void;
          setStyle: (sel: Record<string, unknown>, style: Record<string, unknown>) => void;
          zoomTo: () => void;
          render: () => void;
          clear: () => void;
          resize: () => void;
        };
        viewerRef.current = viewer;

        viewer.addModel(sdfText, "sdf");
        viewer.setStyle({}, { stick: {}, sphere: { scale: 0.3 } });
        viewer.zoomTo();
        viewer.render();

        if (cancelled) return;

        // 弹窗展开后可能仍有布局抖动，延迟调用 resize 再 zoomTo/render
        const doResizeAndRender = () => {
          if (!viewerRef.current || !containerRef.current) return;
          try {
            viewerRef.current.resize();
            viewerRef.current.zoomTo();
            viewerRef.current.render();
          } catch {
            // ignore
          }
        };
        timeoutId = setTimeout(() => {
          if (!cancelled) doResizeAndRender();
        }, 200);
        timeoutId2 = setTimeout(() => {
          if (!cancelled) doResizeAndRender();
        }, 500);

        if (typeof ResizeObserver !== "undefined" && el) {
          resizeObserver = new ResizeObserver(() => {
            if (!cancelled) doResizeAndRender();
          });
          resizeObserver.observe(el);
        }

        setStatus("ready");
        onLoad?.();
      } catch (e) {
        const err = e instanceof Error ? e : new Error(String(e));
        if (!cancelled) {
          setStatus("error");
          setErrorMessage(err.message);
          onError?.(err);
        }
      }
    };

    initViewer();
    return () => {
      cancelled = true;
      sizeWaitCleanup.resizeObserver?.disconnect();
      sizeWaitCleanup.resizeObserver = null;
      if (sizeWaitCleanup.timeoutId) clearTimeout(sizeWaitCleanup.timeoutId);
      sizeWaitCleanup.timeoutId = null;
      if (sizeWaitCleanup.pollIntervalId) clearInterval(sizeWaitCleanup.pollIntervalId);
      sizeWaitCleanup.pollIntervalId = null;
      if (timeoutId) clearTimeout(timeoutId);
      if (timeoutId2) clearTimeout(timeoutId2);
      resizeObserver?.disconnect();
      resizeObserver = null;
      if (viewerRef.current) {
        try {
          viewerRef.current.clear();
        } catch {
          // ignore
        }
        viewerRef.current = null;
      }
    };
  }, [sdfUrl, smiles, modelIndex, backgroundColor, scriptReady, width, height, onLoad, onError]);

  const heightPx = typeof height === "number" ? `${height}px` : height;
  const widthStyle = typeof width === "number" ? `${width}px` : width;

  return (
    <>
      <Script
        src={CDN_3DMOL}
        strategy="lazyOnload"
        onLoad={() => setScriptReady(true)}
      />
      <div className="relative rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50 overflow-hidden" style={{ width: widthStyle, height: heightPx, minHeight: heightPx }}>
        <div ref={containerRef} className="absolute inset-0 w-full h-full" style={{ width: "100%", height: "100%" }} />
        {status === "loading" && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-100/80 dark:bg-slate-800/80">
            <span className="text-sm text-slate-500">加载 3D 结构中…</span>
          </div>
        )}
        {status === "error" && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-100/80 dark:bg-slate-800/80 p-4">
            <span className="text-sm text-red-600 dark:text-red-400">{errorMessage ?? "加载失败"}</span>
          </div>
        )}
        {status === "ready" && (
          <div className="absolute bottom-2 left-2 text-xs text-slate-500 dark:text-slate-400">
            拖拽旋转 · 滚轮缩放
          </div>
        )}
      </div>
    </>
  );
}
