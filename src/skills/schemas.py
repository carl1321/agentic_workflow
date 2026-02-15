# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Pydantic models for Agent Skills (agentskills.io) metadata and content."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Skill metadata parsed from SKILL.md frontmatter. Aligns with Agent Skills spec."""

    name: str = Field(..., description="Skill name, must match directory name")
    description: str = Field(..., description="What the skill does and when to use it")
    path: str = Field(..., description="Absolute path to the skill directory")
    license: Optional[str] = Field(None, description="License name or reference")
    compatibility: Optional[str] = Field(None, max_length=500)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Extra metadata, e.g. tools list")
    allowed_tools: Optional[str] = Field(None, description="Space-delimited list of pre-approved tools (experimental)")


class SkillContent(BaseModel):
    """Full skill content for prompt injection."""

    name: str
    description: str
    body: str = Field(..., description="Markdown body of SKILL.md after frontmatter")
    path: str = ""


class SkillMetadataResponse(BaseModel):
    """Skill metadata for API list; optionally includes tools."""

    name: str
    description: str
    path: str = ""
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    tools: Optional[List[str]] = Field(None, description="Tool names associated with this skill when include_tools=1")
