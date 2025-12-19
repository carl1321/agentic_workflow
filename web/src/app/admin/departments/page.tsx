"use client";

import { useEffect, useState } from "react";

import {
  createAdminDepartment,
  deleteAdminDepartment,
  listAdminDepartments,
  listAdminOrganizations,
  updateAdminDepartment,
  type AdminDepartment,
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

export default function AdminDepartmentsPage() {
  const { token } = useAuthStore();
  const [orgs, setOrgs] = useState<any[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [depts, setDepts] = useState<AdminDepartment[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AdminDepartment | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    organization_id: "",
    code: "",
    name: "",
    description: "",
    is_active: true,
  });

  async function loadOrgs() {
    if (!token) return;
    try {
      const data = await listAdminOrganizations(token);
      setOrgs(data);
      if (data.length > 0 && !selectedOrgId) {
        setSelectedOrgId(data[0].id);
      }
    } catch (e: any) {
      console.error(e);
    }
  }

  async function loadDepts(orgId: string) {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const data = await listAdminDepartments(token, orgId);
      setDepts(data);
    } catch (e: any) {
      setError(e?.message ?? "加载部门列表失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadOrgs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (selectedOrgId) {
      void loadDepts(selectedOrgId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOrgId]);

  function renderDeptTree(list: AdminDepartment[], level = 0): JSX.Element[] {
    const indent = level * 16;
    return list.flatMap((d) => [
      <tr key={d.id} className="hover:bg-slate-50">
        <td className="border-t border-slate-200 px-3 py-2">
          <span style={{ paddingLeft: indent }}>{d.name}</span>
        </td>
        <td className="border-t border-slate-200 px-3 py-2">{d.code}</td>
        <td className="border-t border-slate-200 px-3 py-2">
          {d.description || "-"}
        </td>
        <td className="border-t border-slate-200 px-3 py-2">
          <span
            className={
              d.is_active
                ? "rounded bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-600"
                : "rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
            }
          >
            {d.is_active ? "启用" : "禁用"}
          </span>
        </td>
        <td className="border-t border-slate-200 px-3 py-2 text-right">
          <Button
            variant="outline"
            size="xs"
            className="mr-2 h-6 border-slate-300 px-2 text-[11px] text-slate-700 hover:bg-slate-100"
            onClick={() => {
              setEditing(d);
              setForm({
                organization_id: d.organization_id,
                code: d.code,
                name: d.name,
                description: d.description || "",
                is_active: d.is_active,
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
            onClick={() => handleDelete(d)}
          >
            删除
          </Button>
        </td>
      </tr>,
      ...(d.children ? renderDeptTree(d.children, level + 1) : []),
    ]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">部门管理</h1>
        <Button
          size="sm"
          className="bg-sky-500 px-3 text-xs text-white hover:bg-sky-400"
          onClick={() => {
            setEditing(null);
            setForm({
              organization_id: selectedOrgId || "",
              code: "",
              name: "",
              description: "",
              is_active: true,
            });
            setFormError(null);
            setDialogOpen(true);
          }}
        >
          新建部门
        </Button>
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-700">
        <span>所属单位：</span>
        <select
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800"
          value={selectedOrgId ?? ""}
          onChange={(e) => setSelectedOrgId(e.target.value || null)}
        >
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
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
              <th className="border-b border-slate-200 px-3 py-2 text-left text-slate-600">
                操作
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
            ) : depts.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-4 text-center text-slate-500">
                  暂无部门
                </td>
              </tr>
            ) : (
              renderDeptTree(depts)
            )}
          </tbody>
        </table>
      </div>
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑部门" : "新建部门"}</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!token) return;
              const orgId = form.organization_id || selectedOrgId;
              if (!orgId) {
                setFormError("请先选择所属单位");
                return;
              }
              if (!form.code || !form.name) {
                setFormError("编码和名称为必填项");
                return;
              }
              try {
                setSaving(true);
                setFormError(null);
                if (!editing) {
                  await createAdminDepartment(token, {
                    code: form.code,
                    name: form.name,
                    organization_id: orgId,
                    description: form.description || null,
                    parent_id: null,
                    manager_id: null,
                    is_active: form.is_active,
                  });
                } else {
                  await updateAdminDepartment(token, editing.id, {
                    name: form.name,
                    description: form.description || null,
                    organization_id: orgId,
                    is_active: form.is_active,
                  });
                }
                setDialogOpen(false);
                setSelectedOrgId(orgId);
                await loadDepts(orgId);
              } catch (err: any) {
                setFormError(err?.message ?? "保存失败");
              } finally {
                setSaving(false);
              }
            }}
          >
            <div className="space-y-1 text-xs">
              <Label>所属单位</Label>
              <select
                className="h-9 w-full rounded border border-slate-300 bg-white px-2 text-xs text-slate-800"
                value={form.organization_id || selectedOrgId || ""}
                onChange={(e) => {
                  const orgId = e.target.value || "";
                  setForm((prev) => ({
                    ...prev,
                    organization_id: orgId,
                  }));
                }}
              >
                <option value="">请选择单位</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="dept-code">编码</Label>
                <Input
                  id="dept-code"
                  value={form.code}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, code: e.target.value }))
                  }
                  disabled={!!editing}
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="dept-name">名称</Label>
                <Input
                  id="dept-name"
                  value={form.name}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, name: e.target.value }))
                  }
                  required
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="dept-desc">描述</Label>
              <Input
                id="dept-desc"
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
