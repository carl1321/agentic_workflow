"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { extractIterationAnalytics } from "../utils/molecule";
import type { Molecule } from "../types";
import { ScoreTrendChart } from "./ScoreTrendChart";
import { ParetoScatterChart } from "./ParetoScatterChart";

interface IterationAnalyticsPanelProps {
  nodeOutputs: Record<string, any>;
  molecules: Molecule[];
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>;
  iterationNodeOutputs?: Map<number, Record<string, any>>;
  workflowGraph?: { nodes: any[]; edges: any[] } | null;
  executionState: "idle" | "running" | "completed" | "failed";
}

/**
 * 迭代分析面板（中列下方：趋势图 + Pareto 散点图）
 */
export function IterationAnalyticsPanel({
  nodeOutputs,
  molecules,
  iterationSnapshots = [],
  iterationNodeOutputs = new Map(),
  workflowGraph,
  executionState,
}: IterationAnalyticsPanelProps) {
  const [analytics, setAnalytics] = useState(extractIterationAnalytics(nodeOutputs, molecules, iterationSnapshots, iterationNodeOutputs, workflowGraph));

  // 当 nodeOutputs、molecules 或 iterationSnapshots 更新时，重新提取分析数据
  useEffect(() => {
    const newAnalytics = extractIterationAnalytics(nodeOutputs, molecules, iterationSnapshots, iterationNodeOutputs, workflowGraph);
    setAnalytics(newAnalytics);
  }, [nodeOutputs, molecules, iterationSnapshots, iterationNodeOutputs, workflowGraph]);

  return (
    <div className="flex h-full flex-col bg-white dark:bg-slate-900">
      <div className="border-b border-slate-200 px-4 py-2 dark:border-slate-700">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">迭代分析</h3>
      </div>
      <div className="flex-1 overflow-hidden">
        <Tabs defaultValue="trend" className="h-full flex flex-col">
          <TabsList className="mx-4 mt-2">
            <TabsTrigger value="trend">总分趋势</TabsTrigger>
            <TabsTrigger value="pareto">总分散点</TabsTrigger>
          </TabsList>
          <TabsContent value="trend" className="flex-1 overflow-hidden mt-0">
            <ScoreTrendChart
              candidateTrends={analytics.candidateTrends}
              hasData={analytics.hasData}
              executionState={executionState}
            />
          </TabsContent>
          <TabsContent value="pareto" className="flex-1 overflow-hidden mt-0">
            <ParetoScatterChart
              paretoPoints={analytics.paretoPoints}
              hasData={analytics.hasData}
              executionState={executionState}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
