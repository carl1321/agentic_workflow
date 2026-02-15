# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Load LangChain tools from skill directory (tools.py or tools/__init__.py) and return for registry."""

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.skills.schemas import SkillMetadata

logger = logging.getLogger(__name__)


def _load_tools_from_path(skill_name: str, skill_path: str) -> Tuple[List[Any], List[str]]:
    """
    Load tools from skill_path/tools.py or skill_path/tools/__init__.py.
    Returns (list of tool instances, list of tool names).
    """
    path = Path(skill_path)
    mod_path = path / "tools.py"
    if not mod_path.is_file():
        mod_path = path / "tools" / "__init__.py"
    if not mod_path.is_file():
        return [], []

    # Add parent of skill dir to path so "import tools" or "from tools import X" can work
    parent = str(path.resolve())
    if parent in sys.path:
        sys.path.remove(parent)
    sys.path.insert(0, parent)

    try:
        spec = importlib.util.spec_from_file_location(f"skill_tools_{skill_name}", mod_path)
        if spec is None or spec.loader is None:
            return [], []
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        logger.warning("Failed to load tools from %s: %s", mod_path, e)
        return [], []
    finally:
        if parent in sys.path:
            sys.path.remove(parent)

    tools: List[Any] = []
    if hasattr(mod, "get_tools") and callable(mod.get_tools):
        tools = list(mod.get_tools())
    elif hasattr(mod, "TOOLS"):
        raw = getattr(mod, "TOOLS")
        if isinstance(raw, (list, tuple)):
            tools = list(raw)
        else:
            tools = []

    names: List[str] = []
    for t in tools:
        if hasattr(t, "name"):
            names.append(t.name)
        else:
            names.append(getattr(t, "__name__", "unknown"))
    return tools, names


def load_tools_from_skill_dirs(skills: List[SkillMetadata]) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """
    For each skill directory that has tools.py or tools/__init__.py, load tools.
    Returns (tool_name -> tool callable, skill_name -> [tool_name, ...]).
    Duplicate tool names: first wins, later skipped with log.
    """
    all_tools: Dict[str, Any] = {}
    skill_tools: Dict[str, List[str]] = {}

    for meta in skills:
        loaded, names = _load_tools_from_path(meta.name, meta.path)
        if not loaded:
            continue
        added = []
        for t, name in zip(loaded, names):
            if name in all_tools:
                logger.warning("Tool name %r already registered, skipping from skill %s", name, meta.name)
                continue
            all_tools[name] = t
            added.append(name)
        if added:
            skill_tools[meta.name] = skill_tools.get(meta.name, []) + added

    return all_tools, skill_tools
