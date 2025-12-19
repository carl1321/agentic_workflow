# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
User management database operations.
"""

import logging
from typing import List, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env
from src.server.auth.password import hash_password

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


class UserAdminDB:
    """User management database operations."""
    
    @staticmethod
    def create_user(
        username: str,
        email: str,
        password: str,
        real_name: Optional[str] = None,
        phone: Optional[str] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        is_active: bool = True,
        data_permission_level: str = "self",
    ) -> Optional[UUID]:
        """Create a new user."""
        try:
            password_hash = hash_password(password)
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users (
                            username, email, password_hash, real_name, phone,
                            organization_id, department_id, is_active, data_permission_level
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            username, email, password_hash, real_name, phone,
                            str(organization_id) if organization_id else None,
                            str(department_id) if department_id else None,
                            is_active, data_permission_level
                        )
                    )
                    user_id = cursor.fetchone()["id"]
                    conn.commit()
                    return _as_uuid(user_id)
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None
    
    @staticmethod
    def update_user(
        user_id: UUID,
        username: Optional[str] = None,
        email: Optional[str] = None,
        real_name: Optional[str] = None,
        phone: Optional[str] = None,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
        data_permission_level: Optional[str] = None,
    ) -> bool:
        """Update user information."""
        try:
            updates = []
            values = []
            
            if username is not None:
                updates.append("username = %s")
                values.append(username)
            if email is not None:
                updates.append("email = %s")
                values.append(email)
            if real_name is not None:
                updates.append("real_name = %s")
                values.append(real_name)
            if phone is not None:
                updates.append("phone = %s")
                values.append(phone)
            if organization_id is not None:
                updates.append("organization_id = %s")
                values.append(str(organization_id))
            if department_id is not None:
                updates.append("department_id = %s")
                values.append(str(department_id))
            if is_active is not None:
                updates.append("is_active = %s")
                values.append(is_active)
            if data_permission_level is not None:
                updates.append("data_permission_level = %s")
                values.append(data_permission_level)
            
            if not updates:
                return True
            
            updates.append("updated_at = NOW()")
            values.append(str(user_id))
            
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE users
                        SET {', '.join(updates)}
                        WHERE id = %s
                        """,
                        values
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            return False
    
    @staticmethod
    def change_password(user_id: UUID, new_password: str) -> bool:
        """Change user password."""
        try:
            password_hash = hash_password(new_password)
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE users
                        SET password_hash = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (password_hash, str(user_id))
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error changing password: {e}")
            return False
    
    @staticmethod
    def delete_user(user_id: UUID) -> bool:
        """Delete a user (soft delete by setting is_active=False)."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE users
                        SET is_active = false, updated_at = NOW()
                        WHERE id = %s AND is_superuser = false
                        """,
                        (str(user_id),)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False
    
    @staticmethod
    def assign_roles(user_id: UUID, role_ids: List[UUID]) -> bool:
        """Assign roles to a user."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Remove existing roles
                    cursor.execute(
                        "DELETE FROM user_roles WHERE user_id = %s",
                        (str(user_id),)
                    )
                    # Add new roles
                    if role_ids:
                        cursor.executemany(
                            """
                            INSERT INTO user_roles (user_id, role_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            [(str(user_id), str(role_id)) for role_id in role_ids]
                        )
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Error assigning roles: {e}")
            return False
    
    @staticmethod
    def list_users(
        limit: int = 50,
        offset: int = 0,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
    ) -> List[dict]:
        """List users with filters."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    conditions = []
                    params = []
                    
                    if organization_id:
                        conditions.append("u.organization_id = %s")
                        params.append(str(organization_id))
                    if department_id:
                        conditions.append("u.department_id = %s")
                        params.append(str(department_id))
                    if is_active is not None:
                        conditions.append("u.is_active = %s")
                        params.append(is_active)
                    
                    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
                    
                    params.extend([limit, offset])
                    
                    cursor.execute(
                        f"""
                        SELECT u.*, 
                               o.name as organization_name,
                               d.name as department_name
                        FROM users u
                        LEFT JOIN organizations o ON u.organization_id = o.id
                        LEFT JOIN departments d ON u.department_id = d.id
                        {where_clause}
                        ORDER BY u.created_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        params
                    )
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []

