# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Slide-deck 工具：baoyu 风格整页图片幻灯片。
流程：outline（含 STYLE_INSTRUCTIONS）→ prompts → 每页 16:9 图片 → Python 合并为 PPTX/PDF。
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.llms.llm import get_llm_by_type
from src.tools.image_gen_tool import generate_image_to_path, is_image_gen_configured
from src.tools.slide_deck_merge import merge_images_to_pdf, merge_images_to_pptx

logger = logging.getLogger(__name__)

SLIDE_DECK_DIR = "slide_deck"
SLIDE_IMAGE_SIZE_16_9 = "1792x1024"  # DMX/Gemini 常用 16:9
_REF_DIR = Path(__file__).resolve().parent.parent / "third_party" / "baoyu_slide_deck" / "references"


def _topic_to_slug(topic: str) -> str:
    """将主题转为目录名：小写、空格与非法字符替换为连字符。"""
    s = (topic or "slides").strip()[:80]
    s = re.sub(r"[^\w\s\-]", "", s)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    return s or "slides"


def _load_base_prompt() -> str:
    """加载 baoyu base-prompt 模板。"""
    p = _REF_DIR / "base-prompt.md"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return "Create a 16:9 presentation slide image. Professional, clear layout. One message per slide."


OUTLINE_SYSTEM = """你是一个专业的幻灯片大纲撰写助手，产出与 baoyu-slide-deck 兼容的 outline。
要求：
1. 使用 Markdown。第一行用一级标题（# ）写整份演示的标题。
2. 紧接着包含一个代码块，用于 STYLE_INSTRUCTIONS。格式如下：
```
STYLE_INSTRUCTIONS
- Design: 简洁/蓝图/手绘等（与 style 一致）
- Background: 背景描述与主色
- Typography: 标题与正文字体风格
- Color: 主色与辅色（可写 hex）
- Density: minimal/balanced/dense
- Do: 2-3 条必须遵守的规则
- Don't: 2-3 条禁止项
```
3. 然后每一页幻灯片用一个二级标题：## 1. 页面标题、## 2. 页面标题 …，标题下用列表写该页要点（- 或 *），每页 2-5 个要点。
4. 总页数按用户要求的 slides 数量（含封面），通常 5-12 页。
5. 只输出大纲内容，不要多余解释。"""


IMAGE_PROMPT_SYSTEM = """你是幻灯片配图助手。根据给定的「单页幻灯片规格」（含风格说明 STYLE_INSTRUCTIONS 和该页内容），生成一句用于文生图的英文 prompt。
要求：一句话描述该页要呈现的视觉画面，体现风格与关键信息，适合 16:9 幻灯片。不要包含「slide」「page」等元信息。只输出这一句英文，不要解释。"""


class SlideDeckInput(BaseModel):
    """Slide-deck 工具入参。"""

    topic: str = Field(default="", description="一句话主题；与 content 二选一。")
    content: str = Field(default="", description="长文/Markdown 内容；与 topic 二选一，优先 content。")
    outline: str = Field(default="", description="已有大纲（如用户编辑后）；若提供则跳过生成 outline 步骤。")
    style: str = Field(default="blueprint", description="风格预设：blueprint, minimal, hand-drawn 等。")
    audience: str = Field(default="general", description="受众：general, beginners, intermediate, experts, executives。")
    lang: str = Field(default="auto", description="语言：zh, en, auto。")
    slides: int = Field(default=8, ge=3, le=20, description="目标页数（含封面）。")
    outline_only: bool = Field(default=False, description="若为 true，只生成并返回 outline。")
    prompts_only: bool = Field(default=False, description="若为 true，生成 outline 与 prompts 后即返回，不生成图片。")
    images_only: bool = Field(default=False, description="若为 true，生成图片后即返回，不合并 pptx/pdf。")


def _generate_outline(topic: str, content: str, style: str, audience: str, lang: str, slides: int) -> str:
    """用 LLM 生成带 STYLE_INSTRUCTIONS 的 outline。"""
    llm = get_llm_by_type("basic")
    user_content = content.strip() if content else f"主题：{topic.strip()}"
    if not user_content:
        raise ValueError("请提供 topic 或 content")
    human = (
        f"请生成 {slides} 页左右的幻灯片大纲。\n"
        f"风格 style={style}，受众 audience={audience}，语言 lang={lang}。\n\n"
        f"内容或主题：\n{user_content}"
    )
    messages = [SystemMessage(content=OUTLINE_SYSTEM), HumanMessage(content=human)]
    resp = llm.invoke(messages)
    text = (resp.content if hasattr(resp, "content") else str(resp)) or ""
    return text.strip()


def _parse_outline(outline: str) -> dict[str, Any]:
    """解析 outline：提取 STYLE_INSTRUCTIONS 与 slides 列表。"""
    text = outline.strip()
    title = ""
    style_block = ""
    slides_list: list[dict[str, str]] = []
    lines = text.split("\n")

    # 第一行 # 标题
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("# ") and not title:
            title = line.lstrip("# ").strip()
            start = i + 1
            break

    # 找 ``` 代码块（STYLE_INSTRUCTIONS）
    rest_start = start
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("```"):
            block_end = i + 1
            while block_end < len(lines) and lines[block_end].strip() != "```":
                block_end += 1
            if block_end < len(lines):
                block_end += 1
            style_block = "\n".join(lines[i:block_end])
            rest_start = block_end
            break

    rest = "\n".join(lines[rest_start:])

    # 按 ## N. 分割幻灯片（支持 rest 开头就是 ## 1. 的情况，用 (?:^|\n) 匹配首或换行后）
    parts = re.split(r"(?:\n|^)##\s*\d+\.\s*", rest)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        first_line = part.split("\n")[0].strip()
        body = "\n".join(part.split("\n")[1:]).strip()
        slides_list.append({"title": first_line, "content": body})

    if not slides_list and title:
        slides_list = [{"title": title, "content": ""}]

    return {"title": title or "Presentation", "style_instructions": style_block, "slides": slides_list}


def _generate_slide_image_prompt(slide_title: str, slide_content: str, style_instructions: str) -> str:
    """根据单页规格生成一句文生图 prompt。"""
    llm = get_llm_by_type("basic")
    content = (
        f"STYLE_INSTRUCTIONS:\n{style_instructions[:1500]}\n\n"
        f"本页标题: {slide_title}\n本页要点:\n{slide_content[:800]}"
    )
    messages = [SystemMessage(content=IMAGE_PROMPT_SYSTEM), HumanMessage(content=content)]
    resp = llm.invoke(messages)
    text = (resp.content if hasattr(resp, "content") else str(resp)) or ""
    return text.strip()[:500]


def _run_slide_deck(
    topic: str = "",
    content: str = "",
    outline: str = "",
    style: str = "blueprint",
    audience: str = "general",
    lang: str = "auto",
    slides: int = 8,
    outline_only: bool = False,
    prompts_only: bool = False,
    images_only: bool = False,
) -> str:
    """执行 slide-deck 流程，返回 JSON。"""
    cwd = Path(os.getcwd()).resolve()
    topic = (topic or "").strip()
    content = (content or "").strip()
    outline_text = (outline or "").strip()

    # 确定 slug 与工作目录：有 outline 时从大纲标题推导 slug，否则需要 topic 或 content
    if outline_text:
        parsed_for_slug = _parse_outline(outline_text)
        title = (parsed_for_slug.get("title") or "").strip()
        slug = _topic_to_slug(title[:80]) if title else "slides"
    else:
        source = content if content else topic
        if not source:
            return json.dumps({"error": "请提供 topic 或 content"}, ensure_ascii=False)
        slug = _topic_to_slug(source[:80])
    work_dir = cwd / SLIDE_DECK_DIR / slug
    work_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = work_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Outline
        if not outline_text:
            outline_text = _generate_outline(topic, content, style, audience, lang, slides)
        outline_path = work_dir / "outline.md"
        outline_path.write_text(outline_text, encoding="utf-8")

        if outline_only:
            rel_outline = f"{SLIDE_DECK_DIR}/{slug}/outline.md"
            return json.dumps(
                {
                    "outline": outline_text,
                    "outline_path": rel_outline,
                    "outline_download_url": f"/api/workspace-file?path={rel_outline}",
                    "slug": slug,
                },
                ensure_ascii=False,
            )

        parsed = _parse_outline(outline_text)
        style_instructions = parsed.get("style_instructions") or ""
        slides_list = parsed.get("slides") or []

        # 2. Prompts
        for i, slide in enumerate(slides_list):
            idx = i + 1
            prompt_content = _load_base_prompt()
            prompt_content += "\n\n## STYLE_INSTRUCTIONS\n\n" + style_instructions
            prompt_content += "\n\n## SLIDE CONTENT\n\n" + f"Slide {idx}: {slide.get('title', '')}\n\n{slide.get('content', '')}"
            prompt_path = prompts_dir / f"{idx:02d}-slide-{idx:02d}.md"
            prompt_path.write_text(prompt_content, encoding="utf-8")

        if prompts_only:
            return json.dumps(
                {
                    "outline": outline_text,
                    "slug": slug,
                    "prompts_count": len(slides_list),
                    "message": "已生成 outline 与 prompts，可下一步生成图片。",
                },
                ensure_ascii=False,
            )

        # 3. Images（需要 IMAGE_GEN）
        if not is_image_gen_configured():
            return json.dumps(
                {"error": "生成幻灯片图片需要配置 IMAGE_GEN（conf.yaml 中 api_key、provider 等）", "slug": slug},
                ensure_ascii=False,
            )
        preview_urls = []
        for i, slide in enumerate(slides_list):
            idx = i + 1
            short_prompt = _generate_slide_image_prompt(
                slide.get("title", ""), slide.get("content", ""), style_instructions
            )
            if not short_prompt:
                short_prompt = f"Professional slide: {slide.get('title', '')}"
            try:
                rel_path = generate_image_to_path(short_prompt, size=SLIDE_IMAGE_SIZE_16_9)
                # 复制/移动到 slide_deck/slug/01-slide-01.png
                src = cwd / rel_path
                dest_name = f"{idx:02d}-slide-{idx:02d}.png"
                dest = work_dir / dest_name
                if src.is_file():
                    dest.write_bytes(src.read_bytes())
                preview_urls.append(f"/api/workspace-file?path={SLIDE_DECK_DIR}/{slug}/{dest_name}")
            except Exception as e:
                logger.warning("幻灯片 %d 图片生成失败: %s", idx, e)

        if images_only:
            return json.dumps(
                {
                    "slug": slug,
                    "slides_preview_urls": preview_urls,
                    "message": "已生成图片，可下一步合并为 pptx/pdf。",
                },
                ensure_ascii=False,
            )

        # 4. Merge
        try:
            pptx_path = merge_images_to_pptx(work_dir, slug)
            pdf_path = merge_images_to_pdf(work_dir, slug)
        except FileNotFoundError as e:
            return json.dumps({"error": str(e), "slug": slug}, ensure_ascii=False)
        except Exception as e:
            logger.exception("合并 pptx/pdf 失败")
            return json.dumps({"error": f"合并失败: {e!s}", "slug": slug}, ensure_ascii=False)

        rel_pptx = f"{SLIDE_DECK_DIR}/{slug}/{slug}.pptx"
        rel_pdf = f"{SLIDE_DECK_DIR}/{slug}/{slug}.pdf"
        return json.dumps(
            {
                "pptx_download_url": f"/api/workspace-file?path={rel_pptx}",
                "pdf_download_url": f"/api/workspace-file?path={rel_pdf}",
                "filename_pptx": f"{slug}.pptx",
                "filename_pdf": f"{slug}.pdf",
                "slides_preview_urls": preview_urls,
                "slug": slug,
            },
            ensure_ascii=False,
        )
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.exception("slide_deck 执行异常")
        return json.dumps({"error": f"执行失败: {e!s}"}, ensure_ascii=False)


slide_deck_tool = StructuredTool(
    name="slide_deck_tool",
    description="生成 baoyu 风格整页图片幻灯片：outline（可含 STYLE_INSTRUCTIONS）→ prompts → 每页 16:9 图片 → 合并为 PPTX/PDF。支持 outline_only/prompts_only/images_only 分步执行。需配置 IMAGE_GEN。",
    args_schema=SlideDeckInput,
    func=_run_slide_deck,
)
