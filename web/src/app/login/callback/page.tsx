"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuthStore } from "~/core/store/auth-store";
import { casdoorCallback } from "~/core/api/auth";

export default function LoginCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state") || "/chat";

    if (!code) {
      setErrorMsg("缺少授权码，请从登录页重新选择 Casdoor 登录");
      setStatus("error");
      return;
    }

    let cancelled = false;
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const redirectUri = `${origin}/login/callback`;

    (async () => {
      try {
        const res = await casdoorCallback(code, state || undefined, redirectUri);
        if (cancelled) return;
        useAuthStore.setState({
          token: res.access_token,
          user: res.user,
          error: null,
          loading: false,
        });
        setStatus("ok");
        router.replace(state || "/chat");
      } catch (e: unknown) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Casdoor 登录失败";
        setErrorMsg(msg);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [searchParams, router]);

  if (status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
        <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-950/80 p-8 text-center">
          <p className="mb-4 text-sm text-red-300">{errorMsg}</p>
          <a
            href="/login"
            className="inline-block rounded-md bg-slate-700 px-4 py-2 text-sm text-white hover:bg-slate-600"
          >
            返回登录页
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
      <div className="text-center text-slate-400">
        <p className="animate-pulse">正在完成 Casdoor 登录…</p>
      </div>
    </div>
  );
}
