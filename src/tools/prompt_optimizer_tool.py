# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import Annotated, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from src.llms.llm import get_llm_by_model_name, get_llm_by_type

from .decorators import log_io

logger = logging.getLogger(__name__)


@tool
@log_io
def prompt_optimizer_tool(
    prompt: Annotated[str, "The system prompt or instruction to guide the model's behavior."],
    question: Annotated[str, "The user's question or input to be answered."],
    model_name: Annotated[
        Optional[str],
        "Optional model name identifier. If not provided, uses the default basic model.",
    ] = None,
) -> str:
    """Use this tool to get AI responses based on a custom prompt and question. 
    You can specify which model to use, or leave it empty to use the default model."""
    try:
        # Get LLM instance based on model_name parameter
        # Handle empty string as None (for compatibility with frontend)
        if model_name and model_name.strip():
            try:
                llm = get_llm_by_model_name(model_name.strip())
                logger.info(f"Using model: {model_name}")
            except ValueError as e:
                error_msg = f"Model '{model_name}' not found. Available models can be checked in the configuration. Error: {str(e)}"
                logger.error(error_msg)
                return error_msg
        else:
            llm = get_llm_by_type("basic")
            logger.info("Using default basic model")

        # Build messages: prompt as system message, question as user message
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=question),
        ]

        # Invoke LLM to generate response
        logger.info(f"Invoking LLM with prompt length: {len(prompt)}, question length: {len(question)}")
        response = llm.invoke(messages)
        
        # Extract content from response
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"LLM response generated, length: {len(result)}")
        
        return result

    except Exception as e:
        error_msg = f"Failed to generate response. Error: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg

