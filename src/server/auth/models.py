# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Data models for RBAC system.
These are Pydantic models for request/response, not database models.
"""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    """Base user model."""
    username: str
    email: EmailStr
    real_name: Optional[str] = None
    phone: Optional[str] = None
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    is_active: bool = True


class UserCreate(UserBase):
    """User creation model."""
    password: str
    role_ids: Optional[List[UUID]] = None


class UserUpdate(BaseModel):
    """User update model."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    real_name: Optional[str] = None
    phone: Optional[str] = None
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    data_permission_level: Optional[str] = None


class UserResponse(UserBase):
    """User response model."""
    id: UUID
    is_superuser: bool
    data_permission_level: str
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class UserWithRoles(UserResponse):
    """User with roles information."""
    roles: List["RoleResponse"] = []


class RoleBase(BaseModel):
    """Base role model."""
    code: str
    name: str
    description: Optional[str] = None
    organization_id: Optional[UUID] = None
    data_permission_level: str = "self"
    is_active: bool = True


class RoleCreate(RoleBase):
    """Role creation model."""
    permission_ids: Optional[List[UUID]] = None
    menu_ids: Optional[List[UUID]] = None


class RoleUpdate(BaseModel):
    """Role update model."""
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    organization_id: Optional[UUID] = None
    data_permission_level: Optional[str] = None
    is_active: Optional[bool] = None


class RoleResponse(RoleBase):
    """Role response model."""
    id: UUID
    is_system: bool
    sort_order: int
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class PermissionBase(BaseModel):
    """Base permission model."""
    code: str
    name: str
    resource: str
    action: str
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    """Permission creation model."""
    pass


class PermissionResponse(PermissionBase):
    """Permission response model."""
    id: UUID
    is_system: bool
    created_at: str
    
    class Config:
        from_attributes = True


class MenuBase(BaseModel):
    """Base menu model."""
    code: str
    name: str
    path: Optional[str] = None
    icon: Optional[str] = None
    component: Optional[str] = None
    menu_type: str = "menu"
    permission_code: Optional[str] = None
    is_visible: bool = True
    parent_id: Optional[UUID] = None


class MenuCreate(MenuBase):
    """Menu creation model."""
    pass


class MenuUpdate(BaseModel):
    """Menu update model."""
    code: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None
    icon: Optional[str] = None
    component: Optional[str] = None
    menu_type: Optional[str] = None
    permission_code: Optional[str] = None
    is_visible: Optional[bool] = None
    parent_id: Optional[UUID] = None
    sort_order: Optional[int] = None


class MenuResponse(MenuBase):
    """Menu response model."""
    id: UUID
    is_system: bool
    sort_order: int
    created_at: str
    updated_at: str
    children: List["MenuResponse"] = []
    
    class Config:
        from_attributes = True


class OrganizationBase(BaseModel):
    """Base organization model."""
    code: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    is_active: bool = True


class OrganizationCreate(OrganizationBase):
    """Organization creation model."""
    pass


class OrganizationResponse(OrganizationBase):
    """Organization response model."""
    id: UUID
    sort_order: int
    created_at: str
    updated_at: str
    children: List["OrganizationResponse"] = []
    
    class Config:
        from_attributes = True


class DepartmentBase(BaseModel):
    """Base department model."""
    code: str
    name: str
    organization_id: UUID
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    """Department creation model."""
    pass


class DepartmentUpdate(BaseModel):
    """Department update model with optional fields."""
    code: Optional[str] = None
    name: Optional[str] = None
    organization_id: Optional[UUID] = None
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class DepartmentResponse(DepartmentBase):
    """Department response model."""
    id: UUID
    sort_order: int
    created_at: str
    updated_at: str
    children: List["DepartmentResponse"] = []
    
    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response model."""
    access_token: str
    token_type: str = "bearer"
    user: UserWithRoles


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    token_type: str = "bearer"


class UserInfoResponse(BaseModel):
    """User info response model."""
    id: UUID
    username: str
    email: str
    real_name: Optional[str]
    is_superuser: bool
    roles: List[RoleResponse]
    permissions: List[str]  # Permission codes
    menus: List[MenuResponse]  # Accessible menus
    organization: Optional[OrganizationResponse] = None
    department: Optional[DepartmentResponse] = None
    data_permission_level: str

