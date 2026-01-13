// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { apiRequest } from "./api-client";
import type { DesignHistory, DesignObjective, Constraint, ExecutionResult, Molecule } from "~/app/sam-design/types";

/**
 * 保存设计历史记录
 */
export async function saveDesignHistory(
  name: string | undefined,
  objective: DesignObjective,
  constraints: Constraint[],
  executionResult: ExecutionResult,
  molecules: Molecule[],
): Promise<{ success: boolean; id: string }> {
  return apiRequest<{ success: boolean; id: string }>("sam-design/history", {
    method: "POST",
    body: JSON.stringify({
      name,
      objective,
      constraints,
      executionResult,
      molecules,
    }),
  });
}

/**
 * 获取设计历史记录列表
 */
export async function getDesignHistoryList(
  limit: number = 100,
  offset: number = 0,
): Promise<{ success: boolean; history: Array<{ id: string; name: string; createdAt: string; moleculeCount: number }> }> {
  return apiRequest<{ success: boolean; history: Array<{ id: string; name: string; createdAt: string; moleculeCount: number }> }>(
    `sam-design/history?limit=${limit}&offset=${offset}`
  );
}

/**
 * 获取单个设计历史记录
 */
export async function getDesignHistory(historyId: string): Promise<{ success: boolean; history: DesignHistory }> {
  return apiRequest<{ success: boolean; history: DesignHistory }>(`sam-design/history/${historyId}`);
}

/**
 * 删除设计历史记录
 */
export async function deleteDesignHistory(historyId: string): Promise<{ success: boolean }> {
  return apiRequest<{ success: boolean }>(`sam-design/history/${historyId}`, {
    method: "DELETE",
  });
}

