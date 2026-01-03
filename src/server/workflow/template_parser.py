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
                # 解析变量路径，支持 variables.变量名 或 variables.变量名.字段名
                var_path_parts = loop_field.split(".", 2)  # 最多分割为3部分
                var_name = var_path_parts[1] if len(var_path_parts) > 1 else None
                field_name = var_path_parts[2] if len(var_path_parts) > 2 else None
                
                variables = current_loop_context.get("variables", {})
                value = variables.get(var_name) if var_name else None
                
                if value is None:
                    logger.debug(f"Loop variable '{var_name}' not found in variables: {list(variables.keys())}")
                elif field_name:
                    # 如果指定了字段名，尝试从变量值中提取字段
                    # 处理数组：从第一个元素提取字段
                    if isinstance(value, list) and len(value) > 0:
                        first_item = value[0]
                        # 如果第一个元素是数组（嵌套数组），继续取第一个元素
                        while isinstance(first_item, list) and len(first_item) > 0:
                            first_item = first_item[0]
                        if isinstance(first_item, dict):
                            value = first_item.get(field_name)
                            if value is not None:
                                logger.debug(f"Found field '{field_name}' in loop variable '{var_name}' array first item")
                        elif hasattr(first_item, field_name):
                            value = getattr(first_item, field_name, None)
                    # 处理对象：直接从对象提取字段
                    elif isinstance(value, dict):
                        value = value.get(field_name)
                        if value is not None:
                            logger.debug(f"Found field '{field_name}' in loop variable '{var_name}' dict")
                    # 处理JSON字符串：先解析再提取
                    elif isinstance(value, str):
                        try:
                            import json
                            parsed = json.loads(value)
                            # 如果解析后是数组，从第一个元素提取字段
                            if isinstance(parsed, list) and len(parsed) > 0:
                                first_item = parsed[0]
                                # 如果第一个元素是数组（嵌套数组），继续取第一个元素
                                while isinstance(first_item, list) and len(first_item) > 0:
                                    first_item = first_item[0]
                                if isinstance(first_item, dict):
                                    value = first_item.get(field_name)
                                elif hasattr(first_item, field_name):
                                    value = getattr(first_item, field_name, None)
                            elif isinstance(parsed, dict):
                                value = parsed.get(field_name)
                        except (json.JSONDecodeError, ValueError):
                            logger.debug(f"Loop variable '{var_name}' is a string but not valid JSON, cannot extract field '{field_name}'")
                            value = None
                    
                    if value is None:
                        logger.debug(f"Field '{field_name}' not found in loop variable '{var_name}'")
                # 如果没有指定字段名，返回整个变量值（保持原有行为）
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
        value = None
        if isinstance(node_output, dict):
            # 统一从 output 字段中提取变量（除了格式字段）
            # 格式字段（array、object、string、number、output）需要特殊处理
            if field_name not in ["array", "object", "string", "number", "output"]:
                # 检查是否是嵌套路径（如 output.content）
                if field_name.startswith("output."):
                    # 提取嵌套字段名（如 content）
                    nested_field = field_name[len("output."):]
                    raw_output = node_output.get("output")
                    if raw_output is not None:
                        # 如果 output 是字符串，尝试解析为 JSON
                        if isinstance(raw_output, str):
                            try:
                                import json
                                parsed = json.loads(raw_output)
                                raw_output = parsed
                                logger.debug(f"Parsed JSON string from output for node '{target_node_id}'")
                            except (json.JSONDecodeError, ValueError):
                                logger.debug(f"Output is a string but not valid JSON for node '{target_node_id}', treating as plain string")
                        
                        # 如果 output 是数组，尝试从第一个元素中获取字段
                        if isinstance(raw_output, list):
                            if len(raw_output) > 0:
                                first_item = raw_output[0]
                                # 如果第一个元素是数组（嵌套数组），继续取第一个元素
                                while isinstance(first_item, list) and len(first_item) > 0:
                                    first_item = first_item[0]
                                if isinstance(first_item, dict):
                                    value = first_item.get(nested_field)
                                    if value is not None:
                                        logger.debug(f"Found field '{nested_field}' in array output first item for node '{target_node_id}'")
                                elif hasattr(first_item, nested_field):
                                    value = getattr(first_item, nested_field, None)
                            else:
                                logger.warning(f"Output array is empty for node '{target_node_id}', cannot extract field '{nested_field}'")
                        # 如果 output 是字典，尝试从字典中获取字段
                        elif isinstance(raw_output, dict):
                            value = raw_output.get(nested_field)
                            if value is not None:
                                logger.debug(f"Found field '{nested_field}' in output dict for node '{target_node_id}'")
                        # 如果 output 是其他类型（如字符串但解析失败），记录警告
                        elif isinstance(raw_output, str):
                            logger.warning(f"Output is a plain string for node '{target_node_id}', cannot extract field '{nested_field}' from string")
                else:
                    # 普通字段，统一从 output 字段中提取（兼容旧格式）
                    raw_output = node_output.get("output")
                    if raw_output is not None:
                        # 如果 output 是字符串，尝试解析为 JSON
                        if isinstance(raw_output, str):
                            try:
                                import json
                                parsed = json.loads(raw_output)
                                raw_output = parsed
                                logger.debug(f"Parsed JSON string from output for node '{target_node_id}'")
                            except (json.JSONDecodeError, ValueError):
                                logger.debug(f"Output is a string but not valid JSON for node '{target_node_id}', treating as plain string")
                        
                        # 如果 output 是数组，尝试从第一个元素中获取字段
                        if isinstance(raw_output, list):
                            if len(raw_output) > 0:
                                first_item = raw_output[0]
                                # 如果第一个元素是数组（嵌套数组），继续取第一个元素
                                while isinstance(first_item, list) and len(first_item) > 0:
                                    first_item = first_item[0]
                                if isinstance(first_item, dict):
                                    value = first_item.get(field_name)
                                    if value is not None:
                                        logger.debug(f"Found field '{field_name}' in array output first item for node '{target_node_id}'")
                                elif hasattr(first_item, field_name):
                                    value = getattr(first_item, field_name, None)
                            else:
                                logger.warning(f"Output array is empty for node '{target_node_id}', cannot extract field '{field_name}'")
                        # 如果 output 是字典，尝试从字典中获取字段
                        elif isinstance(raw_output, dict):
                            value = raw_output.get(field_name)
                            if value is not None:
                                logger.debug(f"Found field '{field_name}' in output dict for node '{target_node_id}'")
                        # 如果 output 是其他类型（如字符串但解析失败），记录警告
                        elif isinstance(raw_output, str):
                            logger.warning(f"Output is a plain string for node '{target_node_id}', cannot extract field '{field_name}' from string")
        else:
            # 如果输出不是字典，尝试直接访问属性
            value = getattr(node_output, field_name, None)
        
        # 如果字段是 "output"，直接返回节点的 output 字段
        if field_name == "output":
            if isinstance(node_output, dict):
                raw_output = node_output.get("output")
                if raw_output is not None:
                    # 如果 output 是字符串，尝试解析为 JSON
                    if isinstance(raw_output, str):
                        try:
                            import json
                            parsed = json.loads(raw_output)
                            value = parsed
                            logger.debug(f"Parsed JSON string from output field for node '{target_node_id}'")
                        except (json.JSONDecodeError, ValueError):
                            # 如果解析失败，直接使用字符串
                            value = raw_output
                            logger.debug(f"Output is a string but not valid JSON for node '{target_node_id}', using as-is")
                    else:
                        value = raw_output
                else:
                    logger.warning(f"Field 'output' is None for node '{target_node_id}'")
                    value = None
            else:
                logger.warning(f"Node output is not a dict for node '{target_node_id}', cannot get 'output' field")
                value = None
        
        # 如果字段是格式字段（array、object、string、number），需要根据节点的输出格式进行转换
        elif field_name in ["array", "object", "string", "number"]:
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

