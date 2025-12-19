// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export function resolveServiceURL(path: string) {
  try {
    // 前端统一请求本机 8008 端口的 FastAPI 服务
    // 注意：这里 BASE_URL 末尾保留 `/api/`，后面拼接的是相对路径，不能再以 `/` 开头，
    // 否则会把 `/api/` 覆盖掉，变成 `/auth/login` 之类的根路径。
    let BASE_URL = "http://localhost:8008/api/";

    // 处理相对路径，移除开头的 ./
    let normalizedPath = path.startsWith("./") ? path.slice(2) : path;
    // 去掉前导 `/`，保证是相对于 `/api/` 的子路径
    if (normalizedPath.startsWith("/")) {
      normalizedPath = normalizedPath.slice(1);
    }

    return new URL(normalizedPath, BASE_URL).toString();
  } catch (error) {
    // 兜底：即便上面出错，也继续使用 http://localhost:8008/api/
    console.error("Error resolving service URL:", error);
    const defaultBase = "http://localhost:8008/api/";
    let normalizedPath = path.startsWith("./") ? path.slice(2) : path;
    if (normalizedPath.startsWith("/")) {
      normalizedPath = normalizedPath.slice(1);
    }
    return new URL(normalizedPath, defaultBase).toString();
  }
}
