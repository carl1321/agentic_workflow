"use client";

import { Search, Loader2, ChevronDown, ChevronRight, FileText, BarChart3 } from "lucide-react";
import { useState, useEffect } from "react";
import { cn } from "~/lib/utils";
import { executeTool } from "~/core/api/tools";
import { Button } from "~/components/ui/button";
import { Markdown } from "~/components/ui/markdown";

interface ZoteroSearchItem {
  key: string;
  itemType?: string;
  title: string;
  authors?: string[];
  year?: string;
  abstract?: string;
  url?: string;
  doi?: string;
  publicationTitle?: string;
  attachment_count?: number;
}

interface ZoteroDetail extends ZoteroSearchItem {
  attachments?: Array<{ key: string; filename: string; contentType: string }>;
  extra?: string;
  tags?: string[];
  fulltext?: string;
}

export function LibraryPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<ZoteroSearchItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<ZoteroDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [analysisType, setAnalysisType] = useState<"summary" | "compare" | "key_findings">("summary");
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);

  const loadList = async () => {
    try {
      setSearching(true);
      setError(null);
      const raw = await executeTool("zotero_literature_tool", {
        action: "list",
        limit: 50,
      });
      const items = JSON.parse(raw || "[]") as ZoteroSearchItem[];
      setResults(Array.isArray(items) ? items : []);
    } catch (e) {
      setError((e as Error).message);
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    loadList();
  }, []);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    try {
      setSearching(true);
      setError(null);
      setResults([]);
      setExpandedKey(null);
      setDetail(null);
      setAnalysisResult(null);
      const raw = await executeTool("zotero_literature_tool", {
        action: "search",
        query: searchQuery.trim(),
        limit: 30,
      });
      const items = JSON.parse(raw || "[]") as ZoteroSearchItem[];
      setResults(Array.isArray(items) ? items : []);
    } catch (e) {
      setError((e as Error).message);
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleSelectItem = async (item: ZoteroSearchItem) => {
    const key = item.key;
    if (expandedKey === key) {
      setExpandedKey(null);
      setDetail(null);
      return;
    }
    setExpandedKey(key);
    setDetail(null);
    try {
      setLoadingDetail(true);
      const raw = await executeTool("zotero_literature_tool", {
        action: "get_detail",
        item_key: key,
      });
      const data = JSON.parse(raw || "{}") as ZoteroDetail;
      if (data.error) throw new Error(data.error);
      setDetail(data);
    } catch (e) {
      setError((e as Error).message);
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleFetchFulltext = async (attachmentKey: string) => {
    if (!expandedKey || !detail) return;
    try {
      setLoadingDetail(true);
      const raw = await executeTool("zotero_literature_tool", {
        action: "get_detail",
        item_key: expandedKey,
        attachment_key: attachmentKey,
      });
      const data = JSON.parse(raw || "{}") as ZoteroDetail;
      if (data.error) throw new Error(data.error);
      setDetail(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingDetail(false);
    }
  };

  const toggleSelect = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleAnalyze = async () => {
    if (selectedKeys.size === 0) return;
    try {
      setAnalyzing(true);
      setError(null);
      setAnalysisResult(null);
      const raw = await executeTool("zotero_literature_tool", {
        action: "analyze",
        item_keys: Array.from(selectedKeys).join(","),
        analysis_type: analysisType,
      });
      const display = (raw && raw.trim()) ? raw : "（LLM 未返回有效内容，请检查后端日志或 conf.yaml 中 BASIC_MODEL 配置）";
      setAnalysisResult(display);
    } catch (e) {
      setError((e as Error).message);
      setAnalysisResult(null);
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* 搜索区 */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索文库..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <Button onClick={handleSearch} disabled={searching}>
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          搜索
        </Button>
      </div>

      {error && (
        <div className="px-4 py-2 text-sm text-red-500 bg-red-50 dark:bg-red-950/30">{error}</div>
      )}

      {results.length > 0 && selectedKeys.size === 0 && (
        <div className="px-4 py-2 text-xs text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30">
          勾选文献后可分析：摘要（总结文章摘要）、对比（需选2篇及以上，比较异同）、关键发现（提炼文章关键发现）
        </div>
      )}

      <div className="flex-1 overflow-hidden flex">
        {/* 结果列表 */}
        <div className="w-[400px] border-r border-slate-200 dark:border-slate-700 overflow-y-auto flex flex-col">
          {results.length === 0 && !searching && (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 px-4 text-center">
              <FileText className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-sm">文库暂无内容或输入关键词搜索</p>
            </div>
          )}
          {results.map((item) => (
            <div
              key={item.key}
              className={cn(
                "px-4 py-3 border-b border-slate-100 dark:border-slate-800 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors",
                expandedKey === item.key && "bg-blue-50 dark:bg-blue-950/30 border-l-2 border-l-blue-500"
              )}
              onClick={() => handleSelectItem(item)}
            >
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={selectedKeys.has(item.key)}
                  onChange={(e) => {
                    e.stopPropagation();
                    toggleSelect(item.key);
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="mt-1"
                />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-slate-900 dark:text-slate-100 text-sm line-clamp-2">
                    {item.title || "（无标题）"}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    {(item.authors || []).join(", ")}
                    {item.year && ` (${item.year})`}
                  </div>
                </div>
                {expandedKey === item.key ? (
                  <ChevronDown className="h-4 w-4 flex-shrink-0 text-slate-400" />
                ) : (
                  <ChevronRight className="h-4 w-4 flex-shrink-0 text-slate-400" />
                )}
              </div>
            </div>
          ))}
        </div>

        {/* 详情/全文/分析区（右侧主区） */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col">
          {analyzing && (
            <div className="flex flex-col items-center justify-center flex-1 text-slate-500 dark:text-slate-400">
              <Loader2 className="h-10 w-10 animate-spin mb-3" />
              <p className="text-sm">LLM 分析中，请稍候...</p>
            </div>
          )}
          {!analyzing && analysisResult && (
            <div className="flex-1">
              <h3 className="text-base font-semibold text-slate-800 dark:text-slate-200 mb-3 flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                LLM 分析结果
                {analysisType === "summary" && "（摘要）"}
                {analysisType === "compare" && "（对比）"}
                {analysisType === "key_findings" && "（关键发现）"}
              </h3>
              <div className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 prose prose-slate dark:prose-invert max-w-none">
                <Markdown>{analysisResult}</Markdown>
              </div>
            </div>
          )}
          {!analyzing && !analysisResult && !expandedKey && (
            <div className="flex flex-col items-center justify-center flex-1 text-slate-500 dark:text-slate-400">
              <FileText className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-sm">点击左侧文献查看详情，或勾选多篇后点击「分析」</p>
            </div>
          )}
          {!analyzing && !analysisResult && expandedKey && loadingDetail && (
            <div className="flex items-center justify-center flex-1">
              <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
            </div>
          )}
          {!analyzing && !analysisResult && expandedKey && detail && !loadingDetail && (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {detail.title || "（无标题）"}
                </h2>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                  {(detail.authors || []).join(", ")}
                  {detail.year && ` · ${detail.year}`}
                </p>
                {detail.publicationTitle && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    {detail.publicationTitle}
                  </p>
                )}
              </div>
              {detail.abstract && (
                <div>
                  <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">摘要</h3>
                  <p className="text-sm text-slate-600 dark:text-slate-400 whitespace-pre-wrap">
                    {detail.abstract}
                  </p>
                </div>
              )}
              {detail.attachments && detail.attachments.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">附件</h3>
                  <div className="space-y-2">
                    {detail.attachments.map((att) => (
                      <div
                        key={att.key}
                        className="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-100 dark:bg-slate-800"
                      >
                        <span className="text-sm truncate flex-1">{att.filename}</span>
                        {att.contentType === "application/pdf" && !detail.fulltext && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleFetchFulltext(att.key)}
                          >
                            获取全文
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {detail.fulltext && (
                <div>
                  <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">全文</h3>
                  <div className="text-sm text-slate-600 dark:text-slate-400 whitespace-pre-wrap max-h-96 overflow-y-auto p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50">
                    {detail.fulltext}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 分析操作栏（仅保留按钮，结果在右侧展示） */}
      {selectedKeys.size > 0 && (
        <div className="border-t border-slate-200 dark:border-slate-700 px-4 py-3 bg-slate-50 dark:bg-slate-900/50 flex items-center gap-3 flex-wrap">
          <span className="text-sm text-slate-600 dark:text-slate-400">
            已选 {selectedKeys.size} 篇文献
          </span>
          <select
            value={analysisType}
            onChange={(e) => setAnalysisType(e.target.value as "summary" | "compare" | "key_findings")}
            className="text-sm border border-slate-200 dark:border-slate-700 rounded px-2 py-1 bg-white dark:bg-slate-800"
            title={
              analysisType === "summary"
                ? "总结文章摘要"
                : analysisType === "compare"
                  ? "比较异同（需选2篇及以上）"
                  : "提炼文章关键发现"
            }
          >
            <option value="summary">摘要：总结文章摘要</option>
            <option value="compare">对比：比较异同（需2篇及以上）</option>
            <option value="key_findings">关键发现：提炼关键发现</option>
          </select>
          <Button
            onClick={handleAnalyze}
            disabled={analyzing || (analysisType === "compare" && selectedKeys.size < 2)}
            title={analysisType === "compare" && selectedKeys.size < 2 ? "对比需至少选择2篇文献" : undefined}
          >
            {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <BarChart3 className="h-4 w-4" />}
            分析
          </Button>
          {analysisType === "compare" && selectedKeys.size < 2 && (
            <span className="text-xs text-amber-600 dark:text-amber-400">对比需至少选择2篇文献</span>
          )}
        </div>
      )}
    </div>
  );
}
