#!/usr/bin/env python3
"""
删除执行中的工作流任务脚本

此脚本会删除所有状态为 'queued' 或 'running' 的工作流运行记录
以及相关的节点任务和运行日志

使用方法:
    python scripts/delete_running_tasks.py

或者指定数据库URL:
    DATABASE_URL=postgresql://user:pass@host:port/dbname python scripts/delete_running_tasks.py
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.server.workflow.db import get_db_connection
from datetime import datetime

def delete_running_tasks(dry_run: bool = False):
    """
    删除执行中的任务
    
    Args:
        dry_run: 如果为True，只显示将要删除的任务，不实际删除
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. 查看当前执行中的任务数量
            print("=" * 60)
            print("当前执行中的任务统计:")
            print("=" * 60)
            cursor.execute("""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM workflow_runs
                WHERE status IN ('queued', 'running')
                GROUP BY status
                ORDER BY status
            """)
            stats = cursor.fetchall()
            if stats:
                for row in stats:
                    print(f"  {row['status']}: {row['count']} 个任务")
            else:
                print("  没有执行中的任务")
            print()
            
            # 2. 查看将要删除的任务详情
            print("=" * 60)
            print("将要删除的任务详情:")
            print("=" * 60)
            cursor.execute("""
                SELECT 
                    id,
                    workflow_id,
                    status,
                    created_at,
                    started_at,
                    heartbeat_at
                FROM workflow_runs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at DESC
            """)
            tasks = cursor.fetchall()
            if tasks:
                for task in tasks:
                    print(f"  Run ID: {task['id']}")
                    print(f"    Workflow ID: {task['workflow_id']}")
                    print(f"    Status: {task['status']}")
                    print(f"    Created: {task['created_at']}")
                    if task['started_at']:
                        print(f"    Started: {task['started_at']}")
                    if task['heartbeat_at']:
                        print(f"    Heartbeat: {task['heartbeat_at']}")
                    print()
            else:
                print("  没有需要删除的任务")
                return
            
            if dry_run:
                print("=" * 60)
                print("这是预览模式，不会实际删除数据")
                print("要实际删除，请运行: python scripts/delete_running_tasks.py --execute")
                print("=" * 60)
                return
            
            # 3. 确认删除
            print("=" * 60)
            print(f"即将删除 {len(tasks)} 个执行中的任务及其相关数据")
            print("=" * 60)
            confirm = input("确认删除? (yes/no): ").strip().lower()
            if confirm != 'yes':
                print("已取消删除操作")
                return
            
            # 4. 删除相关的节点任务
            print("\n正在删除节点任务...")
            cursor.execute("""
                DELETE FROM node_tasks
                WHERE run_id IN (
                    SELECT id FROM workflow_runs
                    WHERE status IN ('queued', 'running')
                )
            """)
            node_tasks_deleted = cursor.rowcount
            print(f"  已删除 {node_tasks_deleted} 条节点任务记录")
            
            # 5. 删除相关的运行日志
            print("正在删除运行日志...")
            cursor.execute("""
                DELETE FROM run_logs
                WHERE run_id IN (
                    SELECT id FROM workflow_runs
                    WHERE status IN ('queued', 'running')
                )
            """)
            logs_deleted = cursor.rowcount
            print(f"  已删除 {logs_deleted} 条运行日志记录")
            
            # 6. 删除执行中的工作流运行记录
            print("正在删除工作流运行记录...")
            cursor.execute("""
                DELETE FROM workflow_runs
                WHERE status IN ('queued', 'running')
            """)
            runs_deleted = cursor.rowcount
            print(f"  已删除 {runs_deleted} 条工作流运行记录")
            
            # 提交事务
            conn.commit()
            
            print("\n" + "=" * 60)
            print("删除完成!")
            print(f"  工作流运行: {runs_deleted} 条")
            print(f"  节点任务: {node_tasks_deleted} 条")
            print(f"  运行日志: {logs_deleted} 条")
            print("=" * 60)
            
            # 7. 验证删除结果
            print("\n验证删除结果:")
            cursor.execute("""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM workflow_runs
                GROUP BY status
                ORDER BY status
            """)
            remaining = cursor.fetchall()
            if remaining:
                print("  剩余任务统计:")
                for row in remaining:
                    print(f"    {row['status']}: {row['count']} 个任务")
            else:
                print("  没有剩余的任务")
                
    except Exception as e:
        conn.rollback()
        print(f"\n错误: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="删除执行中的工作流任务")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际执行删除操作（默认是预览模式）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式，只显示将要删除的任务，不实际删除"
    )
    
    args = parser.parse_args()
    
    # 如果指定了 --execute，则执行删除；否则是预览模式
    dry_run = not args.execute
    
    if args.dry_run:
        dry_run = True
    
    delete_running_tasks(dry_run=dry_run)

