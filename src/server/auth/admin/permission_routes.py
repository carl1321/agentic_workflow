# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Permission management API routes.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import CurrentUser, require_permission
from ..models import PermissionCreate, PermissionResponse
from .permissions import PermissionAdminDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/permissions", tags=["admin", "permissions"])


@router.get("", response_model=List[PermissionResponse])
async def list_permissions(
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    resource: Optional[str] = Query(None),
    include_system: bool = Query(True),
    current_user: CurrentUser = Depends(require_permission("permission:read")),
):
    """List permissions with filters."""
    permissions = PermissionAdminDB.list_permissions(
        limit=limit,
        offset=offset,
        resource=resource,
        include_system=include_system,
    )
    
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


@router.get("/{permission_id}", response_model=PermissionResponse)
async def get_permission(
    permission_id: UUID,
    current_user: CurrentUser = Depends(require_permission("permission:read")),
):
    """Get permission by ID."""
    perm_data = PermissionAdminDB.get_by_id(permission_id)
    if not perm_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )
    
    return PermissionResponse(
        id=perm_data["id"] if isinstance(perm_data["id"], UUID) else UUID(str(perm_data["id"])),
        code=perm_data["code"],
        name=perm_data["name"],
        resource=perm_data["resource"],
        action=perm_data["action"],
        description=perm_data.get("description"),
        is_system=perm_data.get("is_system", False),
        created_at=perm_data.get("created_at").isoformat() if perm_data.get("created_at") else None,
    )


@router.post("", response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
async def create_permission(
    perm_data: PermissionCreate,
    current_user: CurrentUser = Depends(require_permission("permission:create")),
):
    """Create a new permission."""
    # Check if code already exists
    existing = PermissionAdminDB.get_by_code(perm_data.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permission code already exists",
        )
    
    perm_id = PermissionAdminDB.create_permission(
        code=perm_data.code,
        name=perm_data.name,
        resource=perm_data.resource,
        action=perm_data.action,
        description=perm_data.description,
    )
    
    if not perm_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create permission",
        )
    
    # Get created permission
    created_perm = PermissionAdminDB.get_by_id(perm_id)
    return PermissionResponse(
        id=UUID(created_perm["id"]),
        code=created_perm["code"],
        name=created_perm["name"],
        resource=created_perm["resource"],
        action=created_perm["action"],
        description=created_perm.get("description"),
        is_system=created_perm.get("is_system", False),
        created_at=created_perm.get("created_at").isoformat() if created_perm.get("created_at") else None,
    )

