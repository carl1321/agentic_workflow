# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import Annotated

import httpx
from langchain_core.tools import tool

from src.config.loader import get_str_env

from .decorators import log_io

logger = logging.getLogger(__name__)


@tool
@log_io
def molecular_analysis_tool(
    smiles: Annotated[str, "The SMILES string of the molecule to analyze."],
) -> str:
    """Analyze molecular structure using InternLM API. 
    This tool takes a SMILES string and returns detailed molecular structure analysis 
    including chemical properties, structural features, and potential applications."""
    try:
        # Get API configuration from environment variables
        api_base_url = get_str_env("INTERNLM_API_BASE_URL", "")
        api_key = get_str_env("INTERNLM_API_KEY", "")

        if not api_base_url:
            error_msg = "INTERNLM_API_BASE_URL environment variable is not set. Please configure it in .env file."
            logger.error(error_msg)
            return error_msg

        if not api_key:
            error_msg = "INTERNLM_API_KEY environment variable is not set. Please configure it in .env file."
            logger.error(error_msg)
            return error_msg

        # Normalize base_url and construct API endpoint
        base_url = api_base_url.rstrip("/")
        
        # Remove /v1/chat/completions if present
        if base_url.endswith("/v1/chat/completions"):
            base_url = base_url[: -len("/v1/chat/completions")].rstrip("/")
        # Remove /v1 if present (to avoid duplicate /v1)
        elif base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")].rstrip("/")
        
        # Construct API endpoint
        api_url = f"{base_url}/v1/chat/completions"

        # Build prompt for molecular analysis
        system_prompt = """你是一个专业的分子结构分析专家。请对给定的SMILES字符串进行详细的分子结构分析，包括但不限于：
1. 分子的化学结构特征
2. 官能团识别
3. 可能的化学性质和反应活性
4. 分子量、分子式等基本信息
5. 潜在的应用领域
请用中文回答，并提供详细、专业的分析。"""

        user_prompt = f"请分析以下SMILES字符串表示的分子结构：{smiles}"

        # Prepare request payload (OpenAI-compatible format)
        # Using internlm3-latest which points to internlm3-8b-instruct (latest LLM model)
        payload = {
            "model": "internlm3-latest",  # Latest InternLM3 model, automatically points to internlm3-8b-instruct
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.info(f"Calling InternLM API for SMILES analysis: {smiles[:50]}...")

        # Make API request
        with httpx.Client(timeout=60.0) as client:
            response = client.post(api_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

        # Extract response content
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            if content:
                logger.info(f"Successfully received analysis result, length: {len(content)}")
                return content
            else:
                error_msg = "API response does not contain content in expected format."
                logger.error(error_msg)
                return f"错误：{error_msg}\nAPI响应：{result}"
        else:
            error_msg = "API response does not contain choices in expected format."
            logger.error(f"{error_msg} Response: {result}")
            return f"错误：{error_msg}\nAPI响应：{result}"

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg, exc_info=True)
        return f"错误：API调用失败\n{error_msg}"

    except httpx.RequestError as e:
        error_msg = f"Request error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return f"错误：无法连接到InternLM API\n{error_msg}\n请检查INTERNLM_API_BASE_URL配置是否正确。"

    except Exception as e:
        error_msg = f"Unexpected error: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return f"错误：分析分子结构时发生异常\n{error_msg}"

