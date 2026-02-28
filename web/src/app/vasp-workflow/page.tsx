"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * VASP 计算入口：跳转到对话页，用户可在对话中使用 VASP 计算
 */
export default function VaspWorkflowRoutePage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/chat");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F5F5F5] dark:bg-slate-900">
      <p className="text-slate-500 dark:text-slate-400">正在跳转到对话...</p>
    </div>
  );
}
