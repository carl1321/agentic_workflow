"use client";

import { useEffect, useState } from "react";

import {
  createAdminOrganization,
  deleteAdminOrganization,
  listAdminOrganizations,
  type AdminOrganization,
} from "~/core/api/admin";
import { useAuthStore } from "~/core/store/auth-store";
import { Button } from "~/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

export default function AdminOrganizationsPage() {
  const { token } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [orgs, setOrgs] = useState<AdminOrganization[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AdminOrganization | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    code: "",
    name: "",
    description: "",
    is_active: true,
  });

  async function load() {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const data = await listAdminOrganizations(token);
      setOrgs(data);
    } catch (e: any) {
      setError(e?.message ?? "加载单位列表失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function renderOrgTree(list: AdminOrganization[], level = 0): JSX.Element[] {
    const indent = level * 16;
    return list.flatMap((o) => [
      <tr key={o.id} className="hover:bg-slate-50">
        <td className="border-t border-slate-200 px-3 py-2">
          <span style={{ paddingLeft: indent }}>{o.name}</span>
        </td>
        <td className="border-t border-slate-200 px-3 py-2">{o.code}</td>
        <td className="border-t border-slate-200 px-3 py-2">
          {o.description || "-"}
        </td>
        <td className="border-t border-slate-200 px-3 py-2">
          <span
            className={
              o.is_active
                ? "rounded bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-600"
                : "rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
            }
          >
            {o.is_active ? "启用" : "禁用"}
          </span>
        </td>
        <td className="border-t border-slate-200 px-3 py-2 text-right">
          <Button
            variant="outline"
            size="xs"
            className="mr-2 h-6 border-slate-300 px-2 text-[11px] text-slate-700 hover:bg-slate-100"
            onClick={() => {
              setEditing(o);
              setForm({
                code: o.code,
                name: o.name,
                description: o.description || "",
                is_active: o.is_active,
              });
              setFormError(null);
              setDialogOpen(true);
            }}
          >
            编辑
          </Button>
          <Button
            variant="outline"
            size="xs"
            className="h-6 border-red-300 px-2 text-[11px] text-red-600 hover:bg-red-50"
            onClick={() => handleDelete(o)}
          >
            删除
          </Button>
        </td>
      </tr>,
      ...(o.children ? renderOrgTree(o.children, level + 1) : []),
    ]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">单位管理</h1>
        <Button
          size="sm"
          className="bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
          onClick={() => {
            setEditing(null);
            setForm({
              code: "",
              name: "",
              description: "",
              is_active: true,
            });
            setFormError(null);
            setDialogOpen(true);
          }}
        >
          新建单位
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
                描述
              </th>
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                状态
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className="px-3 py-4 text-center text-slate-500">
                  正在加载...
                </td>
              </tr>
            ) : orgs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-4 text-center text-slate-500">
                  暂无单位
                </td>
              </tr>
            ) : (
              renderOrgTree(orgs)
            )}
          </tbody>
        </table>
      </div>
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑单位" : "新建单位"}</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={async (e) => {
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
                  await createAdminOrganization(token, {
                    code: form.code,
                    name: form.name,
                    description: form.description || null,
                    is_active: form.is_active,
                  });
                } else {
                  await createAdminOrganization(token, {
                    code: form.code,
                    name: form.name,
                    description: form.description || null,
                    is_active: form.is_active,
                  });
                }
                setDialogOpen(false);
                await load();
              } catch (err: any) {
                setFormError(err?.message ?? "保存失败");
              } finally {
                setSaving(false);
              }
            }}
          >
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="org-code">编码</Label>
                <Input
                  id="org-code"
                  value={form.code}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, code: e.target.value }))
                  }
                  disabled={!!editing}
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="org-name">名称</Label>
                <Input
                  id="org-name"
                  value={form.name}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, name: e.target.value }))
                  }
                  required
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="org-desc">描述</Label>
              <Input
                id="org-desc"
                value={form.description}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    description: e.target.value,
                  }))
                }
              />
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
    </div>
  );
}


