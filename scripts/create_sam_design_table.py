#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
创建 sam_design_history 表
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.loader import get_str_env
import psycopg
from psycopg.rows import dict_row
import logging

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


def create_sam_design_table():
    """创建 sam_design_history 表"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查表是否已存在
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'sam_design_history'
                )
            """)
            table_exists = cursor.fetchone()['exists']
            
            if table_exists:
                logger.info("sam_design_history 表已存在，无需创建")
                return True
            
            logger.info("创建 sam_design_history 表...")
            cursor.execute("""
                CREATE TABLE sam_design_history (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    objective JSONB NOT NULL,
                    constraints JSONB NOT NULL,
                    execution_result JSONB NOT NULL,
                    molecules JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                
                CREATE INDEX idx_sam_design_history_user_id ON sam_design_history(user_id);
                CREATE INDEX idx_sam_design_history_created_at ON sam_design_history(created_at DESC);
            """)
            
            conn.commit()
            logger.info("✅ sam_design_history 表创建成功")
            return True
            
    except Exception as e:
        logger.error(f"创建表时出错: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    logger.info("开始创建 sam_design_history 表...")
    success = create_sam_design_table()
    if success:
        logger.info("完成！")
        sys.exit(0)
    else:
        logger.error("失败！")
        sys.exit(1)

