# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
PPT 生成工具：根据 Markdown/文本内容生成 PPT 文件（分镜预览、汇报等）。
内部调用现有 PPT 工作流，将生成文件保存到 temp/ppt 并返回路径。
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def ppt_generate_tool(
    content: Annotated[str, "PPT 的 Markdown 或结构化文本内容（可包含 ## 标题、列表、分镜描述等）"],
    save_relative_path: Annotated[str, "保存到 temp/ppt 下的相对路径，如 第一集分镜.pptx"] = "",
) -> str:
    """根据文本内容生成 PPT 文件，用于分镜预览、汇报等。依赖 marp-cli。生成文件保存在 temp/ppt 下。"""
    try:
        from src.ppt.graph.builder import build_graph as build_ppt_graph
    except ImportError as e:
        return f"无法加载 PPT 工作流: {e}"

    try:
        workflow = build_ppt_graph()
        final_state = workflow.invoke({"input": content})
        generated = final_state.get("generated_file_path")
        if not generated or not Path(generated).exists():
            return "PPT 生成失败或未得到输出文件。"

        root = Path(__file__).resolve().parents[2]
        out_dir = root / "temp" / "ppt"
        out_dir.mkdir(parents=True, exist_ok=True)
        if save_relative_path:
            out_path = (out_dir / save_relative_path).resolve()
            if out_path.suffix.lower() != ".pptx":
                out_path = out_path.with_suffix(".pptx")
        else:
            out_path = out_dir / f"ppt_{uuid.uuid4().hex[:8]}.pptx"
        shutil.copy2(generated, out_path)
        try:
            Path(generated).unlink(missing_ok=True)
        except Exception:
            pass
        logger.info("ppt_generate_tool saved %s", out_path)
        return f"已生成: {out_path}"
    except Exception as e:
        logger.warning("ppt_generate_tool failed: %s", e)
        return f"生成失败: {e}"
