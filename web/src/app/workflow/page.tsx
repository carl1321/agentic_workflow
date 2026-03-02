"use client";

import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { WorkflowsPage } from "~/app/chat/components/workflows-page";
import { useAuthStore, useAuthRehydratedStore } from "~/core/store/auth-store";

export default function WorkflowRoutePage() {
  const router = useRouter();
  const pathname = usePathname();
  const { token } = useAuthStore();
  const hasRehydrated = useAuthRehydratedStore((s) => s.hasRehydrated);

  useEffect(() => {
    if (!hasRehydrated) return;
    if (!token) router.replace(`/login?redirect=${encodeURIComponent(pathname ?? "/workflow")}`);
  }, [hasRehydrated, token, router, pathname]);

  if (!hasRehydrated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F5F5] dark:bg-slate-900">
        <p className="text-slate-500">Loading...</p>
      </div>
    );
  }
  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F5F5] dark:bg-slate-900">
        <p className="text-slate-500">正在跳转到登录页...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#F5F5F5] dark:bg-slate-900">
      <div className="flex-1 overflow-auto">
        <WorkflowsPage onBack={() => router.push("/chat?view=toolbox")} />
      </div>
    </div>
  );
}
