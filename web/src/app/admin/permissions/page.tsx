"use client";

import { useEffect, useState } from "react";

import {
  createAdminPermission,
  deleteAdminPermission,
  listAdminPermissions,
  type AdminPermission,
} from "~/core/api/admin";
import { useAuthStore } from "~/core/store/auth-store";
import { Button } from "~/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

export default function AdminPermissionsPage() {
  const { token } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [perms, setPerms] = useState<AdminPermission[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AdminPermission | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    code: "",
    name: "",
    resource: "",
    action: "",
    description: "",
  });

  async function load() {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const data = await listAdminPermissions(token);
      setPerms(data);
    } catch (e: any) {
      setError(e?.message ?? "加载权限列表失败");
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setEditing(null);
    setForm({
      code: "",
      name: "",
      resource: "",
      action: "",
      description: "",
    });
    setFormError(null);
    setDialogOpen(true);
  }

  async function handleDelete(p: AdminPermission) {
    if (!token) return;
    if (!confirm(`确定要删除权限「${p.name}」吗？`)) return;
    try {
      await deleteAdminPermission(token, p.id);
      await load();
    } catch (e: any) {
      alert(e?.message ?? "删除失败");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (!form.code || !form.name || !form.resource || !form.action) {
      setFormError("编码、名称、资源、动作为必填项");
      return;
    }
    try {
      setSaving(true);
      setFormError(null);
      await createAdminPermission(token, {
        code: form.code,
        name: form.name,
        resource: form.resource,
        action: form.action,
        description: form.description || undefined,
      });
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
        <h1 className="text-lg font-semibold text-slate-900">权限管理</h1>
        <Button
          size="sm"
          className="bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
          onClick={openCreate}
        >
          新建权限
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
                资源
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                动作
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                系统内置
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
            ) : perms.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                  暂无权限
                </td>
              </tr>
            ) : (
              perms.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="border-t border-slate-200 px-3 py-2">
                    {p.code}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {p.name}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {p.resource}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {p.action}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2">
                    {p.is_system ? "是" : "否"}
                  </td>
                  <td className="border-t border-slate-200 px-3 py-2 text-right">
                    {!p.is_system && (
                      <Button
                        variant="outline"
                        size="xs"
                        className="h-6 border-red-300 px-2 text-[11px] text-red-600 hover:bg-red-50"
                        onClick={() => handleDelete(p)}
                      >
                        删除
                      </Button>
                    )}
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
            <DialogTitle>新建权限</DialogTitle>
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
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="resource">资源</Label>
                <Input
                  id="resource"
                  value={form.resource}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, resource: e.target.value }))
                  }
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="action">动作</Label>
                <Input
                  id="action"
                  value={form.action}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, action: e.target.value }))
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
                {saving ? "保存中..." : "创建"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}


