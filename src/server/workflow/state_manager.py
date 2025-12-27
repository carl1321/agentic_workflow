# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
节点执行状态管理器（带数据库集成）

扩展原有的 NodeExecutionStateManager，添加数据库持久化和实时状态同步
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

import psycopg

# 定义基础状态管理器类（如果不存在则在这里定义）
from enum import Enum

class NodeStatus(Enum):
    """节点状态"""
    PENDING = "pending"      # 未执行（等待上游节点）
    READY = "ready"          # 就绪（上游节点已完成，等待执行）
    RUNNING = "running"      # 执行中
    SUCCESS = "success"       # 执行成功
    ERROR = "error"          # 执行失败
    SKIPPED = "skipped"      # 跳过（条件不满足）
    CANCELLED = "cancelled"  # 已取消


class IterationTracker:
    """迭代跟踪器"""
    def __init__(self):
        self._iterations: Dict[str, int] = {}
    
    def get_iteration(self, node_id: str) -> int:
        """获取节点的当前迭代次数"""
        return self._iterations.get(node_id, 0)
    
    def increment_iteration(self, node_id: str):
        """增加节点的迭代次数"""
        self._iterations[node_id] = self._iterations.get(node_id, 0) + 1
    
    def reset_iteration(self, node_id: str):
        """重置节点的迭代次数"""
        self._iterations[node_id] = 0


class NodeExecutionStateManager:
    """节点执行状态管理器（基础实现）"""
    
    def __init__(self):
        self._node_statuses: Dict[str, NodeStatus] = {}
        self._node_outputs: Dict[str, Any] = {}
        self._node_errors: Dict[str, str] = {}
        self._global_running_nodes: Set[str] = set()
        self._global_processed_nodes: Set[str] = set()
        self._iteration_tracker = IterationTracker()
    
    def mark_node_running(self, node_id: str, **kwargs) -> bool:
        """标记节点为运行中"""
        is_new = node_id not in self._global_running_nodes
        self._node_statuses[node_id] = NodeStatus.RUNNING
        self._global_running_nodes.add(node_id)
        return is_new
    
    def mark_node_success(self, node_id: str, output: Any = None, **kwargs) -> bool:
        """标记节点为成功"""
        is_new = node_id not in self._global_processed_nodes
        self._node_statuses[node_id] = NodeStatus.SUCCESS
        self._global_running_nodes.discard(node_id)
        self._global_processed_nodes.add(node_id)
        if output is not None:
            self._node_outputs[node_id] = output
        return is_new
    
    def mark_node_error(self, node_id: str, error: str, **kwargs) -> bool:
        """标记节点为错误"""
        is_new = node_id not in self._global_processed_nodes
        self._node_statuses[node_id] = NodeStatus.ERROR
        self._global_running_nodes.discard(node_id)
        self._global_processed_nodes.add(node_id)
        self._node_errors[node_id] = error
        return is_new
    
    def mark_node_ready(self, node_id: str, **kwargs) -> bool:
        """标记节点为就绪（上游节点已完成，等待执行）"""
        is_new = node_id not in self._node_statuses or self._node_statuses.get(node_id) != NodeStatus.READY
        self._node_statuses[node_id] = NodeStatus.READY
        return is_new
    
    def mark_node_skipped(self, node_id: str, reason: Optional[str] = None, **kwargs) -> bool:
        """标记节点为跳过"""
        is_new = node_id not in self._global_processed_nodes
        self._node_statuses[node_id] = NodeStatus.SKIPPED
        self._global_processed_nodes.add(node_id)
        if reason:
            self._node_errors[node_id] = f"Skipped: {reason}"
        return is_new
    
    def mark_node_cancelled(self, node_id: str, reason: Optional[str] = None, **kwargs) -> bool:
        """标记节点为已取消"""
        is_new = node_id not in self._global_processed_nodes
        self._node_statuses[node_id] = NodeStatus.CANCELLED
        self._global_running_nodes.discard(node_id)
        self._global_processed_nodes.add(node_id)
        if reason:
            self._node_errors[node_id] = f"Cancelled: {reason}"
        return is_new
    
    def get_node_status(self, node_id: str) -> Optional[NodeStatus]:
        """获取节点状态"""
        return self._node_statuses.get(node_id)
    
    def get_node_output(self, node_id: str) -> Optional[Any]:
        """获取节点输出"""
        return self._node_outputs.get(node_id)
    
    def get_node_error(self, node_id: str) -> Optional[str]:
        """获取节点错误"""
        return self._node_errors.get(node_id)


from src.server.workflow.db import (
    append_log,
    create_node_task,
    get_db_connection,
    update_node_task,
)

logger = logging.getLogger(__name__)


class DatabaseStateManager(NodeExecutionStateManager):
    """带数据库集成的状态管理器"""
    
    def __init__(
        self,
        run_id: UUID,
        db_conn: Optional[psycopg.Connection] = None,
    ):
        """
        初始化数据库状态管理器
        
        Args:
            run_id: 运行 ID
            db_conn: 数据库连接（可选，如果不提供则每次操作时创建新连接）
        """
        super().__init__()
        self.run_id = run_id
        self._db_conn = db_conn
        self._node_task_ids: Dict[str, UUID] = {}  # 节点ID到任务ID的映射
    
    def _get_conn(self) -> psycopg.Connection:
        """获取数据库连接"""
        if self._db_conn:
            return self._db_conn
        return get_db_connection()
    
    def _close_conn_if_needed(self, conn: psycopg.Connection):
        """如果需要则关闭连接（如果不是共享连接）"""
        if conn != self._db_conn:
            conn.close()
    
    # ============= 重写状态更新方法，添加数据库集成 =============
    
    def mark_node_running(
        self,
        node_id: str,
        loop_id: Optional[str] = None,
        iteration: Optional[int] = None,
        input_data: Optional[Dict[str, Any]] = None,
        parent_task_id: Optional[UUID] = None,
        branch_id: Optional[str] = None,
    ) -> bool:
        """
        标记节点为运行中（带数据库更新）
        
        Args:
            node_id: 节点ID
            loop_id: 循环ID（如果是循环体内的节点）
            iteration: 迭代次数（如果是循环体内的节点）
            input_data: 输入数据（可选）
            parent_task_id: 父任务ID（可选）
            branch_id: 分支ID（可选）
            
        Returns:
            是否是新节点
        """
        # 调用父类方法更新内存状态
        is_new = super().mark_node_running(node_id)
        
        # 更新数据库
        conn = self._get_conn()
        try:
            # 如果任务不存在，创建任务
            if node_id not in self._node_task_ids:
                task_id = create_node_task(
                    conn,
                    self.run_id,
                    node_id,
                    input_data=input_data,
                    parent_task_id=parent_task_id,
                    branch_id=branch_id,
                    iteration=iteration,
                    loop_node_id=loop_id,
                )
                self._node_task_ids[node_id] = task_id
            else:
                task_id = self._node_task_ids[node_id]
            
            # 更新任务状态为 running
            update_node_task(
                conn,
                task_id,
                status='running',
                started_at=datetime.now(),
            )
            conn.commit()
            
            # 记录日志
            logger.info(f"Recording node_start log for node {node_id} in run {self.run_id}")
            seq = append_log(
                conn,
                self.run_id,
                'info',
                'node_start',
                payload={
                    'node_id': node_id, 
                    'loop_id': loop_id, 
                    'iteration': iteration,
                    'inputs': input_data
                },
                node_id=node_id,
            )
            conn.commit()
            logger.debug(f"Node_start log recorded with seq {seq} for node {node_id}")
        except Exception as e:
            logger.error(f"Error updating node task status in database: {e}", exc_info=True)
            if conn != self._db_conn:
                conn.rollback()
        finally:
            self._close_conn_if_needed(conn)
        
        return is_new
    
    def mark_node_success(
        self,
        node_id: str,
        outputs: Any = None,
        loop_id: Optional[str] = None,
        iteration: Optional[int] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        标记节点为成功（带数据库更新）
        
        Args:
            node_id: 节点ID
            outputs: 节点输出
            loop_id: 循环ID（如果是循环体内的节点）
            iteration: 迭代次数（如果是循环体内的节点）
            metrics: 指标数据（可选）
            
        Returns:
            是否是新节点
        """
        # 调用父类方法更新内存状态
        is_new = super().mark_node_success(node_id, outputs)
        
        # 更新数据库
        if node_id in self._node_task_ids:
            conn = self._get_conn()
            try:
                task_id = self._node_task_ids[node_id]
                update_node_task(
                    conn,
                    task_id,
                    status='success',
                    output=outputs,
                    finished_at=datetime.now(),
                    metrics=metrics,
                )
                conn.commit()
                
                # 记录日志
                logger.info(f"Recording node_end log for node {node_id} in run {self.run_id}")
                seq = append_log(
                    conn,
                    self.run_id,
                    'info',
                    'node_end',
                    payload={
                        'node_id': node_id, 
                        'status': 'success', 
                        'loop_id': loop_id, 
                        'iteration': iteration,
                        'outputs': outputs,
                        'metrics': metrics
                    },
                    node_id=node_id,
                )
                conn.commit()
                logger.debug(f"Node_end log recorded with seq {seq} for node {node_id}")
            except Exception as e:
                logger.error(f"Error updating node task status in database: {e}", exc_info=True)
                if conn != self._db_conn:
                    conn.rollback()
            finally:
                self._close_conn_if_needed(conn)
        
        return is_new
    
    def mark_node_error(
        self,
        node_id: str,
        error: str,
        loop_id: Optional[str] = None,
        iteration: Optional[int] = None,
    ) -> bool:
        """
        标记节点为错误（带数据库更新）
        
        Args:
            node_id: 节点ID
            error: 错误信息
            loop_id: 循环ID（如果是循环体内的节点）
            iteration: 迭代次数（如果是循环体内的节点）
            
        Returns:
            是否是新节点
        """
        # 调用父类方法更新内存状态
        is_new = super().mark_node_error(node_id, error)
        
        # 更新数据库
        if node_id in self._node_task_ids:
            conn = self._get_conn()
            try:
                task_id = self._node_task_ids[node_id]
                error_data = {'error': error}
                update_node_task(
                    conn,
                    task_id,
                    status='failed',
                    error=error_data,
                    finished_at=datetime.now(),
                )
                conn.commit()
                
                # 记录日志
                append_log(
                    conn,
                    self.run_id,
                    'error',
                    'node_error',
                    payload={'node_id': node_id, 'error': error, 'loop_id': loop_id, 'iteration': iteration},
                    node_id=node_id,
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Error updating node task status in database: {e}", exc_info=True)
                if conn != self._db_conn:
                    conn.rollback()
            finally:
                self._close_conn_if_needed(conn)
        
        return is_new
    
    def mark_node_ready(
        self,
        node_id: str,
        loop_id: Optional[str] = None,
        iteration: Optional[int] = None,
    ) -> bool:
        """
        标记节点为就绪（带数据库更新）
        
        Args:
            node_id: 节点ID
            loop_id: 循环ID（如果是循环体内的节点）
            iteration: 迭代次数（如果是循环体内的节点）
            
        Returns:
            是否是新节点
        """
        # 调用父类方法更新内存状态
        is_new = super().mark_node_ready(node_id)
        
        # 更新数据库
        conn = self._get_conn()
        try:
            # 如果任务不存在，创建任务（状态为 pending）
            if node_id not in self._node_task_ids:
                task_id = create_node_task(
                    conn,
                    self.run_id,
                    node_id,
                    loop_node_id=loop_id,
                    iteration=iteration,
                )
                self._node_task_ids[node_id] = task_id
            
            # 记录日志
            logger.info(f"Recording node_ready log for node {node_id} in run {self.run_id}")
            seq = append_log(
                conn,
                self.run_id,
                'info',
                'node_ready',
                payload={
                    'node_id': node_id,
                    'loop_id': loop_id,
                    'iteration': iteration,
                },
                node_id=node_id,
            )
            conn.commit()
            logger.debug(f"Node_ready log recorded with seq {seq} for node {node_id}")
        except Exception as e:
            logger.error(f"Error recording node_ready status in database: {e}", exc_info=True)
            if conn != self._db_conn:
                conn.rollback()
        finally:
            self._close_conn_if_needed(conn)
        
        return is_new
    
    def mark_node_skipped(
        self,
        node_id: str,
        reason: Optional[str] = None,
        loop_id: Optional[str] = None,
        iteration: Optional[int] = None,
    ) -> bool:
        """
        标记节点为跳过（带数据库更新）
        
        Args:
            node_id: 节点ID
            reason: 跳过原因（可选）
            loop_id: 循环ID（如果是循环体内的节点）
            iteration: 迭代次数（如果是循环体内的节点）
            
        Returns:
            是否是新节点
        """
        # 调用父类方法更新内存状态
        is_new = super().mark_node_skipped(node_id, reason)
        
        # 更新数据库
        if node_id in self._node_task_ids:
            conn = self._get_conn()
            try:
                task_id = self._node_task_ids[node_id]
                update_node_task(
                    conn,
                    task_id,
                    status='skipped',
                    finished_at=datetime.now(),
                    error={'reason': reason} if reason else None,
                )
                conn.commit()
                
                # 记录日志
                logger.info(f"Recording node_skipped log for node {node_id} in run {self.run_id}")
                seq = append_log(
                    conn,
                    self.run_id,
                    'info',
                    'node_skipped',
                    payload={
                        'node_id': node_id,
                        'reason': reason,
                        'loop_id': loop_id,
                        'iteration': iteration,
                    },
                    node_id=node_id,
                )
                conn.commit()
                logger.debug(f"Node_skipped log recorded with seq {seq} for node {node_id}")
            except Exception as e:
                logger.error(f"Error recording node_skipped status in database: {e}", exc_info=True)
                if conn != self._db_conn:
                    conn.rollback()
            finally:
                self._close_conn_if_needed(conn)
        
        return is_new
    
    def mark_node_cancelled(
        self,
        node_id: str,
        reason: Optional[str] = None,
        loop_id: Optional[str] = None,
        iteration: Optional[int] = None,
    ) -> bool:
        """
        标记节点为已取消（带数据库更新）
        
        Args:
            node_id: 节点ID
            reason: 取消原因（可选）
            loop_id: 循环ID（如果是循环体内的节点）
            iteration: 迭代次数（如果是循环体内的节点）
            
        Returns:
            是否是新节点
        """
        # 调用父类方法更新内存状态
        is_new = super().mark_node_cancelled(node_id, reason)
        
        # 更新数据库
        if node_id in self._node_task_ids:
            conn = self._get_conn()
            try:
                task_id = self._node_task_ids[node_id]
                update_node_task(
                    conn,
                    task_id,
                    status='cancelled',
                    finished_at=datetime.now(),
                    error={'reason': reason} if reason else None,
                )
                conn.commit()
                
                # 记录日志
                logger.info(f"Recording node_cancelled log for node {node_id} in run {self.run_id}")
                seq = append_log(
                    conn,
                    self.run_id,
                    'info',
                    'node_cancelled',
                    payload={
                        'node_id': node_id,
                        'reason': reason,
                        'loop_id': loop_id,
                        'iteration': iteration,
                    },
                    node_id=node_id,
                )
                conn.commit()
                logger.debug(f"Node_cancelled log recorded with seq {seq} for node {node_id}")
            except Exception as e:
                logger.error(f"Error recording node_cancelled status in database: {e}", exc_info=True)
                if conn != self._db_conn:
                    conn.rollback()
            finally:
                self._close_conn_if_needed(conn)
        
        return is_new
    
    # ============= 状态同步 =============
    
    def sync_state_from_db(self):
        """从数据库加载最新状态"""
        from src.server.workflow.db import get_run_tasks
        
        conn = self._get_conn()
        try:
            tasks = get_run_tasks(conn, self.run_id)
            for task in tasks:
                node_id = task['node_id']
                status = task['status']
                task_id = task['id']
                
                # 更新任务ID映射
                self._node_task_ids[node_id] = task_id
                
                # 更新内存状态
                if status == 'pending':
                    self._node_statuses[node_id] = NodeStatus.PENDING
                elif status == 'ready':
                    self._node_statuses[node_id] = NodeStatus.READY
                elif status == 'running':
                    self._node_statuses[node_id] = NodeStatus.RUNNING
                    self._global_running_nodes.add(node_id)
                elif status == 'success':
                    self._node_statuses[node_id] = NodeStatus.SUCCESS
                    self._global_processed_nodes.add(node_id)
                    if task.get('output'):
                        import json
                        try:
                            self._node_outputs[node_id] = json.loads(task['output']) if isinstance(task['output'], str) else task['output']
                        except:
                            self._node_outputs[node_id] = task['output']
                elif status == 'failed':
                    self._node_statuses[node_id] = NodeStatus.ERROR
                    self._global_processed_nodes.add(node_id)
                    if task.get('error'):
                        import json
                        try:
                            error_data = json.loads(task['error']) if isinstance(task['error'], str) else task['error']
                            self._node_errors[node_id] = error_data.get('error', str(error_data))
                        except:
                            self._node_errors[node_id] = str(task['error'])
                elif status == 'skipped':
                    self._node_statuses[node_id] = NodeStatus.SKIPPED
                    self._global_processed_nodes.add(node_id)
                elif status == 'cancelled':
                    self._node_statuses[node_id] = NodeStatus.CANCELLED
                    self._global_processed_nodes.add(node_id)
        finally:
            self._close_conn_if_needed(conn)
    
    def get_node_task_status(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        从数据库查询节点任务状态
        
        Args:
            node_id: 节点ID
            
        Returns:
            任务状态字典，如果不存在则返回 None
        """
        if node_id not in self._node_task_ids:
            return None
        
        from src.server.workflow.db import get_node_task
        
        conn = self._get_conn()
        try:
            task = get_node_task(conn, self._node_task_ids[node_id])
            return task
        finally:
            self._close_conn_if_needed(conn)
    
    # ============= 检查点管理 =============
    
    def save_checkpoint(self, checkpoint_data: Dict[str, Any], checkpoint_id: Optional[str] = None):
        """
        保存执行检查点（使用 LangGraph checkpoint）
        
        Args:
            checkpoint_data: 检查点数据
            checkpoint_id: 检查点ID（可选）
        """
        # 注意：实际的检查点保存由 LangGraph 的 checkpointer 处理
        # 这里只是记录日志
        logger.debug(f"Saving checkpoint for run {self.run_id}")
        
        conn = self._get_conn()
        try:
            append_log(
                conn,
                self.run_id,
                'info',
                'checkpoint_saved',
                payload={'checkpoint_id': checkpoint_id},
            )
            conn.commit()
        finally:
            self._close_conn_if_needed(conn)
    
    def load_checkpoint(self, checkpoint_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        加载执行检查点（使用 LangGraph checkpoint）
        
        Args:
            checkpoint_id: 检查点ID（可选）
            
        Returns:
            检查点数据，如果不存在则返回 None
        """
        # 注意：实际的检查点加载由 LangGraph 的 checkpointer 处理
        # 这里只是记录日志
        logger.debug(f"Loading checkpoint for run {self.run_id}")
        
        # 从数据库同步状态
        self.sync_state_from_db()
        
        return None

