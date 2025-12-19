# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
from dataclasses import dataclass, field, fields
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from src.config.loader import get_bool_env, get_int_env, get_str_env, load_yaml_config
from src.config.report_style import ReportStyle
from src.rag.retriever import Resource

logger = logging.getLogger(__name__)


def get_recursion_limit(default: int = 25) -> int:
    """Get the recursion limit from environment variable or use default.

    Args:
        default: Default recursion limit if environment variable is not set or invalid

    Returns:
        int: The recursion limit to use
    """
    env_value_str = get_str_env("AGENT_RECURSION_LIMIT", str(default))
    parsed_limit = get_int_env("AGENT_RECURSION_LIMIT", default)

    if parsed_limit > 0:
        logger.info(f"Recursion limit set to: {parsed_limit}")
        return parsed_limit
    else:
        logger.warning(
            f"AGENT_RECURSION_LIMIT value '{env_value_str}' (parsed as {parsed_limit}) is not positive. "
            f"Using default value {default}."
        )
        return default


@dataclass(kw_only=True)
class Configuration:
    """The configurable fields."""

    resources: list[Resource] = field(
        default_factory=list
    )  # Resources to be used for the research
    max_plan_iterations: int = 1  # Maximum number of plan iterations
    max_step_num: int = 3  # Maximum number of steps in a plan
    max_search_results: int = 3  # Maximum number of search results
    mcp_settings: dict = None  # MCP settings, including dynamic loaded tools
    report_style: str = ReportStyle.ACADEMIC.value  # Report style
    enable_deep_thinking: bool = False  # Whether to enable deep thinking
    
    # Deep Research Mode Configuration
    research_mode: str = "standard"  # "standard" | "deep_research"
    max_research_iterations: int = 5  # Maximum number of research iterations
    enable_report_synthesis: bool = True  # Whether to enable progressive report synthesis
    literature_focus: bool = False  # Whether to prioritize academic tools
    context_compression: bool = True  # Whether to enable context compression
    selected_model: Optional[str] = None  # Selected model identifier for unified model usage

    @classmethod
    def from_runnable_config(
        cls, config: Optional[RunnableConfig] = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )
        
        # Load YAML configuration
        yaml_config = load_yaml_config("conf.yaml")
        research_mode_config = yaml_config.get("RESEARCH_MODE", {})
        
        # Merge YAML config with configurable
        yaml_values = {
            "research_mode": research_mode_config.get("mode", "standard"),
            "max_research_iterations": research_mode_config.get("max_iterations", 5),
            "enable_report_synthesis": research_mode_config.get("enable_synthesis", True),
            "literature_focus": research_mode_config.get("literature_focus", False),
            "context_compression": research_mode_config.get("context_compression", True),
        }
        
        # Merge configurable with YAML values (configurable takes precedence)
        merged_configurable = {**yaml_values, **configurable}
        
        # logger.info(f"YAML research_mode config: {research_mode_config}")
        # logger.info(f"Merged research_mode: {merged_configurable.get('research_mode')}")
        
        values: dict[str, Any] = {
            f.name: os.environ.get(f.name.upper(), merged_configurable.get(f.name))
            for f in fields(cls)
            if f.init
        }
        return cls(**{k: v for k, v in values.items() if v})
