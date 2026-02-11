# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
from typing import List, Optional

from pydantic import SecretStr

from langchain_community.tools import (
    BraveSearch,
    DuckDuckGoSearchResults,
    SearxSearchRun,
    WikipediaQueryRun,
)
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.utilities import (
    ArxivAPIWrapper,
    BraveSearchWrapper,
    SearxSearchWrapper,
    WikipediaAPIWrapper,
)

from src.config import (
    SELECTED_SEARCH_ENGINE,
    SELECTED_GENERAL_SEARCH_ENGINE,
    SearchEngine,
    load_yaml_config,
)
from src.config.loader import get_str_env
from src.tools.decorators import create_logged_tool
from src.tools.tavily_search.tavily_search_api_wrapper import EnhancedTavilySearchAPIWrapper
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchWithImages,
)

logger = logging.getLogger(__name__)

# Create logged versions of the search tools
LoggedTavilySearch = create_logged_tool(TavilySearchWithImages)
LoggedDuckDuckGoSearch = create_logged_tool(DuckDuckGoSearchResults)
LoggedBraveSearch = create_logged_tool(BraveSearch)
LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
LoggedSearxSearch = create_logged_tool(SearxSearchRun)
LoggedWikipediaSearch = create_logged_tool(WikipediaQueryRun)


def get_search_config():
    """学术/默认搜索配置（SEARCH_ENGINE，可含 include_domains）。"""
    config = load_yaml_config("conf.yaml")
    return config.get("SEARCH_ENGINE", {})


def get_general_search_config():
    """通用搜索配置（GENERAL_SEARCH_ENGINE，用于选题、热点、失败补救等，不限制学术站）。"""
    config = load_yaml_config("conf.yaml")
    return config.get("GENERAL_SEARCH_ENGINE", {})


# 通用搜索工具：使用 GENERAL_SEARCH_ENGINE（bing / tavily / duckduckgo / brave_search），不限制域名
def get_general_web_search_tool(max_search_results: int):
    """
    用于计划执行、验收/执行失败补救等场景的通用网页搜索。
    引擎由 conf.yaml 的 GENERAL_SEARCH_ENGINE.engine 或环境变量 GENERAL_SEARCH_API 指定。
    支持：bing, tavily, duckduckgo, brave_search。
    """
    gen_config = get_general_search_config()
    engine = (SELECTED_GENERAL_SEARCH_ENGINE or "").strip().lower() or "tavily"

    if engine == SearchEngine.TAVILY.value:
        tavily_key = get_str_env("TAVILY_API_KEY", "").strip() or os.getenv("TAVILY_API_KEY", "")
        kwargs: dict = {
            "name": "web_search",
            "max_results": max_search_results,
            "include_domains": [],  # 通用搜索不限制域名
            "exclude_domains": gen_config.get("exclude_domains", []),
            "include_raw_content": gen_config.get("include_raw_content", True),
            "include_images": gen_config.get("include_images", False),
            "include_image_descriptions": False,
        }
        if tavily_key:
            kwargs["api_wrapper"] = EnhancedTavilySearchAPIWrapper(tavily_api_key=SecretStr(tavily_key))
        logger.info("General search (Tavily): no include_domains")
        return LoggedTavilySearch(**kwargs)

    if engine == SearchEngine.BING.value:
        try:
            from langchain_community.tools.bing_search.tool import BingSearchRun
            from langchain_community.utilities.bing_search import BingSearchAPIWrapper
        except Exception as e:
            logger.warning("Bing search not available: %s", e)
            raise ValueError("通用搜索已配置为 bing，但 Bing 依赖未安装或未配置 BING_SUBSCRIPTION_KEY") from e
        key = os.getenv("BING_SUBSCRIPTION_KEY", "") or get_str_env("BING_SUBSCRIPTION_KEY", "").strip()
        url = (
            os.getenv("BING_SEARCH_URL", "")
            or gen_config.get("bing_search_url", "")
            or "https://api.bing.microsoft.com/v7.0/search"
        )
        if not key:
            raise ValueError("使用 Bing 通用搜索请在 ENV 中配置 BING_SUBSCRIPTION_KEY")
        wrapper = BingSearchAPIWrapper(
            bing_subscription_key=key,
            bing_search_url=url,
            k=max_search_results,
        )
        tool = BingSearchRun(api_wrapper=wrapper, name="web_search")
        logger.info("General search: Bing")
        return create_logged_tool(tool)

    if engine == SearchEngine.DUCKDUCKGO.value:
        logger.info("General search: DuckDuckGo")
        return LoggedDuckDuckGoSearch(name="web_search", num_results=max_search_results)

    if engine == SearchEngine.BRAVE_SEARCH.value:
        logger.info("General search: Brave")
        return LoggedBraveSearch(
            name="web_search",
            search_wrapper=BraveSearchWrapper(
                api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
                search_kwargs={"count": max_search_results},
            ),
        )

    # 未配置或未知引擎时回退到 Tavily 通用（不限制域名）
    logger.info("General search fallback: Tavily (no include_domains)")
    tavily_key = get_str_env("TAVILY_API_KEY", "").strip() or os.getenv("TAVILY_API_KEY", "")
    return LoggedTavilySearch(
        name="web_search",
        max_results=max_search_results,
        include_domains=[],
        exclude_domains=gen_config.get("exclude_domains", []),
        include_raw_content=gen_config.get("include_raw_content", True),
        include_images=False,
        api_wrapper=EnhancedTavilySearchAPIWrapper(tavily_api_key=SecretStr(tavily_key)) if tavily_key else None,
    )


# 学术/默认搜索工具：使用 SEARCH_ENGINE（可配置 include_domains 限制学术站）
def get_web_search_tool(max_search_results: int, general_web: bool = False):
    """
    默认使用 SEARCH_ENGINE 配置（学术或默认引擎）。general_web 为 True 时改为调用通用搜索
    get_general_web_search_tool，便于未配置 GENERAL_SEARCH_ENGINE 时兼容旧逻辑。
    """
    if general_web:
        return get_general_web_search_tool(max_search_results)
    search_config = get_search_config()

    if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
        # API key：优先从 conf.yaml ENV.TAVILY_API_KEY 读取，否则用环境变量（LangChain 默认行为）
        tavily_key = get_str_env("TAVILY_API_KEY", "").strip() or os.getenv("TAVILY_API_KEY", "")
        kwargs: dict = {
            "name": "web_search",
            "max_results": max_search_results,
            "include_raw_content": search_config.get("include_raw_content", True),
            "include_images": search_config.get("include_images", True),
            "include_image_descriptions": (
                search_config.get("include_images", True)
                and search_config.get("include_image_descriptions", True)
            ),
            "include_domains": [] if general_web else search_config.get("include_domains", []),
            "exclude_domains": search_config.get("exclude_domains", []),
        }
        if tavily_key:
            kwargs["api_wrapper"] = EnhancedTavilySearchAPIWrapper(tavily_api_key=SecretStr(tavily_key))

        include_domains = kwargs["include_domains"]
        exclude_domains = kwargs["exclude_domains"]
        logger.info(
            "Tavily search configuration loaded: include_domains=%s, exclude_domains=%s",
            include_domains,
            exclude_domains,
        )
        return LoggedTavilySearch(**kwargs)
    elif SELECTED_SEARCH_ENGINE == SearchEngine.DUCKDUCKGO.value:
        return LoggedDuckDuckGoSearch(
            name="web_search",
            num_results=max_search_results,
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.BRAVE_SEARCH.value:
        return LoggedBraveSearch(
            name="web_search",
            search_wrapper=BraveSearchWrapper(
                api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
                search_kwargs={"count": max_search_results},
            ),
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.ARXIV.value:
        return LoggedArxivSearch(
            name="web_search",
            api_wrapper=ArxivAPIWrapper(
                top_k_results=max_search_results,
                load_max_docs=max_search_results,
                load_all_available_meta=True,
            ),
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.SEARX.value:
        return LoggedSearxSearch(
            name="web_search",
            wrapper=SearxSearchWrapper(
                k=max_search_results,
            ),
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.WIKIPEDIA.value:
        wiki_lang = search_config.get("wikipedia_lang", "en")
        wiki_doc_content_chars_max = search_config.get(
            "wikipedia_doc_content_chars_max", 4000
        )
        return LoggedWikipediaSearch(
            name="web_search",
            api_wrapper=WikipediaAPIWrapper(
                lang=wiki_lang,
                top_k_results=max_search_results,
                load_all_available_meta=True,
                doc_content_chars_max=wiki_doc_content_chars_max,
            ),
        )
    else:
        raise ValueError(f"Unsupported search engine: {SELECTED_SEARCH_ENGINE}")
