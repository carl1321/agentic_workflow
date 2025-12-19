# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, get_args

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from src.config import load_yaml_config
from src.config.agents import LLMType
from src.llms.providers.dashscope import ChatDashscope
from src.llms.providers.reasoning import (
    AzureChatOpenAIWithReasoning,
    ChatOpenAIWithReasoning,
)

logger = logging.getLogger(__name__)

# Cache for LLM instances
_llm_cache: dict[LLMType, BaseChatModel] = {}
# Cache for LLM instances by model name
_model_llm_cache: dict[str, BaseChatModel] = {}


def _get_config_file_path() -> str:
    """Get the path to the configuration file."""
    return str((Path(__file__).parent.parent.parent / "conf.yaml").resolve())


def _get_llm_type_config_keys() -> dict[str, str]:
    """Get mapping of LLM types to their configuration keys."""
    return {
        "reasoning": "REASONING_MODEL",
        "basic": "BASIC_MODEL",
        "vision": "VISION_MODEL",
        "code": "CODE_MODEL",
    }


def _get_env_llm_conf(llm_type: str) -> Dict[str, Any]:
    """
    Get LLM configuration from environment variables.
    Environment variables should follow the format: {LLM_TYPE}__{KEY}
    e.g., BASIC_MODEL__api_key, BASIC_MODEL__base_url
    """
    prefix = f"{llm_type.upper()}_MODEL__"
    conf = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            conf_key = key[len(prefix) :].lower()
            conf[conf_key] = value
    return conf


def _process_base_url_with_completion_path(base_url: str, completion_path: Optional[str] = None) -> str:
    """Process base_url with completion_path if provided.
    
    Note: OpenAI client automatically appends /v1/chat/completions to base_url.
    So we should only append completion_path if it's NOT the default path.
    """
    # Normalize completion_path
    if completion_path:
        completion_path = completion_path.strip().lstrip('/')
        # If completion_path is the default path, don't append it
        # OpenAI client will add it automatically
        if completion_path == "v1/chat/completions" or completion_path == "/v1/chat/completions":
            # Just return the base_url, let OpenAI client add the default path
            return base_url.rstrip('/')
        # If base_url already ends with completion_path, don't duplicate
        normalized_completion = completion_path.rstrip('/')
        if base_url.rstrip('/').endswith(normalized_completion):
            return base_url.rstrip('/')
        # Append custom completion_path
        base_url = base_url.rstrip('/')
        return f"{base_url}/{normalized_completion}"
    # No completion_path specified, return base_url as-is
    # OpenAI client will add /v1/chat/completions automatically
    return base_url.rstrip('/')


def _create_llm_use_conf(llm_type: LLMType, conf: Dict[str, Any]) -> BaseChatModel:
    """Create LLM instance using configuration."""
    llm_type_config_keys = _get_llm_type_config_keys()
    config_key = llm_type_config_keys.get(llm_type)

    if not config_key:
        raise ValueError(f"Unknown LLM type: {llm_type}")

    llm_conf = conf.get(config_key, {})
    if not isinstance(llm_conf, dict):
        raise ValueError(f"Invalid LLM configuration for {llm_type}: {llm_conf}")

    # Get configuration from environment variables
    env_conf = _get_env_llm_conf(llm_type)

    # Merge configurations, with environment variables taking precedence
    merged_conf = {**llm_conf, **env_conf}

    # If BASIC_MODEL not found and llm_type is "basic", try to find from MODELS list
    if not merged_conf and llm_type == "basic":
        models_config = conf.get("MODELS", [])
        if models_config and isinstance(models_config, list):
            # Try to find a basic model from MODELS
            for model_config in models_config:
                if isinstance(model_config, dict):
                    model_type = model_config.get("type", "basic")  # Default to basic if no type
                    supports_thinking = model_config.get("supports_thinking", False)
                    # Prefer models that are explicitly basic type and don't support thinking
                    if model_type == "basic" and not supports_thinking:
                        # Found a basic model, use it
                        merged_conf = model_config.copy()
                        logger.info(f"Using model '{model_config.get('name', 'unknown')}' from MODELS as BASIC_MODEL fallback")
                        break
            # If still not found, use first non-thinking model as fallback
            if not merged_conf:
                for model_config in models_config:
                    if isinstance(model_config, dict):
                        supports_thinking = model_config.get("supports_thinking", False)
                        if not supports_thinking:
                            merged_conf = model_config.copy()
                            logger.info(f"Using model '{model_config.get('name', 'unknown')}' from MODELS as BASIC_MODEL fallback (non-thinking)")
                            break

    # Remove unnecessary parameters when initializing the client
    if "token_limit" in merged_conf:
        merged_conf.pop("token_limit")
    
    # Remove name, type, and supports_thinking fields if they exist (from MODELS fallback)
    merged_conf.pop("name", None)
    merged_conf.pop("type", None)
    merged_conf.pop("supports_thinking", None)

    if not merged_conf:
        raise ValueError(f"No configuration found for LLM type: {llm_type}")

    # Add max_retries to handle rate limit errors
    if "max_retries" not in merged_conf:
        merged_conf["max_retries"] = 3

    # Handle completion_path if provided
    completion_path = merged_conf.pop("completion_path", None)
    base_url = merged_conf.get("base_url") or merged_conf.get("host")
    
    if base_url:
        # Process base_url with completion_path
        processed_base_url = _process_base_url_with_completion_path(base_url, completion_path)
        merged_conf["base_url"] = processed_base_url

    # Handle SSL verification settings
    verify_ssl = merged_conf.pop("verify_ssl", True)

    # Create custom HTTP client if SSL verification is disabled
    if not verify_ssl:
        http_client = httpx.Client(verify=False)
        http_async_client = httpx.AsyncClient(verify=False)
        merged_conf["http_client"] = http_client
        merged_conf["http_async_client"] = http_async_client

    # Check if it's Google AI Studio platform based on configuration
    platform = merged_conf.get("platform", "").lower()
    is_google_aistudio = platform == "google_aistudio" or platform == "google-aistudio"

    if is_google_aistudio:
        # Handle Google AI Studio specific configuration
        gemini_conf = merged_conf.copy()

        # Map common keys to Google AI Studio specific keys
        if "api_key" in gemini_conf:
            gemini_conf["google_api_key"] = gemini_conf.pop("api_key")

        # Remove base_url and platform since Google AI Studio doesn't use them
        gemini_conf.pop("base_url", None)
        gemini_conf.pop("platform", None)

        # Remove unsupported parameters for Google AI Studio
        gemini_conf.pop("http_client", None)
        gemini_conf.pop("http_async_client", None)

        return ChatGoogleGenerativeAI(**gemini_conf)

    # Check for Azure - prioritize azure_endpoint in config
    azure_endpoint = merged_conf.get("azure_endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        # Ensure azure_endpoint is set
        merged_conf["azure_endpoint"] = azure_endpoint
        # Use reasoning wrapper if this is a reasoning model
        if llm_type == "reasoning":
            return AzureChatOpenAIWithReasoning(**merged_conf)
        else:
            return AzureChatOpenAI(**merged_conf)

    # Check if base_url is dashscope endpoint
    if "base_url" in merged_conf and "dashscope." in merged_conf["base_url"]:
        if llm_type == "reasoning":
            merged_conf["extra_body"] = {"enable_thinking": True}
        else:
            merged_conf["extra_body"] = {"enable_thinking": False}
        return ChatDashscope(**merged_conf)

    if llm_type == "reasoning":
        # REASONING_MODEL automatically supports thinking
        # Check if it's DeepSeek or standard OpenAI
        if "api_base" in merged_conf or merged_conf.get("base_url"):
            # Use reasoning wrapper for OpenAI-compatible reasoning models
            return ChatOpenAIWithReasoning(**merged_conf)
        else:
            merged_conf["api_base"] = merged_conf.pop("base_url", None)
            return ChatDeepSeek(**merged_conf)
    else:
        return ChatOpenAI(**merged_conf)


def get_llm_by_type(llm_type: LLMType) -> BaseChatModel:
    """
    Get LLM instance by type. Returns cached instance if available.
    """
    if llm_type in _llm_cache:
        return _llm_cache[llm_type]

    conf = load_yaml_config(_get_config_file_path())
    llm = _create_llm_use_conf(llm_type, conf)
    _llm_cache[llm_type] = llm
    return llm


def get_llm_by_model_name(model_name: str) -> BaseChatModel:
    """
    Get LLM instance by model name identifier. Returns cached instance if available.
    
    Args:
        model_name: The model identifier (e.g., "doubao-pro", "qwen3-32b")
    
    Returns:
        BaseChatModel instance for the specified model
    
    Raises:
        ValueError: If model name is not found in configuration
    """
    if model_name in _model_llm_cache:
        return _model_llm_cache[model_name]
    
    conf = load_yaml_config(_get_config_file_path())
    
    # First, check MODELS configuration (new format)
    models_config = conf.get("MODELS", [])
    if models_config and isinstance(models_config, list):
        for model_config in models_config:
            if isinstance(model_config, dict) and model_config.get("name") == model_name:
                # Found the model, create LLM instance from this config
                model_conf = model_config.copy()
                llm = _create_llm_from_dict(model_conf)
                _model_llm_cache[model_name] = llm
                return llm
    
    # If not found, raise error
    raise ValueError(f"Model '{model_name}' not found in configuration. Available models: {list(_get_available_model_names(conf))}")


def _get_available_model_names(conf: Dict[str, Any]) -> set[str]:
    """Get set of available model names from configuration."""
    model_names = set()
    
    # From MODELS config
    models_config = conf.get("MODELS", [])
    if models_config and isinstance(models_config, list):
        for model_config in models_config:
            if isinstance(model_config, dict):
                name = model_config.get("name")
                if name:
                    model_names.add(name)
    
    return model_names


def get_model_supports_thinking(model_name: str) -> bool:
    """
    Check if a model supports thinking based on its configuration.
    
    Args:
        model_name: The model identifier (e.g., "Doubao-Thinking", "Doubao-Pro")
    
    Returns:
        True if the model supports thinking, False otherwise.
        Defaults to False if model not found or supports_thinking not set.
    """
    try:
        conf = load_yaml_config(_get_config_file_path())
        
        # First, check MODELS configuration (new format)
        models_config = conf.get("MODELS", [])
        if models_config and isinstance(models_config, list):
            for model_config in models_config:
                if isinstance(model_config, dict) and model_config.get("name") == model_name:
                    # Found the model, check supports_thinking
                    return model_config.get("supports_thinking", False)
        
        # If not found in MODELS, check backward compatibility with old format
        llm_type_config_keys = _get_llm_type_config_keys()
        for llm_type in get_args(LLMType):
            config_key = llm_type_config_keys.get(llm_type, "")
            yaml_conf = conf.get(config_key, {}) if config_key else {}
            env_conf = _get_env_llm_conf(llm_type)
            merged_conf = {**yaml_conf, **env_conf}
            
            # REASONING_MODEL automatically supports thinking
            if llm_type == "reasoning" and merged_conf.get("model"):
                # Check if this is the requested model (for backward compatibility)
                # Old format models use format like "reasoning-{model_name}"
                model_identifier = f"{llm_type}-{merged_conf.get('model', '')}"
                if model_name == model_identifier or model_name == merged_conf.get("model"):
                    return True
        
        # Default to False if model not found
        return False
        
    except Exception as e:
        # Log error and return False as default
        print(f"Warning: Failed to check supports_thinking for model '{model_name}': {e}")
        return False


def _create_llm_from_dict(model_conf: Dict[str, Any]) -> BaseChatModel:
    """Create LLM instance from model configuration dictionary."""
    # Copy config to avoid modifying original
    merged_conf = model_conf.copy()
    
    # Remove name field as it's not needed for LLM creation
    merged_conf.pop("name", None)
    merged_conf.pop("type", None)
    
    # Check if model supports thinking before removing the flag
    supports_thinking = merged_conf.pop("supports_thinking", False)
    
    # Remove unnecessary parameters when initializing the client
    if "token_limit" in merged_conf:
        merged_conf.pop("token_limit")
    
    # Add max_retries if not present
    if "max_retries" not in merged_conf:
        merged_conf["max_retries"] = 3
    
    # Handle completion_path
    completion_path = merged_conf.pop("completion_path", None)
    base_url = merged_conf.get("base_url") or merged_conf.get("host")
    
    if base_url:
        processed_base_url = _process_base_url_with_completion_path(base_url, completion_path)
        merged_conf["base_url"] = processed_base_url
    
    # Handle SSL verification settings
    verify_ssl = merged_conf.pop("verify_ssl", True)
    
    # Create custom HTTP client if SSL verification is disabled
    if not verify_ssl:
        http_client = httpx.Client(verify=False)
        http_async_client = httpx.AsyncClient(verify=False)
        merged_conf["http_client"] = http_client
        merged_conf["http_async_client"] = http_async_client
    
    # Check if it's Google AI Studio platform
    platform = merged_conf.get("platform", "").lower()
    is_google_aistudio = platform == "google_aistudio" or platform == "google-aistudio"
    
    if is_google_aistudio:
        gemini_conf = merged_conf.copy()
        if "api_key" in gemini_conf:
            gemini_conf["google_api_key"] = gemini_conf.pop("api_key")
        gemini_conf.pop("base_url", None)
        gemini_conf.pop("platform", None)
        gemini_conf.pop("supports_thinking", None)
        gemini_conf.pop("http_client", None)
        gemini_conf.pop("http_async_client", None)
        return ChatGoogleGenerativeAI(**gemini_conf)
    
    # Check for Azure - prioritize azure_endpoint in config
    azure_endpoint = merged_conf.get("azure_endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        # Handle Azure-specific configuration
        azure_conf = merged_conf.copy()
        # Ensure azure_endpoint is set
        azure_conf["azure_endpoint"] = azure_endpoint
        # Map model to deployment_name if deployment_name is not set
        if not azure_conf.get("deployment_name") and azure_conf.get("model"):
            # Keep model as deployment_name, but don't remove it
            azure_conf["deployment_name"] = azure_conf.get("model")
        # Use reasoning wrapper if model supports thinking
        if supports_thinking:
            return AzureChatOpenAIWithReasoning(**azure_conf)
        else:
            return AzureChatOpenAI(**azure_conf)
    
    # Check if base_url is dashscope endpoint
    if "base_url" in merged_conf and "dashscope." in merged_conf["base_url"]:
        merged_conf["extra_body"] = {"enable_thinking": False}
        return ChatDashscope(**merged_conf)
    
    # Default to ChatOpenAI, use reasoning wrapper if model supports thinking
    if supports_thinking:
        return ChatOpenAIWithReasoning(**merged_conf)
    else:
        return ChatOpenAI(**merged_conf)


def get_configured_llm_models() -> dict[str, list[dict[str, Any]]]:
    """
    Get all configured LLM models with detailed information.
    Only returns models from MODELS configuration (excludes BASIC_MODEL).

    Returns:
        Dictionary mapping model type to list of model info dictionaries.
        Format: {
            "basic": [
                {"name": "Doubao-Pro", "model": "doubao-1-5-pro-32k-250115", "base_url": "...", ...},
                ...
            ],
            ...
        }
    """
    try:
        conf = load_yaml_config(_get_config_file_path())
        result: dict[str, list[dict[str, Any]]] = {}
        
        # Only return models from MODELS configuration (excludes BASIC_MODEL)
        models_config = conf.get("MODELS", [])
        if models_config and isinstance(models_config, list):
            for model_config in models_config:
                if isinstance(model_config, dict):
                    model_name = model_config.get("name")
                    model_type = model_config.get("type", "basic")  # Default to "basic" if not specified
                    if model_name:
                        # Create model info dict
                        model_info = {
                            "name": model_name,
                            "model": model_config.get("model", ""),
                            "base_url": model_config.get("base_url") or model_config.get("host", ""),
                            "api_key": model_config.get("api_key", ""),
                            "completion_path": model_config.get("completion_path", "/v1/chat/completions"),
                            "max_retries": model_config.get("max_retries", 3),
                            "verify_ssl": model_config.get("verify_ssl", True),
                            "supports_thinking": model_config.get("supports_thinking", False),
                            "azure_endpoint": model_config.get("azure_endpoint", ""),
                            "api_version": model_config.get("api_version", ""),
                            "deployment_name": model_config.get("deployment_name", ""),
                        }
                        result.setdefault(model_type, []).append(model_info)

        return result

    except Exception as e:
        # Log error and return empty dict to avoid breaking the application
        logger.warning(f"Failed to load LLM configuration: {e}")
        return {}


def get_llm_token_limit_by_type(llm_type: str) -> int:
    """
    Get the maximum token limit for a given LLM type.

    Args:
        llm_type (str): The type of LLM.

    Returns:
        int: The maximum token limit for the specified LLM type.
    """

    llm_type_config_keys = _get_llm_type_config_keys()
    config_key = llm_type_config_keys.get(llm_type)

    conf = load_yaml_config(_get_config_file_path())
    llm_max_token = conf.get(config_key, {}).get("token_limit")
    return llm_max_token


# In the future, we will use reasoning_llm and vl_llm for different purposes
# reasoning_llm = get_llm_by_type("reasoning")
# vl_llm = get_llm_by_type("vision")
