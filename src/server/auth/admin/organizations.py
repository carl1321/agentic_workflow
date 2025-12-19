# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Organization database operations.
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


class OrganizationDB:
    """Organization database operations."""
    
    @staticmethod
    def get_by_id(org_id: UUID) -> Optional[dict]:
        """Get organization by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM organizations
                        WHERE id = %s
                        """,
                        (str(org_id),)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting organization by ID: {e}")
            return None
    
    @staticmethod
    def get_by_code(code: str) -> Optional[dict]:
        """Get organization by code."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM organizations
                        WHERE code = %s
                        """,
                        (code,)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting organization by code: {e}")
            return None
    
    @staticmethod
    def list_all(include_inactive: bool = False) -> List[dict]:
        """List all organizations."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if include_inactive:
                        cursor.execute("SELECT * FROM organizations ORDER BY sort_order, name")
                    else:
                        cursor.execute("SELECT * FROM organizations WHERE is_active = true ORDER BY sort_order, name")
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing organizations: {e}")
            return []
    
    @staticmethod
    def get_children(parent_id: UUID) -> List[dict]:
        """Get child organizations."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM organizations
                        WHERE parent_id = %s AND is_active = true
                        ORDER BY sort_order, name
                        """,
                        (str(parent_id),)
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting child organizations: {e}")
            return []

    @staticmethod
    def create(
        code: str,
        name: str,
        description: Optional[str] = None,
        parent_id: Optional[UUID] = None,
        is_active: bool = True,
    ) -> Optional[UUID]:
        """Create a new organization."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get next sort_order under the same parent
                    if parent_id:
                        cursor.execute(
                            """
                            SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                            FROM organizations
                            WHERE parent_id = %s
                            """,
                            (str(parent_id),),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                            FROM organizations
                            WHERE parent_id IS NULL
                            """
                        )
                    next_order = cursor.fetchone()["next_order"]

                    cursor.execute(
                        """
                        INSERT INTO organizations (
                            code, name, description, parent_id,
                            is_active, sort_order
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            code,
                            name,
                            description,
                            str(parent_id) if parent_id else None,
                            is_active,
                            next_order,
                        ),
                    )
                    org_id = cursor.fetchone()["id"]
                    conn.commit()
                    return _as_uuid(org_id)
        except Exception as e:
            logger.error(f"Error creating organization: {e}")
            return None

    @staticmethod
    def update(
        org_id: UUID,
        code: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update organization information."""
        try:
            updates = []
            values: list = []

            if code is not None:
                updates.append("code = %s")
                values.append(code)
            if name is not None:
                updates.append("name = %s")
                values.append(name)
            if description is not None:
                updates.append("description = %s")
                values.append(description)
            if parent_id is not None:
                updates.append("parent_id = %s")
                values.append(str(parent_id) if parent_id else None)
            if is_active is not None:
                updates.append("is_active = %s")
                values.append(is_active)

            if not updates:
                return True

            updates.append("updated_at = NOW()")
            values.append(str(org_id))

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE organizations
                        SET {', '.join(updates)}
                        WHERE id = %s
                        """,
                        values,
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating organization: {e}")
            return False

    @staticmethod
    def delete(org_id: UUID) -> bool:
        """Delete an organization.

        For simplicity, we perform a hard delete. In production you may want
        to check for children or related data first.
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM organizations WHERE id = %s",
                        (str(org_id),),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting organization: {e}")
            return False

