# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Password hashing and verification utilities.

注意：生产环境强烈建议安装 `bcrypt` 包，这里仅在缺失时提供一个
明显标记为不安全的纯文本回退方案，用于本地开发调试。
"""

import logging

logger = logging.getLogger(__name__)

try:
    import bcrypt  # type: ignore
except ImportError:  # pragma: no cover - fallback for environments without bcrypt
    bcrypt = None  # type: ignore
    logger.warning(
        "bcrypt not installed. Falling back to INSECURE plain-text password storage. "
        "Please install bcrypt in production: pip install bcrypt"
    )


def _plain_tag(password: str) -> str:
    return f"plain${password}"


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt when available.
    If bcrypt is not installed, fall back to a clearly-tagged plain-text scheme.
    """
    try:
        if bcrypt is not None:
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
            return hashed.decode("utf-8")
        # INSECURE fallback for local dev when bcrypt is missing
        return _plain_tag(password)
    except Exception as e:
        logger.error(f"Error hashing password: {e}")
        raise


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against a hash.

    - If bcrypt is available and hash looks like a bcrypt hash, use bcrypt.
    - If hash starts with 'plain$', use simple string comparison (fallback mode).
    """
    try:
        # Fallback plain-text mode
        if password_hash.startswith("plain$"):
            return password_hash == _plain_tag(password)

        if bcrypt is None:
            logger.error(
                "bcrypt is not installed but password hash is not in plain$ format. "
                "Unable to verify password securely."
            )
            return False

        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False

