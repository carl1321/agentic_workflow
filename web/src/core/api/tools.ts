// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { resolveServiceURL } from "./resolve-service-url";
import { useAuthStore } from "../store/auth-store";

export interface ToolExecuteRequest {
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ToolExecuteResponse {
  result: string;
  error?: string;
}

/**
 * 执行工具调用
 * 使用独立的工具执行API端点，不经过对话流程
 */
export async function executeTool(
  toolName: string,
  args: Record<string, unknown>
): Promise<string> {
  try {
    const token = useAuthStore.getState().token;
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const response = await fetch(resolveServiceURL("tools/execute"), {
      method: "POST",
      headers,
      body: JSON.stringify({ tool_name: toolName, arguments: args }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`工具执行失败: ${response.statusText} - ${errorText}`);
    }

    const data: ToolExecuteResponse = await response.json();
    
    if (data.error) {
      throw new Error(data.error);
    }

    return data.result || "工具执行完成";
  } catch (error) {
    throw new Error(
      `工具执行失败: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

