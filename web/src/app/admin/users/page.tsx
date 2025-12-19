"use client";

import { useEffect, useMemo, useState } from "react";

import {
  createAdminUser,
  updateAdminUser,
  deleteAdminUser,
  listAdminOrganizations,
  listAdminRoles,
  listAdminUsers,
  listAdminDepartments,
  getAdminUser,
  type AdminDepartment,
  type AdminOrganization,
  type AdminRoleListItem,
  assignUserRoles,
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

export default function AdminUsersPage() {
  const { token } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [orgs, setOrgs] = useState<AdminOrganization[]>([]);
  const [departments, setDepartments] = useState<AdminDepartment[]>([]);
  const [roles, setRoles] = useState<AdminRoleListItem[]>([]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<any | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    username: "",
    real_name: "",
    email: "",
    password: "",
    is_active: true,
    organization_id: "",
    department_id: "",
    role_ids: [] as string[],
  });

  async function load() {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const [userData, orgData, roleData] = await Promise.all([
        listAdminUsers(token),
        listAdminOrganizations(token),
        listAdminRoles(token),
      ]);
      setUsers(userData);
      setOrgs(orgData);
      setRoles(roleData);
    } catch (e: any) {
      setError(e?.message ?? "加载用户列表失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // 选中单位时加载该单位下的部门
  useEffect(() => {
    const orgId = form.organization_id;
    if (!token || !orgId) {
      setDepartments([]);
      setForm((prev) => ({ ...prev, department_id: "" }));
      return;
    }
    (async () => {
      try {
        const depts = await listAdminDepartments(token, orgId);
        setDepartments(depts);
        // 如果当前选中的部门不在新列表中，则清空
        if (form.department_id && !depts.find((d) => d.id === form.department_id)) {
          setForm((prev) => ({ ...prev, department_id: "" }));
        }
      } catch (e) {
        // 部门加载失败不影响主体表单
        console.error(e);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.organization_id, token]);

  async function handleDelete(id: string) {
    if (!token) return;
    if (!confirm("确定要删除该用户吗？")) return;
    try {
      await deleteAdminUser(token, id);
      await load();
    } catch (e: any) {
      alert(e?.message ?? "删除失败");
    }
  }

  function openCreateDialog() {
    setEditingUser(null);
    setForm({
      username: "",
      real_name: "",
      email: "",
      password: "",
      is_active: true,
      organization_id: "",
      department_id: "",
      role_ids: [],
    });
    setFormError(null);
    setDialogOpen(true);
  }

  async function openEditDialog(user: any) {
    if (!token) return;
    try {
      // 为确保拿到完整的角色信息，单独请求 /api/admin/users/{id}
      const full = await getAdminUser(token, user.id);
      setEditingUser(full);
      setForm({
        username: full.username ?? "",
        real_name: full.real_name ?? "",
        email: full.email ?? "",
        password: "",
        is_active: full.is_active ?? true,
        organization_id: full.organization_id ?? "",
        department_id: full.department_id ?? "",
        role_ids: Array.isArray(full.roles) ? full.roles.map((r: any) => r.id) : [],
      });
      setFormError(null);
      setDialogOpen(true);
    } catch (e: any) {
      setFormError(e?.message ?? "加载用户信息失败");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setFormError(null);
    try {
      setSaving(true);
      if (!editingUser) {
        if (!form.username || !form.password || !form.email) {
          setFormError("用户名、密码、邮箱为必填项");
          setSaving(false);
          return;
        }
        const created = await createAdminUser(token, {
          username: form.username,
          password: form.password,
          email: form.email,
          real_name: form.real_name || null,
          organization_id: form.organization_id || null,
          department_id: form.department_id || null,
          is_active: form.is_active,
        });
        if (form.role_ids.length) {
          await assignUserRoles(token, created.id, form.role_ids);
        }
      } else {
        await updateAdminUser(token, editingUser.id, {
          username: form.username || undefined,
          email: form.email || undefined,
          real_name: form.real_name || null,
          organization_id: form.organization_id || null,
          department_id: form.department_id || null,
          is_active: form.is_active,
        });
        await assignUserRoles(token, editingUser.id, form.role_ids);
      }
      setDialogOpen(false);
      await load();
    } catch (e: any) {
      setFormError(e?.message ?? "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const orgOptions = useMemo(() => orgs, [orgs]);

  const roleOptions = useMemo(() => roles, [roles]);

  function toggleRole(roleId: string) {
    setForm((prev) => {
      const exists = prev.role_ids.includes(roleId);
      return {
        ...prev,
        role_ids: exists
          ? prev.role_ids.filter((id) => id !== roleId)
          : [...prev.role_ids, roleId],
      };
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">用户管理</h1>
        <Button
          size="sm"
          className="bg-sky-500 text-xs text-white hover:bg-sky-400"
          onClick={openCreateDialog}
        >
          新建用户
        </Button>
      </div>
      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      )}
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="min-w-full border-collapse text-xs">
          <thead className="bg-slate-100">
            <tr>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                用户名
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                姓名
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                邮箱
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                角色
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
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-slate-500">
                  暂无用户
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id} className="hover:bg-slate-50">
                  <td className="border-t border-slate-200 px-3 py-2">
                    {u.username}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {u.real_name || "-"}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {u.email}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {Array.isArray(u.roles) && u.roles.length > 0
                      ? u.roles.map((r: any) => r.name).join("，")
                      : "-"}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {u.is_active ? (
                      <span className="rounded bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-600">
                        启用
                      </span>
                    ) : (
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                        禁用
                      </span>
                    )}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2 text-right">
                    <Button
                      variant="outline"
                      size="xs"
                      className="mr-2 h-6 border-slate-300 px-2 text-[11px] text-slate-700 hover:bg-slate-100"
                      onClick={() => {
                        void openEditDialog(u);
                      }}
                    >
                      编辑
                    </Button>
                    <Button
                      variant="outline"
                      size="xs"
                      className="h-6 border-red-300 px-2 text-[11px] text-red-600 hover:bg-red-50"
                      onClick={() => handleDelete(u.id)}
                    >
                      删除
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>
              {editingUser ? "编辑用户" : "新建用户"}
            </DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={handleSubmit}>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="username">用户名</Label>
                <Input
                  id="username"
                  value={form.username}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, username: e.target.value }))
                  }
                  disabled={!!editingUser}
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="real_name">姓名</Label>
                <Input
                  id="real_name"
                  value={form.real_name}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, real_name: e.target.value }))
                  }
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, email: e.target.value }))
                }
                required
              />
            </div>
            {!editingUser && (
              <div className="space-y-1">
                <Label htmlFor="password">密码</Label>
                <Input
                  id="password"
                  type="password"
                  value={form.password}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, password: e.target.value }))
                  }
                  required
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>所属单位</Label>
                <select
                  className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                  value={form.organization_id}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      organization_id: e.target.value,
                      department_id: "",
                    }))
                  }
                >
                  <option value="">（未选择）</option>
                  {orgOptions.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label>所属部门</Label>
                <select
                  className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                  value={form.department_id}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      department_id: e.target.value,
                    }))
                  }
                  disabled={!form.organization_id || departments.length === 0}
                >
                  <option value="">
                    {form.organization_id
                      ? departments.length === 0
                        ? "该单位暂无部门"
                        : "（未选择）"
                      : "请先选择单位"}
                  </option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
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
            <div className="space-y-1">
              <Label>角色</Label>
              <div className="max-h-32 space-y-1 overflow-y-auto rounded border border-slate-300 bg-white px-2 py-2 text-xs text-slate-800">
                {roleOptions.length === 0 && (
                  <span className="text-slate-500">
                    暂无可用角色，请先在角色管理中创建。
                  </span>
                )}
                {roleOptions.map((r) => {
                  const checked = form.role_ids.includes(r.id);
                  return (
                    <label
                      key={r.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-slate-50"
                    >
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5"
                        checked={checked}
                        onChange={() => toggleRole(r.id)}
                      />
                      <span className="truncate">{r.name}</span>
                    </label>
                  );
                })}
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
                {saving ? "保存中..." : editingUser ? "保存" : "创建"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

