# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流模板解析器

解析 prompt 中的 {{节点名.字段名}} 模板语法，替换为实际值
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def render_template(
    template: str,
    node_outputs: Dict[str, Dict[str, Any]],
    node_labels: Optional[Dict[str, str]] = None,
) -> str:
    """
    解析模板中的 {{节点名.字段名}} 语法并替换为实际值
    
    Args:
        template: 包含模板语法的字符串，如 "请分析：{{start.inputs}}"
        node_outputs: 节点输出映射，格式为 {节点ID: {字段名: 值}}
        node_labels: 节点标签映射，格式为 {节点ID: 标签}，用于通过标签查找节点
    
    Returns:
        解析后的字符串
    
    Example:
        >>> node_outputs = {
        ...     "node_123": {"response": "Hello"},
        ...     "node_456": {"result": 42}
        ... }
        >>> node_labels = {
        ...     "node_123": "LLM节点",
        ...     "node_456": "工具节点"
        ... }
        >>> render_template("{{LLM节点.response}}", node_outputs, node_labels)
        "Hello"
    """
    if not template:
        return template
    
    pattern = r'\{\{([^}]+)\}\}'
    
    def replace_match(match):
        var_path = match.group(1).strip()
        
        # 解析 节点名.字段名
        parts = var_path.split('.', 1)
        if len(parts) != 2:
            logger.warning(f"Invalid template syntax: {var_path}, expected format: nodeName.fieldName")
            return match.group(0)  # 返回原始模板，不替换
        
        node_name, field_name = parts[0].strip(), parts[1].strip()
        
        # 查找对应的节点
        target_node_id = None
        
        # 方案1: 优先尝试直接使用 node_name 作为节点 ID（节点 ID 是唯一标识符，应该优先使用）
        if node_name in node_outputs:
            target_node_id = node_name
        
        # 方案2: 如果直接查找失败，通过节点标签（nodeName）查找
        if not target_node_id and node_labels:
            for node_id, label in node_labels.items():
                # 确保 label 是字符串
                label_str = str(label) if label is not None else ""
                node_name_str = str(node_name) if node_name is not None else ""
                # 支持标签或标签_序号的形式
                if label_str == node_name_str or label_str.startswith(f"{node_name_str}_"):
                    target_node_id = node_id
                    break
        
        if not target_node_id:
            logger.warning(f"Node not found: {node_name}")
            return match.group(0)  # 返回原始模板
        
        # 获取节点输出
        node_output = node_outputs.get(target_node_id)
        if not node_output:
            logger.warning(f"No output found for node: {target_node_id}")
            return match.group(0)
        
        # 获取字段值
        if isinstance(node_output, dict):
            value = node_output.get(field_name)
        else:
            # 如果输出不是字典，尝试直接访问属性
            value = getattr(node_output, field_name, None)
        
        if value is None:
            logger.warning(f"Field '{field_name}' not found in node '{target_node_id}' output")
            return match.group(0)
        
        # 转换为字符串
        if isinstance(value, (dict, list)):
            import json
            try:
                return json.dumps(value, ensure_ascii=False)
            except:
                return str(value)
        return str(value)
    
    return re.sub(pattern, replace_match, template)


def extract_template_variables(template: str) -> list[tuple[str, str]]:
    """
    提取模板中的所有变量引用
    
    Returns:
        [(节点名, 字段名), ...] 列表
    """
    if not template:
        return []
    
    pattern = r'\{\{([^}]+)\}\}'
    variables = []
    
    for match in re.finditer(pattern, template):
        var_path = match.group(1).strip()
        parts = var_path.split('.', 1)
        if len(parts) == 2:
            node_name, field_name = parts[0].strip(), parts[1].strip()
            variables.append((node_name, field_name))
    
    return variables

