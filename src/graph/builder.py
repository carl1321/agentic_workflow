# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from src.config.loader import get_bool_env, get_str_env

from src.prompts.planner_model import StepType

logger = logging.getLogger(__name__)

from .nodes import (
    background_investigation_node,
    coder_node,
    common_reporter_node,
    coordinator_node,
    literature_answerer_node,
    literature_planner_node,
    literature_researcher_node,
    human_feedback_node,
    molecular_planner_node,
    planner_node,
    reporter_node,
    research_team_node,
    researcher_node,
)
from .types import State


def continue_to_running_research_team(state: State):
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        return "planner"

    # 检查是否所有步骤都已完成
    all_completed = all(step.execution_res for step in current_plan.steps)
    
    if all_completed:
        # 根据planner类型选择reporter
        messages = state.get("messages", [])
        
        # 检查是否是深度研究任务（使用标准planner）
        is_deep_research = False
        is_literature = False
        from langchain_core.messages import AIMessage
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, 'name'):
                name = getattr(msg, 'name', None)
                if name == "planner":
                    is_deep_research = True
                    break
                elif name == "molecular_planner":
                    # molecular_planner 总是用 common_reporter
                    return "common_reporter"
                elif name == "literature_planner":
                    is_literature = True
                    break
        
        # 文献问答用 literature_answerer，深度研究用 reporter，其他用 common_reporter
        if is_literature:
            return "literature_answerer"
        return "reporter" if is_deep_research else "common_reporter"

    # Find first incomplete step
    incomplete_step = None
    for step in current_plan.steps:
        if not step.execution_res:
            incomplete_step = step
            break

    if not incomplete_step:
        # 同样根据任务类型选择reporter
        messages = state.get("messages", [])
        is_deep_research = False
        is_literature = False
        
        from langchain_core.messages import AIMessage
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, 'name'):
                name = getattr(msg, 'name', None)
                if name == "planner":
                    is_deep_research = True
                    break
                elif name == "molecular_planner":
                    # molecular_planner 总是用 common_reporter
                    return "common_reporter"
                elif name == "literature_planner":
                    is_literature = True
                    break
        
        if is_literature:
            return "literature_answerer"
        return "reporter" if is_deep_research else "common_reporter"

    if incomplete_step.step_type == StepType.RESEARCH:
        # 文献流程走专用 researcher
        messages = state.get("messages", [])
        from langchain_core.messages import AIMessage
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, 'name', None) == "literature_planner":
                return "literature_researcher"
        return "researcher"
    if incomplete_step.step_type == StepType.PROCESSING:
        return "coder"
    return "planner"


def _build_base_graph():
    """Build and return the base state graph with all nodes and edges."""
    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("background_investigator", background_investigation_node)
    builder.add_node("planner", planner_node)
    builder.add_node("literature_planner", literature_planner_node)
    builder.add_node("molecular_planner", molecular_planner_node)
    builder.add_node("reporter", reporter_node)
    builder.add_node("common_reporter", common_reporter_node)
    builder.add_node("research_team", research_team_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("literature_researcher", literature_researcher_node)
    builder.add_node("coder", coder_node)
    builder.add_node("human_feedback", human_feedback_node)
    builder.add_edge("background_investigator", "planner")
    builder.add_conditional_edges(
        "research_team",
        continue_to_running_research_team,
        ["planner", "researcher", "coder", "reporter", "common_reporter"],
    )
    builder.add_edge("reporter", END)
    builder.add_edge("common_reporter", END)
    builder.add_node("literature_answerer", literature_answerer_node)
    builder.add_edge("literature_answerer", END)
    return builder


def build_graph_with_memory():
    """Build and return the agent workflow graph with memory."""
    # Use PostgreSQL checkpoint if enabled, otherwise use memory checkpoint
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    checkpoint_url = get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "")
    
    if checkpoint_saver and checkpoint_url and (
        checkpoint_url.startswith("postgresql://") or checkpoint_url.startswith("postgres://")
    ):
        # Use PostgreSQL checkpoint for persistence
        try:
            # Create async PostgreSQL checkpoint saver
            # Note: This requires async connection pool
            from psycopg_pool import AsyncConnectionPool
            connection_kwargs = {
                "autocommit": True,
                "row_factory": "dict_row",
                "prepare_threshold": 0,
            }
            pool = AsyncConnectionPool(
                checkpoint_url,
                min_size=1,
                max_size=10,
                kwargs=connection_kwargs,
            )
            checkpointer = AsyncPostgresSaver(pool)
            logger.info(f"Using PostgreSQL checkpoint: {checkpoint_url}")
        except Exception as e:
            logger.warning(f"Failed to initialize PostgreSQL checkpoint: {e}, falling back to MemorySaver")
            checkpointer = MemorySaver()
    else:
        # Use in-memory checkpoint (default)
        checkpointer = MemorySaver()
        if checkpoint_saver:
            logger.warning("Checkpoint saver enabled but no valid PostgreSQL URL provided, using MemorySaver")

    # build state graph
    builder = _build_base_graph()
    return builder.compile(checkpointer=checkpointer)


def build_graph():
    """Build and return the agent workflow graph without memory."""
    # build state graph
    builder = _build_base_graph()
    return builder.compile()


graph = build_graph()
