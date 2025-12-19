# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from src.server.workflow_request import WorkflowConfigRequest, WorkflowConfigResponse

logger = logging.getLogger(__name__)


class WorkflowStorage:
    """工作流存储服务 - 使用文件系统存储"""
    
    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            # 默认存储在工作流目录
            storage_dir = os.path.join(os.path.dirname(__file__), "../../workflows")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_workflow_path(self, workflow_id: str) -> Path:
        """获取工作流文件路径"""
        return self.storage_dir / f"{workflow_id}.json"
    
    def save(self, request: WorkflowConfigRequest, thread_id: Optional[str] = None) -> str:
        """保存工作流配置
        
        Args:
            request: 工作流配置请求
            thread_id: 可选的thread_id，用于绑定工作流到对话线程
            
        Returns:
            工作流ID
        """
        workflow_id = request.id or str(uuid4())
        
        # 加载现有配置以获取版本号和执行结果
        version = 1
        existing = self.load(workflow_id)
        existing_execution_result = None
        existing_has_executed = False
        if existing:
            version = existing.get("version", 0) + 1
            # 保留现有的执行结果
            existing_execution_result = existing.get("execution_result")
            existing_has_executed = existing.get("has_executed", False)
        
        workflow_data = {
            "id": workflow_id,
            "name": request.name,
            "description": request.description,
            "nodes": [node.model_dump(by_alias=True) for node in request.nodes],
            "edges": [edge.model_dump(by_alias=True) for edge in request.edges],
            "version": version,
            "created_at": existing.get("created_at") if existing else datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        
        # 保留现有的执行结果（如果存在）
        if existing_execution_result is not None:
            workflow_data["execution_result"] = existing_execution_result
            workflow_data["has_executed"] = existing_has_executed
        
        # 如果提供了thread_id，保存关联
        if thread_id:
            workflow_data["thread_id"] = thread_id
        
        workflow_path = self._get_workflow_path(workflow_id)
        with open(workflow_path, "w", encoding="utf-8") as f:
            json.dump(workflow_data, f, indent=2, ensure_ascii=False)
        
        return workflow_id
    
    def load(self, workflow_id: str) -> Optional[Dict]:
        """加载工作流配置"""
        workflow_path = self._get_workflow_path(workflow_id)
        if not workflow_path.exists():
            return None
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)
        
        # 检查是否有执行结果
        # 优先从工作流配置中读取 execution_result
        if workflow_data.get("execution_result"):
            workflow_data["has_executed"] = True
            logger.info(f"[Storage] Loaded workflow {workflow_id}: has_executed=True, execution_result keys: {list(workflow_data.get('execution_result', {}).keys())}")
        else:
            # 向后兼容：检查是否有单独的执行结果文件
            results_path = self._get_execution_results_path(workflow_id)
            if results_path.exists():
                try:
                    with open(results_path, "r", encoding="utf-8") as rf:
                        results_data = json.load(rf)
                        # 迁移执行结果到工作流配置中
                        workflow_data["execution_result"] = {
                            "execution_logs": results_data.get("execution_logs", []),
                            "final_result": results_data.get("final_result"),
                            "created_at": results_data.get("created_at"),
                            "updated_at": results_data.get("updated_at"),
                        }
                        workflow_data["has_executed"] = True
                        # 更新工作流配置文件
                        with open(workflow_path, "w", encoding="utf-8") as wf:
                            json.dump(workflow_data, wf, indent=2, ensure_ascii=False)
                        logger.info(f"Migrated execution results from separate file to workflow config for {workflow_id}")
                except Exception as e:
                    logger.warning(f"Failed to migrate execution results for {workflow_id}: {e}")
                    workflow_data["has_executed"] = True
            elif "has_executed" not in workflow_data:
                workflow_data["has_executed"] = False
        
        return workflow_data
    
    def list(self) -> List[Dict]:
        """列出所有工作流"""
        workflows = []
        for workflow_file in self.storage_dir.glob("*.json"):
            try:
                with open(workflow_file, "r", encoding="utf-8") as f:
                    workflow_data = json.load(f)
                    workflows.append({
                        "id": workflow_data.get("id", workflow_file.stem),
                        "name": workflow_data.get("name", "Untitled"),
                        "description": workflow_data.get("description"),
                        "nodes": workflow_data.get("nodes", []),
                        "edges": workflow_data.get("edges", []),
                        "created_at": workflow_data.get("created_at"),
                        "updated_at": workflow_data.get("updated_at"),
                        "version": workflow_data.get("version", 1),
                    })
            except Exception as e:
                # 跳过损坏的文件
                continue
        
        # 按更新时间排序
        workflows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return workflows
    
    def delete(self, workflow_id: str) -> bool:
        """删除工作流"""
        workflow_path = self._get_workflow_path(workflow_id)
        if workflow_path.exists():
            workflow_path.unlink()
            return True
        return False
    
    def find_by_thread_id(self, thread_id: str) -> Optional[Dict]:
        """根据thread_id查找工作流
        
        Args:
            thread_id: 对话线程ID
            
        Returns:
            工作流配置字典，如果未找到则返回None
        """
        # 遍历所有工作流文件，查找匹配的thread_id
        # 排除执行结果文件（以_results.json结尾）
        for workflow_file in self.storage_dir.glob("*.json"):
            # 跳过执行结果文件
            if workflow_file.name.endswith("_results.json"):
                continue
            try:
                with open(workflow_file, "r", encoding="utf-8") as f:
                    workflow_data = json.load(f)
                    # 确保是工作流配置文件（包含必需的字段）
                    if workflow_data.get("thread_id") == thread_id:
                        # 验证必需字段是否存在
                        if all(key in workflow_data for key in ["id", "name", "nodes", "edges", "version"]):
                            # 确保 has_executed 和 execution_result 字段正确设置
                            # 优先使用配置文件中的 execution_result
                            workflow_id = workflow_data.get("id")
                            if workflow_id:
                                if workflow_data.get("execution_result"):
                                    workflow_data["has_executed"] = True
                                else:
                                    # 向后兼容：检查是否有单独的执行结果文件
                                    results_path = self._get_execution_results_path(workflow_id)
                                    if results_path.exists():
                                        try:
                                            with open(results_path, "r", encoding="utf-8") as rf:
                                                results_data = json.load(rf)
                                                workflow_data["execution_result"] = {
                                                    "execution_logs": results_data.get("execution_logs", []),
                                                    "final_result": results_data.get("final_result"),
                                                    "created_at": results_data.get("created_at"),
                                                    "updated_at": results_data.get("updated_at"),
                                                }
                                                workflow_data["has_executed"] = True
                                        except Exception as e:
                                            logger.warning(f"Failed to load execution results for {workflow_id}: {e}")
                                            workflow_data["has_executed"] = True
                                    elif "has_executed" not in workflow_data:
                                        workflow_data["has_executed"] = False
                            return workflow_data
                        else:
                            logger.warning(f"Found workflow file {workflow_file.name} with thread_id {thread_id} but missing required fields")
            except Exception as e:
                # 跳过损坏的文件
                logger.debug(f"Skipping file {workflow_file.name} due to error: {e}")
                continue
        
        return None
    
    def _get_execution_results_path(self, workflow_id: str) -> Path:
        """获取执行结果文件路径"""
        return self.storage_dir / f"{workflow_id}_results.json"
    
    def save_execution_results(
        self,
        workflow_id: str,
        execution_logs: List[Dict],
        final_result: Optional[Dict] = None,
        thread_id: Optional[str] = None,
    ) -> str:
        """保存工作流执行结果到工作流文件中
        
        Args:
            workflow_id: 工作流ID
            execution_logs: 执行日志列表
            final_result: 最终结果
            thread_id: 可选的thread_id
            
        Returns:
            执行结果ID（与workflow_id相同）
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Saving execution results for workflow {workflow_id}: {len(execution_logs)} logs, has_final_result={final_result is not None}")
        
        # 构建执行结果数据
        execution_result = {
            "execution_logs": execution_logs,
            "final_result": final_result,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        
        # 加载现有工作流配置
        workflow_data = self.load(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        # 将执行结果保存到工作流文件的 execution_result 字段中
        workflow_data["execution_result"] = execution_result
        workflow_data["has_executed"] = True
        workflow_data["updated_at"] = datetime.now().isoformat()
        
        # 如果提供了thread_id，确保保存关联
        if thread_id:
            workflow_data["thread_id"] = thread_id
        
        # 保存更新后的工作流配置
        workflow_path = self._get_workflow_path(workflow_id)
        try:
            with open(workflow_path, "w", encoding="utf-8") as f:
                json.dump(workflow_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Successfully saved execution results to workflow config {workflow_id}")
        except Exception as e:
            logger.error(f"Failed to save execution results to workflow config {workflow_id}: {e}")
            raise
        
        return workflow_id
    
    def load_execution_results(self, workflow_id: str) -> Optional[Dict]:
        """加载工作流执行结果
        
        Args:
            workflow_id: 工作流ID
            
        Returns:
            执行结果字典，如果未找到则返回None
        """
        results_path = self._get_execution_results_path(workflow_id)
        if not results_path.exists():
            return None
        
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def duplicate(self, workflow_id: str) -> Dict:
        """复制工作流"""
        existing = self.load(workflow_id)
        if not existing:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        # 创建新ID
        new_id = str(uuid4())
        
        # 复制数据，更新名称和ID
        new_workflow_data = {
            "id": new_id,
            "name": f"{existing.get('name', 'Untitled')} (副本)",
            "description": existing.get("description"),
            "nodes": existing.get("nodes", []),
            "edges": existing.get("edges", []),
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        
        # 保存新工作流
        workflow_path = self._get_workflow_path(new_id)
        with open(workflow_path, "w", encoding="utf-8") as f:
            json.dump(new_workflow_data, f, indent=2, ensure_ascii=False)
        
        return new_workflow_data


# 全局存储实例
_storage_instance: Optional[WorkflowStorage] = None


def get_workflow_storage() -> WorkflowStorage:
    """获取工作流存储实例（单例）"""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = WorkflowStorage()
    return _storage_instance

