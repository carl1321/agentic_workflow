# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Authentication routes.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .dependencies import CurrentUser, get_current_user
from .db import TokenBlacklist, UserDB
from .jwt import create_access_token, decode_token, get_token_jti
from .models import LoginRequest, LoginResponse, TokenResponse, UserInfoResponse
from .password import verify_password
from .crypto import decrypt_password, get_public_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

security = HTTPBearer()


@router.get("/public-key")
async def get_public_key_endpoint():
    """
    Get RSA public key for client-side password encryption.
    
    This endpoint returns the public key that clients should use to encrypt
    passwords before sending them to the login endpoint.
    """
    try:
        public_key = get_public_key()
        return {
            "public_key": public_key,
            "algorithm": "RSA",
            "key_size": 2048,
        }
    except Exception as e:
        logger.error(f"Error getting public key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve public key",
        )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    User login endpoint.
    
    Returns JWT token and user information.
    """
    # Get user by username
    user_data = UserDB.get_by_username(request.username)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    # Check if user is active
    if not user_data.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Decrypt password if it's encrypted (base64 encoded)
    password = request.password
    # Check if password looks like base64-encoded encrypted data (starts with common base64 chars and is longer)
    # Simple heuristic: if it's base64 and longer than typical plaintext passwords, try decrypting
    if len(password) > 100 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in password):
        decrypted = decrypt_password(password)
        if decrypted is not None:
            password = decrypted
            logger.debug("Password decrypted successfully")
        else:
            # If decryption fails but it looks encrypted, reject
            logger.warning("Failed to decrypt password, treating as invalid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )
    
    # Verify password
    password_hash = user_data.get("password_hash")
    if not password_hash or not verify_password(password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    # Get user roles and permissions
    raw_id = user_data["id"]
    # psycopg with dict_row may already return UUID objects, so handle both cases
    user_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
    roles = UserDB.get_user_roles(user_id)
    # Normalize datetime fields to ISO strings for Pydantic models
    def _normalize_role(role: dict) -> dict:
      normalized = {}
      for k, v in role.items():
          if isinstance(v, datetime):
              normalized[k] = v.isoformat()
          else:
              normalized[k] = v
      return normalized
    roles = [_normalize_role(r) for r in roles]
    permissions = UserDB.get_user_permissions(user_id)
    
    # Create access token
    token = create_access_token(
        user_id=str(user_id),
        username=user_data["username"],
        is_superuser=user_data.get("is_superuser", False),
    )
    
    # Update last login time
    UserDB.update_last_login(user_id)
    
    # Build user response
    user_response = {
        "id": user_id,
        "username": user_data["username"],
        "email": user_data["email"],
        "real_name": user_data.get("real_name"),
        "is_superuser": user_data.get("is_superuser", False),
        "roles": roles,
        "permissions": permissions,
        "organization_id": user_data.get("organization_id"),
        "department_id": user_data.get("department_id"),
        "data_permission_level": user_data.get("data_permission_level", "self"),
        "is_active": user_data.get("is_active", True),
        "last_login_at": datetime.utcnow().isoformat() if user_data.get("last_login_at") else None,
        "created_at": user_data.get("created_at").isoformat() if user_data.get("created_at") else None,
        "updated_at": user_data.get("updated_at").isoformat() if user_data.get("updated_at") else None,
    }
    
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=user_response,
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    User logout endpoint.
    Adds token to blacklist.
    """
    token = credentials.credentials
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    
    # Get token JTI and expiration
    token_jti = get_token_jti(token)
    user_id_str = payload.get("sub")
    expires_at = datetime.fromtimestamp(payload.get("exp", 0))
    
    if token_jti and user_id_str:
        try:
            user_id = UUID(user_id_str)
            TokenBlacklist.add_token(token_jti, user_id, expires_at)
        except Exception as e:
            logger.error(f"Error adding token to blacklist: {e}")
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get current user information including roles, permissions, and menus.
    """
    # Get user data
    user_data = UserDB.get_by_id(current_user.id)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Get user roles
    roles_data = UserDB.get_user_roles(current_user.id)
    
    # Get user permissions
    permissions = UserDB.get_user_permissions(current_user.id)
    
    # Get user menus (tree structure)
    menus_data = UserDB.get_user_menus(current_user.id)
    
    # Build menu tree
    def build_menu_tree(menus: list, parent_id: Optional[UUID] = None) -> list:
        """Build menu tree structure."""
        result = []
        for menu in menus:
            if menu.get("parent_id") == (str(parent_id) if parent_id else None):
                menu_dict = {
                    # psycopg 可能已经返回 UUID 对象，这里统一兼容
                    "id": menu["id"] if isinstance(menu["id"], UUID) else UUID(str(menu["id"])),
                    "code": menu["code"],
                    "name": menu["name"],
                    "path": menu.get("path"),
                    "icon": menu.get("icon"),
                    "component": menu.get("component"),
                    "menu_type": menu.get("menu_type", "menu"),
                    "permission_code": menu.get("permission_code"),
                    "is_visible": menu.get("is_visible", True),
                    "is_system": menu.get("is_system", False),
                    "sort_order": menu.get("sort_order", 0),
                    # 这些字段在 Pydantic MenuResponse 中是必填，这里统一补齐（允许为 None）
                    "created_at": menu.get("created_at").isoformat() if menu.get("created_at") else None,
                    "updated_at": menu.get("updated_at").isoformat() if menu.get("updated_at") else None,
                    "parent_id": (
                        menu["parent_id"]
                        if isinstance(menu.get("parent_id"), UUID)
                        else (UUID(str(menu["parent_id"])) if menu.get("parent_id") else None)
                    ),
                    "children": build_menu_tree(
                        menus,
                        menu["id"] if isinstance(menu["id"], UUID) else UUID(str(menu["id"])),
                    ),
                }
                result.append(menu_dict)
        return sorted(result, key=lambda x: x["sort_order"])
    
    menus_tree = build_menu_tree(menus_data)
    
    # Get organization and department info
    organization = None
    department = None
    
    if user_data.get("organization_id"):
        from .admin.organizations import OrganizationDB
        raw_org_id = user_data["organization_id"]
        org_uuid = raw_org_id if isinstance(raw_org_id, UUID) else UUID(str(raw_org_id))
        org_data = OrganizationDB.get_by_id(org_uuid)
        if org_data:
            organization = {
                "id": (
                    org_data["id"]
                    if isinstance(org_data["id"], UUID)
                    else UUID(str(org_data["id"]))
                ),
                "code": org_data["code"],
                "name": org_data["name"],
                "description": org_data.get("description"),
                "parent_id": (
                    org_data["parent_id"]
                    if isinstance(org_data.get("parent_id"), UUID)
                    else (UUID(str(org_data["parent_id"])) if org_data.get("parent_id") else None)
                ),
                "is_active": org_data.get("is_active", True),
                "sort_order": org_data.get("sort_order", 0),
                "created_at": org_data.get("created_at").isoformat() if org_data.get("created_at") else None,
                "updated_at": org_data.get("updated_at").isoformat() if org_data.get("updated_at") else None,
                "children": [],
            }
    
    if user_data.get("department_id"):
        from .admin.departments import DepartmentDB
        raw_dept_id = user_data["department_id"]
        dept_uuid = raw_dept_id if isinstance(raw_dept_id, UUID) else UUID(str(raw_dept_id))
        dept_data = DepartmentDB.get_by_id(dept_uuid)
        if dept_data:
            department = {
                "id": (
                    dept_data["id"]
                    if isinstance(dept_data["id"], UUID)
                    else UUID(str(dept_data["id"]))
                ),
                "code": dept_data["code"],
                "name": dept_data["name"],
                "organization_id": (
                    dept_data["organization_id"]
                    if isinstance(dept_data["organization_id"], UUID)
                    else UUID(str(dept_data["organization_id"]))
                ),
                "description": dept_data.get("description"),
                "parent_id": (
                    dept_data["parent_id"]
                    if isinstance(dept_data.get("parent_id"), UUID)
                    else (UUID(str(dept_data["parent_id"])) if dept_data.get("parent_id") else None)
                ),
                "manager_id": (
                    dept_data["manager_id"]
                    if isinstance(dept_data.get("manager_id"), UUID)
                    else (UUID(str(dept_data["manager_id"])) if dept_data.get("manager_id") else None)
                ),
                "is_active": dept_data.get("is_active", True),
                "sort_order": dept_data.get("sort_order", 0),
                "created_at": dept_data.get("created_at").isoformat() if dept_data.get("created_at") else None,
                "updated_at": dept_data.get("updated_at").isoformat() if dept_data.get("updated_at") else None,
                "children": [],
            }
    
    return UserInfoResponse(
        id=current_user.id,
        username=current_user.username,
        email=user_data["email"],
        real_name=current_user.real_name,
        is_superuser=current_user.is_superuser,
        roles=[
            {
                "id": (
                    role["id"]
                    if isinstance(role["id"], UUID)
                    else UUID(str(role["id"]))
                ),
                "code": role["code"],
                "name": role["name"],
                "description": role.get("description"),
                "organization_id": (
                    role["organization_id"]
                    if isinstance(role.get("organization_id"), UUID)
                    else (UUID(str(role["organization_id"])) if role.get("organization_id") else None)
                ),
                "data_permission_level": role.get("data_permission_level", "self"),
                "is_system": role.get("is_system", False),
                "is_active": role.get("is_active", True),
                "sort_order": role.get("sort_order", 0),
                "created_at": role.get("created_at").isoformat() if role.get("created_at") else None,
                "updated_at": role.get("updated_at").isoformat() if role.get("updated_at") else None,
            }
            for role in roles_data
        ],
        permissions=permissions,
        menus=menus_tree,
        organization=organization,
        department=department,
        data_permission_level=current_user.data_permission_level,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Refresh access token.
    """
    # Create new token
    token = create_access_token(
        user_id=str(current_user.id),
        username=current_user.username,
        is_superuser=current_user.is_superuser,
    )
    
    return TokenResponse(access_token=token, token_type="bearer")

