# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import contextvars
import dataclasses
import json
import logging
import os
import time
from functools import partial
from typing import Annotated, Any, Literal
from urllib.parse import quote

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.types import Command, interrupt

from src.agents import create_agent
from src.config.agents import AGENT_LLM_MAP
from src.config.configuration import Configuration
from src.llms.llm import get_llm_by_type, get_llm_token_limit_by_type, get_llm_by_model_name, get_model_supports_thinking
from src.prompts.planner_model import Plan
from src.prompts.template import apply_prompt_template
from src.tools import (
    crawl_tool,
    generate_sam_molecules,
    get_retriever_tool,
    get_web_search_tool,
    predict_molecular_properties,
    python_repl_tool,
    visualize_molecules,
    search_literature,
    fetch_pdf_text,
)
from src.tools.literature_search import get_literature_research_tools, get_arxiv_search_tool
from src.tools.search import LoggedTavilySearch
from src.utils.context_manager import ContextManager
from src.utils.json_utils import repair_json_output

from ..config import SELECTED_SEARCH_ENGINE, SearchEngine
from .deep_research_engine import IterativeResearchEngine
from .types import State

logger = logging.getLogger(__name__)

# Context var for injecting HPC config into vaspilot tools when executor runs (avoids LLM omitting args)
_VASP_HPC_CONFIG_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("vasp_hpc_config", default=None)
# 同一执行步内「submit_to_hpc 因缺 files 失败」次数，超过上限后返回终止说明，避免无限重试
_VASP_SUBMIT_FILES_ERROR_CTX: contextvars.ContextVar[int] = contextvars.ContextVar("vasp_submit_files_error_count", default=0)
_SUBMIT_FILES_ERROR_LIMIT = 2
# 从已完成步骤（生成输入）解析出的 files 字典，供 submit_to_hpc 在 LLM 未传时自动注入
_VASP_SUBMIT_FILES_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("vasp_submit_files", default=None)
# 第 3 步下载的 vasprun/kpoints 内容，供第 4 步 vaspilot_plot_band_structure 自动注入（避免大内容进 prompt）
_VASP_BAND_CONTENT_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("vasp_band_content", default=None)


def _get_hpc_config_for_wrapper() -> dict:
    """Get HPC config: first from context (previous steps), else by calling vaspilot_get_hpc_config."""
    hpc = _VASP_HPC_CONFIG_CTX.get()
    if hpc and (hpc.get("host") or hpc.get("username")):
        return hpc
    try:
        from src.server.app import TOOL_REGISTRY
        get_cfg = TOOL_REGISTRY.get("vaspilot_get_hpc_config")
        if get_cfg and callable(getattr(get_cfg, "invoke", None)):
            out = get_cfg.invoke({})
            if isinstance(out, str):
                raw = json.loads(out)
            else:
                raw = out
            if isinstance(raw, dict) and (raw.get("host") or raw.get("username")):
                hpc = {
                    "host": (raw.get("host") or "").strip(),
                    "username": (raw.get("username") or "").strip(),
                    "remote_work_dir": (raw.get("work_dir") or raw.get("remote_work_dir") or "").strip(),
                    "port": int(raw.get("port", 22)) if raw.get("port") else 22,
                    "key_path": (raw.get("key_path") or "").strip() or None,
                }
                try:
                    _VASP_HPC_CONFIG_CTX.set(hpc)
                except Exception:
                    pass
                return hpc
    except Exception as e:
        logger.debug("vasp wrapper: get_hpc_config fallback failed: %s", e)
    return {}


def _merge_hpc_into_args(name: str, args: dict, hpc: dict) -> dict:
    """Merge hpc into args for host/username/port/key_path/remote_work_dir/password."""
    if not hpc or not isinstance(args, dict):
        return args
    args = dict(args)
    if not args.get("host") and hpc.get("host"):
        args["host"] = hpc["host"]
    if not args.get("username") and hpc.get("username"):
        args["username"] = hpc["username"]
    if not args.get("port") and hpc.get("port"):
        args["port"] = hpc["port"]
    if not args.get("key_path") and hpc.get("key_path"):
        args["key_path"] = hpc["key_path"]
    if name == "vaspilot_submit_to_hpc":
        if not args.get("remote_work_dir") and hpc.get("remote_work_dir"):
            args["remote_work_dir"] = hpc["remote_work_dir"]
        if not args.get("key_path") and not args.get("password"):
            args["password"] = "__use_config__"
    elif name in ("vaspilot_job_status", "vaspilot_fetch_job_logs", "vaspilot_download_remote_file"):
        if not args.get("key_path") and not args.get("password"):
            args["password"] = "__use_config__"
    return args


def _wrap_vasp_tool_with_hpc_fill(t: Any, cached_files: dict | None = None) -> Any:
    """Wrap a vaspilot tool so missing host/username/remote_work_dir/key_path/files are filled from cache or context."""
    name = getattr(t, "name", "") or ""
    if name not in (
        "vaspilot_submit_to_hpc",
        "vaspilot_job_status",
        "vaspilot_fetch_job_logs",
        "vaspilot_download_remote_file",
    ):
        return t
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        return t

    def _check_submit_files(args: dict) -> str | None:
        """If submit_to_hpc is missing valid 'files', return error message for agent; else None."""
        if name != "vaspilot_submit_to_hpc":
            return None
        files = args.get("files") if isinstance(args, dict) else None
        if not files or not isinstance(files, dict):
            err = (
                "Error: 缺少必填参数 files。请从 **Completed Step 2**（生成输入）的 <finding> 中解析出 **files** 字段"
                "（即 generate_inputs 返回的 JSON 里的 files 对象，包含 submit.sh、POSCAR、INCAR_*、KPOINTS_*、gen_potcar.sh 等），"
                "将整个 files 字典作为 vaspilot_submit_to_hpc 的 files 参数传入，不可省略或传空。"
            )
        elif "submit.sh" not in files:
            err = (
                "Error: files 中必须包含 submit.sh。请使用 Completed Step 2 的 finding 里 **files** 对象的完整内容，不要删减。"
            )
        else:
            return None
        # 同一轮内缺 files 失败次数上限，超过后返回终止说明，避免无限重试
        try:
            count = _VASP_SUBMIT_FILES_ERROR_CTX.get() or 0
        except LookupError:
            count = 0
        if count >= _SUBMIT_FILES_ERROR_LIMIT:
            return (
                "请勿继续重试。请检查 Completed Step 2 的 files，并确保将完整的 files 对象作为 vaspilot_submit_to_hpc 的 files 参数传入。"
                "本步不再接受重复的空参数调用。"
            )
        try:
            _VASP_SUBMIT_FILES_ERROR_CTX.set(count + 1)
        except Exception:
            pass
        return err

    def _fill_submit_files_from_ctx(args: dict) -> dict:
        """If submit_to_hpc and args missing valid files, fill from cached_files (closure) or _VASP_SUBMIT_FILES_CTX."""
        if name != "vaspilot_submit_to_hpc" or not isinstance(args, dict):
            return args
        files = args.get("files")
        if isinstance(files, dict) and files.get("submit.sh"):
            return args
        fill_from = cached_files
        if not (isinstance(fill_from, dict) and fill_from.get("submit.sh")):
            try:
                fill_from = _VASP_SUBMIT_FILES_CTX.get()
            except LookupError:
                fill_from = None
        if isinstance(fill_from, dict) and fill_from.get("submit.sh"):
            args = dict(args)
            args["files"] = fill_from
            logger.info("VASP: submit_to_hpc filled files from cache/context, keys=%s", list(fill_from.keys()))
        return args

    async def _acall(*positional: Any, **kwargs: Any):
        # LangChain may call coroutine(**tool_input); accept both single dict and **kwargs
        if positional and len(positional) == 1 and isinstance(positional[0], dict) and not kwargs:
            args = dict(positional[0])
        else:
            args = dict(kwargs) if kwargs else (dict(positional[0]) if positional and isinstance(positional[0], dict) else {})
        need_hpc = isinstance(args, dict) and (not args.get("host") or not args.get("username"))
        if need_hpc:
            hpc = _get_hpc_config_for_wrapper()
            args = _merge_hpc_into_args(name, args, hpc)
        args = _fill_submit_files_from_ctx(args)
        err = _check_submit_files(args)
        if err is not None:
            return err
        if hasattr(t, "ainvoke"):
            return await t.ainvoke(args)
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, lambda: t.invoke(args))

    def _sync_call(*positional: Any, **kwargs: Any):
        if positional and len(positional) == 1 and isinstance(positional[0], dict) and not kwargs:
            args = dict(positional[0])
        else:
            args = dict(kwargs) if kwargs else (dict(positional[0]) if positional and isinstance(positional[0], dict) else {})
        need_hpc = isinstance(args, dict) and (not args.get("host") or not args.get("username"))
        if need_hpc:
            hpc = _get_hpc_config_for_wrapper()
            args = _merge_hpc_into_args(name, args, hpc)
        args = _fill_submit_files_from_ctx(args)
        err = _check_submit_files(args)
        if err is not None:
            return err
        return t.invoke(args)

    return StructuredTool(
        name=t.name,
        description=t.description,
        args_schema=getattr(t, "args_schema", None),
        func=_sync_call,
        coroutine=_acall,
    )


def _wrap_vasp_plot_band_from_ctx(t: Any) -> Any:
    """若为 vaspilot_plot_band_structure，则从 _VASP_BAND_CONTENT_CTX 注入 vasprun_xml_content/kpoints_content（避免第 4 步 LLM 未传大内容）。"""
    name = getattr(t, "name", "") or ""
    if name != "vaspilot_plot_band_structure":
        return t
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        return t

    def _merge_band_content(args: dict) -> dict:
        try:
            band = _VASP_BAND_CONTENT_CTX.get()
        except LookupError:
            band = None
        if not band or not isinstance(args, dict):
            return args
        args = dict(args)
        if (not (args.get("vasprun_xml_content") or "").strip() and band.get("vasprun_xml_content")):
            args["vasprun_xml_content"] = band["vasprun_xml_content"]
            logger.info("VASP: plot_band_structure filled vasprun_xml_content from state (len=%s)", len(band.get("vasprun_xml_content", "")))
        if band.get("kpoints_content") is not None and (args.get("kpoints_content") is None or (isinstance(args.get("kpoints_content"), str) and not args.get("kpoints_content").strip())):
            args["kpoints_content"] = band["kpoints_content"]
        return args

    async def _acall(*positional: Any, **kwargs: Any):
        if positional and len(positional) == 1 and isinstance(positional[0], dict) and not kwargs:
            args = _merge_band_content(dict(positional[0]))
        else:
            args = _merge_band_content(dict(kwargs) if kwargs else (dict(positional[0]) if positional and isinstance(positional[0], dict) else {}))
        if hasattr(t, "ainvoke"):
            return await t.ainvoke(args)
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, lambda: t.invoke(args))

    def _sync_call(*positional: Any, **kwargs: Any):
        if positional and len(positional) == 1 and isinstance(positional[0], dict) and not kwargs:
            args = _merge_band_content(dict(positional[0]))
        else:
            args = _merge_band_content(dict(kwargs) if kwargs else (dict(positional[0]) if positional and isinstance(positional[0], dict) else {}))
        return t.invoke(args)

    return StructuredTool(
        name=t.name,
        description=t.description,
        args_schema=getattr(t, "args_schema", None),
        func=_sync_call,
        coroutine=_acall,
    )


@tool
def handoff_to_planner(
    research_topic: Annotated[str, "The topic of the research task to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to planner agent to do plan."""
    # This tool is not returning anything: we're just using it
    # as a way for LLM to signal that it needs to hand off to planner agent
    return


@tool
def handoff_to_molecular_planner(
    research_topic: Annotated[str, "The molecular design task to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to molecular planner agent for molecular design and generation tasks."""
    # This tool is not returning anything: we're just using it
    # as a way for LLM to signal that it needs to hand off to molecular planner agent
    return


@tool
def handoff_to_vasp(
    research_topic: Annotated[str, "The VASP calculation task (e.g. structure relaxation, band, DOS, submit to HPC)."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to VASP agent for VASP/DFT calculation workflows: structure, inputs, HPC submit, results, band plot."""
    return


@tool
def handoff_to_literature_planner(
    research_topic: Annotated[str, "The literature-focused materials question to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to literature planner agent for materials/scientific literature Q&A tasks."""
    return


@tool
def handoff_after_clarification(
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to planner after clarification rounds are complete. Pass all clarification history to planner for analysis."""
    return


def _get_llm_for_agent(agent_type: str, config: RunnableConfig = None) -> Any:
    """
    Get LLM instance for an agent.
    
    Only planner agents (planner, molecular_planner, literature_planner) can use selected_model.
    All other agents always use BASIC_MODEL.
    
    Args:
        agent_type: The agent type (e.g., "planner", "reporter")
        config: Optional RunnableConfig containing selected_model
    
    Returns:
        LLM instance
    """
    # Planner agents can use selected_model, others always use BASIC_MODEL
    planner_agents = ["planner", "molecular_planner", "literature_planner"]
    
    if agent_type in planner_agents:
        # Planner agents: use selected_model if available, otherwise use AGENT_LLM_MAP
        selected_model = None
        if config:
            configurable = Configuration.from_runnable_config(config)
            selected_model = configurable.selected_model if configurable else None
        
        if selected_model:
            try:
                return get_llm_by_model_name(selected_model)
            except ValueError:
                # Fall back to default if model not found
                return get_llm_by_type(AGENT_LLM_MAP[agent_type])
        else:
            return get_llm_by_type(AGENT_LLM_MAP[agent_type])
    else:
        # All other agents: always use BASIC_MODEL (ignores selected_model)
        return get_llm_by_type("basic")


def needs_clarification(state: dict) -> bool:
    """
    Check if clarification is needed based on current state.
    Centralized logic for determining when to continue clarification.
    """
    if not state.get("enable_clarification", False):
        return False

    clarification_rounds = state.get("clarification_rounds", 0)
    is_clarification_complete = state.get("is_clarification_complete", False)
    max_clarification_rounds = state.get("max_clarification_rounds", 3)

    # Need clarification if: enabled + has rounds + not complete + not exceeded max
    # Use <= because after asking the Nth question, we still need to wait for the Nth answer
    return (
        clarification_rounds > 0
        and not is_clarification_complete
        and clarification_rounds <= max_clarification_rounds
    )


def background_investigation_node(state: State, config: RunnableConfig):
    logger.info("background investigation node is running.")
    configurable = Configuration.from_runnable_config(config)
    query = state.get("research_topic")
    background_investigation_results = None
    if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
        searched_content = LoggedTavilySearch(
            max_results=configurable.max_search_results
        ).invoke(query)
        # check if the searched_content is a tuple, then we need to unpack it
        if isinstance(searched_content, tuple):
            searched_content = searched_content[0]
        if isinstance(searched_content, list):
            background_investigation_results = [
                f"## {elem['title']}\n\n{elem['content']}" for elem in searched_content
            ]
            return {
                "background_investigation_results": "\n\n".join(
                    background_investigation_results
                )
            }
        else:
            logger.error(
                f"Tavily search returned malformed response: {searched_content}"
            )
    else:
        background_investigation_results = get_web_search_tool(
            configurable.max_search_results
        ).invoke(query)
    return {
        "background_investigation_results": json.dumps(
            background_investigation_results, ensure_ascii=False
        )
    }


def planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["human_feedback", "reporter"]]:
    """Planner node that generate the full plan."""
    logger.info("Planner generating full plan")
    configurable = Configuration.from_runnable_config(config)
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0

    # For clarification feature: only send the final clarified question to planner
    if state.get("enable_clarification", False) and state.get("clarified_question"):
        # Create a clean state with only the clarified question
        clean_state = {
            "messages": [{"role": "user", "content": state["clarified_question"]}],
            "locale": state.get("locale", "en-US"),
            "research_topic": state["clarified_question"],
        }
        messages = apply_prompt_template("planner", clean_state, configurable)
        logger.info(
            f"Clarification mode: Using clarified question: {state['clarified_question']}"
        )
    else:
        # Normal mode: use full conversation history
        messages = apply_prompt_template("planner", state, configurable)

    if state.get("enable_background_investigation") and state.get(
        "background_investigation_results"
    ):
        messages += [
            {
                "role": "user",
                "content": (
                    "background investigation results of user query:\n"
                    + state["background_investigation_results"]
                    + "\n"
                ),
            }
        ]

    # LLM selection priority:
    # 1. If selected_model exists, use it (user's choice takes priority)
    # 2. If no selected_model but enable_deep_thinking, use REASONING_MODEL (backward compatibility)
    # 3. Otherwise use default AGENT_LLM_MAP
    if configurable.selected_model:
        llm = _get_llm_for_agent("planner", config)
        # Check if model supports thinking - if so, don't use structured output
        supports_thinking = get_model_supports_thinking(configurable.selected_model)
        if AGENT_LLM_MAP["planner"] == "basic" and not supports_thinking:
            llm = llm.with_structured_output(Plan, method="json_mode")
    elif configurable.enable_deep_thinking:
        # Backward compatibility: use REASONING_MODEL when deep thinking is enabled but no model is selected
        llm = get_llm_by_type("reasoning")
    elif AGENT_LLM_MAP["planner"] == "basic":
        llm = get_llm_by_type("basic").with_structured_output(
            Plan,
            method="json_mode",
        )
    else:
        llm = _get_llm_for_agent("planner", config)

    # if the plan iterations is greater than the max plan iterations, return the reporter node
    if plan_iterations >= configurable.max_plan_iterations:
        return Command(goto="reporter")

    full_response = ""
    # Check if using structured output
    # - Use structured output when: selected_model exists, AGENT_LLM_MAP is "basic", and model doesn't support thinking
    # - Or when: no selected_model, AGENT_LLM_MAP is "basic", and deep thinking is not enabled
    supports_thinking = False
    if configurable.selected_model:
        supports_thinking = get_model_supports_thinking(configurable.selected_model)
    
    using_structured_output = (
        (configurable.selected_model and AGENT_LLM_MAP["planner"] == "basic" and not supports_thinking) or
        (not configurable.selected_model and AGENT_LLM_MAP["planner"] == "basic" and not configurable.enable_deep_thinking)
    )
    
    if using_structured_output:
        # When using structured output, use invoke to get Plan object directly
        response = llm.invoke(messages)
        full_response = response.model_dump_json(indent=4, exclude_none=True)
    else:
        # For streaming responses, chunks are AIMessageChunk with content attribute
        response = llm.stream(messages)
        for chunk in response:
            full_response += chunk.content
    logger.debug(f"Current state messages: {state['messages']}")
    logger.info(f"Planner response: {full_response}")

    try:
        curr_plan = json.loads(repair_json_output(full_response))
    except json.JSONDecodeError:
        logger.warning("Planner response is not a valid JSON")
        if plan_iterations > 0:
            return Command(goto="reporter")
        else:
            return Command(goto="__end__")
    if isinstance(curr_plan, dict) and curr_plan.get("has_enough_context"):
        logger.info("Planner response has enough context.")
        new_plan = Plan.model_validate(curr_plan)
        return Command(
            update={
                "messages": [AIMessage(content=full_response, name="planner")],
                "current_plan": new_plan,
            },
            goto="reporter",
        )
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="planner")],
            "current_plan": full_response,
        },
        goto="human_feedback",
    )


def molecular_planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["human_feedback", "common_reporter", "reporter", "__end__"]]:
    """Molecular planner node for molecule generation tasks."""
    logger.info("Molecular planner generating molecule design plan")
    configurable = Configuration.from_runnable_config(config)
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0

    # For clarification feature: only send the final clarified question to planner
    if state.get("enable_clarification", False) and state.get("clarified_question"):
        # Create a clean state with only the clarified question
        clean_state = {
            "messages": [{"role": "user", "content": state["clarified_question"]}],
            "locale": state.get("locale", "en-US"),
            "research_topic": state["clarified_question"],
        }
        messages = apply_prompt_template("molecular_planner", clean_state, configurable)
        logger.info(
            f"Clarification mode: Using clarified question: {state['clarified_question']}"
        )
    else:
        # Normal mode: use full conversation history
        messages = apply_prompt_template("molecular_planner", state, configurable)

    # Use same LLM selection logic as planner_node
    # LLM selection priority:
    # 1. If selected_model exists, use it (user's choice takes priority)
    # 2. If no selected_model but enable_deep_thinking, use REASONING_MODEL (backward compatibility)
    # 3. Otherwise use default AGENT_LLM_MAP
    if configurable.selected_model:
        llm = _get_llm_for_agent("molecular_planner", config)
        # Check if model supports thinking - if so, don't use structured output
        supports_thinking = get_model_supports_thinking(configurable.selected_model)
        if AGENT_LLM_MAP["molecular_planner"] == "basic" and not supports_thinking:
            llm = llm.with_structured_output(Plan, method="json_mode")
    elif configurable.enable_deep_thinking:
        # Backward compatibility: use REASONING_MODEL when deep thinking is enabled but no model is selected
        llm = get_llm_by_type("reasoning")
    elif AGENT_LLM_MAP["molecular_planner"] == "basic":
        llm = get_llm_by_type("basic").with_structured_output(
            Plan,
            method="json_mode",
        )
    else:
        llm = _get_llm_for_agent("molecular_planner", config)

    # if the plan iterations is greater than the max plan iterations, return the reporter node
    if plan_iterations >= configurable.max_plan_iterations:
        return Command(goto="reporter")

    # Use same invoke/stream logic as planner_node
    full_response = ""
    # Check if using structured output
    # - Use structured output when: selected_model exists, AGENT_LLM_MAP is "basic", and model doesn't support thinking
    # - Or when: no selected_model, AGENT_LLM_MAP is "basic", and deep thinking is not enabled
    supports_thinking = False
    if configurable.selected_model:
        supports_thinking = get_model_supports_thinking(configurable.selected_model)
    
    using_structured_output = (
        (configurable.selected_model and AGENT_LLM_MAP["molecular_planner"] == "basic" and not supports_thinking) or
        (not configurable.selected_model and AGENT_LLM_MAP["molecular_planner"] == "basic" and not configurable.enable_deep_thinking)
    )
    
    if using_structured_output:
        # When using structured output, use invoke to get Plan object directly
        response = llm.invoke(messages)
        full_response = response.model_dump_json(indent=4, exclude_none=True)
    else:
        # For streaming responses, chunks are AIMessageChunk with content attribute
        response = llm.stream(messages)
        for chunk in response:
            full_response += chunk.content
    
    logger.debug(f"Current state messages: {state['messages']}")
    logger.info(f"Molecular planner response: {full_response}")

    try:
        curr_plan = json.loads(repair_json_output(full_response))
    except json.JSONDecodeError:
        logger.warning("Molecular planner response is not a valid JSON")
        if plan_iterations > 0:
            return Command(goto="reporter")
        else:
            return Command(goto="__end__")
    if isinstance(curr_plan, dict) and curr_plan.get("has_enough_context"):
        logger.info("Molecular planner response has enough context.")
        new_plan = Plan.model_validate(curr_plan)
        return Command(
            update={
                "messages": [AIMessage(content=full_response, name="molecular_planner")],
                "current_plan": new_plan,
            },
            goto="common_reporter",
        )
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="molecular_planner")],
            "current_plan": full_response,
        },
        goto="human_feedback",
    )


def vasp_planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["human_feedback", "__end__"]]:
    """VASP workflow planner: output a Plan with steps, then go to human_feedback for Edit/Start."""
    logger.info("VASP planner generating plan")
    configurable = Configuration.from_runnable_config(config)
    # VASP 4-step plan: load → submit (composite) → status → band plot (composite)
    if getattr(configurable, "max_step_num", 3) < 4:
        configurable = dataclasses.replace(configurable, max_step_num=10)
    messages = apply_prompt_template("vasp_planner", state, configurable)
    llm = get_llm_by_type("basic")
    try:
        llm = llm.with_structured_output(Plan, method="json_mode")
    except Exception:
        pass
    response = llm.invoke(messages)
    full_response = response.model_dump_json(indent=4, exclude_none=True) if hasattr(response, "model_dump_json") else str(response.content)
    try:
        curr_plan = json.loads(repair_json_output(full_response))
    except json.JSONDecodeError:
        logger.warning("VASP planner response is not valid JSON")
        return Command(goto="__end__")
    if not isinstance(curr_plan, dict):
        return Command(goto="__end__")
    new_plan = Plan.model_validate(curr_plan)
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="vasp_planner")],
            "current_plan": new_plan,
        },
        goto="human_feedback",
    )


def _vasp_current_step_is_composite(current_plan) -> bool:
    """True iff the first unexecuted step has execution_mode composite_submit or composite_band.
    仅当步骤显式标记为组合步时才走 composite；4 步全 agent 时全部走 executor。"""
    steps = getattr(current_plan, "steps", None) or []
    for step in steps:
        if not getattr(step, "execution_res", None):
            mode = getattr(step, "execution_mode", None)
            if mode in ("composite_submit", "composite_band"):
                return True
            return False
    return False


def vasp_team_routing(state: State) -> str:
    """Route: all steps done -> common_reporter; 刚跑完组合步 -> vasp_executor(LLM 参与); composite step -> vasp_composite; else -> vasp_executor."""
    current_plan = state.get("current_plan")
    if not current_plan or not getattr(current_plan, "steps", None):
        return "common_reporter"
    if all(getattr(s, "execution_res", None) for s in current_plan.steps):
        return "common_reporter"
    # 组合步已执行完毕，等待 LLM 参与总结/补充
    if state.get("vasp_post_composite"):
        return "vasp_executor"
    if _vasp_current_step_is_composite(current_plan):
        return "vasp_composite"
    return "vasp_executor"


def vasp_team_node(state: State) -> dict:
    """Routing-only node: state passes through; conditional edge chooses vasp_executor, vasp_composite, or common_reporter."""
    return {}


def vasp_composite_node(
    state: State, config: RunnableConfig
) -> Command[Literal["vasp_team"]]:
    """
    Execute a composite VASP step without LLM: composite_submit (generate_inputs + get_hpc_config + submit_to_hpc)
    or composite_band (download vasprun.xml + plot_band_structure). Reads inputs from completed_steps.
    """
    from src.server.app import TOOL_REGISTRY

    current_plan = state.get("current_plan")
    if not current_plan or not getattr(current_plan, "steps", None):
        return Command(goto="vasp_team")
    current_step = None
    completed_steps = []
    for step in current_plan.steps:
        if not getattr(step, "execution_res", None):
            current_step = step
            break
        completed_steps.append(step)
    if not current_step:
        return Command(goto="vasp_team")

    mode = getattr(current_step, "execution_mode", None)
    steps = current_plan.steps
    if not mode:
        idx = steps.index(current_step)
        if len(steps) == 4:
            mode = "composite_submit" if idx == 1 else ("composite_band" if idx == 3 else None)
        elif len(steps) == 3:
            mode = "composite_submit" if idx == 1 else ("composite_band" if idx == 2 else None)
        else:
            mode = None

    observations = state.get("observations", [])

    def _invoke(tool_name: str, args: dict) -> dict:
        t = TOOL_REGISTRY.get(tool_name)
        if not t or not callable(getattr(t, "invoke", None)):
            return {"error": f"Tool {tool_name} not found"}
        out = t.invoke(args)
        if isinstance(out, str):
            try:
                return json.loads(repair_json_output(out))
            except (json.JSONDecodeError, ValueError):
                return {"error": out}
        return out if isinstance(out, dict) else {"error": str(out)}

    if mode == "composite_submit":
        # 幂等：若本步已有提交结果（state 中有 vasp_composite_result 且含 job_id），视为步骤已成功，直接进入下一步
        existing = state.get("vasp_composite_result")
        if existing:
            try:
                parsed = json.loads(repair_json_output(existing))
                if parsed.get("job_id") and parsed.get("remote_dir"):
                    logger.info("VASP composite_submit idempotent: already have job_id=%s, mark step done and go to next", parsed.get("job_id"))
                    current_step.execution_res = existing
                    return Command(
                        update={
                            "messages": [HumanMessage(content=existing, name="vasp_composite")],
                            "observations": observations + [existing],
                            "vasp_post_composite": False,
                            "vasp_composite_result": None,
                        },
                        goto="vasp_team",
                    )
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        poscar = _parse_poscar_from_completed_steps(completed_steps)
        if not poscar:
            current_step.execution_res = json.dumps(
                {"error": "缺少 Step 1 的 poscar_content，无法生成输入"}, ensure_ascii=False
            )
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        gen = _invoke("vaspilot_generate_inputs", {"poscar_content": poscar, "calc_type": "band"})
        if gen.get("error"):
            current_step.execution_res = json.dumps(gen, ensure_ascii=False)
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        files = gen.get("files")
        if not files or not isinstance(files, dict) or "submit.sh" not in files:
            current_step.execution_res = json.dumps(
                {"error": "generate_inputs 未返回有效 files（需包含 submit.sh）"}, ensure_ascii=False
            )
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        hpc = _invoke("vaspilot_get_hpc_config", {})
        if hpc.get("error") or not (hpc.get("host") and hpc.get("username")):
            current_step.execution_res = json.dumps(
                hpc if hpc.get("error") else {"error": "get_hpc_config 未返回 host/username"}, ensure_ascii=False
            )
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        remote_work_dir = (hpc.get("work_dir") or hpc.get("remote_work_dir") or "").strip()
        if not remote_work_dir:
            current_step.execution_res = json.dumps({"error": "HPC 配置缺少 work_dir"}, ensure_ascii=False)
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        submit_args = {
            "files": files,
            "host": str(hpc.get("host", "")).strip(),
            "username": str(hpc.get("username", "")).strip(),
            "remote_work_dir": remote_work_dir,
            "port": int(hpc.get("port", 22)) if hpc.get("port") else 22,
            "key_path": (str(hpc.get("key_path", "")).strip() or None),
            "password": "__use_config__",
        }
        submit_res = _invoke("vaspilot_submit_to_hpc", submit_args)
        if submit_res.get("error") or not submit_res.get("success"):
            current_step.execution_res = json.dumps(submit_res, ensure_ascii=False)
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        # Store job_id, remote_dir and hpc for Step 3/4
        result = {
            "success": True,
            "job_id": submit_res.get("job_id"),
            "remote_dir": submit_res.get("remote_dir"),
            "message": submit_res.get("message", ""),
            "host": hpc.get("host"),
            "username": hpc.get("username"),
            "port": hpc.get("port", 22),
            "key_path": hpc.get("key_path"),
            "work_dir": remote_work_dir,
        }
        composite_res = json.dumps(result, ensure_ascii=False)
        logger.info("VASP composite_submit done: job_id=%s remote_dir=%s", result.get("job_id"), result.get("remote_dir"))
        # 给用户看的消息：生成输入文件列表+各文件内容+检查项+提交结果，便于看到有哪些输入文件
        display = (gen.get("display") or "").strip()
        if display:
            user_visible = display + "\n\n--- 提交结果 ---\n" + json.dumps(result, ensure_ascii=False, indent=2)
        else:
            user_visible = composite_res
        # 写入 state 供 composite_band 轮询使用，避免从 execution_res 解析不到 job_id 时跳过轮询
        update = {
            "messages": [HumanMessage(content=user_visible, name="vasp_composite")],
            "observations": observations + [user_visible],
            "vasp_composite_result": composite_res,
            "vasp_gen_display": display or None,
            "vasp_post_composite": True,
            "vasp_submit_job_id": str(result.get("job_id", "")).strip() or None,
            "vasp_submit_remote_dir": str(result.get("remote_dir", "")).strip() or None,
            "vasp_submit_host": str(result.get("host", "")).strip() or None,
            "vasp_submit_username": str(result.get("username", "")).strip() or None,
            "vasp_submit_port": int(result.get("port", 22)) if result.get("port") is not None else 22,
            "vasp_submit_key_path": (str(result.get("key_path", "")).strip() or None),
        }
        return Command(update=update, goto="vasp_team")

    if mode == "composite_band":
        # 优先从 state 取提交结果（composite_submit 写入），避免从 execution_res 解析失败导致无 job_id 从而跳过轮询
        submit_info = {
            "job_id": (state.get("vasp_submit_job_id") or "").strip() or None,
            "remote_dir": (state.get("vasp_submit_remote_dir") or "").strip() or None,
            "host": (state.get("vasp_submit_host") or "").strip() or None,
            "username": (state.get("vasp_submit_username") or "").strip() or None,
            "port": state.get("vasp_submit_port") if state.get("vasp_submit_port") is not None else 22,
            "key_path": (state.get("vasp_submit_key_path") or "").strip() or None,
        }
        parsed = _parse_submit_result_from_completed_steps(completed_steps)
        for k, v in parsed.items():
            if v is not None and (v != "" if isinstance(v, str) else True):
                submit_info[k] = v
        remote_dir = submit_info.get("remote_dir")
        host = submit_info.get("host")
        username = submit_info.get("username")
        job_id = submit_info.get("job_id")
        logger.info(
            "VASP composite_band: submit_info job_id=%s remote_dir=%s host=%s",
            job_id, remote_dir, host,
        )
        if not host or not username:
            hpc = _invoke("vaspilot_get_hpc_config", {})
            if not hpc.get("error"):
                host = host or str(hpc.get("host", "")).strip()
                username = username or str(hpc.get("username", "")).strip()
        if not remote_dir:
            current_step.execution_res = json.dumps(
                {"error": "缺少 Step 2 的 remote_dir，无法下载 vasprun.xml"}, ensure_ascii=False
            )
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        if not host or not username:
            current_step.execution_res = json.dumps(
                {"error": "缺少 HPC host/username，无法下载 vasprun.xml"}, ensure_ascii=False
            )
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        # 必须有 job_id 才能轮询，否则会直接下载（作业可能仍在 RUNNING）
        if not job_id and remote_dir:
            current_step.execution_res = json.dumps(
                {"error": "缺少 job_id，无法轮询作业状态。请确保上一步提交结果包含 job_id，或使用带 composite 的能带流程。"}, ensure_ascii=False
            )
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        port = submit_info.get("port", 22)
        key_path = submit_info.get("key_path")
        # 轮询作业状态直到 COMPLETED 或 FAILED，再下载/画图（与 scripts/run_band_workflow.py 一致：RUNNING 时持续轮询）
        if job_id:
            poll_interval_sec = 30
            while True:
                st = _invoke(
                    "vaspilot_job_status",
                    {
                        "job_id": job_id,
                        "host": host,
                        "username": username,
                        "port": port,
                        "key_path": key_path,
                        "password": "__use_config__",
                    },
                )
                if st.get("error"):
                    current_step.execution_res = json.dumps(
                        {"error": f"查询作业状态失败: {st.get('error')}"}, ensure_ascii=False
                    )
                    return Command(
                        update={
                            "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                            "observations": observations + [current_step.execution_res],
                        },
                        goto="vasp_team",
                    )
                status = (st.get("status") or "").strip().upper()
                node_info = st.get("node") or ""
                time_used = st.get("time_used") or ""
                logger.info("VASP composite_band 轮询: job_id=%s 状态=%s %s %s", job_id, status, node_info, time_used)
                if status == "COMPLETED":
                    logger.info("VASP composite_band: job %s COMPLETED, proceeding to download", job_id)
                    break
                if status == "FAILED":
                    current_step.execution_res = json.dumps(
                        {
                            "error": "作业已失败 (FAILED)，请使用 vaspilot_fetch_job_logs 查看远程日志后重试或修改输入。",
                            "job_id": job_id,
                            "status": status,
                        },
                        ensure_ascii=False,
                    )
                    return Command(
                        update={
                            "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                            "observations": observations + [current_step.execution_res],
                        },
                        goto="vasp_team",
                    )
                logger.info("VASP composite_band: status=%s，%ds 后再次查询", status, poll_interval_sec)
                time.sleep(poll_interval_sec)
        dl = _invoke(
            "vaspilot_download_remote_file",
            {
                "remote_dir": remote_dir,
                "filename": "vasprun.xml",
                "host": host,
                "username": username,
                "port": port,
                "key_path": key_path,
                "password": "__use_config__",
            },
        )
        if dl.get("error") or not dl.get("content"):
            current_step.execution_res = json.dumps(dl if dl.get("error") else {"error": "下载 vasprun.xml 失败或内容为空"}, ensure_ascii=False)
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        # 能带图需 KPOINTS（line mode）否则 pymatgen 报 KPOINTS not found
        dl_kpts = _invoke(
            "vaspilot_download_remote_file",
            {
                "remote_dir": remote_dir,
                "filename": "KPOINTS",
                "host": host,
                "username": username,
                "port": port,
                "key_path": key_path,
                "password": "__use_config__",
            },
        )
        kpoints_content = (dl_kpts.get("content") or "").strip() if not dl_kpts.get("error") else ""
        # 传入 output_dir 使工具返回 image_path，仅将 image_path 写入 state，避免大 base64 导致打开会话卡顿
        plot_res = _invoke(
            "vaspilot_plot_band_structure",
            {
                "vasprun_xml_content": dl.get("content", ""),
                "kpoints_content": kpoints_content or None,
                "output_dir": "band_workflow_out",
            },
        )
        if plot_res.get("error"):
            current_step.execution_res = json.dumps(plot_res, ensure_ascii=False)
            return Command(
                update={
                    "messages": [HumanMessage(content=current_step.execution_res, name="vasp_composite")],
                    "observations": observations + [current_step.execution_res],
                },
                goto="vasp_team",
            )
        # 只存 image_path，不存 image_base64，避免 checkpoint/messages 过大、打开会话卡顿；报告通过 /api/workspace-file 展示
        band_res = json.dumps(
            {"success": True, "image_path": plot_res.get("image_path") or ""}, ensure_ascii=False
        )
        logger.info("VASP composite_band done: image generated (path only in state)")
        # 不在此处写 execution_res，交给 vasp_executor（LLM+组合）总结后再写
        return Command(
            update={
                "messages": [HumanMessage(content=band_res, name="vasp_composite")],
                "observations": observations + [band_res],
                "vasp_composite_result": band_res,
                "vasp_post_composite": True,
            },
            goto="vasp_team",
        )

    # Not a composite step; should not reach here if routing is correct
    return Command(goto="vasp_team")


def literature_planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["human_feedback", "literature_answerer", "reporter", "__end__"]]:
    """Planner for literature-based Q&A (Semantic Scholar + PDF crawler)."""
    logger.info("Literature planner generating plan")
    configurable = Configuration.from_runnable_config(config)
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0

    # Use full conversation history
    messages = apply_prompt_template("literature_planner", state, configurable)

    # LLM selection
    # LLM selection priority:
    # 1. If selected_model exists, use it (user's choice takes priority)
    # 2. If no selected_model but enable_deep_thinking, use REASONING_MODEL (backward compatibility)
    # 3. Otherwise use default AGENT_LLM_MAP
    if configurable.selected_model:
        llm = _get_llm_for_agent("planner", config)
        # Check if model supports thinking - if so, don't use structured output
        supports_thinking = get_model_supports_thinking(configurable.selected_model)
        if AGENT_LLM_MAP.get("planner") == "basic" and not supports_thinking:
            llm = llm.with_structured_output(Plan, method="json_mode")
    elif configurable.enable_deep_thinking:
        # Backward compatibility: use REASONING_MODEL when deep thinking is enabled but no model is selected
        llm = get_llm_by_type("reasoning")
    elif AGENT_LLM_MAP.get("planner") == "basic":
        llm = get_llm_by_type("basic").with_structured_output(
            Plan,
            method="json_mode",
        )
    else:
        llm = _get_llm_for_agent("planner", config)

    if plan_iterations >= configurable.max_plan_iterations:
        return Command(goto="reporter")

    full_response = ""
    # Check if using structured output
    # - Use structured output when: selected_model exists, AGENT_LLM_MAP is "basic", and model doesn't support thinking
    # - Or when: no selected_model, AGENT_LLM_MAP is "basic", and deep thinking is not enabled
    supports_thinking = False
    if configurable.selected_model:
        supports_thinking = get_model_supports_thinking(configurable.selected_model)
    
    using_structured_output = (
        (configurable.selected_model and AGENT_LLM_MAP.get("planner") == "basic" and not supports_thinking) or
        (not configurable.selected_model and AGENT_LLM_MAP.get("planner") == "basic" and not configurable.enable_deep_thinking)
    )
    
    if using_structured_output:
        # When using structured output, use invoke to get Plan object directly
        response = llm.invoke(messages)
        full_response = response.model_dump_json(indent=4, exclude_none=True)
    else:
        # For streaming responses, chunks are AIMessageChunk with content attribute
        response = llm.stream(messages)
        for chunk in response:
            full_response += chunk.content

    logger.info(f"Literature planner response: {full_response}")

    try:
        curr_plan = json.loads(repair_json_output(full_response))
    except json.JSONDecodeError:
        logger.warning("Literature planner response is not valid JSON")
        if plan_iterations > 0:
            return Command(goto="reporter")
        else:
            return Command(goto="__end__")

    if isinstance(curr_plan, dict) and curr_plan.get("has_enough_context"):
        new_plan = Plan.model_validate(curr_plan)
        return Command(
            update={
                "messages": [AIMessage(content=full_response, name="literature_planner")],
                "current_plan": new_plan,
            },
            goto="literature_answerer",
        )

    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="literature_planner")],
            "current_plan": full_response,
        },
        goto="human_feedback",
    )


async def literature_researcher_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Researcher restricted to literature tools (Semantic Scholar + PDF crawler)."""
    logger.info("Literature researcher is researching with SemanticScholar+PDF tools")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "researcher",
        [search_literature, fetch_pdf_text],
    )


def literature_answerer_node(state: State, config: RunnableConfig):
    """Answerer that produces deep Q&A format from literature evidence."""
    logger.info("Literature answerer generating deep answer")
    configurable = Configuration.from_runnable_config(config)
    current_plan = state.get("current_plan")

    input_ = {
        "messages": [
            HumanMessage(
                f"# Question\n\n{current_plan.title}\n\n## Context\n\n{current_plan.thought}"
            )
        ],
        "locale": state.get("locale", "en-US"),
    }
    invoke_messages = apply_prompt_template("literature_answerer", input_, configurable)

    observation_messages = []
    for observation in state.get("observations", []):
        observation_messages.append(
            HumanMessage(content=f"Evidence:\n\n{observation}", name="observation")
        )

    llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP["reporter"])
    compressed_state = ContextManager(llm_token_limit).compress_messages(
        {"messages": observation_messages}
    )
    invoke_messages += compressed_state.get("messages", [])

    response = _get_llm_for_agent("reporter", config).invoke(invoke_messages)
    response_content = response.content
    logger.info(f"literature answerer response length: {len(response_content)}")
    return {"final_answer": response_content}


def human_feedback_node(
    state: State, config: RunnableConfig
) -> Command[Literal["planner", "research_team", "vasp_team", "reporter", "__end__"]]:
    current_plan = state.get("current_plan", "")
    # check if the plan is auto accepted
    auto_accepted_plan = state.get("auto_accepted_plan", False)
    if not auto_accepted_plan:
        feedback = interrupt("Please Review the Plan.")

        # if the feedback is not accepted, return the planner node
        if feedback and str(feedback).upper().startswith("[EDIT_PLAN]"):
            return Command(
                update={
                    "messages": [
                        HumanMessage(content=feedback, name="feedback"),
                    ],
                },
                goto="planner",
            )
        elif feedback and str(feedback).upper().startswith("[ACCEPTED]"):
            logger.info("Plan is accepted by user.")
        else:
            raise TypeError(f"Interrupt value of {feedback} is not supported.")

    # if the plan is accepted, run the following node
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0
    goto = "research_team"
    # 按「最近一条计划消息」决定下一跳：vasp_planner → vasp_team（plan→vasp_executor→report）；否则 → research_team（深度研究/分子/文献）
    messages = state.get("messages", [])
    for m in reversed(messages):
        if not hasattr(m, "name"):
            continue
        name = getattr(m, "name", None)
        if name == "vasp_planner":
            goto = "vasp_team"
            logger.info("human_feedback: routing to vasp_team (plan → vasp_executor → report)")
            break
        if name in ("planner", "molecular_planner", "literature_planner"):
            logger.info("human_feedback: routing to %s (last plan from %s)", goto, name)
            break
    
    # Handle both Plan object and string
    if isinstance(current_plan, Plan):
        # If it's already a Plan object, use it directly
        new_plan = current_plan.model_dump()
    else:
        try:
            current_plan_str = repair_json_output(current_plan)
            # parse the plan
            new_plan = json.loads(current_plan_str)
        except json.JSONDecodeError:
            logger.warning("Planner response is not a valid JSON")
            if plan_iterations > 1:  # the plan_iterations is increased before this check
                return Command(goto="reporter")
            else:
                return Command(goto="__end__")
    
    # increment the plan iterations
    plan_iterations += 1

    return Command(
        update={
            "current_plan": Plan.model_validate(new_plan),
            "plan_iterations": plan_iterations,
            "locale": new_plan["locale"],
        },
        goto=goto,
    )


def coordinator_node(
    state: State, config: RunnableConfig
) -> Command[Literal["planner", "molecular_planner", "vasp_planner", "background_investigator", "coordinator", "__end__"]]:
    """Coordinator node that communicate with customers and handle clarification."""
    logger.info("Coordinator talking.")
    configurable = Configuration.from_runnable_config(config)

    # 如果会话启用了知识库（前端通过 resources 传入），则直接走 RAG 问答模式，
    # 不再进入 planner 流程，而是交给 rag_agent_node。
    resources = configurable.resources or state.get("resources", [])
    if resources:
        logger.info("Knowledge base resources detected, routing directly to rag_agent")
        messages = state.get("messages", [])
        research_topic = state.get("research_topic", "")
        locale = state.get("locale", "en-US")

        # 尝试用最后一条用户消息作为问题标题，并根据内容粗略识别语言（中/英）
        last_user = None
        for m in reversed(messages):
            if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") == "user"):
                last_user = m
                break
        if last_user:
            content = last_user.content if hasattr(last_user, "content") else last_user.get("content", "")
            text = (content or "")[:200]
            if not research_topic:
                research_topic = text
            # 简单语言检测：包含中文字符则使用 zh-CN，否则保持默认
            try:
                if any("\u4e00" <= ch <= "\u9fff" for ch in text):
                    locale = "zh-CN"
            except Exception:
                pass
        return Command(
            update={
                "messages": messages,
                "locale": locale,
                "research_topic": research_topic,
                "resources": resources,
                "goto": "rag_agent",
            },
            goto="rag_agent",
        )

    # Check if clarification is enabled
    enable_clarification = state.get("enable_clarification", False)

    # ============================================================
    # BRANCH 1: Clarification DISABLED (Legacy Mode)
    # ============================================================
    if not enable_clarification:
        # Use normal prompt with explicit instruction to skip clarification
        messages = apply_prompt_template("coordinator", state)
        messages.append(
            {
                "role": "system",
                "content": "CRITICAL: Clarification is DISABLED. You MUST immediately call handoff_to_planner tool with the user's query as-is. Do NOT ask questions or mention needing more information.",
            }
        )

        # Bind handoff tools (literature planner branch removed)
        tools = [handoff_to_planner, handoff_to_molecular_planner, handoff_to_vasp]
        response = (
            _get_llm_for_agent("coordinator", config)
            .bind_tools(tools)
            .invoke(messages)
        )

        # Process response - should directly handoff to planner
        goto = "__end__"
        locale = state.get("locale", "en-US")
        research_topic = state.get("research_topic", "")

        # Literature fast-path removed; all literature-like queries go through general planner unless molecular

        # Process tool calls for legacy mode
        if response.tool_calls:
            try:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    if tool_name == "handoff_to_molecular_planner":
                        logger.info("Handing off to molecular_planner")
                        goto = "molecular_planner"
                        
                        # Extract locale and research_topic if provided
                        if tool_args.get("locale") and tool_args.get("research_topic"):
                            locale = tool_args.get("locale")
                            research_topic = tool_args.get("research_topic")
                        break
                    elif tool_name == "handoff_to_vasp":
                        logger.info("Handing off to vasp_planner")
                        goto = "vasp_planner"
                        if tool_args.get("locale") and tool_args.get("research_topic"):
                            locale = tool_args.get("locale")
                            research_topic = tool_args.get("research_topic")
                        break
                    elif tool_name == "handoff_to_planner":
                        logger.info("Handing off to planner")
                        goto = "planner"
                    

            except Exception as e:
                logger.error(f"Error processing tool calls: {e}")
                goto = "planner"

    # ============================================================
    # BRANCH 2: Clarification ENABLED (New Feature)
    # ============================================================
    else:
        # Load clarification state
        clarification_rounds = state.get("clarification_rounds", 0)
        clarification_history = state.get("clarification_history", [])
        max_clarification_rounds = state.get("max_clarification_rounds", 3)

        # Prepare the messages for the coordinator
        messages = apply_prompt_template("coordinator", state)

        # Add clarification status for first round
        if clarification_rounds == 0:
            messages.append(
                {
                    "role": "system",
                    "content": "Clarification mode is ENABLED. Follow the 'Clarification Process' guidelines in your instructions.",
                }
            )

        # Add clarification context if continuing conversation (round > 0)
        elif clarification_rounds > 0:
            logger.info(
                f"Clarification enabled (rounds: {clarification_rounds}/{max_clarification_rounds}): Continuing conversation"
            )

            # Add user's response to clarification history (only user messages)
            last_message = None
            if state.get("messages"):
                last_message = state["messages"][-1]
                # Extract content from last message for logging
                if isinstance(last_message, dict):
                    content = last_message.get("content", "No content")
                else:
                    content = getattr(last_message, "content", "No content")
                logger.info(f"Last message content: {content}")
                # Handle dict format
                if isinstance(last_message, dict):
                    if last_message.get("role") == "user":
                        clarification_history.append(last_message["content"])
                        logger.info(
                            f"Added user response to clarification history: {last_message['content']}"
                        )
                # Handle object format (like HumanMessage)
                elif hasattr(last_message, "role") and last_message.role == "user":
                    clarification_history.append(last_message.content)
                    logger.info(
                        f"Added user response to clarification history: {last_message.content}"
                    )
                # Handle object format with content attribute (like the one in logs)
                elif hasattr(last_message, "content"):
                    clarification_history.append(last_message.content)
                    logger.info(
                        f"Added user response to clarification history: {last_message.content}"
                    )

            # Build comprehensive clarification context with conversation history
            current_response = "No response"
            if last_message:
                # Handle dict format
                if isinstance(last_message, dict):
                    if last_message.get("role") == "user":
                        current_response = last_message.get("content", "No response")
                    else:
                        # If last message is not from user, try to get the latest user message
                        messages = state.get("messages", [])
                        for msg in reversed(messages):
                            if isinstance(msg, dict) and msg.get("role") == "user":
                                current_response = msg.get("content", "No response")
                                break
                # Handle object format (like HumanMessage)
                elif hasattr(last_message, "role") and last_message.role == "user":
                    current_response = last_message.content
                # Handle object format with content attribute (like the one in logs)
                elif hasattr(last_message, "content"):
                    current_response = last_message.content
                else:
                    # If last message is not from user, try to get the latest user message
                    messages = state.get("messages", [])
                    for msg in reversed(messages):
                        if isinstance(msg, dict) and msg.get("role") == "user":
                            current_response = msg.get("content", "No response")
                            break
                        elif hasattr(msg, "role") and msg.role == "user":
                            current_response = msg.content
                            break
                        elif hasattr(msg, "content"):
                            current_response = msg.content
                            break

            # Create conversation history summary
            conversation_summary = ""
            if clarification_history:
                conversation_summary = "Previous conversation:\n"
                for i, response in enumerate(clarification_history, 1):
                    conversation_summary += f"- Round {i}: {response}\n"

            clarification_context = f"""Continuing clarification (round {clarification_rounds}/{max_clarification_rounds}):
            User's latest response: {current_response}
            Ask for remaining missing dimensions. Do NOT repeat questions or start new topics."""

            # Log the clarification context for debugging
            logger.info(f"Clarification context: {clarification_context}")

            messages.append({"role": "system", "content": clarification_context})

        # Bind all handoff tools
        tools = [handoff_to_planner, handoff_to_molecular_planner, handoff_to_vasp, handoff_after_clarification]
        response = (
            _get_llm_for_agent("coordinator", config)
            .bind_tools(tools)
            .invoke(messages)
        )
        logger.debug(f"Current state messages: {state['messages']}")

        # Initialize response processing variables
        goto = "__end__"
        locale = state.get("locale", "en-US")
        research_topic = state.get("research_topic", "")

        # --- Process LLM response ---
        # No tool calls - LLM is asking a clarifying question
        if not response.tool_calls and response.content:
            if clarification_rounds < max_clarification_rounds:
                # Continue clarification process
                clarification_rounds += 1
                # Do NOT add LLM response to clarification_history - only user responses
                logger.info(
                    f"Clarification response: {clarification_rounds}/{max_clarification_rounds}: {response.content}"
                )

                # Append coordinator's question to messages
                state_messages = state.get("messages", [])
                if response.content:
                    state_messages.append(
                        HumanMessage(content=response.content, name="coordinator")
                    )

                return Command(
                    update={
                        "messages": state_messages,
                        "locale": locale,
                        "research_topic": research_topic,
                        "resources": configurable.resources,
                        "clarification_rounds": clarification_rounds,
                        "clarification_history": clarification_history,
                        "is_clarification_complete": False,
                        "clarified_question": "",
                        "goto": goto,
                        "__interrupt__": [("coordinator", response.content)],
                    },
                    goto=goto,
                )
            else:
                # Max rounds reached - no more questions allowed
                logger.warning(
                    f"Max clarification rounds ({max_clarification_rounds}) reached. Handing off to planner."
                )
                goto = "planner"
                if state.get("enable_background_investigation"):
                    goto = "background_investigator"
        else:
            # LLM called a tool (handoff) or has no content - clarification complete
            if response.tool_calls:
                logger.info(
                    f"Clarification completed after {clarification_rounds} rounds. LLM called handoff tool."
                )
            else:
                logger.warning("LLM response has no content and no tool calls.")
            # goto will be set in the final section based on tool calls

    # ============================================================
    # Final: Build and return Command
    # ============================================================
    messages = state.get("messages", [])
    if response.content:
        messages.append(HumanMessage(content=response.content, name="coordinator"))

    # Process tool calls for BOTH branches (legacy and clarification)
    if response.tool_calls:
        try:
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})

                if tool_name == "handoff_to_molecular_planner":
                    logger.info("Handing off to molecular_planner")
                    goto = "molecular_planner"
                    
                    # Extract locale and research_topic if provided
                    if tool_args.get("locale") and tool_args.get("research_topic"):
                        locale = tool_args.get("locale")
                        research_topic = tool_args.get("research_topic")
                    break
                elif tool_name == "handoff_to_vasp":
                    logger.info("Handing off to vasp_planner")
                    goto = "vasp_planner"
                    if tool_args.get("locale") and tool_args.get("research_topic"):
                        locale = tool_args.get("locale")
                        research_topic = tool_args.get("research_topic")
                    break
                elif tool_name in ["handoff_to_planner", "handoff_after_clarification"]:
                    logger.info("Handing off to planner")
                    goto = "planner"

                    # Extract locale and research_topic if provided
                    if tool_args.get("locale") and tool_args.get("research_topic"):
                        locale = tool_args.get("locale")
                        research_topic = tool_args.get("research_topic")
                    break

        except Exception as e:
            logger.error(f"Error processing tool calls: {e}")
            goto = "planner"
    else:
        # No tool calls - both modes should goto __end__
        logger.warning("LLM didn't call any tools. Staying at __end__.")
        goto = "__end__"

    # Apply background_investigation routing if enabled (unified logic)
    if goto == "planner" and state.get("enable_background_investigation"):
        goto = "background_investigator"

    # Set default values for state variables (in case they're not defined in legacy mode)
    if not enable_clarification:
        clarification_rounds = 0
        clarification_history = []

    return Command(
        update={
            "messages": messages,
            "locale": locale,
            "research_topic": research_topic,
            "resources": configurable.resources,
            "clarification_rounds": clarification_rounds,
            "clarification_history": clarification_history,
            "is_clarification_complete": goto != "coordinator",
            "clarified_question": research_topic if goto != "coordinator" else "",
            "goto": goto,
        },
        goto=goto,
    )


async def vasp_agent_node(state: State, config: RunnableConfig):
    """
    Run VASP ReAct agent (vaspilot tools) in a loop, then hand off to common_reporter.
    Same as molecular_planner flow: user goal -> single agent with tools -> common_reporter.
    """
    logger.info("VASP agent node running")
    try:
        from src.server.app import get_vasp_graph
        vasp = get_vasp_graph()
    except ValueError as e:
        logger.warning("VASP graph not available: %s", e)
        from langchain_core.messages import AIMessage
        err_msg = AIMessage(
            content=f"VASP 工具暂不可用：{e!s}。请确保已启用 vaspilot-skill 并加载工具。",
            name="vasp_agent",
        )
        minimal_plan = Plan(
            locale=state.get("locale", "en-US"),
            has_enough_context=True,
            thought="VASP workflow (tools unavailable).",
            title=state.get("research_topic", "VASP 计算")[:200],
            steps=[],
        )
        return Command(
            update={
                "messages": state.get("messages", []) + [err_msg],
                "current_plan": minimal_plan,
                "observations": [],
            },
            goto="common_reporter",
        )
    out = await vasp.ainvoke(
        {"messages": state["messages"]},
        config=config,
    )
    new_messages = out.get("messages", state["messages"])
    # Build minimal plan for common_reporter (title from last user message)
    research_topic = state.get("research_topic", "")
    if not research_topic and new_messages:
        for m in reversed(new_messages):
            if isinstance(m, HumanMessage):
                research_topic = (m.content or "")[:200]
                break
    minimal_plan = Plan(
        locale=state.get("locale", "en-US"),
        has_enough_context=True,
        thought="VASP workflow execution.",
        title=research_topic or "VASP 计算",
        steps=[],
    )
    return Command(
        update={
            "messages": new_messages,
            "current_plan": minimal_plan,
            "observations": [],
        },
        goto="common_reporter",
    )


async def rag_agent_node(
    state: State, config: RunnableConfig
) -> Command[Literal["__end__"]]:
    """
    Single-turn RAG QA agent（直接面向用户流式输出）.

    当会话启用了知识库（state.resources 非空）时，优先、强制使用本地知识库检索
    来回答用户问题，并由 `rag_agent` 自己直接给出最终回答（不再经过 common_reporter 二次整理），
    以便前端可以看到完整的流式输出体验。
    当前实现：只挂载 local_search_tool；仅在完全没有 retriever 时才兜底使用 web_search。
    """
    logger.info("RAG agent node running")
    configurable = Configuration.from_runnable_config(config)

    tools = []

    # 1. 知识库检索工具（RAGFlow / 其他 provider）——RAG 模式的核心，必须优先使用
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.append(retriever_tool)
        logger.info("RAG agent: added local_search_tool with resources")
    else:
        # 理论上启用 @知识库 时一定会有 retriever；这里做兜底，避免前端挂了知识库但后端未正确配置时完全报错
        try:
            web_tool = get_web_search_tool(configurable.max_search_results)
            tools.append(web_tool)
            logger.warning(
                "RAG agent: no retriever found for resources, falling back to web_search only"
            )
        except Exception as e:
            logger.error("RAG agent: failed to init fallback web_search tool: %s", e)

    # 创建基于 researcher 提示词的 ReAct agent（只用检索类工具）
    llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP["researcher"])
    pre_model_hook = partial(ContextManager(llm_token_limit, 3).compress_messages)
    selected_model = configurable.selected_model if configurable else None

    agent = create_agent(
        "rag_agent",
        "researcher",
        tools,
        "researcher",
        pre_model_hook,
        selected_model,
    )

    out = await agent.ainvoke(
        {"messages": state["messages"]},
        config=config,
    )
    new_messages = out.get("messages", state["messages"])

    # 直接更新消息并结束流程，由 rag_agent 的回答作为最终输出（支持流式）
    return Command(
        update={
            "messages": new_messages,
        },
        goto="__end__",
    )


async def vasp_executor_node(
    state: State, config: RunnableConfig
) -> Command[Literal["vasp_team"]]:
    """Execute one VASP plan step using vaspilot tools, then return to vasp_team."""
    from src.server.app import TOOL_REGISTRY
    from src.graph.vasp_agent import get_vasp_tools_from_registry

    vasp_tools = get_vasp_tools_from_registry(TOOL_REGISTRY)
    if not vasp_tools:
        logger.warning("No vaspilot tools in registry; skipping step")
        return Command(goto="vasp_team")
    # 本步内「submit_to_hpc 缺 files 失败」计数清零，超过 _SUBMIT_FILES_ERROR_LIMIT 次后返回终止说明
    try:
        _VASP_SUBMIT_FILES_ERROR_CTX.set(0)
    except Exception:
        pass
    # Set HPC config in context so wrapped tools can fill missing host/username/remote_work_dir when LLM omits them
    current_plan = state.get("current_plan")
    completed_steps = []
    if current_plan and getattr(current_plan, "steps", None):
        completed_steps = [s for s in current_plan.steps if getattr(s, "execution_res", None)]
    hpc_args = _parse_hpc_config_from_completed_steps(completed_steps)
    files_from_steps = _parse_files_from_completed_steps(completed_steps)
    if files_from_steps is not None:
        logger.info("VASP: parsed files from completed steps for submit_to_hpc, keys=%s", list(files_from_steps.keys()))
    else:
        logger.info("VASP: no files parsed from completed steps (will rely on context or LLM)")
    token = None
    files_token = None
    band_token = None
    if hpc_args:
        token = _VASP_HPC_CONFIG_CTX.set(hpc_args)
    if files_from_steps is not None:
        try:
            files_token = _VASP_SUBMIT_FILES_CTX.set(files_from_steps)
        except Exception:
            pass
    # 第 4 步画图时从 state 注入 vasprun/kpoints，避免大内容进 prompt
    band_ctx = {}
    if state.get("vasp_vasprun_xml_content"):
        band_ctx["vasprun_xml_content"] = state["vasp_vasprun_xml_content"]
    if state.get("vasp_kpoints_content") is not None:
        band_ctx["kpoints_content"] = state.get("vasp_kpoints_content") or ""
    if band_ctx:
        band_token = _VASP_BAND_CONTENT_CTX.set(band_ctx)
    vasp_tools = [_wrap_vasp_plot_band_from_ctx(_wrap_vasp_tool_with_hpc_fill(t, cached_files=files_from_steps)) for t in vasp_tools]
    try:
        return await _setup_and_execute_agent_step(
            state, config, "vasp_executor", vasp_tools, next_goto="vasp_team"
        )
    finally:
        if token is not None:
            _VASP_HPC_CONFIG_CTX.reset(token)
        if files_token is not None:
            try:
                _VASP_SUBMIT_FILES_CTX.reset(files_token)
            except Exception:
                pass
        if band_token is not None:
            try:
                _VASP_BAND_CONTENT_CTX.reset(band_token)
            except Exception:
                pass


def reporter_node(state: State, config: RunnableConfig):
    """Reporter node that generates a comprehensive detailed answer."""
    logger.info("Reporter generating comprehensive detailed answer")
    configurable = Configuration.from_runnable_config(config)
    current_plan = state.get("current_plan")
    input_ = {
        "messages": [
            HumanMessage(
                f"# Research Question\n\n## Question\n\n{current_plan.title}\n\n## Context\n\n{current_plan.thought}"
            )
        ],
        "locale": state.get("locale", "en-US"),
    }
    invoke_messages = apply_prompt_template("reporter", input_, configurable)
    observations = state.get("observations", [])

    # Add a reminder about the new detailed answer format
    invoke_messages.append(
        HumanMessage(
            content="IMPORTANT: Generate a comprehensive and detailed answer that thoroughly addresses the research question. Focus on:\n\n1. Comprehensive Answer - Thorough, detailed response with multiple perspectives\n2. Detailed Analysis - In-depth analysis with comprehensive explanations\n3. Supporting Evidence - Extensive data, examples, and case studies\n4. Key Insights - Important discoveries and implications\n5. Additional Context - Broader context and related topics\n\nProvide comprehensive coverage with detailed explanations, examples, and context. Make it thorough and informative.",
            name="system",
        )
    )

    observation_messages = []
    for observation in observations:
        observation_messages.append(
            HumanMessage(
                content=f"Research findings:\n\n{observation}",
                name="observation",
            )
        )

    # Context compression
    llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP["reporter"])
    compressed_state = ContextManager(llm_token_limit).compress_messages(
        {"messages": observation_messages}
    )
    invoke_messages += compressed_state.get("messages", [])

    logger.debug(f"Current invoke messages: {invoke_messages}")
    response = _get_llm_for_agent("reporter", config).invoke(invoke_messages)
    response_content = response.content
    logger.info(f"reporter response: {response_content}")

    return {"final_report": response_content}


def common_reporter_node(state: State, config: RunnableConfig):
    """Common reporter node for non-research tasks (molecule generation, calculations, etc.)."""
    import re
    from langchain_core.messages import AIMessage
    
    logger.info("Common reporter formatting task results")
    configurable = Configuration.from_runnable_config(config)
    current_plan = state.get("current_plan")
    
    # Determine task type from messages
    messages = state.get("messages", [])
    task_type = "general"
    for msg in messages:
        if isinstance(msg, AIMessage):
            if getattr(msg, 'name', None) == "molecular_planner":
                task_type = "molecular_generation"
                break
    
    observations = state.get("observations", [])
    
    # Note: observations should only contain summaries (no base64 data)
    # Images are stored separately in molecular_images to avoid token waste
    
    input_ = {
        "messages": [
            HumanMessage(
                f"# Task\n\n## Objective\n\n{current_plan.title}\n\n## Context\n\n{current_plan.thought}"
            )
        ],
        "locale": state.get("locale", "en-US"),
        "task_type": task_type,
    }
    
    invoke_messages = apply_prompt_template("common_reporter", input_, configurable)
    
    # Add task-specific formatting instructions
    if task_type == "molecular_generation":
        pass  # Use template prompt only
    else:
        invoke_messages.append(
            HumanMessage(
                content="IMPORTANT: Format the task results clearly and concisely:\n\n1. Summary - Brief overview of results\n2. Key Findings - Main results and outputs\n3. Analysis - Interpretation and insights\n\nGenerate a clear, professional report.",
                name="system",
            )
        )
    
    # Add observations (should only contain summaries, no base64)
    observation_messages = []
    for observation in observations:
        observation_messages.append(
            HumanMessage(
                content=f"Task results:\n\n{observation}",
                name="observation",
            )
        )
    
    # Context compression
    llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP["reporter"])
    compressed_state = ContextManager(llm_token_limit).compress_messages(
        {"messages": observation_messages}
    )
    invoke_messages += compressed_state.get("messages", [])
    
    logger.debug(f"Current invoke messages for common_reporter: {invoke_messages}")
    response = _get_llm_for_agent("reporter", config).invoke(invoke_messages)
    response_content = response.content
    
    logger.info(f"common reporter response length: {len(response_content)}")
    logger.info(f"Images in final report: {response_content.count('data:image')}")
    if len(response_content) > 500:
        logger.info(f"Response preview: {response_content[:500]}...")
    else:
        logger.info(f"common reporter response: {response_content}")
    
    # Get stored molecular images and combine with LLM response
    molecular_images = state.get("molecular_images", [])
    logger.info(f"=== COMMON REPORTER COMBINING ===")
    logger.info(f"LLM response length: {len(response_content)}")
    
    # LLM 应该已经在响应中包含了 <img> 标签
    # 直接返回 LLM 响应，不再手动附加图片
    final_content = response_content

    # VASP 能带工作流：若 observations 中有 step 结果含 image_base64/image_path，追加能带图到报告（与 common research 一致，在「结果」页展示）
    # 优先使用 image_path 通过 /api/workspace-file 展示，避免 base64 过长导致浏览器不渲染
    _MAX_BASE64_CHARS = 400_000  # 约 300KB 图片，再大则 data URL 易超限或卡顿
    for obs in (observations or []):
        obs_s = (obs or "").strip()
        if not obs_s or ("image_base64" not in obs_s and "image_path" not in obs_s):
            continue
        json_end = obs_s.find("\n\n---")
        json_str = obs_s[:json_end] if json_end >= 0 else obs_s
        try:
            data = json.loads(repair_json_output(json_str))
            if not isinstance(data, dict) or not data.get("success"):
                continue
            image_path = data.get("image_path") or ""
            b64 = data.get("image_base64") or ""
            # 1) 有 image_path 时用 API 链接展示，避免超大 base64
            if image_path and image_path.strip():
                try:
                    rel = os.path.relpath(image_path, os.getcwd()) if os.path.isabs(image_path) else image_path.strip()
                    if ".." not in rel and not rel.startswith("/"):
                        img_url = "/api/workspace-file?path=" + quote(rel, safe="/")
                        final_content = final_content.rstrip() + "\n\n## 能带图\n\n![能带图](" + img_url + ")\n\n"
                        logger.info("Common reporter: appended VASP band image via workspace-file API (path=%s)", rel)
                    else:
                        final_content = final_content.rstrip() + "\n\n## 能带图\n\n能带图已保存至：`" + image_path.strip() + "`，请在本机打开该文件查看。\n\n"
                        logger.info("Common reporter: appended VASP band image path (no API link)")
                except (ValueError, OSError):
                    final_content = final_content.rstrip() + "\n\n## 能带图\n\n能带图已保存至：`" + image_path.strip() + "`，请在本机打开该文件查看。\n\n"
                break
            # 2) 仅 base64 且长度可接受时内嵌
            if b64 and len(b64) <= _MAX_BASE64_CHARS:
                final_content = final_content.rstrip() + "\n\n## 能带图\n\n<img src=\"data:image/png;base64," + b64 + "\" alt=\"能带图\" width=\"800\" />\n"
                logger.info("Common reporter: appended VASP band image (base64, len=%s)", len(b64))
                break
            # 3) base64 过大或仅有 base64 无 path：只提示路径
            if b64:
                logger.warning("Common reporter: base64 too long (len=%s), not embedding; add path hint", len(b64))
            final_content = final_content.rstrip() + "\n\n## 能带图\n\n能带图已生成并保存至：`band_workflow_out/band_structure.png`，请在本机打开该文件查看。\n\n"
            logger.info("Common reporter: appended VASP band image path hint (no embed)")
            break
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    
    logger.info(f"Final content length: {len(final_content)}")
    if 'data:image' in final_content:
        logger.warning("⚠️  Final content contains 'data:image' - LLM may have generated incorrect image format")
    if '<img' in final_content:
        logger.info("✓ LLM included <img> tag in response")
    
    logger.info(f"=== END COMMON REPORTER COMBINING ===")
    
    # Return both final_report and messages to trigger streaming
    # Also preserve molecular_images in state for frontend access
    # #region debug log
    try:
        import time
        with open("/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log", "a") as f:
            f.write(json.dumps({
                "location": "nodes.py:common_reporter_node:1033",
                "message": "Common reporter returning result",
                "data": {
                    "final_content_length": len(final_content),
                    "has_img_tag": "<img" in final_content,
                    "has_data_image": "data:image" in final_content,
                    "molecular_images_count": len(molecular_images),
                    "task_type": task_type,
                },
                "timestamp": int(time.time() * 1000),
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "A"
            }) + "\n")
    except: pass
    # #endregion
    return {
        "final_report": final_content,
        "messages": [AIMessage(content=final_content, name="reporter")],
        "molecular_images": molecular_images,  # Preserve images for frontend
    }


def research_team_node(state: State):
    """Research team node that collaborates on tasks."""
    logger.info("Research team is collaborating on tasks.")
    pass


def _parse_hpc_config_from_completed_steps(completed_steps: list) -> dict:
    """
    Parse vaspilot_get_hpc_config result from completed steps' execution_res.
    Returns dict with host, username, remote_work_dir (from work_dir), port, key_path for submit_to_hpc.
    """
    def _extract_obj(text: str):
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _to_hpc_args(obj: dict) -> dict:
        if not isinstance(obj, dict) or not obj.get("host") or not obj.get("username"):
            return {}
        return {
            "host": str(obj.get("host", "")).strip(),
            "username": str(obj.get("username", "")).strip(),
            "remote_work_dir": str(obj.get("work_dir") or obj.get("remote_work_dir") or "").strip(),
            "port": int(obj.get("port", 22)) if obj.get("port") else 22,
            "key_path": (str(obj.get("key_path", "")).strip() or None),
        }

    for step in reversed(completed_steps):
        if not getattr(step, "execution_res", None):
            continue
        text = step.execution_res.strip()
        try:
            # Try whole text as JSON first
            obj = json.loads(repair_json_output(text))
            out = _to_hpc_args(obj)
            if out:
                return out
            # Try first brace-balanced {...} in text
            snippet = _extract_obj(text)
            if snippet:
                obj = json.loads(repair_json_output(snippet))
                out = _to_hpc_args(obj)
                if out:
                    return out
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return {}


def _parse_files_from_completed_steps(completed_steps: list) -> dict | None:
    """
    Parse generate_inputs result (top-level "files" dict) from completed steps' execution_res.
    Returns the "files" dict if found (must contain submit.sh), else None.
    Handles JSON string, Python dict string, and <finding>...</finding> wrapped content.
    """
    import ast

    def _extract_obj(text: str):
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _parse_obj(snippet: str) -> dict | None:
        if not snippet or not snippet.strip():
            return None
        try:
            obj = json.loads(repair_json_output(snippet))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        try:
            obj = ast.literal_eval(snippet)
            if isinstance(obj, dict):
                return obj
        except (ValueError, SyntaxError, TypeError):
            pass
        return None

    for step in reversed(completed_steps):
        if not getattr(step, "execution_res", None):
            continue
        text = (step.execution_res or "").strip()
        if not text:
            continue
        # Strip <finding>...</finding> if present
        if "<finding>" in text and "</finding>" in text:
            start = text.find("<finding>") + len("<finding>")
            end = text.find("</finding>")
            if end > start:
                text = text[start:end].strip()
        # Try whole text first
        obj = _parse_obj(text)
        if obj:
            files = obj.get("files")
            if isinstance(files, dict) and files.get("submit.sh"):
                return files
        # Try first brace-balanced {...}
        snippet = _extract_obj(text)
        if snippet:
            obj = _parse_obj(snippet)
            if obj:
                files = obj.get("files")
                if isinstance(files, dict) and files.get("submit.sh"):
                    return files
    return None


def _parse_poscar_from_completed_steps(completed_steps: list) -> str | None:
    """
    Parse load_structure result (poscar_content) from the first completed step's execution_res.
    Returns poscar_content string or None.
    """
    if not completed_steps:
        return None
    step = completed_steps[0]
    text = (getattr(step, "execution_res", None) or "").strip()
    if not text:
        return None
    if "<finding>" in text and "</finding>" in text:
        start = text.find("<finding>") + len("<finding>")
        end = text.find("</finding>")
        if end > start:
            text = text[start:end].strip()
    try:
        obj = json.loads(repair_json_output(text))
        if isinstance(obj, dict) and obj.get("poscar_content"):
            return str(obj["poscar_content"]).strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(repair_json_output(text[start : i + 1]))
                        if isinstance(obj, dict) and obj.get("poscar_content"):
                            return str(obj["poscar_content"]).strip()
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                    break
    return None


def _parse_submit_result_from_completed_steps(completed_steps: list) -> dict:
    """
    Parse submit_to_hpc result (job_id, remote_dir, etc.) from a completed step's execution_res.
    execution_res 可能为：纯 JSON；或「display 文本 + --- 提交结果 ---\\n + JSON + --- LLM 总结 --- + ...」。
    Prefers a step that has remote_dir (submit result); fallback to any step with job_id.
    Returns dict with job_id, remote_dir, host, username, port, key_path, remote_work_dir (or work_dir).
    """
    def _extract_obj(text: str):
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _extract_submit_json(text: str) -> str | None:
        """若 execution_res 含「--- 提交结果 ---」，则提取其后到「--- LLM 总结 ---」或结尾的 JSON 片段。"""
        marker = "--- 提交结果 ---"
        if marker not in text:
            return None
        start = text.find(marker) + len(marker)
        rest = text[start:].lstrip()
        end_marker = "\n\n--- LLM 总结 ---"
        if end_marker in rest:
            rest = rest[: rest.find(end_marker)]
        return rest.strip()

    def _to_out(obj: dict) -> dict:
        return {
            "job_id": str(obj.get("job_id", "")).strip() or None,
            "remote_dir": str(obj.get("remote_dir", "")).strip() or None,
            "host": str(obj.get("host", "")).strip() or None,
            "username": str(obj.get("username", "")).strip() or None,
            "port": int(obj.get("port", 22)) if obj.get("port") else 22,
            "key_path": (str(obj.get("key_path", "")).strip() or None),
            "remote_work_dir": str(obj.get("remote_work_dir") or obj.get("work_dir") or "").strip() or None,
        }

    best = {}
    for step in reversed(completed_steps):
        text = (getattr(step, "execution_res", None) or "").strip()
        if not text:
            continue
        json_str = _extract_submit_json(text)
        if json_str is None:
            json_str = text
        try:
            obj = json.loads(repair_json_output(json_str))
            if not isinstance(obj, dict):
                snippet = _extract_obj(json_str)
                if snippet:
                    obj = json.loads(repair_json_output(snippet))
                else:
                    continue
            if not isinstance(obj, dict):
                continue
            remote_dir = obj.get("remote_dir")
            job_id = obj.get("job_id")
            if remote_dir and (obj.get("host") or obj.get("username")):
                return _to_out(obj)
            if job_id or remote_dir:
                best = _to_out(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return best


async def _execute_agent_step(
    state: State, agent, agent_name: str, *, next_goto: str = "research_team"
) -> Command[Literal["research_team", "vasp_team"]]:
    """Helper function to execute a step using the specified agent. next_goto: next node after step (research_team or vasp_team)."""
    current_plan = state.get("current_plan")
    plan_title = current_plan.title
    observations = state.get("observations", [])

    # Find the first unexecuted step
    current_step = None
    completed_steps = []
    # #region debug log
    import time
    debug_log_path = "/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log"
    try:
        with open(debug_log_path, "a") as f:
            f.write(json.dumps({
                "location": "nodes.py:_execute_agent_step:1057",
                "message": "Finding unexecuted step",
                "data": {
                    "total_steps": len(current_plan.steps),
                    "step_titles": [s.title for s in current_plan.steps],
                    "step_execution_status": [bool(s.execution_res) for s in current_plan.steps],
                },
                "timestamp": int(time.time() * 1000),
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "A"
            }) + "\n")
    except: pass
    # #endregion
    for step in current_plan.steps:
        if not step.execution_res:
            current_step = step
            break
        else:
            completed_steps.append(step)

    if not current_step:
        logger.warning("No unexecuted step found")
        # #region debug log
        try:
            with open(debug_log_path, "a") as f:
                f.write(json.dumps({
                    "location": "nodes.py:_execute_agent_step:1065",
                    "message": "No unexecuted step found - all steps completed",
                    "data": {"completed_steps_count": len(completed_steps)},
                    "timestamp": int(__import__("time").time() * 1000),
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A"
                }) + "\n")
        except: pass
        # #endregion
        return Command(goto=next_goto)

    logger.info(f"Executing step: {current_step.title}, agent: {agent_name}")
    # #region debug log
    try:
        with open(debug_log_path, "a") as f:
            f.write(json.dumps({
                "location": "nodes.py:_execute_agent_step:1068",
                "message": "Executing step",
                "data": {
                    "step_title": current_step.title,
                    "step_description": current_step.description[:200],
                    "agent_name": agent_name,
                    "completed_steps_count": len(completed_steps),
                },
                "timestamp": int(__import__("time").time() * 1000),
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "A"
            }) + "\n")
    except: pass
    # #endregion

    # Format completed steps information
    completed_steps_info = ""
    if completed_steps:
        # Log what will be passed to next LLM call
        logger.info(f"=== COMPLETED STEPS INFO (will be passed to LLM) ===")
        for i, step in enumerate(completed_steps):
            exec_res_length = len(step.execution_res) if step.execution_res else 0
            exec_res_preview = step.execution_res[:200] if step.execution_res else "None"
            logger.info(f"Step {i+1}: {step.title}, execution_res length={exec_res_length}")
            logger.info(f"  Preview: {exec_res_preview}")
            if step.execution_res and 'base64' in step.execution_res.lower():
                logger.warning(f"  ⚠️  execution_res contains 'base64' keyword!")
        logger.info(f"=== END COMPLETED STEPS INFO ===")
        
        completed_steps_info = "# Completed Research Steps\n\n"
        for i, step in enumerate(completed_steps):
            completed_steps_info += f"## Completed Step {i + 1}: {step.title}\n\n"
            completed_steps_info += f"<finding>\n{step.execution_res}\n</finding>\n\n"

    # Prepare the input for the agent with completed steps info
    # CRITICAL: Emphasize that agent should ONLY execute the current step
    step_boundary_warning = "\n\n**CRITICAL STEP BOUNDARY**:\n- You are working on **ONE STEP ONLY** at a time\n- Focus **ONLY** on the current step's description below\n- Do **NOT** execute tools for other steps\n- Do **NOT** mix tasks from different steps\n- Execute tools **ONLY** as specified in the current step description\n"
    
    agent_input = {
        "messages": [
            HumanMessage(
                content=f"# Research Topic\n\n{plan_title}\n\n{completed_steps_info}{step_boundary_warning}# Current Step\n\n## Title\n\n{current_step.title}\n\n## Description\n\n{current_step.description}\n\n## Locale\n\n{state.get('locale', 'en-US')}"
            )
        ]
    }

    # For vasp_executor: include last user message so agent sees POSCAR/attachment and request
    if agent_name == "vasp_executor":
        for m in reversed(state.get("messages", [])):
            if isinstance(m, HumanMessage) and m.content:
                agent_input["messages"].insert(0, m)
                break
        # 组合步刚执行完：注入组合结果，由 LLM 总结/补充后再写 execution_res
        if state.get("vasp_post_composite") and state.get("vasp_composite_result"):
            agent_input["messages"].append(
                HumanMessage(
                    content="【组合步骤已执行】请根据下方组合步骤结果做简要总结或补充说明，完成后本步即完成。\n\n" + state["vasp_composite_result"],
                    name="vasp_composite",
                )
            )
        # Inject HPC args for any step that may call submit/job_status/fetch_logs/download (all need host/username)
        step_desc_lower = ((current_step.title or "") + " " + (current_step.description or "")).lower()
        needs_hpc = (
            "submit" in step_desc_lower or "提交" in step_desc_lower
            or "vaspilot_submit_to_hpc" in step_desc_lower
            or "vaspilot_job_status" in step_desc_lower
            or "vaspilot_fetch_job_logs" in step_desc_lower
            or "vaspilot_download_remote_file" in step_desc_lower
            or "监控" in (current_step.title or "") or "监控" in (current_step.description or "")
            or "下载" in (current_step.title or "") or "下载" in (current_step.description or "")
        )
        if needs_hpc:
            hpc_args = _parse_hpc_config_from_completed_steps(completed_steps)
            if hpc_args:
                # Append to the main instruction message (the one with Current Step), not the user message
                main_idx = 1 if len(agent_input["messages"]) > 1 else 0
                main_msg = agent_input["messages"][main_idx]
                if isinstance(main_msg, HumanMessage):
                    extra = (
                        "\n\n**MANDATORY HPC parameters** (from vaspilot_get_hpc_config). "
                        "You MUST pass these for vaspilot_submit_to_hpc, vaspilot_job_status, vaspilot_fetch_job_logs, vaspilot_download_remote_file:\n"
                        f"- host={repr(hpc_args.get('host', ''))}\n"
                        f"- username={repr(hpc_args.get('username', ''))}\n"
                        f"- remote_work_dir={repr(hpc_args.get('remote_work_dir', ''))} (use for submit_to_hpc and download)\n"
                        f"- port={hpc_args.get('port', 22)}\n"
                    )
                    if hpc_args.get("key_path"):
                        extra += f"- key_path={repr(hpc_args['key_path'])}\n"
                    else:
                        extra += "- password=\"__use_config__\" (use when key_path not set)\n"
                    extra += (
                        "vaspilot_submit_to_hpc: pass files, host, username, remote_work_dir, port, key_path or password. "
                        "vaspilot_job_status: pass job_id (from submit result), host, username, port, key_path or password. "
                        "vaspilot_fetch_job_logs / vaspilot_download_remote_file: same host/username/key_path."
                    )
                    agent_input["messages"][main_idx] = HumanMessage(content=main_msg.content + extra)
        # 第 4 步生成能带图：上一步已把 vasprun/kpoints 存入 state，画图时自动注入；提示 LLM 直接调用即可
        needs_band_plot = (
            "vaspilot_plot_band_structure" in step_desc_lower
            or "生成能带图" in (current_step.title or "")
            or "能带图" in (current_step.description or "")
        )
        if needs_band_plot and state.get("vasp_vasprun_xml_content"):
            main_idx = 1 if len(agent_input["messages"]) > 1 else 0
            main_msg = agent_input["messages"][main_idx]
            if isinstance(main_msg, HumanMessage):
                band_hint = (
                    "\n\n**生成能带图**：上一步已下载 vasprun.xml 与 KPOINTS，内容已缓存。"
                    "请直接调用 vaspilot_plot_band_structure，vasprun_xml_content 与 kpoints_content 可传空字符串 \"\"，系统将自动注入。"
                    "可选传 output_dir 指定图片保存目录（如 band_workflow_out）。"
                )
                agent_input["messages"][main_idx] = HumanMessage(content=main_msg.content + band_hint)
    # Add citation reminder for researcher agent
    if agent_name == "researcher":
        if state.get("resources"):
            resources_info = "**The user mentioned the following resource files:**\n\n"
            for resource in state.get("resources"):
                resources_info += f"- {resource.title} ({resource.description})\n"

            agent_input["messages"].append(
                HumanMessage(
                    content=resources_info
                    + "\n\n"
                    + "You MUST use the **local_search_tool** to retrieve the information from the resource files.",
                )
            )

        agent_input["messages"].append(
            HumanMessage(
                content="IMPORTANT: DO NOT include inline citations in the text. Instead, track all sources and include a References section at the end using link reference format. Include an empty line between each citation for better readability. Use this format for each reference:\n- [Source Title](URL)\n\n- [Another Source](URL)",
                name="system",
            )
        )

    # Invoke the agent
    default_recursion_limit = 25
    try:
        env_value_str = os.getenv("AGENT_RECURSION_LIMIT", str(default_recursion_limit))
        parsed_limit = int(env_value_str)

        if parsed_limit > 0:
            recursion_limit = parsed_limit
            logger.info(f"Recursion limit set to: {recursion_limit}")
        else:
            logger.warning(
                f"AGENT_RECURSION_LIMIT value '{env_value_str}' (parsed as {parsed_limit}) is not positive. "
                f"Using default value {default_recursion_limit}."
            )
            recursion_limit = default_recursion_limit
    except ValueError:
        raw_env_value = os.getenv("AGENT_RECURSION_LIMIT")
        logger.warning(
            f"Invalid AGENT_RECURSION_LIMIT value: '{raw_env_value}'. "
            f"Using default value {default_recursion_limit}."
        )
        recursion_limit = default_recursion_limit

    logger.info(f"Agent input: {agent_input}")
    try:
        result = await agent.ainvoke(
            input=agent_input, config={"recursion_limit": recursion_limit}
        )

        # vasp_executor: 若本轮有 job_status 返回 FAILED 且 exit_code==1，自动从服务端拉取错误日志并再跑一轮 LLM 分析
        if agent_name == "vasp_executor" and result.get("messages"):
            tool_id_to_name = {}
            for m in result["messages"]:
                if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                        tname = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        if tid:
                            tool_id_to_name[tid] = tname
            job_status_failed = False
            for m in result["messages"]:
                if isinstance(m, ToolMessage):
                    tid = getattr(m, "tool_call_id", None)
                    tname = (tool_id_to_name.get(tid, "") if tid else "") or ""
                    if tname == "vaspilot_job_status":
                        try:
                            data = json.loads(repair_json_output(str(m.content)))
                            if data.get("status") == "FAILED" and data.get("exit_code") == 1:
                                job_status_failed = True
                                break
                        except (json.JSONDecodeError, ValueError, TypeError):
                            pass
            if job_status_failed:
                submit_info = _parse_submit_result_from_completed_steps(completed_steps)
                job_id = submit_info.get("job_id")
                remote_dir = submit_info.get("remote_dir")
                host = submit_info.get("host")
                username = submit_info.get("username")
                if job_id and remote_dir and host and username:
                    try:
                        from src.server.app import TOOL_REGISTRY
                        fetch_tool = TOOL_REGISTRY.get("vaspilot_fetch_job_logs")
                        if fetch_tool:
                            logs_out = fetch_tool.invoke({
                                "job_id": str(job_id),
                                "remote_dir": remote_dir,
                                "host": host,
                                "username": username,
                                "port": submit_info.get("port", 22),
                                "key_path": submit_info.get("key_path") or "",
                                "password": "__use_config__",
                            })
                            if isinstance(logs_out, str):
                                try:
                                    logs_out = json.loads(repair_json_output(logs_out))
                                except Exception:
                                    logs_out = {"raw": logs_out}
                            logs_str = json.dumps(logs_out, ensure_ascii=False, indent=2)
                            follow_up_messages = list(agent_input["messages"]) + list(result["messages"]) + [
                                HumanMessage(
                                    content="【系统】作业状态为 FAILED（退出码 1），已从服务端拉取错误日志。请根据以下内容分析失败原因、定位问题并告知用户。\n\n" + logs_str,
                                    name="system",
                                )
                            ]
                            result = await agent.ainvoke(
                                input={"messages": follow_up_messages},
                                config={"recursion_limit": recursion_limit},
                            )
                            logger.info("VASP: auto fetch_job_logs done, LLM re-invoked for failure analysis")
                    except Exception as e:
                        logger.exception("VASP auto fetch_job_logs failed: %s", e)

        # Log all messages returned from agent
        logger.info(f"=== AGENT RESULT MESSAGES ANALYSIS ===")
        for idx, msg in enumerate(result['messages']):
            msg_type = type(msg).__name__
            content_length = len(str(msg.content)) if hasattr(msg, 'content') else 0
            logger.info(f"Message {idx}: Type={msg_type}, ContentLength={content_length}")
            
            # For ToolMessage, log first 200 chars
            if msg_type == 'ToolMessage':
                content_preview = str(msg.content)[:200]
                logger.info(f"  ToolMessage preview: {content_preview}")
                # Check if contains base64 data
                if 'base64' in str(msg.content).lower():
                    logger.warning(f"  ⚠️  ToolMessage contains 'base64' keyword!")
                if 'data:image' in str(msg.content):
                    logger.warning(f"  ⚠️  ToolMessage contains 'data:image' prefix!")
        logger.info(f"=== END AGENT RESULT MESSAGES ANALYSIS ===")
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        error_message = f"Error executing {agent_name} agent for step '{current_step.title}': {str(e)}"
        logger.exception(error_message)
        logger.error(f"Full traceback:\n{error_traceback}")
        
        detailed_error = f"[ERROR] {agent_name.capitalize()} Agent Error\n\nStep: {current_step.title}\n\nError Details:\n{str(e)}\n\nPlease check the logs for more information."
        current_step.execution_res = detailed_error
        
        return Command(
            update={
                "messages": [
                    HumanMessage(
                        content=detailed_error,
                        name=agent_name,
                    )
                ],
                "observations": observations + [detailed_error],
            },
            goto=next_goto,
        )

    # Extract molecular images from ToolMessages (avoiding base64 in LLM context)
    molecular_images = state.get("molecular_images", [])
    logger.info(f"=== EXTRACTING MOLECULAR IMAGES ===")
    logger.info(f"Current molecular_images count: {len(molecular_images)}")
    logger.info(f"Result messages count: {len(result['messages'])}")

    # Prepare holders for URL and SMILES summary
    extracted_img_url = ""
    extracted_summary = ""

    try:
        import re

        # Search for image ID marker in ToolMessages
        image_id_pattern = re.compile(r'<!-- MOLECULAR_IMAGE_ID:([a-f0-9\-]+) -->')

        for idx, msg in enumerate(result['messages']):
            if type(msg).__name__ == 'ToolMessage':
                text = str(msg.content)
                match = image_id_pattern.search(text)

                if match:
                    image_id = match.group(1)
                    logger.info(f"Found image marker in ToolMessage {idx}: {image_id}")

                    # Directly construct public URL without reading JSON
                    extracted_img_url = f"/molecular_images/{image_id}.svg"
                    molecular_images.append({
                        "id": image_id,
                        "url": extracted_img_url,
                    })
                    logger.info(f"Image URL: {extracted_img_url}")

                    # Extract the full summary from visualize_molecules output (before cleaning)
                    # The summary contains all SMILES info
                    extracted_summary = image_id_pattern.sub('', text).strip()
                    logger.info(f"Extracted summary (first 200 chars): {extracted_summary[:200]}")

                    # Clean marker from ToolMessage to avoid LLM seeing it in context
                    msg.content = extracted_summary
                    logger.info(f"✓ Cleaned marker from ToolMessage {idx}")

    except Exception as e:
        logger.warning(f"Error extracting molecular images: {e}")
    
    logger.info(f"Final molecular_images count: {len(molecular_images)}")
    logger.info(f"=== END EXTRACTING MOLECULAR IMAGES ===")
    
    # Process the result - prioritize ToolMessage content over AIMessage content
    logger.info(f"=== PROCESSING AGENT RESULT ===")
    
    # Collect all ToolMessage contents (actual tool execution results)
    tool_results = []
    # #region debug log
    try:
        import time
        with open("/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log", "a") as f:
            f.write(json.dumps({
                "location": "nodes.py:_execute_agent_step:1242",
                "message": "Processing tool results",
                "data": {
                    "total_messages": len(result['messages']),
                    "message_types": [type(m).__name__ for m in result['messages']],
                    "agent_name": agent_name,
                    "step_title": current_step.title,
                },
                "timestamp": int(time.time() * 1000),
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "B"
            }) + "\n")
    except: pass
    # #endregion
    for idx, msg in enumerate(result['messages']):
        if isinstance(msg, ToolMessage):
            tool_content = str(msg.content)
            tool_results.append(tool_content)
            logger.info(f"Found ToolMessage {idx}: length={len(tool_content)}, preview={tool_content[:200]}")
            # #region debug log
            try:
                import time
                with open("/Users/carl/workspace/tools/AgenticWorkflow/.cursor/debug.log", "a") as f:
                    f.write(json.dumps({
                        "location": "nodes.py:_execute_agent_step:1247",
                        "message": "Found ToolMessage",
                        "data": {
                            "tool_call_id": getattr(msg, 'tool_call_id', None),
                            "content_length": len(tool_content),
                            "content_preview": tool_content[:100],
                            "step_title": current_step.title,
                        },
                        "timestamp": int(time.time() * 1000),
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B"
                    }) + "\n")
            except: pass
            # #endregion
    
    # Get the last message content (usually AIMessage if no tools, or final response)
    response_content = result["messages"][-1].content
    logger.debug(f"{agent_name.capitalize()} full response: {response_content}")
    
    # Check if response_content contains tool call markers (indicates tool wasn't executed)
    tool_call_marker_pattern = r'<\|FunctionCallBegin\|>.*?<\|FunctionCallEnd\|>'
    import re
    has_tool_call_markers = bool(re.search(tool_call_marker_pattern, str(response_content), re.DOTALL))
    
    logger.info(f"ToolMessage count: {len(tool_results)}")
    logger.info(f"Has tool call markers: {has_tool_call_markers}")
    
    # Update the step with the execution result
    # Priority: 1) ToolMessage results, 2) Extracted summary from images, 3) Response content
    # 若为组合步后的 LLM 参与轮：合并组合结果与 LLM 输出后写 execution_res，并清除 post_composite 标志
    if agent_name == "vasp_executor" and state.get("vasp_post_composite") and state.get("vasp_composite_result"):
        composite_res = state["vasp_composite_result"]
        gen_display = (state.get("vasp_gen_display") or "").strip()
        llm_part = ("\n\n".join(tool_results) if tool_results else response_content) or "(LLM 已确认)"
        if gen_display:
            current_step.execution_res = gen_display + "\n\n--- 提交结果 ---\n" + composite_res.rstrip() + "\n\n--- LLM 总结 ---\n" + str(llm_part)
        else:
            current_step.execution_res = composite_res.rstrip() + "\n\n--- LLM 总结 ---\n" + str(llm_part)
        logger.info("VASP post_composite: set execution_res from composite + LLM summary (with gen_display=%s)", bool(gen_display))
        return Command(
            update={
                "messages": [
                    HumanMessage(
                        content=current_step.execution_res,
                        name=agent_name,
                    )
                ],
                "observations": observations + [current_step.execution_res],
                "molecular_images": molecular_images,
                "vasp_post_composite": False,
                "vasp_composite_result": None,
                "vasp_gen_display": None,
            },
            goto=next_goto,
        )

    logger.info(f"=== SETTING execution_res ===")
    logger.info(f"molecular_images count: {len(molecular_images)}")
    
    # 第 3 步 vaspilot_wait_and_download_band 返回含整份 vasprun，不写入 execution_res/消息，避免上下文爆炸；存摘要 + state 供第 4 步注入
    if tool_results and agent_name == "vasp_executor" and len(tool_results) == 1:
        raw = (tool_results[0] or "").strip()
        try:
            data = json.loads(repair_json_output(raw))
        except (json.JSONDecodeError, ValueError, TypeError):
            data = None
        if isinstance(data, dict) and data.get("status") == "COMPLETED" and "vasprun_xml_content" in data:
            vasprun_content = data.get("vasprun_xml_content") or ""
            kpoints_content = data.get("kpoints_content") or ""
            summary = {
                "status": "COMPLETED",
                "job_id": data.get("job_id"),
                "vasprun_length": len(vasprun_content),
                "kpoints_length": len(kpoints_content),
                "note": "vasprun 与 KPOINTS 已存入 state，下一步「生成能带图」将自动注入 vaspilot_plot_band_structure，无需在 prompt 中传递大内容。",
            }
            current_step.execution_res = json.dumps(summary, ensure_ascii=False)
            logger.info(
                "VASP step3 (wait_and_download_band): stored summary in execution_res, vasprun len=%s kpoints len=%s in state",
                len(vasprun_content), len(kpoints_content),
            )
            return Command(
                update={
                    "messages": [
                        HumanMessage(content=current_step.execution_res, name=agent_name),
                    ],
                    "observations": observations + [current_step.execution_res],
                    "molecular_images": molecular_images,
                    "vasp_vasprun_xml_content": vasprun_content,
                    "vasp_kpoints_content": kpoints_content,
                },
                goto=next_goto,
            )

    if tool_results:
        # Use ToolMessage results (actual tool execution results)
        # Join all tool results with newlines
        all_tool_results = "\n\n".join(tool_results)
        logger.info(f"Using ToolMessage results (total length: {len(all_tool_results)})")
        logger.info(f"ToolMessage results preview: {all_tool_results[:500]}")
        
        # If we have images, combine with image summary
        if molecular_images and extracted_summary:
            img_url = extracted_img_url or molecular_images[0].get('url', '')
            uuid_match = re.search(r'([a-f0-9\-]+)\.svg$', img_url)
            if uuid_match:
                uuid = uuid_match.group(1)
                detailed_summary = f"{all_tool_results}\n\nMOLECULAR_IMAGE_ID: {uuid}"
            else:
                detailed_summary = f"{all_tool_results}\n\n{extracted_summary}"
            current_step.execution_res = detailed_summary
        else:
            current_step.execution_res = all_tool_results
    elif molecular_images and extracted_summary:
        # Use the summary directly from visualize_molecules (contains SMILES)
        # Add UUID for image embedding
        img_url = extracted_img_url or molecular_images[0].get('url', '')
        
        # Extract UUID from URL
        uuid_match = re.search(r'([a-f0-9\-]+)\.svg$', img_url)
        if uuid_match:
            uuid = uuid_match.group(1)
            detailed_summary = f"{extracted_summary}\n\nMOLECULAR_IMAGE_ID: {uuid}"
        else:
            detailed_summary = extracted_summary
            logger.warning(f"Could not extract UUID from URL: {img_url}")
        
        logger.info(f"Using summary from visualize_molecules with img URL: {img_url}")
        logger.info(f"Full detailed_summary content:\n{detailed_summary}")
        current_step.execution_res = detailed_summary
    else:
        # Use response content as fallback
        logger.info(f"Using response_content length: {len(response_content)}")
        logger.info(f"Response content preview: {response_content[:200]}")
        if 'base64' in response_content.lower():
            logger.warning(f"  ⚠️  response_content contains 'base64' keyword!")
        if has_tool_call_markers:
            logger.warning(f"  ⚠️  response_content contains tool call markers - tool may not have been executed!")
        current_step.execution_res = response_content
    logger.info(f"=== END SETTING execution_res ===")
    
    logger.info(f"Step '{current_step.title}' execution completed by {agent_name}")

    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=current_step.execution_res,
                    name=agent_name,
                )
            ],
            "observations": observations + [current_step.execution_res],
            "molecular_images": molecular_images,
        },
        goto=next_goto,
    )


async def _setup_and_execute_agent_step(
    state: State,
    config: RunnableConfig,
    agent_type: str,
    default_tools: list,
    *,
    next_goto: str = "research_team",
) -> Command[Literal["research_team", "vasp_team"]]:
    """Helper function to set up an agent with appropriate tools and execute a step.

    This function handles the common logic for researcher_node, coder_node, and vasp_executor_node:
    1. Configures MCP servers and tools based on agent type
    2. Creates an agent with the appropriate tools or uses the default agent
    3. Executes the agent on the current step

    Args:
        state: The current state
        config: The runnable config
        agent_type: The type of agent ("researcher", "coder", or "vasp_executor")
        default_tools: The default tools to add to the agent
        next_goto: Next node after step ("research_team" or "vasp_team")

    Returns:
        Command to update state and go to next_goto
    """
    configurable = Configuration.from_runnable_config(config)
    mcp_servers = {}
    enabled_tools = {}

    # Extract MCP server configuration for this agent type
    if configurable.mcp_settings:
        for server_name, server_config in configurable.mcp_settings["servers"].items():
            if (
                server_config["enabled_tools"]
                and agent_type in server_config["add_to_agents"]
            ):
                mcp_servers[server_name] = {
                    k: v
                    for k, v in server_config.items()
                    if k in ("transport", "command", "args", "url", "env", "headers")
                }
                for tool_name in server_config["enabled_tools"]:
                    enabled_tools[tool_name] = server_name

    # Create and execute agent with MCP tools if available
    if mcp_servers:
        client = MultiServerMCPClient(mcp_servers)
        loaded_tools = default_tools[:]
        all_tools = await client.get_tools()
        for tool in all_tools:
            if tool.name in enabled_tools:
                tool.description = (
                    f"Powered by '{enabled_tools[tool.name]}'.\n{tool.description}"
                )
                loaded_tools.append(tool)

        llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP[agent_type])
        pre_model_hook = partial(ContextManager(llm_token_limit, 3).compress_messages)
        selected_model = configurable.selected_model if configurable else None
        agent = create_agent(
            agent_type, agent_type, loaded_tools, agent_type, pre_model_hook, selected_model
        )
        return await _execute_agent_step(state, agent, agent_type, next_goto=next_goto)
    else:
        # Use default tools if no MCP servers are configured
        llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP[agent_type])
        pre_model_hook = partial(ContextManager(llm_token_limit, 3).compress_messages)
        selected_model = configurable.selected_model if configurable else None
        agent = create_agent(
            agent_type, agent_type, default_tools, agent_type, pre_model_hook, selected_model
        )
        return await _execute_agent_step(state, agent, agent_type, next_goto=next_goto)


async def researcher_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Researcher node that do research"""
    logger.info("Researcher node is researching.")
    configurable = Configuration.from_runnable_config(config)
    
    # logger.info(f"Current research_mode: {configurable.research_mode}")
    # logger.info(f"Configuration details: max_iterations={configurable.max_research_iterations}, literature_focus={configurable.literature_focus}")
    
    # Check if deep research mode is enabled
    if configurable.research_mode == "deep_research":
        logger.info("Using deep research mode")
        return await _execute_deep_research(state, config, configurable)
    else:
        logger.info("Using standard research mode")
        return await _execute_standard_research(state, config, configurable)


async def _execute_deep_research(
    state: State, config: RunnableConfig, configurable: Configuration
) -> Command[Literal["research_team"]]:
    """Execute deep research using iterative engine"""
    
    logger.info("Starting deep research execution")
    
    # Get current step
    current_plan = state.get("current_plan")
    if not current_plan:
        logger.error("No current plan found for deep research")
        return Command(goto="research_team")
    
    logger.info(f"Current plan: {current_plan.title}")
    
    # Find the first unexecuted step
    current_step = None
    for step in current_plan.steps:
        if not step.execution_res:
            current_step = step
            break
    
    if not current_step:
        logger.warning("No unexecuted step found for deep research")
        return Command(goto="research_team")
    
    logger.info(f"Executing step: {current_step.title}")
    
    # 构建新的工具集：knowledge_base, web_search, arxiv_search, fetch_pdf_text
    tools = []
    
    # 1. 知识库工具（如果存在 resources，优先级最高）
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.append(retriever_tool)
        logger.info("Added knowledge base tool (retriever_tool)")
    
    # 2. 网络搜索与 arXiv 文献检索（已完全替代 google_scholar）
    try:
        tools.append(get_web_search_tool(configurable.max_search_results))
        tools.append(get_arxiv_search_tool(configurable.max_search_results))
        logger.info("Added web_search and arxiv_search tools")
    except Exception as e:
        logger.warning("Failed to add web_search/arxiv_search tools: %s", e)
    
    # 3. PDF 提取工具
    tools.append(fetch_pdf_text)
    logger.info("Added fetch_pdf_text tool")
    
    # 4. Python REPL 工具（数据分析，deep research 模式下必需）
    if python_repl_tool not in tools:
        # 检查工具是否启用（deep research 模式必需）
        from src.tools.python_repl import _is_python_repl_enabled
        if not _is_python_repl_enabled():
            logger.warning("Python REPL tool is disabled in configuration, but it's required for deep research mode.")
            logger.warning("Please enable it in conf.yaml (PYTHON_REPL.enabled: true) or set ENABLE_PYTHON_REPL=true environment variable.")
            # 临时启用 Python REPL（deep research 模式强制启用）
            import os
            os.environ["ENABLE_PYTHON_REPL"] = "true"
            logger.info("Temporarily enabled Python REPL for deep research mode (via environment variable)")
        tools.append(python_repl_tool)
        logger.info(f"Added python_repl_tool (enabled: {_is_python_repl_enabled()})")
    
    logger.info(f"Final tools list: {[t.name for t in tools]}")
    
    # Get LLM for deep research
    llm = _get_llm_for_agent("researcher", config)
    
    # Create iterative research engine
    engine = IterativeResearchEngine(
        max_iterations=configurable.max_research_iterations,
        llm=llm,
        tools=tools,
        config=configurable
    )
    
    # Prepare step information
    step_info = {
        "title": current_step.title,
        "description": current_step.description,
        "research_topic": state.get("research_topic", ""),
        "locale": state.get("locale", "en-US")
    }
    
    # Execute iterative research with full plan context
    try:
        # 传递完整的plan上下文给引擎
        context = {
            'current_plan': current_plan,
            'research_topic': state.get("research_topic", ""),
            'locale': state.get("locale", "en-US"),
            'resources': state.get("resources", [])
        }
        result = await engine.iterate_research(step_info, context)
        
        if result.success:
            # Update step with execution result
            current_step.execution_res = result.final_report
            
            # Update state
            observations = state.get("observations", [])
            observations.append(result.final_report)
            
            logger.info(f"Deep research completed: {result.iteration_count} iterations, {len(result.tools_used)} tools used")
            
            return Command(
                update={
                    "messages": [
                        HumanMessage(
                            content=result.final_report,
                            name="researcher",
                        )
                    ],
                    "observations": observations,
                    "progressive_report": result.final_report,
                    "research_metadata": {
                        "iterations": result.iteration_count,
                        "tools_used": result.tools_used,
                        "mode": "deep_research"
                    }
                },
                goto="research_team",
            )
        else:
            # Handle error
            error_msg = f"Deep research failed: {result.error_message}"
            logger.error(error_msg)
            current_step.execution_res = error_msg
            
            return Command(
                update={
                    "messages": [
                        HumanMessage(
                            content=error_msg,
                            name="researcher",
                        )
                    ],
                    "observations": state.get("observations", []) + [error_msg],
                },
                goto="research_team",
            )
            
    except Exception as e:
        error_msg = f"Deep research engine error: {str(e)}"
        logger.error(error_msg)
        current_step.execution_res = error_msg
        
        return Command(
            update={
                "messages": [
                    HumanMessage(
                        content=error_msg,
                        name="researcher",
                    )
                ],
                "observations": state.get("observations", []) + [error_msg],
            },
            goto="research_team",
        )


async def _execute_standard_research(
    state: State, config: RunnableConfig, configurable: Configuration
) -> Command[Literal["research_team"]]:
    """Execute standard research (original logic)"""
    tools = [get_web_search_tool(configurable.max_search_results), crawl_tool]
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.insert(0, retriever_tool)
    # Add Python REPL tool for data analysis
    tools.append(python_repl_tool)
    logger.info(f"Researcher tools: {tools}")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "researcher",
        tools,
    )


async def coder_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Coder node that do code analysis."""
    logger.info("Coder node is coding.")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "coder",
        [python_repl_tool, generate_sam_molecules, visualize_molecules, predict_molecular_properties],
    )
