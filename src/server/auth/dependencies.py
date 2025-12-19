# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
FastAPI dependencies for authentication and authorization.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import TokenBlacklist, UserDB
from .jwt import decode_token, get_token_jti

logger = logging.getLogger(__name__)

security = HTTPBearer()


class CurrentUser:
    """Current user object with permissions and roles."""
    
    def __init__(self, user_data: dict, roles: list, permissions: list):
        # 兼容 psycopg 返回 UUID 对象或字符串的情况
        raw_id = user_data["id"]
        self.id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
        self.username = user_data["username"]
        self.email = user_data["email"]
        self.real_name = user_data.get("real_name")
        self.is_superuser = user_data.get("is_superuser", False)
        self.organization_id = user_data.get("organization_id")
        self.department_id = user_data.get("department_id")
        self.data_permission_level = user_data.get("data_permission_level", "self")
        self.roles = roles
        self.permissions = permissions
    
    def has_permission(self, permission_code: str) -> bool:
        """Check if user has a specific permission."""
        if self.is_superuser:
            return True
        return permission_code in self.permissions
    
    def has_role(self, role_code: str) -> bool:
        """Check if user has a specific role."""
        if self.is_superuser:
            return True
        return any(role["code"] == role_code for role in self.roles)
    
    def has_any_permission(self, permission_codes: list) -> bool:
        """Check if user has any of the specified permissions."""
        if self.is_superuser:
            return True
        return any(code in self.permissions for code in permission_codes)
    
    def has_any_role(self, role_codes: list) -> bool:
        """Check if user has any of the specified roles."""
        if self.is_superuser:
            return True
        return any(role["code"] in role_codes for role in self.roles)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """
    Get current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        CurrentUser object
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    token = credentials.credentials
    
    # Decode token
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check token blacklist
    token_jti = get_token_jti(token)
    if token_jti and TokenBlacklist.is_blacklisted(token_jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user ID from token
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    user_data = UserDB.get_by_id(user_id)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user_data.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Get user roles and permissions
    roles = UserDB.get_user_roles(user_id)
    permissions = UserDB.get_user_permissions(user_id)
    
    return CurrentUser(user_data, roles, permissions)


def require_permission(permission_code: str):
    """
    Dependency factory to require a specific permission.
    
    Usage:
        @app.get("/api/users")
        async def get_users(
            user: CurrentUser = Depends(require_permission("user:read"))
        ):
            ...
    """
    async def permission_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not current_user.has_permission(permission_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission_code}",
            )
        return current_user
    
    return permission_checker


def require_any_permission(permission_codes: list):
    """Dependency factory to require any of the specified permissions."""
    async def permission_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not current_user.has_any_permission(permission_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of the following permissions required: {', '.join(permission_codes)}",
            )
        return current_user
    
    return permission_checker


def require_role(role_code: str):
    """
    Dependency factory to require a specific role.
    
    Usage:
        @app.get("/api/admin/users")
        async def get_users(
            user: CurrentUser = Depends(require_role("admin"))
        ):
            ...
    """
    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not current_user.has_role(role_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role_code}",
            )
        return current_user
    
    return role_checker


def require_any_role(role_codes: list):
    """Dependency factory to require any of the specified roles."""
    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not current_user.has_any_role(role_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of the following roles required: {', '.join(role_codes)}",
            )
        return current_user
    
    return role_checker


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Dependency to require admin role or superuser.
    
    Usage:
        @app.get("/api/admin/users")
        async def get_users(user: CurrentUser = Depends(require_admin)):
            ...
    """
    if not (current_user.is_superuser or current_user.has_role("admin")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Optional[CurrentUser]:
    """
    Get current authenticated user from JWT token (optional).
    Returns None if no token is provided or token is invalid.
    
    Usage:
        @app.post("/api/chat/stream")
        async def chat_stream(
            current_user: Optional[CurrentUser] = Depends(get_current_user_optional)
        ):
            user_id = str(current_user.id) if current_user else None
            ...
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    
    try:
        # Decode token
        payload = decode_token(token)
        if not payload:
            return None
        
        # Check token blacklist
        token_jti = get_token_jti(token)
        if token_jti and TokenBlacklist.is_blacklisted(token_jti):
            return None
        
        # Get user ID from token
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        
        try:
            user_id = UUID(user_id_str)
        except ValueError:
            return None
        
        # Get user from database
        user_data = UserDB.get_by_id(user_id)
        if not user_data:
            return None
        
        if not user_data.get("is_active", True):
            return None
        
        # Get user roles and permissions
        roles = UserDB.get_user_roles(user_id)
        permissions = UserDB.get_user_permissions(user_id)
        
        return CurrentUser(user_data, roles, permissions)
    except Exception as e:
        logger.debug(f"Optional authentication failed: {e}")
        return None

