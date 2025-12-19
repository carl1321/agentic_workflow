# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Menu management API routes.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import CurrentUser, require_permission
from ..models import MenuCreate, MenuResponse, MenuUpdate
from .menus import MenuAdminDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/menus", tags=["admin", "menus"])


def build_menu_tree(menus: list, parent_id: Optional[UUID] = None) -> list:
    """Build menu tree structure."""
    result = []
    for menu in menus:
        raw_parent = menu.get("parent_id")
        menu_parent_id = (
            raw_parent
            if isinstance(raw_parent, UUID)
            else (UUID(str(raw_parent)) if raw_parent else None)
        )
        if menu_parent_id == parent_id:
            menu_dict = MenuResponse(
                id=menu["id"] if isinstance(menu["id"], UUID) else UUID(str(menu["id"])),
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
                children=build_menu_tree(
                    menus,
                    menu["id"] if isinstance(menu["id"], UUID) else UUID(str(menu["id"])),
                ),
            )
            result.append(menu_dict)
    return sorted(result, key=lambda x: x.sort_order)


@router.get("", response_model=List[MenuResponse])
async def list_menus(
    include_system: bool = Query(True),
    current_user: CurrentUser = Depends(require_permission("menu:read")),
):
    """List all menus as a tree structure."""
    menus = MenuAdminDB.list_all(include_system=include_system)
    menus_tree = build_menu_tree(menus)
    return menus_tree


@router.get("/{menu_id}", response_model=MenuResponse)
async def get_menu(
    menu_id: UUID,
    current_user: CurrentUser = Depends(require_permission("menu:read")),
):
    """Get menu by ID."""
    menu_data = MenuAdminDB.get_by_id(menu_id)
    if not menu_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu not found",
        )
    
    # Get all menus to build tree
    all_menus = MenuAdminDB.list_all(include_system=True)
    menus_tree = build_menu_tree(all_menus)
    
    # Find the menu in tree
    def find_menu(menus_list: List[MenuResponse], target_id: UUID) -> Optional[MenuResponse]:
        for menu in menus_list:
            if menu.id == target_id:
                return menu
            if menu.children:
                found = find_menu(menu.children, target_id)
                if found:
                    return found
        return None
    
    menu = find_menu(menus_tree, menu_id)
    if not menu:
        # Return flat menu if not found in tree
        return MenuResponse(
            id=UUID(menu_data["id"]),
            code=menu_data["code"],
            name=menu_data["name"],
            path=menu_data.get("path"),
            icon=menu_data.get("icon"),
            component=menu_data.get("component"),
            menu_type=menu_data.get("menu_type", "menu"),
            permission_code=menu_data.get("permission_code"),
            is_visible=menu_data.get("is_visible", True),
            parent_id=UUID(menu_data["parent_id"]) if menu_data.get("parent_id") else None,
            is_system=menu_data.get("is_system", False),
            sort_order=menu_data.get("sort_order", 0),
            created_at=menu_data.get("created_at").isoformat() if menu_data.get("created_at") else None,
            updated_at=menu_data.get("updated_at").isoformat() if menu_data.get("updated_at") else None,
            children=[],
        )
    
    return menu


@router.post("", response_model=MenuResponse, status_code=status.HTTP_201_CREATED)
async def create_menu(
    menu_data: MenuCreate,
    current_user: CurrentUser = Depends(require_permission("menu:create")),
):
    """Create a new menu."""
    menu_id = MenuAdminDB.create_menu(
        code=menu_data.code,
        name=menu_data.name,
        path=menu_data.path,
        icon=menu_data.icon,
        component=menu_data.component,
        menu_type=menu_data.menu_type,
        permission_code=menu_data.permission_code,
        is_visible=menu_data.is_visible,
        parent_id=menu_data.parent_id,
    )
    
    if not menu_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create menu",
        )
    
    # Get created menu
    created_menu = MenuAdminDB.get_by_id(menu_id)
    return MenuResponse(
        id=UUID(created_menu["id"]),
        code=created_menu["code"],
        name=created_menu["name"],
        path=created_menu.get("path"),
        icon=created_menu.get("icon"),
        component=created_menu.get("component"),
        menu_type=created_menu.get("menu_type", "menu"),
        permission_code=created_menu.get("permission_code"),
        is_visible=created_menu.get("is_visible", True),
        parent_id=UUID(created_menu["parent_id"]) if created_menu.get("parent_id") else None,
        is_system=created_menu.get("is_system", False),
        sort_order=created_menu.get("sort_order", 0),
        created_at=created_menu.get("created_at").isoformat() if created_menu.get("created_at") else None,
        updated_at=created_menu.get("updated_at").isoformat() if created_menu.get("updated_at") else None,
        children=[],
    )


@router.put("/{menu_id}", response_model=MenuResponse)
async def update_menu(
    menu_id: UUID,
    menu_data: MenuUpdate,
    current_user: CurrentUser = Depends(require_permission("menu:update")),
):
    """Update menu information."""
    # Check if menu exists
    existing = MenuAdminDB.get_by_id(menu_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu not found",
        )
    
    # Prevent updating system menus
    if existing.get("is_system"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update system menu",
        )
    
    success = MenuAdminDB.update_menu(
        menu_id=menu_id,
        code=menu_data.code,
        name=menu_data.name,
        path=menu_data.path,
        icon=menu_data.icon,
        component=menu_data.component,
        menu_type=menu_data.menu_type,
        permission_code=menu_data.permission_code,
        is_visible=menu_data.is_visible,
        parent_id=menu_data.parent_id,
        sort_order=menu_data.sort_order,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update menu",
        )
    
    # Get updated menu
    updated_menu = MenuAdminDB.get_by_id(menu_id)
    return MenuResponse(
        id=UUID(updated_menu["id"]),
        code=updated_menu["code"],
        name=updated_menu["name"],
        path=updated_menu.get("path"),
        icon=updated_menu.get("icon"),
        component=updated_menu.get("component"),
        menu_type=updated_menu.get("menu_type", "menu"),
        permission_code=updated_menu.get("permission_code"),
        is_visible=updated_menu.get("is_visible", True),
        parent_id=UUID(updated_menu["parent_id"]) if updated_menu.get("parent_id") else None,
        is_system=updated_menu.get("is_system", False),
        sort_order=updated_menu.get("sort_order", 0),
        created_at=updated_menu.get("created_at").isoformat() if updated_menu.get("created_at") else None,
        updated_at=updated_menu.get("updated_at").isoformat() if updated_menu.get("updated_at") else None,
        children=[],
    )


@router.delete("/{menu_id}")
async def delete_menu(
    menu_id: UUID,
    current_user: CurrentUser = Depends(require_permission("menu:delete")),
):
    """Delete a menu (only non-system menus can be deleted)."""
    # Check if menu exists
    existing = MenuAdminDB.get_by_id(menu_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu not found",
        )
    
    # Prevent deleting system menus
    if existing.get("is_system"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete system menu",
        )
    
    success = MenuAdminDB.delete_menu(menu_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete menu",
        )
    
    return {"message": "Menu deleted successfully"}

