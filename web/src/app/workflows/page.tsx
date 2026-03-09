// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function WorkflowsPage() {
  const router = useRouter();

  useEffect(() => {
    // 重定向到 chat 页面，并设置 view=workflow
    router.replace("/chat?view=workflow");
  }, [router]);

  return (
    <div className="flex h-screen w-screen items-center justify-center">
      正在跳转...
    </div>
  );
}

