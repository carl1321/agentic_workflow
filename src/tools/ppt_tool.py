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
from typing import Annotated, Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def ppt_generate_tool(
    content: Annotated[str, "PPT 的 Markdown 或结构化文本内容（可包含 ## 标题、列表、分镜描述等）"],
    save_relative_path: Annotated[str, "保存到 temp/ppt 下的相对路径，如 第一集分镜.pptx；与 base_dir/relative_path 二选一"] = "",
    base_dir: Annotated[
        Optional[str],
        "与 relative_path 一起使用，直接写入指定目录（如 outputs），用于计划任务验收路径",
    ] = None,
    relative_path: Annotated[
        Optional[str],
        "与 base_dir 一起使用，相对 base_dir 的路径，如 plans/{plan_id}/xxx.pptx；写入后验收会检查该文件",
    ] = None,
) -> str:
    """根据文本内容生成 PPT 文件，用于分镜预览、汇报等。依赖 marp-cli。若传 base_dir+relative_path 则写入该路径（供计划任务验收）；否则写入 temp/ppt。"""
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
        if base_dir and relative_path:
            out_path = (root / base_dir / relative_path).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.suffix.lower() != ".pptx":
                out_path = out_path.with_suffix(".pptx")
        else:
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
