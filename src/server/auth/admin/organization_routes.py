# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Organization management API routes.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import CurrentUser, require_permission
from ..models import OrganizationCreate, OrganizationResponse, OrganizationBase
from .organizations import OrganizationDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/organizations", tags=["admin", "organizations"])


def build_org_tree(orgs: list, parent_id: Optional[UUID] = None) -> list:
    """Build organization tree structure."""
    result = []
    for org in orgs:
        raw_parent = org.get("parent_id")
        org_parent_id = (
            raw_parent
            if isinstance(raw_parent, UUID)
            else (UUID(str(raw_parent)) if raw_parent else None)
        )
        if org_parent_id == parent_id:
            org_dict = OrganizationResponse(
                id=org["id"] if isinstance(org["id"], UUID) else UUID(str(org["id"])),
                code=org["code"],
                name=org["name"],
                description=org.get("description"),
                parent_id=org_parent_id,
                is_active=org.get("is_active", True),
                sort_order=org.get("sort_order", 0),
                created_at=org.get("created_at").isoformat() if org.get("created_at") else None,
                updated_at=org.get("updated_at").isoformat() if org.get("updated_at") else None,
                children=build_org_tree(
                    orgs,
                    org["id"] if isinstance(org["id"], UUID) else UUID(str(org["id"])),
                ),
            )
            result.append(org_dict)
    return sorted(result, key=lambda x: x.sort_order)


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    include_inactive: bool = Query(False),
    current_user: CurrentUser = Depends(require_permission("organization:read")),
):
    """List all organizations as a tree structure."""
    orgs = OrganizationDB.list_all(include_inactive=include_inactive)
    orgs_tree = build_org_tree(orgs)
    return orgs_tree


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_permission("organization:read")),
):
    """Get organization by ID."""
    org_data = OrganizationDB.get_by_id(org_id)
    if not org_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Get all orgs to build tree
    all_orgs = OrganizationDB.list_all(include_inactive=True)
    orgs_tree = build_org_tree(all_orgs)
    
    # Find the org in tree
    def find_org(orgs_list: List[OrganizationResponse], target_id: UUID) -> Optional[OrganizationResponse]:
        for org in orgs_list:
            if org.id == target_id:
                return org
            if org.children:
                found = find_org(org.children, target_id)
                if found:
                    return found
        return None
    
    org = find_org(orgs_tree, org_id)
    if not org:
        # Return flat org if not found in tree
        return OrganizationResponse(
            id=UUID(org_data["id"]),
            code=org_data["code"],
            name=org_data["name"],
            description=org_data.get("description"),
            parent_id=UUID(org_data["parent_id"]) if org_data.get("parent_id") else None,
            is_active=org_data.get("is_active", True),
            sort_order=org_data.get("sort_order", 0),
            created_at=org_data.get("created_at").isoformat() if org_data.get("created_at") else None,
            updated_at=org_data.get("updated_at").isoformat() if org_data.get("updated_at") else None,
            children=[],
        )
    
    return org


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    org_data: OrganizationCreate,
    current_user: CurrentUser = Depends(require_permission("organization:create")),
):
    """Create a new organization."""
    # Check if code already exists
    existing = OrganizationDB.get_by_code(org_data.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization code already exists",
        )
    
    org_id = OrganizationDB.create(
        code=org_data.code,
        name=org_data.name,
        description=org_data.description,
        parent_id=org_data.parent_id,
        is_active=org_data.is_active,
    )
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create organization",
        )
    
    created = OrganizationDB.get_by_id(org_id)
    return OrganizationResponse(
        id=UUID(created["id"]),
        code=created["code"],
        name=created["name"],
        description=created.get("description"),
        parent_id=UUID(created["parent_id"]) if created.get("parent_id") else None,
        is_active=created.get("is_active", True),
        sort_order=created.get("sort_order", 0),
        created_at=created.get("created_at").isoformat() if created.get("created_at") else None,
        updated_at=created.get("updated_at").isoformat() if created.get("updated_at") else None,
        children=[],
    )


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: UUID,
    org_data: OrganizationBase,
    current_user: CurrentUser = Depends(require_permission("organization:update")),
):
    """Update organization information."""
    existing = OrganizationDB.get_by_id(org_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    success = OrganizationDB.update(
        org_id=org_id,
        code=org_data.code,
        name=org_data.name,
        description=org_data.description,
        parent_id=org_data.parent_id,
        is_active=org_data.is_active,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update organization",
        )
    
    updated = OrganizationDB.get_by_id(org_id)
    return OrganizationResponse(
        id=UUID(updated["id"]),
        code=updated["code"],
        name=updated["name"],
        description=updated.get("description"),
        parent_id=UUID(updated["parent_id"]) if updated.get("parent_id") else None,
        is_active=updated.get("is_active", True),
        sort_order=updated.get("sort_order", 0),
        created_at=updated.get("created_at").isoformat() if updated.get("created_at") else None,
        updated_at=updated.get("updated_at").isoformat() if updated.get("updated_at") else None,
        children=[],
    )


@router.delete("/{org_id}")
async def delete_organization(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_permission("organization:delete")),
):
    """Delete an organization."""
    existing = OrganizationDB.get_by_id(org_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    success = OrganizationDB.delete(org_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete organization",
        )
    
    return {"message": "Organization deleted successfully"}

