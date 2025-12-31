# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流执行器（重构版）

支持 worker 异步执行和状态的动态管理
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from src.config.loader import get_str_env
from src.server.workflow.db import (
    append_log,
    get_db_connection,
    get_run_tasks,
    update_run_status,
)
from src.server.workflow.state_manager import DatabaseStateManager
from src.server.workflow_request import WorkflowConfigRequest
from src.workflow.compiler import compile_workflow_to_langgraph

logger = logging.getLogger(__name__)


class ExecutionContext:
    """执行上下文"""
    
    def __init__(
        self,
        run_id: UUID,
        state_manager: DatabaseStateManager,
        db_conn: psycopg.Connection,
        checkpoint: Optional[AsyncPostgresSaver] = None,
        event_queue: Optional[asyncio.Queue] = None,
    ):
        self.run_id = run_id
        self.state_manager = state_manager
        self.db_conn = db_conn
        self.checkpoint = checkpoint
        self.event_queue = event_queue


class WorkflowExecutor:
    """工作流执行器（重构版）"""
    
    def __init__(self):
        """初始化执行器"""
        self._checkpoint_pool: Optional[AsyncConnectionPool] = None
    
    async def _get_checkpoint_pool(self) -> AsyncConnectionPool:
        """获取检查点连接池"""
        if self._checkpoint_pool is None:
            db_url = (
                get_str_env("DATABASE_URL") or
                get_str_env("SQLALCHEMY_DATABASE_URI") or
                get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
            )
            
            # Ensure postgresql:// format
            if db_url.startswith("postgresql://"):
                db_url = db_url.replace("postgresql://", "postgres://", 1)
            
            connection_kwargs = {
                "autocommit": True,
                "row_factory": "dict_row",
                "prepare_threshold": 0,
            }
            self._checkpoint_pool = AsyncConnectionPool(
                db_url,
                min_size=1,
                max_size=10,
                kwargs=connection_kwargs,
            )
        return self._checkpoint_pool
    
    async def create_run(
        self,
        workflow_id: UUID,
        release_id: UUID,
        inputs: Dict[str, Any],
        created_by: UUID,
    ) -> UUID:
        """
        创建工作流运行记录
        
        Args:
            workflow_id: 工作流 ID
            release_id: 发布版本 ID
            inputs: 输入数据
            created_by: 创建者 ID
            
        Returns:
            运行 ID
        """
        run_id = UUID(int=0)  # 将由数据库生成
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO workflow_runs (
                        workflow_id, release_id, status, input, created_by
                    ) VALUES (%s, %s, 'queued', %s, %s)
                    RETURNING id
                """, (
                    workflow_id,
                    release_id,
                    json.dumps(inputs),
                    created_by,
                ))
                row = cursor.fetchone()
                run_id = row['id']
                conn.commit()
                
                logger.info(f"Created run {run_id} for workflow {workflow_id}")
        finally:
            conn.close()
        
        # 立即唤醒worker检查新任务
        try:
            from src.server.workflow.worker import get_workflow_worker
            worker = get_workflow_worker()
            worker.wake()
            logger.debug(f"[EXECUTOR] Woke up worker after creating run {run_id}")
        except Exception as e:
            logger.warning(f"[EXECUTOR] Failed to wake worker: {e}")
        
        return run_id
    
    async def execute_run(self, run_id: UUID):
        """
        执行运行（由 worker 调用）
        
        Args:
            run_id: 运行 ID
        """
        conn = get_db_connection()
        try:
            # 获取运行信息
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT wr.*, wrr.spec, wrr.workflow_id
                    FROM workflow_runs wr
                    JOIN workflow_releases wrr ON wr.release_id = wrr.id
                    WHERE wr.id = %s
                """, (run_id,))
                run = cursor.fetchone()
                if not run:
                    raise ValueError(f"Run {run_id} not found")
            
            # 加载工作流配置
            spec = run['spec']
            if isinstance(spec, str):
                spec = json.loads(spec)
            
            # 如果 spec 中没有 name 字段，从数据库获取工作流名称
            if 'name' not in spec or not spec['name']:
                workflow_id = run['workflow_id']
                from src.server.workflow.db import get_workflow
                workflow = get_workflow(conn, workflow_id)
                if workflow:
                    spec['name'] = workflow.get('name', '未命名工作流')
                else:
                    spec['name'] = '未命名工作流'
            
            config = WorkflowConfigRequest(**spec)
            
            # 解析输入
            inputs = run['input']
            if isinstance(inputs, str):
                inputs = json.loads(inputs)
            
            # 初始化状态管理器
            state_manager = DatabaseStateManager(run_id, db_conn=conn)
            
            # 创建检查点
            checkpoint_pool = await self._get_checkpoint_pool()
            checkpointer = AsyncPostgresSaver(checkpoint_pool)
            await checkpointer.setup()
            
            # 创建执行上下文
            context = ExecutionContext(
                run_id=run_id,
                state_manager=state_manager,
                db_conn=conn,
                checkpoint=checkpointer,
            )
            
            # 记录工作流开始
            append_log(conn, run_id, 'info', 'workflow_start', payload={'workflow_id': str(run['workflow_id'])})
            conn.commit()
            
            try:
                # 编译工作流
                logger.info(f"Compiling workflow for run {run_id}")
                graph = compile_workflow_to_langgraph(config)
                logger.info(f"Workflow compiled successfully for run {run_id}")
                
                # 将状态管理器添加到初始状态中
                initial_state = {
                    "workflow_inputs": inputs,
                    "state_manager": state_manager,  # 传递状态管理器
                    "node_outputs": {},  # 初始化节点输出
                }
                logger.info(f"Initial state prepared for run {run_id}, state_manager present: {state_manager is not None}, state keys: {list(initial_state.keys())}")
                
                # 执行工作流
                thread_id = f"workflow_run_{run_id}"
                logger.info(f"Starting graph execution for run {run_id}, thread_id: {thread_id}")
                result = await graph.ainvoke(
                    initial_state,
                    config={"configurable": {"thread_id": thread_id}},
                )
                logger.info(f"Graph execution completed for run {run_id}, result is None: {result is None}")
                
                # 获取最终输出
                if result is None:
                    logger.warning(f"Graph execution returned None for run {run_id}, attempting to recover state from checkpoint")
                    # 尝试从检查点恢复状态
                    try:
                        # 从检查点获取最新状态
                        checkpoint_state = await checkpointer.aget({"configurable": {"thread_id": thread_id}})
                        if checkpoint_state:
                            logger.info(f"Recovered state from checkpoint for run {run_id}")
                            final_output = checkpoint_state.get("node_outputs", {}) if isinstance(checkpoint_state, dict) else {}
                        else:
                            logger.warning(f"No checkpoint state found for run {run_id}, using empty output")
                            final_output = {}
                    except Exception as e:
                        logger.error(f"Error recovering state from checkpoint for run {run_id}: {e}", exc_info=True)
                        final_output = {}
                else:
                    final_output = result.get("node_outputs", {}) if isinstance(result, dict) else {}
                    logger.debug(f"Final output extracted for run {run_id}, node count: {len(final_output)}")
                
                # 更新运行状态为成功
                update_run_status(
                    conn,
                    run_id,
                    'success',
                    output=final_output,
                    finished_at=datetime.now(),
                )
                conn.commit()
                
                # 记录工作流结束
                append_log(conn, run_id, 'info', 'workflow_end', payload={'status': 'success'})
                conn.commit()
                
                logger.info(f"Run {run_id} completed successfully")
            except Exception as e:
                logger.error(f"Error executing run {run_id}: {e}", exc_info=True)
                
                # 更新运行状态为失败
                update_run_status(
                    conn,
                    run_id,
                    'failed',
                    error={'error': str(e)},
                    finished_at=datetime.now(),
                )
                conn.commit()
                
                # 记录工作流错误
                append_log(conn, run_id, 'error', 'workflow_error', payload={'error': str(e)})
                conn.commit()
                
                raise
        finally:
            conn.close()
    
    async def execute_run_stream(self, run_id: UUID):
        """
        流式执行运行（SSE）
        
        API 只负责创建任务并轮询日志，实际执行由 Worker 负责
        
        Args:
            run_id: 运行 ID
            
        Yields:
            SSE 事件字符串
        """
        # 发送初始事件
        yield f"data: {json.dumps({'type': 'run_start', 'run_id': str(run_id)})}\n\n"
        
        # 轮询日志并发送事件
        last_seq = 0
        conn = get_db_connection()
        try:
            # 继续轮询直到任务完成且没有新日志
            max_empty_polls = 10  # 最多连续10次空轮询后停止
            empty_polls = 0
            task_completed = False
            post_completion_polls = 0  # 任务完成后的轮询次数
            max_post_completion_polls = 10  # 任务完成后最多再轮询10次
            
            while True:
                # 获取新日志
                from src.server.workflow.db import get_run_logs
                logs = get_run_logs(conn, run_id, after_seq=last_seq)
                
                if logs:
                    empty_polls = 0
                    post_completion_polls = 0  # 有新日志时重置
                    for log in logs:
                        # 解析 payload（可能是 JSON 字符串）
                        payload = log.get('payload')
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except (json.JSONDecodeError, TypeError):
                                pass  # 保持原样
                        
                        node_id = log.get('node_id')
                        event_type = log.get('event')
                        
                        # 调试日志
                        logger.debug(f"SSE Event: event={event_type}, node_id={node_id}, payload={payload}")
                        
                        # 检查是否是工作流结束事件
                        if event_type == 'workflow_end':
                            task_completed = True
                            # 立即发送 run_end 事件，确保前端能及时收到
                            run_end_event = {
                                "type": "run_end",
                                "success": True,
                                "status": "success",
                            }
                            yield f"data: {json.dumps(run_end_event)}\n\n"
                            logger.info(f"Sent run_end event for run {run_id} after workflow_end log")
                        elif event_type == 'workflow_error':
                            task_completed = True
                            # 立即发送 run_end 事件
                            run_end_event = {
                                "type": "run_end",
                                "success": False,
                                "status": "failed",
                            }
                            yield f"data: {json.dumps(run_end_event)}\n\n"
                            logger.info(f"Sent run_end event for run {run_id} after workflow_error log")
                        
                        event = {
                            "type": "log",
                            "level": log['level'],
                            "event": event_type,
                            "payload": payload,
                            "node_id": node_id,
                            "time": log['time'].isoformat() if log.get('time') else None,
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                        last_seq = log['seq']
                else:
                    empty_polls += 1
                    if task_completed:
                        post_completion_polls += 1
                
                # 检查任务状态（如果日志中没有 workflow_end 事件，通过状态判断）
                if not task_completed:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT status FROM workflow_runs WHERE id = %s
                        """, (run_id,))
                        row = cursor.fetchone()
                        if row:
                            status = row['status']
                            if status in ('success', 'failed', 'canceled'):
                                task_completed = True
                                logger.info(f"Task {run_id} completed with status: {status}")
                                # 发送完成事件
                                event = {
                                    "type": "run_end",
                                    "success": status == 'success',
                                    "status": status,
                                }
                                yield f"data: {json.dumps(event)}\n\n"
                
                # 如果任务已完成，继续轮询一段时间
                if task_completed:
                    if post_completion_polls >= max_post_completion_polls:
                        # 最后再轮询一次确保获取所有日志
                        logger.info(f"Final log poll for run {run_id}")
                        await asyncio.sleep(0.2)  # 最后一次等待日志写入
                        logs = get_run_logs(conn, run_id, after_seq=last_seq)
                        for log in logs:
                            payload = log.get('payload')
                            if isinstance(payload, str):
                                try:
                                    payload = json.loads(payload)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            node_id = log.get('node_id')
                            event_type = log.get('event')
                            logger.debug(f"Final SSE Event: event={event_type}, node_id={node_id}, payload={payload}")
                            event = {
                                "type": "log",
                                "level": log['level'],
                                "event": event_type,
                                "payload": payload,
                                "node_id": node_id,
                                "time": log['time'].isoformat() if log.get('time') else None,
                            }
                            yield f"data: {json.dumps(event)}\n\n"
                            last_seq = log['seq']
                        break
                elif empty_polls >= max_empty_polls:
                    # 如果长时间没有新日志，检查任务状态
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT status FROM workflow_runs WHERE id = %s
                        """, (run_id,))
                        row = cursor.fetchone()
                        if row:
                            status = row['status']
                            if status in ('success', 'failed', 'canceled'):
                                task_completed = True
                                logger.info(f"Task {run_id} completed with status: {status} (detected by status check)")
                                event = {
                                    "type": "run_end",
                                    "success": status == 'success',
                                    "status": status,
                                }
                                yield f"data: {json.dumps(event)}\n\n"
                            else:
                                # 任务还在运行，重置空轮询计数
                                empty_polls = 0
                
                await asyncio.sleep(0.5)  # 轮询间隔
        finally:
            conn.close()


# 全局执行器实例
_executor_instance: Optional[WorkflowExecutor] = None


def get_workflow_executor() -> WorkflowExecutor:
    """获取执行器实例（单例）"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = WorkflowExecutor()
    return _executor_instance

