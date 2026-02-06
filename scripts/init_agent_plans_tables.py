#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
初始化“本地长期计划（Coze-like）”模块所需数据库表。

说明：
- 这是一个独立脚本，不修改现有 scripts/init_database.py。
- 依赖 PostgreSQL，并复用 conf.yaml/环境变量中的连接串：
  DATABASE_URL / SQLALCHEMY_DATABASE_URI / LANGGRAPH_CHECKPOINT_DB_URL

用法：
  uv run scripts/init_agent_plans_tables.py
"""

import logging

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_db_connection():
    """获取数据库连接（优先读取环境变量，其次 conf.yaml 的 ENV）。"""
    db_url = (
        get_str_env("DATABASE_URL")
        or get_str_env("SQLALCHEMY_DATABASE_URI")
        or get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
    )

    # Ensure postgresql:// format -> psycopg prefers postgres://
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)

    return psycopg.connect(db_url, row_factory=dict_row)


def init_agent_plan_tables(conn: psycopg.Connection):
    """创建长期计划相关表结构（IF NOT EXISTS）。"""
    with conn.cursor() as cursor:
        # 依赖 gen_random_uuid()（pgcrypto）。若无权限创建扩展，这里失败也不影响后续（已有扩展即可）。
        try:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
        except Exception as e:  # pragma: no cover
            logger.warning(f'Failed to create extension pgcrypto (may already exist or no privilege): {e}')

        # 1) 计划主表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_plans (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID,
                title TEXT,
                status VARCHAR(50) NOT NULL DEFAULT 'draft',
                raw_goal TEXT,
                ora_spec JSONB,
                clarify JSONB,
                spec_version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_agent_plans_user_id ON agent_plans(user_id);
            CREATE INDEX IF NOT EXISTS idx_agent_plans_status ON agent_plans(status);
            """
        )

        # 2) 任务表（最小可执行单元）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_plan_tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plan_id UUID NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                acceptance_criteria TEXT,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                depends_on JSONB,
                scheduled_at TIMESTAMP WITH TIME ZONE,
                started_at TIMESTAMP WITH TIME ZONE,
                finished_at TIMESTAMP WITH TIME ZONE,
                executor_type VARCHAR(20) NOT NULL,
                executor_args JSONB,
                idempotency_key TEXT,
                attempt INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 0,
                error JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (plan_id) REFERENCES agent_plans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_plan_tasks_plan_id ON agent_plan_tasks(plan_id);
            CREATE INDEX IF NOT EXISTS idx_agent_plan_tasks_status ON agent_plan_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_agent_plan_tasks_scheduled_at ON agent_plan_tasks(scheduled_at);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_plan_tasks_plan_id_idempotency_key
                ON agent_plan_tasks(plan_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL AND idempotency_key <> '';
            """
        )

        # 3) 产物表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_plan_artifacts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plan_id UUID NOT NULL,
                task_id UUID NOT NULL,
                type VARCHAR(50) NOT NULL,
                file_path TEXT NOT NULL,
                meta JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (plan_id) REFERENCES agent_plans(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES agent_plan_tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_plan_artifacts_plan_id ON agent_plan_artifacts(plan_id);
            CREATE INDEX IF NOT EXISTS idx_agent_plan_artifacts_task_id ON agent_plan_artifacts(task_id);
            """
        )

        # 4) 日志表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_plan_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plan_id UUID NOT NULL,
                task_id UUID,
                level VARCHAR(20) NOT NULL,
                event VARCHAR(100) NOT NULL,
                payload JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (plan_id) REFERENCES agent_plans(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES agent_plan_tasks(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_plan_logs_plan_id ON agent_plan_logs(plan_id);
            CREATE INDEX IF NOT EXISTS idx_agent_plan_logs_task_id ON agent_plan_logs(task_id);
            CREATE INDEX IF NOT EXISTS idx_agent_plan_logs_created_at ON agent_plan_logs(created_at);
            """
        )

        # 5) 计划对话消息表（与 chat_streams/thread 分离）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_plan_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plan_id UUID NOT NULL,
                role VARCHAR(20) NOT NULL,            -- user / assistant / system
                content TEXT NOT NULL,
                meta JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (plan_id) REFERENCES agent_plans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_plan_messages_plan_id ON agent_plan_messages(plan_id);
            CREATE INDEX IF NOT EXISTS idx_agent_plan_messages_created_at ON agent_plan_messages(created_at);
            """
        )

    conn.commit()


def main():
    conn = get_db_connection()
    try:
        logger.info("Initializing agent plans tables...")
        init_agent_plan_tables(conn)
        logger.info("Agent plans tables initialized successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

