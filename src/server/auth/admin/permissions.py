# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Permission management database operations.
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


class PermissionAdminDB:
    """Permission management database operations."""
    
    @staticmethod
    def create_permission(
        code: str,
        name: str,
        resource: str,
        action: str,
        description: Optional[str] = None,
    ) -> Optional[UUID]:
        """Create a new permission."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO permissions (code, name, resource, action, description)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (code, name, resource, action, description)
                    )
                    perm_id = cursor.fetchone()["id"]
                    conn.commit()
                    return _as_uuid(perm_id)
        except Exception as e:
            logger.error(f"Error creating permission: {e}")
            return None
    
    @staticmethod
    def get_by_id(perm_id: UUID) -> Optional[dict]:
        """Get permission by ID."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM permissions WHERE id = %s",
                        (str(perm_id),)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting permission by ID: {e}")
            return None
    
    @staticmethod
    def get_by_code(code: str) -> Optional[dict]:
        """Get permission by code."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM permissions WHERE code = %s",
                        (code,)
                    )
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting permission by code: {e}")
            return None
    
    @staticmethod
    def list_permissions(
        limit: int = 1000,
        offset: int = 0,
        resource: Optional[str] = None,
        include_system: bool = True,
    ) -> List[dict]:
        """List permissions with filters."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    conditions = []
                    params = []
                    
                    if not include_system:
                        conditions.append("is_system = false")
                    if resource:
                        conditions.append("resource = %s")
                        params.append(resource)
                    
                    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
                    
                    params.extend([limit, offset])
                    
                    cursor.execute(
                        f"""
                        SELECT * FROM permissions
                        {where_clause}
                        ORDER BY resource, code
                        LIMIT %s OFFSET %s
                        """,
                        params
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing permissions: {e}")
            return []

