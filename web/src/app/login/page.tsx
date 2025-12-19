"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuthStore } from "~/core/store/auth-store";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { cn } from "~/lib/utils";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = searchParams.get("redirect") || "/chat";

  const { login, loading, error, user } = useAuthStore();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  // 如果已经登录，直接跳转（放在 effect 里，避免在 render 期间触发路由更新）
  useEffect(() => {
    if (user) {
      router.replace(redirect);
    }
  }, [user, router, redirect]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    try {
      await login({ username, password });
      router.replace(redirect);
    } catch (e: any) {
      const msg =
        e instanceof Error ? e.message : "登录失败，请检查用户名和密码";
      setLocalError(msg);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
      <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-950/80 p-8 shadow-2xl shadow-slate-900/70">
        <h1 className="mb-2 text-center text-2xl font-semibold text-white">
          AgenticWorkflow 管理登录
        </h1>
        <p className="mb-6 text-center text-sm text-slate-400">
          使用管理员账号登录以访问用户与权限管理功能
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username" className="text-slate-200">
              用户名
            </Label>
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="border-slate-700 bg-slate-900 text-slate-100 placeholder:text-slate-500"
              placeholder="admin"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password" className="text-slate-200">
              密码
            </Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="border-slate-700 bg-slate-900 text-slate-100 placeholder:text-slate-500"
              placeholder="输入密码"
              required
            />
          </div>

          {(localError || error) && (
            <div className="rounded-md border border-red-500/50 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {localError || error}
            </div>
          )}

          <Button
            type="submit"
            className={cn(
              "mt-2 w-full bg-emerald-500 text-white hover:bg-emerald-400",
            )}
            disabled={loading}
          >
            {loading ? "登录中..." : "登录"}
          </Button>
        </form>
      </div>
    </div>
  );
}


