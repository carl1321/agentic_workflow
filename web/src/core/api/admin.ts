// Admin API helpers for RBAC resources

import { resolveServiceURL } from "./resolve-service-url";
import type {
  LoginResponse,
  MenuInfo,
  RoleInfo,
  UserInfo,
} from "./auth";

// --- Common helper ---

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const url = resolveServiceURL(path);
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) {
    (headers as any).Authorization = `Bearer ${token}`;
  }
  const res = await fetch(url, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `请求失败: ${res.status}`);
  }
  return res.json();
}

// --- Users ---

export interface AdminUserListItem extends UserInfo {}

// 带角色信息的用户（用于编辑时精确回显）
export interface AdminUserWithRoles extends AdminUserListItem {
  roles: RoleInfo[];
}

export async function listAdminUsers(
  token: string,
): Promise<AdminUserListItem[]> {
  const data = await request<{ users?: AdminUserListItem[] } | AdminUserListItem[]>(
    "admin/users",
    { method: "GET" },
    token,
  );
  // 兼容数组或对象包装
  return Array.isArray(data) ? data : data.users ?? [];
}

export async function getAdminUser(
  token: string,
  userId: string,
): Promise<AdminUserWithRoles> {
  return request<AdminUserWithRoles>(
    `admin/users/${userId}`,
    { method: "GET" },
    token,
  );
}

export async function deleteAdminUser(token: string, userId: string) {
  await request(`admin/users/${userId}`, { method: "DELETE" }, token);
}

export async function assignUserRoles(
  token: string,
  userId: string,
  roleIds: string[],
): Promise<void> {
  await request<void>(
    `admin/users/${userId}/assign-roles`,
    {
      method: "POST",
      body: JSON.stringify(roleIds),
    },
    token,
  );
}

export interface AdminUserCreatePayload {
  username: string;
  password: string;
  email: string;
  real_name?: string | null;
  phone?: string | null;
  organization_id?: string | null;
  department_id?: string | null;
  is_active: boolean;
  role_ids?: string[];
}

export interface AdminUserUpdatePayload {
  username?: string;
  email?: string;
  real_name?: string | null;
  phone?: string | null;
  organization_id?: string | null;
  department_id?: string | null;
  is_active?: boolean;
  data_permission_level?: string;
}

export async function createAdminUser(
  token: string,
  payload: AdminUserCreatePayload,
): Promise<AdminUserListItem> {
  return request<AdminUserListItem>(
    "admin/users",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function updateAdminUser(
  token: string,
  userId: string,
  payload: AdminUserUpdatePayload,
): Promise<AdminUserListItem> {
  return request<AdminUserListItem>(
    `admin/users/${userId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    token,
  );
}

// --- Roles ---

export interface AdminRoleListItem extends RoleInfo {}

export async function listAdminRoles(
  token: string,
): Promise<AdminRoleListItem[]> {
  const data = await request<AdminRoleListItem[]>(
    "admin/roles",
    { method: "GET" },
    token,
  );
  return data;
}

export async function getRolePermissions(
  token: string,
  roleId: string,
): Promise<AdminPermission[]> {
  return request<AdminPermission[]>(
    `admin/roles/${roleId}/permissions`,
    { method: "GET" },
    token,
  );
}

export async function assignRolePermissions(
  token: string,
  roleId: string,
  permissionIds: string[],
): Promise<void> {
  await request<void>(
    `admin/roles/${roleId}/assign-permissions`,
    {
      method: "POST",
      body: JSON.stringify(permissionIds),
    },
    token,
  );
}

export interface AdminRolePayload {
  code: string;
  name: string;
  description?: string | null;
  organization_id?: string | null;
  data_permission_level: string;
  is_active: boolean;
}

export async function createAdminRole(
  token: string,
  payload: AdminRolePayload,
): Promise<AdminRoleListItem> {
  return request<AdminRoleListItem>(
    "admin/roles",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function updateAdminRole(
  token: string,
  roleId: string,
  payload: Partial<AdminRolePayload>,
): Promise<AdminRoleListItem> {
  return request<AdminRoleListItem>(
    `admin/roles/${roleId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function deleteAdminRole(token: string, roleId: string) {
  await request<void>(
    `admin/roles/${roleId}`,
    { method: "DELETE" },
    token,
  );
}

// --- Permissions ---

export interface AdminPermission {
  id: string;
  code: string;
  name: string;
  resource: string;
  action: string;
  description?: string | null;
  is_system: boolean;
  created_at?: string | null;
}

export async function listAdminPermissions(
  token: string,
): Promise<AdminPermission[]> {
  const data = await request<AdminPermission[]>(
    "admin/permissions",
    { method: "GET" },
    token,
  );
  return data;
}

export interface AdminPermissionPayload {
  code: string;
  name: string;
  resource: string;
  action: string;
  description?: string | null;
}

export async function createAdminPermission(
  token: string,
  payload: AdminPermissionPayload,
): Promise<AdminPermission> {
  return request<AdminPermission>(
    "admin/permissions",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function deleteAdminPermission(
  token: string,
  permissionId: string,
) {
  await request<void>(
    `admin/permissions/${permissionId}`,
    { method: "DELETE" },
    token,
  );
}

// --- Menus ---

export interface AdminMenuItem extends MenuInfo {}

export async function listAdminMenus(
  token: string,
): Promise<AdminMenuItem[]> {
  const data = await request<AdminMenuItem[]>(
    "admin/menus",
    { method: "GET" },
    token,
  );
  return data;
}

export async function getRoleMenus(
  token: string,
  roleId: string,
): Promise<AdminMenuItem[]> {
  return request<AdminMenuItem[]>(
    `admin/roles/${roleId}/menus`,
    { method: "GET" },
    token,
  );
}

export async function assignRoleMenus(
  token: string,
  roleId: string,
  menuIds: string[],
): Promise<void> {
  await request<void>(
    `admin/roles/${roleId}/assign-menus`,
    {
      method: "POST",
      body: JSON.stringify(menuIds),
    },
    token,
  );
}

export interface AdminMenuPayload {
  code: string;
  name: string;
  path?: string | null;
  menu_type?: string;
  permission_code?: string | null;
  parent_id?: string | null;
  is_visible?: boolean;
  sort_order?: number;
}

export async function createAdminMenu(
  token: string,
  payload: AdminMenuPayload,
): Promise<AdminMenuItem> {
  return request<AdminMenuItem>(
    "admin/menus",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function updateAdminMenu(
  token: string,
  menuId: string,
  payload: Partial<AdminMenuPayload>,
): Promise<AdminMenuItem> {
  return request<AdminMenuItem>(
    `admin/menus/${menuId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function deleteAdminMenu(token: string, menuId: string) {
  await request<void>(
    `admin/menus/${menuId}`,
    { method: "DELETE" },
    token,
  );
}

// --- Organizations ---

export interface AdminOrganization {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  parent_id?: string | null;
  is_active: boolean;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
  children?: AdminOrganization[];
}

export async function listAdminOrganizations(
  token: string,
): Promise<AdminOrganization[]> {
  const data = await request<AdminOrganization[]>(
    "admin/organizations",
    { method: "GET" },
    token,
  );
  return data;
}

export interface AdminOrganizationPayload {
  code: string;
  name: string;
  description?: string | null;
  parent_id?: string | null;
  is_active: boolean;
}

export async function createAdminOrganization(
  token: string,
  payload: AdminOrganizationPayload,
): Promise<AdminOrganization> {
  return request<AdminOrganization>(
    "admin/organizations",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function updateAdminOrganization(
  token: string,
  orgId: string,
  payload: Partial<AdminOrganizationPayload>,
): Promise<AdminOrganization> {
  return request<AdminOrganization>(
    `admin/organizations/${orgId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function deleteAdminOrganization(token: string, orgId: string) {
  await request<void>(
    `admin/organizations/${orgId}`,
    { method: "DELETE" },
    token,
  );
}

// --- Departments ---

export interface AdminDepartment {
  id: string;
  code: string;
  name: string;
  organization_id: string;
  description?: string | null;
  parent_id?: string | null;
  manager_id?: string | null;
  is_active: boolean;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
  children?: AdminDepartment[];
}

export async function listAdminDepartments(
  token: string,
  organizationId: string,
): Promise<AdminDepartment[]> {
  const data = await request<AdminDepartment[]>(
    `admin/departments?organization_id=${encodeURIComponent(organizationId)}`,
    { method: "GET" },
    token,
  );
  return data;
}

export interface AdminDepartmentPayload {
  code: string;
  name: string;
  organization_id: string;
  description?: string | null;
  parent_id?: string | null;
  manager_id?: string | null;
  is_active: boolean;
}

export async function createAdminDepartment(
  token: string,
  payload: AdminDepartmentPayload,
): Promise<AdminDepartment> {
  return request<AdminDepartment>(
    "admin/departments",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function updateAdminDepartment(
  token: string,
  deptId: string,
  payload: Partial<AdminDepartmentPayload>,
): Promise<AdminDepartment> {
  return request<AdminDepartment>(
    `admin/departments/${deptId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export async function deleteAdminDepartment(token: string, deptId: string) {
  await request<void>(
    `admin/departments/${deptId}`,
    { method: "DELETE" },
    token,
  );
}

// --- Self-service: change current user's password via admin endpoint ---

export async function changeCurrentUserPassword(
  token: string,
  userId: string,
  newPassword: string,
): Promise<void> {
  await request<void>(
    `admin/users/${userId}/change-password`,
    {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    },
    token,
  );
}



