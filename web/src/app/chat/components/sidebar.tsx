"use client";

import { Plus, MessageSquare, Trash2, BookOpen, Wrench, Workflow, FlaskConical, ListTodo } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState, useImperativeHandle, forwardRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";

import { Logo } from "~/components/ui/logo";
import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Textarea } from "~/components/ui/textarea";
import { Badge } from "~/components/ui/badge";
import { toast } from "sonner";
import { cn } from "~/lib/utils";
import { fetchConversations, deleteConversation, type ConversationSummary } from "~/core/api/conversations";
import { createPlan, listPlans, deletePlan, type PlanSummary } from "~/core/api/plans";
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
  onSelectPlan?: (planId: string) => void;
  currentPlanId?: string | null;
  onPlanDeleted?: (planId: string) => void;
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
  onSelectPlan,
  currentPlanId,
  onPlanDeleted,
  onOpenToolbox,
  onOpenKnowledgeBase,
  onOpenWorkflow,
}, ref) => {
  const router = useRouter();
  const pathname = usePathname();
  const { token, user } = useAuthStore();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingPlanId, setDeletingPlanId] = useState<string | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [planTitle, setPlanTitle] = useState("");
  const [planGoal, setPlanGoal] = useState("");
  const [planCreating, setPlanCreating] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

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

  const loadPlans = async () => {
    try {
      if (!token) {
        setPlans([]);
        return;
      }
      const res = await listPlans(50, 0);
      setPlans(res.plans || []);
    } catch (e) {
      // 计划列表失败不应影响聊天功能
      console.error("Failed to load plans:", e);
    }
  };

  // Expose refresh function via ref
  useImperativeHandle(ref, () => ({
    refresh: async () => {
      await Promise.all([loadConversations(), loadPlans()]);
    },
  }));

  useEffect(() => {
    // Initial load only - no polling
    loadConversations();
    loadPlans();
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

  const handleDeletePlan = async (e: React.MouseEvent, planId: string) => {
    e.stopPropagation();
    if (!confirm("确定要删除该长期计划吗？删除后无法恢复。")) {
      return;
    }
    try {
      setDeletingPlanId(planId);
      await deletePlan(planId);
      setPlans((prev) => prev.filter((p) => p.id !== planId));
      onPlanDeleted?.(planId);
    } catch (err) {
      console.error("Failed to delete plan:", err);
      alert("删除计划失败，请稍后重试");
    } finally {
      setDeletingPlanId(null);
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
        {/* Long-term plans */}
        <div className="px-2 mb-4">
          <div className="flex items-center justify-between px-4 mb-2">
            <div className="text-xs font-medium text-slate-500 dark:text-slate-400 flex items-center gap-2">
              <ListTodo className="h-3.5 w-3.5" />
              长期计划
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => {
                setPlanOpen(true);
                setPlanTitle("");
                setPlanGoal("");
                setPlanError(null);
              }}
              title="新建长期计划"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {plans.length === 0 ? (
            <div className="px-4 py-2 text-xs text-slate-500">暂无计划</div>
          ) : (
            <div className="space-y-1">
              {plans.map((p) => {
                const active = currentPlanId === p.id;
                return (
                  <div key={p.id} className="group relative">
                    <button
                      onClick={() => onSelectPlan?.(p.id)}
                      className={cn(
                        "w-full text-left px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-3",
                        active
                          ? "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300"
                          : "text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                      )}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{p.title || "未命名计划"}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400 truncate">
                          {p.updatedAt ? `更新：${p.updatedAt}` : ""}
                        </div>
                      </div>
                      <Badge variant="secondary" className="shrink-0">{p.status}</Badge>
                    </button>
                    <button
                      onClick={(e) => handleDeletePlan(e, p.id)}
                      disabled={deletingPlanId === p.id}
                      className={cn(
                        "absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                        "text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                      title="删除计划"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

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

      {/* Create plan dialog */}
      <Dialog open={planOpen} onOpenChange={setPlanOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>新建长期计划</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="planTitle">计划标题（可选）</Label>
              <Input
                id="planTitle"
                value={planTitle}
                onChange={(e) => setPlanTitle(e.target.value)}
                placeholder="例如：设备对接接口文档生成"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="planGoal">目标（必填）</Label>
              <Textarea
                id="planGoal"
                value={planGoal}
                onChange={(e) => setPlanGoal(e.target.value)}
                placeholder="你想长期持续做的事情是什么？可以很模糊。"
                rows={4}
              />
            </div>
            {planError && (
              <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-300">
                {planError}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              className="h-8 px-3 text-xs"
              onClick={() => setPlanOpen(false)}
              disabled={planCreating}
            >
              取消
            </Button>
            <Button
              type="button"
              className="h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-500 text-white"
              disabled={planCreating || planGoal.trim().length === 0}
              onClick={async () => {
                const goal = planGoal.trim();
                if (!goal) return;
                setPlanCreating(true);
                setPlanError(null);
                try {
                  const res = await createPlan(goal, planTitle.trim() || undefined);
                  setPlanOpen(false);
                  onSelectPlan?.(res.planId);
                  await loadPlans();
                } catch (e) {
                  const msg = e instanceof Error ? e.message : String(e);
                  setPlanError(msg);
                  setPlanOpen(false);
                  toast.error(`创建计划失败：${msg}`);
                } finally {
                  setPlanCreating(false);
                }
              }}
            >
              {planCreating ? "创建中..." : "创建并打开"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
});

Sidebar.displayName = "Sidebar";

