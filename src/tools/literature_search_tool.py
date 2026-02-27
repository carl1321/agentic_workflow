"""
Semantic Scholar 文献检索工具（免费 API 友好）

功能：
- 按查询检索文献，返回结构化元数据（标题/作者/年份/DOI/URL/pdf_url/摘要/引用数/来源/sid）
- 对结果进行基础去重（DOI 优先；否则 title+firstAuthor+year 指纹）

注意：
- 免费未授权请求速率较低（约 100 次/5 分钟），易触发 429；建议在 conf.yaml 的 ENV 或环境变量中配置 SEMANTIC_SCHOLAR_KEY（https://www.semanticscholar.org/product/api）
- PDF 链接并非总是可用，需配合 pdf_crawler_tool 做回退
"""

import hashlib
import logging
import os
import time
import typing as t

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 优先从 conf.yaml 的 ENV 读取，其次环境变量（与 src.config.tools 一致）
def _get_semantic_scholar_key() -> str:
    try:
        from src.config.loader import load_yaml_config
        config = load_yaml_config("conf.yaml")
        env_config = config.get("ENV") or {}
        key = (env_config.get("SEMANTIC_SCHOLAR_KEY") or os.getenv("SEMANTIC_SCHOLAR_KEY") or "").strip()
        return key
    except Exception:
        return (os.getenv("SEMANTIC_SCHOLAR_KEY") or "").strip()


def _get_semantic_scholar_api() -> str:
    try:
        from src.config.loader import load_yaml_config
        config = load_yaml_config("conf.yaml")
        env_config = config.get("ENV") or {}
        api = env_config.get("SEMANTIC_SCHOLAR_API") or os.getenv("SEMANTIC_SCHOLAR_API") or "https://api.semanticscholar.org/graph/v1"
        return (api or "").strip() or "https://api.semanticscholar.org/graph/v1"
    except Exception:
        return os.getenv("SEMANTIC_SCHOLAR_API", "https://api.semanticscholar.org/graph/v1")


def _get_timeout() -> float:
    try:
        t_str = os.getenv("SEMANTIC_SCHOLAR_TIMEOUT", "20")
        from src.config.loader import load_yaml_config
        config = load_yaml_config("conf.yaml")
        env_config = config.get("ENV") or {}
        t_str = env_config.get("SEMANTIC_SCHOLAR_TIMEOUT") or t_str
        return float(t_str)
    except Exception:
        return float(os.getenv("SEMANTIC_SCHOLAR_TIMEOUT", "20"))


def _fingerprint(title: str, authors: t.List[str] | None, year: int | None) -> str:
    base = (title or "").strip().lower()
    first_author = (authors[0] if authors else "").strip().lower()
    year_str = str(year) if year else ""
    return hashlib.sha1(f"{base}|{first_author}|{year_str}".encode("utf-8")).hexdigest()


def _request(path: str, params: dict) -> dict:
    api_key = _get_semantic_scholar_key()
    base_url = _get_semantic_scholar_api()
    timeout = _get_timeout()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    for attempt in range(3):
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 429:
            if attempt < 2:
                wait_sec = 5 * (attempt + 1)
                logger.warning("Semantic Scholar 429 (rate limit), retry after %ss (attempt %s/3)", wait_sec, attempt + 1)
                time.sleep(wait_sec)
                continue
            hint = " 建议在 conf.yaml 的 ENV.SEMANTIC_SCHOLAR_KEY 中配置 API Key（https://www.semanticscholar.org/product/api）以提高限速。" if not api_key else ""
            raise requests.HTTPError(
                f"429 Too Many Requests: Semantic Scholar 请求过于频繁，已重试 3 次仍被限流。{hint}",
                response=resp,
            )
        resp.raise_for_status()
        return resp.json()
    return {}


def _normalize_paper(p: dict) -> dict:
    # authors as list[str]
    authors = [a.get("name", "").strip() for a in (p.get("authors") or []) if a and a.get("name")]
    # best pdf url
    oa = p.get("openAccessPdf") or {}
    pdf_url = oa.get("url") or p.get("pdfUrl") or None
    title = p.get("title") or ""
    year = p.get("year")
    doi = p.get("externalIds", {}).get("DOI") if isinstance(p.get("externalIds"), dict) else (p.get("doi") or None)
    citations = p.get("citationCount") or p.get("citations") or None
    abstract = p.get("abstract") or p.get("abstractText") or None
    sid = p.get("paperId") or _fingerprint(title, authors, year)
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": p.get("url") or p.get("s2Url") or None,
        "pdf_url": pdf_url,
        "abstract": abstract,
        "source": "semantic_scholar",
        "citations": citations,
        "sid": sid,
    }


def _dedupe(papers: t.List[dict]) -> t.List[dict]:
    seen: set[str] = set()
    results: list[dict] = []
    for p in papers:
        key = p.get("doi") or p.get("sid") or _fingerprint(p.get("title") or "", p.get("authors"), p.get("year"))
        if key in seen:
            continue
        seen.add(key)
        results.append(p)
    return results


@tool("search_literature", return_direct=False)
def search_literature(query: str, top_k: int = 20) -> str:
    """使用 arXiv 检索文献，返回 JSON 字符串（列表）。

    参数：
    - query: 检索查询语句
    - top_k: 返回最大条数（默认 20）
    """
    if not query or not query.strip():
        return "[]"

    try:
        # 延迟导入，避免在未使用时增加依赖负担
        from langchain_community.retrievers import ArxivRetriever  # type: ignore

        max_k = min(max(top_k, 1), 50)
        retriever = ArxivRetriever(
            top_k_results=max_k,
            load_max_docs=max_k,
            load_all_available_meta=True,
        )

        docs = retriever.get_relevant_documents(query.strip())
        results: list[dict] = []

        for doc in docs:
            meta = getattr(doc, "metadata", {}) or {}
            # arxiv 元数据里有时用 Title / Published / entry_id 等大小写形式
            title = meta.get("title") or meta.get("Title") or ""

            authors = meta.get("authors") or meta.get("Authors") or []
            if isinstance(authors, str):
                authors = [authors]

            year = None
            published = (
                meta.get("Published")
                or meta.get("published")
                or meta.get("published_date")
            )
            if isinstance(published, str):
                # 简单从日期字符串中提取年份
                for part in published.split("-"):
                    part = part.strip()
                    if len(part) == 4 and part.isdigit():
                        year = int(part)
                        break

            url = (
                meta.get("entry_id")
                or meta.get("Entry ID")
                or meta.get("url")
                or (meta.get("links") or [{}])[0].get("href", "")
            )
            pdf_url = meta.get("pdf_url")
            url_str = str(url or "")
            if not pdf_url and "arxiv.org" in url_str:
                if "/abs/" in url_str:
                    pdf_url = url_str.replace("/abs/", "/pdf/") + ".pdf"
                elif "/pdf/" in url_str:
                    # 已经是 pdf 链接，确保以 .pdf 结尾
                    pdf_url = url_str if url_str.endswith(".pdf") else (url_str + ".pdf")

            abstract = meta.get("summary") or meta.get("Summary") or doc.page_content

            result = {
                "title": title,
                "authors": authors,
                "year": year,
                "doi": meta.get("doi"),
                "url": url,
                "pdf_url": pdf_url,
                "abstract": abstract,
                "source": "arxiv",
                "citations": None,
                "sid": meta.get("entry_id") or meta.get("Entry ID") or meta.get("id") or title,
            }
            results.append(result)

        import json as _json

        return _json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.exception("arXiv literature search failed: %s", e)
        return f"[ERROR] arxiv_search failed: {e}"


