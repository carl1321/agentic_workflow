#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
初始化 AgenticWorkflow 数据库
创建所有必要的表结构
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from psycopg.rows import dict_row
from src.config.loader import get_str_env
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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


def create_rbac_tables(conn):
    """创建RBAC系统相关表"""
    logger.info("创建RBAC系统表...")
    
    with conn.cursor() as cursor:
        # 1. 组织表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(100) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                parent_id UUID,
                sort_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (parent_id) REFERENCES organizations(id) ON DELETE SET NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_organizations_code ON organizations(code);
            CREATE INDEX IF NOT EXISTS idx_organizations_parent_id ON organizations(parent_id);
        """)
        
        # 2. 部门表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(100) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                organization_id UUID NOT NULL,
                parent_id UUID,
                manager_id UUID,
                sort_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES departments(id) ON DELETE SET NULL,
                FOREIGN KEY (manager_id) REFERENCES users(id) ON DELETE SET NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_departments_code ON departments(code);
            CREATE INDEX IF NOT EXISTS idx_departments_organization_id ON departments(organization_id);
            CREATE INDEX IF NOT EXISTS idx_departments_parent_id ON departments(parent_id);
        """)
        
        # 3. 用户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                real_name VARCHAR(255),
                phone VARCHAR(50),
                organization_id UUID,
                department_id UUID,
                is_superuser BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                data_permission_level VARCHAR(20) DEFAULT 'self',
                last_login_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_organization_id ON users(organization_id);
            CREATE INDEX IF NOT EXISTS idx_users_department_id ON users(department_id);
        """)
        
        # 4. 角色表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(100) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                organization_id UUID,
                data_permission_level VARCHAR(20) DEFAULT 'self',
                is_system BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_roles_code ON roles(code);
            CREATE INDEX IF NOT EXISTS idx_roles_organization_id ON roles(organization_id);
        """)
        
        # 5. 权限表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(100) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                resource VARCHAR(100) NOT NULL,
                action VARCHAR(50) NOT NULL,
                description TEXT,
                is_system BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_permissions_code ON permissions(code);
            CREATE INDEX IF NOT EXISTS idx_permissions_resource_action ON permissions(resource, action);
        """)
        
        # 6. 菜单表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS menus (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(100) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                path VARCHAR(500),
                icon VARCHAR(100),
                component VARCHAR(255),
                menu_type VARCHAR(50) DEFAULT 'menu',
                permission_code VARCHAR(100),
                is_visible BOOLEAN DEFAULT TRUE,
                is_system BOOLEAN DEFAULT FALSE,
                parent_id UUID,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (parent_id) REFERENCES menus(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_menus_code ON menus(code);
            CREATE INDEX IF NOT EXISTS idx_menus_parent_id ON menus(parent_id);
            CREATE INDEX IF NOT EXISTS idx_menus_permission_code ON menus(permission_code);
        """)
        
        # 7. 用户角色关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                role_id UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);
        """)
        
        # 8. 角色权限关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                role_id UUID NOT NULL,
                permission_id UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(role_id, permission_id),
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON role_permissions(role_id);
            CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_id ON role_permissions(permission_id);
        """)
        
        # 9. 角色菜单关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_menus (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                role_id UUID NOT NULL,
                menu_id UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(role_id, menu_id),
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (menu_id) REFERENCES menus(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_role_menus_role_id ON role_menus(role_id);
            CREATE INDEX IF NOT EXISTS idx_role_menus_menu_id ON role_menus(menu_id);
        """)
        
        # 10. 用户会话表（用于token黑名单）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                token_jti VARCHAR(255) NOT NULL UNIQUE,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_token_jti ON user_sessions(token_jti);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
        """)
        
        conn.commit()
        logger.info("RBAC系统表创建完成")


def create_workflow_tables(conn):
    """创建工作流相关表"""
    logger.info("创建工作流系统表...")
    
    with conn.cursor() as cursor:
        # 1. 工作流表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                description TEXT,
                status VARCHAR(50) DEFAULT 'draft',
                created_by UUID NOT NULL,
                organization_id UUID,
                department_id UUID,
                workspace_id UUID,
                current_draft_id UUID,
                current_release_id UUID,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_workflows_created_by ON workflows(created_by);
            CREATE INDEX IF NOT EXISTS idx_workflows_organization_id ON workflows(organization_id);
            CREATE INDEX IF NOT EXISTS idx_workflows_department_id ON workflows(department_id);
            CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
        """)
        
        # 2. 工作流草稿表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_drafts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID NOT NULL,
                version INTEGER NOT NULL,
                is_autosave BOOLEAN DEFAULT FALSE,
                graph JSONB NOT NULL,
                validation JSONB,
                created_by UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(workflow_id, version),
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
            );
            
            CREATE INDEX IF NOT EXISTS idx_workflow_drafts_workflow_id ON workflow_drafts(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_drafts_version ON workflow_drafts(workflow_id, version);
        """)
        
        # 3. 工作流发布表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_releases (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID NOT NULL,
                release_version VARCHAR(50) NOT NULL,
                source_draft_id UUID,
                spec JSONB NOT NULL,
                checksum VARCHAR(64),
                created_by UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(workflow_id, release_version),
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
                FOREIGN KEY (source_draft_id) REFERENCES workflow_drafts(id) ON DELETE SET NULL,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
            );
            
            CREATE INDEX IF NOT EXISTS idx_workflow_releases_workflow_id ON workflow_releases(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_releases_version ON workflow_releases(workflow_id, release_version);
        """)
        
        # 4. 工作流运行表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID NOT NULL,
                release_id UUID NOT NULL,
                status VARCHAR(50) DEFAULT 'queued',
                input JSONB,
                output JSONB,
                error JSONB,
                started_at TIMESTAMP WITH TIME ZONE,
                finished_at TIMESTAMP WITH TIME ZONE,
                heartbeat_at TIMESTAMP WITH TIME ZONE,
                created_by UUID NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
                FOREIGN KEY (release_id) REFERENCES workflow_releases(id) ON DELETE RESTRICT,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
            );
            
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_release_id ON workflow_runs(release_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at ON workflow_runs(created_at);
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_heartbeat_at ON workflow_runs(heartbeat_at);
        """)
        
        # 5. 节点任务表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_id UUID NOT NULL,
                node_id VARCHAR(255) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                attempt INTEGER DEFAULT 1,
                input JSONB,
                output JSONB,
                error JSONB,
                metrics JSONB,
                started_at TIMESTAMP WITH TIME ZONE,
                finished_at TIMESTAMP WITH TIME ZONE,
                parent_task_id UUID,
                branch_id VARCHAR(255),
                iteration INTEGER,
                loop_node_id VARCHAR(255),
                run_seq INTEGER,
                timeout_seconds INTEGER,
                retry_delay_seconds INTEGER,
                FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_task_id) REFERENCES node_tasks(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_node_tasks_run_id ON node_tasks(run_id);
            CREATE INDEX IF NOT EXISTS idx_node_tasks_node_id ON node_tasks(node_id);
            CREATE INDEX IF NOT EXISTS idx_node_tasks_status ON node_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_node_tasks_run_seq ON node_tasks(run_id, run_seq);
            CREATE INDEX IF NOT EXISTS idx_node_tasks_started_at ON node_tasks(started_at);
        """)
        
        # 6. 运行日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_id UUID NOT NULL,
                seq INTEGER NOT NULL,
                level VARCHAR(20) NOT NULL,
                event VARCHAR(100) NOT NULL,
                payload JSONB,
                node_id VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                UNIQUE(run_id, seq),
                FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_run_logs_run_id ON run_logs(run_id);
            CREATE INDEX IF NOT EXISTS idx_run_logs_seq ON run_logs(run_id, seq);
            CREATE INDEX IF NOT EXISTS idx_run_logs_event ON run_logs(event);
            CREATE INDEX IF NOT EXISTS idx_run_logs_node_id ON run_logs(node_id);
            CREATE INDEX IF NOT EXISTS idx_run_logs_created_at ON run_logs(created_at);
        """)
        
        conn.commit()
        logger.info("工作流系统表创建完成")


def create_chat_tables(conn):
    """创建聊天相关表"""
    logger.info("创建聊天系统表...")
    
    with conn.cursor() as cursor:
        # 聊天流表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_streams (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                thread_id VARCHAR(255) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL DEFAULT '新对话',
                messages JSONB NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_chat_streams_thread_id ON chat_streams(thread_id);
            CREATE INDEX IF NOT EXISTS idx_chat_streams_created_at ON chat_streams(created_at);
            CREATE INDEX IF NOT EXISTS idx_chat_streams_updated_at ON chat_streams(updated_at);
        """)
        
        conn.commit()
        logger.info("聊天系统表创建完成")


def create_data_extraction_tables(conn):
    """创建数据提取相关表"""
    logger.info("创建数据提取系统表...")
    
    with conn.cursor() as cursor:
        # 1. 数据提取文件表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_extraction_files (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL UNIQUE,
                task_name VARCHAR(255),
                extraction_type VARCHAR(50) NOT NULL,
                file_name VARCHAR(255),
                file_size BIGINT,
                file_base64 TEXT,
                pdf_url TEXT,
                model_name VARCHAR(100),
                metadata JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_data_extraction_files_task_id ON data_extraction_files(task_id);
            CREATE INDEX IF NOT EXISTS idx_data_extraction_files_created_at ON data_extraction_files(created_at DESC);
        """)
        
        # 2. 数据提取分类表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_extraction_categories (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL UNIQUE,
                categories JSONB NOT NULL,
                result_json TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (task_id) REFERENCES data_extraction_files(task_id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_data_extraction_categories_task_id ON data_extraction_categories(task_id);
        """)
        
        # 3. 数据提取数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_extraction_data (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL UNIQUE,
                selected_categories JSONB NOT NULL,
                table_data JSONB NOT NULL,
                result_json TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                FOREIGN KEY (task_id) REFERENCES data_extraction_files(task_id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_data_extraction_data_task_id ON data_extraction_data(task_id);
        """)
        
        conn.commit()
        logger.info("数据提取系统表创建完成")


def create_sam_design_tables(conn):
    """创建SAM分子设计历史记录表"""
    logger.info("创建SAM分子设计历史记录表...")
    
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sam_design_history (
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
            
            CREATE INDEX IF NOT EXISTS idx_sam_design_history_user_id ON sam_design_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_sam_design_history_created_at ON sam_design_history(created_at DESC);
        """)
        
        conn.commit()
        logger.info("SAM分子设计历史记录表创建完成")


def init_database():
    """初始化数据库"""
    logger.info("开始初始化数据库...")
    
    try:
        conn = get_db_connection()
        logger.info("数据库连接成功")
        
        # 创建所有表
        create_rbac_tables(conn)
        create_workflow_tables(conn)
        create_chat_tables(conn)
        create_data_extraction_tables(conn)
        create_sam_design_tables(conn)
        
        logger.info("数据库初始化完成！")
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    init_database()

