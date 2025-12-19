# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Department database operations.
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


class DepartmentDB:
    """Department database operations."""
    
    @staticmethod
    def get_by_id(dept_id: UUID) -> Optional[dict]:
        """Get department by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM departments
                        WHERE id = %s
                        """,
                        (str(dept_id),)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting department by ID: {e}")
            return None
    
    @staticmethod
    def get_by_code(code: str, organization_id: Optional[UUID] = None) -> Optional[dict]:
        """Get department by code."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if organization_id:
                        cursor.execute(
                            """
                            SELECT * FROM departments
                            WHERE code = %s AND organization_id = %s
                            """,
                            (code, str(organization_id))
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT * FROM departments
                            WHERE code = %s
                            """,
                            (code,)
                        )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting department by code: {e}")
            return None
    
    @staticmethod
    def list_by_organization(organization_id: UUID, include_inactive: bool = False) -> List[dict]:
        """List departments by organization."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if include_inactive:
                        cursor.execute(
                            """
                            SELECT * FROM departments
                            WHERE organization_id = %s
                            ORDER BY sort_order, name
                            """,
                        (str(organization_id),)
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT * FROM departments
                            WHERE organization_id = %s AND is_active = true
                            ORDER BY sort_order, name
                            """,
                        (str(organization_id),)
                        )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing departments by organization: {e}")
            return []
    
    @staticmethod
    def get_children(parent_id: UUID) -> List[dict]:
        """Get child departments."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM departments
                        WHERE parent_id = %s AND is_active = true
                        ORDER BY sort_order, name
                        """,
                        (str(parent_id),)
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting child departments: {e}")
            return []

    @staticmethod
    def create(
        code: str,
        name: str,
        organization_id: UUID,
        description: Optional[str] = None,
        parent_id: Optional[UUID] = None,
        manager_id: Optional[UUID] = None,
        is_active: bool = True,
    ) -> Optional[UUID]:
        """Create a new department."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get next sort_order under same parent in same organization
                    if parent_id:
                        cursor.execute(
                            """
                            SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                            FROM departments
                            WHERE organization_id = %s AND parent_id = %s
                            """,
                            (str(organization_id), str(parent_id)),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                            FROM departments
                            WHERE organization_id = %s AND parent_id IS NULL
                            """,
                            (str(organization_id),),
                        )
                    next_order = cursor.fetchone()["next_order"]

                    cursor.execute(
                        """
                        INSERT INTO departments (
                            code, name, organization_id, description,
                            parent_id, manager_id, is_active, sort_order
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            code,
                            name,
                            str(organization_id),
                            description,
                            str(parent_id) if parent_id else None,
                            str(manager_id) if manager_id else None,
                            is_active,
                            next_order,
                        ),
                    )
                    dept_id = cursor.fetchone()["id"]
                    conn.commit()
                    return _as_uuid(dept_id)
        except Exception as e:
            logger.error(f"Error creating department: {e}")
            return None

    @staticmethod
    def update(
        dept_id: UUID,
        code: Optional[str] = None,
        name: Optional[str] = None,
        organization_id: Optional[UUID] = None,
        description: Optional[str] = None,
        parent_id: Optional[UUID] = None,
        manager_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update department information."""
        try:
            updates = []
            values: list = []

            if code is not None:
                updates.append("code = %s")
                values.append(code)
            if name is not None:
                updates.append("name = %s")
                values.append(name)
            if organization_id is not None:
                updates.append("organization_id = %s")
                values.append(str(organization_id))
            if description is not None:
                updates.append("description = %s")
                values.append(description)
            if parent_id is not None:
                updates.append("parent_id = %s")
                values.append(str(parent_id) if parent_id else None)
            if manager_id is not None:
                updates.append("manager_id = %s")
                values.append(str(manager_id) if manager_id else None)
            if is_active is not None:
                updates.append("is_active = %s")
                values.append(is_active)

            if not updates:
                return True

            updates.append("updated_at = NOW()")
            values.append(str(dept_id))

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE departments
                        SET {', '.join(updates)}
                        WHERE id = %s
                        """,
                        values,
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating department: {e}")
            return False

    @staticmethod
    def delete(dept_id: UUID) -> bool:
        """Delete a department.

        For simplicity, we perform a hard delete. In production you may want
        to check for children or related users first.
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM departments WHERE id = %s",
                        (str(dept_id),),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting department: {e}")
            return False

