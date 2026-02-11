# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Text-to-Speech module: 支持 Volcengine（商业 API）与 Edge-TTS（开源，免 API key）。
"""

import asyncio
import base64
import json
import logging
import subprocess
import tempfile
from pathlib import Path
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class VolcengineTTS:
    """
    Client for volcengine Text-to-Speech API.
    """

    def __init__(
        self,
        appid: str,
        access_token: str,
        cluster: str = "volcano_tts",
        voice_type: str = "BV700_V2_streaming",
        host: str = "openspeech.bytedance.com",
    ):
        """
        Initialize the volcengine TTS client.

        Args:
            appid: Platform application ID
            access_token: Access token for authentication
            cluster: TTS cluster name
            voice_type: Voice type to use
            host: API host
        """
        self.appid = appid
        self.access_token = access_token
        self.cluster = cluster
        self.voice_type = voice_type
        self.host = host
        self.api_url = f"https://{host}/api/v1/tts"
        self.header = {"Authorization": f"Bearer;{access_token}"}

    def text_to_speech(
        self,
        text: str,
        encoding: str = "mp3",
        speed_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        pitch_ratio: float = 1.0,
        text_type: str = "plain",
        with_frontend: int = 1,
        frontend_type: str = "unitTson",
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert text to speech using volcengine TTS API.

        Args:
            text: Text to convert to speech
            encoding: Audio encoding format
            speed_ratio: Speech speed ratio
            volume_ratio: Speech volume ratio
            pitch_ratio: Speech pitch ratio
            text_type: Text type (plain or ssml)
            with_frontend: Whether to use frontend processing
            frontend_type: Frontend type
            uid: User ID (generated if not provided)

        Returns:
            Dictionary containing the API response and base64-encoded audio data
        """
        if not uid:
            uid = str(uuid.uuid4())

        request_json = {
            "app": {
                "appid": self.appid,
                "token": self.access_token,
                "cluster": self.cluster,
            },
            "user": {"uid": uid},
            "audio": {
                "voice_type": self.voice_type,
                "encoding": encoding,
                "speed_ratio": speed_ratio,
                "volume_ratio": volume_ratio,
                "pitch_ratio": pitch_ratio,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": text_type,
                "operation": "query",
                "with_frontend": with_frontend,
                "frontend_type": frontend_type,
            },
        }

        try:
            sanitized_text = text.replace("\r\n", "").replace("\n", "")
            logger.debug(f"Sending TTS request for text: {sanitized_text[:50]}...")
            response = requests.post(
                self.api_url, json.dumps(request_json), headers=self.header
            )
            response_json = response.json()

            if response.status_code != 200:
                logger.error(f"TTS API error: {response_json}")
                return {"success": False, "error": response_json, "audio_data": None}

            if "data" not in response_json:
                logger.error(f"TTS API returned no data: {response_json}")
                return {
                    "success": False,
                    "error": "No audio data returned",
                    "audio_data": None,
                }

            return {
                "success": True,
                "response": response_json,
                "audio_data": response_json["data"],  # Base64 encoded audio data
            }

        except Exception as e:
            logger.exception(f"Error in TTS API call: {str(e)}")
            return {"success": False, "error": "TTS API call error", "audio_data": None}


class EdgeTTS:
    """
    开源 TTS：使用 Microsoft Edge 在线语音服务，免 API key。
    支持中英文及多种语音，输出 MP3；需 WAV 时内部用 ffmpeg 转换。
    """

    # 常用中文语音
    VOICE_ZH_FEMALE = "zh-CN-XiaoxiaoNeural"
    VOICE_ZH_MALE = "zh-CN-YunxiNeural"
    VOICE_ZH_MALE_NEWS = "zh-CN-YunyangNeural"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    def text_to_speech(
        self,
        text: str,
        encoding: str = "mp3",
        rate: str = "+0%",
        volume: str = "+0%",
    ) -> Dict[str, Any]:
        """
        同步调用 edge-tts 生成语音。
        返回格式与 VolcengineTTS 兼容：{"success": bool, "audio_data": base64 str, "error": str}
        encoding 为 wav 时，内部先生成 mp3 再用 ffmpeg 转为 wav。
        """
        import sys
        try:
            import edge_tts
        except ImportError:
            logger.info("edge-tts 未安装，尝试自动安装: pip install edge-tts")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "edge-tts"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except Exception as install_err:
                logger.warning("自动安装 edge-tts 失败: %s", install_err)
                return {"success": False, "error": "请安装 edge-tts: pip install edge-tts", "audio_data": None}
            try:
                import edge_tts
            except ImportError:
                return {"success": False, "error": "请安装 edge-tts: pip install edge-tts", "audio_data": None}

        async def _run():
            communicate = edge_tts.Communicate(text=text[:1024], voice=self.voice, rate=rate, volume=volume)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_mp3 = f.name
            try:
                await communicate.save(tmp_mp3)
                with open(tmp_mp3, "rb") as f:
                    audio_bytes = f.read()
                if encoding.lower() == "wav":
                    # 用 ffmpeg 转 mp3 -> wav
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
                        tmp_wav = wf.name
                    try:
                        r = subprocess.run(
                            ["ffmpeg", "-y", "-i", tmp_mp3, "-acodec", "pcm_s16le", "-ar", "44100", tmp_wav],
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if r.returncode == 0:
                            with open(tmp_wav, "rb") as f:
                                audio_bytes = f.read()
                        else:
                            logger.warning("ffmpeg mp3->wav failed, using mp3: %s", r.stderr)
                    finally:
                        Path(tmp_wav).unlink(missing_ok=True)
                return {"success": True, "audio_data": base64.b64encode(audio_bytes).decode(), "error": None}
            finally:
                Path(tmp_mp3).unlink(missing_ok=True)

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=120)
        except Exception as e:
            logger.exception("EdgeTTS failed: %s", e)
            return {"success": False, "error": str(e), "audio_data": None}
