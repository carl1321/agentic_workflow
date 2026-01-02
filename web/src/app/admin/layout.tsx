"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import type { MenuInfo, UserInfo } from "~/core/api/auth";
import { useAuthStore } from "~/core/store/auth-store";
import { Button } from "~/components/ui/button";
import { cn } from "~/lib/utils";

function isAdminUser(user: UserInfo | null | undefined): boolean {
  if (!user) return false;
  if ((user as any).is_superuser) return true;
  const roles = (user as any).roles || [];
  // 把 code 为 admin 或 user_admin 的角色都视为后台管理员
  const adminCodes = new Set(["admin", "user_admin"]);
  return (
    Array.isArray(roles) &&
    roles.some((r: any) => r?.code && adminCodes.has(r.code))
  );
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, token, loading, refreshUser, logout } = useAuthStore();

  // 菜单计算必须放在任何可能 return 之前，避免 Hooks 顺序在不同渲染之间变化
  const menus = useMemo(() => {
    // 管理后台下不展示 /chat 相关菜单（对话、工具箱、知识库等）
    const visible = (user?.menus || [])
      .filter((m) => m.is_visible !== false)
      .filter((m) => !m.path || !m.path.startsWith("/chat"));
    const sortMenus = (list: MenuInfo[]): MenuInfo[] =>
      [...list]
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((m) => ({
          ...m,
          children: m.children ? sortMenus(m.children) : [],
        }));
    return sortMenus(visible);
  }, [user?.menus]);

  // 如果有 token 但 user 为空，或者 user 没有菜单信息，则尝试刷新用户信息（调用 /api/auth/me）
  useEffect(() => {
    if (!token || loading) return;
    if (!user || !user.menus || user.menus.length === 0) {
      refreshUser().catch(() => {
        router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
      });
    }
  }, [token, user, loading, refreshUser, router, pathname]);

  // 未登录访问 /admin/** -> 跳转登录
  useEffect(() => {
    if (loading) return;
    if (!token) {
      router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
    }
  }, [loading, token, pathname, router]);

  // 已登录但不是管理员：在副作用中触发重定向，避免在渲染阶段调用 router
  useEffect(() => {
    if (loading) return;
    if (!token || !user) return;
    if (!isAdminUser(user)) {
      router.replace("/chat");
    }
  }, [loading, token, user, router]);

  // 加载中或刚拿到 token 但还没拉到 user
  if (loading || (!user && token)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        正在验证登录状态...
      </div>
    );
  }

  // 未登录：已在 effect 里触发跳转，这里只做占位
  if (!token || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        即将跳转到登录页...
      </div>
    );
  }

  // 已登录但不是管理员：副作用中已触发重定向，这里仅显示占位
  if (!isAdminUser(user)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        正在跳转到主页面...
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      {/* 侧边栏：改为浅色系 */}
      <aside className="flex w-64 flex-col border-r border-slate-200 bg-white/95">
        <div className="flex h-14 items-center border-b border-slate-200 px-4 text-lg font-semibold">
          <span className="text-sky-600">Agentic</span>
          <span className="ml-1 text-slate-900">Admin</span>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3 text-sm">
          {menus.length === 0 && (
            <div className="px-3 py-2 text-xs text-slate-400">
              当前账号未配置菜单，请检查后台角色与菜单权限。
            </div>
          )}
          {menus.map((menu, index) => (
            <MenuItem key={`${menu.id}-${index}-${menu.path || ''}`} menu={menu} level={0} activePath={pathname} />
          ))}
        </nav>
      </aside>

      {/* 右侧主内容区：light 风格 + 顶部右上角退出 */}
      <div className="flex min-h-screen flex-1 flex-col">
        {/* 顶部栏 */}
        <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-gradient-to-r from-sky-100 via-sky-200 to-sky-300 px-4 backdrop-blur">
          <div className="text-sm font-medium text-slate-900">
            管理后台
            <span className="ml-2 text-xs text-slate-600">
              {user.is_superuser ? "超级管理员" : "普通管理员"}
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-600">
            <span className="hidden sm:inline">
              {user.real_name || user.username}（{user.email}）
            </span>
            <span className="hidden md:inline text-slate-500">
              当前路径：<span className="text-slate-700">{pathname}</span>
            </span>
            <Button
              variant="outline"
              size="sm"
              className="h-8 border-sky-500/60 bg-white/80 px-3 text-xs font-medium text-sky-700 hover:bg-sky-100 hover:text-sky-800"
              onClick={() => {
                logout();
                router.replace("/login");
              }}
            >
              退出登录
            </Button>
          </div>
        </header>

        {/* 内容 */}
        <main className="flex-1 overflow-y-auto bg-slate-50 p-4">
          <div className="mx-auto max-w-6xl rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

function MenuItem({
  menu,
  level,
  activePath,
}: {
  menu: MenuInfo;
  level: number;
  activePath: string;
}) {
  const hasChildren = !!menu.children && menu.children.length > 0;
  const indent = level * 12;
  const isActive =
    !!menu.path &&
    (activePath === menu.path || activePath.startsWith(`${menu.path}/`));

  const content = (
    <div
      className={cn(
        "flex items-center rounded-md border px-2.5 py-1.5 text-xs transition-colors",
        isActive
          ? "border-sky-500 bg-sky-500 text-white shadow-sm"
          : "border-slate-200 bg-white text-slate-700 hover:border-sky-300 hover:bg-sky-50",
      )}
      style={{ paddingLeft: 8 + indent }}
    >
      <span className="truncate">{menu.name}</span>
    </div>
  );

  return (
    <div className="mb-1">
      {menu.path ? (
        <Link href={menu.path}>{content}</Link>
      ) : (
        <div>{content}</div>
      )}
      {hasChildren &&
        menu.children!.map((child, index) => (
          <MenuItem
            key={`${child.id}-${level + 1}-${index}-${child.path || ''}`}
            menu={child}
            level={level + 1}
            activePath={activePath}
          />
        ))}
    </div>
  );
}

