"use client";

export default function AdminHomePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-100">
        欢迎进入管理后台
      </h1>
      <p className="text-sm text-slate-400">
        请通过左侧菜单进入「用户管理」「角色管理」「权限管理」「菜单管理」「单位 / 部门管理」等功能页面。
      </p>
      <p className="text-xs text-slate-500">
        提示：菜单和权限由后端 RBAC 系统动态控制，当前账号可见的菜单取决于其角色与权限配置。
      </p>
    </div>
  );
}


