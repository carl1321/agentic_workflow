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
    loop_context: Optional[Dict[str, Any]] = None,
    node_output_formats: Optional[Dict[str, str]] = None,
) -> str:
    """
    解析模板中的 {{节点名.字段名}} 语法并替换为实际值
    支持循环上下文变量：{{loop.iteration}}, {{loop.variables.变量名}}, {{loop.previous_output}}
    支持输出格式字段：{{节点名.array}}, {{节点名.object}}, {{节点名.string}}, {{节点名.number}}
    
    Args:
        template: 包含模板语法的字符串，如 "请分析：{{start.inputs}}"
        node_outputs: 节点输出映射，格式为 {节点ID: {字段名: 值}}
        node_labels: 节点标签映射，格式为 {节点ID: 标签}，用于通过标签查找节点
        loop_context: 循环上下文，格式为 {循环节点ID: {iteration: int, variables: dict, previous_output: dict}}
        node_output_formats: 节点输出格式映射，格式为 {节点ID: 格式}，格式可以是 "output", "array", "object", "string", "number"
    
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
        >>> loop_context = {"loop_1": {"iteration": 3, "variables": {"count": 10}}}
        >>> render_template("当前迭代：{{loop.iteration}}，变量：{{loop.variables.count}}", node_outputs, node_labels, loop_context)
        "当前迭代：3，变量：10"
    """
    if not template:
        return template
    
    # 先处理条件语句 {% if ... %} ... {% endif %}
    template = _process_conditionals(template, loop_context)
    
    pattern = r'\{\{([^}]+)\}\}'
    
    def replace_match(match):
        var_path = match.group(1).strip()
        
        # 检查是否是循环上下文变量
        if var_path.startswith("loop."):
            if not loop_context:
                logger.warning(f"Loop context not available for: {var_path}")
                return match.group(0)
            
            # 解析循环变量路径：loop.iteration, loop.variables.变量名, loop.previous_output
            loop_parts = var_path.split('.', 1)
            if len(loop_parts) < 2:
                logger.warning(f"Invalid loop variable syntax: {var_path}")
                return match.group(0)
            
            loop_field = loop_parts[1].strip()
            
            # 获取当前循环上下文（如果有多个循环，使用第一个）
            # 实际使用中，应该根据当前执行的循环节点ID来确定
            current_loop_context = None
            if loop_context:
                # 如果有多个循环，使用最后一个（最内层）
                for loop_id, ctx in loop_context.items():
                    current_loop_context = ctx
                    break  # 使用第一个找到的循环上下文
            
            if not current_loop_context:
                logger.warning(f"Loop context not found for: {var_path}")
                return match.group(0)
            
            # 处理不同的循环变量
            if loop_field == "iteration":
                value = current_loop_context.get("iteration", 0)
            elif loop_field == "previous_output":
                value = current_loop_context.get("previous_output", {})
            elif loop_field == "filtered_data.passed":
                value = current_loop_context.get("filtered_data", {}).get("passed", [])
            elif loop_field == "filtered_data.pending":
                value = current_loop_context.get("filtered_data", {}).get("pending", [])
            elif loop_field.startswith("variables."):
                var_name = loop_field.split(".", 1)[1]
                variables = current_loop_context.get("variables", {})
                value = variables.get(var_name)
                if value is None:
                    logger.debug(f"Loop variable '{var_name}' not found in variables: {list(variables.keys())}")
            else:
                # 直接访问循环上下文字段
                value = current_loop_context.get(loop_field)
            
            if value is None:
                # 对于循环变量，如果值为 None，尝试返回空字符串而不是原始模板
                # 这样可以避免在模板中显示未定义的变量
                logger.debug(f"Loop variable '{loop_field}' is None, returning empty string")
                return ""
            
            # 转换为字符串
            if isinstance(value, (dict, list)):
                import json
                try:
                    return json.dumps(value, ensure_ascii=False)
                except:
                    return str(value)
            return str(value)
        
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
        
        # 如果字段是格式字段（array、object、string、number），需要根据节点的输出格式进行转换
        if field_name in ["array", "object", "string", "number"]:
            # 获取节点的原始输出（output 字段）
            raw_output = node_output.get("output") if isinstance(node_output, dict) else None
            if raw_output is None:
                logger.warning(f"Field 'output' not found in node '{target_node_id}' output for format conversion")
                return match.group(0)
            
            # 根据格式字段进行转换
            if field_name == "array":
                # 转换为数组格式
                if isinstance(raw_output, list):
                    value = raw_output
                elif isinstance(raw_output, str):
                    # 尝试解析 JSON 字符串
                    try:
                        import json
                        parsed = json.loads(raw_output)
                        value = parsed if isinstance(parsed, list) else [parsed]
                    except:
                        value = [raw_output]
                else:
                    value = [raw_output]
            elif field_name == "object":
                # 转换为对象格式
                if isinstance(raw_output, dict):
                    value = raw_output
                elif isinstance(raw_output, str):
                    # 尝试解析 JSON 字符串
                    try:
                        import json
                        value = json.loads(raw_output)
                        if not isinstance(value, dict):
                            value = {"value": value}
                    except:
                        value = {"value": raw_output}
                else:
                    value = {"value": raw_output}
            elif field_name == "string":
                # 转换为字符串格式
                if isinstance(raw_output, (dict, list)):
                    import json
                    try:
                        value = json.dumps(raw_output, ensure_ascii=False)
                    except:
                        value = str(raw_output)
                else:
                    value = str(raw_output)
            elif field_name == "number":
                # 转换为数值格式
                if isinstance(raw_output, (int, float)):
                    value = raw_output
                elif isinstance(raw_output, str):
                    # 尝试转换为数值
                    try:
                        # 尝试转换为整数
                        if '.' not in raw_output:
                            value = int(raw_output)
                        else:
                            value = float(raw_output)
                    except:
                        # 如果转换失败，尝试从 JSON 中提取数值
                        try:
                            import json
                            parsed = json.loads(raw_output)
                            if isinstance(parsed, (int, float)):
                                value = parsed
                            else:
                                logger.warning(f"Cannot convert '{raw_output}' to number")
                                return match.group(0)
                        except:
                            logger.warning(f"Cannot convert '{raw_output}' to number")
                            return match.group(0)
                else:
                    logger.warning(f"Cannot convert '{type(raw_output)}' to number")
                    return match.group(0)
        else:
            # 普通字段，直接获取值
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


def _process_conditionals(template: str, loop_context: Optional[Dict[str, Any]] = None) -> str:
    """
    处理模板中的条件语句 {% if condition %} ... {% endif %}
    
    Args:
        template: 包含条件语句的模板字符串
        loop_context: 循环上下文，用于评估条件
        
    Returns:
        处理后的模板字符串
    """
    if not template:
        return template
    
    # 获取循环上下文中的 iteration 值
    iteration = 0
    if loop_context:
        for loop_id, ctx in loop_context.items():
            iteration = ctx.get("iteration", 0)
            break
    
    # 匹配 {% if condition %} ... {% else %} ... {% endif %}
    # 支持两种格式：
    # 1. {% if condition %} ... {% endif %}
    # 2. {% if condition %} ... {% else %} ... {% endif %}
    pattern = r'\{%\s*if\s+([^%]+)\s*%\}(.*?)(?:\{%\s*else\s*%\}(.*?))?\{%\s*endif\s*%\}'
    
    def replace_conditional(match):
        condition = match.group(1).strip()
        if_content = match.group(2) if match.group(2) else ""
        else_content = match.group(3) if match.group(3) else ""
        
        # 评估条件
        condition_met = False
        
        # 支持 loop.iteration == 1 这样的条件
        if 'loop.iteration' in condition:
            # 提取比较操作符和值
            if '==' in condition:
                parts = condition.split('==')
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    if 'loop.iteration' in left:
                        try:
                            compare_value = int(right)
                            condition_met = (iteration == compare_value)
                        except ValueError:
                            condition_met = False
                    elif 'loop.iteration' in right:
                        try:
                            compare_value = int(left)
                            condition_met = (iteration == compare_value)
                        except ValueError:
                            condition_met = False
            elif '!=' in condition:
                parts = condition.split('!=')
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    if 'loop.iteration' in left:
                        try:
                            compare_value = int(right)
                            condition_met = (iteration != compare_value)
                        except ValueError:
                            condition_met = False
                    elif 'loop.iteration' in right:
                        try:
                            compare_value = int(left)
                            condition_met = (iteration != compare_value)
                        except ValueError:
                            condition_met = False
            elif '>' in condition and '>=' not in condition and '=>' not in condition:
                parts = condition.split('>')
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    if 'loop.iteration' in left:
                        try:
                            compare_value = int(right)
                            condition_met = (iteration > compare_value)
                        except ValueError:
                            condition_met = False
                    elif 'loop.iteration' in right:
                        try:
                            compare_value = int(left)
                            condition_met = (compare_value > iteration)
                        except ValueError:
                            condition_met = False
            elif '<' in condition and '<=' not in condition and '=<' not in condition:
                parts = condition.split('<')
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    if 'loop.iteration' in left:
                        try:
                            compare_value = int(right)
                            condition_met = (iteration < compare_value)
                        except ValueError:
                            condition_met = False
                    elif 'loop.iteration' in right:
                        try:
                            compare_value = int(left)
                            condition_met = (compare_value < iteration)
                        except ValueError:
                            condition_met = False
            elif '>=' in condition:
                parts = condition.split('>=')
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    if 'loop.iteration' in left:
                        try:
                            compare_value = int(right)
                            condition_met = (iteration >= compare_value)
                        except ValueError:
                            condition_met = False
                    elif 'loop.iteration' in right:
                        try:
                            compare_value = int(left)
                            condition_met = (compare_value >= iteration)
                        except ValueError:
                            condition_met = False
            elif '<=' in condition:
                parts = condition.split('<=')
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    if 'loop.iteration' in left:
                        try:
                            compare_value = int(right)
                            condition_met = (iteration <= compare_value)
                        except ValueError:
                            condition_met = False
                    elif 'loop.iteration' in right:
                        try:
                            compare_value = int(left)
                            condition_met = (compare_value <= iteration)
                        except ValueError:
                            condition_met = False
        
        # 如果条件满足，返回 if 分支内容；否则返回 else 分支内容（如果有）
        if condition_met:
            return if_content
        else:
            return else_content
    
    # 使用 DOTALL 标志以支持多行内容
    result = re.sub(pattern, replace_conditional, template, flags=re.DOTALL)
    return result


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

