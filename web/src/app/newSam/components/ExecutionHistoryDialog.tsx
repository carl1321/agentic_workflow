"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect } from "react";
import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Loader2, Trash2, History } from "lucide-react";
import { listExecutionHistory, deleteExecutionHistory, type ExecutionHistoryListItem } from "~/core/api/new-sam";
import { toast } from "sonner";

// 简单的日期格式化函数
function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "刚刚";
  if (diffMins < 60) return `${diffMins}分钟前`;
  if (diffHours < 24) return `${diffHours}小时前`;
  if (diffDays < 7) return `${diffDays}天前`;
  return date.toLocaleDateString("zh-CN");
}

// 执行状态标签
function getExecutionStateLabel(state: string): string {
  switch (state) {
    case "completed":
      return "已完成";
    case "running":
      return "运行中";
    case "failed":
      return "失败";
    case "idle":
      return "待执行";
    default:
      return state;
  }
}

function getExecutionStateColor(state: string): string {
  switch (state) {
    case "completed":
      return "text-green-600 dark:text-green-400";
    case "running":
      return "text-blue-600 dark:text-blue-400";
    case "failed":
      return "text-red-600 dark:text-red-400";
    case "idle":
      return "text-slate-500 dark:text-slate-400";
    default:
      return "text-slate-500 dark:text-slate-400";
  }
}

interface ExecutionHistoryDialogProps {
  /** 是否打开 */
  open: boolean;
  /** 关闭回调 */
  onClose: () => void;
  /** 选择历史记录回调 */
  onSelect: (historyId: string) => void;
}

/**
 * 执行历史记录对话框组件
 */
export function ExecutionHistoryDialog({ open, onClose, onSelect }: ExecutionHistoryDialogProps) {
  const [loading, setLoading] = useState(true);
  const [historyList, setHistoryList] = useState<ExecutionHistoryListItem[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // 加载历史记录列表
  useEffect(() => {
    if (open) {
      loadHistoryList();
    }
  }, [open]);

  const loadHistoryList = async () => {
    try {
      setLoading(true);
      const result = await listExecutionHistory();
      if (result.success) {
        setHistoryList(result.history);
      } else {
        toast.error("加载历史记录失败");
      }
    } catch (error: any) {
      console.error("Failed to load execution history list:", error);
      toast.error(`加载历史记录失败: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (historyId: string, e: React.MouseEvent) => {
    e.stopPropagation(); // 阻止触发选择事件
    
    if (!confirm("确定要删除这条历史记录吗？")) {
      return;
    }

    try {
      setDeletingId(historyId);
      const result = await deleteExecutionHistory(historyId);
      if (result.success) {
        toast.success("删除成功");
        // 重新加载列表
        await loadHistoryList();
      } else {
        toast.error("删除失败");
      }
    } catch (error: any) {
      console.error("Failed to delete execution history:", error);
      toast.error(`删除失败: ${error.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  const handleSelect = (historyId: string) => {
    onSelect(historyId);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="h-5 w-5" />
            运行历史
          </DialogTitle>
          <DialogDescription>
            选择一条历史记录以还原完整的执行状态
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : historyList.length === 0 ? (
            <div className="text-center py-12 text-slate-500 dark:text-slate-400">
              <History className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>暂无历史记录</p>
            </div>
          ) : (
            <div className="space-y-2">
              {historyList.map((item) => (
                <div
                  key={item.id}
                  onClick={() => handleSelect(item.id)}
                  className="flex items-center justify-between p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 cursor-pointer transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-slate-900 dark:text-slate-100 truncate">
                      {item.name}
                    </h3>
                    <div className="flex items-center gap-4 mt-1 text-sm text-slate-500 dark:text-slate-400">
                      <span>{formatTimeAgo(item.createdAt || "")}</span>
                      <span className={getExecutionStateColor(item.executionState)}>
                        {getExecutionStateLabel(item.executionState)}
                      </span>
                      <span>{item.moleculeCount} 个分子</span>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => handleDelete(item.id, e)}
                    disabled={deletingId === item.id}
                    className="shrink-0 text-slate-500 hover:text-destructive dark:text-slate-400"
                  >
                    {deletingId === item.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
