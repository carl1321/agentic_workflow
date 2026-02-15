# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""In-memory skill registry: discovery cache, tool mapping, and content loading."""

import logging
from typing import Any, Dict, List, Optional

from src.skills.discovery import discover_skills
from src.skills.loader import load_skill_content
from src.skills.schemas import SkillContent, SkillMetadata
from src.skills.tool_loader import load_tools_from_skill_dirs

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Holds discovered skills and skill_name -> tool_names mapping."""

    def __init__(self, base_dir: Optional[str] = None):
        self._base_dir = base_dir
        self._metadata: List[SkillMetadata] = []
        self._by_name: Dict[str, SkillMetadata] = {}
        self._skill_tools: Dict[str, List[str]] = {}  # skill_name -> [tool_name, ...]
        self.refresh()

    def refresh(self) -> None:
        """Re-scan skill directories and rebuild cache (metadata + metadata.tools only)."""
        self._metadata = discover_skills(self._base_dir)
        self._by_name = {m.name: m for m in self._metadata}
        self._skill_tools = {}
        for m in self._metadata:
            tools: List[str] = []
            if m.metadata and isinstance(m.metadata.get("tools"), str):
                tools = [t.strip() for t in m.metadata["tools"].split() if t.strip()]
            self._skill_tools[m.name] = tools
        logger.info("Skill registry refreshed: %d skills", len(self._metadata))

    def load_dynamic_tools(self) -> Dict[str, Any]:
        """
        Load tools from skill directories (tools.py or tools/__init__.py).
        Merge loaded tool names into _skill_tools. Return dict of tool_name -> tool for caller to register.
        """
        extra_tools, skill_tools_map = load_tools_from_skill_dirs(self._metadata)
        for skill_name, tool_names in skill_tools_map.items():
            self._skill_tools.setdefault(skill_name, [])
            for tn in tool_names:
                if tn not in self._skill_tools[skill_name]:
                    self._skill_tools[skill_name].append(tn)
        return extra_tools

    def get_all_metadata(self) -> List[SkillMetadata]:
        return list(self._metadata)

    def get_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        return self._by_name.get(skill_name)

    def get_skill_tools(self, skill_name: str) -> List[str]:
        """Return list of tool names associated with this skill."""
        return list(self._skill_tools.get(skill_name, []))

    def load_content(self, skill_name: str) -> Optional[SkillContent]:
        """Load full SKILL.md content for the given skill."""
        meta = self._by_name.get(skill_name)
        if not meta:
            return None
        return load_skill_content(meta.path, meta.name, meta.description)


# Singleton for app use
_registry: Optional[SkillRegistry] = None


def get_skill_registry(base_dir: Optional[str] = None) -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry(base_dir)
    return _registry
