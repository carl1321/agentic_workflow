# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

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


class _GoogleScholarInput(BaseModel):
    """兼容原有 google_scholar 的入参：支持单条或多条查询。"""
    query: Union[str, List[str]] = Field(
        description="The search query or list of queries for academic literature."
    )


def get_google_scholar_tool(max_search_results: int):
    """
    创建学术文献检索工具。
    - 当 SEARCH_API=tavily 且已配置 TAVILY_API_KEY 时，使用 Tavily 学术检索（学术域名偏好）。
    - 否则回退到 Brave Search（需 BRAVE_SEARCH_API_KEY）。
    """
    config = load_yaml_config("conf.yaml")
    env = config.get("ENV", {})
    tavily_key = env.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY", "")

    if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value and (tavily_key and tavily_key.strip()):
        logger.info("Using Tavily (TAVILY_API_KEY) for academic literature search")

        def _run(query: Union[str, List[str]]) -> str:
            queries = [query] if isinstance(query, str) else list(query)
            if not queries:
                return "请提供至少一条检索词。"
            parts = []
            for q in queries:
                q = (q or "").strip()
                if not q:
                    continue
                logger.info("google_scholar (Tavily) query: %s", q[:200])
                part = _tavily_academic_search(q, max_search_results, tavily_key)
                parts.append(f"## 检索: {q}\n\n{part}")
            return "\n\n=======\n\n".join(parts) if parts else "未提供有效检索词。"

        return StructuredTool(
            name="google_scholar",
            description="Leverage academic search (Tavily) to retrieve relevant information from academic publications. Accepts a single query or a list of queries.",
            args_schema=_GoogleScholarInput,
            func=lambda inp: _run(inp.query),
        )
    else:
        logger.info("Using Brave Search as Google Scholar fallback (configure TAVILY_API_KEY and SEARCH_API=tavily for Tavily academic search)")
        return LoggedBraveSearch(
            name="google_scholar",
            search_wrapper=BraveSearchWrapper(
                api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
                search_kwargs={
                    "count": max_search_results,
                    "safesearch": "moderate",
                },
            ),
        )


def get_arxiv_search_tool(max_search_results: int):
    """创建arXiv专用搜索工具"""
    return LoggedArxivSearch(
        name="arxiv_search",
        api_wrapper=ArxivAPIWrapper(
            top_k_results=max_search_results,
            load_max_docs=max_search_results,
            load_all_available_meta=True,
        ),
    )


# 文献调研工具优先级配置
LITERATURE_RESEARCH_TOOLS = [
    "google_scholar",  # 优先
    "arxiv_search",
    "literature_search",  # 学术优先的通用搜索
    "web_search",      # 补充
    "crawl_tool",
    "python_repl"      # 数据分析
]


def get_literature_research_tools(max_search_results: int, literature_focus: bool = True):
    """
    获取文献调研工具列表，按优先级排序
    """
    tools = []
    
    if literature_focus:
        # 学术优先工具
        tools.extend([
            get_google_scholar_tool(max_search_results),
            get_arxiv_search_tool(max_search_results),
            get_literature_search_tool(max_search_results, literature_focus=True),
        ])
    else:
        # 标准工具
        tools.append(get_web_search_tool(max_search_results))
    
    return tools
