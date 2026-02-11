# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
文本转语音工具：支持 Volcengine（商业 API）与 Edge-TTS（开源，免 API key）。
可输出 WAV/MP3，支持 base_dir+relative_path 落盘到计划任务验收路径。
"""

import base64
import logging
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.tools import tool

from src.config.loader import get_str_env, load_yaml_config
from src.tools.tts import EdgeTTS, VolcengineTTS

from .decorators import log_io

logger = logging.getLogger(__name__)


def _get_tts_config():
    """从 conf.yaml 读取 TTS 配置。"""
    cfg = load_yaml_config("conf.yaml")
    return cfg.get("TTS") or {}


def _create_tts_client():
    """根据配置创建 TTS 客户端（Volcengine 或 Edge-TTS）。"""
    cfg = _get_tts_config()
    provider = (cfg.get("provider") or "edge_tts").strip().lower()

    if provider == "volcengine":
        app_id = get_str_env("VOLCENGINE_TTS_APPID", "")
        access_token = get_str_env("VOLCENGINE_TTS_ACCESS_TOKEN", "")
        if not app_id or not access_token:
            logger.warning("TTS provider=volcengine 但未配置 VOLCENGINE_TTS_APPID/ACCESS_TOKEN，回退到 edge_tts")
            provider = "edge_tts"

    if provider == "edge_tts":
        edge_cfg = cfg.get("edge_tts") or {}
        voice = edge_cfg.get("voice") or "zh-CN-XiaoxiaoNeural"
        return "edge_tts", EdgeTTS(voice=voice)

    cluster = get_str_env("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
    voice_type = get_str_env("VOLCENGINE_TTS_VOICE_TYPE", "BV700_V2_streaming")
    return "volcengine", VolcengineTTS(
        appid=get_str_env("VOLCENGINE_TTS_APPID", ""),
        access_token=get_str_env("VOLCENGINE_TTS_ACCESS_TOKEN", ""),
        cluster=cluster,
        voice_type=voice_type,
    )


@tool
@log_io
def tts_tool(
    text: Annotated[str, "要转为语音的文本内容"],
    voice: Annotated[
        Optional[str],
        "语音类型：'male'/'female'。edge_tts 时忽略，使用配置的 voice。",
    ] = "female",
    encoding: Annotated[
        Optional[str],
        "音频格式：'mp3' 或 'wav'。默认为 'mp3'。",
    ] = "mp3",
    base_dir: Annotated[
        Optional[str],
        "与 relative_path 一起使用，写入指定目录（如 outputs），用于计划任务验收",
    ] = None,
    relative_path: Annotated[
        Optional[str],
        "与 base_dir 一起使用，如 plans/{plan_id}/xxx.wav；写入后验收会检查该文件",
    ] = None,
) -> str:
    """文本转语音，支持 WAV/MP3。默认使用 edge-tts（开源，免 API key）；可配置为火山引擎。传 base_dir+relative_path 可落盘到计划任务验收路径。"""
    try:
        provider_name, tts_client = _create_tts_client()

        if provider_name == "volcengine":
            result = tts_client.text_to_speech(text=text[:1024], encoding=encoding)
        else:
            result = tts_client.text_to_speech(text=text[:1024], encoding=encoding)

        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            logger.error(f"TTS error ({provider_name}): {error_msg}")
            return f"TTS转换失败: {error_msg}"

        audio_data = result.get("audio_data")
        if not audio_data:
            return "TTS转换失败: 未返回音频数据"

        audio_bytes = base64.b64decode(audio_data)
        audio_size = len(audio_bytes)
        logger.info(f"TTS conversion successful ({provider_name}), size: {audio_size} bytes")

        if base_dir and relative_path:
            root = Path(__file__).resolve().parents[2]
            out_path = (root / base_dir / relative_path).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.suffix.lower() not in (".wav", ".mp3"):
                out_path = out_path.with_suffix(f".{encoding}" if encoding else ".mp3")
            out_path.write_bytes(audio_bytes)
            return f"已保存: {out_path}（{audio_size} 字节，格式: {encoding}）"

        return f"TTS转换成功！音频数据已生成（{audio_size} 字节，格式: {encoding}）。传 base_dir+relative_path 可落盘到指定路径。"
    except Exception as e:
        logger.exception("tts_tool failed: %s", e)
        return f"错误：{repr(e)}"
