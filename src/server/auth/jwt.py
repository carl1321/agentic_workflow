# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
JWT token generation and verification.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import jwt
from jwt import PyJWTError

logger = logging.getLogger(__name__)

# JWT 配置
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 默认24小时


def create_access_token(
    user_id: str,
    username: str,
    is_superuser: bool = False,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.
    
    Args:
        user_id: User ID
        username: Username
        is_superuser: Whether user is superuser
        expires_delta: Optional expiration time delta
        
    Returns:
        JWT token string
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # JWT payload
    payload = {
        "sub": user_id,  # subject (user ID)
        "username": username,
        "is_superuser": is_superuser,
        "jti": str(uuid4()),  # JWT ID (for token blacklist)
        "exp": expire,  # expiration
        "iat": datetime.utcnow(),  # issued at
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload dict if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except PyJWTError as e:
        logger.warning(f"JWT decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding token: {e}")
        return None


def verify_token(token: str) -> bool:
    """
    Verify if a token is valid (not expired and properly signed).
    
    Args:
        token: JWT token string
        
    Returns:
        True if token is valid, False otherwise
    """
    payload = decode_token(token)
    return payload is not None


def get_token_jti(token: str) -> Optional[str]:
    """
    Extract JTI (JWT ID) from token for blacklist management.
    
    Args:
        token: JWT token string
        
    Returns:
        JTI string if present, None otherwise
    """
    payload = decode_token(token)
    return payload.get("jti") if payload else None

