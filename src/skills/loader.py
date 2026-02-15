# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Load full SKILL.md content for prompt injection."""

import logging
from pathlib import Path
from typing import Optional

from src.skills.schemas import SkillContent

logger = logging.getLogger(__name__)


def load_skill_content(skill_path: str, skill_name: str, description: str = "") -> Optional[SkillContent]:
    """
    Load full SKILL.md from a skill directory. Returns body (markdown after frontmatter)
    for prompt injection.
    """
    path = Path(skill_path)
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        logger.warning("SKILL.md not found at %s", skill_md)
        return None

    try:
        raw = skill_md.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("Could not read %s: %s", skill_md, e)
        return None

    # Strip frontmatter to get body only
    if raw.startswith("---"):
        idx = raw.find("---", 3)
        if idx != -1:
            raw = raw[idx + 3 :].lstrip("\n")
        else:
            raw = raw[3:].lstrip("\n")

    return SkillContent(
        name=skill_name,
        description=description or "",
        body=raw,
        path=str(path),
    )
