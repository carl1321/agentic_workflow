# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ToolExecuteRequest(BaseModel):
    """Request model for tool execution."""
    
    tool_name: str = Field(..., description="The name of the tool to execute")
    arguments: Dict[str, Any] = Field(
        ..., description="The arguments to pass to the tool"
    )


class ToolExecuteResponse(BaseModel):
    """Response model for tool execution."""
    
    result: str = Field(..., description="The result of tool execution")
    error: Optional[str] = Field(None, description="Error message if execution failed")

