#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
修复 node_tasks 表中字段类型
将错误类型（UUID）改为正确的 VARCHAR(255) 以匹配节点 ID 格式
需要修复的字段：loop_node_id, node_id, branch_id
"""

import sys
import os
import logging
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 使用后端代码中的配置加载和数据库连接方式
from src.config.loader import get_str_env
import psycopg
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db_connection():
    """获取数据库连接（从 conf.yaml 读取配置）"""
    db_url = (
        get_str_env("DATABASE_URL") or
        get_str_env("SQLALCHEMY_DATABASE_URI") or
        get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
    )
    
    # Ensure postgresql:// format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    
    logger.info(f"连接数据库: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    return psycopg.connect(db_url, row_factory=dict_row)


def fix_column_type(conn, cursor, column_name, table_name='node_tasks'):
    """修复单个字段类型"""
    try:
        # 1. 检查当前字段类型
        cursor.execute("""
            SELECT data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        row = cursor.fetchone()
        
        if not row:
            logger.warning(f"{column_name} 字段不存在，跳过")
            return True
        
        # 使用字典方式访问（因为使用了 dict_row）
        current_type = row.get('data_type') or row.get(0)
        udt_name = row.get('udt_name') or row.get(1)
        logger.info(f"当前 {column_name} 字段类型: {current_type} ({udt_name})")
        
        # 2. 如果已经是 VARCHAR，则不需要修改
        if current_type == 'character varying' or udt_name == 'varchar':
            logger.info(f"{column_name} 字段已经是 VARCHAR 类型，无需修改")
            return True
        
        # 3. 如果是 UUID 类型，需要修改为 VARCHAR(255)
        if current_type == 'uuid' or udt_name == 'uuid':
            logger.info(f"检测到 {column_name} 字段是 UUID 类型，开始修改为 VARCHAR(255)...")
            
            # 先删除可能存在的约束
            try:
                cursor.execute("""
                    SELECT constraint_name 
                    FROM information_schema.table_constraints 
                    WHERE table_name = %s 
                    AND constraint_type = 'FOREIGN KEY'
                    AND constraint_name LIKE %s
                """, (table_name, f'%{column_name}%'))
                fk_constraints = cursor.fetchall()
                for fk in fk_constraints:
                    logger.info(f"删除外键约束: {fk[0]}")
                    cursor.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {fk[0]}")
            except Exception as e:
                logger.warning(f"删除外键约束时出错（可能不存在）: {e}")
            
            # 先清空所有非 NULL 的值（因为它们可能是无效的 UUID）
            logger.info(f"清空 {column_name} 字段中的无效数据...")
            cursor.execute(f"""
                UPDATE {table_name} 
                SET {column_name} = NULL 
                WHERE {column_name} IS NOT NULL 
                AND {column_name}::text !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
            """)
            
            # 将 UUID 类型转换为 VARCHAR(255)
            logger.info(f"将 {column_name} 字段类型从 UUID 改为 VARCHAR(255)...")
            cursor.execute(f"""
                ALTER TABLE {table_name} 
                ALTER COLUMN {column_name} TYPE VARCHAR(255) 
                USING CASE 
                    WHEN {column_name} IS NULL THEN NULL 
                    ELSE {column_name}::text 
                END
            """)
            
            logger.info(f"✅ {column_name} 字段类型修改成功")
            return True
        else:
            logger.warning(f"未知的字段类型: {current_type} ({udt_name})，跳过")
            return True
            
    except Exception as e:
        logger.error(f"修复 {column_name} 字段类型时出错: {e}", exc_info=True)
        raise


def fix_node_tasks_columns():
    """修复 node_tasks 表中所有需要修复的字段类型"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 需要修复的字段列表（应该是 VARCHAR(255)，但可能是 UUID）
            columns_to_fix = ['loop_node_id', 'node_id', 'branch_id']
            
            for column_name in columns_to_fix:
                logger.info(f"\n检查字段: {column_name}")
                fix_column_type(conn, cursor, column_name)
            
            conn.commit()
            logger.info("\n✅ 所有字段类型修复完成")
            return True
                
    except Exception as e:
        logger.error(f"修复字段类型时出错: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    logger.info("开始修复 node_tasks 表字段类型...")
    success = fix_node_tasks_columns()
    if success:
        logger.info("修复完成！")
        sys.exit(0)
    else:
        logger.error("修复失败！")
        sys.exit(1)

