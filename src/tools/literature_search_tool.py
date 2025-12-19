"""
Semantic Scholar 文献检索工具（免费 API 友好）

功能：
- 按查询检索文献，返回结构化元数据（标题/作者/年份/DOI/URL/pdf_url/摘要/引用数/来源/sid）
- 对结果进行基础去重（DOI 优先；否则 title+firstAuthor+year 指纹）

注意：
- 免费未授权请求速率较低，建议配置 SEMANTIC_SCHOLAR_KEY（可为空）
- PDF 链接并非总是可用，需配合 pdf_crawler_tool 做回退
"""

import hashlib
import os
import typing as t

import requests
from langchain_core.tools import tool


SEMANTIC_SCHOLAR_API = os.getenv("SEMANTIC_SCHOLAR_API", "https://api.semanticscholar.org/graph/v1")
SEMANTIC_SCHOLAR_KEY = os.getenv("SEMANTIC_SCHOLAR_KEY", "")
SEMANTIC_SCHOLAR_TIMEOUT = float(os.getenv("SEMANTIC_SCHOLAR_TIMEOUT", "20"))


def _fingerprint(title: str, authors: t.List[str] | None, year: int | None) -> str:
    base = (title or "").strip().lower()
    first_author = (authors[0] if authors else "").strip().lower()
    year_str = str(year) if year else ""
    return hashlib.sha1(f"{base}|{first_author}|{year_str}".encode("utf-8")).hexdigest()


def _request(path: str, params: dict) -> dict:
    headers = {"Accept": "application/json"}
    if SEMANTIC_SCHOLAR_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY
    url = f"{SEMANTIC_SCHOLAR_API.rstrip('/')}/{path.lstrip('/')}"
    resp = requests.get(url, headers=headers, params=params, timeout=SEMANTIC_SCHOLAR_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


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
    """使用 Semantic Scholar 检索文献，返回 JSON 字符串（列表）。

    参数：
    - query: 检索查询语句
    - top_k: 返回最大条数（默认 20）
    """
    if not query or not query.strip():
        return "[]"

    fields = (
        "title,year,authors.name,abstract,externalIds,openAccessPdf,url,s2Url,citationCount"
    )
    params = {"query": query.strip(), "limit": min(max(top_k, 1), 50), "fields": fields}
    try:
        data = _request("paper/search", params)
        items = data.get("data") or []
        norm = [_normalize_paper(p) for p in items]
        deduped = _dedupe(norm)
        # 返回字符串，避免工具上下文过大（下游可再解析）
        import json as _json
        return _json.dumps(deduped, ensure_ascii=False)
    except Exception as e:
        return f"[ERROR] semantic_scholar_search failed: {e}"


