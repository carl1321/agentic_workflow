"use client";

import { Plus, MessageSquare, Trash2, BookOpen, Wrench } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState, useImperativeHandle, forwardRef } from "react";

import { Logo } from "~/components/ui/logo";
import { Button } from "~/components/ui/button";
import { cn } from "~/lib/utils";
import { fetchConversations, deleteConversation, type ConversationSummary } from "~/core/api/conversations";
import { useAuthStore } from "~/core/store/auth-store";

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
}

export interface SidebarRef {
  refresh: () => Promise<void>;
}

export const Sidebar = forwardRef<SidebarRef, SidebarProps>(({
  className,
  onNewChat,
  onSelectChat,
  currentChatId,
  onOpenToolbox,
  onOpenKnowledgeBase,
}, ref) => {
  const { token } = useAuthStore();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

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
        {/* Dify workflow removed - using ReactFlow workflow system instead */}
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

