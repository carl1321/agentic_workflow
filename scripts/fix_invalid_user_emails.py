#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
修复 users 表中非法邮箱（如 xxx@yyy@example.com）。
将「含多个 @」或其它非法格式的 email 改为合法占位邮箱，避免 Casdoor 登录时 Pydantic EmailStr 校验失败。

用法：在项目根目录执行 python3 scripts/fix_invalid_user_emails.py
      会从环境变量或 conf.yaml 的 ENV 中读取 DATABASE_URL。
"""

import os
import sys

import psycopg
from psycopg.rows import dict_row
import yaml


def _get_db_url():
    url = os.environ.get("DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URI")
    if url:
        return url
    conf_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "conf.yaml")
    if os.path.exists(conf_path):
        with open(conf_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
        env = cfg.get("ENV") or {}
        url = env.get("DATABASE_URL") or env.get("SQLALCHEMY_DATABASE_URI") or env.get("LANGGRAPH_CHECKPOINT_DB_URL")
        if url:
            return url
    return "postgresql://localhost:5432/agenticworkflow"


def get_db_connection():
    db_url = _get_db_url()
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    return psycopg.connect(db_url, row_factory=dict_row)


def main():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # 查出 email 中含多个 @ 或明显非法的记录
            cur.execute(
                """
                SELECT id, username, email
                FROM users
                WHERE email ~ '@.*@'
                   OR trim(email) = ''
                   OR email ~ '\\s'
                   OR lower(email) LIKE '%.local'
                """
            )
            rows = cur.fetchall()
            if not rows:
                print("没有需要修复的非法邮箱。")
                return
            print(f"发现 {len(rows)} 条非法邮箱，正在修复…")
            for r in rows:
                uid, username, old_email = r["id"], r["username"] or "user", (r["email"] or "").strip()
                # 若是 xxx@yyy@example.com 这种误拼，改为真实邮箱 xxx@yyy（需未被其他用户占用）
                new_email = None
                if old_email.endswith("@example.com") and old_email.count("@") >= 2:
                    candidate = old_email[: -len("@example.com")]
                    if candidate.count("@") == 1 and "." in candidate.split("@")[-1]:
                        cur.execute(
                            "SELECT 1 FROM users WHERE email = %s AND id != %s",
                            (candidate, uid),
                        )
                        if cur.fetchone() is None:
                            new_email = candidate
                if not new_email:
                    safe_local = (username or "user").replace("@", "_").replace(" ", "_") or "user"
                    new_email = f"{safe_local}+{uid}@example.com"
                cur.execute(
                    "UPDATE users SET email = %s, updated_at = NOW() WHERE id = %s",
                    (new_email, uid),
                )
                print(f"  id={uid} username={username!r} 旧邮箱={old_email!r} -> {new_email}")
            conn.commit()
            print("已提交，修复完成。")


if __name__ == "__main__":
    main()
