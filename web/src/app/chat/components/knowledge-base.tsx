"use client";

import { Search, BookOpen, Loader2 } from "lucide-react";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { cn } from "~/lib/utils";
import { queryRAGResources } from "~/core/api/rag";
import type { Resource } from "~/core/messages";

interface KnowledgeBaseProps {
  onResourceSelect?: (resource: Resource) => void;
}

export function KnowledgeBase({ onResourceSelect }: KnowledgeBaseProps) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadResources = async (query: string = "") => {
    try {
      setLoading(true);
      setError(null);
      const results = await queryRAGResources(query);
      setResources(results);
    } catch (e) {
      setError((e as Error).message);
      setResources([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadResources(searchQuery);
  }, [searchQuery]);

  return (
    <div className="flex h-full flex-col">
      {/* Search Bar */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索知识库..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* Resources Grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="flex flex-col items-center justify-center h-full">
            <Loader2 className="h-8 w-8 text-slate-400 animate-spin mb-2" />
            <p className="text-sm text-slate-500 dark:text-slate-400">加载中...</p>
          </div>
        )}

        {error && (
          <div className="px-4 py-2 text-sm text-red-500">{error}</div>
        )}

        {!loading && !error && (!resources || resources.length === 0) && (
          <div className="flex flex-col items-center justify-center h-full px-4 text-center">
            <BookOpen className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
            <p className="text-sm text-slate-500 dark:text-slate-400">暂无知识库资源</p>
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-2">
              {searchQuery ? "未找到匹配的资源" : "请先配置知识库"}
            </p>
          </div>
        )}

        {!loading && !error && resources && resources.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {resources.map((resource) => {
              return (
                <motion.div
                  key={resource.uri}
                  whileHover={{ scale: 1.02, y: -2 }}
                  whileTap={{ scale: 0.98 }}
                  className="group"
                >
                  <div
                    className={cn(
                      "h-full p-4 rounded-lg border transition-all cursor-pointer flex flex-col",
                      "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                      "hover:bg-slate-50 dark:hover:bg-slate-700 hover:border-blue-300 dark:hover:border-blue-600",
                      "hover:shadow-md"
                    )}
                    onClick={() => onResourceSelect?.(resource)}
                  >
                    <div className="flex items-start gap-3 mb-3">
                      <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/30 flex-shrink-0">
                        <BookOpen className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm truncate">
                          {resource.title}
                        </h3>
                      </div>
                    </div>
                    {resource.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 mb-2 flex-1">
                        {resource.description}
                      </p>
                    )}
                    <div className="mt-auto pt-2 border-t border-slate-200 dark:border-slate-700">
                      <div className="text-xs text-slate-400 dark:text-slate-500 font-mono truncate">
                        {resource.uri.replace("rag://dataset/", "")}
                      </div>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

