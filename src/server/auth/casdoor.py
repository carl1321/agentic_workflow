# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Casdoor OAuth login routes.
Optional: only registered if this module imports successfully.
Failure to register does not affect core auth routes (login, public-key, etc.).
"""

import json
import logging
import os
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ValidationError

from src.config.loader import load_yaml_config, get_str_env

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["casdoor"])


def _norm_key(d: dict, *keys: str) -> Optional[str]:
    """Get first existing key from d (supports both snake_case and kebab-case)."""
    for k in keys:
        v = d.get(k) or d.get(k.replace("_", "-"))
        if v:
            return str(v).strip()
    return None


def _get_casdoor_config() -> Optional[dict]:
    """Read Casdoor config from conf.yaml or env. Returns None if not configured."""
    try:
        config = load_yaml_config("conf.yaml") or {}
        casdoor = config.get("casdoor") or (config.get("ENV") or {}).get("casdoor")
        if isinstance(casdoor, dict) and (casdoor.get("endpoint") or casdoor.get("client_id") or casdoor.get("client-id")):
            endpoint = _norm_key(casdoor, "endpoint") or ""
            client_id = _norm_key(casdoor, "client_id", "client-id") or ""
            if endpoint or client_id:
                return {
                    "endpoint": (endpoint or "https://casdoor.org").rstrip("/"),
                    "client_id": client_id,
                    "client_secret": _norm_key(casdoor, "client_secret", "client-secret") or "",
                    "organization_name": _norm_key(casdoor, "organization_name", "organization-name") or "built-in",
                    "application_name": _norm_key(casdoor, "application_name", "application-name") or "app-built-in",
                    "certificate": _norm_key(casdoor, "certificate") or "",
                }
    except Exception as e:
        logger.debug("No casdoor in conf.yaml: %s", e)
    # Env fallback
    endpoint = get_str_env("CASDOOR_ENDPOINT")
    if not endpoint:
        return None
    return {
        "endpoint": endpoint.rstrip("/"),
        "client_id": get_str_env("CASDOOR_CLIENT_ID", ""),
        "client_secret": get_str_env("CASDOOR_CLIENT_SECRET", ""),
        "organization_name": get_str_env("CASDOOR_ORG_NAME", ""),
        "application_name": get_str_env("CASDOOR_APP_NAME", ""),
        "certificate": get_str_env("CASDOOR_CERTIFICATE", ""),
    }


def _ssl_context_for_casdoor(cfg: dict) -> ssl.SSLContext:
    """若配置了 certificate，则用其校验 Casdoor 的 HTTPS；否则用系统默认。"""
    ctx = ssl.create_default_context()
    cert = (cfg.get("certificate") or "").strip()
    if cert:
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
                f.write(cert)
                tmp = f.name
            try:
                ctx.load_verify_locations(tmp)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception as e:
            logger.warning("Casdoor certificate load failed, using default SSL: %s", e)
    return ctx


class CasdoorCallbackBody(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None  # must match the one used in auth request


@router.get("/casdoor/login")
async def casdoor_login(
    redirect_uri: str,
    state: Optional[str] = None,
):
    """
    Return Casdoor authorization URL for frontend redirect.
    Does not redirect itself so frontend can control navigation.
    """
    cfg = _get_casdoor_config()
    if not cfg or not cfg.get("client_id"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Casdoor is not configured. Set casdoor in conf.yaml or CASDOOR_* env.",
        )
    endpoint = cfg["endpoint"]
    client_id = cfg["client_id"]
    org = cfg.get("organization_name") or "built-in"
    app_name = cfg.get("application_name") or "app-built-in"
    # Casdoor auth URL format
    path = f"/login/oauth/authorize"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        "state": state or "",
    }
    url = f"{endpoint}{path}?{urllib.parse.urlencode({k: v for k, v in params.items() if v})}"
    return {"url": url}


@router.get("/casdoor/logout-url")
async def casdoor_logout_url(redirect_uri: Optional[str] = None):
    """
    返回 Casdoor SSO 登出 URL。前端登出时跳转至此 URL 可清除 Casdoor 会话；
    登出后默认跳转到 Casdoor 的登录页（非本应用登录页）。
    """
    cfg = _get_casdoor_config()
    if not cfg or not cfg.get("client_id"):
        return {"url": None, "configured": False}
    endpoint = cfg["endpoint"].rstrip("/")
    path = "/api/sso-logout"
    # 默认跳转到 Casdoor 登录页，便于用户下次从 Casdoor 重新登录
    redirect = (redirect_uri or "").strip() or f"{endpoint}/login"
    params = {"redirect_uri": redirect}
    url = f"{endpoint}{path}?{urllib.parse.urlencode(params)}"
    return {"url": url, "configured": True}


def _exchange_code_for_token(cfg: dict, code: str, redirect_uri: str) -> tuple[Optional[dict], Optional[str]]:
    """Exchange authorization code for access token. Returns (token_response, error_message)."""
    endpoint = cfg["endpoint"]
    client_id = cfg["client_id"]
    client_secret = cfg["client_secret"]
    path = "/api/login/oauth/access_token"
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode()
    req = urllib.request.Request(
        f"{endpoint}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    ctx = _ssl_context_for_casdoor(cfg)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        logger.warning("Casdoor token exchange HTTP %s: %s", e.code, body[:200])
        return None, f"Casdoor 返回 {e.code}: {body[:200]}" if body else str(e)
    except Exception as e:
        logger.warning("Casdoor token exchange failed: %s", e)
        return None, str(e)


def _get_casdoor_user(cfg: dict, access_token: str) -> Optional[dict]:
    """Get user info from Casdoor. Returns user dict or None."""
    endpoint = cfg["endpoint"]
    path = "/api/get-account"
    req = urllib.request.Request(
        f"{endpoint}{path}",
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    ctx = _ssl_context_for_casdoor(cfg)
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("Casdoor get-account failed: %s", e)
        return None


@router.post("/casdoor/callback")
async def casdoor_callback(body: CasdoorCallbackBody):
    """
    Exchange code for Casdoor token, get user, sync to local user, return same LoginResponse as /auth/login.
    """
    try:
        return await _casdoor_callback_impl(body)
    except HTTPException:
        raise
    except ValidationError as e:
        logger.exception("Casdoor callback validation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid response data: {e.errors()}",
        )
    except Exception as e:
        logger.exception("Casdoor callback failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Casdoor login failed: {getattr(e, 'message', str(e))}",
        )


async def _casdoor_callback_impl(body: CasdoorCallbackBody):
    cfg = _get_casdoor_config()
    if not cfg or not cfg.get("client_id"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Casdoor is not configured.",
        )

    # Frontend must send redirect_uri that was used in the auth request (e.g. in body or we use a default).
    # Casdoor may return it in state as "redirect_uri|state" or we accept from body. For simplicity we
    # require redirect_uri in callback body or derive from config.
    redirect_uri = getattr(body, "redirect_uri", None) or get_str_env("CASDOOR_REDIRECT_URI", "")
    if not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri required in callback or set CASDOOR_REDIRECT_URI.",
        )

    token_resp, token_err = _exchange_code_for_token(cfg, body.code, redirect_uri)
    if not token_resp or not token_resp.get("access_token"):
        detail = "Failed to exchange code for token."
        if token_err:
            detail += " " + token_err
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )
    access_token = token_resp["access_token"]
    casdoor_user = _get_casdoor_user(cfg, access_token)
    if not casdoor_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to get user from Casdoor.",
        )

    # Map Casdoor user to our fields. Casdoor may use "name", "sub", "email", "displayName"
    name = casdoor_user.get("name") or casdoor_user.get("sub") or casdoor_user.get("displayName") or "casdoor_user"
    raw_email = (casdoor_user.get("email") or "").strip()
    # LoginResponse.user.email 需为合法邮箱，.local 等保留域会被 Pydantic EmailStr 拒绝
    if raw_email and " " not in raw_email and not raw_email.lower().endswith(".local"):
        # 仅当 @ 后是合法域且不含多个 @ 时才用（避免 name 为邮箱时再拼 @example.com）
        if raw_email.count("@") == 1 and "." in raw_email.split("@")[-1]:
            email = raw_email
        else:
            email = f"{name.replace('@', '_')}@example.com"
    else:
        email = f"{name.replace('@', '_')}@example.com"
    sub = casdoor_user.get("sub") or casdoor_user.get("id") or name

    from .db import UserDB
    from .jwt import create_access_token
    from .models import LoginResponse

    user_data = UserDB.get_by_username(name)
    if not user_data:
        # Create local user for Casdoor (placeholder password)
        from .db import get_db_connection
        from .password import hash_password
        try:
            password_hash = hash_password(os.urandom(32).hex())
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users (
                            username, email, password_hash, real_name, is_active, is_superuser
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (username) DO NOTHING
                        RETURNING id
                        """,
                        (name, email, password_hash, casdoor_user.get("displayName"), True, True),
                    )
                    conn.commit()
            user_data = UserDB.get_by_username(name)
        except Exception as e:
            logger.exception("Create Casdoor user failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create or find user.",
            )
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create or find user.",
            )

    raw_id = user_data["id"]
    user_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
    UserDB.update_last_login(user_id)

    # Casdoor 登录用户默认给管理员权限（若尚未具备）
    if not user_data.get("is_superuser"):
        try:
            from .db import get_db_connection
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE users SET is_superuser = TRUE, updated_at = NOW() WHERE id = %s",
                        (str(user_id),),
                    )
                    conn.commit()
            user_data = UserDB.get_by_id(user_id) or user_data
            user_data["is_superuser"] = True
        except Exception as e:
            logger.warning("Could not set Casdoor user as superuser: %s", e)
    roles = UserDB.get_user_roles(user_id)
    permissions = UserDB.get_user_permissions(user_id)

    def _normalize_role(role: dict) -> dict:
        out = {}
        for k, v in role.items():
            if isinstance(v, datetime):
                out[k] = v.isoformat()
            elif v is None and k in ("created_at", "updated_at"):
                out[k] = datetime.utcnow().isoformat()
            else:
                out[k] = v
        return out

    token = create_access_token(
        user_id=str(user_id),
        username=user_data["username"],
        is_superuser=user_data.get("is_superuser", False),
    )
    # 返回的 email 须通过 Pydantic EmailStr；若 DB 里存了非法值（如 xxx@yyy@example.com）也走后备
    resp_email = (user_data.get("email") or "").strip()
    def _email_ok(e: str) -> bool:
        if not e or " " in e or e.lower().endswith(".local"):
            return False
        parts = e.split("@")
        if len(parts) != 2 or not parts[0] or "." not in parts[1]:
            return False
        return True
    if not _email_ok(resp_email):
        safe_local = (user_data.get("username") or "user").replace("@", "_")
        resp_email = f"{safe_local}@example.com"
    # UserResponse 要求 created_at/updated_at 为 str，不能为 None
    _ca = user_data.get("created_at")
    _ua = user_data.get("updated_at")
    created_at_str = _ca.isoformat() if _ca else datetime.utcnow().isoformat()
    updated_at_str = _ua.isoformat() if _ua else datetime.utcnow().isoformat()
    user_response = {
        "id": user_id,
        "username": user_data["username"],
        "email": resp_email,
        "real_name": user_data.get("real_name"),
        "is_superuser": user_data.get("is_superuser", False),
        "roles": [_normalize_role(r) for r in roles],
        "permissions": permissions,
        "organization_id": user_data.get("organization_id"),
        "department_id": user_data.get("department_id"),
        "data_permission_level": user_data.get("data_permission_level", "self"),
        "is_active": user_data.get("is_active", True),
        "last_login_at": datetime.utcnow().isoformat(),
        "created_at": created_at_str,
        "updated_at": updated_at_str,
    }
    return LoginResponse(access_token=token, token_type="bearer", user=user_response)
