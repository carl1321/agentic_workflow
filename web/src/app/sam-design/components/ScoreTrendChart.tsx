"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef } from "react";
import type { CandidateTrendPoint } from "../utils/molecule";

interface ScoreTrendChartProps {
  /** 每个候选分子的总分趋势数据 */
  candidateTrends: CandidateTrendPoint[];
  hasData: boolean;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 总分趋势折线图（每个候选分子一条线）
 */
export function ScoreTrendChart({
  candidateTrends = [],
  hasData,
  executionState,
}: ScoreTrendChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<any>(null);

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

      // 收集所有迭代轮次
      const allIters = new Set<number>();
      for (const ct of candidateTrends) {
        for (const iter of ct.scoresByIter.keys()) {
          allIters.add(iter);
        }
      }
      const iters = Array.from(allIters).sort((a, b) => a - b);

      // 为每个候选分子创建一条趋势线
      const colors = [
        "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444",
        "#06b6d4", "#84cc16", "#f97316", "#a855f7", "#ec4899",
      ];
      
      const series = candidateTrends.slice(0, 20).map((ct, idx) => {
        const data = iters.map((iter) => ct.scoresByIter.get(iter) || null);
        const label = ct.smiles 
          ? `分子 ${ct.moleculeId} (${ct.smiles.substring(0, 20)}...)`
          : `分子 ${ct.moleculeId}`;
        
        return {
          name: label,
          type: "line",
          data,
          smooth: true,
          lineStyle: {
            width: idx === 0 ? 2.5 : 1.5,
            color: colors[idx % colors.length],
            opacity: idx === 0 ? 1 : 0.7,
          },
          itemStyle: {
            color: colors[idx % colors.length],
            opacity: idx === 0 ? 1 : 0.7,
          },
          symbol: idx === 0 ? "circle" : "emptyCircle",
          symbolSize: idx === 0 ? 6 : 4,
        };
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
        },
        legend: {
          data: series.map((s) => s.name),
          bottom: 10,
          type: "scroll",
          textStyle: {
            color: isDark ? "#94a3b8" : "#64748b",
            fontSize: 11,
          },
        },
        grid: {
          left: "3%",
          right: "4%",
          bottom: candidateTrends.length > 5 ? "20%" : "15%",
          top: "10%",
          containLabel: true,
        },
        xAxis: {
          type: "category",
          data: iters.map((i) => `迭代 ${i}`),
          axisLabel: {
            color: isDark ? "#94a3b8" : "#64748b",
          },
        },
        yAxis: {
          type: "value",
          name: "总分",
          min: 0,
          max: 10,
          interval: 1,
          nameTextStyle: {
            color: isDark ? "#94a3b8" : "#64748b",
          },
          axisLabel: {
            color: isDark ? "#94a3b8" : "#64748b",
          },
        },
        series,
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
  }, [candidateTrends, hasData, executionState]);

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
