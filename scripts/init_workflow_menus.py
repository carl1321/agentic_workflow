#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
初始化工作流菜单配置
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.server.auth.admin.menus import MenuAdminDB
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_workflow_menus():
    """初始化工作流菜单"""
    
    from src.server.auth.admin.menus import get_db_connection
    
    # 检查菜单是否已存在
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM menus WHERE code = 'workflow'")
            existing = cursor.fetchone()
            if existing:
                logger.info("工作流菜单已存在，跳过创建")
                return
        
        # 创建工作流主菜单
        workflow_menu_id = MenuAdminDB.create_menu(
            code="workflow",
            name="工作流管理",
            path="/admin/workflows",
            icon="Workflow",
            menu_type="menu",
            permission_code="workflow:read",
            is_visible=True,
            parent_id=None,
        )
        
        if not workflow_menu_id:
            logger.error("创建工作流主菜单失败")
            return
        
        logger.info(f"创建工作流主菜单成功，ID: {workflow_menu_id}")
        
        # 创建工作流列表子菜单
        workflow_list_id = MenuAdminDB.create_menu(
            code="workflow:list",
            name="工作流列表",
            path="/admin/workflows",
            icon="List",
            menu_type="menu",
            permission_code="workflow:read",
            is_visible=True,
            parent_id=workflow_menu_id,
        )
        
        if workflow_list_id:
            logger.info(f"创建工作流列表菜单成功，ID: {workflow_list_id}")
        
        # 创建工作流编辑器子菜单（动态路由，不直接显示在菜单中）
        # 这个菜单项主要用于权限控制，实际访问通过工作流列表跳转
        
        logger.info("工作流菜单初始化完成")
        
    except Exception as e:
        logger.error(f"初始化工作流菜单失败: {e}", exc_info=True)
    finally:
        conn.close()


if __name__ == "__main__":
    init_workflow_menus()

