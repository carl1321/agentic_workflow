"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * 深度研究入口：跳转到对话页，用户可在对话中发起深度研究
 */
export default function DeepResearchRoutePage() {
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
