// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "~/components/ui/button";

import { ThemeToggle } from "~/components/ui/theme-toggle";
import { Tooltip } from "~/components/ui/tooltip";
import { SettingsDialog } from "~/app/settings/dialogs/settings-dialog";
import { useAuthStore } from "~/core/store/auth-store";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "~/components/ui/dropdown-menu";
import { User as UserIcon, LogOut, KeyRound } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { changeCurrentUserPassword } from "~/core/api/admin";

const Main = dynamic(() => import("./main"), {
  ssr: false,
      loading: () => (
        <div className="flex h-full w-full items-center justify-center">
          Loading AgenticWorkflow...
        </div>
      ),
});

export default function HomePage() {
  const t = useTranslations("chat.page");
  const router = useRouter();
  const pathname = usePathname();
  const { token, user, logout, refreshUser } = useAuthStore();
  const [pwdOpen, setPwdOpen] = useState(false);
  const [pwd1, setPwd1] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [pwdError, setPwdError] = useState<string | null>(null);
  const [pwdSaving, setPwdSaving] = useState(false);

  useEffect(() => {
    if (!token) {
      router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
    }
  }, [token, router, pathname]);

  // 如果用户已登录但没有菜单信息，尝试刷新用户信息
  useEffect(() => {
    if (token && user && (!user.menus || user.menus.length === 0)) {
      refreshUser().catch((e) => {
        console.error("刷新用户信息失败:", e);
      });
    }
  }, [token, user, refreshUser]);

  if (!token) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-slate-100">
        正在跳转到登录页...
      </div>
    );
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !user) return;
    setPwdError(null);
    if (!pwd1 || !pwd2) {
      setPwdError("请输入新密码并确认。");
      return;
    }
    if (pwd1 !== pwd2) {
      setPwdError("两次输入的密码不一致。");
      return;
    }
    try {
      setPwdSaving(true);
      await changeCurrentUserPassword(token, user.id, pwd1);
      setPwdOpen(false);
      setPwd1("");
      setPwd2("");
      alert("密码修改成功，请使用新密码重新登录。");
      logout();
      router.replace("/login");
    } catch (err: any) {
      setPwdError(err?.message ?? "修改密码失败，请稍后重试或联系管理员。");
    } finally {
      setPwdSaving(false);
    }
  }

  return (
    <div className="flex h-screen w-screen flex-col overscroll-none">
      <header className="z-50 flex h-12 items-center justify-end gap-3 border-b border-slate-200 bg-gradient-to-r from-blue-950 via-slate-800 to-sky-300 px-6 shadow-md backdrop-blur">
        {/* 用户菜单放在靠左一点的位置，避免紧贴窗口右边被遮挡 */}
        {user && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full border border-slate-600 bg-slate-900/80 text-xs font-medium text-slate-100 hover:bg-slate-800"
              >
                <span className="sr-only">用户菜单</span>
                <UserIcon className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <div className="px-2 py-2 text-xs text-slate-400">
                <div className="truncate text-slate-100">
                  {user.real_name || user.username}
                </div>
                <div className="truncate text-slate-500">{user.email}</div>
              </div>
              <DropdownMenuItem
                className="cursor-pointer text-xs"
                onClick={() => {
                  setPwdOpen(true);
                  setPwd1("");
                  setPwd2("");
                  setPwdError(null);
                }}
              >
                <KeyRound className="mr-2 h-4 w-4" />
                修改密码
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="cursor-pointer text-xs text-red-400 focus:text-red-400"
                onClick={() => {
                  logout();
                  router.replace("/login");
                }}
              >
                <LogOut className="mr-2 h-4 w-4" />
                退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <div className="flex items-center gap-1">
          <ThemeToggle />
        </div>
        <Suspense>
          <SettingsDialog />
        </Suspense>
      </header>
      <div className="flex-1">
        <Main />
      </div>
      {user && (
        <Dialog open={pwdOpen} onOpenChange={setPwdOpen}>
          <DialogContent className="sm:max-w-[420px]">
            <DialogHeader>
              <DialogTitle>修改密码</DialogTitle>
            </DialogHeader>
            <form className="space-y-3" onSubmit={handleChangePassword}>
              <div className="space-y-1">
                <Label htmlFor="newPwd">新密码</Label>
                <Input
                  id="newPwd"
                  type="password"
                  value={pwd1}
                  onChange={(e) => setPwd1(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="confirmPwd">确认新密码</Label>
                <Input
                  id="confirmPwd"
                  type="password"
                  value={pwd2}
                  onChange={(e) => setPwd2(e.target.value)}
                  required
                />
              </div>
              {pwdError && (
                <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  {pwdError}
                </div>
              )}
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 px-3 text-xs"
                  onClick={() => setPwdOpen(false)}
                >
                  取消
                </Button>
                <Button
                  type="submit"
                  className="h-8 bg-emerald-500 px-3 text-xs text-white hover:bg-emerald-400"
                  disabled={pwdSaving}
                >
                  {pwdSaving ? "提交中..." : "确定修改"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
