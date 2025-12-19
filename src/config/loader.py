# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from typing import Any, Dict

import yaml

# Global config cache
_config_cache: Dict[str, Dict[str, Any]] = {}


def load_yaml_config(file_path: str = "conf.yaml") -> Dict[str, Any]:
    """Load and process YAML configuration file."""
    # 如果文件不存在，返回{}
    if not os.path.exists(file_path):
        return {}

    # 检查缓存中是否已存在配置
    if file_path in _config_cache:
        return _config_cache[file_path]

    # 如果缓存中不存在，则加载并处理配置
    with open(file_path, "r") as f:
        config = yaml.safe_load(f) or {}
    processed_config = process_dict(config)

    # 将处理后的配置存入缓存
    _config_cache[file_path] = processed_config
    return processed_config


def _get_config_value(key_path: str, default: Any = None) -> Any:
    """
    Get configuration value from YAML config using dot notation.
    Example: _get_config_value("ENV.SEARCH_API") -> config["ENV"]["SEARCH_API"]
    """
    config = load_yaml_config()
    keys = key_path.split(".")
    value = config
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def get_bool_env(name: str, default: bool = False) -> bool:
    """
    Get boolean value from environment variable or YAML config.
    Priority: environment variable > YAML config > default
    """
    # First try environment variable
    val = os.getenv(name)
    if val is not None:
        return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}
    
    # Then try YAML config (look in ENV section)
    yaml_val = _get_config_value(f"ENV.{name}", None)
    if yaml_val is not None:
        if isinstance(yaml_val, bool):
            return yaml_val
        return str(yaml_val).strip().lower() in {"1", "true", "yes", "y", "on"}
    
    return default


def get_str_env(name: str, default: str = "") -> str:
    """
    Get string value from environment variable or YAML config.
    Priority: environment variable > YAML config > default
    """
    # First try environment variable
    val = os.getenv(name)
    if val is not None:
        return str(val).strip()
    
    # Then try YAML config (look in ENV section)
    yaml_val = _get_config_value(f"ENV.{name}", None)
    if yaml_val is not None:
        return str(yaml_val).strip()
    
    return default


def get_int_env(name: str, default: int = 0) -> int:
    """
    Get integer value from environment variable or YAML config.
    Priority: environment variable > YAML config > default
    """
    # First try environment variable
    val = os.getenv(name)
    if val is not None:
        try:
            return int(val.strip())
        except ValueError:
            print(f"Invalid integer value for {name}: {val}. Using default {default}.")
            return default
    
    # Then try YAML config (look in ENV section)
    yaml_val = _get_config_value(f"ENV.{name}", None)
    if yaml_val is not None:
        try:
            return int(yaml_val)
        except (ValueError, TypeError):
            print(f"Invalid integer value for {name}: {yaml_val}. Using default {default}.")
            return default
    
    return default


def replace_env_vars(value: str) -> str:
    """Replace environment variables in string values."""
    if not isinstance(value, str):
        return value
    if value.startswith("$"):
        env_var = value[1:]
        return os.getenv(env_var, env_var)
    return value


def process_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively process dictionary to replace environment variables."""
    if not config:
        return {}
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = process_dict(value)
        elif isinstance(value, str):
            result[key] = replace_env_vars(value)
        else:
            result[key] = value
    return result
