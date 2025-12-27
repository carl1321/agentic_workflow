# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
工作流编译器

将工作流配置编译为LangGraph图结构
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict
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


# 定义工作流状态
# 使用 TypedDict 确保 LangGraph 能正确识别和处理状态结构
class WorkflowState(TypedDict):
    """工作流执行状态"""
    workflow_inputs: Dict[str, Any]
    node_outputs: Dict[str, Any]
    state_manager: NotRequired[Any]  # 状态管理器，使用 NotRequired 因为可能在某些情况下不存在
    loop_context: NotRequired[Dict[str, Any]]  # 循环上下文，用于循环节点
    loop_context: NotRequired[Dict[str, Any]]  # 循环上下文，用于循环节点


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
    
    for node in nodes:
        node_id = node.id
        node_type = node.type
        node_data = node.data
        
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
                    
                    # 开始节点的输出
                    # 支持 startInputInfo 或 start_input_info（输入信息描述）
                    # 实际输入从 workflow_inputs 获取
                    outputs = {
                        "inputs": workflow_inputs,
                        "input": workflow_inputs,  # 默认返回整个输入对象
                    }
                    
                    # 如果有特定的输入字段，也提供
                    if hasattr(ndata, 'start_input_field') and ndata.start_input_field:
                        outputs["input"] = workflow_inputs.get(ndata.start_input_field, workflow_inputs)
                    elif hasattr(ndata, 'startInputField') and ndata.startInputField:
                        outputs["input"] = workflow_inputs.get(ndata.startInputField, workflow_inputs)
                    
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
                    
                    # 构建返回状态
                    result_state: WorkflowState = {
                        "workflow_inputs": state.get("workflow_inputs", {}),
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
                        if state_manager:
                            input_data = {
                                "model": model_name,
                                "prompt": raw_prompt,
                                "system_prompt": raw_system_prompt
                            }
                            state_manager.mark_node_running(nid, input_data=input_data)
                        
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
                        
                        # 解析prompt模板（支持两种字段名格式）
                        prompt = raw_prompt
                        system_prompt = raw_system_prompt
                        if prompt:
                            prompt = render_template(prompt, node_outputs, node_labels)
                        if system_prompt:
                            system_prompt = render_template(system_prompt, node_outputs, node_labels)
                        
                        logger.info(f"Executing LLM node {nid} with model {model_name}")
                        
                        llm = get_llm_by_model_name(model_name)
                        temperature = getattr(ndata, 'llm_temperature', None) or getattr(ndata, 'llmTemperature', None) or 0.7
                        if hasattr(llm, 'temperature'):
                            llm.temperature = temperature
                        
                        # 构建消息
                        from langchain_core.messages import HumanMessage, SystemMessage
                        messages = []
                        if system_prompt:
                            messages.append(SystemMessage(content=system_prompt))
                        messages.append(HumanMessage(content=prompt))
                        
                        # 调用LLM
                        response = await llm.ainvoke(messages)
                        response_content = response.content if hasattr(response, 'content') else str(response)
                        
                        # 获取Token消耗等指标
                        metrics = {}
                        if hasattr(response, 'response_metadata'):
                            token_usage = response.response_metadata.get('token_usage', {})
                            if token_usage:
                                metrics['token_usage'] = token_usage
                                metrics['total_tokens'] = token_usage.get('total_tokens')
                                metrics['prompt_tokens'] = token_usage.get('prompt_tokens')
                                metrics['completion_tokens'] = token_usage.get('completion_tokens')
                        
                        # 输出
                        outputs = {
                            "response": response_content,
                            "content": response_content,
                            "output": response_content,
                        }
                        
                        # 更新节点输出 - 创建新的字典避免修改原状态
                        new_node_outputs = dict(node_outputs)
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态，确保 state_manager 被保留
                        result_state: WorkflowState = {
                            "workflow_inputs": state.get("workflow_inputs", {}),
                            "node_outputs": new_node_outputs,
                        }
                        
                        # 确保状态管理器被保留在返回的状态中
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs, metrics=metrics)
                        
                        logger.info(f"LLM node {nid} completed successfully, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except Exception as e:
                        logger.error(f"Error executing LLM node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留
                            error_state: WorkflowState = {
                                "workflow_inputs": state.get("workflow_inputs", {}),
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e))
                            return error_state
                        raise
                
                return llm_node_func
            
            node_functions[node_id] = make_llm_node(node_id, node_data)
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
                        if state_manager:
                            input_data = {
                                "tool_name": tool_name,
                                "params": raw_tool_params
                            }
                            state_manager.mark_node_running(nid, input_data=input_data)
                        
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
                        
                        # 解析工具参数模板（使用之前获取的 raw_tool_params）
                        parsed_params = {}
                        if raw_tool_params:
                            for key, value in raw_tool_params.items():
                                if isinstance(value, str):
                                    parsed_params[key] = render_template(value, node_outputs, node_labels)
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
                        
                        # 输出
                        outputs = {
                            "result": result,
                            "output": result,
                        }
                        
                        # 更新节点输出
                        new_node_outputs = dict(node_outputs)
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态
                        result_state: WorkflowState = {
                            "workflow_inputs": state.get("workflow_inputs", {}),
                            "node_outputs": new_node_outputs,
                        }
                        
                        # 确保状态管理器被保留在返回的状态中
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs)
                        
                        logger.info(f"Tool node {nid} completed successfully, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except Exception as e:
                        logger.error(f"Error executing Tool node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留
                            error_state: WorkflowState = {
                                "workflow_inputs": state.get("workflow_inputs", {}),
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e))
                            return error_state
                        raise
                
                return tool_node_func
            
            node_functions[node_id] = make_tool_node(node_id, node_data)
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
                        if state_manager:
                            input_data = {
                                "condition_expression": raw_condition_expression
                            }
                            state_manager.mark_node_running(nid, input_data=input_data)
                        
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
                        
                        # 解析条件表达式模板
                        condition_expression = raw_condition_expression
                        if condition_expression:
                            condition_expression = render_template(condition_expression, node_outputs, node_labels)
                        
                        # 评估条件表达式（简单实现，实际应该使用更安全的表达式解析器）
                        # 这里使用eval，但在生产环境中应该使用更安全的方法
                        try:
                            result = eval(expression, {"__builtins__": {}}, node_outputs)
                            condition_result = bool(result)
                        except Exception as e:
                            logger.warning(f"Error evaluating condition expression: {e}")
                            condition_result = False
                        
                        # 输出
                        outputs = {
                            "result": condition_result,
                            "conditionResult": condition_result,
                        }
                        
                        # 更新节点输出
                        new_node_outputs = dict(node_outputs)
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态
                        result_state: WorkflowState = {
                            "workflow_inputs": state.get("workflow_inputs", {}),
                            "node_outputs": new_node_outputs,
                        }
                        
                        # 确保状态管理器被保留在返回的状态中
                        if state_manager:
                            result_state["state_manager"] = state_manager
                            state_manager.mark_node_success(nid, outputs)
                        
                        logger.info(f"Condition node {nid} completed successfully, result: {condition_result}, returning state with keys: {list(result_state.keys())}")
                        return result_state
                    except Exception as e:
                        logger.error(f"Error executing Condition node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留
                            error_state: WorkflowState = {
                                "workflow_inputs": state.get("workflow_inputs", {}),
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e))
                            return error_state
                        raise
                
                return condition_node_func
            
            node_functions[node_id] = make_condition_node(node_id, node_data)
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
                        
                        # 初始化循环变量
                        # 注意：需要创建新的字典，避免修改原状态
                        existing_loop_context = state.get("loop_context", {})
                        loop_context = dict(existing_loop_context) if existing_loop_context else {}
                        loop_context[nid] = {
                            "iteration": 0,
                            "variables": {},
                        }
                        
                        # 查找循环体内的节点（通过loop_id标记）
                        loop_body_nodes = [n for n in nodes if n.data.get("loopId") == nid or n.data.get("loop_id") == nid]
                        
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
                        
                        # 执行循环（简化实现，实际应该构建循环子图）
                        max_iterations = loop_count if loop_count else 100  # 默认最大100次
                        iteration = 0
                        
                        while iteration < max_iterations:
                            iteration += 1
                            loop_context[nid]["iteration"] = iteration
                            
                            # 执行循环体内的节点（这里简化处理，实际应该按顺序执行）
                            # 注意：完整的循环体执行需要构建子图，这里只是占位
                            # 在实际使用中，循环体内的节点应该通过边连接到循环节点
                            # 循环节点会通过递归调用或子图执行来处理循环体
                            
                            # 检查退出条件
                            should_break = False
                            if break_conditions:
                                # 评估退出条件
                                condition_results = []
                                node_outputs = state.get("node_outputs", {})
                                
                                for condition in break_conditions:
                                    output_variable = condition.get("outputVariable") or condition.get("output_variable", "")
                                    operator = condition.get("operator", ">=")
                                    compare_value = condition.get("value")
                                    
                                    # 从节点输出中获取变量值
                                    # 这里简化处理，实际应该支持更复杂的路径解析
                                    variable_value = None
                                    for node_output in node_outputs.values():
                                        if isinstance(node_output, dict):
                                            if output_variable in node_output:
                                                variable_value = node_output[output_variable]
                                                break
                                    
                                    # 比较操作
                                    condition_met = False
                                    if variable_value is not None:
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
                            
                            if should_break:
                                break
                        
                        # 输出
                        outputs = {
                            "output": loop_context[nid],
                            "iterations": iteration,
                        }
                        
                        # 更新节点输出
                        new_node_outputs = dict(state.get("node_outputs", {}))
                        new_node_outputs[nid] = outputs
                        
                        # 构建返回状态，包含 loop_context
                        result_state: WorkflowState = {
                            "workflow_inputs": state.get("workflow_inputs", {}),
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
                    except Exception as e:
                        logger.error(f"Error executing Loop node {nid}: {e}", exc_info=True)
                        if state_manager:
                            # 构建错误状态，确保 state_manager 被保留
                            error_state: WorkflowState = {
                                "workflow_inputs": state.get("workflow_inputs", {}),
                                "node_outputs": state.get("node_outputs", {}),
                                "state_manager": state_manager,
                            }
                            state_manager.mark_node_error(nid, str(e), loop_id=nid)
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
    
    # 添加普通边（非条件节点）
    for edge in edges:
        source_id = edge.source
        target_id = edge.target
        
        if source_id not in condition_nodes:
            # 普通边
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

