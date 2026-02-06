# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
文件写入工具：用于选题库、分镜剧本、SRT 字幕、脚本等。
仅允许在配置的根目录（outputs、temp、data、docs、src）下写入，禁止 .. 与绝对路径逃逸。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 允许写入的根目录（相对于项目根）
ALLOWED_BASE_DIRS = ("outputs", "temp", "data", "docs", "src")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_safe_path(base_dir: str, relative_path: str) -> Path:
    """解析为项目下的安全路径，禁止 .. 逃逸。"""
    if base_dir not in ALLOWED_BASE_DIRS:
        raise ValueError(f"base_dir 必须是以下之一: {ALLOWED_BASE_DIRS}")
    root = _project_root()
    # 规范化并限制在 base_dir 下
    parts = Path(relative_path).parts
    if any(p == ".." or p == "..." for p in parts):
        raise ValueError("路径中不允许包含 .. 或 ...")
    full = (root / base_dir / relative_path).resolve()
    if not str(full).startswith(str(root)):
        raise ValueError("路径必须在项目根目录下")
    return full


@tool
def create_file_tool(
    base_dir: Annotated[str, "根目录：outputs / temp / data / docs / src 之一"],
    relative_path: Annotated[str, "相对路径，如 选题库.txt、第一集/分镜剧本.md"],
    content: Annotated[str, "要写入的文本内容"],
) -> str:
    """在指定根目录下创建或覆盖写入文本文件。用于选题库、分镜剧本、SRT、脚本等。"""
    try:
        path = _resolve_safe_path(base_dir, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("create_file_tool wrote %s", path)
        return f"已写入: {path}"
    except Exception as e:
        logger.warning("create_file_tool failed: %s", e)
        return f"写入失败: {e}"


@tool
def edit_file_tool(
    base_dir: Annotated[str, "根目录：outputs / temp / data / docs / src 之一"],
    relative_path: Annotated[str, "相对路径"],
    content: Annotated[str, "要追加或覆盖的文本内容"],
    append: Annotated[bool, "True=追加到文件末尾，False=覆盖"] = False,
) -> str:
    """在指定根目录下编辑文件：追加或覆盖。用于选题库追加、日志等。"""
    try:
        path = _resolve_safe_path(base_dir, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        logger.info("edit_file_tool %s %s", "appended" if append else "wrote", path)
        return f"已{'追加' if append else '写入'}: {path}"
    except Exception as e:
        logger.warning("edit_file_tool failed: %s", e)
        return f"编辑失败: {e}"
