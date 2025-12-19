# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from functools import partial
from typing import Annotated, Any, Literal

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
from src.tools.literature_search import get_literature_research_tools
from src.tools.search import LoggedTavilySearch
from src.tools.deep_research import google_scholar
from src.utils.context_manager import ContextManager
from src.utils.json_utils import repair_json_output

from ..config import SELECTED_SEARCH_ENGINE, SearchEngine
from .deep_research_engine import IterativeResearchEngine
from .types import State

logger = logging.getLogger(__name__)


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
) -> Command[Literal["planner", "research_team", "reporter", "__end__"]]:
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
) -> Command[Literal["planner", "molecular_planner", "background_investigator", "coordinator", "__end__"]]:
    """Coordinator node that communicate with customers and handle clarification."""
    logger.info("Coordinator talking.")
    configurable = Configuration.from_runnable_config(config)

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
        tools = [handoff_to_planner, handoff_to_molecular_planner]
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
        tools = [handoff_to_planner, handoff_to_molecular_planner, handoff_after_clarification]
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


async def _execute_agent_step(
    state: State, agent, agent_name: str
) -> Command[Literal["research_team"]]:
    """Helper function to execute a step using the specified agent."""
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
        return Command(goto="research_team")

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
            goto="research_team",
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
    logger.info(f"=== SETTING execution_res ===")
    logger.info(f"molecular_images count: {len(molecular_images)}")
    
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
        goto="research_team",
    )


async def _setup_and_execute_agent_step(
    state: State,
    config: RunnableConfig,
    agent_type: str,
    default_tools: list,
) -> Command[Literal["research_team"]]:
    """Helper function to set up an agent with appropriate tools and execute a step.

    This function handles the common logic for both researcher_node and coder_node:
    1. Configures MCP servers and tools based on agent type
    2. Creates an agent with the appropriate tools or uses the default agent
    3. Executes the agent on the current step

    Args:
        state: The current state
        config: The runnable config
        agent_type: The type of agent ("researcher" or "coder")
        default_tools: The default tools to add to the agent

    Returns:
        Command to update state and go to research_team
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
        return await _execute_agent_step(state, agent, agent_type)
    else:
        # Use default tools if no MCP servers are configured
        llm_token_limit = get_llm_token_limit_by_type(AGENT_LLM_MAP[agent_type])
        pre_model_hook = partial(ContextManager(llm_token_limit, 3).compress_messages)
        selected_model = configurable.selected_model if configurable else None
        agent = create_agent(
            agent_type, agent_type, default_tools, agent_type, pre_model_hook, selected_model
        )
        return await _execute_agent_step(state, agent, agent_type)


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
    
    # 构建新的工具集：knowledge_base, google_scholar, fetch_pdf_text
    tools = []
    
    # 1. 知识库工具（如果存在 resources，优先级最高）
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.append(retriever_tool)
        logger.info("Added knowledge base tool (retriever_tool)")
    
    # 2. Google Scholar 工具（学术文献搜索）
    try:
        tools.append(google_scholar)
        logger.info("Added google_scholar tool")
    except Exception as e:
        logger.warning(f"Failed to add google_scholar tool: {e}")
    
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
