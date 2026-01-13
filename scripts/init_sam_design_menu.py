#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
初始化SAM分子设计菜单、权限和角色配置
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.server.auth.admin.menus import MenuAdminDB
from src.server.auth.admin.permissions import PermissionAdminDB
from src.server.auth.admin.roles import RoleAdminDB
from uuid import UUID
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _as_uuid(value):
    """Safely convert possible UUID/str/None to UUID or None."""
    if isinstance(value, UUID):
        return value
    return UUID(str(value)) if value is not None else None


def init_sam_design_menu():
    """初始化SAM分子设计菜单、权限和角色配置"""
    
    from src.server.auth.admin.menus import get_db_connection
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. 创建权限
            permissions = [
                {
                    "code": "sam-design:read",
                    "name": "查看SAM分子设计",
                    "resource": "sam-design",
                    "action": "read",
                    "description": "查看SAM分子设计页面和结果"
                },
                {
                    "code": "sam-design:create",
                    "name": "创建SAM分子设计",
                    "resource": "sam-design",
                    "action": "create",
                    "description": "创建新的SAM分子设计任务"
                },
                {
                    "code": "sam-design:update",
                    "name": "更新SAM分子设计",
                    "resource": "sam-design",
                    "action": "update",
                    "description": "更新SAM分子设计任务"
                },
                {
                    "code": "sam-design:delete",
                    "name": "删除SAM分子设计",
                    "resource": "sam-design",
                    "action": "delete",
                    "description": "删除SAM分子设计任务"
                }
            ]
            
            permission_ids = []
            for perm in permissions:
                # 检查权限是否已存在
                cursor.execute("SELECT id FROM permissions WHERE code = %s", (perm["code"],))
                existing = cursor.fetchone()
                if existing:
                    logger.info(f"权限 {perm['code']} 已存在，跳过创建")
                    permission_ids.append(_as_uuid(existing["id"]))
                else:
                    perm_id = PermissionAdminDB.create_permission(
                        code=perm["code"],
                        name=perm["name"],
                        resource=perm["resource"],
                        action=perm["action"],
                        description=perm["description"]
                    )
                    if perm_id:
                        permission_ids.append(perm_id)
                        logger.info(f"创建权限 {perm['code']} 成功，ID: {perm_id}")
                    else:
                        logger.error(f"创建权限 {perm['code']} 失败")
            
            # 2. 创建菜单（使用 read 权限）
            cursor.execute("SELECT id FROM menus WHERE code = 'sam-design'")
            existing_menu = cursor.fetchone()
            if existing_menu:
                logger.info("SAM分子设计菜单已存在，跳过创建")
                menu_id = _as_uuid(existing_menu["id"])
            else:
                menu_id = MenuAdminDB.create_menu(
                    code="sam-design",
                    name="SAM分子设计",
                    path="/sam-design",
                    icon="FlaskConical",
                    menu_type="menu",
                    permission_code="sam-design:read",  # 使用 read 权限
                    is_visible=True,
                    parent_id=None,
                )
                if not menu_id:
                    logger.error("创建SAM分子设计菜单失败")
                    return
                logger.info(f"创建SAM分子设计菜单成功，ID: {menu_id}")
            
            # 3. 查找或创建 normal_user 角色
            cursor.execute("SELECT id FROM roles WHERE code = 'normal_user'")
            existing_role = cursor.fetchone()
            if existing_role:
                role_id = _as_uuid(existing_role["id"])
                logger.info(f"normal_user 角色已存在，ID: {role_id}")
            else:
                # 创建 normal_user 角色
                role_id = RoleAdminDB.create_role(
                    code="normal_user",
                    name="普通用户",
                    description="普通用户角色，可以访问基本功能",
                    organization_id=None,
                    data_permission_level="self",
                    is_active=True
                )
                if not role_id:
                    logger.error("创建 normal_user 角色失败")
                    return
                logger.info(f"创建 normal_user 角色成功，ID: {role_id}")
            
            # 4. 将权限分配给 normal_user 角色
            # 先获取角色已有的权限
            cursor.execute(
                "SELECT permission_id FROM role_permissions WHERE role_id = %s",
                (str(role_id),)
            )
            existing_perm_ids = [_as_uuid(row["permission_id"]) for row in cursor.fetchall()]
            
            # 合并已有权限和新权限
            all_perm_ids = list(set(existing_perm_ids + permission_ids))
            
            if RoleAdminDB.assign_permissions(role_id, all_perm_ids):
                logger.info(f"成功将权限分配给 normal_user 角色")
            else:
                logger.error("分配权限给 normal_user 角色失败")
            
            # 5. 将菜单分配给 normal_user 角色
            # 先获取角色已有的菜单
            cursor.execute(
                "SELECT menu_id FROM role_menus WHERE role_id = %s",
                (str(role_id),)
            )
            existing_menu_ids = [_as_uuid(row["menu_id"]) for row in cursor.fetchall()]
            
            # 合并已有菜单和新菜单
            all_menu_ids = list(set(existing_menu_ids + [menu_id]))
            
            if RoleAdminDB.assign_menus(role_id, all_menu_ids):
                logger.info(f"成功将菜单分配给 normal_user 角色")
            else:
                logger.error("分配菜单给 normal_user 角色失败")
            
            logger.info("SAM分子设计菜单、权限和角色配置初始化完成")
        
    except Exception as e:
        logger.error(f"初始化SAM分子设计配置失败: {e}", exc_info=True)
    finally:
        conn.close()


if __name__ == "__main__":
    init_sam_design_menu()

