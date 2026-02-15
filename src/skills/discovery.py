# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Discover skills from configured directories and parse SKILL.md frontmatter."""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional

import yaml

from src.skills.schemas import SkillMetadata

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _get_skills_config() -> dict:
    """Read skills config from conf.yaml. Defaults when missing."""
    from src.config.loader import load_yaml_config

    config = load_yaml_config("conf.yaml")
    skills_config = config.get("skills") or {}
    return {
        "enabled": skills_config.get("enabled", True),
        "directories": skills_config.get("directories") or ["skills"],
    }


def _parse_frontmatter(content: str) -> Optional[dict]:
    """Extract YAML frontmatter from SKILL.md content. Returns None on failure."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return None
    try:
        return yaml.safe_load(match.group(1))
    except Exception as e:
        logger.warning("Failed to parse SKILL.md frontmatter: %s", e)
        return None


def discover_skills(base_dir: Optional[str] = None) -> List[SkillMetadata]:
    """
    Scan configured (or given) directories for skill folders containing SKILL.md.
    Parse only frontmatter; do not read full body.
    """
    config = _get_skills_config()
    if not config["enabled"]:
        logger.info("Skills are disabled in config.")
        return []

    root = Path(base_dir or os.getcwd())
    results: List[SkillMetadata] = []

    for dir_name in config["directories"]:
        search_path = root / dir_name
        if not search_path.is_dir():
            logger.debug("Skills directory not found: %s", search_path)
            continue

        for entry in search_path.iterdir():
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue

            try:
                raw = skill_md.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.warning("Could not read %s: %s", skill_md, e)
                continue

            fm = _parse_frontmatter(raw)
            if not fm or not isinstance(fm, dict):
                logger.warning("Invalid or missing frontmatter in %s", skill_md)
                continue

            name = fm.get("name")
            description = fm.get("description")
            if not name or not description:
                logger.warning("SKILL.md %s missing required name or description", skill_md)
                continue

            try:
                meta = SkillMetadata(
                    name=str(name).strip(),
                    description=str(description).strip(),
                    path=str(entry.resolve()),
                    license=fm.get("license"),
                    compatibility=fm.get("compatibility"),
                    metadata=fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {},
                    allowed_tools=fm.get("allowed-tools") or fm.get("allowed_tools"),
                )
                results.append(meta)
            except Exception as e:
                logger.warning("Failed to build SkillMetadata for %s: %s", skill_md, e)

    return results
