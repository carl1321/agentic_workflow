// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { resolveServiceURL } from "./resolve-service-url";
import { useAuthStore } from "../store/auth-store";

/**
 * 处理 401 未授权错误，清除 token 并跳转到登录页面
 */
function handleUnauthorized() {
  // 清除 token 和用户信息
  useAuthStore.getState().logout();
  
  // 跳转到登录页面（保留当前路径作为 redirect 参数）
  if (typeof window !== "undefined") {
    const currentPath = window.location.pathname;
    window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`;
  }
}

/**
 * 统一的 API 请求函数，自动处理 401 错误并跳转到登录页面
 */
export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const url = resolveServiceURL(path);
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  
  // 如果没有传入 token，尝试从 store 获取
  if (!token) {
    token = useAuthStore.getState().token;
  }
  
  if (token) {
    (headers as any).Authorization = `Bearer ${token}`;
  }
  
  const res = await fetch(url, {
    ...options,
    headers,
  });
  
  // 处理 401 未授权错误
  if (res.status === 401) {
    handleUnauthorized();
    throw new Error("未授权，请重新登录");
  }
  
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `请求失败: ${res.status}`);
  }
  
  return res.json();
}

/**
 * 检查响应状态，如果是 401 则处理未授权错误
 * 用于 SSE 流等非 JSON 响应
 */
export function checkResponseStatus(res: Response): void {
  if (res.status === 401) {
    handleUnauthorized();
    throw new Error("未授权，请重新登录");
  }
}

