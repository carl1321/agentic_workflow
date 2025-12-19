# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Role management database operations.
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


class RoleAdminDB:
    """Role management database operations."""
    
    @staticmethod
    def create_role(
        code: str,
        name: str,
        description: Optional[str] = None,
        organization_id: Optional[UUID] = None,
        data_permission_level: str = "self",
        is_active: bool = True,
    ) -> Optional[UUID]:
        """Create a new role."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get max sort_order
                    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM roles")
                    next_order = cursor.fetchone()["next_order"]
                    
                    cursor.execute(
                        """
                        INSERT INTO roles (
                            code, name, description, organization_id,
                            data_permission_level, is_active, sort_order
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            code, name, description,
                            str(organization_id) if organization_id else None,
                            data_permission_level, is_active, next_order
                        )
                    )
                    role_id = cursor.fetchone()["id"]
                    conn.commit()
                    return _as_uuid(role_id)
        except Exception as e:
            logger.error(f"Error creating role: {e}")
            return None
    
    @staticmethod
    def update_role(
        role_id: UUID,
        code: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        organization_id: Optional[UUID] = None,
        data_permission_level: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update role information."""
        try:
            updates = []
            values = []
            
            if code is not None:
                updates.append("code = %s")
                values.append(code)
            if name is not None:
                updates.append("name = %s")
                values.append(name)
            if description is not None:
                updates.append("description = %s")
                values.append(description)
            if organization_id is not None:
                updates.append("organization_id = %s")
                values.append(str(organization_id))
            if data_permission_level is not None:
                updates.append("data_permission_level = %s")
                values.append(data_permission_level)
            if is_active is not None:
                updates.append("is_active = %s")
                values.append(is_active)
            
            if not updates:
                return True
            
            updates.append("updated_at = NOW()")
            values.append(str(role_id))
            
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE roles
                        SET {', '.join(updates)}
                        WHERE id = %s AND is_system = false
                        """,
                        values
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating role: {e}")
            return False
    
    @staticmethod
    def delete_role(role_id: UUID) -> bool:
        """Delete a role (only non-system roles can be deleted)."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM roles
                        WHERE id = %s AND is_system = false
                        """,
                        (str(role_id),)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting role: {e}")
            return False
    
    @staticmethod
    def assign_permissions(role_id: UUID, permission_ids: List[UUID]) -> bool:
        """Assign permissions to a role."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Remove existing permissions
                    cursor.execute(
                        "DELETE FROM role_permissions WHERE role_id = %s",
                        (str(role_id),)
                    )
                    # Add new permissions
                    if permission_ids:
                        cursor.executemany(
                            """
                            INSERT INTO role_permissions (role_id, permission_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            [(str(role_id), str(perm_id)) for perm_id in permission_ids]
                        )
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Error assigning permissions: {e}")
            return False
    
    @staticmethod
    def assign_menus(role_id: UUID, menu_ids: List[UUID]) -> bool:
        """Assign menus to a role."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Remove existing menus
                    cursor.execute(
                        "DELETE FROM role_menus WHERE role_id = %s",
                        (str(role_id),)
                    )
                    # Add new menus
                    if menu_ids:
                        cursor.executemany(
                            """
                            INSERT INTO role_menus (role_id, menu_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            [(str(role_id), str(menu_id)) for menu_id in menu_ids]
                        )
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Error assigning menus: {e}")
            return False
    
    @staticmethod
    def get_by_id(role_id: UUID) -> Optional[dict]:
        """Get role by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM roles WHERE id = %s",
                        (str(role_id),)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting role by ID: {e}")
            return None
    
    @staticmethod
    def list_roles(
        limit: int = 50,
        offset: int = 0,
        organization_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
        include_system: bool = False,
    ) -> List[dict]:
        """List roles with filters."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    conditions = []
                    params = []
                    
                    if not include_system:
                        conditions.append("is_system = false")
                    if organization_id:
                        conditions.append("organization_id = %s")
                        params.append(str(organization_id))
                    if is_active is not None:
                        conditions.append("is_active = %s")
                        params.append(is_active)
                    
                    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
                    
                    params.extend([limit, offset])
                    
                    cursor.execute(
                        f"""
                        SELECT * FROM roles
                        {where_clause}
                        ORDER BY sort_order, name
                        LIMIT %s OFFSET %s
                        """,
                        params
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing roles: {e}")
            return []
    
    @staticmethod
    def get_role_permissions(role_id: UUID) -> List[dict]:
        """Get permissions assigned to a role."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT p.*
                        FROM permissions p
                        INNER JOIN role_permissions rp ON p.id = rp.permission_id
                        WHERE rp.role_id = %s
                        ORDER BY p.code
                        """,
                        (str(role_id),)
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting role permissions: {e}")
            return []
    
    @staticmethod
    def get_role_menus(role_id: UUID) -> List[dict]:
        """Get menus assigned to a role."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT m.*
                        FROM menus m
                        INNER JOIN role_menus rm ON m.id = rm.menu_id
                        WHERE rm.role_id = %s
                        ORDER BY m.sort_order
                        """,
                        (str(role_id),)
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting role menus: {e}")
            return []

