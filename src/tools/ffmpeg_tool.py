# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
FFmpeg 封装工具：视频拼接、音画合成。
用于将多个 MP4 片段合并为完整视频，或将视频轨与音频轨（配音、BGM）混合为成片。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Annotated, List

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _run_ffmpeg(args: List[str], cwd: Path | None = None, timeout: int = 600) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["ffmpeg", "-y"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "ffmpeg timed out"
    except FileNotFoundError:
        return -1, "", "ffmpeg not found (please install ffmpeg)"
    except Exception as e:
        return -1, "", str(e)


@tool
def ffmpeg_tool(
    action: Annotated[str, "操作类型：concat=多段视频拼接；merge_av=音画合成"],
    output_path: Annotated[str, "输出文件路径（建议在 outputs 或 temp 下），如 outputs/第一集/完整视频.mp4"],
    video_paths: Annotated[List[str], "concat 时：按顺序的 MP4 文件路径列表"] = None,
    concat_list_path: Annotated[str, "concat 时：可选，已写好的 concat 列表文件路径（每行 file 'xxx.mp4'）"] = "",
    video_path: Annotated[str, "merge_av 时：主视频文件路径"] = "",
    audio_path: Annotated[str, "merge_av 时：音频文件路径（配音/BGM）"] = "",
) -> str:
    """使用 ffmpeg 做视频拼接（concat）或音画合成（merge_av）。拼接示例：video_paths=[a.mp4,b.mp4]，输出 output_path。音画合成：video_path + audio_path -> output_path。"""
    video_paths = video_paths or []
    root = Path(__file__).resolve().parents[2]
    out = Path(output_path)
    if not out.is_absolute():
        out = root / output_path
    out.parent.mkdir(parents=True, exist_ok=True)

    if action == "concat":
        if concat_list_path:
            list_file = Path(concat_list_path) if Path(concat_list_path).is_absolute() else root / concat_list_path
            if not list_file.exists():
                return f"列表文件不存在: {list_file}"
            code, _, err = _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)])
        elif video_paths:
            # 先写临时 concat 列表
            list_file = out.with_suffix(".concat_list.txt")
            abs_paths = []
            for p in video_paths:
                pp = Path(p) if Path(p).is_absolute() else root / p
                if not pp.exists():
                    return f"视频文件不存在: {pp}"
                abs_paths.append(pp.resolve())
            list_file.write_text("\n".join(f"file '{p}'" for p in abs_paths), encoding="utf-8")
            try:
                code, _, err = _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)])
            finally:
                if list_file.exists():
                    list_file.unlink(missing_ok=True)
        else:
            return "concat 需提供 video_paths 或 concat_list_path"
        if code != 0:
            return f"拼接失败: {err}"
        return f"已生成: {out}"

    if action == "merge_av":
        if not video_path or not audio_path:
            return "merge_av 需提供 video_path 和 audio_path"
        vp = Path(video_path) if Path(video_path).is_absolute() else root / video_path
        ap = Path(audio_path) if Path(audio_path).is_absolute() else root / audio_path
        if not vp.exists():
            return f"视频文件不存在: {vp}"
        if not ap.exists():
            return f"音频文件不存在: {ap}"
        # -i video -i audio -c:v copy -c:a aac -shortest 常见用法
        code, _, err = _run_ffmpeg(
            ["-i", str(vp), "-i", str(ap), "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)]
        )
        if code != 0:
            return f"音画合成失败: {err}"
        return f"已生成: {out}"

    return "action 必须是 concat 或 merge_av"
