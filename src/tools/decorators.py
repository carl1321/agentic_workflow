# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import functools
import logging
from typing import Any, Callable, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def log_io(func: Callable) -> Callable:
    """
    A decorator that logs the input parameters and output of a tool function.

    Args:
        func: The tool function to be decorated

    Returns:
        The wrapped function with input/output logging
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Log input parameters (compressed for data_extraction_tool)
        func_name = func.__name__
        
        # Compress parameters for data_extraction_tool to avoid logging large base64 data
        if func_name == "data_extraction_tool":
            compressed_params = []
            for arg in args:
                if isinstance(arg, str) and len(arg) > 200:
                    compressed_params.append(f"{arg[:100]}... (truncated, length: {len(arg)})")
                else:
                    compressed_params.append(str(arg))
            for k, v in kwargs.items():
                if k == "pdf_file_base64" and isinstance(v, str) and len(v) > 200:
                    compressed_params.append(f"{k}=<base64_data> (length: {len(v)})")
                elif isinstance(v, str) and len(v) > 200:
                    compressed_params.append(f"{k}={v[:100]}... (truncated, length: {len(v)})")
                else:
                    compressed_params.append(f"{k}={v}")
            params = ", ".join(compressed_params)
        else:
            params = ", ".join(
                [*(str(arg) for arg in args), *(f"{k}={v}" for k, v in kwargs.items())]
            )
        logger.info(f"Tool {func_name} called with parameters: {params}")

        # Execute the function
        result = func(*args, **kwargs)

        # Log the output (compressed for data_extraction_tool)
        if func_name == "data_extraction_tool":
            if isinstance(result, str):
                # Compress result if it's too long (e.g., JSON with table_data)
                if len(result) > 500:
                    try:
                        import json
                        result_json = json.loads(result)
                        if isinstance(result_json, dict) and "table_data" in result_json:
                            table_data = result_json.get("table_data", [])
                            table_count = len(table_data) if isinstance(table_data, list) else 0
                            
                            # Compress categories to only show counts
                            categories = result_json.get("categories")
                            categories_summary = None
                            if categories and isinstance(categories, dict):
                                categories_summary = {
                                    "materials_count": len(categories.get("materials", [])),
                                    "processes_count": len(categories.get("processes", [])),
                                    "properties_count": len(categories.get("properties", [])),
                                }
                            
                            # Compress selected_categories to only show counts
                            selected_categories = result_json.get("selected_categories")
                            selected_categories_summary = None
                            if selected_categories and isinstance(selected_categories, dict):
                                selected_categories_summary = {
                                    "materials_count": len(selected_categories.get("materials", [])),
                                    "processes_count": len(selected_categories.get("processes", [])),
                                    "properties_count": len(selected_categories.get("properties", [])),
                                }
                            
                            # Compress metadata (remove large fields)
                            metadata = result_json.get("metadata")
                            metadata_summary = None
                            if metadata and isinstance(metadata, dict):
                                metadata_summary = {
                                    k: v for k, v in metadata.items() 
                                    if not isinstance(v, str) or len(v) < 100
                                }
                            
                            # Create compressed result summary
                            compressed_result = {
                                "step": result_json.get("step"),
                                "extraction_type": result_json.get("extraction_type"),
                                "table_data_count": table_count,
                                "categories": categories_summary,
                                "selected_categories": selected_categories_summary,
                                "metadata": metadata_summary,
                            }
                            logger.info(f"Tool {func_name} returned (compressed): {json.dumps(compressed_result, ensure_ascii=False)}")
                        elif isinstance(result_json, dict):
                            # Compress any result JSON, not just those with table_data
                            compressed_result = {
                                "step": result_json.get("step"),
                                "extraction_type": result_json.get("extraction_type"),
                            }
                            # Add categories summary if present
                            categories = result_json.get("categories")
                            if categories and isinstance(categories, dict):
                                compressed_result["categories"] = {
                                    "materials_count": len(categories.get("materials", [])),
                                    "processes_count": len(categories.get("processes", [])),
                                    "properties_count": len(categories.get("properties", [])),
                                }
                            logger.info(f"Tool {func_name} returned (compressed): {json.dumps(compressed_result, ensure_ascii=False)}")
                        else:
                            logger.info(f"Tool {func_name} returned (length: {len(result)}): {result[:200]}...")
                    except:
                        # If JSON parsing fails, just log length
                        logger.info(f"Tool {func_name} returned (length: {len(result)}, not JSON)")
                else:
                    logger.info(f"Tool {func_name} returned: {result}")
            else:
                logger.info(f"Tool {func_name} returned: {result}")
        else:
            logger.info(f"Tool {func_name} returned: {result}")

        return result

    return wrapper


class LoggedToolMixin:
    """A mixin class that adds logging functionality to any tool."""

    def _log_operation(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Helper method to log tool operations."""
        tool_name = self.__class__.__name__.replace("Logged", "")
        params = ", ".join(
            [*(str(arg) for arg in args), *(f"{k}={v}" for k, v in kwargs.items())]
        )
        logger.debug(f"Tool {tool_name}.{method_name} called with parameters: {params}")

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Override _run method to add logging."""
        self._log_operation("_run", *args, **kwargs)
        result = super()._run(*args, **kwargs)
        logger.debug(
            f"Tool {self.__class__.__name__.replace('Logged', '')} returned: {result}"
        )
        return result


def create_logged_tool(base_tool_class: Type[T]) -> Type[T]:
    """
    Factory function to create a logged version of any tool class.

    Args:
        base_tool_class: The original tool class to be enhanced with logging

    Returns:
        A new class that inherits from both LoggedToolMixin and the base tool class
    """

    class LoggedTool(LoggedToolMixin, base_tool_class):
        pass

    # Set a more descriptive name for the class
    LoggedTool.__name__ = f"Logged{base_tool_class.__name__}"
    return LoggedTool
