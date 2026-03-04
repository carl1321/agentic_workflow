/**
 * 工具箱运行历史 API（文生图、PPT 生成等）
 */

import { resolveServiceURL } from "./resolve-service-url";

export interface ToolRunHistoryRecord {
  id: string;
  tool_id: string;
  params_json: Record<string, unknown> | null;
  result_json: string | null;
  created_at: string | null;
}

export interface ToolRunHistoryListResponse {
  records: ToolRunHistoryRecord[];
}

export async function saveToolRunHistory(
  toolId: string,
  params: Record<string, unknown>,
  result: string | object
): Promise<ToolRunHistoryRecord> {
  const response = await fetch(resolveServiceURL("tool-history"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tool_id: toolId,
      params,
      result: typeof result === "string" ? result : JSON.stringify(result),
    }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to save tool run");
  }
  return response.json();
}

export async function getToolRunHistoryList(
  toolId: string,
  limit: number = 50,
  offset: number = 0
): Promise<ToolRunHistoryListResponse> {
  const params = new URLSearchParams({
    tool_id: toolId,
    limit: String(limit),
    offset: String(offset),
  });
  const response = await fetch(`${resolveServiceURL("tool-history")}?${params.toString()}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to list tool runs");
  }
  return response.json();
}

export async function getToolRunRecord(recordId: string): Promise<ToolRunHistoryRecord> {
  const response = await fetch(resolveServiceURL(`tool-history/${recordId}`), {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to get tool run");
  }
  return response.json();
}

export async function deleteToolRunRecord(recordId: string): Promise<void> {
  const response = await fetch(resolveServiceURL(`tool-history/${recordId}`), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to delete tool run");
  }
}
