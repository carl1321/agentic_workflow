# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Admin module for RBAC system.
Contains database operations for organizations, departments, roles, permissions, menus, and users.
"""

from .departments import DepartmentDB
from .organizations import OrganizationDB

__all__ = [
    "OrganizationDB",
    "DepartmentDB",
]

