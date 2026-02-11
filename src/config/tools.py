# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import enum
import os

from src.config.loader import load_yaml_config


class SearchEngine(enum.Enum):
    TAVILY = "tavily"
    DUCKDUCKGO = "duckduckgo"
    BRAVE_SEARCH = "brave_search"
    BING = "bing"
    ARXIV = "arxiv"
    SEARX = "searx"
    WIKIPEDIA = "wikipedia"


# 学术/默认搜索：SEARCH_ENGINE（可配置 include_domains 限制学术站）
def _get_search_engine():
    config = load_yaml_config("conf.yaml")
    env_config = config.get("ENV", {})
    return env_config.get("SEARCH_API") or os.getenv("SEARCH_API", SearchEngine.TAVILY.value)


SELECTED_SEARCH_ENGINE = _get_search_engine()


# 通用搜索：GENERAL_SEARCH_ENGINE（选题、热点、失败补救等，不限制学术站；可选 bing、tavily、duckduckgo、brave_search）
def _get_general_search_engine():
    config = load_yaml_config("conf.yaml")
    gen = config.get("GENERAL_SEARCH_ENGINE", {})
    engine = (gen.get("engine") or "").strip() or os.getenv("GENERAL_SEARCH_API", "")
    if engine:
        return engine.lower()
    # 未配置时回退到 ENV.SEARCH_API，避免破坏现有部署
    return _get_search_engine()


SELECTED_GENERAL_SEARCH_ENGINE = _get_general_search_engine()


class RAGProvider(enum.Enum):
    DIFY = "dify"
    RAGFLOW = "ragflow"
    VIKINGDB_KNOWLEDGE_BASE = "vikingdb_knowledge_base"
    MOI = "moi"
    MILVUS = "milvus"


def _get_rag_provider():
    config = load_yaml_config("conf.yaml")
    env_config = config.get("ENV", {})
    return env_config.get("RAG_PROVIDER") or os.getenv("RAG_PROVIDER")

SELECTED_RAG_PROVIDER = _get_rag_provider()

# Semantic Scholar / PDF 抓取配置
def _get_semantic_scholar_key():
    config = load_yaml_config("conf.yaml")
    env_config = config.get("ENV", {})
    return env_config.get("SEMANTIC_SCHOLAR_KEY") or os.getenv("SEMANTIC_SCHOLAR_KEY", "")

def _get_semantic_scholar_api():
    config = load_yaml_config("conf.yaml")
    env_config = config.get("ENV", {})
    return env_config.get("SEMANTIC_SCHOLAR_API") or os.getenv("SEMANTIC_SCHOLAR_API", "https://api.semanticscholar.org/graph/v1")

def _get_pdf_fetch_timeout():
    config = load_yaml_config("conf.yaml")
    env_config = config.get("ENV", {})
    timeout_str = env_config.get("PDF_FETCH_TIMEOUT") or os.getenv("PDF_FETCH_TIMEOUT", "25")
    try:
        return float(timeout_str)
    except (ValueError, TypeError):
        return 25.0

SEMANTIC_SCHOLAR_KEY = _get_semantic_scholar_key()
SEMANTIC_SCHOLAR_API = _get_semantic_scholar_api()
PDF_FETCH_TIMEOUT = _get_pdf_fetch_timeout()
