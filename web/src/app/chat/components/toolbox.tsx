"use client";

import { Search, Play } from "lucide-react";
import { useState, useMemo } from "react";
import { motion } from "framer-motion";
import { cn } from "~/lib/utils";
import { tools, toolsByCategory, type ToolConfig, type ToolCategory } from "~/core/config/tools";

interface ToolboxProps {
  onToolSelect?: (tool: ToolConfig) => void;
}

export function Toolbox({ onToolSelect }: ToolboxProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<ToolCategory | "all">("all");

  const filteredTools = useMemo(() => {
    let result = tools;

    // 按分类筛选
    if (selectedCategory !== "all") {
      result = result.filter((t) => t.category === selectedCategory);
    }

    // 按搜索查询筛选
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (t) =>
          t.name.toLowerCase().includes(query) ||
          t.description.toLowerCase().includes(query)
      );
    }

    return result;
  }, [searchQuery, selectedCategory]);

  const categories: Array<{ id: ToolCategory | "all"; label: string }> = [
    { id: "all", label: "全部" },
    { id: "molecular", label: "分子科学" },
    { id: "literature", label: "文献研究" },
    { id: "general", label: "通用工具" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Search Bar */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索工具..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* Category Filter */}
        <div className="flex gap-2 overflow-x-auto">
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setSelectedCategory(cat.id)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-colors",
                selectedCategory === cat.id
                  ? "bg-blue-500 text-white dark:bg-blue-600"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700"
              )}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tools Grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {filteredTools.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Search className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
            <p className="text-sm text-slate-500 dark:text-slate-400">未找到匹配的工具</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredTools.map((tool) => {
              const Icon = tool.icon;
              return (
                <motion.div
                  key={tool.id}
                  whileHover={{ scale: 1.02, y: -2 }}
                  whileTap={{ scale: 0.98 }}
                  className="group"
                >
                  <div
                    className={cn(
                      "h-full p-4 rounded-lg border transition-all cursor-pointer flex flex-col",
                      "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                      "hover:border-blue-300 dark:hover:border-blue-600 hover:shadow-lg",
                      "active:scale-[0.98]"
                    )}
                    onClick={() => onToolSelect?.(tool)}
                  >
                    {/* Icon */}
                    <div className="mb-3">
                      <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/30 w-fit">
                        <Icon className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                      </div>
                    </div>
                    
                    {/* Title */}
                    <h3 className="font-semibold text-sm text-slate-900 dark:text-slate-100 mb-1.5 line-clamp-1">
                      {tool.name}
                    </h3>
                    
                    {/* Description */}
                    <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 mb-3 flex-1">
                      {tool.description}
                    </p>
                    
                    {/* Category Badge */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                        {tool.category === "molecular"
                          ? "分子科学"
                          : tool.category === "literature"
                          ? "文献研究"
                          : "通用工具"}
                      </span>
                      <Play className="h-4 w-4 text-slate-400 group-hover:text-blue-500 transition-colors" />
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

