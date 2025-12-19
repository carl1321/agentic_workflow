"use client";

import { useEffect, useState } from "react";

import { listAdminMenus } from "~/core/api/admin";
import { useAuthStore } from "~/core/store/auth-store";

export default function AdminMenusPage() {
  const { token } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [menus, setMenus] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const data = await listAdminMenus(token);
      setMenus(data);
    } catch (e: any) {
      setError(e?.message ?? "加载菜单列表失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function renderMenuTree(list: any[], level = 0): JSX.Element[] {
    const indent = level * 16;
    return list.flatMap((m) => [
      <tr key={m.id} className="hover:bg-slate-900/60">
        <td className="border-t border-slate-800 px-3 py-2">
          <span style={{ paddingLeft: indent }}>{m.name}</span>
        </td>
        <td className="border-t border-slate-800 px-3 py-2">{m.code}</td>
        <td className="border-t border-slate-800 px-3 py-2">{m.path}</td>
        <td className="border-t border-slate-800 px-3 py-2">
          {m.menu_type || "menu"}
        </td>
        <td className="border-t border-slate-800 px-3 py-2">
          {m.permission_code || "-"}
        </td>
      </tr>,
      ...(m.children ? renderMenuTree(m.children, level + 1) : []),
    ]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">菜单管理</h1>
        <button
          className="rounded bg-sky-500 px-3 py-1 text-xs text-white hover:bg-sky-400"
          onClick={() => alert("后续可在此实现菜单创建 / 编辑对话框")}
        >
          新建菜单
        </button>
      </div>
      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
          {error}
        </div>
      )}
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="min-w-full border-collapse text-xs">
          <thead className="bg-slate-100">
            <tr>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                名称（树形）
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                编码
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                路径
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                类型
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                绑定权限
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                  正在加载...
                </td>
              </tr>
            ) : menus.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                  暂无菜单
                </td>
              </tr>
            ) : (
              renderMenuTree(menus)
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}


