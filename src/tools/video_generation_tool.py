# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
视频生成工具：调用可配置的云端/本地视频 API（如通义万相、H20 WAN2.2）。
支持异步接口：POST 提交 -> 202 返回 file_id -> 轮询状态 -> GET 下载 MP4。
也兼容同步返回或旧式 task_id 轮询。
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

from langchain_core.tools import tool

from src.config.loader import load_yaml_config

logger = logging.getLogger(__name__)

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
    accept_202: bool = False,
) -> Dict[str, Any]:
    """发起视频生成请求。accept_202 为 True 时 202 视为成功并返回 body。"""
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
        data["image"] = image_base64
    try:
        r = requests.post(url, headers=headers, json=data, timeout=timeout)
        if accept_202 and r.status_code == 202:
            return r.json() if r.content else {}
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
                b64 = body.get("video_base64") or body.get("output", {}).get("base64")
                if b64:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(base64.b64decode(b64))
                    return str(output_path)
            elif status in ("failed", "error"):
                err = body.get("error") or body.get("message") or "任务失败"
                logger.warning("video task failed: %s", err)
                return None
        except Exception as e:
            logger.warning("poll failed: %s", e)
        time.sleep(poll_interval)
    return None


def _poll_and_download_via_download_url(
    base_url: str,
    status_path_tpl: str,
    download_path_tpl: str,
    file_id: str,
    api_key: str,
    output_path: Path,
    poll_interval: int = 5,
    max_wait: int = 600,
) -> Optional[str]:
    """轮询 GET status_path，完成后 GET download_path 下载视频到 output_path。"""
    import requests

    base = base_url.rstrip("/")
    status_url = base + status_path_tpl.replace("{file_id}", file_id)
    download_url = base + download_path_tpl.replace("{file_id}", file_id)
    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    while (time.time() - start) < max_wait:
        try:
            r = requests.get(status_url, headers=headers, timeout=30)
            r.raise_for_status()
            body = r.json()
            status = (body.get("status") or "").lower()
            if status == "completed":
                r2 = requests.get(download_url, headers=headers, timeout=120)
                r2.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(r2.content)
                return str(output_path)
            if status == "failed":
                err = body.get("error") or body.get("message") or "任务失败"
                logger.warning("video task failed: %s", err)
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
    """调用配置的视频生成 API，根据 prompt 生成短视频并保存为 MP4。支持异步接口：提交后 202 返回 file_id，轮询状态完成后从 download 接口下载。"""
    import requests

    cfg = _get_video_config()
    key = api_key or cfg.get("api_key") or ""
    if not key:
        return "未配置 VIDEO_GENERATION（api_key），请在 conf.yaml 中配置或传入 api_key 参数。"

    base_url = cfg.get("base_url", "").rstrip("/")
    submit_path = cfg.get("submit_path", "").strip()
    # 新异步接口：base_url + submit_path（POST 返回 202 + file_id）
    if base_url and submit_path:
        submit_url = base_url + (submit_path if submit_path.startswith("/") else "/" + submit_path)
        timeout = int(cfg.get("timeout", 60))
        resp = _call_video_api(
            url=submit_url,
            api_key=key,
            prompt=prompt,
            image_base64=image_base64,
            size=size or cfg.get("size", "1280*720"),
            timeout=timeout,
            accept_202=True,
        )
        if resp.get("error"):
            return f"请求失败: {resp.get('error')}"
        file_id = resp.get("file_id") or resp.get("task_id") or resp.get("id")
        if file_id:
            status_path = cfg.get("status_path") or "/v1/video/files/{file_id}"
            download_path = cfg.get("download_path") or "/v1/video/files/{file_id}/download"
            root = Path(__file__).resolve().parents[2]
            out_dir = cfg.get("output_dir") or DEFAULT_VIDEO_OUTPUT_DIR
            out_rel = save_relative_path or f"{file_id}.mp4"
            out_path = root / out_dir / out_rel
            delay_minutes = int(cfg.get("deferred_download_minutes", 0))
            if delay_minutes > 0:
                # 延迟下载：由调度器在 N 分钟后检查并下载，返回约定格式供 executor 写入待下载表
                return (
                    f"DEFERRED_VIDEO_DOWNLOAD|{file_id}|{out_path}|{base_url}|{status_path}|{download_path}|{delay_minutes}"
                )
            result = _poll_and_download_via_download_url(
                base_url=base_url,
                status_path_tpl=status_path,
                download_path_tpl=download_path,
                file_id=file_id,
                api_key=key,
                output_path=out_path,
                poll_interval=int(cfg.get("poll_interval", 5)),
                max_wait=int(cfg.get("max_wait", 600)),
            )
            return result if result else "轮询超时或任务失败，未获取到视频文件。"
        return "API 返回 202 但无 file_id，请检查接口。"

    # 兼容旧配置：url 为完整提交地址
    api_url = url or cfg.get("url")
    if not api_url:
        return "未配置 VIDEO_GENERATION（base_url+submit_path 或 url），请在 conf.yaml 中配置。"

    timeout = int(cfg.get("timeout", 60))
    resp = _call_video_api(
        url=api_url,
        api_key=key,
        prompt=prompt,
        image_base64=image_base64,
        size=size or cfg.get("size", "1280*720"),
        timeout=timeout,
    )
    if resp.get("error"):
        return f"请求失败: {resp.get('error')}"

    out = resp.get("output") if isinstance(resp.get("output"), dict) else {}
    video_url = resp.get("video_url") or out.get("url") or resp.get("url")
    if video_url:
        try:
            root = Path(__file__).resolve().parents[2]
            out_dir = cfg.get("output_dir") or DEFAULT_VIDEO_OUTPUT_DIR
            out_rel = save_relative_path or "output.mp4"
            out_path = root / out_dir / out_rel
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
            out_dir = cfg.get("output_dir") or DEFAULT_VIDEO_OUTPUT_DIR
            out_rel = save_relative_path or "output.mp4"
            out_path = root / out_dir / out_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(b64))
            return f"已保存: {out_path}"
        except Exception as e:
            return f"保存失败: {e}"

    task_id = resp.get("task_id") or resp.get("id") or resp.get("data", {}).get("task_id")
    if task_id:
        status_url = cfg.get("status_url") or f"{api_url.rstrip('/')}/{task_id}"
        root = Path(__file__).resolve().parents[2]
        out_dir = cfg.get("output_dir") or DEFAULT_VIDEO_OUTPUT_DIR
        out_rel = save_relative_path or f"{task_id}.mp4"
        out_path = root / out_dir / out_rel
        result = _poll_and_download(
            get_status_url=status_url,
            api_key=key,
            output_path=out_path,
            poll_interval=int(cfg.get("poll_interval", 5)),
            max_wait=int(cfg.get("max_wait", 600)),
        )
        return result if result else "轮询超时或任务失败，未获取到视频文件。"

    return "API 返回格式无法解析（无 video_url / video_base64 / task_id / file_id），请检查接口或配置。"
