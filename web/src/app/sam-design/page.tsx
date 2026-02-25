"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * SAM分子设计已迁移到 /newSam，此路由仅做重定向
 */
export default function SAMDesignRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/newSam");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
      <p className="text-slate-500 dark:text-slate-400">正在跳转到 SAM 分子设计…</p>
    </div>
  );
}
