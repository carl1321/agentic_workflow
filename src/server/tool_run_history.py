# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""工具箱运行历史：文生图、PPT 生成等的结果持久化与查询。"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from src.server.workflow.db import get_db_connection

logger = logging.getLogger(__name__)


def _ensure_table(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tool_run_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tool_id VARCHAR(64) NOT NULL,
                params_json JSONB,
                result_json TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_run_history_tool_id ON tool_run_history(tool_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_run_history_created_at ON tool_run_history(created_at DESC)"
        )
    conn.commit()


def save_tool_run(tool_id: str, params: Dict[str, Any], result: str) -> Dict[str, Any]:
    """保存一次工具运行记录。返回包含 id、created_at 等的完整记录。"""
    conn = get_db_connection()
    try:
        _ensure_table(conn)
        rid = uuid4()
        params_str = json.dumps(params, ensure_ascii=False) if isinstance(params, dict) else "{}"
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tool_run_history (id, tool_id, params_json, result_json)
                VALUES (%s, %s, %s::jsonb, %s)
                """,
                (rid, tool_id, params_str, result),
            )
        conn.commit()
        return get_tool_run(str(rid)) or {"id": str(rid), "tool_id": tool_id}
    finally:
        conn.close()


def list_tool_runs(
    tool_id: str, limit: int = 50, offset: int = 0
) -> List[Dict[str, Any]]:
    """按 tool_id 分页列出历史记录。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, tool_id, params_json, result_json, created_at
                FROM tool_run_history
                WHERE tool_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (tool_id, limit, offset),
            )
            rows = cursor.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": str(r["id"]),
                "tool_id": r["tool_id"],
                "params_json": r["params_json"],
                "result_json": r["result_json"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
        return out
    finally:
        conn.close()


def get_tool_run(record_id: str) -> Optional[Dict[str, Any]]:
    """根据 id 获取单条记录。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, tool_id, params_json, result_json, created_at
                FROM tool_run_history
                WHERE id = %s
                """,
                (UUID(record_id),),
            )
            r = cursor.fetchone()
        if not r:
            return None
        return {
            "id": str(r["id"]),
            "tool_id": r["tool_id"],
            "params_json": r["params_json"],
            "result_json": r["result_json"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
    except Exception as e:
        logger.warning("get_tool_run %s: %s", record_id, e)
        return None
    finally:
        conn.close()


def delete_tool_run(record_id: str) -> bool:
    """删除一条记录。"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM tool_run_history WHERE id = %s", (UUID(record_id),))
            deleted = cursor.rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()
