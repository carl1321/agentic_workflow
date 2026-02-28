# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""文生图工具：根据文本 prompt 调用图像 API，保存到 image_output/ 并返回下载链接。"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.config.loader import load_yaml_config

logger = logging.getLogger(__name__)

IMAGE_OUTPUT_DIR = "image_output"


# DMXAPI 文档：模型列表 https://www.dmxapi.cn/rmb ，使用说明 https://doc.dmxapi.cn/kaishi.html
# 图像生成为 OpenAI 兼容接口，base_url 为 https://www.dmxapi.cn/v1
DMX_IMAGE_DEFAULT_BASE_URL = "https://www.dmxapi.cn/v1"
DMX_IMAGE_DEFAULT_MODEL = "gemini-3.1-flash-image-preview"


def _get_image_gen_config() -> dict:
    """从 conf.yaml 读取 IMAGE_GEN 配置；环境变量可作为 api_key 回退。"""
    config = load_yaml_config("conf.yaml") or {}
    image_gen = config.get("IMAGE_GEN") or {}
    if not isinstance(image_gen, dict):
        return {}
    provider = (image_gen.get("provider") or "openai").strip().lower()
    api_key = (image_gen.get("api_key") or "").strip()
    if not api_key:
        api_key = os.getenv("DMX_API_KEY", "").strip() if provider == "dmx" else os.getenv("OPENAI_API_KEY", "").strip()
    if api_key:
        image_gen = {**image_gen, "api_key": api_key}
    return image_gen


def _generate_image_openai(prompt: str, api_key: str, base_url: Optional[str], model: str, size: str) -> bytes:
    """调用 OpenAI 兼容的 images API，返回图片二进制内容。"""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请安装 openai: uv add openai")
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")
    client = OpenAI(**client_kwargs)
    kwargs = {
        "prompt": prompt,
        "model": model or "dall-e-3",
        "n": 1,
        "size": size or "1024x1024",
    }
    if (model or "").lower().startswith("dall-e-3"):
        kwargs["quality"] = "standard"
        kwargs["response_format"] = "b64_json"
    else:
        kwargs["response_format"] = "b64_json"
    resp = client.images.generate(**kwargs)
    if not resp.data or len(resp.data) == 0:
        raise ValueError("API 未返回图片数据")
    b64 = getattr(resp.data[0], "b64_json", None)
    if b64:
        import base64
        return base64.b64decode(b64)
    url = getattr(resp.data[0], "url", None)
    if url:
        import httpx
        r = httpx.get(url, timeout=60)
        r.raise_for_status()
        return r.content
    raise ValueError("API 返回中既无 b64_json 也无 url")


def is_image_gen_configured() -> bool:
    """是否已配置 IMAGE_GEN（供幻灯片增强等判断是否可生成配图）。"""
    return bool((_get_image_gen_config().get("api_key") or "").strip())


def generate_image_to_path(prompt: str, size: str = "1024x1024") -> str:
    """
    根据 prompt 调用配置的 IMAGE_GEN API，将图片保存到 image_output/ 并返回相对路径。
    供文生图工具与幻灯片增强共用。未配置或调用失败时抛出异常。
    """
    cfg = _get_image_gen_config()
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("请在 conf.yaml 中配置 IMAGE_GEN（api_key、provider、model）")
    provider = (cfg.get("provider") or "openai").strip().lower()
    model = (cfg.get("model") or "dall-e-3").strip()
    base_url = (cfg.get("base_url") or "").strip() or None
    size = (size or cfg.get("size") or "1024x1024").strip()

    if provider == "dmx":
        base_url = base_url or DMX_IMAGE_DEFAULT_BASE_URL
        model = model or DMX_IMAGE_DEFAULT_MODEL
        content = _generate_image_openai(prompt, api_key, base_url, model, size)
    elif provider == "openai":
        content = _generate_image_openai(prompt, api_key, base_url, model, size)
    else:
        raise ValueError(f"暂不支持的 IMAGE_GEN.provider: {provider}，当前仅支持 openai、dmx")

    cwd = Path(os.getcwd()).resolve()
    out_dir = cwd / IMAGE_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "png"
    filename = f"img_{uuid.uuid4().hex[:12]}.{ext}"
    filepath = out_dir / filename
    filepath.write_bytes(content)
    relative_path = f"{IMAGE_OUTPUT_DIR}/{filename}"
    return relative_path


class ImageGenInput(BaseModel):
    """文生图工具入参。"""

    prompt: str = Field(..., description="图片描述（英文或中文）")
    size: str = Field(default="1024x1024", description="图片尺寸，如 1024x1024、1792x1024")
    n: int = Field(default=1, description="生成张数，当前仅支持 1")


def _run_image_gen(prompt: str = "", size: str = "1024x1024", n: int = 1) -> str:
    """StructuredTool 按 schema 关键字参数调用。"""
    prompt = (prompt or "").strip()
    if not prompt:
        return json.dumps({"error": "prompt 不能为空"}, ensure_ascii=False)
    if n != 1:
        return json.dumps({"error": "当前仅支持 n=1，生成一张图片"}, ensure_ascii=False)
    try:
        relative_path = generate_image_to_path(prompt, size=size)
        download_url = f"/api/workspace-file?path={relative_path}"
        filename = Path(relative_path).name
        return json.dumps(
            {"download_url": download_url, "filename": filename, "path": relative_path},
            ensure_ascii=False,
        )
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.exception("文生图失败")
        return json.dumps({"error": f"文生图失败: {e!s}"}, ensure_ascii=False)


image_gen_tool = StructuredTool(
    name="image_gen_tool",
    description="根据文本描述生成图片并返回下载链接。需在 conf.yaml 中配置 IMAGE_GEN（provider、api_key、model）。",
    args_schema=ImageGenInput,
    func=_run_image_gen,
)
