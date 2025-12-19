# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
from typing import List, Optional

from langchain_community.tools import BraveSearch
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.utilities import (
    ArxivAPIWrapper,
    BraveSearchWrapper,
)

from src.config import SELECTED_SEARCH_ENGINE, SearchEngine, load_yaml_config
from src.tools.decorators import create_logged_tool
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchWithImages,
)

logger = logging.getLogger(__name__)

# Create logged versions of the search tools
LoggedTavilySearch = create_logged_tool(TavilySearchWithImages)
LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
LoggedBraveSearch = create_logged_tool(BraveSearch)


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


def get_google_scholar_tool(max_search_results: int):
    """
    创建Google Scholar搜索工具
    注意：这需要Google Scholar的API访问权限
    """
    # 这里可以集成Google Scholar API
    # 目前使用Brave Search作为替代，因为它包含学术来源
    logger.info("Using Brave Search as Google Scholar alternative")
    
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
