# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Department management API routes.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import CurrentUser, require_permission
from ..models import DepartmentCreate, DepartmentResponse, DepartmentBase, DepartmentUpdate
from .departments import DepartmentDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/departments", tags=["admin", "departments"])


def build_dept_tree(depts: list, parent_id: Optional[UUID] = None) -> list:
    """Build department tree structure."""
    result = []
    for dept in depts:
        raw_parent = dept.get("parent_id")
        dept_parent_id = (
            raw_parent
            if isinstance(raw_parent, UUID)
            else (UUID(str(raw_parent)) if raw_parent else None)
        )
        if dept_parent_id == parent_id:
            dept_dict = DepartmentResponse(
                id=dept["id"] if isinstance(dept["id"], UUID) else UUID(str(dept["id"])),
                code=dept["code"],
                name=dept["name"],
                organization_id=(
                    dept["organization_id"]
                    if isinstance(dept["organization_id"], UUID)
                    else UUID(str(dept["organization_id"]))
                ),
                description=dept.get("description"),
                parent_id=dept_parent_id,
                manager_id=(
                    dept["manager_id"]
                    if isinstance(dept.get("manager_id"), UUID)
                    else (UUID(str(dept["manager_id"])) if dept.get("manager_id") else None)
                ),
                is_active=dept.get("is_active", True),
                sort_order=dept.get("sort_order", 0),
                created_at=dept.get("created_at").isoformat() if dept.get("created_at") else None,
                updated_at=dept.get("updated_at").isoformat() if dept.get("updated_at") else None,
                children=build_dept_tree(
                    depts,
                    dept["id"] if isinstance(dept["id"], UUID) else UUID(str(dept["id"])),
                ),
            )
            result.append(dept_dict)
    return sorted(result, key=lambda x: x.sort_order)


@router.get("", response_model=List[DepartmentResponse])
async def list_departments(
    organization_id: UUID = Query(..., description="Organization ID"),
    include_inactive: bool = Query(False),
    current_user: CurrentUser = Depends(require_permission("department:read")),
):
    """List departments by organization as a tree structure."""
    depts = DepartmentDB.list_by_organization(organization_id, include_inactive=include_inactive)
    depts_tree = build_dept_tree(depts)
    return depts_tree


@router.get("/{dept_id}", response_model=DepartmentResponse)
async def get_department(
    dept_id: UUID,
    current_user: CurrentUser = Depends(require_permission("department:read")),
):
    """Get department by ID."""
    dept_data = DepartmentDB.get_by_id(dept_id)
    if not dept_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    
    # Get all depts for the organization to build tree
    org_id = UUID(dept_data["organization_id"])
    all_depts = DepartmentDB.list_by_organization(org_id, include_inactive=True)
    depts_tree = build_dept_tree(all_depts)
    
    # Find the dept in tree
    def find_dept(depts_list: List[DepartmentResponse], target_id: UUID) -> Optional[DepartmentResponse]:
        for dept in depts_list:
            if dept.id == target_id:
                return dept
            if dept.children:
                found = find_dept(dept.children, target_id)
                if found:
                    return found
        return None
    
    dept = find_dept(depts_tree, dept_id)
    if not dept:
        # Return flat dept if not found in tree
        return DepartmentResponse(
            id=UUID(dept_data["id"]),
            code=dept_data["code"],
            name=dept_data["name"],
            organization_id=UUID(dept_data["organization_id"]),
            description=dept_data.get("description"),
            parent_id=UUID(dept_data["parent_id"]) if dept_data.get("parent_id") else None,
            manager_id=UUID(dept_data["manager_id"]) if dept_data.get("manager_id") else None,
            is_active=dept_data.get("is_active", True),
            sort_order=dept_data.get("sort_order", 0),
            created_at=dept_data.get("created_at").isoformat() if dept_data.get("created_at") else None,
            updated_at=dept_data.get("updated_at").isoformat() if dept_data.get("updated_at") else None,
            children=[],
        )
    
    return dept


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    dept_data: DepartmentCreate,
    current_user: CurrentUser = Depends(require_permission("department:create")),
):
    """Create a new department."""
    # Check if code already exists in organization
    existing = DepartmentDB.get_by_code(dept_data.code, dept_data.organization_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department code already exists in this organization",
        )
    
    dept_id = DepartmentDB.create(
        code=dept_data.code,
        name=dept_data.name,
        organization_id=dept_data.organization_id,
        description=dept_data.description,
        parent_id=dept_data.parent_id,
        manager_id=dept_data.manager_id,
        is_active=dept_data.is_active,
    )
    if not dept_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create department",
        )
    
    created = DepartmentDB.get_by_id(dept_id)
    return DepartmentResponse(
        id=created["id"] if isinstance(created["id"], UUID) else UUID(str(created["id"])),
        code=created["code"],
        name=created["name"],
        organization_id=(
            created["organization_id"]
            if isinstance(created.get("organization_id"), UUID)
            else UUID(str(created["organization_id"]))
        ),
        description=created.get("description"),
        parent_id=(
            created["parent_id"]
            if isinstance(created.get("parent_id"), UUID)
            else (UUID(str(created["parent_id"])) if created.get("parent_id") else None)
        ),
        manager_id=(
            created["manager_id"]
            if isinstance(created.get("manager_id"), UUID)
            else (UUID(str(created["manager_id"])) if created.get("manager_id") else None)
        ),
        is_active=created.get("is_active", True),
        sort_order=created.get("sort_order", 0),
        created_at=created.get("created_at").isoformat() if created.get("created_at") else None,
        updated_at=created.get("updated_at").isoformat() if created.get("updated_at") else None,
        children=[],
    )


@router.put("/{dept_id}", response_model=DepartmentResponse)
async def update_department(
    dept_id: UUID,
    dept_data: DepartmentUpdate,
    current_user: CurrentUser = Depends(require_permission("department:update")),
):
    """Update department information."""
    existing = DepartmentDB.get_by_id(dept_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    
    success = DepartmentDB.update(
        dept_id=dept_id,
        code=dept_data.code,
        name=dept_data.name,
        organization_id=dept_data.organization_id,
        description=dept_data.description,
        parent_id=dept_data.parent_id,
        manager_id=dept_data.manager_id,
        is_active=dept_data.is_active,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update department",
        )
    
    updated = DepartmentDB.get_by_id(dept_id)
    return DepartmentResponse(
        id=updated["id"] if isinstance(updated["id"], UUID) else UUID(str(updated["id"])),
        code=updated["code"],
        name=updated["name"],
        organization_id=(
            updated["organization_id"]
            if isinstance(updated["organization_id"], UUID)
            else UUID(str(updated["organization_id"]))
        ),
        description=updated.get("description"),
        parent_id=(
            updated["parent_id"]
            if isinstance(updated.get("parent_id"), UUID)
            else (UUID(str(updated["parent_id"])) if updated.get("parent_id") else None)
        ),
        manager_id=(
            updated["manager_id"]
            if isinstance(updated.get("manager_id"), UUID)
            else (UUID(str(updated["manager_id"])) if updated.get("manager_id") else None)
        ),
        is_active=updated.get("is_active", True),
        sort_order=updated.get("sort_order", 0),
        created_at=updated.get("created_at").isoformat() if updated.get("created_at") else None,
        updated_at=updated.get("updated_at").isoformat() if updated.get("updated_at") else None,
        children=[],
    )


@router.delete("/{dept_id}")
async def delete_department(
    dept_id: UUID,
    current_user: CurrentUser = Depends(require_permission("department:delete")),
):
    """Delete a department."""
    existing = DepartmentDB.get_by_id(dept_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    
    success = DepartmentDB.delete(dept_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete department",
        )
    
    return {"message": "Department deleted successfully"}

