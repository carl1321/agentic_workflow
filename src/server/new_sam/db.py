# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
newSam执行历史记录的数据库操作函数
"""

import json
import logging
from typing import List, Dict, Any, Optional
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from datetime import datetime

logger = logging.getLogger(__name__)


def get_db_connection():
    """获取数据库连接"""
    from src.config.loader import get_str_env
    
    db_url = (
        get_str_env("DATABASE_URL") or
        get_str_env("SQLALCHEMY_DATABASE_URI") or
        get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
    )
    
    # Ensure postgresql:// format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    
    return psycopg.connect(db_url, row_factory=dict_row)


def save_execution_history(
    run_id: UUID,
    workflow_id: UUID,
    user_id: UUID,
    name: str,
    objective: Dict[str, Any],
    constraints: List[Dict[str, Any]],
    execution_state: str,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    execution_logs: Optional[List[str]] = None,
    node_outputs: Optional[Dict[str, Any]] = None,
    iteration_node_outputs: Optional[Dict[str, Any]] = None,  # Map<iter, Record<nodeId, outputs>> 序列化为对象
    iteration_snapshots: Optional[List[Dict[str, Any]]] = None,
    workflow_graph: Optional[Dict[str, Any]] = None,
    iteration_analytics: Optional[Dict[str, Any]] = None,
    candidate_molecules: Optional[List[Dict[str, Any]]] = None,
) -> UUID:
    """
    保存执行历史记录
    
    Args:
        run_id: 工作流运行ID
        workflow_id: 工作流ID
        user_id: 用户ID
        name: 执行记录名称
        objective: 研究目标
        constraints: 约束条件列表
        execution_state: 执行状态
        started_at: 开始时间
        finished_at: 结束时间
        execution_logs: 执行日志数组
        node_outputs: 所有节点的输出
        iteration_node_outputs: 按迭代组织的节点输出（Map序列化为对象）
        iteration_snapshots: 迭代快照数组
        workflow_graph: 工作流图结构
        iteration_analytics: 迭代分析数据
        candidate_molecules: 最终候选分子列表
    
    Returns:
        保存的历史记录ID
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查名称是否重复，如果重复则添加时间戳
            original_name = name
            count = 0
            while True:
                cursor.execute(
                    "SELECT id FROM new_sam_execution_history WHERE user_id = %s AND name = %s",
                    (user_id, name)
                )
                if not cursor.fetchone():
                    break
                count += 1
                name = f"{original_name} ({count})"
            
            cursor.execute("""
                INSERT INTO new_sam_execution_history (
                    run_id, workflow_id, user_id, name, objective, constraints,
                    execution_state, started_at, finished_at,
                    execution_logs, node_outputs, iteration_node_outputs,
                    iteration_snapshots, workflow_graph, iteration_analytics, candidate_molecules
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id
            """, (
                run_id,
                workflow_id,
                user_id,
                name,
                json.dumps(objective, ensure_ascii=False),
                json.dumps(constraints, ensure_ascii=False),
                execution_state,
                started_at,
                finished_at,
                json.dumps(execution_logs, ensure_ascii=False) if execution_logs else None,
                json.dumps(node_outputs, ensure_ascii=False) if node_outputs else None,
                json.dumps(iteration_node_outputs, ensure_ascii=False) if iteration_node_outputs else None,
                json.dumps(iteration_snapshots, ensure_ascii=False) if iteration_snapshots else None,
                json.dumps(workflow_graph, ensure_ascii=False) if workflow_graph else None,
                json.dumps(iteration_analytics, ensure_ascii=False) if iteration_analytics else None,
                json.dumps(candidate_molecules, ensure_ascii=False) if candidate_molecules else None,
            ))
            result = cursor.fetchone()
            conn.commit()
            return result['id']
    finally:
        conn.close()


def list_execution_history(
    user_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    获取用户的执行历史记录列表
    
    Args:
        user_id: 用户ID
        limit: 限制数量
        offset: 偏移量
    
    Returns:
        历史记录列表，每个记录包含id、name、execution_state、created_at等基本信息
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id,
                    run_id,
                    workflow_id,
                    name,
                    execution_state,
                    started_at,
                    finished_at,
                    created_at,
                    jsonb_array_length(COALESCE(candidate_molecules, '[]'::jsonb)) as molecule_count
                FROM new_sam_execution_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (user_id, limit, offset))
            rows = cursor.fetchall()
            result = []
            for row in rows:
                record = dict(row)
                # 转换datetime为ISO字符串
                for key in ['started_at', 'finished_at', 'created_at']:
                    if isinstance(record.get(key), datetime):
                        record[key] = record[key].isoformat()
                result.append(record)
            return result
    finally:
        conn.close()


def get_execution_history(
    history_id: UUID,
    user_id: UUID,
) -> Optional[Dict[str, Any]]:
    """
    获取单个执行历史记录详情
    
    Args:
        history_id: 历史记录ID
        user_id: 用户ID（用于验证所有权）
    
    Returns:
        历史记录详情，如果不存在或不属于该用户则返回None
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id,
                    run_id,
                    workflow_id,
                    user_id,
                    name,
                    objective,
                    constraints,
                    execution_state,
                    started_at,
                    finished_at,
                    execution_logs,
                    node_outputs,
                    iteration_node_outputs,
                    iteration_snapshots,
                    workflow_graph,
                    iteration_analytics,
                    candidate_molecules,
                    created_at,
                    updated_at
                FROM new_sam_execution_history
                WHERE id = %s AND user_id = %s
            """, (history_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None
            
            result = dict(row)
            # 解析JSONB字段
            jsonb_fields = [
                'objective', 'constraints', 'execution_logs', 'node_outputs',
                'iteration_node_outputs', 'iteration_snapshots', 'workflow_graph',
                'iteration_analytics', 'candidate_molecules'
            ]
            for field in jsonb_fields:
                if isinstance(result.get(field), str):
                    result[field] = json.loads(result[field])
                elif result.get(field) is None:
                    result[field] = None
            
            # 转换datetime为ISO字符串
            for key in ['started_at', 'finished_at', 'created_at', 'updated_at']:
                if isinstance(result.get(key), datetime):
                    result[key] = result[key].isoformat()
            
            return result
    finally:
        conn.close()


def delete_execution_history(
    history_id: UUID,
    user_id: UUID,
) -> bool:
    """
    删除执行历史记录
    
    Args:
        history_id: 历史记录ID
        user_id: 用户ID（用于验证所有权）
    
    Returns:
        是否删除成功
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM new_sam_execution_history
                WHERE id = %s AND user_id = %s
            """, (history_id, user_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    finally:
        conn.close()
