# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Menu management database operations.
"""

import logging
from typing import List, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env

logger = logging.getLogger(__name__)


def _as_uuid(value):
    """Safely convert possible UUID/str/None to UUID or None."""
    if isinstance(value, UUID):
        return value
    return UUID(str(value)) if value is not None else None


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


class MenuAdminDB:
    """Menu management database operations."""
    
    @staticmethod
    def create_menu(
        code: str,
        name: str,
        path: Optional[str] = None,
        icon: Optional[str] = None,
        component: Optional[str] = None,
        menu_type: str = "menu",
        permission_code: Optional[str] = None,
        is_visible: bool = True,
        parent_id: Optional[UUID] = None,
    ) -> Optional[UUID]:
        """Create a new menu."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get max sort_order for parent
                    if parent_id:
                        cursor.execute(
                            "SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM menus WHERE parent_id = %s",
                            (str(parent_id),)
                        )
                    else:
                        cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM menus WHERE parent_id IS NULL")
                    next_order = cursor.fetchone()["next_order"]
                    
                    cursor.execute(
                        """
                        INSERT INTO menus (
                            code, name, path, icon, component, menu_type,
                            permission_code, is_visible, parent_id, sort_order
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            code, name, path, icon, component, menu_type,
                            permission_code, is_visible,
                            str(parent_id) if parent_id else None,
                            next_order
                        )
                    )
                    menu_id = cursor.fetchone()["id"]
                    conn.commit()
                    return _as_uuid(menu_id)
        except Exception as e:
            logger.error(f"Error creating menu: {e}")
            return None
    
    @staticmethod
    def update_menu(
        menu_id: UUID,
        code: Optional[str] = None,
        name: Optional[str] = None,
        path: Optional[str] = None,
        icon: Optional[str] = None,
        component: Optional[str] = None,
        menu_type: Optional[str] = None,
        permission_code: Optional[str] = None,
        is_visible: Optional[bool] = None,
        parent_id: Optional[UUID] = None,
        sort_order: Optional[int] = None,
    ) -> bool:
        """Update menu information."""
        try:
            updates = []
            values = []
            
            if code is not None:
                updates.append("code = %s")
                values.append(code)
            if name is not None:
                updates.append("name = %s")
                values.append(name)
            if path is not None:
                updates.append("path = %s")
                values.append(path)
            if icon is not None:
                updates.append("icon = %s")
                values.append(icon)
            if component is not None:
                updates.append("component = %s")
                values.append(component)
            if menu_type is not None:
                updates.append("menu_type = %s")
                values.append(menu_type)
            if permission_code is not None:
                updates.append("permission_code = %s")
                values.append(permission_code)
            if is_visible is not None:
                updates.append("is_visible = %s")
                values.append(is_visible)
            if parent_id is not None:
                updates.append("parent_id = %s")
                values.append(str(parent_id) if parent_id else None)
            if sort_order is not None:
                updates.append("sort_order = %s")
                values.append(sort_order)
            
            if not updates:
                return True
            
            updates.append("updated_at = NOW()")
            values.append(str(menu_id))
            
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE menus
                        SET {', '.join(updates)}
                        WHERE id = %s AND is_system = false
                        """,
                        values
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating menu: {e}")
            return False
    
    @staticmethod
    def delete_menu(menu_id: UUID) -> bool:
        """Delete a menu (only non-system menus can be deleted)."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM menus
                        WHERE id = %s AND is_system = false
                        """,
                        (str(menu_id),)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting menu: {e}")
            return False
    
    @staticmethod
    def get_by_id(menu_id: UUID) -> Optional[dict]:
        """Get menu by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM menus WHERE id = %s",
                        (str(menu_id),)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting menu by ID: {e}")
            return None
    
    @staticmethod
    def list_all(include_system: bool = True) -> List[dict]:
        """List all menus."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if include_system:
                        cursor.execute("SELECT * FROM menus ORDER BY sort_order, name")
                    else:
                        cursor.execute("SELECT * FROM menus WHERE is_system = false ORDER BY sort_order, name")
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing menus: {e}")
            return []

