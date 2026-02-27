# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
VASP 专用 Agent 图：单节点 ReAct 循环，仅绑定 vaspilot_* 工具。
从 TOOL_REGISTRY 按名筛出工具后传入 build_vasp_graph(tools)，不直接依赖 app。
"""

import asyncio
import logging
from typing import Any, List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.llms.llm import get_llm_by_type

logger = logging.getLogger(__name__)

VASPILOT_TOOL_PREFIX = "vaspilot_"

VASP_SYSTEM_PROMPT = """你是 VASP 工作流助手，根据用户目标自动选择并执行 vaspilot 工具，直至任务完成或明确失败。

可用工具及典型顺序：
1. 结构：vaspilot_create_structure（创建）、vaspilot_load_structure（上传/加载 POSCAR）
2. 分析：vaspilot_analyze_structure（分析结构）
3. 输入：vaspilot_generate_inputs（生成 INCAR/KPOINTS 等）
4. 集群：vaspilot_get_hpc_config（获取 HPC 配置）、vaspilot_submit_to_hpc（提交作业）
5. 监控：vaspilot_job_status、vaspilot_fetch_job_logs
6. 结果：vaspilot_download_remote_file（下载结果）、vaspilot_plot_band_structure（能带绘图）

用户可能在消息中附带文件内容，格式为 [附件: 文件名] 后跟 ``` 代码块。若用户要求用某结构（如 POSCAR）做能带/弛豫等，请从该附件中提取内容，并优先调用 vaspilot_load_structure(file_content=提取的文本, filename=文件名)。

调用 vaspilot_submit_to_hpc 时**必须**传入 host、username、remote_work_dir（以及 key_path 或 password 之一）。请先调用 vaspilot_get_hpc_config 获取配置，再在 submit_to_hpc 中传入：host、username、remote_work_dir、port、key_path 或 password，以及 files。

请根据用户目标自主选择工具并循环调用直到任务完成。若 HPC 未配置、作业失败或需要用户上传 POSCAR，请明确说明并给出下一步建议。"""


def get_vasp_tools_from_registry(registry: dict) -> List[Any]:
    """
    从工具注册表中筛出所有 vaspilot_* 工具，保持与 skill 注册一致。
    :param registry: tool_name -> tool 字典（如 TOOL_REGISTRY）
    :return: 工具列表，用于 bind_tools
    """
    tools = [t for name, t in registry.items() if name.startswith(VASPILOT_TOOL_PREFIX)]
    # 保持稳定顺序（按注册表键排序）
    tools.sort(key=lambda t: getattr(t, "name", str(t)))
    logger.info("VASP agent: resolved %d tools from registry (vaspilot_*)", len(tools))
    return tools


async def _execute_tool_async(tool: Any, args: dict) -> str:
    """执行单个工具（支持 async/sync），与 app.py 的 /api/tools/execute 语义一致。"""
    try:
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(args)
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: tool.invoke(args))
        return str(result) if result is not None else ""
    except Exception as e:
        logger.exception("VASP tool execution failed: %s", e)
        return f"Error: {e!s}"


async def _vasp_agent_node(state: MessagesState, tools: List[Any], name_to_tool: dict):
    """
    单节点逻辑：用当前 messages 调用 LLM(bind_tools)；若有 tool_calls 则执行并追加 ToolMessage 再循环。
    节点为 async，工具执行使用 ainvoke/run_in_executor，与 astream 兼容。
    """
    messages = state["messages"]
    system = SystemMessage(content=VASP_SYSTEM_PROMPT)
    invoke_messages: List[BaseMessage] = [system] + list(messages)

    llm = get_llm_by_type("basic")
    llm_with_tools = llm.bind_tools(tools)
    response = await llm_with_tools.ainvoke(invoke_messages)
    # 与主图一致：AI 消息带 name 便于前端显示 agent
    out_ai = AIMessage(
        content=response.content,
        tool_calls=getattr(response, "tool_calls", None),
        name="vasp_agent",
        response_metadata=getattr(response, "response_metadata", {}),
        additional_kwargs=getattr(response, "additional_kwargs", {}),
    )

    if not response.tool_calls:
        return {"messages": [out_ai]}

    tool_messages: List[ToolMessage] = []
    for tc in response.tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
        if args is None:
            args = {}
        if isinstance(args, str):
            try:
                import json
                args = json.loads(args)
            except Exception:
                args = {}
        tool = name_to_tool.get(name) if name else None
        if not tool:
            content = f"Tool not found: {name}"
        else:
            content = await _execute_tool_async(tool, args)
        tool_messages.append(
            ToolMessage(content=content, tool_call_id=tc_id or "")
        )
    return {"messages": [out_ai] + tool_messages}


def _make_vasp_agent_node(tools: List[Any]):
    name_to_tool = {getattr(t, "name", str(t)): t for t in tools}

    async def node(state: MessagesState):
        return await _vasp_agent_node(state, tools, name_to_tool)

    return node


def _should_continue(state: MessagesState) -> str:
    """若最后一条为 ToolMessage（刚执行完工具）则继续进 agent；否则结束。"""
    messages = state["messages"]
    if not messages:
        return "end"
    last = messages[-1]
    # 刚追加了工具结果，需再跑一轮 agent
    if isinstance(last, ToolMessage):
        return "continue"
    # AI 无 tool_calls 或未产生工具调用，结束
    return "end"


def build_vasp_graph(tools: List[Any]):
    """
    构建 VASP 专用单节点 ReAct 图。
    :param tools: vaspilot 工具列表（通常来自 get_vasp_tools_from_registry(TOOL_REGISTRY)）
    :return: 编译后的 CompiledGraph
    """
    if not tools:
        raise ValueError("VASP graph requires at least one vaspilot tool.")

    builder = StateGraph(MessagesState)
    node = _make_vasp_agent_node(tools)
    builder.add_node("vasp_agent", node)
    builder.add_edge(START, "vasp_agent")
    builder.add_conditional_edges("vasp_agent", _should_continue, {"continue": "vasp_agent", "end": END})

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)
