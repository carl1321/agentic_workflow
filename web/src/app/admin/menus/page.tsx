"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  createAdminMenu,
  deleteAdminMenu,
  listAdminMenus,
  type AdminMenuItem,
} from "~/core/api/admin";
import { useAuthStore } from "~/core/store/auth-store";
import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

function flattenMenuOptions(
  menus: AdminMenuItem[],
  level = 0,
): Array<{ id: string; label: string }> {
  const prefix = level > 0 ? `${"—".repeat(level)} ` : "";
  const out: Array<{ id: string; label: string }> = [];
  for (const m of menus) {
    out.push({ id: m.id, label: `${prefix}${m.name} (${m.code})` });
    if (m.children && m.children.length > 0) {
      out.push(...flattenMenuOptions(m.children, level + 1));
    }
  }
  return out;
}

export default function AdminMenusPage() {
  const { token } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [menus, setMenus] = useState<AdminMenuItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    code: "",
    name: "",
    path: "",
    parent_id: "", // "" 表示顶层
    permission_code: "", // 权限代码，格式：resource:action（如：menu:read），留空则自动生成
    is_visible: true,
  });

  const parentOptions = useMemo(
    () => flattenMenuOptions(menus),
    [menus],
  );

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

  function openCreate() {
    setForm({
      code: "",
      name: "",
      path: "",
      parent_id: "",
      permission_code: "",
      is_visible: true,
    });
    setFormError(null);
    setDialogOpen(true);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (!form.code || !form.name) {
      setFormError("编码和名称为必填项");
      return;
    }
    try {
      setSaving(true);
      setFormError(null);
      await createAdminMenu(token, {
        code: form.code,
        name: form.name,
        path: form.path?.trim() ? form.path.trim() : null,
        parent_id: form.parent_id ? form.parent_id : null,
        permission_code: form.permission_code?.trim() ? form.permission_code.trim() : null,
        is_visible: form.is_visible,
      });
      setDialogOpen(false);
      await load();
    } catch (e: any) {
      setFormError(e?.message ?? "创建失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(menu: AdminMenuItem) {
    if (!token) return;
    if (!confirm(`确定要删除菜单「${menu.name}」吗？`)) return;
    try {
      await deleteAdminMenu(token, menu.id);
      await load();
    } catch (e: any) {
      alert(e?.message ?? "删除失败");
    }
  }

  function renderMenuTree(list: AdminMenuItem[], level = 0): JSX.Element[] {
    const indent = level * 16;
    return list.flatMap((m) => [
      <tr key={m.id} className="hover:bg-slate-50">
        <td className="border-t border-slate-200 px-3 py-2">
          <span style={{ paddingLeft: indent }}>{m.name}</span>
        </td>
        <td className="border-t border-slate-200 px-3 py-2">{m.code}</td>
        <td className="border-t border-slate-200 px-3 py-2">{m.path}</td>
        <td className="border-t border-slate-200 px-3 py-2">
          {m.menu_type || "menu"}
        </td>
        <td className="border-t border-slate-200 px-3 py-2">
          {m.permission_code || "-"}
        </td>
        <td className="border-t border-slate-200 px-3 py-2 text-right">
          {!m.is_system && (
            <Button
              variant="outline"
              size="xs"
              className="h-6 border-red-300 px-2 text-[11px] text-red-600 hover:bg-red-50"
              onClick={() => handleDelete(m)}
            >
              删除
            </Button>
          )}
        </td>
      </tr>,
      ...(m.children ? renderMenuTree(m.children, level + 1) : []),
    ]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">菜单管理</h1>
        <Button
          size="sm"
          className="bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
          onClick={openCreate}
        >
          新建菜单
        </Button>
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
              <th className="border-b border-slate-200 px-3 py-2 text-right text-slate-600">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                  正在加载...
                </td>
              </tr>
            ) : menus.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                  暂无菜单
                </td>
              </tr>
            ) : (
              renderMenuTree(menus)
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>新建菜单</DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={handleSubmit}>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="code">编码</Label>
                <Input
                  id="code"
                  value={form.code}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, code: e.target.value }))
                  }
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="name">名称</Label>
                <Input
                  id="name"
                  value={form.name}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, name: e.target.value }))
                  }
                  required
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label htmlFor="path">路径</Label>
              <Input
                id="path"
                value={form.path}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, path: e.target.value }))
                }
                placeholder="例如：/admin/menus（可选）"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="permission_code">权限代码</Label>
              <Input
                id="permission_code"
                value={form.permission_code}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, permission_code: e.target.value }))
                }
                placeholder="留空则自动生成（根据菜单编码生成权限代码）"
              />
              <p className="text-[10px] text-slate-500 mt-0.5">
                留空：自动根据菜单编码生成权限代码（如 menu:read）并创建 read/create/update/delete 权限 | 
                填写：使用指定权限代码（格式：resource:action）
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1 text-xs">
                <Label>父菜单</Label>
                <select
                  className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                  value={form.parent_id}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, parent_id: e.target.value }))
                  }
                >
                  <option value="">顶层（无父菜单）</option>
                  {parentOptions.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1 text-xs">
                <Label>是否可见</Label>
                <select
                  className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                  value={form.is_visible ? "true" : "false"}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      is_visible: e.target.value === "true",
                    }))
                  }
                >
                  <option value="true">可见</option>
                  <option value="false">隐藏</option>
                </select>
              </div>
            </div>

            {formError && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                {formError}
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                className="h-8 px-3 text-xs"
                onClick={() => setDialogOpen(false)}
              >
                取消
              </Button>
              <Button
                type="submit"
                className="h-8 bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
                disabled={saving}
              >
                {saving ? "创建中..." : "创建"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}


