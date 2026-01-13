"use client";

import { Plus, MessageSquare, Trash2, BookOpen, Wrench, Workflow, FlaskConical } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState, useImperativeHandle, forwardRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";

import { Logo } from "~/components/ui/logo";
import { Button } from "~/components/ui/button";
import { cn } from "~/lib/utils";
import { fetchConversations, deleteConversation, type ConversationSummary } from "~/core/api/conversations";
import { useAuthStore } from "~/core/store/auth-store";
import type { MenuInfo } from "~/core/api/auth";

interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  messageCount: number;
  preview: string;
}

interface SidebarProps {
  className?: string;
  onNewChat?: () => void;
  onSelectChat?: (id: string) => void;
  currentChatId?: string | null;
  onOpenToolbox?: () => void;
  onOpenKnowledgeBase?: () => void;
  onOpenWorkflow?: () => void;
}

export interface SidebarRef {
  refresh: () => Promise<void>;
}

// 图标映射
const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  FlaskConical,
  BookOpen,
  Wrench,
  Workflow,
};

export const Sidebar = forwardRef<SidebarRef, SidebarProps>(({
  className,
  onNewChat,
  onSelectChat,
  currentChatId,
  onOpenToolbox,
  onOpenKnowledgeBase,
  onOpenWorkflow,
}, ref) => {
  const router = useRouter();
  const pathname = usePathname();
  const { token, user } = useAuthStore();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // 硬编码的菜单路径和代码（这些已经有专门的按钮，不需要从数据库加载）
  const hardcodedMenuPaths = new Set([
    "/chat",
    "/chat?view=toolbox",
    "/chat?view=knowledge",
    "/chat?view=workflow",
    "/workflows", // 工作流管理
  ]);
  
  const hardcodedMenuCodes = new Set([
    "toolbox",
    "knowledge_base",
    "workflow",
    "workflow:list",
    "chat",
    "business",
  ]);

  // 获取用户菜单中非管理后台的菜单项
  const userMenus = useMemo(() => {
    if (!user?.menus) {
      // 调试：检查用户菜单是否加载
      if (process.env.NODE_ENV === "development") {
        console.log("[Sidebar] 用户菜单未加载", { user: user?.id, hasMenus: !!user?.menus });
      }
      return [];
    }
    
    // 过滤出非管理后台的菜单（不以 /admin 开头，且有路径）
    // 同时排除硬编码的菜单路径
    const flattenMenus = (menus: MenuInfo[]): MenuInfo[] => {
      const result: MenuInfo[] = [];
      for (const menu of menus) {
        if (
          menu.path && 
          !menu.path.startsWith("/admin") && 
          menu.is_visible !== false &&
          !hardcodedMenuPaths.has(menu.path) &&
          !hardcodedMenuCodes.has(menu.code)
        ) {
          result.push(menu);
        }
        if (menu.children) {
          result.push(...flattenMenus(menu.children));
        }
      }
      return result;
    };
    
    // 去重：根据路径和代码去重，避免重复显示
    const uniqueMenus = new Map<string, MenuInfo>();
    flattenMenus(user.menus).forEach((menu) => {
      // 使用路径作为key，如果没有路径则使用代码
      const key = menu.path || menu.code;
      if (key && !uniqueMenus.has(key)) {
        uniqueMenus.set(key, menu);
      }
    });
    
    const finalMenus = Array.from(uniqueMenus.values()).sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
    
    // 调试：输出过滤后的菜单
    if (process.env.NODE_ENV === "development") {
      console.log("[Sidebar] 过滤后的菜单", {
        totalMenus: user.menus.length,
        filteredMenus: finalMenus.length,
        menus: finalMenus.map(m => ({ name: m.name, code: m.code, path: m.path }))
      });
    }
    
    return finalMenus;
  }, [user?.menus]);

  const loadConversations = async () => {
    try {
      setLoading(true);
      if (!token) {
        setConversations([]);
        setError(null);
        return;
      }
      const res = await fetchConversations(token, 50, 0);
      setConversations(res.conversations || []);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Expose refresh function via ref
  useImperativeHandle(ref, () => ({
    refresh: loadConversations,
  }));

  useEffect(() => {
    // Initial load only - no polling
    loadConversations();
  }, []);

  // map to old ChatSession shape for rendering
  const chatHistory: ChatSession[] = useMemo(() => {
    return (conversations || []).map((c) => ({
      id: c.thread_id,
      title: c.title || "新对话",
      timestamp: c.updated_at ? new Date(c.updated_at).getTime() : 0,
      messageCount: 0,
      preview: c.updated_at ? new Date(c.updated_at).toLocaleString() : "",
    }));
  }, [conversations]);

  // group by recency
  const now = Date.now();
  const oneDay = 24 * 60 * 60 * 1000;
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const startOfYesterday = new Date(startOfToday.getTime() - oneDay);
  const startOfWeek = new Date(now - 6 * oneDay);

  const groupedHistory = useMemo(() => {
    const today: ChatSession[] = [];
    const yesterday: ChatSession[] = [];
    const thisWeek: ChatSession[] = [];
    const earlier: ChatSession[] = [];

    chatHistory.forEach((c) => {
      const ts = c.timestamp;
      if (ts >= startOfToday.getTime()) today.push(c);
      else if (ts >= startOfYesterday.getTime() && ts < startOfToday.getTime())
        yesterday.push(c);
      else if (ts >= startOfWeek.getTime()) thisWeek.push(c);
      else earlier.push(c);
    });

    const byTimeDesc = (a: ChatSession, b: ChatSession) => b.timestamp - a.timestamp;
    today.sort(byTimeDesc);
    yesterday.sort(byTimeDesc);
    thisWeek.sort(byTimeDesc);
    earlier.sort(byTimeDesc);

    return { today, yesterday, thisWeek, earlier };
  }, [chatHistory]);

  const handleDelete = async (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    if (!confirm("确定要删除这条对话吗？")) {
      return;
    }
    
    try {
      if (!token) return;
      setDeletingId(chatId);
      await deleteConversation(token, chatId);
      // Remove from local state
      setConversations((prev) => prev.filter((c) => c.thread_id !== chatId));
      // If deleted conversation was currently selected, clear selection
      if (currentChatId === chatId) {
        onNewChat?.();
      }
    } catch (e) {
      console.error("Failed to delete conversation:", e);
      alert("删除对话失败，请稍后重试");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <motion.div
      className={cn(
        "flex h-full w-[320px] flex-col border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900",
        className
      )}
      initial={{ x: -320 }}
      animate={{ x: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {/* Header */}
      <div className="flex h-16 items-center justify-between px-4 border-b border-slate-200 dark:border-slate-700">
        <Logo />
        <Button
          variant="ghost"
          size="icon"
          onClick={onNewChat}
          className="h-8 w-8"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {/* New Chat Button */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <Button
          onClick={onNewChat}
          className="w-full bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
        >
          <Plus className="h-4 w-4 mr-2" />
          新建对话
        </Button>
      </div>

      {/* Navigation Buttons */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 space-y-2">
        <Button
          variant="outline"
          className="w-full justify-start"
          onClick={onOpenToolbox}
        >
          <Wrench className="h-4 w-4 mr-2" />
          工具箱
        </Button>
        <Button
          variant="outline"
          className="w-full justify-start"
          onClick={onOpenKnowledgeBase}
        >
          <BookOpen className="h-4 w-4 mr-2" />
          知识库
        </Button>
        <Button
          variant="outline"
          className="w-full justify-start"
          onClick={onOpenWorkflow}
        >
          <Workflow className="h-4 w-4 mr-2" />
          工作流
        </Button>
        
        {/* 动态菜单项 */}
        {userMenus.length > 0 && (
          <>
            {userMenus.map((menu) => {
              const IconComponent = menu.icon ? iconMap[menu.icon] : FlaskConical;
              const isActive = pathname === menu.path;
              
              return (
                <Link key={menu.id} href={menu.path || "#"}>
                  <Button
                    variant="outline"
                    className={cn(
                      "w-full justify-start",
                      isActive && "bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border-blue-300 dark:border-blue-700"
                    )}
                  >
                    {IconComponent ? <IconComponent className="h-4 w-4 mr-2" /> : <FlaskConical className="h-4 w-4 mr-2" />}
                    {menu.name}
                  </Button>
                </Link>
              );
            })}
          </>
        )}
      </div>

      {/* Chat History */}
      <div className="flex-1 overflow-y-auto py-2">
        {loading && (
          <div className="px-4 py-2 text-xs text-slate-500">加载中...</div>
        )}
        {error && (
          <div className="px-4 py-2 text-xs text-red-500">{error}</div>
        )}
        {Object.entries(groupedHistory).map(([period, chats]) => {
          if (chats.length === 0) return null;

          return (
            <div key={period} className="px-2 mb-4">
              <div className="text-xs font-medium text-slate-500 dark:text-slate-400 px-4 mb-2">
                {period === "today" && "今天"}
                {period === "yesterday" && "昨天"}
                {period === "thisWeek" && "本周"}
                {period === "earlier" && "更早"}
              </div>
              {chats.map((chat) => (
                <motion.div
                  key={chat.id}
                  whileHover={{ x: 4 }}
                  transition={{ duration: 0.2 }}
                  className="group relative"
                >
                  <button
                    onClick={() => onSelectChat?.(chat.id)}
                    className={cn(
                      "w-full text-left px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-3",
                      currentChatId === chat.id
                        ? "bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400"
                        : "text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                    )}
                  >
                    <MessageSquare className="h-4 w-4 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{chat.title}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 truncate">
                        {chat.preview}
                      </div>
                    </div>
                  </button>
                  <button
                    onClick={(e) => handleDelete(e, chat.id)}
                    disabled={deletingId === chat.id}
                    className={cn(
                      "absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                      "text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    title="删除对话"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </motion.div>
              ))}
            </div>
          );
        })}

        {chatHistory.length === 0 && !loading && !error && (
          <div className="flex flex-col items-center justify-center h-full px-4 text-center">
            <MessageSquare className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
            <p className="text-sm text-slate-500 dark:text-slate-400">暂无对话历史</p>
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-2">开始新的对话吧</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-slate-200 dark:border-slate-700 px-4 py-3">
        <div className="text-xs text-slate-500 dark:text-slate-400">AgenticWorkflow</div>
      </div>
    </motion.div>
  );
});

Sidebar.displayName = "Sidebar";

