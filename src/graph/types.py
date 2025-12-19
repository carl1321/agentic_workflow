# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


from langgraph.graph import MessagesState

from src.prompts.planner_model import Plan
from src.rag import Resource


class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""

    # Runtime Variables
    locale: str = "en-US"
    research_topic: str = ""
    observations: list[str] = []
    resources: list[Resource] = []
    plan_iterations: int = 0
    current_plan: Plan | str = None
    final_report: str = ""
    auto_accepted_plan: bool = False
    enable_background_investigation: bool = False
    background_investigation_results: str = None

    # Clarification state tracking (disabled by default)
    enable_clarification: bool = (
        False  # Enable/disable clarification feature (default: False)
    )
    clarification_rounds: int = 0
    clarification_history: list[str] = []
    is_clarification_complete: bool = False
    clarified_question: str = ""
    max_clarification_rounds: int = (
        3  # Default: 3 rounds (only used when enable_clarification=True)
    )

    # Deep Research Mode state tracking
    research_mode: str = "standard"  # "standard" | "deep_research"
    current_research_iteration: int = 0
    progressive_report: str = ""  # Progressive knowledge synthesis
    research_metadata: dict = {}  # Iteration metadata (tools used, etc.)

    # Workflow control
    goto: str = "planner"  # Default next node
    
    # Molecular images storage (to avoid token waste)
    molecular_images: list[dict] = []  # Store molecular structure images