# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流数据库访问层
提供工作流、草稿、发布、运行、任务、日志的 CRUD 操作
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env

logger = logging.getLogger(__name__)


def get_db_connection():
    """获取数据库连接"""
    db_url = (
        get_str_env("DATABASE_URL") or
        get_str_env("SQLALCHEMY_DATABASE_URI") or
        get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
    )
    
    # Ensure postgresql:// format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    
    return psycopg.connect(db_url, row_factory=dict_row)


def _as_uuid(value):
    """将值转换为 UUID"""
    if value is None:
        return None
    return UUID(str(value)) if value is not None else None


# ============= 运行状态管理 =============

def acquire_run(conn: psycopg.Connection) -> Optional[Dict[str, Any]]:
    """
    获取并锁定一个 queued 状态的运行（使用 SKIP LOCKED）
    
    Args:
        conn: 数据库连接
        
    Returns:
        运行记录字典，如果没有可用任务则返回 None
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM workflow_runs 
            WHERE status = 'queued' 
            ORDER BY created_at ASC 
            FOR UPDATE SKIP LOCKED 
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def update_run_status(
    conn: psycopg.Connection,
    run_id: UUID,
    status: str,
    output: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> bool:
    """
    更新运行状态
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        status: 新状态（queued, running, success, failed, canceled）
        output: 输出数据（可选）
        error: 错误信息（可选）
        started_at: 开始时间（可选）
        finished_at: 结束时间（可选）
        
    Returns:
        是否更新成功
    """
    updates = ["status = %s"]
    params = [status]
    
    if output is not None:
        updates.append("output = %s")
        params.append(json.dumps(output))
    
    if error is not None:
        updates.append("error = %s")
        params.append(json.dumps(error))
    
    if started_at is not None:
        updates.append("started_at = %s")
        params.append(started_at)
    
    if finished_at is not None:
        updates.append("finished_at = %s")
        params.append(finished_at)
    
    params.append(run_id)
    
    with conn.cursor() as cursor:
        cursor.execute(f"""
            UPDATE workflow_runs 
            SET {', '.join(updates)}
            WHERE id = %s
        """, params)
        return cursor.rowcount > 0


def update_run_heartbeat(conn: psycopg.Connection, run_id: UUID) -> bool:
    """
    更新运行心跳时间
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        
    Returns:
        是否更新成功
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE workflow_runs 
            SET heartbeat_at = NOW()
            WHERE id = %s
        """, (run_id,))
        return cursor.rowcount > 0


def reset_stale_runs(conn: psycopg.Connection, timeout_minutes: int = 5) -> int:
    """
    重置僵尸任务（heartbeat 超时）
    
    Args:
        conn: 数据库连接
        timeout_minutes: 超时时间（分钟）
        
    Returns:
        重置的任务数量
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE workflow_runs 
            SET status = 'queued', heartbeat_at = NULL
            WHERE status = 'running' 
            AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - INTERVAL '%s minutes')
        """, (timeout_minutes,))
        return cursor.rowcount


# ============= 节点任务管理 =============

def create_node_task(
    conn: psycopg.Connection,
    run_id: UUID,
    node_id: str,
    input_data: Optional[Dict[str, Any]] = None,
    parent_task_id: Optional[UUID] = None,
    branch_id: Optional[str] = None,
    iteration: Optional[int] = None,
    loop_node_id: Optional[str] = None,
) -> UUID:
    """
    创建节点任务
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        node_id: 节点 ID
        input_data: 输入数据（可选）
        parent_task_id: 父任务 ID（可选）
        branch_id: 分支 ID（可选，用于并行节点）
        iteration: 迭代次数（可选，用于循环节点）
        loop_node_id: 循环节点 ID（可选）
        
    Returns:
        任务 ID
    """
    task_id = uuid4()
    
    # 获取当前运行的最大 run_seq
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT COALESCE(MAX(run_seq), 0) + 1 as next_seq
            FROM node_tasks
            WHERE run_id = %s
        """, (run_id,))
        row = cursor.fetchone()
        run_seq = row['next_seq'] if row else 1
    
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO node_tasks (
                id, run_id, node_id, status, attempt, input,
                parent_task_id, branch_id, iteration, loop_node_id, run_seq
            ) VALUES (%s, %s, %s, 'pending', 1, %s, %s, %s, %s, %s, %s)
        """, (
            task_id, run_id, node_id,
            json.dumps(input_data) if input_data else None,
            parent_task_id, branch_id, iteration, loop_node_id, run_seq
        ))
    
    return task_id


def update_node_task(
    conn: psycopg.Connection,
    task_id: UUID,
    status: Optional[str] = None,
    output: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    metrics: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[int] = None,
    retry_delay_seconds: Optional[int] = None,
) -> bool:
    """
    更新节点任务状态和输出
    
    Args:
        conn: 数据库连接
        task_id: 任务 ID
        status: 新状态（pending, running, success, failed）
        output: 输出数据（可选）
        error: 错误信息（可选）
        started_at: 开始时间（可选）
        finished_at: 结束时间（可选）
        metrics: 指标数据（可选）
        timeout_seconds: 超时时间（秒，可选）
        retry_delay_seconds: 重试延迟时间（秒，可选）
        
    Returns:
        是否更新成功
    """
    updates = []
    params = []
    
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    
    if output is not None:
        updates.append("output = %s")
        params.append(json.dumps(output))
    
    if error is not None:
        updates.append("error = %s")
        params.append(json.dumps(error))
    
    if started_at is not None:
        updates.append("started_at = %s")
        params.append(started_at)
    
    if finished_at is not None:
        updates.append("finished_at = %s")
        params.append(finished_at)
    
    if metrics is not None:
        updates.append("metrics = %s")
        params.append(json.dumps(metrics))
    
    # 检查列是否存在，如果不存在则跳过更新
    conn_check = conn
    with conn_check.cursor() as check_cursor:
        check_cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'node_tasks' AND column_name IN ('timeout_seconds', 'retry_delay_seconds')
        """)
        existing_columns = {row['column_name'] for row in check_cursor.fetchall()}
    
    if timeout_seconds is not None and 'timeout_seconds' in existing_columns:
        updates.append("timeout_seconds = %s")
        params.append(timeout_seconds)
    
    if retry_delay_seconds is not None and 'retry_delay_seconds' in existing_columns:
        updates.append("retry_delay_seconds = %s")
        params.append(retry_delay_seconds)
    
    if not updates:
        return False
    
    params.append(task_id)
    
    with conn.cursor() as cursor:
        cursor.execute(f"""
            UPDATE node_tasks 
            SET {', '.join(updates)}
            WHERE id = %s
        """, params)
        return cursor.rowcount > 0


def get_node_task(conn: psycopg.Connection, task_id: UUID) -> Optional[Dict[str, Any]]:
    """
    获取节点任务详情
    
    Args:
        conn: 数据库连接
        task_id: 任务 ID
        
    Returns:
        任务记录字典，如果不存在则返回 None
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM node_tasks WHERE id = %s
        """, (task_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def get_run_tasks(conn: psycopg.Connection, run_id: UUID) -> List[Dict[str, Any]]:
    """
    获取运行的所有任务
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        
    Returns:
        任务列表
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM node_tasks 
            WHERE run_id = %s 
            ORDER BY run_seq ASC
        """, (run_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_retry_delay(attempt: int) -> int:
    """
    获取重试延迟时间（秒）
    
    Args:
        attempt: 当前尝试次数（1-based，即第1次重试时attempt=1）
        
    Returns:
        延迟时间（秒）
    """
    if attempt == 1:
        return 0  # 立即重试
    elif attempt == 2:
        return 10  # 10秒
    elif attempt == 3:
        return 30  # 30秒
    elif attempt == 4:
        return 60  # 60秒
    else:
        return 60  # 默认60秒


def detect_timeout_node_tasks(
    conn: psycopg.Connection,
    default_timeout_seconds: int = 300,
    max_retries: int = 4
) -> List[Dict[str, Any]]:
    """
    检测超时的节点任务（排除循环体节点本身）
    
    检测范围：
    - 循环体内部节点（loop_node_id IS NOT NULL AND loop_node_id != node_id）
    - 普通节点（loop_node_id IS NULL）
    
    排除：
    - 循环体节点本身（loop_node_id IS NOT NULL AND loop_node_id == node_id）
    
    对于循环体内部节点：
    - 检测条件：status='running' AND started_at < NOW() - INTERVAL 'timeout_seconds seconds'
    - **关键**：需要同时匹配当前的 iteration，确保检测的是当前迭代的超时
    - 由于每次迭代都会更新 started_at，所以 started_at 就是当前迭代的开始时间
    - 这样可以正确检测当前迭代是否超时，而不是累计时间
    
    对于普通节点：
    - 检测条件：status='running' AND started_at < NOW() - INTERVAL 'timeout_seconds seconds'
    
    Args:
        conn: 数据库连接
        default_timeout_seconds: 默认超时时间（秒）
        max_retries: 最大重试次数（4次）
        
    Returns:
        超时的节点任务列表，包含 task_id, node_id, iteration, loop_node_id, run_id 等信息
    """
    with conn.cursor() as cursor:
        # 首先检查列是否存在
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'node_tasks' AND column_name = 'timeout_seconds'
        """)
        has_timeout_column = cursor.fetchone() is not None
        
        # 查询超时的节点任务
        # 排除循环体节点本身：WHERE (loop_node_id IS NULL OR loop_node_id != node_id)
        if has_timeout_column:
            cursor.execute("""
                SELECT 
                    nt.id as task_id,
                    nt.run_id,
                    nt.node_id,
                    nt.attempt,
                    nt.iteration,
                    nt.loop_node_id,
                    nt.started_at,
                    COALESCE(nt.timeout_seconds, %s) as timeout_seconds
                FROM node_tasks nt
                WHERE nt.status = 'running'
                    AND nt.started_at IS NOT NULL
                    AND nt.attempt < %s
                    AND (nt.loop_node_id IS NULL OR nt.loop_node_id != nt.node_id)
                    AND nt.started_at < NOW() - INTERVAL '1 second' * COALESCE(nt.timeout_seconds, %s)
                ORDER BY nt.started_at ASC
            """, (default_timeout_seconds, max_retries, default_timeout_seconds))
        else:
            # 如果列不存在，使用默认超时时间
            cursor.execute("""
                SELECT 
                    nt.id as task_id,
                    nt.run_id,
                    nt.node_id,
                    nt.attempt,
                    nt.iteration,
                    nt.loop_node_id,
                    nt.started_at,
                    %s as timeout_seconds
                FROM node_tasks nt
                WHERE nt.status = 'running'
                    AND nt.started_at IS NOT NULL
                    AND nt.attempt < %s
                    AND (nt.loop_node_id IS NULL OR nt.loop_node_id != nt.node_id)
                    AND nt.started_at < NOW() - INTERVAL '1 second' * %s
                ORDER BY nt.started_at ASC
            """, (default_timeout_seconds, max_retries, default_timeout_seconds))
        
        tasks = []
        for row in cursor.fetchall():
            task_dict = dict(row)
            tasks.append(task_dict)
        
        return tasks


def reset_timeout_node_task(
    conn: psycopg.Connection,
    task_id: UUID,
    retry_delay_seconds: int,
    current_iteration: Optional[int] = None
) -> bool:
    """
    重置超时的节点任务为pending，准备重试
    
    对于循环体内部节点：
    - 保持当前的 iteration 不变
    - 重置 started_at = NULL（下次执行时会更新为新的开始时间）
    - 增加 attempt 计数
    
    Args:
        conn: 数据库连接
        task_id: 任务ID
        retry_delay_seconds: 重试延迟时间（秒）
        current_iteration: 当前迭代次数（如果是循环体内部节点）
        
    Returns:
        是否重置成功
    """
    with conn.cursor() as cursor:
        # 检查 retry_delay_seconds 列是否存在
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'node_tasks' AND column_name = 'retry_delay_seconds'
        """)
        has_retry_delay_column = cursor.fetchone() is not None
        
        # 更新 attempt = attempt + 1
        # 更新 status = 'pending'
        # 更新 started_at = NULL（下次执行时会重新设置）
        # 保持 iteration 不变（如果是循环体内部节点）
        if has_retry_delay_column:
            cursor.execute("""
                UPDATE node_tasks
                SET 
                    attempt = attempt + 1,
                    status = 'pending',
                    started_at = NULL,
                    retry_delay_seconds = %s
                WHERE id = %s
            """, (retry_delay_seconds, task_id))
        else:
            cursor.execute("""
                UPDATE node_tasks
                SET 
                    attempt = attempt + 1,
                    status = 'pending',
                    started_at = NULL
                WHERE id = %s
            """, (task_id,))
        
        return cursor.rowcount > 0


def mark_workflow_failed_due_to_node_timeout(
    conn: psycopg.Connection,
    run_id: UUID,
    node_id: str,
    attempt: int,
    timeout_seconds: int
) -> bool:
    """
    标记工作流为失败（由于节点超时达到最大重试次数）
    
    Args:
        conn: 数据库连接
        run_id: 运行ID
        node_id: 超时的节点ID
        attempt: 重试次数
        timeout_seconds: 超时时间
        
    Returns:
        是否标记成功
    """
    error_info = {
        'reason': 'node_timeout',
        'node_id': node_id,
        'attempt': attempt,
        'timeout_seconds': timeout_seconds,
        'message': f'Node {node_id} exceeded max retries ({attempt}) after timeout of {timeout_seconds}s'
    }
    
    with conn.cursor() as cursor:
        # 1. 更新 workflow_runs.status = 'failed'
        cursor.execute("""
            UPDATE workflow_runs
            SET 
                status = 'failed',
                finished_at = NOW(),
                error = %s
            WHERE id = %s
        """, (json.dumps(error_info), run_id))
        
        # 2. 更新 node_tasks.status = 'failed'（所有该运行的任务）
        cursor.execute("""
            UPDATE node_tasks
            SET status = 'failed'
            WHERE run_id = %s AND status IN ('pending', 'running')
        """, (run_id,))
        
        # 3. 记录 workflow_error 日志（包含超时和重试信息）
        from src.server.workflow.db import append_log
        append_log(
            conn,
            run_id,
            'error',
            'workflow_failed',
            payload={
                **error_info,
                'reason': 'node_timeout',
                'max_retries_reached': True
            },
            node_id=node_id
        )
        
        return cursor.rowcount > 0


def get_running_tasks(conn: psycopg.Connection, run_id: UUID) -> List[Dict[str, Any]]:
    """
    获取运行中的任务
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        
    Returns:
        运行中的任务列表
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM node_tasks 
            WHERE run_id = %s AND status = 'running'
            ORDER BY run_seq ASC
        """, (run_id,))
        return [dict(row) for row in cursor.fetchall()]


# ============= 日志管理 =============

def append_log(
    conn: psycopg.Connection,
    run_id: UUID,
    level: str,
    event: str,
    payload: Optional[Dict[str, Any]] = None,
    node_id: Optional[str] = None,
) -> int:
    """
    追加运行日志
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        level: 日志级别（info, warning, error）
        event: 事件类型（node_start, node_end, node_error, workflow_start, workflow_end, workflow_error）
        payload: 事件负载（可选）
        node_id: 节点 ID（可选）
        
    Returns:
        日志序列号（seq）
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO run_logs (run_id, level, event, payload, node_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING seq
        """, (
            run_id, level, event,
            json.dumps(payload) if payload else None,
            node_id
        ))
        row = cursor.fetchone()
        return row['seq'] if row else 0


def get_run_logs(
    conn: psycopg.Connection,
    run_id: UUID,
    after_seq: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    获取运行日志（支持增量拉取）
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        after_seq: 起始序列号（可选，用于增量拉取）
        limit: 限制数量（可选）
        
    Returns:
        日志列表
    """
    query = """
        SELECT * FROM run_logs 
        WHERE run_id = %s
    """
    params = [run_id]
    
    if after_seq is not None:
        query += " AND seq > %s"
        params.append(after_seq)
    
    query += " ORDER BY seq ASC"
    
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
    
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_logs_by_node(
    conn: psycopg.Connection,
    run_id: UUID,
    node_id: str,
) -> List[Dict[str, Any]]:
    """
    获取节点的日志
    
    Args:
        conn: 数据库连接
        run_id: 运行 ID
        node_id: 节点 ID
        
    Returns:
        日志列表
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM run_logs 
            WHERE run_id = %s AND node_id = %s
            ORDER BY seq ASC
        """, (run_id, node_id))
        return [dict(row) for row in cursor.fetchall()]


# ============= 工作流CRUD =============

def create_workflow(
    conn: psycopg.Connection,
    name: str,
    description: Optional[str],
    created_by: UUID,
    status: str = 'draft',
    organization_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    workflow_id: Optional[UUID] = None,
) -> UUID:
    """
    创建工作流
    
    Args:
        conn: 数据库连接
        name: 工作流名称
        description: 描述（可选）
        created_by: 创建者ID
        status: 状态（默认'draft'）
        organization_id: 组织ID（可选）
        department_id: 部门ID（可选）
        workspace_id: 工作空间ID（可选）
        workflow_id: 工作流ID（可选，如果不提供则自动生成）
        
    Returns:
        工作流ID
    """
    if workflow_id is None:
        workflow_id = uuid4()
    
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO workflows (
                id, name, description, status, created_by,
                organization_id, department_id, workspace_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            workflow_id, name, description, status, created_by,
            organization_id, department_id, workspace_id
        ))
    
    return workflow_id


def get_workflow(conn: psycopg.Connection, workflow_id: UUID) -> Optional[Dict[str, Any]]:
    """
    获取工作流
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        
    Returns:
        工作流记录字典，如果不存在则返回None
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT w.*, u.username as created_by_name
            FROM workflows w
            LEFT JOIN users u ON w.created_by = u.id
            WHERE w.id = %s
        """, (workflow_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def update_workflow(
    conn: psycopg.Connection,
    workflow_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    current_draft_id: Optional[UUID] = None,
    current_release_id: Optional[UUID] = None,
) -> bool:
    """
    更新工作流
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        name: 名称（可选）
        description: 描述（可选）
        status: 状态（可选）
        current_draft_id: 当前草稿ID（可选）
        current_release_id: 当前发布ID（可选）
        
    Returns:
        是否更新成功
    """
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    
    if current_draft_id is not None:
        updates.append("current_draft_id = %s")
        params.append(current_draft_id)
    
    if current_release_id is not None:
        updates.append("current_release_id = %s")
        params.append(current_release_id)
    
    if not updates:
        return False
    
    params.append(workflow_id)
    
    with conn.cursor() as cursor:
        cursor.execute(f"""
            UPDATE workflows 
            SET {', '.join(updates)}
            WHERE id = %s
        """, params)
        return cursor.rowcount > 0


def delete_workflow(conn: psycopg.Connection, workflow_id: UUID) -> bool:
    """
    删除工作流（级联删除草稿和发布）
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        
    Returns:
        是否删除成功
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            DELETE FROM workflows WHERE id = %s
        """, (workflow_id,))
        return cursor.rowcount > 0


def list_workflows(
    conn: psycopg.Connection,
    status: Optional[str] = None,
    created_by: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    列出工作流
    
    Args:
        conn: 数据库连接
        status: 状态筛选（可选）
        created_by: 创建者筛选（可选）
        limit: 限制数量
        offset: 偏移量
        
    Returns:
        工作流列表
    """
    query = """
        SELECT w.*, u.username as created_by_name
        FROM workflows w
        LEFT JOIN users u ON w.created_by = u.id
        WHERE 1=1
    """
    params = []
    
    if status:
        query += " AND w.status = %s"
        params.append(status)
    
    if created_by:
        query += " AND w.created_by = %s"
        params.append(created_by)
    
    query += " ORDER BY w.created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


# ============= 草稿CRUD =============

def save_draft(
    conn: psycopg.Connection,
    workflow_id: UUID,
    graph: Dict[str, Any],
    created_by: UUID,
    is_autosave: bool = False,
    validation: Optional[Dict[str, Any]] = None,
) -> UUID:
    """
    保存工作流草稿
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        graph: 工作流图配置（包含nodes和edges）
        created_by: 创建者ID
        is_autosave: 是否为自动保存
        validation: 验证结果（可选）
        
    Returns:
        草稿ID
    """
    # 获取当前最大版本号
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT COALESCE(MAX(version), 0) + 1 as next_version
            FROM workflow_drafts
            WHERE workflow_id = %s
        """, (workflow_id,))
        row = cursor.fetchone()
        version = row['next_version'] if row else 1
    
    draft_id = uuid4()
    
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO workflow_drafts (
                id, workflow_id, version, is_autosave, graph, validation, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            draft_id, workflow_id, version, is_autosave,
            json.dumps(graph), json.dumps(validation) if validation else None, created_by
        ))
    
    # 更新工作流的current_draft_id
    update_workflow(conn, workflow_id, current_draft_id=draft_id)
    
    return draft_id


def get_draft(conn: psycopg.Connection, workflow_id: UUID, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    获取工作流草稿
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        version: 版本号（可选，不指定则获取最新版本）
        
    Returns:
        草稿记录字典，如果不存在则返回None
    """
    if version is not None:
        query = """
            SELECT * FROM workflow_drafts
            WHERE workflow_id = %s AND version = %s
        """
        params = (workflow_id, version)
    else:
        query = """
            SELECT * FROM workflow_drafts
            WHERE workflow_id = %s
            ORDER BY version DESC
            LIMIT 1
        """
        params = (workflow_id,)
    
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
        if row:
            draft = dict(row)
            # 解析JSON字段
            if isinstance(draft.get('graph'), str):
                draft['graph'] = json.loads(draft['graph'])
            if isinstance(draft.get('validation'), str):
                draft['validation'] = json.loads(draft['validation'])
            return draft
        return None


def delete_draft(conn: psycopg.Connection, workflow_id: UUID, version: Optional[int] = None) -> bool:
    """
    删除工作流草稿
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        version: 版本号（可选，不指定则删除所有版本）
        
    Returns:
        是否删除成功
    """
    if version is not None:
        query = "DELETE FROM workflow_drafts WHERE workflow_id = %s AND version = %s"
        params = (workflow_id, version)
    else:
        query = "DELETE FROM workflow_drafts WHERE workflow_id = %s"
        params = (workflow_id,)
    
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.rowcount > 0


# ============= 发布CRUD =============

def create_release(
    conn: psycopg.Connection,
    workflow_id: UUID,
    source_draft_id: UUID,
    spec: Dict[str, Any],
    checksum: str,
    created_by: UUID,
) -> UUID:
    """
    创建工作流发布
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        source_draft_id: 源草稿ID
        spec: 执行规范（编译后的配置）
        checksum: 校验和
        created_by: 创建者ID
        
    Returns:
        发布ID
    """
    # 获取当前最大发布版本号
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT COALESCE(MAX(release_version), 0) + 1 as next_version
            FROM workflow_releases
            WHERE workflow_id = %s
        """, (workflow_id,))
        row = cursor.fetchone()
        release_version = row['next_version'] if row else 1
    
    release_id = uuid4()
    
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO workflow_releases (
                id, workflow_id, release_version, source_draft_id, spec, checksum, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            release_id, workflow_id, release_version, source_draft_id,
            json.dumps(spec), checksum, created_by
        ))
    
    # 更新工作流的current_release_id和status
    update_workflow(conn, workflow_id, current_release_id=release_id, status='published')
    
    return release_id


def get_release(conn: psycopg.Connection, release_id: UUID) -> Optional[Dict[str, Any]]:
    """
    获取工作流发布
    
    Args:
        conn: 数据库连接
        release_id: 发布ID
        
    Returns:
        发布记录字典，如果不存在则返回None
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM workflow_releases WHERE id = %s
        """, (release_id,))
        row = cursor.fetchone()
        if row:
            release = dict(row)
            # 解析JSON字段
            if isinstance(release.get('spec'), str):
                release['spec'] = json.loads(release['spec'])
            return release
        return None


def list_releases(conn: psycopg.Connection, workflow_id: UUID) -> List[Dict[str, Any]]:
    """
    列出工作流的所有发布
    
    Args:
        conn: 数据库连接
        workflow_id: 工作流ID
        
    Returns:
        发布列表
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM workflow_releases
            WHERE workflow_id = %s
            ORDER BY release_version DESC
        """, (workflow_id,))
        releases = []
        for row in cursor.fetchall():
            release = dict(row)
            # 解析JSON字段
            if isinstance(release.get('spec'), str):
                release['spec'] = json.loads(release['spec'])
            releases.append(release)
        return releases

