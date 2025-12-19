# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import base64
import logging
from typing import Annotated, Optional

from langchain_core.tools import tool

from src.config.loader import get_str_env
from src.tools.tts import VolcengineTTS

from .decorators import log_io

logger = logging.getLogger(__name__)


@tool
@log_io
def tts_tool(
    text: Annotated[str, "The text to convert to speech."],
    voice: Annotated[
        Optional[str],
        "Voice type: 'male' or 'female'. Defaults to 'female'.",
    ] = "female",
    encoding: Annotated[
        Optional[str],
        "Audio encoding format: 'mp3' or 'wav'. Defaults to 'mp3'.",
    ] = "mp3",
) -> str:
    """Convert text to speech using Volcengine TTS API.
    
    This tool takes text input and converts it to speech audio.
    Returns a message indicating success or failure.
    """
    try:
        # Get TTS configuration from environment variables
        app_id = get_str_env("VOLCENGINE_TTS_APPID", "")
        access_token = get_str_env("VOLCENGINE_TTS_ACCESS_TOKEN", "")

        if not app_id:
            error_msg = "VOLCENGINE_TTS_APPID environment variable is not set. Please configure it in .env file."
            logger.error(error_msg)
            return error_msg

        if not access_token:
            error_msg = "VOLCENGINE_TTS_ACCESS_TOKEN environment variable is not set. Please configure it in .env file."
            logger.error(error_msg)
            return error_msg

        # Get optional configuration
        cluster = get_str_env("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
        voice_type = get_str_env("VOLCENGINE_TTS_VOICE_TYPE", "BV700_V2_streaming")

        # Map voice parameter to voice type if needed
        # Note: Volcengine TTS uses specific voice types, so we keep the configured voice_type
        # The 'voice' parameter is kept for API compatibility but may not directly map to voice_type

        # Initialize TTS client
        tts_client = VolcengineTTS(
            appid=app_id,
            access_token=access_token,
            cluster=cluster,
            voice_type=voice_type,
        )

        # Call TTS API
        logger.info(f"Converting text to speech, length: {len(text)}")
        result = tts_client.text_to_speech(
            text=text[:1024],  # Limit text length
            encoding=encoding,
        )

        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            logger.error(f"TTS API error: {error_msg}")
            return f"TTS转换失败: {error_msg}"

        # Get audio data
        audio_data = result.get("audio_data")
        if not audio_data:
            error_msg = "TTS API returned no audio data"
            logger.error(error_msg)
            return f"TTS转换失败: {error_msg}"

        # Decode base64 audio data to get size info
        try:
            audio_bytes = base64.b64decode(audio_data)
            audio_size = len(audio_bytes)
            logger.info(f"TTS conversion successful, audio size: {audio_size} bytes")
            return f"TTS转换成功！音频数据已生成（{audio_size} 字节，格式: {encoding}）。音频数据为base64编码，可在前端进行播放。"
        except Exception as e:
            logger.error(f"Error decoding audio data: {e}")
            return f"TTS转换成功，但处理音频数据时出错: {str(e)}"

    except Exception as e:
        error_msg = f"Failed to convert text to speech: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return f"错误：{error_msg}"

