# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流 Worker 服务
从数据库队列获取任务，使用 SKIP LOCKED 避免并发冲突
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env
from src.server.workflow.db import (
    acquire_run,
    detect_timeout_node_tasks,
    get_db_connection,
    get_retry_delay,
    mark_workflow_failed_due_to_node_timeout,
    reset_stale_runs,
    reset_timeout_node_task,
    update_run_heartbeat,
    update_run_status,
)

logger = logging.getLogger(__name__)


class WorkflowWorker:
    """工作流 Worker 服务"""
    
    def __init__(
        self,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 30.0,
        stale_timeout_minutes: int = 5,
    ):
        """
        初始化 Worker
        
        Args:
            poll_interval: 轮询间隔（秒）
            heartbeat_interval: 心跳更新间隔（秒）
            stale_timeout_minutes: 僵尸任务超时时间（分钟）
        """
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.stale_timeout_minutes = stale_timeout_minutes
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._current_run_id: Optional[UUID] = None
        self._executor = None  # 将在后续阶段设置
        self._wake_event: Optional[asyncio.Event] = None  # 用于立即唤醒worker
    
    def set_executor(self, executor):
        """设置执行器（延迟注入）"""
        self._executor = executor
    
    async def start(self):
        """启动 worker 循环"""
        if self._running:
            logger.warning("Worker is already running")
            return
        
        self._running = True
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._worker_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Workflow worker started")
    
    def wake(self):
        """立即唤醒worker检查新任务（非阻塞）"""
        if self._wake_event:
            self._wake_event.set()
    
    async def stop(self):
        """停止 worker"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Workflow worker stopped")
    
    async def _worker_loop(self):
        """Worker 主循环"""
        while self._running:
            try:
                # 重置僵尸任务
                conn = get_db_connection()
                try:
                    # 1. 检测并重置超时的节点任务（排除循环体节点本身）
                    timeout_tasks = detect_timeout_node_tasks(conn, max_retries=4)
                    for task in timeout_tasks:
                        attempt = task['attempt']
                        retry_delay = get_retry_delay(attempt)  # 新的延迟规则
                        current_iteration = task.get('iteration')  # 循环体内部节点的迭代次数
                        
                        # 检查是否达到最大重试次数
                        if attempt >= 4:
                            # 标记工作流为失败
                            mark_workflow_failed_due_to_node_timeout(
                                conn,
                                task['run_id'],
                                task['node_id'],
                                attempt,
                                task.get('timeout_seconds', 300)
                            )
                            logger.error(
                                f"[WORKER] Node {task['node_id']} reached max retries ({attempt}), "
                                f"marking workflow {task['run_id']} as failed"
                            )
                        else:
                            # 重置任务为pending，准备重试
                            reset_timeout_node_task(
                                conn, 
                                task['task_id'], 
                                retry_delay,
                                current_iteration=current_iteration
                            )
                            
                            node_type = "循环体内部节点" if task.get('loop_node_id') else "普通节点"
                            logger.info(
                                f"[WORKER] Reset timeout {node_type} task {task['task_id']}, "
                                f"node_id={task['node_id']}, "
                                f"iteration={current_iteration}, "
                                f"attempt {attempt}, "
                                f"retry_delay {retry_delay}s"
                            )
                    
                    # 2. 重置僵尸工作流（现有逻辑）
                    reset_count = reset_stale_runs(conn, self.stale_timeout_minutes)
                    if reset_count > 0:
                        logger.info(f"[WORKER] Reset {reset_count} stale runs")
                    conn.commit()
                finally:
                    conn.close()
                
                # 获取并执行任务
                await self._try_execute_run()
                
                # 等待轮询间隔或立即唤醒事件
                if self._wake_event:
                    try:
                        # 使用wait_for实现超时，如果被唤醒则立即继续
                        await asyncio.wait_for(self._wake_event.wait(), timeout=self.poll_interval)
                        self._wake_event.clear()  # 清除事件标志
                        logger.debug("[WORKER] Woken up to check for new tasks")
                    except asyncio.TimeoutError:
                        # 超时是正常的，继续下一次循环
                        pass
                else:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)
    
    async def _try_execute_run(self):
        """尝试获取并执行运行任务"""
        conn = get_db_connection()
        try:
            # 使用事务获取任务
            with conn.transaction():
                run = acquire_run(conn)
                if not run:
                    return
                
                run_id = run['id']
                logger.info(f"Acquired run: {run_id}")
                
                # 更新状态为 running（事务会自动提交）
                update_run_status(
                    conn,
                    run_id,
                    'running',
                    started_at=run.get('started_at') or None,
                )
            
            # 在事务外执行任务
            self._current_run_id = run_id
            try:
                await self._execute_run(run)
            finally:
                self._current_run_id = None
        except Exception as e:
            logger.error(f"Error executing run {run.get('id') if run else 'unknown'}: {e}", exc_info=True)
            # 更新运行状态为 failed
            if run:
                conn = get_db_connection()
                try:
                    update_run_status(
                        conn,
                        run['id'],
                        'failed',
                        error={'error': str(e)},
                        finished_at=None,
                    )
                    conn.commit()
                finally:
                    conn.close()
        finally:
            conn.close()
    
    async def _execute_run(self, run: dict):
        """
        执行运行任务
        
        Args:
            run: 运行记录字典
        """
        if not self._executor:
            logger.error("Executor not set, cannot execute run")
            return
        
        run_id = run['id']
        logger.info(f"Executing run: {run_id}")
        
        try:
            # 调用执行器执行运行
            await self._executor.execute_run(run_id)
        except Exception as e:
            logger.error(f"Error in executor for run {run_id}: {e}", exc_info=True)
            raise
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                if self._current_run_id:
                    conn = get_db_connection()
                    try:
                        update_run_heartbeat(conn, self._current_run_id)
                        conn.commit()
                    finally:
                        conn.close()
                
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}", exc_info=True)
                await asyncio.sleep(self.heartbeat_interval)


# 全局 worker 实例
_worker_instance: Optional[WorkflowWorker] = None


def get_workflow_worker() -> WorkflowWorker:
    """获取 worker 实例（单例）"""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = WorkflowWorker()
    return _worker_instance

