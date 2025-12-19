# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Database utilities for RBAC system.
Provides functions to interact with PostgreSQL database directly.
"""

import logging
from typing import List, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    db_url = (
        get_str_env("DATABASE_URL") or
        get_str_env("SQLALCHEMY_DATABASE_URI") or
        get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
    )
    
    # Ensure postgresql:// format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    
    return psycopg.connect(db_url, row_factory=dict_row)


class UserDB:
    """User database operations."""
    
    @staticmethod
    def get_by_username(username: str) -> Optional[dict]:
        """Get user by username."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT u.*, 
                               o.name as organization_name,
                               d.name as department_name
                        FROM users u
                        LEFT JOIN organizations o ON u.organization_id = o.id
                        LEFT JOIN departments d ON u.department_id = d.id
                        WHERE u.username = %s
                        """,
                        (username,)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user by username: {e}")
            return None
    
    @staticmethod
    def get_by_id(user_id: UUID) -> Optional[dict]:
        """Get user by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT u.*, 
                               o.name as organization_name,
                               d.name as department_name
                        FROM users u
                        LEFT JOIN organizations o ON u.organization_id = o.id
                        LEFT JOIN departments d ON u.department_id = d.id
                        WHERE u.id = %s
                        """,
                        (str(user_id),)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            return None
    
    @staticmethod
    def get_user_roles(user_id: UUID) -> List[dict]:
        """Get user's roles."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT r.*
                        FROM roles r
                        INNER JOIN user_roles ur ON r.id = ur.role_id
                        WHERE ur.user_id = %s AND r.is_active = true
                        ORDER BY r.sort_order
                        """,
                        (str(user_id),)
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting user roles: {e}")
            return []
    
    @staticmethod
    def get_user_permissions(user_id: UUID) -> List[str]:
        """Get user's permission codes."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get permissions from user's roles
                    cursor.execute(
                        """
                        SELECT DISTINCT p.code
                        FROM permissions p
                        INNER JOIN role_permissions rp ON p.id = rp.permission_id
                        INNER JOIN user_roles ur ON rp.role_id = ur.role_id
                        WHERE ur.user_id = %s
                        ORDER BY p.code
                        """,
                        (str(user_id),)
                    )
                    return [row["code"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user permissions: {e}")
            return []
    
    @staticmethod
    def get_user_menus(user_id: UUID) -> List[dict]:
        """Get user's accessible menus (tree structure)."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # 首先判断是否为超级管理员；超级管理员默认拥有所有可见菜单
                    cursor.execute(
                        "SELECT is_superuser FROM users WHERE id = %s",
                        (str(user_id),),
                    )
                    row = cursor.fetchone()
                    is_superuser = bool(row and row.get("is_superuser"))

                    if is_superuser:
                        # 超级管理员：直接返回所有 is_visible = true 的菜单
                        cursor.execute(
                            """
                            SELECT *
                            FROM menus
                            WHERE is_visible = true
                            ORDER BY sort_order
                            """
                        )
                        return cursor.fetchall()

                    # 普通用户：根据角色关联的菜单来计算可访问菜单
                    # Get menu IDs from user's roles
                    cursor.execute(
                        """
                        SELECT DISTINCT m.id
                        FROM menus m
                        INNER JOIN role_menus rm ON m.id = rm.menu_id
                        INNER JOIN user_roles ur ON rm.role_id = ur.role_id
                        WHERE ur.user_id = %s AND m.is_visible = true
                        """,
                        (str(user_id),)
                    )
                    menu_ids = [row["id"] for row in cursor.fetchall()]
                    
                    if not menu_ids:
                        return []
                    
                    # Get all menus (including parents for tree structure)
                    cursor.execute(
                        """
                        WITH RECURSIVE menu_tree AS (
                            SELECT m.*, 0 as level
                            FROM menus m
                            WHERE m.id = ANY(%s::uuid[])
                            
                            UNION ALL
                            
                            SELECT m.*, mt.level + 1
                            FROM menus m
                            INNER JOIN menu_tree mt ON m.id = mt.parent_id
                        )
                        SELECT DISTINCT * FROM menu_tree
                        ORDER BY sort_order, level
                        """,
                        (menu_ids,)
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting user menus: {e}")
            return []
    
    @staticmethod
    def update_last_login(user_id: UUID):
        """Update user's last login time."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE users SET last_login_at = NOW() WHERE id = %s",
                        (str(user_id),)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Error updating last login: {e}")


class TokenBlacklist:
    """Token blacklist management."""
    
    @staticmethod
    def add_token(token_jti: str, user_id: UUID, expires_at):
        """Add token to blacklist."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO user_sessions (user_id, token_jti, expires_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (token_jti) DO NOTHING
                        """,
                        (str(user_id), token_jti, expires_at)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Error adding token to blacklist: {e}")
    
    @staticmethod
    def is_blacklisted(token_jti: str) -> bool:
        """Check if token is blacklisted."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1 FROM user_sessions
                        WHERE token_jti = %s AND expires_at > NOW()
                        """,
                        (token_jti,)
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking token blacklist: {e}")
            return False
    
    @staticmethod
    def cleanup_expired():
        """Clean up expired tokens."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM user_sessions WHERE expires_at < NOW()"
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {e}")

