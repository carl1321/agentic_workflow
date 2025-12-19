# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Authentication and authorization module for RBAC system.
"""

from .dependencies import get_current_user, require_admin, require_permission, require_role
from .jwt import create_access_token, decode_token, verify_token
from .password import hash_password, verify_password

__all__ = [
    "create_access_token",
    "decode_token",
    "verify_token",
    "hash_password",
    "verify_password",
    "get_current_user",
    "require_admin",
    "require_permission",
    "require_role",
]

