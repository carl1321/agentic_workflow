# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
视频生成工具：调用可配置的云端/本地视频 API（如通义万相、H20 WAN2.2）。
支持 prompt、可选图生视频、轮询任务状态、下载 MP4 到本地。
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

from langchain_core.tools import tool

from src.config.loader import load_yaml_config

logger = logging.getLogger(__name__)

# 默认保存目录
DEFAULT_VIDEO_OUTPUT_DIR = "temp/video_generations"


def _get_video_config() -> Dict[str, Any]:
    try:
        conf = load_yaml_config("conf.yaml")
        return conf.get("VIDEO_GENERATION") or {}
    except Exception:
        return {}


def _call_video_api(
    url: str,
    api_key: str,
    prompt: str,
    image_base64: Optional[str] = None,
    size: str = "1280*720",
    timeout: int = 60,
) -> Dict[str, Any]:
    """同步发起视频生成请求。部分 API 返回 task_id 需轮询。"""
    import requests

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data: Dict[str, Any] = {
        "prompt": prompt,
        "size": size,
    }
    if image_base64:
        data["image"] = image_base64  # 或 image_url，视 API 而定
    try:
        r = requests.post(url, headers=headers, json=data, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("video API request failed: %s", e)
        return {"error": str(e)}


def _poll_and_download(
    get_status_url: str,
    api_key: str,
    output_path: Path,
    poll_interval: int = 5,
    max_wait: int = 600,
) -> Optional[str]:
    """轮询任务状态并在完成时下载 MP4。返回最终文件路径或 None。"""
    import requests

    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    while (time.time() - start) < max_wait:
        try:
            r = requests.get(get_status_url, headers=headers, timeout=30)
            r.raise_for_status()
            body = r.json()
            status = body.get("status", "").lower()
            if status in ("succeeded", "completed", "done"):
                video_url = body.get("video_url") or body.get("output", {}).get("url") or body.get("url")
                if video_url:
                    r2 = requests.get(video_url, timeout=60)
                    r2.raise_for_status()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(r2.content)
                    return str(output_path)
                # 有的 API 直接返回 base64
                b64 = body.get("video_base64") or body.get("output", {}).get("base64")
                if b64:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(base64.b64decode(b64))
                    return str(output_path)
            elif status in ("failed", "error"):
                return None
        except Exception as e:
            logger.warning("poll failed: %s", e)
        time.sleep(poll_interval)
    return None


@tool
def video_generation_tool(
    prompt: Annotated[str, "视频描述提示词，如：一位剑修在竹林间御剑飞行，动漫风格"],
    size: Annotated[str, "分辨率，如 1280*720"] = "1280*720",
    image_base64: Annotated[Optional[str], "可选，图生视频时的 base64 图片"] = None,
    save_relative_path: Annotated[Optional[str], "保存到 temp/video_generations 下的相对路径，如 episode01/clip1.mp4"] = None,
    url: Annotated[Optional[str], "覆盖配置的 API 地址"] = None,
    api_key: Annotated[Optional[str], "覆盖配置的 API Key"] = None,
) -> str:
    """调用配置的视频生成 API（如通义万相、H20），根据 prompt 生成短视频片段，并保存为 MP4。若 API 返回 task_id，会轮询状态并下载到 temp/video_generations。"""
    cfg = _get_video_config()
    api_url = url or cfg.get("url")
    key = api_key or cfg.get("api_key") or ""
    if not api_url or not key:
        return "未配置 VIDEO_GENERATION（url / api_key），请在 conf.yaml 中配置或传入 url、api_key 参数。"

    timeout = int(cfg.get("timeout", 60))
    resp = _call_video_api(
        url=api_url,
        api_key=key,
        prompt=prompt,
        image_base64=image_base64,
        size=size,
        timeout=timeout,
    )
    if resp.get("error"):
        return f"请求失败: {resp.get('error')}"

    # 若直接返回视频 URL 或 base64
    out = resp.get("output") if isinstance(resp.get("output"), dict) else {}
    video_url = resp.get("video_url") or out.get("url") or resp.get("url")
    if video_url:
        try:
            import requests
            root = Path(__file__).resolve().parents[2]
            out_rel = save_relative_path or "output.mp4"
            out_path = root / DEFAULT_VIDEO_OUTPUT_DIR / out_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            r = requests.get(video_url, timeout=120)
            r.raise_for_status()
            out_path.write_bytes(r.content)
            return f"已保存: {out_path}"
        except Exception as e:
            return f"下载失败: {e}"

    b64 = resp.get("video_base64") or out.get("base64")
    if b64:
        try:
            root = Path(__file__).resolve().parents[2]
            out_rel = save_relative_path or "output.mp4"
            out_path = root / DEFAULT_VIDEO_OUTPUT_DIR / out_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(b64))
            return f"已保存: {out_path}"
        except Exception as e:
            return f"保存失败: {e}"

    # 异步任务：轮询
    task_id = resp.get("task_id") or resp.get("id") or resp.get("data", {}).get("task_id")
    if task_id:
        status_url = cfg.get("status_url") or f"{api_url.rstrip('/')}/{task_id}"
        root = Path(__file__).resolve().parents[2]
        out_rel = save_relative_path or f"{task_id}.mp4"
        out_path = root / DEFAULT_VIDEO_OUTPUT_DIR / out_rel
        result = _poll_and_download(
            get_status_url=status_url,
            api_key=key,
            output_path=out_path,
            poll_interval=int(cfg.get("poll_interval", 5)),
            max_wait=int(cfg.get("max_wait", 600)),
        )
        return result if result else "轮询超时或任务失败，未获取到视频文件。"

    return "API 返回格式无法解析（无 video_url / video_base64 / task_id），请检查接口或配置。"
