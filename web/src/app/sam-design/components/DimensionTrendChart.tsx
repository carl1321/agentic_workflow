"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useMemo } from "react";
import type { CandidateTrendPoint } from "../utils/molecule";

interface DimensionTrendChartProps {
  /** 每个候选分子的趋势数据（包含维度分数） */
  candidateTrends: CandidateTrendPoint[];
  hasData: boolean;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 维度分数变化趋势图（三个并排子图，每个维度一个）
 */
export function DimensionTrendChart({
  candidateTrends = [],
  hasData,
  executionState,
}: DimensionTrendChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<any>(null);

  // 收集所有迭代轮次（从维度分数和总分趋势中收集）
  const allIters = useMemo(() => {
    const iters = new Set<number>();
    for (const ct of candidateTrends) {
      // 从维度分数趋势中收集
      if (ct.dimensionScoresByIter) {
        for (const iter of ct.dimensionScoresByIter.keys()) {
          iters.add(iter);
        }
      }
      // 从总分趋势中收集（作为后备）
      if (ct.scoresByIter) {
        for (const iter of ct.scoresByIter.keys()) {
          iters.add(iter);
        }
      }
    }
    return Array.from(iters).sort((a, b) => a - b);
  }, [candidateTrends]);

  // 限制显示的候选分子数量（默认前10个）
  const visibleCandidates = useMemo(() => {
    return candidateTrends.slice(0, 10);
  }, [candidateTrends]);

  // 颜色调色板
  const colors = [
    "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444",
    "#06b6d4", "#84cc16", "#f97316", "#a855f7", "#ec4899",
  ];

  useEffect(() => {
    let echarts: any;
    let mounted = true;

    const initChart = async () => {
      if (!mounted || !chartRef.current) return;

      try {
        const echartsModule = await import("echarts");
        echarts = echartsModule.default || echartsModule;

        if (!chartInstanceRef.current) {
          const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches || 
                         document.documentElement.classList.contains("dark");
          chartInstanceRef.current = echarts.init(chartRef.current);
          
          // 监听主题变化
          const observer = new MutationObserver(() => {
            if (chartInstanceRef.current) {
              const isDarkNow = document.documentElement.classList.contains("dark");
              chartInstanceRef.current.dispose();
              chartInstanceRef.current = echarts.init(chartRef.current);
              updateChart(isDarkNow);
            }
          });
          observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class"],
          });
        }

        const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches || 
                      document.documentElement.classList.contains("dark");
        updateChart(isDark);
      } catch (error) {
        console.error("Failed to load echarts:", error);
      }
    };

    const updateChart = (isDark: boolean) => {
      if (!chartInstanceRef.current || !hasData || !candidateTrends || candidateTrends.length === 0) {
        if (chartInstanceRef.current) {
          chartInstanceRef.current.setOption({
            title: {
              text: executionState === "running" 
                ? "等待迭代数据..." 
                : "暂无迭代数据",
              left: "center",
              top: "middle",
              textStyle: {
                color: isDark ? "#94a3b8" : "#64748b",
                fontSize: 14,
              },
            },
          });
        }
        return;
      }

      const dimensions = [
        { name: "表面锚定强度", key: "surfaceAnchoring" as const },
        { name: "化学有效性", key: "chemistryValidity" as const },
        { name: "缺陷评估", key: "defectPassivation" as const },
      ];

      // 为每个维度创建系列数据
      const allSeries: any[] = [];
      // legend 只按“候选分子”展示一次（避免三个子图重复显示同一分子）
      const legendData: string[] = [];
      const legendSet = new Set<string>();
      // 用于 tooltip 分组：seriesIndex -> dimension name
      const seriesDimByIndex: string[] = [];

      dimensions.forEach((dim, dimIdx) => {
        visibleCandidates.forEach((ct, candidateIdx) => {
          const data = allIters.map((iter) => {
            const dimScores = ct.dimensionScoresByIter?.get(iter);
            return dimScores?.[dim.key] ?? null;
          });

          const label = ct.smiles 
            ? `分子 ${ct.moleculeId} (${ct.smiles.substring(0, 15)}...)`
            : `分子 ${ct.moleculeId}`;
          
          // 关键：同一个候选分子在三个维度子图里共享同一个 series name
          // 这样 legend 点击一次即可联动隐藏/显示该候选分子的三条线，同时 legend 不会重复显示。
          const seriesName = label;
          if (!legendSet.has(seriesName)) {
            legendSet.add(seriesName);
            legendData.push(seriesName);
          }

          allSeries.push({
            name: seriesName,
            type: "line",
            data,
            smooth: true,
            xAxisIndex: dimIdx,
            yAxisIndex: dimIdx,
            lineStyle: {
              width: candidateIdx === 0 ? 2.5 : 1.5,
              color: colors[candidateIdx % colors.length],
              opacity: candidateIdx === 0 ? 1 : 0.7,
            },
            itemStyle: {
              color: colors[candidateIdx % colors.length],
              opacity: candidateIdx === 0 ? 1 : 0.7,
            },
            symbol: candidateIdx === 0 ? "circle" : "emptyCircle",
            symbolSize: candidateIdx === 0 ? 6 : 4,
            connectNulls: false, // 缺失值断开连接
          });
          seriesDimByIndex.push(dim.name);
        });
      });

      const option = {
        tooltip: {
          trigger: "axis",
          backgroundColor: isDark ? "rgba(30, 41, 59, 0.95)" : "rgba(255, 255, 255, 0.95)",
          borderColor: isDark ? "rgba(100, 116, 139, 0.3)" : "rgba(0, 0, 0, 0.1)",
          textStyle: {
            color: isDark ? "#e2e8f0" : "#1e293b",
            fontSize: 12,
          },
          formatter: (params: any) => {
            if (!Array.isArray(params)) return "";
            const iter = allIters[params[0].dataIndex];
            let html = `<div style="margin-bottom: 4px;"><strong>迭代 ${iter}</strong></div>`;
            
            // 按维度分组显示
            dimensions.forEach((dim) => {
              const dimParams = params.filter((p: any) => seriesDimByIndex[p.seriesIndex] === dim.name);
              if (dimParams.length > 0) {
                html += `<div style="margin-top: 8px; font-weight: 600; color: ${isDark ? '#cbd5e1' : '#475569'};">
                  ${dim.name}:
                </div>`;
                dimParams.forEach((p: any) => {
                  const value = p.value;
                  if (value !== null && value !== undefined) {
                    html += `<div style="margin-left: 12px; margin-top: 2px;">
                      <span style="display: inline-block; width: 10px; height: 10px; background: ${p.color}; border-radius: 50%; margin-right: 6px;"></span>
                      ${p.seriesName}: <strong>${value.toFixed(1)}</strong>
                    </div>`;
                  }
                });
              }
            });
            
            return html;
          },
        },
        legend: {
          data: legendData,
          bottom: 10,
          type: "scroll",
          textStyle: {
            color: isDark ? "#94a3b8" : "#64748b",
            fontSize: 11,
          },
        },
        grid: dimensions.map((_, idx) => ({
          left: idx === 0 ? "3%" : `${3 + idx * 33}%`,
          right: idx === dimensions.length - 1 ? "4%" : `${4 + (dimensions.length - 1 - idx) * 33}%`,
          top: "10%",
          bottom: candidateTrends.length > 5 ? "25%" : "20%",
          width: "30%",
          containLabel: true,
        })),
        xAxis: dimensions.map((_, idx) => ({
          type: "category",
          gridIndex: idx,
          data: allIters.map((i) => `迭代 ${i}`),
          axisLabel: {
            color: isDark ? "#94a3b8" : "#64748b",
            fontSize: 10,
          },
          axisLine: {
            lineStyle: {
              color: isDark ? "#475569" : "#cbd5e1",
            },
          },
        })),
        yAxis: dimensions.map((dim, idx) => ({
          type: "value",
          name: dim.name,
          gridIndex: idx,
          min: 0,
          max: 10,
          interval: 2,
          nameTextStyle: {
            color: isDark ? "#94a3b8" : "#64748b",
            fontSize: 11,
          },
          axisLabel: {
            color: isDark ? "#94a3b8" : "#64748b",
            fontSize: 10,
          },
          axisLine: {
            lineStyle: {
              color: isDark ? "#475569" : "#cbd5e1",
            },
          },
          splitLine: {
            lineStyle: {
              color: isDark ? "rgba(71, 85, 105, 0.2)" : "rgba(203, 213, 225, 0.5)",
            },
          },
        })),
        series: allSeries,
      };

      chartInstanceRef.current.setOption(option, true);
    };

    initChart();

    return () => {
      mounted = false;
      if (chartInstanceRef.current) {
        chartInstanceRef.current.dispose();
        chartInstanceRef.current = null;
      }
    };
  }, [candidateTrends, hasData, executionState, allIters, visibleCandidates]);

  // 响应式调整
  useEffect(() => {
    const handleResize = () => {
      if (chartInstanceRef.current) {
        chartInstanceRef.current.resize();
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return <div ref={chartRef} className="h-full w-full" />;
}
