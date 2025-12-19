"use client";

import { useEffect, useState } from "react";

import {
  assignRoleMenus,
  assignRolePermissions,
  createAdminRole,
  deleteAdminRole,
  getRoleMenus,
  getRolePermissions,
  listAdminMenus,
  listAdminPermissions,
  listAdminRoles,
  type AdminMenuItem,
  type AdminPermission,
  type AdminRoleListItem,
  updateAdminRole,
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

export default function AdminRolesPage() {
  const { token } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [roles, setRoles] = useState<AdminRoleListItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AdminRoleListItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    code: "",
    name: "",
    description: "",
    data_permission_level: "self",
    is_active: true,
  });

  // 权限配置弹窗
  const [permDialogOpen, setPermDialogOpen] = useState(false);
  const [permRole, setPermRole] = useState<AdminRoleListItem | null>(null);
  const [permLoading, setPermLoading] = useState(false);
  const [permSaving, setPermSaving] = useState(false);
  const [permError, setPermError] = useState<string | null>(null);
  const [allPerms, setAllPerms] = useState<AdminPermission[]>([]);
  const [selectedPermIds, setSelectedPermIds] = useState<string[]>([]);

  // 菜单配置弹窗
  const [menuDialogOpen, setMenuDialogOpen] = useState(false);
  const [menuRole, setMenuRole] = useState<AdminRoleListItem | null>(null);
  const [menuLoading, setMenuLoading] = useState(false);
  const [menuSaving, setMenuSaving] = useState(false);
  const [menuError, setMenuError] = useState<string | null>(null);
  const [allMenus, setAllMenus] = useState<AdminMenuItem[]>([]);
  const [selectedMenuIds, setSelectedMenuIds] = useState<string[]>([]);

  async function openPermConfig(role: AdminRoleListItem) {
    if (!token) return;
    setPermDialogOpen(true);
    setPermRole(role);
    setPermError(null);
    setPermLoading(true);
    try {
      const [perms, rolePerms] = await Promise.all([
        listAdminPermissions(token),
        getRolePermissions(token, role.id),
      ]);
      setAllPerms(perms);
      setSelectedPermIds(rolePerms.map((p) => p.id));
    } catch (e: any) {
      setPermError(e?.message ?? "加载角色权限失败");
    } finally {
      setPermLoading(false);
    }
  }

  async function submitPermConfig(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !permRole) return;
    try {
      setPermSaving(true);
      setPermError(null);
      await assignRolePermissions(token, permRole.id, selectedPermIds);
      setPermDialogOpen(false);
    } catch (e: any) {
      setPermError(e?.message ?? "保存权限配置失败");
    } finally {
      setPermSaving(false);
    }
  }

  async function openMenuConfig(role: AdminRoleListItem) {
    if (!token) return;
    setMenuDialogOpen(true);
    setMenuRole(role);
    setMenuError(null);
    setMenuLoading(true);
    try {
      const [menus, roleMenus] = await Promise.all([
        listAdminMenus(token),
        getRoleMenus(token, role.id),
      ]);
      setAllMenus(menus);
      const collectIds = (items: AdminMenuItem[], acc: string[] = []): string[] => {
        for (const m of items) {
          acc.push(m.id);
          if (m.children && m.children.length) {
            collectIds(m.children, acc);
          }
        }
        return acc;
      };
      setSelectedMenuIds(collectIds(roleMenus));
    } catch (e: any) {
      setMenuError(e?.message ?? "加载角色菜单失败");
    } finally {
      setMenuLoading(false);
    }
  }

  async function submitMenuConfig(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !menuRole) return;
    try {
      setMenuSaving(true);
      setMenuError(null);
      await assignRoleMenus(token, menuRole.id, selectedMenuIds);
      setMenuDialogOpen(false);
    } catch (e: any) {
      setMenuError(e?.message ?? "保存菜单配置失败");
    } finally {
      setMenuSaving(false);
    }
  }

  function togglePerm(id: string) {
    setSelectedPermIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function toggleMenu(id: string) {
    setSelectedMenuIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function renderMenuTree(list: AdminMenuItem[], level = 0): JSX.Element[] {
    const indent = level * 16;
    return list.flatMap((m) => {
      const checked = selectedMenuIds.includes(m.id);
      return [
        <div
          key={m.id}
          className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50"
          style={{ paddingLeft: indent }}
        >
          <input
            type="checkbox"
            className="h-3.5 w-3.5"
            checked={checked}
            onChange={() => toggleMenu(m.id)}
          />
          <span className="truncate text-xs text-slate-800">
            {m.name} <span className="text-[10px] text-slate-400">({m.code})</span>
          </span>
        </div>,
        ...(m.children ? renderMenuTree(m.children, level + 1) : []),
      ];
    });
  }

  async function load() {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const data = await listAdminRoles(token);
      setRoles(data);
    } catch (e: any) {
      setError(e?.message ?? "加载角色列表失败");
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setEditing(null);
    setForm({
      code: "",
      name: "",
      description: "",
      data_permission_level: "self",
      is_active: true,
    });
    setFormError(null);
    setDialogOpen(true);
  }

  function openEdit(role: AdminRoleListItem) {
    setEditing(role);
    setForm({
      code: role.code,
      name: role.name,
      description: role.description || "",
      data_permission_level: role.data_permission_level || "self",
      is_active: role.is_active,
    });
    setFormError(null);
    setDialogOpen(true);
  }

  async function handleDelete(role: AdminRoleListItem) {
    if (!token) return;
    if (!confirm(`确定要删除角色「${role.name}」吗？`)) return;
    try {
      await deleteAdminRole(token, role.id);
      await load();
    } catch (e: any) {
      alert(e?.message ?? "删除失败");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (!form.code || !form.name) {
      setFormError("编码和名称为必填项");
      return;
    }
    try {
      setSaving(true);
      setFormError(null);
      if (!editing) {
        await createAdminRole(token, {
          code: form.code,
          name: form.name,
          description: form.description || null,
          data_permission_level: form.data_permission_level || "self",
          is_active: form.is_active,
        });
      } else {
        await updateAdminRole(token, editing.id, {
          name: form.name,
          description: form.description || null,
          data_permission_level: form.data_permission_level || "self",
          is_active: form.is_active,
        });
      }
      setDialogOpen(false);
      await load();
    } catch (e: any) {
      setFormError(e?.message ?? "保存失败");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">角色管理</h1>
        <Button
          size="sm"
          className="bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
          onClick={openCreate}
        >
          新建角色
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
                编码
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                名称
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                数据权限
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                系统内置
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                状态
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
            ) : roles.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                  暂无角色
                </td>
              </tr>
            ) : (
              roles.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="border-t border-slate-200 px-3 py-2">
                    {r.code}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {r.name}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {r.data_permission_level}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {r.is_system ? "是" : "否"}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    <span
                      className={
                        r.is_active
                          ? "rounded bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-600"
                          : "rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
                      }
                    >
                      {r.is_active ? "启用" : "禁用"}
                    </span>
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2 text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        size="xs"
                        className="h-6 border-sky-300 px-2 text-[11px] text-sky-700 hover:bg-sky-50"
                        onClick={() => openMenuConfig(r)}
                      >
                        配置菜单
                      </Button>
                      <Button
                        variant="outline"
                        size="xs"
                        className="h-6 border-sky-300 px-2 text-[11px] text-sky-700 hover:bg-sky-50"
                        onClick={() => openPermConfig(r)}
                      >
                        配置权限
                      </Button>
                      <Button
                        variant="outline"
                        size="xs"
                        className="h-6 border-slate-300 px-2 text-[11px] text-slate-700 hover:bg-slate-100"
                        onClick={() => openEdit(r)}
                      >
                        编辑
                      </Button>
                      {!r.is_system && (
                        <Button
                          variant="outline"
                          size="xs"
                          className="h-6 border-red-300 px-2 text-[11px] text-red-600 hover:bg-red-50"
                          onClick={() => handleDelete(r)}
                        >
                          删除
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑角色" : "新建角色"}</DialogTitle>
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
                  disabled={!!editing}
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
              <Label htmlFor="desc">描述</Label>
              <Input
                id="desc"
                value={form.description}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    description: e.target.value,
                  }))
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1 text-xs">
                <Label>数据权限</Label>
                <select
                  className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                  value={form.data_permission_level}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      data_permission_level: e.target.value,
                    }))
                  }
                >
                  <option value="self">仅本人数据</option>
                  <option value="department">本部门数据</option>
                  <option value="organization">本单位数据</option>
                  <option value="all">全部数据</option>
                </select>
              </div>
              <div className="space-y-1 text-xs">
                <Label>状态</Label>
                <select
                  className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                  value={form.is_active ? "true" : "false"}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      is_active: e.target.value === "true",
                    }))
                  }
                >
                  <option value="true">启用</option>
                  <option value="false">禁用</option>
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
                {saving ? "保存中..." : editing ? "保存" : "创建"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 权限配置弹窗 */}
      <Dialog open={permDialogOpen} onOpenChange={setPermDialogOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>
              角色权限配置 {permRole ? `（${permRole.name}）` : ""}
            </DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={submitPermConfig}>
            {permError && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                {permError}
              </div>
            )}
            <div className="max-h-72 overflow-y-auto rounded border border-slate-200 bg-slate-50 px-3 py-2">
              {permLoading ? (
                <div className="py-6 text-center text-xs text-slate-500">
                  正在加载权限列表...
                </div>
              ) : allPerms.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">
                  暂无权限，请先在「权限管理」中创建。
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-1">
                  {allPerms.map((p) => {
                    const checked = selectedPermIds.includes(p.id);
                    return (
                      <label
                        key={p.id}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-slate-100"
                      >
                        <input
                          type="checkbox"
                          className="h-3.5 w-3.5"
                          checked={checked}
                          onChange={() => togglePerm(p.id)}
                        />
                        <span className="truncate text-xs text-slate-800">
                          {p.name}{" "}
                          <span className="text-[10px] text-slate-400">
                            ({p.code})
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                className="h-8 px-3 text-xs"
                onClick={() => setPermDialogOpen(false)}
              >
                取消
              </Button>
              <Button
                type="submit"
                className="h-8 bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
                disabled={permSaving}
              >
                {permSaving ? "保存中..." : "保存权限"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 菜单配置弹窗 */}
      <Dialog open={menuDialogOpen} onOpenChange={setMenuDialogOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>
              角色菜单配置 {menuRole ? `（${menuRole.name}）` : ""}
            </DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={submitMenuConfig}>
            {menuError && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                {menuError}
              </div>
            )}
            <div className="max-h-72 overflow-y-auto rounded border border-slate-200 bg-slate-50 px-3 py-2">
              {menuLoading ? (
                <div className="py-6 text-center text-xs text-slate-500">
                  正在加载菜单树...
                </div>
              ) : allMenus.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">
                  暂无菜单，请先在「菜单管理」中创建。
                </div>
              ) : (
                <div className="space-y-0.5">{renderMenuTree(allMenus)}</div>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                className="h-8 px-3 text-xs"
                onClick={() => setMenuDialogOpen(false)}
              >
                取消
              </Button>
              <Button
                type="submit"
                className="h-8 bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
                disabled={menuSaving}
              >
                {menuSaving ? "保存中..." : "保存菜单"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}


