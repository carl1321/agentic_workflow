#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流导出/导入脚本

将已有工作流导出为 JSON 文件，在另一台服务器上导入即可复现。

用法:
  导出（按名称）: uv run scripts/export_import_workflow.py export --name "分子生成2" -o workflow_export.json
  导出（按ID）  : uv run scripts/export_import_workflow.py export --id <workflow_uuid> -o workflow_export.json
  导入         : uv run scripts/export_import_workflow.py import -f workflow_export.json

导入时需配置目标服务器的数据库连接（DATABASE_URL / LANGGRAPH_CHECKPOINT_DB_URL）。
导入会使用目标库中的第一个管理员用户作为 created_by；若无管理员则需通过 --user-id 指定。
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_db_connection():
    """获取数据库连接"""
    db_url = (
        get_str_env("DATABASE_URL")
        or get_str_env("SQLALCHEMY_DATABASE_URI")
        or get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    return psycopg.connect(db_url, row_factory=dict_row)


def get_admin_user_id(conn) -> UUID:
    """获取第一个管理员用户 ID（优先 superuser，其次 admin 角色，最后任意用户）"""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE is_superuser = true AND is_active = true LIMIT 1")
        row = cur.fetchone()
    if row:
        return UUID(str(row["id"]))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id FROM users u
            JOIN user_roles ur ON u.id = ur.user_id
            JOIN roles r ON ur.role_id = r.id
            WHERE r.code = 'admin' AND u.is_active = true
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row:
        return UUID(str(row["id"]))
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE is_active = true ORDER BY created_at LIMIT 1")
        row = cur.fetchone()
    if row:
        return UUID(str(row["id"]))
    raise SystemExit("未找到用户，请先初始化数据库并创建管理员，或使用 --user-id 指定")


def export_workflow(conn, workflow_id: UUID) -> dict:
    """导出工作流（含草稿图与发布 spec）"""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, description, current_draft_id, current_release_id FROM workflows WHERE id = %s", (workflow_id,))
        wf = cur.fetchone()
    if not wf:
        raise SystemExit(f"工作流不存在: {workflow_id}")

    with conn.cursor() as cur:
        cur.execute("SELECT id, graph FROM workflow_drafts WHERE workflow_id = %s ORDER BY version DESC LIMIT 1", (workflow_id,))
        draft = cur.fetchone()
    if not draft:
        raise SystemExit(f"工作流 {wf['name']} 无草稿，无法导出")

    graph = draft["graph"]
    if isinstance(graph, str):
        graph = json.loads(graph)

    # 获取当前 release 的 spec（若有）
    spec = None
    if wf.get("current_release_id"):
        with conn.cursor() as cur:
            cur.execute("SELECT spec FROM workflow_releases WHERE id = %s", (wf["current_release_id"],))
            rel = cur.fetchone()
        if rel:
            spec = rel["spec"]
            if isinstance(spec, str):
                spec = json.loads(spec)

    # 若没有 release，从 draft graph 构建 spec（与前端 publish 一致）
    if spec is None:
        nodes = graph.get("nodes", [])
        spec = {
            "name": wf["name"] or "未命名工作流",
            "nodes": [
                {
                    "id": n["id"],
                    "type": n["type"],
                    "position": n.get("position", {"x": 0, "y": 0}),
                    "data": {**n.get("data", {}), "nodeName": n.get("data", {}).get("taskName", n.get("data", {}).get("nodeName", n["id"]))},
                }
                for n in nodes
            ],
            "edges": [
                {"id": e["id"], "source": e["source"], "target": e["target"], "sourceHandle": e.get("sourceHandle"), "targetHandle": e.get("targetHandle")}
                for e in graph.get("edges", [])
            ],
        }

    return {
        "name": wf["name"],
        "description": wf.get("description"),
        "graph": graph,
        "spec": spec,
    }


def _insert_draft_with_spec(conn, workflow_id: UUID, graph: dict, spec: dict, created_by: UUID) -> UUID:
    """直接插入草稿（含 spec），兼容目标库 workflow_drafts 含 spec NOT NULL 的 schema"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM workflow_drafts WHERE workflow_id = %s",
            (workflow_id,),
        )
        row = cur.fetchone()
        version = row["next_version"] if row else 1

    draft_id = uuid4()
    graph_json = json.dumps(graph)
    spec_json = json.dumps(spec)

    # 优先尝试带 spec 的插入（目标库可能有 spec NOT NULL）
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO workflow_drafts (id, workflow_id, version, is_autosave, graph, spec, created_by)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (draft_id, workflow_id, version, False, graph_json, spec_json, created_by),
            )
        except psycopg.errors.UndefinedColumn:
            # 无 spec 列的 schema，回退为只插入 graph
            cur.execute(
                """
                INSERT INTO workflow_drafts (id, workflow_id, version, is_autosave, graph, validation, created_by)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (draft_id, workflow_id, version, False, graph_json, None, created_by),
            )

    with conn.cursor() as cur:
        cur.execute("UPDATE workflows SET current_draft_id = %s WHERE id = %s", (draft_id, workflow_id))

    return draft_id


def _get_release_version_column(conn) -> str:
    """检测 workflow_releases 表的版本列名（release_version 或 version）"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'workflow_releases' AND column_name IN ('release_version', 'version')
            """
        )
        row = cur.fetchone()
    return row["column_name"] if row else "release_version"


def _insert_release(
    conn, workflow_id: UUID, draft_id: UUID, spec: dict, checksum: str, created_by: UUID
) -> UUID:
    """直接插入 workflow_releases，兼容 release_version / version 不同列名"""
    version_col = _get_release_version_column(conn)
    # 兼容 INTEGER 与 VARCHAR/TEXT：用 COALESCE(MAX(col), '0')::int + 1 避免类型不匹配
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT (COALESCE(MAX({version_col})::text, '0')::int + 1) AS next_version
            FROM workflow_releases WHERE workflow_id = %s
            """,
            (workflow_id,),
        )
        row = cur.fetchone()
    next_ver = row["next_version"] if row else 1
    release_version = str(next_ver) if isinstance(next_ver, (int, float)) else next_ver

    release_id = uuid4()
    spec_json = json.dumps(spec)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO workflow_releases (
                id, workflow_id, {version_col}, source_draft_id, spec, checksum, created_by
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (release_id, workflow_id, release_version, draft_id, spec_json, checksum, created_by),
        )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workflows SET current_release_id = %s, status = %s WHERE id = %s",
            (release_id, "published", workflow_id),
        )
    return release_id


def import_workflow(conn, data: dict, created_by: UUID) -> UUID:
    """导入工作流到当前数据库"""
    from src.server.workflow.db import create_workflow

    name = data.get("name") or "导入的工作流"
    description = data.get("description")
    graph = data["graph"]
    spec = data["spec"]

    workflow_id = create_workflow(conn, name=name, description=description, created_by=created_by, status="draft")
    conn.commit()

    draft_id = _insert_draft_with_spec(conn, workflow_id, graph=graph, spec=spec, created_by=created_by)
    conn.commit()

    spec_str = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    checksum = hashlib.sha256(spec_str.encode()).hexdigest()
    _insert_release(conn, workflow_id, draft_id, spec=spec, checksum=checksum, created_by=created_by)
    conn.commit()

    return workflow_id


def main():
    parser = argparse.ArgumentParser(description="工作流导出/导入")
    sub = parser.add_subparsers(dest="cmd", required=True)
    # export
    ep = sub.add_parser("export", help="导出工作流到 JSON")
    ep.add_argument("--name", "-n", help="按名称匹配工作流（如：分子生成2）")
    ep.add_argument("--id", help="按工作流 UUID 导出")
    ep.add_argument("-o", "--output", required=True, help="输出 JSON 文件路径")
    # import
    ip = sub.add_parser("import", help="从 JSON 导入工作流")
    ip.add_argument("-f", "--file", required=True, help="导出的 JSON 文件路径")
    ip.add_argument("--user-id", help="导入时使用的用户 UUID，不填则自动取第一个管理员")

    args = parser.parse_args()

    conn = get_db_connection()
    try:
        if args.cmd == "export":
            if args.id:
                workflow_id = UUID(args.id)
            elif args.name:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM workflows WHERE name = %s ORDER BY created_at DESC LIMIT 1", (args.name,))
                    row = cur.fetchone()
                if not row:
                    raise SystemExit(f"未找到名为 '{args.name}' 的工作流")
                workflow_id = UUID(str(row["id"]))
            else:
                raise SystemExit("请指定 --name 或 --id")

            data = export_workflow(conn, workflow_id)
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("已导出工作流 '%s' 到 %s", data["name"], out)

        else:  # import
            with open(args.file, "r", encoding="utf-8") as f:
                data = json.load(f)
            created_by = UUID(args.user_id) if args.user_id else get_admin_user_id(conn)
            workflow_id = import_workflow(conn, data, created_by)
            logger.info("已导入工作流 '%s'，ID: %s", data.get("name"), workflow_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
