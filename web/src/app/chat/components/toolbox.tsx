"use client";

import Link from "next/link";
import { Search, Play, Workflow, FlaskConical, Library, Cpu, Image as ImageIcon } from "lucide-react";
import { useState, useMemo } from "react";
import { motion } from "framer-motion";
import { cn } from "~/lib/utils";
import { tools, type ToolConfig, type ToolCategory } from "~/core/config/tools";

export type ToolboxPageId = "workflow" | "library" | "sam" | "vasp" | "image_gen";

/** 置顶功能 id 到独立子页面路径的映射，便于外嵌与分享 */
const PAGE_ENTRY_HREF: Record<ToolboxPageId, string> = {
  library: "/library",
  sam: "/newSam",
  vasp: "/vasp-workflow",
  workflow: "/workflow",
  image_gen: "/tools/image_gen",
};

const PAGE_ENTRIES: Array<{ id: ToolboxPageId; name: string; description: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: "library", name: "我的文库", description: "管理个人文献与资料", icon: Library },
  { id: "sam", name: "SAM 分子设计", description: "分子设计与结构优化", icon: FlaskConical },
  { id: "vasp", name: "VASP 计算", description: "VASP 相关计算与对话", icon: Cpu },
  { id: "workflow", name: "工作流", description: "编排与运行工作流", icon: Workflow },
  { id: "image_gen", name: "文生图", description: "根据文本描述生成图片", icon: ImageIcon },
];

interface ToolboxProps {
  onToolSelect?: (tool: ToolConfig) => void;
  onOpenPage?: (page: ToolboxPageId) => void;
}

export function Toolbox({ onToolSelect, onOpenPage }: ToolboxProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<ToolCategory | "all">("all");

  const filteredTools = useMemo(() => {
    // 不在下方工具网格重复展示已置顶的「文生图」工具
    let result = tools.filter((t) => t.id !== "image_gen");

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
    { id: "general", label: "通用技能" },
  ];

  return (
    <div className="flex h-full flex-col bg-[#F5F5F5] dark:bg-slate-900">
      {/* 智能工具箱横幅：深蓝渐变 + 白字描述 */}
      <div className="px-6 py-4">
        <div
          className="rounded-xl overflow-hidden bg-gradient-to-br from-[#0f172a] via-[#1e3a5f] to-[#0f172a] dark:from-slate-900 dark:via-blue-950/50 dark:to-slate-900 p-6 text-white shadow-lg"
          style={{ minHeight: "120px" }}
        >
          <h2 className="text-xl font-bold mb-2">智能工具箱</h2>
          <p className="text-sm text-white/90 max-w-2xl">
            高效聚合多种先进自动化仪器与软件平台，为科研人员快速搭建智能实验室，显著提升研发效率，释放科研潜能。
          </p>
        </div>
      </div>

      {/* 分类筛选：选中项浅蓝底 + 蓝色文字 */}
      <div className="px-6 py-2 flex gap-2 overflow-x-auto border-b border-slate-200 dark:border-slate-700">
        {categories.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setSelectedCategory(cat.id)}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg whitespace-nowrap transition-colors",
              selectedCategory === cat.id
                ? "bg-[#E6F7FF] dark:bg-blue-950/40 text-[#1890FF] dark:text-blue-400"
                : "text-[#595959] dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            )}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* 置顶技能：链接到独立子页面，便于外嵌与分享 */}
      <div className="px-6 py-3 border-b border-slate-200 dark:border-slate-700">
        <div className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">置顶技能</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {PAGE_ENTRIES.map((entry) => {
            const Icon = entry.icon;
            const href = PAGE_ENTRY_HREF[entry.id];
            return (
              <motion.div
                key={entry.id}
                whileHover={{ scale: 1.02, y: -2 }}
                whileTap={{ scale: 0.98 }}
                className="group"
              >
                <Link
                  href={href}
                  className={cn(
                    "block p-3 rounded-lg border transition-all cursor-pointer flex flex-col bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                    "hover:border-[#1890FF]/40 hover:shadow-md active:scale-[0.98]"
                  )}
                >
                  <div className="mb-2">
                    <div className="p-1.5 rounded-lg bg-[#E6F7FF] dark:bg-blue-950/40 w-fit">
                      <Icon className="h-5 w-5 text-[#1890FF] dark:text-blue-400" />
                    </div>
                  </div>
                  <h3 className="font-semibold text-sm text-slate-900 dark:text-slate-100 line-clamp-1 mb-0.5">
                    {entry.name}
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {entry.description}
                  </p>
                </Link>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* 工具卡片网格：白底、圆角、阴影，全部卡片统一紫色顶边 */}
      <div className="flex-1 overflow-y-auto p-6">
        {filteredTools.length === 0 ? (
          <div className="flex flex-col items-center justify-center min-h-[200px] text-center">
            <Search className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
            <p className="text-sm text-[#595959] dark:text-slate-400">未找到匹配的工具</p>
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
                  <Link
                    href={`/tools/${tool.id}`}
                    className={cn(
                      "block h-full p-4 rounded-lg border transition-all cursor-pointer flex flex-col bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 shadow-sm",
                      "border-t-[3px] border-t-[#9C27B0] dark:border-t-purple-500",
                      "hover:border-[#1890FF]/40 hover:shadow-lg active:scale-[0.98]"
                    )}
                  >
                    <div className="mb-3">
                      <div className="p-2 rounded-lg bg-[#E6F7FF] dark:bg-blue-950/40 w-fit">
                        <Icon className="h-6 w-6 text-[#1890FF] dark:text-blue-400" />
                      </div>
                    </div>
                    <h3 className="font-semibold text-sm text-slate-900 dark:text-slate-100 mb-1.5 line-clamp-1">
                      {tool.name}
                    </h3>
                    <p className="text-xs text-[#595959] dark:text-slate-400 line-clamp-2 mb-3 flex-1">
                      {tool.description}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {tool.category === "molecular"
                          ? "领域: 分子"
                          : tool.category === "literature"
                            ? "领域: 文献"
                            : "领域: 通用"}
                      </span>
                      <Play className="h-4 w-4 text-slate-400 group-hover:text-[#1890FF] transition-colors" />
                    </div>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

