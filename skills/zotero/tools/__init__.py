# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Zotero literature tool: search, get_detail, analyze."""

import json
import logging
import os
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _get_zotero_config() -> dict:
    """Load Zotero config from conf.yaml and env. Env overrides YAML."""
    try:
        from src.config.loader import load_yaml_config

        config = load_yaml_config("conf.yaml")
        zotero_block = config.get("ZOTERO") or {}
        if not isinstance(zotero_block, dict):
            zotero_block = {}
    except Exception as e:
        logger.warning("Failed to load ZOTERO config from conf.yaml: %s", e)
        zotero_block = {}

    library_id = os.getenv("ZOTERO_LIBRARY_ID") or zotero_block.get("library_id") or ""
    library_type = os.getenv("ZOTERO_LIBRARY_TYPE") or zotero_block.get("library_type") or "user"
    api_key = os.getenv("ZOTERO_API_KEY") or zotero_block.get("api_key") or ""
    return {
        "library_id": str(library_id).strip(),
        "library_type": str(library_type).strip().lower() or "user",
        "api_key": str(api_key).strip(),
    }


def _zotero_client():
    """Create Zotero client from config."""
    cfg = _get_zotero_config()
    if not cfg["library_id"] or not cfg["api_key"]:
        raise ValueError(
            "Zotero not configured. Set ZOTERO.library_id and ZOTERO.api_key in conf.yaml, "
            "or ZOTERO_LIBRARY_ID and ZOTERO_API_KEY env vars."
        )
    from pyzotero import Zotero

    return Zotero(cfg["library_id"], cfg["library_type"], cfg["api_key"])


def _normalize_item(item: dict, attachment_count: int = 0) -> dict:
    """Normalize Zotero item to a simple dict for JSON output."""
    data = item.get("data") or item
    meta = item.get("meta") or {}
    creators = data.get("creators") or []
    authors = []
    for c in creators:
        name = c.get("name") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
        if name:
            authors.append(name)
    count = attachment_count or meta.get("numChildren", 0) or len(item.get("children", []))
    return {
        "key": data.get("key", ""),
        "itemType": data.get("itemType", ""),
        "title": data.get("title", ""),
        "authors": authors,
        "year": data.get("date", "")[:4] if data.get("date") else None,
        "abstract": data.get("abstractNote", ""),
        "url": data.get("url", ""),
        "doi": data.get("DOI", ""),
        "publicationTitle": data.get("publicationTitle", ""),
        "attachment_count": count,
    }


def _do_search(zot, query: str, item_type: Optional[str], limit: int) -> str:
    """Search items and return JSON string."""
    params = {"q": query.strip(), "limit": min(max(limit, 1), 100)}
    if item_type and item_type.strip():
        params["itemType"] = item_type.strip()
    items = zot.top(**params)
    out = []
    for it in items:
        out.append(_normalize_item(it))
    return json.dumps(out, ensure_ascii=False)


def _do_list(zot, limit: int, item_type: Optional[str]) -> str:
    """List top-level items without search query (recent/available items)."""
    params = {"limit": min(max(limit, 1), 100)}
    if item_type and item_type.strip():
        params["itemType"] = item_type.strip()
    items = zot.top(**params)
    out = []
    for it in items:
        out.append(_normalize_item(it))
    return json.dumps(out, ensure_ascii=False)


def _do_get_detail(zot, item_key: str, attachment_key: Optional[str]) -> str:
    """Get item detail and optionally fulltext for one attachment."""
    raw = zot.item(item_key)
    if not raw:
        return json.dumps({"error": f"Item not found: {item_key}"}, ensure_ascii=False)
    item = raw[0] if isinstance(raw, list) else raw
    data = item.get("data") or item
    children = zot.children(item_key)
    attachments = []
    for c in children:
        cd = c.get("data") or c
        att = {
            "key": cd.get("key", ""),
            "filename": cd.get("filename", cd.get("title", "")),
            "contentType": cd.get("contentType", ""),
        }
        attachments.append(att)

    result = _normalize_item(item, attachment_count=len(attachments))
    result["attachments"] = attachments
    result["extra"] = data.get("extra", "")
    result["tags"] = [t.get("tag", "") for t in (data.get("tags") or []) if t and t.get("tag")]

    fulltext = None
    if attachment_key and attachment_key.strip():
        try:
            ft = zot.fulltext_item(attachment_key.strip())
            if isinstance(ft, dict) and ft.get("content"):
                fulltext = ft.get("content", "")
        except Exception as e:
            logger.warning("Fulltext fetch failed for %s: %s", attachment_key, e)
            fulltext = f"(Fulltext not indexed or error: {e})"

    if fulltext is not None:
        result["fulltext"] = fulltext[:50000] if len(fulltext or "") > 50000 else (fulltext or "")

    return json.dumps(result, ensure_ascii=False)


def _do_analyze(
    zot,
    item_keys: str,
    analysis_type: str,
    custom_prompt: Optional[str],
) -> str:
    """Fetch items and run LLM analysis."""
    keys = [k.strip() for k in item_keys.split(",") if k.strip()]
    if not keys:
        return json.dumps({"error": "No item_keys provided"}, ensure_ascii=False)

    try:
        items_raw = zot.get_subset(keys[:50])
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch items: {e}"}, ensure_ascii=False)

    if not items_raw:
        return json.dumps({"error": "No items found for given keys"}, ensure_ascii=False)

    parts = []
    for it in items_raw:
        meta = _normalize_item(it)
        data = it.get("data") or it
        parts.append(
            f"--- {meta.get('title', '')} ---\n"
            f"Authors: {', '.join(meta.get('authors', []))}\n"
            f"Year: {meta.get('year', '')}\n"
            f"Abstract: {meta.get('abstract', '')}\n"
            f"Key: {meta.get('key', '')}\n"
        )
        # Optionally fetch first attachment fulltext
        key = meta.get("key", "")
        if key:
            try:
                children = zot.children(key)
                for c in children:
                    cd = c.get("data") or c
                    if cd.get("contentType") == "application/pdf":
                        try:
                            ft = zot.fulltext_item(cd.get("key", ""))
                            if isinstance(ft, dict) and ft.get("content"):
                                content = ft.get("content", "")
                                parts.append(f"Fulltext (excerpt): {content[:8000]}...\n")
                                break
                        except Exception:
                            pass
            except Exception:
                pass

    literature_text = "\n".join(parts)

    if analysis_type == "custom" and custom_prompt and custom_prompt.strip():
        user_prompt = f"Literature:\n{literature_text}\n\nQuestion: {custom_prompt.strip()}"
    elif analysis_type == "compare":
        user_prompt = (
            "Compare and contrast the following literature. Identify similarities and differences (比较异同). "
            "Provide a clear, structured comparison.\n\n"
            f"{literature_text}"
        )
    elif analysis_type == "key_findings":
        user_prompt = (
            "Extract and list the key findings (关键发现) from each paper. "
            "Focus on main conclusions, notable results, and important contributions.\n\n"
            f"{literature_text}"
        )
    else:
        user_prompt = (
            "Summarize the abstract of each article (总结文章摘要). "
            "Provide a concise summary of the main content and purpose of each paper.\n\n"
            f"{literature_text}"
        )

    try:
        from src.llms.llm import get_llm_by_type

        llm = get_llm_by_type("basic")
        messages = [
            SystemMessage(content="You are a literature analysis assistant. Respond in a clear, structured way."),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        result = response.content if hasattr(response, "content") else str(response)
        # 兼容 content 为 list 的情况（多模态模型）
        if isinstance(result, list):
            texts = []
            for block in result:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif isinstance(block, str):
                    texts.append(block)
            result_str = "\n".join(texts) if texts else str(response)
        else:
            result_str = result if isinstance(result, str) else str(result)
        if not result_str or not result_str.strip():
            logger.warning(
                "LLM analyze returned empty content, response type=%s, content type=%s",
                type(response).__name__,
                type(result).__name__,
            )
        return result_str
    except Exception as e:
        logger.exception("LLM analyze failed: %s", e)
        return json.dumps({"error": f"LLM analysis failed: {e}"}, ensure_ascii=False)


@tool("zotero_literature_tool", return_direct=False)
def zotero_literature_tool(
    action: str,
    query: str = "",
    item_key: str = "",
    attachment_key: str = "",
    item_keys: str = "",
    analysis_type: str = "summary",
    custom_prompt: str = "",
    item_type: str = "",
    limit: int = 20,
) -> str:
    """Zotero literature tool: list, search, get detail/fulltext, or analyze.

    Actions:
    - list: List top-level items (no query). Optional: limit, item_type.
    - search: Search library. Requires query. Optional: item_type, limit.
    - get_detail: Get item metadata and attachments. Requires item_key. Optional: attachment_key for fulltext.
    - analyze: LLM analysis of items. Requires item_keys. Optional: analysis_type (summary|compare|key_findings|custom), custom_prompt when custom.
    """
    action = (action or "").strip().lower()
    if not action:
        return json.dumps({"error": "action is required (search, get_detail, analyze)"}, ensure_ascii=False)

    try:
        zot = _zotero_client()
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    if action == "list":
        return _do_list(zot, limit, item_type or None)

    if action == "search":
        if not query or not query.strip():
            return json.dumps({"error": "query is required for action=search"}, ensure_ascii=False)
        return _do_search(zot, query, item_type or None, limit)

    if action == "get_detail":
        if not item_key or not item_key.strip():
            return json.dumps({"error": "item_key is required for action=get_detail"}, ensure_ascii=False)
        return _do_get_detail(zot, item_key.strip(), attachment_key.strip() or None)

    if action == "analyze":
        if not item_keys or not item_keys.strip():
            return json.dumps({"error": "item_keys is required for action=analyze"}, ensure_ascii=False)
        return _do_analyze(zot, item_keys, analysis_type or "summary", custom_prompt or None)

    return json.dumps({"error": f"Unknown action: {action}. Use list, search, get_detail, or analyze."}, ensure_ascii=False)


def get_tools():
    """Return tools for skill loader."""
    return [zotero_literature_tool]
