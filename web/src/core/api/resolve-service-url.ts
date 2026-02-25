// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * 解析 API 请求路径。使用相对路径，由 nginx 将 /api/ 转发到后端（如 8008）。
 */
export function resolveServiceURL(path: string): string {
  // 处理相对路径，移除开头的 ./
  let normalizedPath = path.startsWith("./") ? path.slice(2) : path;
  // 去掉前导 `/`，保证是相对于 /api/ 的子路径
  if (normalizedPath.startsWith("/")) {
    normalizedPath = normalizedPath.slice(1);
  }
  return `/api/${normalizedPath}`;
}
