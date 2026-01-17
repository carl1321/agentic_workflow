// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { apiRequest } from "./api-client";
import type { DesignObjective, Constraint, Molecule } from "~/app/sam-design/types";

/**
 * 执行历史记录接口
 */
export interface ExecutionHistory {
  id: string;
  runId: string;
  workflowId: string;
  name: string;
  objective: DesignObjective;
  constraints: Constraint[];
  executionState: "idle" | "running" | "completed" | "failed";
  startedAt?: string;
  finishedAt?: string;
  executionLogs?: string[];
  nodeOutputs?: Record<string, any>;
  iterationNodeOutputs?: Record<string, Record<string, any>>; // Map<iter, Record<nodeId, outputs>> 序列化为对象
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>;
  workflowGraph?: { nodes: any[]; edges: any[] };
  iterationAnalytics?: {
    trend: Array<{
      iter: number;
      total_best: number;
      surfaceAnchoring_best: number;
      energyLevel_best: number;
      packingDensity_best: number;
    }>;
    paretoPoints: Array<{
      energyLevel: number;
      surfaceAnchoring: number;
      packingDensity: number;
      total: number;
      iter?: number;
      smiles?: string;
      moleculeId?: number | string;
    }>;
    candidateTrends: Array<{
      moleculeId: number | string;
      smiles?: string;
      scoresByIter: Record<number, number>; // Map序列化为对象
    }>;
    hasData: boolean;
  };
  candidateMolecules?: Molecule[];
  createdAt?: string;
  updatedAt?: string;
}

/**
 * 执行历史记录列表项
 */
export interface ExecutionHistoryListItem {
  id: string;
  runId: string;
  workflowId: string;
  name: string;
  executionState: "idle" | "running" | "completed" | "failed";
  startedAt?: string;
  finishedAt?: string;
  createdAt?: string;
  moleculeCount: number;
}

/**
 * 保存执行历史记录
 */
export async function saveExecutionHistory(
  runId: string,
  workflowId: string,
  name: string | undefined,
  objective: DesignObjective,
  constraints: Constraint[],
  executionState: "idle" | "running" | "completed" | "failed",
  startedAt?: string,
  finishedAt?: string,
  executionLogs?: string[],
  nodeOutputs?: Record<string, any>,
  iterationNodeOutputs?: Map<number, Record<string, any>>,
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>,
  workflowGraph?: { nodes: any[]; edges: any[] } | null,
  iterationAnalytics?: {
    trend: Array<{
      iter: number;
      total_best: number;
      surfaceAnchoring_best: number;
      energyLevel_best: number;
      packingDensity_best: number;
    }>;
    paretoPoints: Array<{
      energyLevel: number;
      surfaceAnchoring: number;
      packingDensity: number;
      total: number;
      iter?: number;
      smiles?: string;
      moleculeId?: number | string;
    }>;
    candidateTrends: Array<{
      moleculeId: number | string;
      smiles?: string;
      scoresByIter: Map<number, number>;
    }>;
    hasData: boolean;
  },
  candidateMolecules?: Molecule[],
): Promise<{ success: boolean; id: string }> {
  // 将 Map 转换为对象
  const iterationNodeOutputsObj: Record<string, Record<string, any>> = {};
  if (iterationNodeOutputs) {
    for (const [iter, outputs] of iterationNodeOutputs.entries()) {
      iterationNodeOutputsObj[String(iter)] = outputs;
    }
  }

  // 将 candidateTrends 中的 Map 转换为对象
  let iterationAnalyticsObj = iterationAnalytics;
  if (iterationAnalytics?.candidateTrends) {
    iterationAnalyticsObj = {
      ...iterationAnalytics,
      candidateTrends: iterationAnalytics.candidateTrends.map((ct) => ({
        ...ct,
        scoresByIter: Object.fromEntries(ct.scoresByIter.entries()),
      })),
    };
  }

  return apiRequest<{ success: boolean; id: string }>("new-sam/save-execution-history", {
    method: "POST",
    body: JSON.stringify({
      runId,
      workflowId,
      name,
      objective,
      constraints,
      executionState,
      startedAt,
      finishedAt,
      executionLogs,
      nodeOutputs,
      iterationNodeOutputs: iterationNodeOutputsObj,
      iterationSnapshots,
      workflowGraph,
      iterationAnalytics: iterationAnalyticsObj,
      candidateMolecules,
    }),
  });
}

/**
 * 获取执行历史记录列表
 */
export async function listExecutionHistory(
  limit: number = 100,
  offset: number = 0,
): Promise<{ success: boolean; history: ExecutionHistoryListItem[] }> {
  return apiRequest<{ success: boolean; history: ExecutionHistoryListItem[] }>(
    `new-sam/execution-history?limit=${limit}&offset=${offset}`
  );
}

/**
 * 获取单个执行历史记录详情
 */
export async function getExecutionHistory(historyId: string): Promise<{ success: boolean; history: ExecutionHistory }> {
  return apiRequest<{ success: boolean; history: ExecutionHistory }>(`new-sam/execution-history/${historyId}`);
}

/**
 * 删除执行历史记录
 */
export async function deleteExecutionHistory(historyId: string): Promise<{ success: boolean }> {
  return apiRequest<{ success: boolean }>(`new-sam/execution-history/${historyId}`, {
    method: "DELETE",
  });
}
