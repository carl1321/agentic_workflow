---
name: zotero
description: Connect to Zotero library for literature search, metadata retrieval, fulltext access, and LLM-based analysis. Use when the user needs to search local/private literature, get article details, or analyze papers from Zotero.
metadata:
  tools: "zotero_literature_tool"
---

# Zotero Literature

## When to use

- User asks to search or read from their Zotero library
- User needs literature metadata, abstracts, or fulltext from Zotero
- User wants to analyze, summarize, or compare papers stored in Zotero

## Configuration

Configure in `conf.yaml`:

```yaml
ZOTERO:
  enabled: true
  library_id: ""        # From zotero.org/settings (personal) or group page URL
  library_type: "user"  # user | group
  api_key: ""           # From zotero.org/settings/keys (library read)
```

Environment variables `ZOTERO_LIBRARY_ID`, `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_TYPE` override YAML.

## Tool actions

Use `zotero_literature_tool` with `action` parameter:

- **search**: Search library by query. Returns title, authors, year, abstract, key, itemType, url, attachment_count.
- **get_detail**: Get item metadata and attachment list by `item_key`. Optional `attachment_key` for fulltext (when Zotero has indexed it).
- **analyze**: Analyze items by keys using LLM. Use `analysis_type`: summary, compare, key_findings, or custom (with `custom_prompt`).

## Typical flow

1. `action=search` with query
2. Pick item keys from results
3. `action=get_detail` for metadata and optional fulltext
4. `action=analyze` for summary/compare/key_findings

## Integration

- **literature_search_tool**: Searches open sources (e.g. Semantic Scholar). Zotero focuses on local/private library.
- **pdf_crawler_tool**: Fetches PDF by URL. When Zotero attachment has no fulltext index, you can use URL for pdf_crawler if available.
- **data_extraction_tool**: Structured extraction from text. Can work with zotero analyze results.
