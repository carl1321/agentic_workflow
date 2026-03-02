# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import logging
import os
from typing import List, Optional, Union

from langchain_community.tools import BraveSearch
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.utilities import (
    ArxivAPIWrapper,
    BraveSearchWrapper,
)
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, SecretStr

from src.config import SELECTED_SEARCH_ENGINE, SearchEngine, load_yaml_config
from src.tools.search import get_web_search_tool
from src.tools.decorators import create_logged_tool
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchWithImages,
)
from src.tools.tavily_search.tavily_search_api_wrapper import (
    EnhancedTavilySearchAPIWrapper,
)

logger = logging.getLogger(__name__)

# Create logged versions of the search tools
LoggedTavilySearch = create_logged_tool(TavilySearchWithImages)
LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
LoggedBraveSearch = create_logged_tool(BraveSearch)

# 学术检索优先/排除的域名（与 get_literature_search_tool 一致，供 Tavily 学术检索使用）
ACADEMIC_INCLUDE_DOMAINS = [
    "arxiv.org",
    "scholar.google.com",
    "pubmed.ncbi.nlm.nih.gov",
    "ieee.org",
    "acm.org",
    "springer.com",
    "nature.com",
    "science.org",
    "cell.com",
    "elsevier.com",
    "wiley.com",
    "sagepub.com",
    "tandfonline.com",
    "researchgate.net",
    "academia.edu",
    "edu.cn",
    "edu",
]
ACADEMIC_EXCLUDE_DOMAINS = [
    "wikipedia.org",
    "reddit.com",
    "quora.com",
    "stackoverflow.com",
    "medium.com",
    "blogspot.com",
    "wordpress.com",
    "tumblr.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
]


def _format_tavily_results_to_string(raw: dict) -> str:
    """将 Tavily raw_results 格式化为可读字符串，便于 LLM 使用。"""
    results = raw.get("results") or []
    if not results:
        return "未找到相关结果。"
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title") or ""
        url = r.get("url") or ""
        content = (r.get("content") or "")[:2000]
        lines.append(f"{i}. [{title}]({url})\n{content}")
    return "\n\n".join(lines)


def _tavily_academic_search(
    query: str,
    max_results: int,
    api_key: str,
) -> str:
    """单次 Tavily 学术检索，使用学术域名偏好。"""
    if not (api_key and api_key.strip()):
        return "Error: TAVILY_API_KEY 未配置，无法执行学术检索。"
    try:
        wrapper = EnhancedTavilySearchAPIWrapper(
            tavily_api_key=SecretStr(api_key),
        )
        raw = wrapper.raw_results(
            query,
            max_results=max_results,
            search_depth="advanced",
            include_domains=ACADEMIC_INCLUDE_DOMAINS,
            exclude_domains=ACADEMIC_EXCLUDE_DOMAINS,
            include_raw_content=True,
            include_images=False,
            include_image_descriptions=False,
        )
        return _format_tavily_results_to_string(raw)
    except Exception as e:
        logger.warning("Tavily academic search failed: %s", e)
        return f"学术检索失败: {e!s}"


def get_literature_search_tool(max_search_results: int, literature_focus: bool = True):
    """
    文献调研专用搜索工具
    - 优先使用学术来源（arXiv、Google Scholar等）
    - 增加学术站点权重
    - 过滤非学术来源
    """
    
    if literature_focus:
        logger.info("Using literature-focused search with academic priority")
        
        # Academic domains to prioritize
        academic_domains = [
            "arxiv.org",
            "scholar.google.com", 
            "pubmed.ncbi.nlm.nih.gov",
            "ieee.org",
            "acm.org",
            "springer.com",
            "nature.com",
            "science.org",
            "cell.com",
            "elsevier.com",
            "wiley.com",
            "sagepub.com",
            "tandfonline.com",
            "researchgate.net",
            "academia.edu",
            "edu.cn",  # Chinese academic institutions
            "edu",     # General educational institutions
        ]
        
        # Non-academic domains to exclude or deprioritize
        exclude_domains = [
            "wikipedia.org",  # Keep for basic definitions but deprioritize
            "reddit.com",
            "quora.com", 
            "stackoverflow.com",  # Keep for technical but not academic
            "medium.com",
            "blogspot.com",
            "wordpress.com",
            "tumblr.com",
            "facebook.com",
            "twitter.com",
            "instagram.com",
            "youtube.com",
            "tiktok.com",
        ]
        
        # Configure search based on selected engine
        if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
            return LoggedTavilySearch(
                name="literature_search",
                max_results=max_search_results,
                include_raw_content=True,
                include_images=False,  # Academic content rarely needs images
                include_image_descriptions=False,
                include_domains=academic_domains,
                exclude_domains=exclude_domains,
            )
        elif SELECTED_SEARCH_ENGINE == SearchEngine.ARXIV.value:
            # Arxiv is already academic-focused
            return LoggedArxivSearch(
                name="literature_search",
                api_wrapper=ArxivAPIWrapper(
                    top_k_results=max_search_results,
                    load_max_docs=max_search_results,
                    load_all_available_meta=True,
                ),
            )
        elif SELECTED_SEARCH_ENGINE == SearchEngine.BRAVE_SEARCH.value:
            # Brave search with academic focus
            return LoggedBraveSearch(
                name="literature_search",
                search_wrapper=BraveSearchWrapper(
                    api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
                    search_kwargs={
                        "count": max_search_results,
                        "safesearch": "moderate",  # Academic content
                    },
                ),
            )
        else:
            # Fallback to regular search
            logger.warning(f"Literature focus not fully supported for {SELECTED_SEARCH_ENGINE}, using regular search")
            return get_web_search_tool(max_search_results)
    else:
        # Use regular search without academic focus
        return get_web_search_tool(max_search_results)


# arXiv 检索仅支持英文简短关键词（2–8 词），不支持中文或长句；需先转英文再查
_ARXIV_QUERY_MAX_WORDS = 8
_ARXIV_LEADING_STOP = (
    "what is ", "what are ", "how to ", "how do ", "how does ", "why ", "when ",
    "where ", "which ", "who ", "can you ", "could you ", "please ",
    "什么是", "有哪些", "怎么", "如何", "为什么", "哪些", "请",
)
_ARXIV_TO_ENGLISH_PROMPT = """Convert the following search topic into 2-8 English keywords suitable for arXiv paper search. Output ONLY the keywords on one line (e.g. "perovskite solar cell efficiency stability"), no explanation, no quotes. arXiv does NOT support Chinese or long sentences."""


def _has_cjk(text: str) -> bool:
    """判断是否包含中日韩字符（arXiv 不支持，必须转成英文关键词）。"""
    if not text:
        return False
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f":
            return True
    return False


def _query_to_english_keywords(normalized_query: str) -> str:
    """将查询转为英文简短术语（2–8 词），失败时返回原串。"""
    if not normalized_query or not _has_cjk(normalized_query):
        return normalized_query
    try:
        from langchain_core.messages import HumanMessage
        from src.llms.llm import get_llm_by_type

        llm = get_llm_by_type("basic")
        prompt = _ARXIV_TO_ENGLISH_PROMPT + "\n\nTopic: " + (normalized_query.strip()[:500])
        out = llm.invoke([HumanMessage(content=prompt)])
        text = (out.content or "").strip()
        if not text:
            return normalized_query
        first_line = text.split("\n")[0].strip()
        words = []
        for w in first_line.split():
            clean = "".join(c for c in w if c.isalnum() or c in ".-")
            if clean:
                words.append(clean)
        result = " ".join(words[:_ARXIV_QUERY_MAX_WORDS])
        return result if result else normalized_query
    except Exception as e:
        logger.warning("arxiv_query to English keywords failed, using original: %s", e)
        return normalized_query


def _normalize_arxiv_query(query: str) -> str:
    """规范为 arXiv 适用的短关键词（2–8 词）。arXiv 仅支持英文简短关键词，中文或长句会先转成英文。"""
    if not query or not isinstance(query, str):
        return query or ""
    s = query.strip().rstrip("?.,;:!").strip()
    if not s:
        return query
    s_lower = s.lower()
    for lead in _ARXIV_LEADING_STOP:
        if s_lower.startswith(lead):
            s = s[len(lead) :].strip()
            s_lower = s.lower()
            break
    words = s.split()
    if len(words) > _ARXIV_QUERY_MAX_WORDS:
        s = " ".join(words[: _ARXIV_QUERY_MAX_WORDS])
    s = s.strip() or query.strip()
    # 中文或含 CJK 时必须转成英文简短关键词，否则 arXiv 无法检索
    if _has_cjk(s):
        en = _query_to_english_keywords(s)
        if en and en != s:
            logger.info("arxiv_search query -> English: %r -> %r", s[:80], en[:80])
            return en
    return s


def _arxiv_search_with_retriever(query: str, top_k: int) -> str:
    """使用 ArxivRetriever 执行检索（与 literature_search_tool 一致），失败时返回错误信息。"""
    if not (query or "").strip():
        return "No query provided."
    try:
        from langchain_community.retrievers import ArxivRetriever  # type: ignore

        max_k = min(max(top_k, 1), 50)
        retriever = ArxivRetriever(
            top_k_results=max_k,
            load_max_docs=max_k,
            load_all_available_meta=True,
        )
        docs = retriever.get_relevant_documents(query.strip())
        if not docs:
            return "No arXiv results found for the query."
        lines = []
        for i, doc in enumerate(docs, 1):
            meta = getattr(doc, "metadata", {}) or {}
            title = meta.get("title") or meta.get("Title") or ""
            summary = meta.get("summary") or meta.get("Summary") or (doc.page_content or "")[:500]
            entry_id = meta.get("entry_id") or meta.get("Entry ID") or meta.get("url") or ""
            lines.append(f"{i}. {title}\n   {entry_id}\n   {summary}")
        return "\n\n".join(lines)
    except Exception as e:
        logger.warning("arxiv_search fallback (ArxivRetriever) failed: %s", e)
        return f"[ERROR] arxiv_search failed: {e}"


def get_arxiv_search_tool(max_search_results: int):
    """创建 arXiv 专用搜索工具；内部会对 query 做短关键词规范化以适配 arXiv 检索。"""
    base = LoggedArxivSearch(
        name="arxiv_search",
        api_wrapper=ArxivAPIWrapper(
            top_k_results=max_search_results,
            load_max_docs=max_search_results,
            load_all_available_meta=True,
        ),
    )

    def _get_query(inp) -> str:
        if isinstance(inp, dict):
            return (inp.get("query") or "").strip()
        return (getattr(inp, "query", None) or "").strip()

    def _invoke_sync(query: str) -> str:
        """StructuredTool 会按 args_schema 将参数以关键字传入，此处为 query。"""
        raw = (query or "").strip() if isinstance(query, str) else _get_query(query)
        q = _normalize_arxiv_query(raw)
        if not (q or "").strip():
            logger.warning("arxiv_search: empty query after normalize, skipping")
            return "No query provided or query was empty after normalization."
        if q != raw:
            logger.info("arxiv_search query normalized: %r -> %r", raw[:80], q[:80])
        try:
            return base.invoke({"query": q})
        except Exception as e:
            logger.warning("arxiv_search (ArxivQueryRun) failed, fallback to ArxivRetriever: %s", e)
            return _arxiv_search_with_retriever(q, max_search_results)

    async def _ainvoke_async(query: str) -> str:
        """StructuredTool 会按 args_schema 将参数以关键字传入，此处为 query。"""
        raw = (query or "").strip() if isinstance(query, str) else _get_query(query)
        q = _normalize_arxiv_query(raw)
        if not (q or "").strip():
            logger.warning("arxiv_search: empty query after normalize, skipping")
            return "No query provided or query was empty after normalization."
        if q != raw:
            logger.info("arxiv_search query normalized: %r -> %r", raw[:80], q[:80])
        try:
            # 在线程中执行同步调用，避免 ArxivQueryRun/arxiv 在 async 下的兼容问题
            return await asyncio.to_thread(base.invoke, {"query": q})
        except Exception as e:
            logger.warning("arxiv_search (ArxivQueryRun) failed, fallback to ArxivRetriever: %s", e)
            return await asyncio.to_thread(_arxiv_search_with_retriever, q, max_search_results)

    class _ArxivInput(BaseModel):
        query: str = Field(description="English short keywords only, 2-8 terms, e.g. 'perovskite solar cell efficiency'. No Chinese.")

    return StructuredTool(
        name="arxiv_search",
        description="Search arXiv for papers. English only: use 2-8 short English keywords (e.g. 'perovskite solar cell efficiency'). Do NOT use Chinese or long phrases; arXiv does not support them.",
        args_schema=_ArxivInput,
        func=_invoke_sync,
        coroutine=_ainvoke_async,
    )


# 文献调研工具优先级配置（已移除 google_scholar，统一使用 web_search + arxiv_search）
LITERATURE_RESEARCH_TOOLS = [
    "web_search",
    "arxiv_search",
    "literature_search",
    "crawl_tool",
    "python_repl",
]


def get_literature_research_tools(max_search_results: int, literature_focus: bool = True):
    """
    获取文献调研工具列表：web_search、arxiv_search，可选 literature_search（学术偏好）。
    """
    tools = []
    if literature_focus:
        tools.extend([
            get_web_search_tool(max_search_results),
            get_arxiv_search_tool(max_search_results),
            get_literature_search_tool(max_search_results, literature_focus=True),
        ])
    else:
        tools.append(get_web_search_tool(max_search_results))
    return tools
