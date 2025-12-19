# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Role management API routes.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import CurrentUser, require_permission
from ..models import RoleCreate, RoleResponse, RoleUpdate
from .roles import RoleAdminDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/roles", tags=["admin", "roles"])


@router.get("", response_model=List[RoleResponse])
async def list_roles(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: Optional[UUID] = Query(None),
    is_active: Optional[bool] = Query(None),
    include_system: bool = Query(False),
    current_user: CurrentUser = Depends(require_permission("role:read")),
):
    """List roles with filters."""
    roles = RoleAdminDB.list_roles(
        limit=limit,
        offset=offset,
        organization_id=organization_id,
        is_active=is_active,
        include_system=include_system,
    )
    
    return [
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
    ]


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: UUID,
    current_user: CurrentUser = Depends(require_permission("role:read")),
):
    """Get role by ID."""
    role_data = RoleAdminDB.get_by_id(role_id)
    if not role_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    return RoleResponse(
        id=role_data["id"] if isinstance(role_data["id"], UUID) else UUID(str(role_data["id"])),
        code=role_data["code"],
        name=role_data["name"],
        description=role_data.get("description"),
        organization_id=(
            role_data["organization_id"]
            if isinstance(role_data.get("organization_id"), UUID)
            else (UUID(str(role_data["organization_id"])) if role_data.get("organization_id") else None)
        ),
        data_permission_level=role_data.get("data_permission_level", "self"),
        is_system=role_data.get("is_system", False),
        is_active=role_data.get("is_active", True),
        sort_order=role_data.get("sort_order", 0),
        created_at=role_data.get("created_at").isoformat() if role_data.get("created_at") else None,
        updated_at=role_data.get("updated_at").isoformat() if role_data.get("updated_at") else None,
    )


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_data: RoleCreate,
    current_user: CurrentUser = Depends(require_permission("role:create")),
):
    """Create a new role."""
    # Check if code already exists
    existing = RoleAdminDB.get_by_id(UUID("00000000-0000-0000-0000-000000000000"))  # Dummy check
    # Actually check by code
    roles = RoleAdminDB.list_roles(limit=1000, include_system=True)
    if any(r["code"] == role_data.code for r in roles):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role code already exists",
        )
    
    role_id = RoleAdminDB.create_role(
        code=role_data.code,
        name=role_data.name,
        description=role_data.description,
        organization_id=role_data.organization_id,
        data_permission_level=role_data.data_permission_level,
        is_active=role_data.is_active,
    )
    
    if not role_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create role",
        )
    
    # Assign permissions if provided
    if role_data.permission_ids:
        RoleAdminDB.assign_permissions(role_id, role_data.permission_ids)
    
    # Assign menus if provided
    if role_data.menu_ids:
        RoleAdminDB.assign_menus(role_id, role_data.menu_ids)
    
    # Get created role
    created_role = RoleAdminDB.get_by_id(role_id)
    return RoleResponse(
        id=created_role["id"] if isinstance(created_role["id"], UUID) else UUID(str(created_role["id"])),
        code=created_role["code"],
        name=created_role["name"],
        description=created_role.get("description"),
        organization_id=(
            created_role["organization_id"]
            if isinstance(created_role.get("organization_id"), UUID)
            else (UUID(str(created_role["organization_id"])) if created_role.get("organization_id") else None)
        ),
        data_permission_level=created_role.get("data_permission_level", "self"),
        is_system=created_role.get("is_system", False),
        is_active=created_role.get("is_active", True),
        sort_order=created_role.get("sort_order", 0),
        created_at=created_role.get("created_at").isoformat() if created_role.get("created_at") else None,
        updated_at=created_role.get("updated_at").isoformat() if created_role.get("updated_at") else None,
    )


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    role_data: RoleUpdate,
    current_user: CurrentUser = Depends(require_permission("role:update")),
):
    """Update role information."""
    # Check if role exists
    existing = RoleAdminDB.get_by_id(role_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    # Prevent updating system roles
    if existing.get("is_system"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update system role",
        )
    
    success = RoleAdminDB.update_role(
        role_id=role_id,
        code=role_data.code,
        name=role_data.name,
        description=role_data.description,
        organization_id=role_data.organization_id,
        data_permission_level=role_data.data_permission_level,
        is_active=role_data.is_active,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update role",
        )
    
    # Get updated role
    updated_role = RoleAdminDB.get_by_id(role_id)
    return RoleResponse(
        id=updated_role["id"] if isinstance(updated_role["id"], UUID) else UUID(str(updated_role["id"])),
        code=updated_role["code"],
        name=updated_role["name"],
        description=updated_role.get("description"),
        organization_id=(
            updated_role["organization_id"]
            if isinstance(updated_role.get("organization_id"), UUID)
            else (UUID(str(updated_role["organization_id"])) if updated_role.get("organization_id") else None)
        ),
        data_permission_level=updated_role.get("data_permission_level", "self"),
        is_system=updated_role.get("is_system", False),
        is_active=updated_role.get("is_active", True),
        sort_order=updated_role.get("sort_order", 0),
        created_at=updated_role.get("created_at").isoformat() if updated_role.get("created_at") else None,
        updated_at=updated_role.get("updated_at").isoformat() if updated_role.get("updated_at") else None,
    )


@router.post("/{role_id}/assign-permissions")
async def assign_role_permissions(
    role_id: UUID,
    permission_ids: List[UUID],
    current_user: CurrentUser = Depends(require_permission("role:update")),
):
    """Assign permissions to a role."""
    # Check if role exists
    existing = RoleAdminDB.get_by_id(role_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    success = RoleAdminDB.assign_permissions(role_id, permission_ids)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign permissions",
        )
    
    return {"message": "Permissions assigned successfully"}


@router.post("/{role_id}/assign-menus")
async def assign_role_menus(
    role_id: UUID,
    menu_ids: List[UUID],
    current_user: CurrentUser = Depends(require_permission("role:update")),
):
    """Assign menus to a role."""
    # Check if role exists
    existing = RoleAdminDB.get_by_id(role_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    success = RoleAdminDB.assign_menus(role_id, menu_ids)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign menus",
        )
    
    return {"message": "Menus assigned successfully"}


@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: UUID,
    current_user: CurrentUser = Depends(require_permission("role:read")),
):
    """Get permissions assigned to a role."""
    permissions = RoleAdminDB.get_role_permissions(role_id)
    
    from ..models import PermissionResponse
    
    return [
        PermissionResponse(
            id=perm["id"] if isinstance(perm["id"], UUID) else UUID(str(perm["id"])),
            code=perm["code"],
            name=perm["name"],
            resource=perm["resource"],
            action=perm["action"],
            description=perm.get("description"),
            is_system=perm.get("is_system", False),
            created_at=perm.get("created_at").isoformat() if perm.get("created_at") else None,
        )
        for perm in permissions
    ]


@router.get("/{role_id}/menus")
async def get_role_menus(
    role_id: UUID,
    current_user: CurrentUser = Depends(require_permission("role:read")),
):
    """Get menus assigned to a role."""
    menus = RoleAdminDB.get_role_menus(role_id)

    from ..models import MenuResponse

    def _as_uuid(value):
        if isinstance(value, UUID):
            return value
        return UUID(str(value)) if value is not None else None

    def build_menu_tree(menus_list: list, parent_id: Optional[UUID] = None) -> list:
        """Build menu tree structure."""
        result = []
        for menu in menus_list:
            raw_parent = menu.get("parent_id")
            menu_parent_id = _as_uuid(raw_parent) if raw_parent else None
            if menu_parent_id == parent_id:
                menu_id = _as_uuid(menu["id"])
                menu_dict = MenuResponse(
                    id=menu_id,
                    code=menu["code"],
                    name=menu["name"],
                    path=menu.get("path"),
                    icon=menu.get("icon"),
                    component=menu.get("component"),
                    menu_type=menu.get("menu_type", "menu"),
                    permission_code=menu.get("permission_code"),
                    is_visible=menu.get("is_visible", True),
                    parent_id=menu_parent_id,
                    is_system=menu.get("is_system", False),
                    sort_order=menu.get("sort_order", 0),
                    created_at=menu.get("created_at").isoformat() if menu.get("created_at") else None,
                    updated_at=menu.get("updated_at").isoformat() if menu.get("updated_at") else None,
                    children=build_menu_tree(menus_list, menu_id),
                )
                result.append(menu_dict)
        return sorted(result, key=lambda x: x.sort_order)

    menus_tree = build_menu_tree(menus)
    return menus_tree


@router.delete("/{role_id}")
async def delete_role(
    role_id: UUID,
    current_user: CurrentUser = Depends(require_permission("role:delete")),
):
    """Delete a role (only non-system roles can be deleted)."""
    # Check if role exists
    existing = RoleAdminDB.get_by_id(role_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    # Prevent deleting system roles
    if existing.get("is_system"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete system role",
        )
    
    success = RoleAdminDB.delete_role(role_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete role",
        )
    
    return {"message": "Role deleted successfully"}

