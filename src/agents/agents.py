# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.prebuilt import create_react_agent

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type, get_llm_by_model_name
from src.prompts import apply_prompt_template


# Create agents using configured LLM types
def create_agent(
    agent_name: str,
    agent_type: str,
    tools: list,
    prompt_template: str,
    pre_model_hook: callable = None,
    selected_model: str = None,
):
    """
    Factory function to create agents with consistent configuration.
    
    Only planner agents (planner, molecular_planner, literature_planner) can use selected_model.
    All other agents always use BASIC_MODEL.
    
    Args:
        agent_name: Name of the agent
        agent_type: Type of the agent
        tools: List of tools available to the agent
        prompt_template: Prompt template name
        pre_model_hook: Optional hook to call before model invocation
        selected_model: Optional model identifier to use. Only used for planner agents.
    """
    # Planner agents can use selected_model, others always use BASIC_MODEL
    planner_agents = ["planner", "molecular_planner", "literature_planner"]
    
    if agent_type in planner_agents:
        # Planner agents: use selected_model if available, otherwise use AGENT_LLM_MAP
        if selected_model:
            try:
                model = get_llm_by_model_name(selected_model)
            except ValueError:
                # Fall back to default if model not found
                model = get_llm_by_type(AGENT_LLM_MAP[agent_type])
        else:
            model = get_llm_by_type(AGENT_LLM_MAP[agent_type])
    else:
        # All other agents: always use BASIC_MODEL (ignores selected_model)
        model = get_llm_by_type(AGENT_LLM_MAP[agent_type])
    
    return create_react_agent(
        name=agent_name,
        model=model,
        tools=tools,
        prompt=lambda state: apply_prompt_template(prompt_template, state),
        pre_model_hook=pre_model_hook,
    )
