// Frontend auth API helpers

import { resolveServiceURL } from "./resolve-service-url";

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RoleInfo {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  organization_id?: string | null;
  data_permission_level: string;
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MenuInfo {
  id: string;
  code: string;
  name: string;
  path?: string | null;
  icon?: string | null;
  component?: string | null;
  menu_type: string;
  permission_code?: string | null;
  is_visible: boolean;
  is_system: boolean;
  sort_order: number;
  parent_id?: string | null;
  children?: MenuInfo[];
}

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  real_name?: string | null;
  is_superuser: boolean;
  roles: RoleInfo[];
  permissions: string[];
  menus: MenuInfo[];
  organization?: any;
  department?: any;
  data_permission_level: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export async function login(request: LoginRequest): Promise<LoginResponse> {
  // Encrypt password before sending
  const { encryptPassword } = await import("../utils/crypto");
  const encryptedPassword = await encryptPassword(request.password);

  const url = resolveServiceURL("auth/login");
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username: request.username,
      password: encryptedPassword, // Send encrypted password
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `登录失败，HTTP ${res.status}`);
  }

  return res.json();
}

export async function fetchCurrentUser(token: string): Promise<UserInfo> {
  // 使用 apiRequest 以便自动处理 401 错误
  const { apiRequest } = await import("./api-client");
  return apiRequest<UserInfo>(
    "auth/me",
    {
      method: "GET",
    },
    token,
  );
}


