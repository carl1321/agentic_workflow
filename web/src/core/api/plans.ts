// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { apiRequest } from "./api-client";
import { fetchStream } from "../sse";
import { resolveServiceURL } from "./resolve-service-url";
import { useAuthStore } from "../store/auth-store";

export type PlanStatus =
  | "draft"
  | "active"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "terminated";
export type TaskStatus =
  | "pending"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "canceled";

export interface PlanSummary {
  id: string;
  title?: string | null;
  status: PlanStatus;
  createdAt?: string;
  updatedAt?: string;
}

export interface TaskItem {
  id: string;
  planId: string;
  name: string;
  description?: string | null;
  acceptanceCriteria?: string | null;
  status: TaskStatus;
  dependsOn: string[];
  scheduledAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  executorType: "llm" | "tool" | "file";
  executorArgs: Record<string, unknown>;
  idempotencyKey?: string | null;
}

export interface ArtifactItem {
  id: string;
  planId: string;
  taskId: string;
  type: string;
  filePath: string;
  meta?: Record<string, unknown>;
  createdAt?: string;
}

export interface PlanDetail {
  id: string;
  title?: string | null;
  status: PlanStatus;
  rawGoal?: string | null;
  oraSpec?: Record<string, unknown> | null;
  clarify?: Record<string, unknown> | null;
  specVersion?: number;
  createdAt?: string;
  updatedAt?: string;
  tasks: TaskItem[];
  artifacts: ArtifactItem[];
}

export interface PlanLogItem {
  id: string;
  planId: string;
  taskId?: string | null;
  level: string;
  event: string;
  payload: Record<string, unknown>;
  createdAt?: string;
}

export type PlanMessageRole = "user" | "assistant" | "system";
export interface PlanMessageItem {
  id: string;
  planId: string;
  role: PlanMessageRole;
  content: string;
  meta?: Record<string, unknown>;
  createdAt?: string;
}

export async function createPlan(goal: string, title?: string) {
  return apiRequest<{ success: boolean; planId: string }>("plans", {
    method: "POST",
    body: JSON.stringify({ goal, title }),
  });
}

export async function listPlans(limit = 50, offset = 0) {
  return apiRequest<{ success: boolean; plans: PlanSummary[] }>(`plans?limit=${limit}&offset=${offset}`);
}

export async function getPlan(planId: string) {
  return apiRequest<{ success: boolean; plan: PlanDetail }>(`plans/${planId}`);
}

export async function deletePlan(planId: string) {
  return apiRequest<unknown>(`plans/${planId}`, { method: "DELETE" });
}

export async function listPlanOutputs(planId: string) {
  return apiRequest<{ success: boolean; items: Array<{ relpath: string; isDir: boolean; size: number; mtime?: string | null }> }>(
    `plans/${planId}/outputs`
  );
}

export async function getPlanOutputPreview(planId: string, path: string) {
  return apiRequest<{ success: boolean; path: string; content: string; truncated: boolean }>(
    `plans/${planId}/outputs/preview?path=${encodeURIComponent(path)}`
  );
}

export function getPlanOutputDownloadUrl(planId: string, path: string) {
  return resolveServiceURL(`plans/${planId}/outputs/download?path=${encodeURIComponent(path)}`);
}

export async function getClarify(planId: string) {
  return apiRequest<{ success: boolean; round: number; question?: string | null; done: boolean; oraDraft?: any }>(
    `plans/${planId}/clarify`
  );
}

export async function answerClarify(planId: string, answer: string) {
  return apiRequest<{ success: boolean; round: number; question?: string | null; done: boolean; oraDraft?: any }>(
    `plans/${planId}/clarify`,
    {
      method: "POST",
      body: JSON.stringify({ answer }),
    }
  );
}

export async function finalizePlan(planId: string, model?: string) {
  return apiRequest<{ success: boolean; planId: string; tasksCreated: number }>(`plans/${planId}/finalize`, {
    method: "POST",
    body: JSON.stringify({ model }),
  });
}

export async function runPlan(planId: string) {
  return apiRequest<{ success: boolean; planId: string; status: PlanStatus }>(`plans/${planId}/run`, {
    method: "POST",
    body: JSON.stringify({ dryRun: false }),
  });
}

export async function listPlanLogs(planId: string, limit = 200, offset = 0) {
  return apiRequest<{ success: boolean; logs: PlanLogItem[] }>(
    `plans/${planId}/logs?limit=${limit}&offset=${offset}`
  );
}

export async function getArtifactContent(planId: string, artifactId: string) {
  return apiRequest<{ success: boolean; filePath: string; content: string; truncated: boolean }>(
    `plans/${planId}/artifacts/${artifactId}/content`
  );
}

export async function listPlanMessages(planId: string, limit = 200, offset = 0) {
  return apiRequest<{ success: boolean; messages: PlanMessageItem[] }>(
    `plans/${planId}/messages?limit=${limit}&offset=${offset}`
  );
}

export async function sendPlanMessage(planId: string, content: string) {
  return apiRequest<{ success: boolean; messages: PlanMessageItem[] }>(`plans/${planId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export type PlanEvent =
  | { type: "message"; data: PlanMessageItem }
  | { type: "log"; data: PlanLogItem }
  | { type: "error"; data: any }
  | { type: string; data: any };

export async function* streamPlanEvents(
  planId: string,
  options: { since?: string; abortSignal?: AbortSignal } = {}
): AsyncIterable<PlanEvent> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    "Cache-Control": "no-cache",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const qs = options.since ? `?since=${encodeURIComponent(options.since)}` : "";
  const url = resolveServiceURL(`plans/${planId}/events${qs}`);

  const stream = fetchStream(url, {
    method: "GET",
    headers,
    signal: options.abortSignal,
  });

  for await (const event of stream) {
    if (!event?.data) continue;
    try {
      const data = JSON.parse(event.data);
      yield { type: event.event, data } as PlanEvent;
    } catch (e) {
      yield { type: "error", data: { error: String(e), raw: event.data } };
    }
  }
}

