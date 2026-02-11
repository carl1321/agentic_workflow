# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
文生图工具：调用可配置的文生图 API（POST /v1/images/generations），
根据 prompt 生成图片并保存为 PNG，返回本地文件路径。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Annotated, Any, Dict, Optional, Tuple

from langchain_core.tools import tool

from src.config.loader import load_yaml_config

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_OUTPUT_DIR = "temp/image_generations"
# 服务端 5xx / 连接/超时 时的重试次数与间隔（秒）
IMAGE_API_MAX_RETRIES = 3
IMAGE_API_RETRY_BACKOFF = [1, 2, 3]  # 第 1、2、3 次重试前的等待秒数


def _get_image_config() -> Dict[str, Any]:
    try:
        conf = load_yaml_config("conf.yaml")
        return conf.get("IMAGE_GENERATION") or {}
    except Exception:
        return {}


def _normalize_base_url(url: str) -> str:
    """修正 base_url 中常见的 host/:port 为 host:port，避免请求发到 port=80、路径 /:port/..."""
    if not url or "/:" not in url:
        return (url or "").rstrip("/")
    # 例如 "http://122.193.22.114/:8889" -> "http://122.193.22.114:8889"
    return url.replace("/:", ":").rstrip("/")


def _call_image_api(
    base_url: str,
    api_key: str,
    prompt: str,
    height: int = 1024,
    width: int = 1024,
    num_inference_steps: int = 9,
    seed: int = 42,
    timeout: int = 120,
) -> Tuple[bool, Optional[bytes], Optional[str]]:
    """
    同步请求文生图 API，返回 (成功, 图片二进制, 错误信息)。
    对 5xx 及连接/超时错误进行最多 3 次重试，重试前有退避等待。
    API 响应为 PNG 二进制（Content-Type: image/png）。
    """
    import requests

    base = _normalize_base_url(base_url)
    url = f"{base}/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data: Dict[str, Any] = {
        "prompt": prompt,
        "height": height,
        "width": width,
        "num_inference_steps": num_inference_steps,
        "seed": seed,
    }
    last_error: Optional[str] = None
    for attempt in range(IMAGE_API_MAX_RETRIES):
        try:
            r = requests.post(url, headers=headers, json=data, timeout=timeout)
            if r.status_code >= 500:
                last_error = f"{r.status_code} Server Error: {r.reason or 'Internal Server Error'} for url: {r.url}"
                if attempt < IMAGE_API_MAX_RETRIES - 1:
                    backoff = IMAGE_API_RETRY_BACKOFF[attempt] if attempt < len(IMAGE_API_RETRY_BACKOFF) else (attempt + 1)
                    logger.warning("image generation API 5xx (attempt %s/%s), retry in %ss: %s", attempt + 1, IMAGE_API_MAX_RETRIES, backoff, last_error)
                    time.sleep(backoff)
                    continue
                logger.warning("image generation API request failed after %s attempts: %s", IMAGE_API_MAX_RETRIES, last_error)
                return (False, None, last_error)
            r.raise_for_status()
            return (True, r.content, None)
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            if attempt < IMAGE_API_MAX_RETRIES - 1:
                backoff = IMAGE_API_RETRY_BACKOFF[attempt] if attempt < len(IMAGE_API_RETRY_BACKOFF) else (attempt + 1)
                logger.warning("image generation API request failed (attempt %s/%s), retry in %ss: %s", attempt + 1, IMAGE_API_MAX_RETRIES, backoff, e)
                time.sleep(backoff)
                continue
            logger.warning("image generation API request failed after %s attempts: %s", IMAGE_API_MAX_RETRIES, e)
            return (False, None, last_error)
    return (False, None, last_error or "unknown error")


@tool
def image_generation_tool(
    prompt: Annotated[str, "图片描述提示词，如：一只可爱的猫咪在阳光下"],
    height: Annotated[Optional[int], "图片高度（像素）"] = None,
    width: Annotated[Optional[int], "图片宽度（像素）"] = None,
    num_inference_steps: Annotated[Optional[int], "推理步数"] = None,
    seed: Annotated[Optional[int], "随机种子，用于复现"] = None,
    save_relative_path: Annotated[
        Optional[str],
        "保存到配置 output_dir 下的相对路径，如 scene01.png；与 base_dir/relative_path 二选一",
    ] = None,
    base_dir: Annotated[
        Optional[str],
        "与 relative_path 一起使用，直接写入指定目录（如 outputs），用于计划任务验收路径",
    ] = None,
    relative_path: Annotated[
        Optional[str],
        "与 base_dir 一起使用，相对 base_dir 的路径，如 plans/{plan_id}/xxx.png；写入后验收会检查该文件",
    ] = None,
    base_url: Annotated[Optional[str], "覆盖配置的 API base_url"] = None,
    api_key: Annotated[Optional[str], "覆盖配置的 API Key"] = None,
) -> str:
    """调用配置的文生图 API，根据 prompt 生成图片并保存为 PNG。若传 base_dir+relative_path 则写入该路径（供计划任务验收）；否则写入 temp/image_generations。"""
    cfg = _get_image_config()
    api_base = _normalize_base_url(base_url or cfg.get("base_url") or "")
    key = api_key or cfg.get("api_key") or ""
    if not api_base or not key:
        return "未配置 IMAGE_GENERATION（base_url / api_key），请在 conf.yaml 中配置或传入 base_url、api_key 参数。"

    height = height if height is not None else int(cfg.get("height", 1024))
    width = width if width is not None else int(cfg.get("width", 1024))
    num_inference_steps = num_inference_steps if num_inference_steps is not None else int(cfg.get("num_inference_steps", 9))
    seed = seed if seed is not None else int(cfg.get("seed", 42))
    timeout = int(cfg.get("timeout", 120))
    output_dir = cfg.get("output_dir") or DEFAULT_IMAGE_OUTPUT_DIR

    ok, content, err = _call_image_api(
        base_url=api_base,
        api_key=key,
        prompt=prompt,
        height=height,
        width=width,
        num_inference_steps=num_inference_steps,
        seed=seed,
        timeout=timeout,
    )
    if not ok or content is None:
        return f"请求失败: {err or '未返回图片数据'}"

    root = Path(__file__).resolve().parents[2]
    if base_dir and relative_path:
        out_path = root / base_dir / relative_path
    else:
        out_dir = root / output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        if save_relative_path:
            out_path = out_dir / save_relative_path
        else:
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in prompt[:20]).strip() or "image"
            out_path = out_dir / f"{safe_name}_seed{seed}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    return f"已保存: {out_path}"
