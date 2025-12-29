# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流编译器

将工作流配置编译为LangGraph图结构
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict, Annotated
from typing_extensions import NotRequired
from langgraph.graph import END, START, StateGraph
from src.server.workflow_request import WorkflowConfigRequest, WorkflowNode, WorkflowEdge
from src.server.workflow.template_parser import render_template
from src.llms.llm import get_llm_by_model_name

logger = logging.getLogger(__name__)


def get_tool_by_name(tool_name: str):
    """
    根据工具名称获取工具实例
    
    Args:
        tool_name: 工具名称
        
    Returns:
        工具实例或None
    """
    # 从工具注册表获取工具
    from src.server.app import TOOL_REGISTRY
    return TOOL_REGISTRY.get(tool_name)


def format_node_output(output: Any, output_format: str, output_fields: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    根据输出格式和定义的字段处理节点输出
    
    Args:
        output: 节点的原始输出
        output_format: 输出格式（"json" 或 "array"）
        output_fields: 输出字段定义列表，每个字段包含 name 和 type
        
    Returns:
        包含 output 字段的输出字典，output 字段存储格式化后的数据
    """
    import json
    
    # 如果没有定义字段，直接返回原始输出
    if not output_fields or not isinstance(output_fields, list):
        return {
            "output": output
        }
    
    # 尝试解析输出（如果是字符串，尝试解析为 JSON）
    parsed_output = output
    if isinstance(output, str):
        try:
            parsed_output = json.loads(output)
        except:
            parsed_output = output
    
    # 检查是否是JSON Schema格式（LLM可能返回 {'type': 'array', 'items': [...]}）
    if isinstance(parsed_output, dict):
        # 如果包含 'type': 'array' 和 'items'，提取 items 作为实际数据
        if parsed_output.get('type') == 'array' and 'items' in parsed_output:
            items = parsed_output.get('items')
            # 如果 items 是数组，直接使用
            if isinstance(items, list):
                parsed_output = items
            # 如果 items 是对象（单个item），转换为数组
            elif isinstance(items, dict):
                parsed_output = [items]
        # 如果包含 'items' 字段（可能是数组格式的JSON Schema）
        elif 'items' in parsed_output and isinstance(parsed_output.get('items'), list):
            parsed_output = parsed_output['items']
    
    # 根据输出格式处理
    if output_format == "array":
        # 数组格式：[{}]
        if isinstance(parsed_output, list):
            # 如果是数组，处理每个元素
            formatted_items = []
            for item in parsed_output:
                formatted_item = {}
                for field in output_fields:
                    field_name = field.get("name") if isinstance(field, dict) else None
                    field_type = field.get("type") if isinstance(field, dict) else "String"
                    if field_name:
                        # 从 item 中提取字段值
                        if isinstance(item, dict):
                            field_value = item.get(field_name)
                            # 如果字段值不存在，尝试从其他可能的键名获取（兼容性处理）
                            if field_value is None:
                                # 尝试小写、大写等变体
                                for key in item.keys():
                                    if key.lower() == field_name.lower():
                                        field_value = item[key]
                                        break
                        else:
                            field_value = None
                        # 根据类型转换（只有在值不为None时才转换，None会使用默认值）
                        formatted_item[field_name] = convert_field_value(field_value, field_type)
                formatted_items.append(formatted_item)
            # 将格式化后的数组存储到 output 字段（严格按照配置的格式）
            return {
                "output": formatted_items
            }
        else:
            # 如果不是数组，转换为数组格式
            formatted_item = {}
            for field in output_fields:
                field_name = field.get("name") if isinstance(field, dict) else None
                field_type = field.get("type") if isinstance(field, dict) else "String"
                if field_name:
                    if isinstance(parsed_output, dict):
                        field_value = parsed_output.get(field_name)
                    else:
                        field_value = None
                    formatted_item[field_name] = convert_field_value(field_value, field_type)
            # 将单个对象转换为数组
            return {
                "output": [formatted_item]
            }
    else:
        # JSON 格式：{}
        if isinstance(parsed_output, dict):
            # 如果是对象，提取定义的字段，构建格式化后的对象
            formatted_obj = {}
            for field in output_fields:
                field_name = field.get("name") if isinstance(field, dict) else None
                field_type = field.get("type") if isinstance(field, dict) else "String"
                if field_name:
                    field_value = parsed_output.get(field_name)
                    formatted_obj[field_name] = convert_field_value(field_value, field_type)
            # 将格式化后的对象存储到 output 字段（严格按照配置的格式）
            return {
                "output": formatted_obj
            }
        else:
            # 如果不是对象，尝试构建格式化后的对象
            formatted_obj = {}
            for field in output_fields:
                field_name = field.get("name") if isinstance(field, dict) else None
                field_type = field.get("type") if isinstance(field, dict) else "String"
                if field_name:
                    # 如果无法提取，使用 None
                    formatted_obj[field_name] = convert_field_value(None, field_type)
            return {
                "output": formatted_obj
            }


def generate_output_schema_prompt(output_format: str, output_fields: Optional[List[Dict[str, Any]]]) -> str:
    """
    根据输出格式和字段定义生成 JSON Schema 描述，用于拼接到系统提示词中
    
    Args:
        output_format: 输出格式（"json" 或 "array"）
        output_fields: 输出字段定义列表，每个字段包含 name 和 type
        
    Returns:
        JSON Schema 描述字符串，如果没有配置则返回空字符串
    """
    if not output_fields or not isinstance(output_fields, list) or len(output_fields) == 0:
        return ""
    
    # 类型映射
    type_mapping = {
        "String": "string",
        "Integer": "integer",
        "Boolean": "boolean",
    }
    
    # 构建属性定义
    properties = {}
    for field in output_fields:
        if not isinstance(field, dict):
            continue
        field_name = field.get("name")
        field_type = field.get("type", "String")
        if field_name:
            properties[field_name] = {
                "type": type_mapping.get(field_type, "string"),
                "description": f"字段 {field_name}"
            }
    
    if not properties:
        return ""
    
    # 根据格式生成 schema
    if output_format == "array":
        # 数组格式：[{}]
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": properties,
                "required": list(properties.keys())
            }
        }
    else:
        # JSON 格式：{}
        schema = {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys())
        }
    
    import json
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
    
    return f"""

请严格按照以下 JSON Schema 格式输出结果：
```json
{schema_json}
```

要求：
1. 输出必须是有效的 JSON 格式
2. 所有字段都必须包含在输出中
3. 字段类型必须符合 schema 定义
4. 不要添加任何额外的说明或注释，只输出 JSON
"""


def convert_field_value(value: Any, field_type: str) -> Any:
    """
    根据字段类型转换值
    
    Args:
        value: 原始值
        field_type: 字段类型（"String", "Integer", "Boolean"）
        
    Returns:
        转换后的值
    """
    if value is None:
        if field_type == "Integer":
            return 0
        elif field_type == "Boolean":
            return False
        else:
            return ""
    
    if field_type == "Integer":
        try:
            if isinstance(value, (int, float)):
                return int(value)
            elif isinstance(value, str):
                return int(float(value)) if '.' in value else int(value)
            else:
                return 0
        except:
            return 0
    elif field_type == "Boolean":
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        elif isinstance(value, (int, float)):
            return bool(value)
        else:
            return False
    else:  # String
        return str(value)


# 定义 reducer 函数，用于合并并发更新的 node_outputs
def merge_node_outputs(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """
    合并两个 node_outputs 字典，支持并发更新
    
    当多个节点并行执行时，它们都会返回自己的 node_outputs 更新。
    这个函数将合并这些更新，确保所有节点的输出都被保留。
    
    Args:
        left: 左侧的 node_outputs 字典（可能是 None）
        right: 右侧的 node_outputs 字典（可能是 None）
        
    Returns:
        合并后的 node_outputs 字典
    """
    # 处理 None 值
    if left is None:
        left = {}
    if right is None:
        right = {}
    
    # 创建新字典，合并两个字典
    result = dict(left)
    result.update(right)
    
    return result


# 定义 reducer 函数，用于处理 state_manager 的并发更新
def merge_state_manager(left: Any, right: Any) -> Any:
    """
    合并两个 state_manager 对象，支持并发更新
    
    state_manager 是一个共享对象，所有节点都应该使用同一个实例。
    当多个节点并行执行时，它们都会返回 state_manager，但应该都是同一个对象。
    
    Args:
        left: 左侧的 state_manager（可能是 None）
        right: 右侧的 state_manager（可能是 None）
        
    Returns:
        合并后的 state_manager（优先返回非 None 的值，如果都是 None 则返回 None）
    """
    # 如果两个值都是 None，返回 None
    if left is None and right is None:
        return None
    
    # 如果一个是 None，返回非 None 的那个
    if left is None:
        return right
    if right is None:
        return left
    
    # 如果两个都不是 None，它们应该是同一个对象，返回第一个
    # 如果它们不是同一个对象，返回第一个（这种情况不应该发生）
    return left


# 定义工作流状态
# 使用 TypedDict 确保 LangGraph 能正确识别和处理状态结构
class WorkflowState(TypedDict):
    """工作流执行状态"""
    workflow_inputs: Dict[str, Any]
    node_outputs: Annotated[Dict[str, Any], merge_node_outputs]  # 使用 reducer 处理并发更新
    state_manager: Annotated[Optional[Any], merge_state_manager]  # 状态管理器，使用 reducer 处理并发更新，可选
    loop_context: NotRequired[Dict[str, Any]]  # 循环上下文，用于循环节点


def get_nested_field_value(data: Any, field_path: str) -> Any:
    """
    从数据中获取嵌套字段值，支持路径如 "score" 或 "output.score"
    
    Args:
        data: 数据对象（字典或列表）
        field_path: 字段路径，如 "score" 或 "output.score"
        
    Returns:
        字段值，如果不存在则返回 None
    """
    if not field_path or not data:
        return None
    
    parts = field_path.split('.')
    current = data
    
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
            else:
                return None
        else:
            return None
        
        if current is None:
            return None
    
    return current


def evaluate_condition(field_value: Any, operator: str, compare_value: Any) -> bool:
    """
    评估条件表达式
    
    Args:
        field_value: 字段值
        operator: 操作符（">=", "<=", ">", "<", "==", "!="）
        compare_value: 比较值
        
    Returns:
        条件是否满足
    """
    if field_value is None:
        return False
    
    try:
        # 尝试数值比较
        if operator == ">=":
            return float(field_value) >= float(compare_value)
        elif operator == "<=":
            return float(field_value) <= float(compare_value)
        elif operator == ">":
            return float(field_value) > float(compare_value)
        elif operator == "<":
            return float(field_value) < float(compare_value)
        elif operator == "==":
            return str(field_value) == str(compare_value)
        elif operator == "!=":
            return str(field_value) != str(compare_value)
    except (ValueError, TypeError):
        # 如果无法转换为数值，使用字符串比较
        if operator == "==":
            return str(field_value) == str(compare_value)
        elif operator == "!=":
            return str(field_value) != str(compare_value)
    
    return False


def filter_data_by_condition(
    data: Any,  # 可以是数组或对象
    field_path: str,  # 如 "score" 或 "output.score"
    operator: str,  # ">=", "<=", ">", "<", "==", "!="
    compare_value: Any
) -> tuple[List[Any], List[Any]]:
    """
    根据条件筛选数据，返回 (passed_items, pending_items)
    支持数组和非数组格式
    
    Args:
        data: 要筛选的数据，可以是数组或对象
        field_path: 字段路径，如 "score" 或 "output.score"
        operator: 操作符
        compare_value: 比较值
        
    Returns:
        (passed_items, pending_items) 元组
    """
    passed = []
    pending = []
    
    if isinstance(data, list):
        # 数组格式：逐个元素筛选
        for item in data:
            field_value = get_nested_field_value(item, field_path)
            if evaluate_condition(field_value, operator, compare_value):
                passed.append(item)
            else:
                pending.append(item)
    else:
        # 非数组格式：整体筛选
        field_value = get_nested_field_value(data, field_path)
        if evaluate_condition(field_value, operator, compare_value):
            passed.append(data)
        else:
            pending.append(data)
    
    return passed, pending


def build_loop_subgraph(
    loop_node_id: str,
    nodes: List[WorkflowNode],
    edges: List[WorkflowEdge],
    state_manager: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    构建循环体子图信息
    
    Args:
        loop_node_id: 循环节点ID
        nodes: 所有节点列表
        edges: 所有边列表
        state_manager: 状态管理器（可选）
        
    Returns:
        循环体子图信息字典，包含节点和边的列表，如果循环体内没有节点则返回None
    """
    # 筛选循环体内的节点（通过loopId标记）
    # 同时也排除循环节点自身，防止死循环递归
    loop_body_nodes = [
        n for n in nodes 
        if n.id != loop_node_id and (
           (hasattr(n.data, 'loopId') and n.data.loopId == loop_node_id) or
           (hasattr(n.data, 'loop_id') and n.data.loop_id == loop_node_id) or
           (isinstance(n.data, dict) and (n.data.get("loopId") == loop_node_id or n.data.get("loop_id") == loop_node_id))
        )
    ]
    
    if not loop_body_nodes:
        logger.warning(f"Loop node {loop_node_id} has no body nodes")
        return None
    
    # 获取循环体内节点的ID集合
    body_node_ids = {n.id for n in loop_body_nodes}
    
    # 筛选循环体内的边（起点和终点都在循环体内）
    loop_body_edges = [
        e for e in edges
        if e.source in body_node_ids and e.target in body_node_ids
    ]
    
    # 查找入口节点（循环体内没有上游节点的节点）
    entry_nodes = [
        n for n in loop_body_nodes
        if not any(e.target == n.id and e.source not in body_node_ids for e in edges)
    ]
    
    # 查找出口节点（循环体内没有下游节点的节点）
    exit_nodes = [
        n for n in loop_body_nodes
        if not any(e.source == n.id and e.target not in body_node_ids for e in loop_body_edges)
    ]
    
    if not entry_nodes:
        logger.warning(f"Loop node {loop_node_id} has no entry nodes")
        return None
    
    if not exit_nodes:
        logger.warning(f"Loop node {loop_node_id} has no exit nodes")
        return None
    
    logger.info(f"Loop node {loop_node_id} subgraph: {len(loop_body_nodes)} nodes, {len(loop_body_edges)} edges, {len(entry_nodes)} entry nodes, {len(exit_nodes)} exit nodes")
    
    return {
        "nodes": loop_body_nodes,
        "edges": loop_body_edges,
        "entry_nodes": entry_nodes,
        "exit_nodes": exit_nodes,
        "body_node_ids": body_node_ids,
    }


def compile_workflow_to_langgraph(config: WorkflowConfigRequest):
    """
    将工作流配置编译为LangGraph图
    
    Args:
        config: 工作流配置请求
        
    Returns:
        编译后的LangGraph图
    """
    nodes = config.nodes
    edges = config.edges
    
    # 构建节点映射
    node_map: Dict[str, WorkflowNode] = {node.id: node for node in nodes}
    
    # 构建边映射（按目标节点分组）
    edges_by_target: Dict[str, List[WorkflowEdge]] = {}
    edges_by_source: Dict[str, List[WorkflowEdge]] = {}
    for edge in edges:
        edges_by_target.setdefault(edge.target, []).append(edge)
        edges_by_source.setdefault(edge.source, []).append(edge)
    
    # 查找开始和结束节点
    start_node = next((n for n in nodes if n.type == "start"), None)
    end_node = next((n for n in nodes if n.type == "end"), None)
    
    if not start_node:
        raise ValueError("工作流必须包含一个开始节点")
    if not end_node:
        raise ValueError("工作流必须包含一个结束节点")
    
    # 创建状态图
    # 使用 TypedDict 确保 LangGraph 能正确识别和处理状态结构
    builder = StateGraph(WorkflowState)
    
    # 为每个节点创建执行函数
    node_functions: Dict[str, callable] = {}
    
    # 识别循环体内的节点（不添加到主图，只在循环节点执行时执行）
    body_node_ids = set()
    for node in nodes:
        loop_id = None
        if hasattr(node.data, 'loopId') and node.data.loopId:
            loop_id = node.data.loopId
        elif hasattr(node.data, 'loop_id') and node.data.loop_id:
            loop_id = node.data.loop_id
        elif isinstance(node.data, dict):
            loop_id = node.data.get("loopId") or node.data.get("loop_id")
        
        if loop_id:
            body_node_ids.add(node.id)
    
    logger.info(f"Found {len(body_node_ids)} nodes in loop bodies, will be executed within loop nodes")
    
    for node in nodes:
        node_id = node.id
        node_type = node.type
        node_data = node.data
        
        # 检查是否是循环体内的节点
        is_body_node = node_id in body_node_ids
        
        if node_type == "start":
            # 开始节点：传递输入
            def make_start_node(nid: str, ndata: Any):
                async def start_node_func(state: WorkflowState):
                    # 获取状态管理器（必须在函数开始时获取）
                    state_manager = state.get("state_manager")
                    if not state_manager:
                        logger.error(f"State manager is None for start node {nid}! State keys: {list(state.keys())}")
                        # 即使状态管理器为 None，也继续执行，但记录错误
                    
                    logger.info(f"Executing start node {nid}, state_manager present: {state_manager is not None}, state keys: {list(state.keys())}")
                    
                    # 获取工作流输入
                    workflow_inputs = state.get("workflow_inputs", {})
                    
                    if state_manager:
                        state_manager.mark_node_running(nid, input_data=workflow_inputs)
                    
                    # 开始节点的输出：简化为 {"input": "..."} 格式
                    # 优先从 workflow_inputs 中获取 "input" 字段，如果没有则使用整个 workflow_inputs
                    if "input" in workflow_inputs:
                        outputs = {
                            "input": workflow_inputs["input"]
                        }
                    else:
                        # 如果没有 "input" 字段，尝试从其他字段获取，或使用第一个值
                        if len(workflow_inputs) == 1:
                            outputs = {
                                "input": list(workflow_inputs.values())[0]
                            }
                        else:
                            # 多个字段时，使用整个 workflow_inputs 作为 input
                            outputs = {
                                "input": workflow_inputs
                            }
                    
                    # 更新状态 - 创建新的状态字典，确保 state_manager 被保留
                    node_outputs = dict(state.get("node_outputs", {}))
                    node_outputs[nid] = outputs
                    
                    # 构建返回状态，确保 state_manager 被保留
                    result_state: WorkflowState = {
                        "workflow_inputs": workflow_inputs,
                        "node_outputs": node_outputs,
                    }
                    
                    # 确保状态管理器被保留在返回的状态中
                    if state_manager:
                        result_state["state_manager"] = state_manager
                        state_manager.mark_node_success(nid, outputs)
                    
                    logger.info(f"Start node {nid} completed successfully, returning state with keys: {list(result_state.keys())}")
                    return result_state
                return start_node_func
            
            node_functions[node_id] = make_start_node(node_id, node_data)
            # 循环体内的节点不添加到主图
            if node_id not in body_node_ids:
                builder.add_node(node_id, node_functions[node_id])
            
        elif node_type == "end":
            # 结束节点：收集最终输出
            def make_end_node(nid: str):
                async def end_node_func(state: WorkflowState):
                    # 获取状态管理器（必须在函数开始时获取）
                    state_manager = state.get("state_manager")
                    if not state_manager:
                        logger.warning(f"State manager is None for end node {nid}, node execution may not be logged")
                    
                    logger.info(f"Executing end node {nid}")
                    
                    if state_manager:
                        state_manager.mark_node_running(nid)
                    
                    # 获取所有上游节点的输出
                    incoming_edges = edges_by_target.get(nid, [])
                    final_outputs = {}
                    
                    for edge in incoming_edges:
                        source_id = edge.source
                        source_outputs = state.get("node_outputs", {}).get(source_id, {})
                        final_outputs[source_id] = source_outputs
                    
                    # 更新节点输出
                    node_outputs = dict(state.get("node_outputs", {}))
                    node_outputs[nid] = final_outputs
                    
                    # 构建返回状态（不返回 workflow_inputs，避免并行执行时的冲突）
                    result_state: WorkflowState = {
                        "node_outputs": node_outputs,
                    }
                    
                    # 确保状态管理器被保留在返回的状态中
                    if state_manager:
                        result_state["state_manager"] = state_manager
                        state_manager.mark_node_success(nid, final_outputs)
                    
                    logger.info(f"End node {nid} completed successfully, returning state with keys: {list(result_state.keys())}")
                    return result_state
                return end_node_func
            
            node_functions[node_id] = make_end_node(node_id)
            # 循环体内的节点不添加到主图
            if node_id not in body_node_ids:
                builder.add_node(node_id, node_functions[node_id])
            
        elif node_type == "llm":
            # LLM节点：调用大语言模型
            def make_llm_node(nid: str, ndata: Any):
                async def llm_node_func(state: WorkflowState):
                    # 获取状态管理器（必须在函数开始时获取）
                    state_manager = state.get("state_manager")
                    if not state_manager:
                        logger.warning(f"State manager is None for LLM node {nid}, state keys: {list(state.keys())}, state type: {type(state)}")
                    
                    try:
                        # 收集上游节点输出
                        node_outputs = state.get("node_outputs", {})
                        incoming_edges = edges_by_target.get(nid, [])
                        
                        # 检查上游节点是否完成（READY 状态检查）
                        if state_manager and incoming_edges:
                            upstream_completed = True
                            for edge in incoming_edges:
                                source_id = edge.source
                                # 检查上游节点是否有输出（表示已完成）
                                if source_id not in node_outputs:
                                    upstream_completed = False
                                    break
                            
                            if upstream_completed:
                                # 上游节点已完成，标记为 READY
                                state_manager.mark_node_ready(nid)
                                logger.info(f"LLM node {nid} is ready (upstream nodes completed)")
                        
                        # 获取LLM实例（支持两种字段名格式）
                        model_name = getattr(ndata, 'llm_model', None) or getattr(ndata, 'llmModel', None)
                        if not model_name:
                            raise ValueError(f"LLM节点 {nid} 未配置模型")
                        
                        # 获取原始 prompt（模板解析前）
                        raw_prompt = getattr(ndata, 'llm_prompt', None) or getattr(ndata, 'llmPrompt', None) or ""
                        raw_system_prompt = getattr(ndata, 'llm_system_prompt', None) or getattr(ndata, 'llmSystemPrompt', None) or ""
                        
                        # 记录开始状态和输入（在模板解析之前，使用原始 prompt）
                        # 检查是否在循环体内
                        loop_context = state.get("loop_context", {})
                        loop_id = None
                        iteration = None
                        if loop_context:
                            # 获取当前循环的ID和迭代次数（如果有多个循环，使用第一个）
                            for ctx_loop_id, ctx_data in loop_context.items():
                                loop_id = ctx_loop_id
                                iteration = ctx_data.get("iteration", 0)
                                break
                        
                        if state_manager:
                            input_data = {
                                "model": model_name,
                                "prompt": raw_prompt,
                                "system_prompt": raw_system_prompt
                            }
                            state_manager.mark_node_running(nid, input_data=input_data, loop_id=loop_id, iteration=iteration)
                        
                        # 构建节点标签映射（用于模板解析）
                        # 注意：n.data 是 WorkflowNodeData 对象，应该使用 node_name 属性
                        node_labels = {}
                        for n in nodes:
                            # 优先使用 node_name（从 WorkflowNodeData），然后是 label，最后是节点 ID
                            node_name = None
                            if hasattr(n.data, 'node_name') and n.data.node_name:
                                node_name = n.data.node_name
                            elif hasattr(n.data, 'nodeName') and n.data.nodeName:
                                node_name = n.data.nodeName
                            elif hasattr(n.data, 'label') and n.data.label:
                                node_name = n.data.label
                            else:
                                node_name = n.id
                            node_labels[n.id] = str(node_name) if node_name is not None else str(n.id)
                        
                        # 构建节点输出格式映射（用于模板解析）
                        node_output_formats = {}
                        for n in nodes:
                            n_data = n.data
                            n_format = "output"
                            if hasattr(n_data, 'output_format') and n_data.output_format:
                                n_format = n_data.output_format
                            elif hasattr(n_data, 'outputFormat') and n_data.outputFormat:
                                n_format = n_data.outputFormat
                            elif isinstance(n_data, dict):
                                n_format = n_data.get("output_format") or n_data.get("outputFormat") or "output"
                            node_output_formats[n.id] = n_format
                        
                        # 解析prompt模板（支持两种字段名格式）
                        prompt = raw_prompt
                        system_prompt = raw_system_prompt
                        if prompt:
                            # 获取循环上下文（如果当前节点在循环体内）
                            loop_context = state.get("loop_context", {})
                            prompt = render_template(prompt, node_outputs, node_labels, loop_context, node_output_formats)
                            if system_prompt:
                                system_prompt = render_template(system_prompt, node_outputs, node_labels, loop_context, node_output_formats)
                        
                        logger.info(f"Executing LLM node {nid} with model {model_name}")
                        
                        llm = get_llm_by_model_name(model_name)
                        temperature = getattr(ndata, 'llm_temperature', None) or getattr(ndata, 'llmTemperature', None) or 0.7
                        if hasattr(llm, 'temperature'):
                            llm.temperature = temperature
                        
                        # 检查是否有输出格式配置，如果有则拼接到系统提示词
                        output_format = "json"
                        output_fields = None
                        if hasattr(ndata, 'output_format') and ndata.output_format:
                            output_format = ndata.output_format
                        elif hasattr(ndata, 'outputFormat') and ndata.outputFormat:
                            output_format = ndata.outputFormat
                        elif isinstance(ndata, dict):
                            output_format = ndata.get("output_format") or ndata.get("outputFormat") or "json"
                        
                        if hasattr(ndata, 'output_fields') and ndata.output_fields:
                            output_fields = ndata.output_fields
                        elif hasattr(ndata, 'outputFields') and ndata.outputFields:
                            output_fields = ndata.outputFields
                        elif isinstance(ndata, dict):
                            output_fields = ndata.get("output_fields") or ndata.get("outputFields")
                        
                        # 如果配置了输出格式，生成 schema 并拼接到系统提示词
                        final_system_prompt = system_prompt
                        if output_fields and isinstance(output_fields, list) and len(output_fields) > 0:
                            schema_prompt = generate_output_schema_prompt(output_format, output_fields)
                            if schema_prompt:
                                # 如果原来有系统提示词，拼接；如果没有，直接使用 schema 提示词
                                if final_system_prompt:
                                    final_system_prompt = final_system_prompt + schema_prompt
                                else:
                                    final_system_prompt = schema_prompt.strip()
                        
                        # 构建消息
                        from langchain_core.messages import HumanMessage, SystemMessage
                        messages = []
                        if final_system_prompt:
                            messages.append(SystemMessage(content=final_system_prompt))
                        messages.append(HumanMessage(content=prompt))
                        
                        # 调用LLM
                        logger.info(f"Invoking LLM node {nid} (model: {model_name})")
                        try:
                            response = await llm.ainvoke(messages)
                            logger.info(f"LLM node {nid} invocation successful")
                        except BaseException as e:
                            logger.error(f"LLM node {nid} invocation failed with {type(e).__name__}: {e}", exc_info=True)
                            raise
                        
                        response_content = response.content if hasattr(response, 'content') else str(response)
                        
                        # 提取JSON内容（如果包含markdown代码块）
                        import re
                        import json
                        json_match = re.search(r'```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```', response_content, re.DOTALL)
                        if json_match:
                            response_content = json_match.group(1).strip()
                        else:
                            # 尝试直接提取JSON对象或数组
                            json_match = re.search(r'(\[.*?\]|\{.*?\})', response_content, re.DOTALL)
                            if json_match:
                                response_content = json_match.group(1).strip()
                        
                        # 尝试解析为JSON对象（如果还是字符串）
                        parsed_response = response_content
                        if isinstance(response_content, str):
                            try:
                                parsed_response = json.loads(response_content)
                                logger.debug(f"LLM node {nid} parsed response: {parsed_response}")
                            except json.JSONDecodeError as e:
                                logger.warning(f"LLM node {nid} failed to parse JSON: {e}, raw content: {response_content[:200]}")
                                parsed_response = response_content
                        
                        # 检查是否是JSON Schema格式（LLM可能返回 {'type': 'array', 'items': [...]}）
                        if isinstance(parsed_response, dict):
                            # 如果包含 'type': 'array' 和 'items'，提取 items 作为实际数据
                            if parsed_response.get('type') == 'array' and 'items' in parsed_response:
                                items = parsed_response.get('items')
                                # 如果 items 是数组，直接使用
                                if isinstance(items, list):
                                    parsed_response = items
                                    logger.debug(f"LLM node {nid} extracted items from JSON Schema: {len(items)} items")
                                # 如果 items 是对象（单个item），转换为数组
                                elif isinstance(items, dict):
                                    parsed_response = [items]
                                    logger.debug(f"LLM node {nid} converted single item to array from JSON Schema")
                            # 如果包含 'items' 字段（可能是数组格式的JSON Schema）
                            elif 'items' in parsed_response and isinstance(parsed_response.get('items'), list):
                                parsed_response = parsed_response['items']
                                logger.debug(f"LLM node {nid} extracted items array from JSON Schema: {len(parsed_response)} items")
                        
                        # 获取Token消耗等指标
                        metrics = {}
                        if hasattr(response, 'response_metadata'):
                            token_usage = response.response_metadata.get('token_usage', {})
                            if token_usage:
                                metrics['token_usage'] = token_usage
                                metrics['total_tokens'] = token_usage.get('total_tokens')
                                metrics['prompt_tokens'] = token_usage.get('prompt_tokens')
                                metrics['completion_tokens'] = token_usage.get('completion_tokens')
                        
                        # 获取节点的输出格式
                        output_format = "json"
                        if hasattr(ndata, 'output_format') and ndata.output_format:
                            output_format = ndata.output_format
                        elif hasattr(ndata, 'outputFormat') and ndata.outputFormat:
                            output_format = ndata.outputFormat
                        elif isinstance(ndata, dict):
                            output_format = ndata.get("output_format") or ndata.get("outputFormat") or "json"
                        
                        # 根据输出格式处理输出
                        # 获取输出字段定义
                        output_fields = None
                        if hasattr(ndata, 'output_fields') and ndata.output_fields:
                            output_fields = ndata.output_fields
                        elif hasattr(ndata, 'outputFields') and ndata.outputFields:
                            output_fields = ndata.outputFields
                        elif isinstance(ndata, dict):
                            output_fields = ndata.get("output_fields") or ndata.get("outputFields")
                        
                        logger.debug(f"LLM node {nid} output_format: {output_format}, output_fields: {output_fields}, parsed_response type: {type(parsed_response)}")
                        outputs = format_node_output(parsed_response, output_format, output_fields)
                        logger.debug(f"LLM node {nid} formatted outputs: {outputs}")
                        
                        # 更新节点输出 - 创建新的字典避免修改原状态
                        new_node_outputs = dict(node_outputs)
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态，确保 state_manager 被保留（不返回 workflow_inputs，避免并行执行时的冲突）
                        result_state: WorkflowState = {
                            "node_outputs": new_node_outputs,
                        }
                        
                        # 确保状态管理器被保留在返回的状态中
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs, metrics=metrics, loop_id=loop_id, iteration=iteration)
                        
                        logger.info(f"LLM node {nid} completed successfully, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except Exception as e:
                        logger.error(f"Error executing LLM node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留
                            # 关键修复：在 node_outputs 中包含错误信息，以便循环体执行器能感知到错误
                            error_output = {"error": str(e)}
                            new_node_outputs = dict(state.get("node_outputs", {}))
                            new_node_outputs[nid] = error_output
                            
                            error_state: WorkflowState = {
                                "node_outputs": new_node_outputs,
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e))
                            return error_state
                        raise
                
                return llm_node_func
            
            node_functions[node_id] = make_llm_node(node_id, node_data)
            # 循环体内的节点不添加到主图
            if node_id not in body_node_ids:
                builder.add_node(node_id, node_functions[node_id])
            
        elif node_type == "tool":
            # Tool节点：执行工具
            def make_tool_node(nid: str, ndata: Any):
                async def tool_node_func(state: WorkflowState):
                    # 获取状态管理器（必须在函数开始时获取）
                    state_manager = state.get("state_manager")
                    if not state_manager:
                        logger.warning(f"State manager is None for tool node {nid}, state keys: {list(state.keys())}")
                    
                    try:
                        # 收集上游节点输出
                        node_outputs = state.get("node_outputs", {})
                        incoming_edges = edges_by_target.get(nid, [])
                        
                        # 检查上游节点是否完成（READY 状态检查）
                        if state_manager and incoming_edges:
                            upstream_completed = True
                            for edge in incoming_edges:
                                source_id = edge.source
                                # 检查上游节点是否有输出（表示已完成）
                                if source_id not in node_outputs:
                                    upstream_completed = False
                                    break
                            
                            if upstream_completed:
                                # 上游节点已完成，标记为 READY
                                state_manager.mark_node_ready(nid)
                                logger.info(f"Tool node {nid} is ready (upstream nodes completed)")
                        
                        logger.info(f"Executing tool node {nid}")
                        
                        # 获取原始参数（模板解析前）
                        raw_tool_params = getattr(ndata, 'tool_params', None) or getattr(ndata, 'toolParams', None) or {}
                        
                        # 记录开始状态和输入（在模板解析之前）
                        # 检查是否在循环体内
                        loop_context = state.get("loop_context", {})
                        loop_id = None
                        iteration = None
                        if loop_context:
                            # 获取当前循环的ID和迭代次数（如果有多个循环，使用第一个）
                            for ctx_loop_id, ctx_data in loop_context.items():
                                loop_id = ctx_loop_id
                                iteration = ctx_data.get("iteration", 0)
                                break
                        
                        if state_manager:
                            input_data = {
                                "tool_name": tool_name,
                                "params": raw_tool_params
                            }
                            state_manager.mark_node_running(nid, input_data=input_data, loop_id=loop_id, iteration=iteration)
                        
                        # 构建节点标签映射（用于模板解析）
                        # 注意：n.data 是 WorkflowNodeData 对象，应该使用 node_name 属性
                        node_labels = {}
                        for n in nodes:
                            # 优先使用 node_name（从 WorkflowNodeData），然后是 label，最后是节点 ID
                            node_name = None
                            if hasattr(n.data, 'node_name') and n.data.node_name:
                                node_name = n.data.node_name
                            elif hasattr(n.data, 'nodeName') and n.data.nodeName:
                                node_name = n.data.nodeName
                            elif hasattr(n.data, 'label') and n.data.label:
                                node_name = n.data.label
                            else:
                                node_name = n.id
                            node_labels[n.id] = str(node_name) if node_name is not None else str(n.id)
                        
                        # 获取工具（支持两种字段名格式）
                        tool_name = getattr(ndata, 'tool_name', None) or getattr(ndata, 'toolName', None)
                        if not tool_name:
                            raise ValueError(f"Tool节点 {nid} 未配置工具名称")
                        
                        tool_func = get_tool_by_name(tool_name)
                        if not tool_func:
                            raise ValueError(f"工具 {tool_name} 不存在")
                        
                        # 构建节点输出格式映射（用于模板解析）
                        node_output_formats = {}
                        for n in nodes:
                            n_data = n.data
                            n_format = "output"
                            if hasattr(n_data, 'output_format') and n_data.output_format:
                                n_format = n_data.output_format
                            elif hasattr(n_data, 'outputFormat') and n_data.outputFormat:
                                n_format = n_data.outputFormat
                            elif isinstance(n_data, dict):
                                n_format = n_data.get("output_format") or n_data.get("outputFormat") or "output"
                            node_output_formats[n.id] = n_format
                        
                        # 解析工具参数模板（使用之前获取的 raw_tool_params）
                        loop_context = state.get("loop_context", {})
                        parsed_params = {}
                        if raw_tool_params:
                            for key, value in raw_tool_params.items():
                                if isinstance(value, str):
                                    parsed_params[key] = render_template(value, node_outputs, node_labels, loop_context, node_output_formats)
                                else:
                                    parsed_params[key] = value
                        tool_params = parsed_params
                        
                        # 执行工具（工具可能是函数或可调用对象）
                        if callable(tool_func):
                            if hasattr(tool_func, 'ainvoke'):
                                result = await tool_func.ainvoke(parsed_params)
                            elif hasattr(tool_func, 'invoke'):
                                result = tool_func.invoke(parsed_params)
                            else:
                                # 直接调用函数
                                import inspect
                                if inspect.iscoroutinefunction(tool_func):
                                    result = await tool_func(**parsed_params)
                                else:
                                    result = tool_func(**parsed_params)
                            
                            # 提取工具返回的内容
                            if hasattr(result, 'content'):
                                result = result.content
                            elif isinstance(result, dict) and 'output' in result:
                                result = result['output']
                        else:
                            raise ValueError(f"工具 {tool_name} 不是可调用对象")
                        
                        # 获取节点的输出格式
                        output_format = "json"
                        if hasattr(ndata, 'output_format') and ndata.output_format:
                            output_format = ndata.output_format
                        elif hasattr(ndata, 'outputFormat') and ndata.outputFormat:
                            output_format = ndata.outputFormat
                        elif isinstance(ndata, dict):
                            output_format = ndata.get("output_format") or ndata.get("outputFormat") or "json"
                        
                        # 根据输出格式处理输出
                        # 获取输出字段定义
                        output_fields = None
                        if hasattr(ndata, 'output_fields') and ndata.output_fields:
                            output_fields = ndata.output_fields
                        elif hasattr(ndata, 'outputFields') and ndata.outputFields:
                            output_fields = ndata.outputFields
                        elif isinstance(ndata, dict):
                            output_fields = ndata.get("output_fields") or ndata.get("outputFields")
                        
                        base_outputs = format_node_output(result, output_format, output_fields)
                        # 工具节点还包含 result 字段
                        outputs = {
                            "result": result,
                            **base_outputs,
                        }
                        
                        # 更新节点输出
                        new_node_outputs = dict(node_outputs)
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态（不返回 workflow_inputs，避免并行执行时的冲突）
                        result_state: WorkflowState = {
                            "node_outputs": new_node_outputs,
                        }
                        
                        # 确保状态管理器被保留在返回的状态中
                        # 检查是否在循环体内
                        loop_context = state.get("loop_context", {})
                        loop_id = None
                        iteration = None
                        if loop_context:
                            # 获取当前循环的ID和迭代次数（如果有多个循环，使用第一个）
                            for ctx_loop_id, ctx_data in loop_context.items():
                                loop_id = ctx_loop_id
                                iteration = ctx_data.get("iteration", 0)
                                break
                        
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs, loop_id=loop_id, iteration=iteration)
                        
                        logger.info(f"Tool node {nid} completed successfully, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except Exception as e:
                        logger.error(f"Error executing Tool node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留（不返回 workflow_inputs，避免并行执行时的冲突）
                            error_state: WorkflowState = {
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e))
                            return error_state
                        raise
                
                return tool_node_func
            
            node_functions[node_id] = make_tool_node(node_id, node_data)
            # 循环体内的节点不添加到主图
            if node_id not in body_node_ids:
                builder.add_node(node_id, node_functions[node_id])
            
        elif node_type == "condition":
            # Condition节点：条件分支
            def make_condition_node(nid: str, ndata: Any):
                async def condition_node_func(state: WorkflowState):
                    # 获取状态管理器（必须在函数开始时获取）
                    state_manager = state.get("state_manager")
                    if not state_manager:
                        logger.warning(f"State manager is None for condition node {nid}, state keys: {list(state.keys())}")
                    
                    try:
                        # 收集上游节点输出
                        node_outputs = state.get("node_outputs", {})
                        incoming_edges = edges_by_target.get(nid, [])
                        
                        # 检查上游节点是否完成（READY 状态检查）
                        if state_manager and incoming_edges:
                            upstream_completed = True
                            for edge in incoming_edges:
                                source_id = edge.source
                                # 检查上游节点是否有输出（表示已完成）
                                if source_id not in node_outputs:
                                    upstream_completed = False
                                    break
                            
                            if upstream_completed:
                                # 上游节点已完成，标记为 READY
                                state_manager.mark_node_ready(nid)
                                logger.info(f"Condition node {nid} is ready (upstream nodes completed)")
                        
                        logger.info(f"Executing condition node {nid}")
                        
                        # 获取原始条件表达式（模板解析前）
                        raw_condition_expression = getattr(ndata, 'condition_expression', None) or getattr(ndata, 'conditionExpression', None) or ""
                        
                        # 记录开始状态和输入（在模板解析之前）
                        # 检查是否在循环体内
                        loop_context = state.get("loop_context", {})
                        loop_id = None
                        iteration = None
                        if loop_context:
                            # 获取当前循环的ID和迭代次数（如果有多个循环，使用第一个）
                            for ctx_loop_id, ctx_data in loop_context.items():
                                loop_id = ctx_loop_id
                                iteration = ctx_data.get("iteration", 0)
                                break
                        
                        if state_manager:
                            input_data = {
                                "condition_expression": raw_condition_expression
                            }
                            state_manager.mark_node_running(nid, input_data=input_data, loop_id=loop_id, iteration=iteration)
                        
                        # 构建节点标签映射（用于模板解析）
                        # 注意：n.data 是 WorkflowNodeData 对象，应该使用 node_name 属性
                        node_labels = {}
                        for n in nodes:
                            # 优先使用 node_name（从 WorkflowNodeData），然后是 label，最后是节点 ID
                            node_name = None
                            if hasattr(n.data, 'node_name') and n.data.node_name:
                                node_name = n.data.node_name
                            elif hasattr(n.data, 'nodeName') and n.data.nodeName:
                                node_name = n.data.nodeName
                            elif hasattr(n.data, 'label') and n.data.label:
                                node_name = n.data.label
                            else:
                                node_name = n.id
                            node_labels[n.id] = str(node_name) if node_name is not None else str(n.id)
                        
                        # 构建节点输出格式映射（用于模板解析）
                        node_output_formats = {}
                        for n in nodes:
                            n_data = n.data
                            n_format = "output"
                            if hasattr(n_data, 'output_format') and n_data.output_format:
                                n_format = n_data.output_format
                            elif hasattr(n_data, 'outputFormat') and n_data.outputFormat:
                                n_format = n_data.outputFormat
                            elif isinstance(n_data, dict):
                                n_format = n_data.get("output_format") or n_data.get("outputFormat") or "output"
                            node_output_formats[n.id] = n_format
                        
                        # 解析条件表达式模板
                        loop_context = state.get("loop_context", {})
                        condition_expression = raw_condition_expression
                        if condition_expression:
                            condition_expression = render_template(condition_expression, node_outputs, node_labels, loop_context, node_output_formats)
                        
                        # 评估条件表达式（简单实现，实际应该使用更安全的表达式解析器）
                        # 这里使用eval，但在生产环境中应该使用更安全的方法
                        try:
                            result = eval(expression, {"__builtins__": {}}, node_outputs)
                            condition_result = bool(result)
                        except Exception as e:
                            logger.warning(f"Error evaluating condition expression: {e}")
                            condition_result = False
                        
                        # 获取节点的输出格式
                        output_format = "json"
                        if hasattr(ndata, 'output_format') and ndata.output_format:
                            output_format = ndata.output_format
                        elif hasattr(ndata, 'outputFormat') and ndata.outputFormat:
                            output_format = ndata.outputFormat
                        elif isinstance(ndata, dict):
                            output_format = ndata.get("output_format") or ndata.get("outputFormat") or "json"
                        
                        # 根据输出格式处理输出
                        base_outputs = format_node_output(condition_result, output_format)
                        # 条件节点还包含 result 和 conditionResult 字段
                        outputs = {
                            "result": condition_result,
                            "conditionResult": condition_result,
                            **base_outputs,
                        }
                        
                        # 更新节点输出
                        new_node_outputs = dict(node_outputs)
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态（不返回 workflow_inputs，避免并行执行时的冲突）
                        result_state: WorkflowState = {
                            "node_outputs": new_node_outputs,
                        }
                        
                        # 确保状态管理器被保留在返回的状态中
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs, loop_id=loop_id, iteration=iteration)
                        
                        logger.info(f"Condition node {nid} completed successfully, result: {condition_result}, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except Exception as e:
                        logger.error(f"Error executing Condition node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留（不返回 workflow_inputs，避免并行执行时的冲突）
                            error_state: WorkflowState = {
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e))
                            return error_state
                        raise
                
                return condition_node_func
            
            node_functions[node_id] = make_condition_node(node_id, node_data)
            # 循环体内的节点不添加到主图
            if node_id not in body_node_ids:
                builder.add_node(node_id, node_functions[node_id])
            
        elif node_type == "loop":
            # Loop节点：循环执行（简化实现，完整实现需要支持循环体子图）
            def make_loop_node(nid: str, ndata: Any):
                async def loop_node_func(state: WorkflowState):
                    # 获取状态管理器（必须在函数开始时获取）
                    state_manager = state.get("state_manager")
                    if not state_manager:
                        logger.warning(f"State manager is None for loop node {nid}, state keys: {list(state.keys())}")
                    
                    try:
                        # 收集上游节点输出
                        node_outputs = state.get("node_outputs", {})
                        incoming_edges = edges_by_target.get(nid, [])
                        
                        # 检查上游节点是否完成（READY 状态检查）
                        if state_manager and incoming_edges:
                            upstream_completed = True
                            for edge in incoming_edges:
                                source_id = edge.source
                                # 检查上游节点是否有输出（表示已完成）
                                if source_id not in node_outputs:
                                    upstream_completed = False
                                    break
                            
                            if upstream_completed:
                                # 上游节点已完成，标记为 READY
                                state_manager.mark_node_ready(nid, loop_id=nid)
                                logger.info(f"Loop node {nid} is ready (upstream nodes completed)")
                        
                        logger.info(f"Executing loop node {nid}")
                        
                        if state_manager:
                            state_manager.mark_node_running(nid, loop_id=nid)
                        
                        # 获取循环配置（支持两种字段名格式）
                        loop_count = getattr(ndata, 'loop_count', None) or getattr(ndata, 'loopCount', None)
                        break_conditions = getattr(ndata, 'break_conditions', None) or getattr(ndata, 'breakConditions', None) or []
                        loop_variables = getattr(ndata, 'loop_variables', None) or getattr(ndata, 'loopVariables', None) or []
                        start_node_id = getattr(ndata, 'start_node_id', None) or getattr(ndata, 'startNodeId', None)
                        logical_operator = getattr(ndata, 'logical_operator', None) or getattr(ndata, 'logicalOperator', None) or "and"
                        pending_items_var_name = getattr(ndata, 'pending_items_variable_name', None) or getattr(ndata, 'pendingItemsVariableName', None) or "pending_items"
                        
                        # 初始化循环变量
                        # 注意：需要创建新的字典，避免修改原状态
                        existing_loop_context = state.get("loop_context", {})
                        loop_context = dict(existing_loop_context) if existing_loop_context else {}
                        loop_context[nid] = {
                            "iteration": 0,
                            "variables": {},
                            "filtered_data": {  # 新增：筛选后的数据
                                "passed": [],      # 已通过筛选的数据
                                "pending": []      # 待优化的数据
                            },
                            "filter_config": {    # 新增：筛选配置
                                "source_node": None,      # 数据来源节点（用于筛选）
                                "filter_field": None,      # 筛选字段路径（如 "output.score"）
                                "filter_operator": None,   # 筛选操作符（如 ">="）
                                "filter_value": None       # 筛选值（如 8）
                            }
                        }
                        
                        # 构建循环体子图信息
                        subgraph_info = build_loop_subgraph(nid, nodes, edges, state_manager)
                        
                        if not subgraph_info:
                            # 如果循环体内没有节点，直接返回
                            logger.warning(f"Loop node {nid} has no body nodes, skipping execution")
                            outputs = {
                                "output": {},
                                "iterations": 0,
                            }
                            new_node_outputs = dict(node_outputs)
                            new_node_outputs[nid] = outputs
                            result_state: WorkflowState = {
                                "node_outputs": new_node_outputs,
                            }
                            if state_manager:
                                result_state["state_manager"] = state_manager
                                state_manager.mark_node_success(nid, outputs, loop_id=nid, iteration=0)
                            return result_state
                        
                        loop_body_nodes = subgraph_info["nodes"]
                        loop_body_edges = subgraph_info["edges"]
                        entry_nodes = subgraph_info["entry_nodes"]
                        exit_nodes = subgraph_info["exit_nodes"]
                        body_node_ids = subgraph_info["body_node_ids"]
                        
                        # 初始化循环变量
                        for var in loop_variables:
                            var_label = var.get("label") or var.get("label", "")
                            var_value = var.get("value")
                            var_value_type = var.get("valueType") or var.get("value_type", "constant")
                            
                            if var_value_type == "variable":
                                # 从上游节点获取变量值
                                node_outputs = state.get("node_outputs", {})
                                # 这里简化处理，实际应该解析变量路径
                                loop_context[nid]["variables"][var_label] = var_value
                            else:
                                # 常量值
                                loop_context[nid]["variables"][var_label] = var_value
                        
                        # 执行循环
                        max_iterations = loop_count if loop_count else 100  # 默认最大100次
                        iteration = 0
                        previous_iteration_output = {}
                        
                        # 初始化待优化数据（从循环变量或初始输入获取）
                        # 如果循环变量中有初始数据，将其作为第一轮的待优化数据
                        initial_pending = loop_context[nid].get("filtered_data", {}).get("pending", [])
                        if not initial_pending:
                            # 尝试从上游节点获取初始数据
                            for edge in incoming_edges:
                                source_output = node_outputs.get(edge.source, {})
                                if source_output and "output" in source_output:
                                    output_data = source_output.get("output")
                                    if isinstance(output_data, list):
                                        initial_pending = output_data
                                    elif isinstance(output_data, dict):
                                        initial_pending = [output_data]
                                    break
                        if initial_pending:
                            loop_context[nid]["filtered_data"]["pending"] = initial_pending
                            loop_context[nid]["variables"][pending_items_var_name] = initial_pending
                            logger.info(f"Loop node {nid} initialized with {len(initial_pending)} pending items")
                        
                        while iteration < max_iterations:
                            iteration += 1
                            loop_context[nid]["iteration"] = iteration
                            loop_context[nid]["previous_output"] = previous_iteration_output
                            
                            logger.info(f"Loop node {nid} iteration {iteration}/{max_iterations}")
                            
                            # 执行循环体内的节点（按拓扑顺序）
                            # 构建循环体内的边映射
                            body_edges_by_target: Dict[str, List[WorkflowEdge]] = {}
                            body_edges_by_source: Dict[str, List[WorkflowEdge]] = {}
                            for edge in loop_body_edges:
                                body_edges_by_target.setdefault(edge.target, []).append(edge)
                                body_edges_by_source.setdefault(edge.source, []).append(edge)
                            
                            # 使用拓扑排序并行执行循环体内的节点
                            executed_nodes = set()
                            iteration_outputs = {}
                            # 用于存储循环体内节点每次迭代的详细结果
                            iteration_results: Dict[str, List[Dict[str, Any]]] = {}
                            
                            async def execute_single_node(node_id: str):
                                """执行单个节点（不触发下游节点，用于并行执行）"""
                                if node_id in executed_nodes:
                                    return
                                
                                # 获取节点函数（如果存在）
                                body_node_func = node_functions.get(node_id)
                                
                                if body_node_func:
                                    # 构建循环体执行状态（包含循环上下文和当前迭代的输出）
                                    # 合并外部节点输出和当前迭代输出，外部输出优先（用于访问循环外的节点，如start节点）
                                    merged_node_outputs = dict(node_outputs)  # 先复制外部节点输出
                                    merged_node_outputs.update(iteration_outputs)  # 再更新当前迭代的输出（会覆盖同名的外部输出）
                                    
                                    body_state: WorkflowState = {
                                        "workflow_inputs": state.get("workflow_inputs", {}),
                                        "node_outputs": merged_node_outputs,  # 合并后的节点输出
                                        "loop_context": loop_context,  # 传递循环上下文
                                    }
                                    if state_manager:
                                        body_state["state_manager"] = state_manager
                                    
                                    # 记录节点执行开始时间
                                    import time
                                    start_time = time.time()
                                    
                                    # 提取节点输入（从body_state中获取，用于模板解析前的原始输入）
                                    # 注意：这里获取的是模板解析前的输入，实际输入可能在节点函数内部处理
                                    node_inputs = {}
                                    if body_node_func:
                                        # 尝试从merged_node_outputs中提取该节点的输入
                                        # 实际上，节点的输入是在节点函数内部通过模板解析得到的
                                        # 为了简化，我们从body_state中提取相关信息
                                        node_inputs = {
                                            "workflow_inputs": body_state.get("workflow_inputs", {}),
                                            "node_outputs": merged_node_outputs,
                                            "loop_context": loop_context,
                                        }
                                    
                                    try:
                                        # 增加微小延时，防止CPU空转，并让其他协程有机会运行
                                        await asyncio.sleep(0.01)
                                        # 执行节点函数
                                        logger.debug(f"Starting execution of loop body node {node_id}")
                                        body_result = await body_node_func(body_state)
                                        logger.debug(f"Finished execution of loop body node {node_id}")
                                        
                                        # 记录节点执行结束时间
                                        end_time = time.time()
                                        
                                        # 更新迭代输出
                                        node_output = {}
                                        node_metrics = {}
                                        if body_result and "node_outputs" in body_result:
                                            node_output = body_result["node_outputs"].get(node_id, {})
                                            iteration_outputs[node_id] = node_output
                                        
                                        # 从body_result中提取指标（如果节点函数返回了指标）
                                        if body_result and "metrics" in body_result:
                                            node_metrics = body_result.get("metrics", {})
                                        
                                        # 记录本次迭代的详细结果
                                        if node_id not in iteration_results:
                                            iteration_results[node_id] = []
                                        
                                        iteration_results[node_id].append({
                                            "iteration": iteration,
                                            "output": node_output,
                                            "inputs": node_inputs,
                                            "metrics": node_metrics,
                                            "startTime": start_time,
                                            "endTime": end_time,
                                            "duration": end_time - start_time,
                                        })
                                        
                                        executed_nodes.add(node_id)
                                        logger.debug(f"Executed loop body node {node_id} in iteration {iteration}")
                                    except BaseException as e:  # 捕获所有异常，包括 SystemExit, KeyboardInterrupt, CancelledError
                                        # 记录错误
                                        end_time = time.time()
                                        if node_id not in iteration_results:
                                            iteration_results[node_id] = []
                                        
                                        error_msg = f"Critical error in loop body node {node_id}: {type(e).__name__}: {str(e)}"
                                        logger.error(error_msg, exc_info=True)
                                        
                                        iteration_results[node_id].append({
                                            "iteration": iteration,
                                            "output": {"error": error_msg},
                                            "inputs": node_inputs,
                                            "metrics": {},
                                            "startTime": start_time,
                                            "endTime": end_time,
                                            "duration": end_time - start_time,
                                            "error": error_msg,
                                        })
                                        
                                        executed_nodes.add(node_id)  # 标记为已执行，避免死循环
                                        # 将错误输出添加到迭代输出中
                                        iteration_outputs[node_id] = {"error": error_msg}
                                else:
                                    # 如果没有节点函数，从当前状态获取输出
                                    node_output = node_outputs.get(node_id, {})
                                    iteration_outputs[node_id] = node_output
                                    
                                    # 记录本次迭代的结果（即使没有执行函数）
                                    if node_id not in iteration_results:
                                        iteration_results[node_id] = []
                                    
                                    iteration_results[node_id].append({
                                        "iteration": iteration,
                                        "output": node_output,
                                        "inputs": {},
                                        "metrics": {},
                                        "startTime": None,
                                        "endTime": None,
                                        "duration": None,
                                    })
                                    
                                    executed_nodes.add(node_id)
                                    logger.warning(f"Loop body node {node_id} has no function, using existing output")
                            
                            # 使用拓扑排序找出所有可以并行执行的节点
                            max_attempts = len(loop_body_nodes) * 2  # 最多尝试次数
                            attempt = 0
                            while len(executed_nodes) < len(loop_body_nodes) and attempt < max_attempts:
                                attempt += 1
                                
                                # 找出所有可以执行的节点（上游都已执行）
                                ready_nodes = []
                                for body_node in loop_body_nodes:
                                    if body_node.id in executed_nodes:
                                        continue
                                    
                                    # 检查所有上游节点是否都已执行
                                    incoming = body_edges_by_target.get(body_node.id, [])
                                    can_execute = True
                                    for edge in incoming:
                                        if edge.source not in executed_nodes:
                                            can_execute = False
                                            break
                                    
                                    if can_execute:
                                        ready_nodes.append(body_node.id)
                                
                                # 并行执行所有就绪的节点
                                if ready_nodes:
                                    import asyncio
                                    # 创建并行任务（只执行节点，不触发下游节点）
                                    tasks = [execute_single_node(node_id) for node_id in ready_nodes]
                                    await asyncio.gather(*tasks)
                                    logger.info(f"Parallel executed {len(ready_nodes)} nodes in iteration {iteration}: {ready_nodes}")
                                else:
                                    # 如果没有就绪的节点，尝试从入口节点开始
                                    for entry_node in entry_nodes:
                                        if entry_node.id not in executed_nodes:
                                            await execute_single_node(entry_node.id)
                                    
                                    # 如果仍然没有进展，尝试执行所有未执行的节点
                                    if len(executed_nodes) < len(loop_body_nodes):
                                        for body_node in loop_body_nodes:
                                            if body_node.id not in executed_nodes:
                                                await execute_single_node(body_node.id)
                                    
                                    if len(executed_nodes) < len(loop_body_nodes):
                                        logger.warning(f"Loop body execution stalled at iteration {iteration}, executed {len(executed_nodes)}/{len(loop_body_nodes)} nodes")
                                        break
                            
                            # 更新循环上下文中的节点输出（用于下一次迭代）
                            previous_iteration_output = iteration_outputs
                            
                            # 将本次迭代的结果存储到循环体内节点的输出中
                            # 更新全局node_outputs，为循环体内的节点添加iteration_outputs
                            for body_node_id, results in iteration_results.items():
                                if body_node_id not in node_outputs:
                                    node_outputs[body_node_id] = {}
                                
                                # 确保有iteration_outputs数组
                                if "iteration_outputs" not in node_outputs[body_node_id]:
                                    node_outputs[body_node_id]["iteration_outputs"] = []
                                
                                # 追加本次迭代的结果
                                node_outputs[body_node_id]["iteration_outputs"].extend(results)
                                
                                # 更新最后一次迭代的输出（向后兼容）
                                if results:
                                    last_result = results[-1]
                                    node_outputs[body_node_id]["output"] = last_result.get("output", {})
                            
                            # 检查退出条件
                            should_break = False
                            if break_conditions:
                                # 评估退出条件
                                condition_results = []
                                # 使用当前迭代的输出，而不是全局的node_outputs
                                # iteration_outputs 包含循环体内节点的输出
                                
                                def get_nested_value(data: Dict[str, Any], path: str) -> Any:
                                    """
                                    从嵌套字典中获取值，支持路径如 "LLM6.output.score"
                                    路径格式：节点名.字段名.嵌套字段名...
                                    """
                                    if not path:
                                        return None
                                    
                                    parts = path.split('.')
                                    if len(parts) < 2:
                                        return None
                                    
                                    # 第一部分是节点名（taskName或nodeName）
                                    node_name = parts[0]
                                    field_path = '.'.join(parts[1:])  # 剩余部分是字段路径
                                    
                                    # 查找节点输出
                                    # 首先尝试通过节点名（taskName）查找
                                    node_output = None
                                    for node_id, output in iteration_outputs.items():
                                        # 获取节点的taskName或nodeName
                                        node_data = None
                                        for n in loop_body_nodes:
                                            if n.id == node_id:
                                                node_data = n.data
                                                break
                                        
                                        if node_data:
                                            task_name = getattr(node_data, 'taskName', None) or getattr(node_data, 'nodeName', None) or getattr(node_data, 'node_name', None)
                                            if task_name == node_name:
                                                node_output = output
                                                break
                                    
                                    # 如果没找到，尝试使用节点ID
                                    if node_output is None:
                                        node_output = iteration_outputs.get(node_name)
                                    
                                    if node_output is None or not isinstance(node_output, dict):
                                        return None
                                    
                                    # 解析字段路径
                                    field_parts = field_path.split('.')
                                    if len(field_parts) < 1:
                                        return None
                                    
                                    # 第一个字段通常是 "output"
                                    first_field = field_parts[0]
                                    current = node_output.get(first_field)
                                    
                                    if current is None:
                                        return None
                                    
                                    # 如果 current 是数组，且还有后续字段路径，需要从数组中提取字段值
                                    if isinstance(current, list) and len(field_parts) > 1:
                                        # 数组格式：从每个元素中提取指定字段
                                        nested_field = '.'.join(field_parts[1:])  # 剩余字段路径
                                        result = []
                                        for item in current:
                                            if isinstance(item, dict):
                                                # 递归获取嵌套字段值
                                                item_value = item
                                                for field in nested_field.split('.'):
                                                    if isinstance(item_value, dict):
                                                        item_value = item_value.get(field)
                                                    else:
                                                        item_value = None
                                                        break
                                                result.append(item_value)
                                            else:
                                                result.append(None)
                                        return result if result else None
                                    elif isinstance(current, list):
                                        # 如果只是 "节点名.output"，返回整个数组
                                        return current
                                    elif len(field_parts) > 1:
                                        # 非数组格式：递归获取嵌套字段值
                                        for field in field_parts[1:]:
                                            if isinstance(current, dict):
                                                current = current.get(field)
                                            else:
                                                return None
                                        return current
                                    else:
                                        # 只有一个字段，直接返回
                                        return current
                                
                                for condition in break_conditions:
                                    # BreakCondition 是 Pydantic 模型，使用属性访问
                                    if hasattr(condition, 'output_variable'):
                                        output_variable = condition.output_variable
                                    elif hasattr(condition, 'outputVariable'):
                                        output_variable = condition.outputVariable
                                    elif isinstance(condition, dict):
                                        output_variable = condition.get("outputVariable") or condition.get("output_variable", "")
                                    else:
                                        output_variable = ""
                                    
                                    if hasattr(condition, 'operator'):
                                        operator = condition.operator
                                    elif isinstance(condition, dict):
                                        operator = condition.get("operator", ">=")
                                    else:
                                        operator = ">="
                                    
                                    if hasattr(condition, 'value'):
                                        compare_value = condition.value
                                    elif isinstance(condition, dict):
                                        compare_value = condition.get("value")
                                    else:
                                        compare_value = None
                                    
                                    # 从节点输出中获取变量值（支持嵌套路径）
                                    variable_value = get_nested_value(iteration_outputs, output_variable)
                                    
                                    # 比较操作
                                    condition_met = False
                                    if variable_value is not None:
                                        # 检查是否是数组格式（output 是数组）
                                        # 如果路径是 "节点名.output.字段名"，且 output 是数组，需要检查所有元素
                                        if isinstance(variable_value, list):
                                            # 数组格式：检查数组中所有元素的某个字段是否都满足条件
                                            # 例如：LLM2.output.score，如果 output 是数组，需要检查所有元素的 score 字段
                                            all_met = True
                                            for item in variable_value:
                                                item_met = False
                                                try:
                                                    # 尝试数值比较
                                                    if operator == ">=":
                                                        item_met = float(item) >= float(compare_value)
                                                    elif operator == "<=":
                                                        item_met = float(item) <= float(compare_value)
                                                    elif operator == ">":
                                                        item_met = float(item) > float(compare_value)
                                                    elif operator == "<":
                                                        item_met = float(item) < float(compare_value)
                                                    elif operator == "==":
                                                        item_met = str(item) == str(compare_value)
                                                    elif operator == "!=":
                                                        item_met = str(item) != str(compare_value)
                                                except (ValueError, TypeError):
                                                    # 如果无法转换为数值，使用字符串比较
                                                    if operator == "==":
                                                        item_met = str(item) == str(compare_value)
                                                    elif operator == "!=":
                                                        item_met = str(item) != str(compare_value)
                                                
                                                if not item_met:
                                                    all_met = False
                                                    break
                                            
                                            condition_met = all_met
                                        else:
                                            # 非数组格式：直接比较
                                            try:
                                                # 尝试数值比较
                                                if operator == ">=":
                                                    condition_met = float(variable_value) >= float(compare_value)
                                                elif operator == "<=":
                                                    condition_met = float(variable_value) <= float(compare_value)
                                                elif operator == ">":
                                                    condition_met = float(variable_value) > float(compare_value)
                                                elif operator == "<":
                                                    condition_met = float(variable_value) < float(compare_value)
                                                elif operator == "==":
                                                    condition_met = str(variable_value) == str(compare_value)
                                                elif operator == "!=":
                                                    condition_met = str(variable_value) != str(compare_value)
                                            except (ValueError, TypeError):
                                                # 如果无法转换为数值，使用字符串比较
                                                if operator == "==":
                                                    condition_met = str(variable_value) == str(compare_value)
                                                elif operator == "!=":
                                                    condition_met = str(variable_value) != str(compare_value)
                                    
                                    condition_results.append(condition_met)
                                
                                # 根据逻辑运算符判断
                                if logical_operator == "and":
                                    should_break = all(condition_results) if condition_results else False
                                else:  # "or"
                                    should_break = any(condition_results) if condition_results else False
                            
                            # 在退出条件评估后，进行数据筛选
                            # 从退出条件中提取筛选配置（第一个退出条件作为筛选条件）
                            if break_conditions and not should_break:
                                first_condition = break_conditions[0]
                                # BreakCondition 是 Pydantic 模型，使用属性访问
                                if hasattr(first_condition, 'output_variable'):
                                    filter_field_path = first_condition.output_variable
                                elif hasattr(first_condition, 'outputVariable'):
                                    filter_field_path = first_condition.outputVariable
                                elif isinstance(first_condition, dict):
                                    filter_field_path = first_condition.get("outputVariable") or first_condition.get("output_variable", "")
                                else:
                                    filter_field_path = ""
                                
                                if hasattr(first_condition, 'operator'):
                                    filter_operator = first_condition.operator
                                elif isinstance(first_condition, dict):
                                    filter_operator = first_condition.get("operator", ">=")
                                else:
                                    filter_operator = ">="
                                
                                if hasattr(first_condition, 'value'):
                                    filter_value = first_condition.value
                                elif isinstance(first_condition, dict):
                                    filter_value = first_condition.get("value")
                                else:
                                    filter_value = None
                                
                                # 更新筛选配置
                                loop_context[nid]["filter_config"]["filter_field"] = filter_field_path
                                loop_context[nid]["filter_config"]["filter_operator"] = filter_operator
                                loop_context[nid]["filter_config"]["filter_value"] = filter_value
                                
                                # 查找数据来源节点（循环体内的最后一个节点，或通过配置指定）
                                source_node_id = None
                                source_data = None
                                
                                # 优先查找有output字段的节点
                                for body_node in loop_body_nodes:
                                    node_output = iteration_outputs.get(body_node.id, {})
                                    if node_output and "output" in node_output:
                                        source_data = node_output.get("output")
                                        source_node_id = body_node.id
                                        break
                                
                                # 如果找到了数据，进行筛选
                                if source_data is not None:
                                    # 解析字段路径，例如 "LLM2.output.score"
                                    # 如果路径包含节点名，需要提取字段部分
                                    actual_field_path = filter_field_path
                                    if '.' in filter_field_path:
                                        parts = filter_field_path.split('.')
                                        # 如果第一部分是节点名，跳过它
                                        if len(parts) >= 2:
                                            # 检查第一部分是否是节点名
                                            first_part = parts[0]
                                            is_node_name = False
                                            for body_node in loop_body_nodes:
                                                node_data = body_node.data
                                                task_name = getattr(node_data, 'taskName', None) or getattr(node_data, 'nodeName', None) or getattr(node_data, 'node_name', None)
                                                if task_name == first_part:
                                                    is_node_name = True
                                                    break
                                            
                                            if is_node_name:
                                                # 跳过节点名，使用剩余部分作为字段路径
                                                actual_field_path = '.'.join(parts[1:])
                                    
                                    try:
                                        # 执行筛选
                                        passed_items, pending_items = filter_data_by_condition(
                                            source_data,
                                            actual_field_path,
                                            filter_operator,
                                            filter_value
                                        )
                                        
                                        # 更新筛选后的数据
                                        existing_passed = loop_context[nid]["filtered_data"]["passed"]
                                        loop_context[nid]["filtered_data"]["passed"] = existing_passed + passed_items
                                        loop_context[nid]["filtered_data"]["pending"] = pending_items
                                        
                                        # 将 pending_items 更新到循环变量，供下一轮使用
                                        loop_context[nid]["variables"][pending_items_var_name] = pending_items
                                        
                                        logger.info(f"Loop iteration {iteration}: {len(passed_items)} items passed, {len(pending_items)} items pending")
                                        
                                        # 如果没有待优化数据，可以提前退出
                                        if not pending_items:
                                            logger.info(f"Loop node {nid} all items passed at iteration {iteration}")
                                            should_break = True
                                    except Exception as e:
                                        logger.warning(f"Error filtering data in loop iteration {iteration}: {e}", exc_info=True)
                            
                            if should_break:
                                logger.info(f"Loop node {nid} break condition met at iteration {iteration}")
                                break
                            
                            # 更新循环变量（如果配置了）
                            # 这里可以根据循环体内的节点输出更新循环变量
                            # 简化实现：保持循环变量不变
                        
                        # 收集循环体的最终输出：只包含通过筛选的结果（passed_items）
                        filtered_data = loop_context[nid].get("filtered_data", {})
                        passed_items = filtered_data.get("passed", [])
                        
                        # 循环体节点的输出只包含最终通过筛选的结果
                        outputs = {
                            "output": passed_items,  # 只显示通过筛选的结果
                            "iterations": iteration,
                            "passed_items": passed_items,  # 保留用于兼容
                            "pending_items": filtered_data.get("pending", []),  # 保留用于调试
                        }
                        
                        # 更新节点输出
                        new_node_outputs = dict(state.get("node_outputs", {}))
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态，包含 loop_context（不返回 workflow_inputs，避免并行执行时的冲突）
                        result_state: WorkflowState = {
                            "node_outputs": new_node_outputs,
                        }
                        # 如果有 loop_context，添加到状态中
                        if loop_context:
                            result_state["loop_context"] = loop_context
                        elif "loop_context" in state:
                            result_state["loop_context"] = state["loop_context"]
                        
                        # 确保状态管理器被保留在返回的状态中
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs, loop_id=nid, iteration=iteration)
                        
                        logger.info(f"Loop node {nid} completed successfully after {iteration} iterations, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except BaseException as e:  # 捕获所有异常
                        logger.error(f"Critical error executing Loop node {nid}: {type(e).__name__}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留（不返回 workflow_inputs，避免并行执行时的冲突）
                            error_state: WorkflowState = {
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, f"{type(e).__name__}: {str(e)}", loop_id=nid)
                            return error_state
                        raise
                
                return loop_node_func
            
            node_functions[node_id] = make_loop_node(node_id, node_data)
            builder.add_node(node_id, node_functions[node_id])
    
    # 添加边
    builder.add_edge(START, start_node.id)
    
    # 处理条件节点的边（需要先处理，因为条件节点有多个输出）
    condition_nodes = {n.id for n in nodes if n.type == "condition"}
    
    # 为条件节点添加条件边
    for node_id in condition_nodes:
        # 查找该条件节点的所有出边
        node_edges = [e for e in edges if e.source == node_id]
        if node_edges:
            # 构建条件映射
            condition_map = {}
            for e in node_edges:
                condition_key = e.condition or "true"
                condition_map[condition_key] = e.target
            
            # 如果没有false分支，添加默认的END
            if "false" not in condition_map:
                condition_map["false"] = END
            if "true" not in condition_map:
                condition_map["true"] = END
            
            # 添加条件边
            def make_condition_router(nid: str):
                def condition_router(state: WorkflowState):
                    node_outputs = state.get("node_outputs", {})
                    node_result = node_outputs.get(nid, {})
                    condition_result = node_result.get("result", False)
                    return "true" if condition_result else "false"
                return condition_router
            
            builder.add_conditional_edges(
                node_id,
                make_condition_router(node_id),
                condition_map
            )
    
    # 识别循环节点ID集合
    loop_node_ids = {n.id for n in nodes if n.type == "loop"}
    
    # 添加普通边（非条件节点）
    for edge in edges:
        source_id = edge.source
        target_id = edge.target
        
        # 跳过条件节点的边（已经处理过了）
        if source_id in condition_nodes:
            continue
        
        # 检查源节点和目标节点是否在循环体内
        source_is_body = source_id in body_node_ids
        target_is_body = target_id in body_node_ids
        
        if source_is_body and target_is_body:
            # 两个节点都在循环体内，这条边在循环节点内部处理，不添加到主图
            continue
        elif source_is_body and not target_is_body:
            # 源节点在循环体内，目标节点不在
            # 需要找到源节点所属的循环节点，然后从循环节点连接到目标节点
            source_loop_id = None
            for node in nodes:
                if node.id == source_id:
                    node_data = node.data
                    if hasattr(node_data, 'loopId') and node_data.loopId:
                        source_loop_id = node_data.loopId
                    elif hasattr(node_data, 'loop_id') and node_data.loop_id:
                        source_loop_id = node_data.loop_id
                    elif isinstance(node_data, dict):
                        source_loop_id = node_data.get("loopId") or node_data.get("loop_id")
                    break
            
            if source_loop_id and source_loop_id in loop_node_ids:
                # 从循环节点连接到目标节点
                builder.add_edge(source_loop_id, target_id)
            else:
                logger.warning(f"Edge from body node {source_id} to {target_id} cannot find loop node, skipping")
        elif not source_is_body and target_is_body:
            # 源节点不在循环体内，目标节点在循环体内
            # 需要找到目标节点所属的循环节点，然后从源节点连接到循环节点
            target_loop_id = None
            for node in nodes:
                if node.id == target_id:
                    node_data = node.data
                    if hasattr(node_data, 'loopId') and node_data.loopId:
                        target_loop_id = node_data.loopId
                    elif hasattr(node_data, 'loop_id') and node_data.loop_id:
                        target_loop_id = node_data.loop_id
                    elif isinstance(node_data, dict):
                        target_loop_id = node_data.get("loopId") or node_data.get("loop_id")
                    break
            
            if target_loop_id and target_loop_id in loop_node_ids:
                # 从源节点连接到循环节点
                builder.add_edge(source_id, target_loop_id)
            else:
                logger.warning(f"Edge from {source_id} to body node {target_id} cannot find loop node, skipping")
        else:
            # 两个节点都不在循环体内，正常添加边
            builder.add_edge(source_id, target_id)
    
    # 添加结束边
    builder.add_edge(end_node.id, END)
    
    # 编译图
    graph = builder.compile()
    
    # 添加状态 reducer 以确保 state_manager 在状态更新时被保留
    # 注意：LangGraph 的 StateGraph 默认会合并状态，但对象引用可能会丢失
    # 我们需要确保 state_manager 在每次状态更新时都被保留
    logger.info(f"Workflow graph compiled with {len(node_functions)} nodes")
    
    return graph

