"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuthStore } from "~/core/store/auth-store";
import { getCasdoorLoginUrl } from "~/core/api/auth";
import { Button } from "~/components/ui/button";

/**
 * 登录入口：直接跳转到 Casdoor 登录，不展示中间登录页
 */
export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = searchParams.get("redirect") || "/chat";

  const { user } = useAuthStore();
  const [error, setError] = useState<string | null>(null);

  // 已登录则直接去目标页
  useEffect(() => {
    if (user) {
      router.replace(redirect);
    }
  }, [user, router, redirect]);

  // 未登录时直接跳转 Casdoor
  useEffect(() => {
    if (user) return;

    let cancelled = false;
    setError(null);

    const go = async () => {
      try {
        const origin = typeof window !== "undefined" ? window.location.origin : "";
        const redirectUri = `${origin}/login/callback`;
        const { url } = await getCasdoorLoginUrl(redirectUri, redirect);
        if (cancelled) return;
        window.location.href = url;
      } catch (e: unknown) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "获取 Casdoor 登录地址失败";
        setError(msg);
      }
    };

    go();
    return () => {
      cancelled = true;
    };
  }, [user, redirect]);

  if (user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
        <p className="text-slate-400">正在跳转…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
        <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-950/80 p-8 text-center">
          <p className="mb-4 text-sm text-red-300">{error}</p>
          <Button
            variant="outline"
            className="border-slate-600 text-slate-200 hover:bg-slate-800 hover:text-white"
            onClick={() => {
              setError(null);
              const origin = typeof window !== "undefined" ? window.location.origin : "";
              const redirectUri = `${origin}/login/callback`;
              getCasdoorLoginUrl(redirectUri, redirect).then(
                ({ url }) => { window.location.href = url; },
                (e) => setError(e instanceof Error ? e.message : "获取 Casdoor 登录地址失败"),
              );
            }}
          >
            重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
      <div className="text-center text-slate-400">
        <p className="animate-pulse">正在跳转到 Casdoor 登录…</p>
      </div>
    </div>
  );
}
