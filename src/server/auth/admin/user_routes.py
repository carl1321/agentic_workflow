# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
User management API routes.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..dependencies import CurrentUser, require_admin, require_permission
from ..models import UserCreate, UserResponse, UserUpdate, UserWithRoles


class ChangePasswordRequest(BaseModel):
    """Change password request model."""
    new_password: str
from .users import UserAdminDB
from ..db import UserDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin", "users"])


@router.get("", response_model=List[UserResponse])
async def list_users(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: Optional[UUID] = Query(None),
    department_id: Optional[UUID] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:read")),
):
    """List users with filters."""
    users = UserAdminDB.list_users(
        limit=limit,
        offset=offset,
        organization_id=organization_id,
        department_id=department_id,
        is_active=is_active,
    )
    
    return [
        UserResponse(
            id=user["id"] if isinstance(user["id"], UUID) else UUID(str(user["id"])),
            username=user["username"],
            email=user["email"],
            real_name=user.get("real_name"),
            phone=user.get("phone"),
            organization_id=(
                user["organization_id"]
                if isinstance(user.get("organization_id"), UUID)
                else (UUID(str(user["organization_id"])) if user.get("organization_id") else None)
            ),
            department_id=(
                user["department_id"]
                if isinstance(user.get("department_id"), UUID)
                else (UUID(str(user["department_id"])) if user.get("department_id") else None)
            ),
            is_superuser=user.get("is_superuser", False),
            is_active=user.get("is_active", True),
            data_permission_level=user.get("data_permission_level", "self"),
            last_login_at=user.get("last_login_at").isoformat() if user.get("last_login_at") else None,
            created_at=user.get("created_at").isoformat() if user.get("created_at") else None,
            updated_at=user.get("updated_at").isoformat() if user.get("updated_at") else None,
        )
        for user in users
    ]


@router.get("/{user_id}", response_model=UserWithRoles)
async def get_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_permission("user:read")),
):
    """Get user by ID."""
    user_data = UserDB.get_by_id(user_id)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    roles = UserDB.get_user_roles(user_id)
    
    from ..models import RoleResponse
    
    return UserWithRoles(
        id=user_data["id"] if isinstance(user_data["id"], UUID) else UUID(str(user_data["id"])),
        username=user_data["username"],
        email=user_data["email"],
        real_name=user_data.get("real_name"),
        phone=user_data.get("phone"),
        organization_id=(
            user_data["organization_id"]
            if isinstance(user_data.get("organization_id"), UUID)
            else (UUID(str(user_data["organization_id"])) if user_data.get("organization_id") else None)
        ),
        department_id=(
            user_data["department_id"]
            if isinstance(user_data.get("department_id"), UUID)
            else (UUID(str(user_data["department_id"])) if user_data.get("department_id") else None)
        ),
        is_superuser=user_data.get("is_superuser", False),
        is_active=user_data.get("is_active", True),
        data_permission_level=user_data.get("data_permission_level", "self"),
        last_login_at=user_data.get("last_login_at").isoformat() if user_data.get("last_login_at") else None,
        created_at=user_data.get("created_at").isoformat() if user_data.get("created_at") else None,
        updated_at=user_data.get("updated_at").isoformat() if user_data.get("updated_at") else None,
        roles=[
            RoleResponse(
                id=role["id"] if isinstance(role["id"], UUID) else UUID(str(role["id"])),
                code=role["code"],
                name=role["name"],
                description=role.get("description"),
                organization_id=(
                    role["organization_id"]
                    if isinstance(role.get("organization_id"), UUID)
                    else (UUID(str(role["organization_id"])) if role.get("organization_id") else None)
                ),
                data_permission_level=role.get("data_permission_level", "self"),
                is_system=role.get("is_system", False),
                is_active=role.get("is_active", True),
                sort_order=role.get("sort_order", 0),
                created_at=role.get("created_at").isoformat() if role.get("created_at") else None,
                updated_at=role.get("updated_at").isoformat() if role.get("updated_at") else None,
            )
            for role in roles
        ],
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: CurrentUser = Depends(require_permission("user:create")),
):
    """Create a new user."""
    # Check if username already exists
    existing = UserDB.get_by_username(user_data.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )
    
    user_id = UserAdminDB.create_user(
        username=user_data.username,
        email=user_data.email,
        password=user_data.password,
        real_name=user_data.real_name,
        phone=user_data.phone,
        organization_id=user_data.organization_id,
        department_id=user_data.department_id,
        is_active=user_data.is_active,
        data_permission_level="self",  # Default permission level
    )
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )
    
    # Assign roles if provided
    if user_data.role_ids:
        UserAdminDB.assign_roles(user_id, user_data.role_ids)
    
    # Get created user
    created_user = UserDB.get_by_id(user_id)
    return UserResponse(
        id=created_user["id"] if isinstance(created_user["id"], UUID) else UUID(str(created_user["id"])),
        username=created_user["username"],
        email=created_user["email"],
        real_name=created_user.get("real_name"),
        phone=created_user.get("phone"),
        organization_id=(
            created_user["organization_id"]
            if isinstance(created_user.get("organization_id"), UUID)
            else (UUID(str(created_user["organization_id"])) if created_user.get("organization_id") else None)
        ),
        department_id=(
            created_user["department_id"]
            if isinstance(created_user.get("department_id"), UUID)
            else (UUID(str(created_user["department_id"])) if created_user.get("department_id") else None)
        ),
        is_superuser=created_user.get("is_superuser", False),
        is_active=created_user.get("is_active", True),
        data_permission_level=created_user.get("data_permission_level", "self"),
        last_login_at=created_user.get("last_login_at").isoformat() if created_user.get("last_login_at") else None,
        created_at=created_user.get("created_at").isoformat() if created_user.get("created_at") else None,
        updated_at=created_user.get("updated_at").isoformat() if created_user.get("updated_at") else None,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    current_user: CurrentUser = Depends(require_permission("user:update")),
):
    """Update user information."""
    # Check if user exists
    existing = UserDB.get_by_id(user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Prevent updating superuser unless current user is superuser
    if existing.get("is_superuser") and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update superuser",
        )
    
    success = UserAdminDB.update_user(
        user_id=user_id,
        username=user_data.username,
        email=user_data.email,
        real_name=user_data.real_name,
        phone=user_data.phone,
        organization_id=user_data.organization_id,
        department_id=user_data.department_id,
        is_active=user_data.is_active,
        data_permission_level=user_data.data_permission_level,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user",
        )
    
    # Get updated user
    updated_user = UserDB.get_by_id(user_id)
    return UserResponse(
        id=updated_user["id"] if isinstance(updated_user["id"], UUID) else UUID(str(updated_user["id"])),
        username=updated_user["username"],
        email=updated_user["email"],
        real_name=updated_user.get("real_name"),
        phone=updated_user.get("phone"),
        organization_id=(
            updated_user["organization_id"]
            if isinstance(updated_user.get("organization_id"), UUID)
            else (UUID(str(updated_user["organization_id"])) if updated_user.get("organization_id") else None)
        ),
        department_id=(
            updated_user["department_id"]
            if isinstance(updated_user.get("department_id"), UUID)
            else (UUID(str(updated_user["department_id"])) if updated_user.get("department_id") else None)
        ),
        is_superuser=updated_user.get("is_superuser", False),
        is_active=updated_user.get("is_active", True),
        data_permission_level=updated_user.get("data_permission_level", "self"),
        last_login_at=updated_user.get("last_login_at").isoformat() if updated_user.get("last_login_at") else None,
        created_at=updated_user.get("created_at").isoformat() if updated_user.get("created_at") else None,
        updated_at=updated_user.get("updated_at").isoformat() if updated_user.get("updated_at") else None,
    )


@router.post("/{user_id}/change-password")
async def change_user_password(
    user_id: UUID,
    request: ChangePasswordRequest,
    current_user: CurrentUser = Depends(require_permission("user:update")),
):
    """Change user password."""
    # Check if user exists
    existing = UserDB.get_by_id(user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    success = UserAdminDB.change_password(user_id, request.new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password",
        )
    
    return {"message": "Password changed successfully"}


@router.post("/{user_id}/assign-roles")
async def assign_user_roles(
    user_id: UUID,
    role_ids: List[UUID],
    current_user: CurrentUser = Depends(require_permission("user:update")),
):
    """Assign roles to a user."""
    """Assign roles to a user."""
    # Check if user exists
    existing = UserDB.get_by_id(user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    success = UserAdminDB.assign_roles(user_id, role_ids)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign roles",
        )
    
    return {"message": "Roles assigned successfully"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_permission("user:delete")),
):
    """Delete a user (soft delete)."""
    # Check if user exists
    existing = UserDB.get_by_id(user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Prevent deleting superuser
    if existing.get("is_superuser"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete superuser",
        )
    
    success = UserAdminDB.delete_user(user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user",
        )
    
    return {"message": "User deleted successfully"}

