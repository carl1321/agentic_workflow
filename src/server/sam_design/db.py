# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
SAM设计历史记录的数据库操作函数
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


def save_design_history(
    user_id: UUID,
    name: str,
    objective: Dict[str, Any],
    constraints: List[Dict[str, Any]],
    execution_result: Dict[str, Any],
    molecules: List[Dict[str, Any]],
) -> UUID:
    """
    保存设计历史记录
    
    Args:
        user_id: 用户ID
        name: 历史记录名称
        objective: 研究目标
        constraints: 约束条件列表
        execution_result: 执行结果
        molecules: 分子数据列表
    
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
                    "SELECT id FROM sam_design_history WHERE user_id = %s AND name = %s",
                    (user_id, name)
                )
                if not cursor.fetchone():
                    break
                count += 1
                name = f"{original_name} ({count})"
            
            cursor.execute("""
                INSERT INTO sam_design_history (
                    user_id, name, objective, constraints, execution_result, molecules
                ) VALUES (
                    %s, %s, %s, %s, %s, %s
                ) RETURNING id
            """, (
                user_id,
                name,
                json.dumps(objective, ensure_ascii=False),
                json.dumps(constraints, ensure_ascii=False),
                json.dumps(execution_result, ensure_ascii=False),
                json.dumps(molecules, ensure_ascii=False),
            ))
            result = cursor.fetchone()
            conn.commit()
            return result['id']
    finally:
        conn.close()


def get_design_history_list(
    user_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    获取用户的设计历史记录列表
    
    Args:
        user_id: 用户ID
        limit: 限制数量
        offset: 偏移量
    
    Returns:
        历史记录列表，每个记录包含id、name、created_at、molecules数量
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id,
                    name,
                    created_at,
                    jsonb_array_length(molecules) as molecule_count
                FROM sam_design_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (user_id, limit, offset))
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_design_history(
    history_id: UUID,
    user_id: UUID,
) -> Optional[Dict[str, Any]]:
    """
    获取单个设计历史记录
    
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
                    name,
                    objective,
                    constraints,
                    execution_result,
                    molecules,
                    created_at
                FROM sam_design_history
                WHERE id = %s AND user_id = %s
            """, (history_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None
            
            result = dict(row)
            # 解析JSONB字段
            if isinstance(result.get('objective'), str):
                result['objective'] = json.loads(result['objective'])
            if isinstance(result.get('constraints'), str):
                result['constraints'] = json.loads(result['constraints'])
            if isinstance(result.get('execution_result'), str):
                result['execution_result'] = json.loads(result['execution_result'])
            if isinstance(result.get('molecules'), str):
                result['molecules'] = json.loads(result['molecules'])
            
            # 转换datetime为ISO字符串
            if isinstance(result.get('created_at'), datetime):
                result['created_at'] = result['created_at'].isoformat()
            
            return result
    finally:
        conn.close()


def delete_design_history(
    history_id: UUID,
    user_id: UUID,
) -> bool:
    """
    删除设计历史记录
    
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
                DELETE FROM sam_design_history
                WHERE id = %s AND user_id = %s
            """, (history_id, user_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    finally:
        conn.close()

