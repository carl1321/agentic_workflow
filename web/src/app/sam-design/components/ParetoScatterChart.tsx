"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef } from "react";
import type { ParetoDataPoint } from "../utils/molecule";

interface ParetoScatterChartProps {
  paretoPoints: ParetoDataPoint[];
  hasData: boolean;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 总分散点图（x=迭代轮次, y=总分，点大小/颜色=总分）
 */
export function ParetoScatterChart({
  paretoPoints,
  hasData,
  executionState,
}: ParetoScatterChartProps) {
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
      if (!chartInstanceRef.current || !hasData || paretoPoints.length === 0) {
        if (chartInstanceRef.current) {
          chartInstanceRef.current.setOption({
            title: {
              text: executionState === "running" 
                ? "等待数据..." 
                : "暂无数据",
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

      const points = paretoPoints.filter((p) => typeof p.iter === "number");
      const iters = Array.from(new Set(points.map((p) => p.iter as number))).sort((a, b) => a - b);

      const totals = points.map((p) => p.total || 0);
      const minTotal = Math.min(...totals);
      const maxTotal = Math.max(...totals);
      const totalRange = maxTotal - minTotal || 1;

      const option = {
        tooltip: {
          trigger: "item",
          formatter: (params: any) => {
            const point = points[params.dataIndex];
            return `
              <div>
                <div>总分: ${point.total.toFixed(1)}</div>
                ${point.iter ? `<div>迭代: ${point.iter}</div>` : ""}
                ${point.moleculeId !== undefined ? `<div>分子ID: ${point.moleculeId}</div>` : ""}
                ${point.smiles ? `<div style="max-width:360px;word-break:break-all;">SMILES: ${point.smiles}</div>` : ""}
              </div>
            `;
          },
          backgroundColor: isDark ? "rgba(30, 41, 59, 0.95)" : "rgba(255, 255, 255, 0.95)",
          borderColor: isDark ? "rgba(100, 116, 139, 0.3)" : "rgba(0, 0, 0, 0.1)",
          textStyle: {
            color: isDark ? "#e2e8f0" : "#1e293b",
          },
        },
        grid: {
          left: "10%",
          right: "10%",
          bottom: "10%",
          top: "10%",
          containLabel: true,
        },
        xAxis: {
          type: "category",
          name: "迭代",
          nameLocation: "middle",
          nameGap: 30,
          nameTextStyle: {
            color: isDark ? "#94a3b8" : "#64748b",
          },
          axisLabel: {
            color: isDark ? "#94a3b8" : "#64748b",
          },
          data: iters.map((i) => `迭代 ${i}`),
        },
        yAxis: {
          type: "value",
          name: "总分",
          nameLocation: "middle",
          nameGap: 50,
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
        visualMap: {
          min: minTotal,
          max: maxTotal,
          dimension: 1, // total
          inRange: {
            color: ["#3b82f6", "#10b981", "#f59e0b"],
          },
          calculable: true,
          right: 10,
          top: "middle",
          textStyle: {
            color: isDark ? "#94a3b8" : "#64748b",
          },
        },
        series: [
          {
            name: "候选分子",
            type: "scatter",
            // xAxis 是 category，用索引定位；y 是 total
            data: points.map((p) => [iters.indexOf(p.iter as number), p.total]),
            symbolSize: (data: number[]) => {
              // 点大小基于总分，范围 8-24
              const total = data[1];
              const normalized = (total - minTotal) / totalRange;
              return 10 + normalized * 20;
            },
            itemStyle: {
              opacity: 0.7,
            },
          },
        ],
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
  }, [paretoPoints, hasData, executionState]);

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
