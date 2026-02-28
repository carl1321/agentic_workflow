"use client";

import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { LibraryPage } from "~/app/chat/components/library-page";
import { useAuthStore } from "~/core/store/auth-store";

/**
 * 我的文库独立子页面，便于外嵌或分享链接 /library
 */
export default function LibraryRoutePage() {
  const router = useRouter();
  const pathname = usePathname();
  const { token } = useAuthStore();

  useEffect(() => {
    if (token === undefined) return;
    if (!token) router.replace(`/login?redirect=${encodeURIComponent(pathname ?? "/library")}`);
  }, [token, router, pathname]);

  if (token !== undefined && !token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F5F5] dark:bg-slate-900">
        <p className="text-slate-500">正在跳转到登录页...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#F5F5F5] dark:bg-slate-900">
      <div className="flex-1 overflow-auto">
        <LibraryPage onBack={() => router.push("/chat?view=toolbox")} />
      </div>
    </div>
  );
}
