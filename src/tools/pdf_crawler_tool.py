"""
PDF 抓取与解析工具：
- 优先尝试下载并解析 PDF 文本；
- 若失败，回退到抓取 HTML 正文（使用现有 readability 管道）；
- 返回 { text, meta }，其中 meta 含 content_type/status/pdf_bytes_len/url 等。
"""

import io
import os
import typing as t

import requests
from langchain_core.tools import tool

# 回退到 HTML 可读性提取
from src.crawler.crawler import Crawler
from src.crawler.readability_extractor import ReadabilityExtractor


PDF_TIMEOUT = float(os.getenv("PDF_FETCH_TIMEOUT", "25"))


def _extract_pdf_text(content: bytes) -> str:
    # 尝试多种解析器，逐个回退，避免硬依赖
    # 1) pdfminer.six
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract

        with io.BytesIO(content) as fp:
            text = pdfminer_extract(fp) or ""
            if text.strip():
                return text
    except Exception:
        pass
    # 2) PyPDF2（有时提取质量较差）
    try:
        import PyPDF2

        with io.BytesIO(content) as fp:
            reader = PyPDF2.PdfReader(fp)
            out = []
            for page in reader.pages:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    continue
        text = "\n".join(out).strip()
        if text:
            return text
    except Exception:
        pass
    # 3) 失败返回空字符串
    return ""


@tool("pdf_crawler", return_direct=False)
def fetch_pdf_text(url: str, max_pages: int | None = None) -> dict:
    """下载并解析 PDF 文本；失败时回退到可读 HTML 正文。

    参数：
    - url: PDF 或落地页 URL
    - max_pages: 预留参数（当前未切页截断）
    返回：{"text": str, "meta": {...}}
    """
    meta: dict[str, t.Any] = {"url": url, "parser": None, "content_type": None, "status": None}
    text = ""

    try:
        resp = requests.get(url, timeout=PDF_TIMEOUT, allow_redirects=True)
        meta["status"] = resp.status_code
        ctype = (resp.headers.get("Content-Type") or "").lower()
        meta["content_type"] = ctype

        if "pdf" in ctype or url.lower().endswith(".pdf"):
            content = resp.content
            meta["pdf_bytes_len"] = len(content)
            text = _extract_pdf_text(content)
            meta["parser"] = "pdfminer|pypdf2"
            if not text:
                # PDF 提取失败则作为空字符串返回
                return {"text": "", "meta": meta}
            return {"text": text, "meta": meta}

        # 非PDF：回退到 HTML 抓取与可读性提取
        try:
            crawler = Crawler()
            html = crawler.fetch_content(url) or ""
            extractor = ReadabilityExtractor()
            article = extractor.extract_article(html)
            text = (article.html_content or "").strip()
            meta["parser"] = "readability"
            return {"text": text, "meta": meta}
        except Exception:
            return {"text": "", "meta": meta}

    except Exception as e:
        meta["error"] = str(e)
        return {"text": "", "meta": meta}


