// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { nanoid } from "nanoid";

import type { Option, Resource } from "~/core/messages";
import { useStore } from "~/core/store";
import { cn } from "~/lib/utils";
import { listPlanMessages, sendPlanMessage, streamPlanEvents, type PlanLogItem } from "~/core/api/plans";

import { InputBox } from "./input-box";
import { MessageListView } from "./message-list-view";

export function PlanMessagesBlock({
  className,
  planId,
  planStatus,
  onPlanShouldRefresh,
}: {
  className?: string;
  planId: string;
  /** 用于空状态提示：区分澄清阶段与执行阶段 */
  planStatus?: string;
  /** 发送消息成功后调用，用于刷新计划详情（任务、状态）避免用户手动刷新页面 */
  onPlanShouldRefresh?: () => void;
}) {
  const responding = useStore((s) => s.responding);
  const messageIds = useStore((s) => s.messageIds);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const [feedback, setFeedback] = useState<{ option: Option } | null>(null);
  const [messagesLoaded, setMessagesLoaded] = useState(false);
  const [updateTrigger, setUpdateTrigger] = useState(0);

  function hasRecentSameMessage(role: string, content: string): boolean {
    const ids = useStore.getState().messageIds;
    const msgs = useStore.getState().messages;
    // 仅检查最近 12 条，避免 O(n) 扫全量
    const recent = ids.slice(Math.max(0, ids.length - 12));
    for (const id of recent) {
      const m = msgs.get(id);
      if (!m) continue;
      if ((m.role as any) === role && String(m.content || "") === content) return true;
    }
    return false;
  }

  function logToMarkdown(log: PlanLogItem): string {
    const payload = (log.payload || {}) as any;
    const title = payload.title as string | undefined;
    const bullets = payload.bullets as string[] | undefined;
    const taskId = log.taskId ? `task=${log.taskId}` : "";
    if (title || (bullets && bullets.length)) {
      const lines: string[] = [];
      if (title) lines.push(`**${title}**`);
      if (bullets && bullets.length) {
        for (const b of bullets) lines.push(`- ${b}`);
      }
      return lines.join("\n");
    }
    return `\`${log.level}\` \`${log.event}\` ${taskId}`.trim();
  }

  /**
   * 计划对话沿用通用的 MessageListView 渲染逻辑。
   * 但 MessageListView 会过滤掉「assistant 且无 agent」的消息，导致 messageIds 非空但 UI 一片空白。
   * 因此：对 plan 场景里追加的 assistant 消息，统一补上 agent="coordinator" 以确保可见。
   */
  function agentForRole(role: string) {
    return role === "assistant" ? ("coordinator" as const) : undefined;
  }

  // 当 planId 变化时，加载历史消息到 store
  useEffect(() => {
    let cancelled = false;
    setMessagesLoaded(false);
    // 先加载历史消息
    async function load() {
      useStore.setState({ responding: false });
      useStore.getState().resetConversation();
      useStore.getState().setThreadId(`plan:${planId}`);
      try {
        const res = await listPlanMessages(planId, 2000, 0);
        if (cancelled) return;
        for (const m of res.messages || []) {
          const role = m.role === "system" ? "assistant" : (m.role as any);
          useStore.getState().appendMessage({
            id: m.id,
            threadId: `plan:${planId}`,
            role,
            content: m.content || "",
            contentChunks: [m.content || ""],
            isStreaming: false,
            // @ts-expect-error: 兼容 store 的扩展字段（用于 MessageListView 过滤）
            agent: agentForRole(role),
          });
        }
      } catch (e) {
        console.error("Failed to load plan messages:", e);
      } finally {
        if (!cancelled) setMessagesLoaded(true);
      }
    }
    void load();

    // 再开启 SSE：监听 message/log 事件，追加到对话流
    const ac = new AbortController();
    streamAbortRef.current = ac;
    async function runStream() {
      try {
        for await (const ev of streamPlanEvents(planId, { abortSignal: ac.signal })) {
          if (ev.type === "message") {
            const m = (ev as any).data;
            const id = m.id;
            const content = m.content || "";
            const role = m.role === "system" ? "assistant" : (m.role as any);
            if (!id || useStore.getState().messageIds.includes(id)) continue;
            // 去重：如果本地已乐观回显过同样的文本，就跳过 SSE 这条
            if (hasRecentSameMessage(role, content)) continue;
            useStore.getState().appendMessage({
              id,
              threadId: `plan:${planId}`,
              role,
              content,
              contentChunks: [content],
              isStreaming: false,
              // @ts-expect-error: 兼容 store 的扩展字段（用于 MessageListView 过滤）
              agent: agentForRole(role),
            });
          } else if (ev.type === "log") {
            const l = (ev as any).data as PlanLogItem;
            const id = `log:${l.id}`;
            if (useStore.getState().messageIds.includes(id)) continue;
            // 计划创建日志已在欢迎语中体现，不重复显示为对话气泡
            if (l.event === "plan_created") continue;
            // 澄清回答仅用于后端状态，不在对话流中展示 info clarify_answer 气泡
            if (l.event === "clarify_answer") continue;
            // 用户补充信息仅记录日志，不展示为 info plan_message 气泡
            if (l.event === "plan_message") continue;
            let content: string;
            if (l.event === "clarify_question") {
              // 澄清问题：用 payload.question 显示；若对话里已有同内容（来自 message 事件）则去重
              const q = (l.payload as Record<string, unknown>)?.question as string | undefined;
              if (!q) continue;
              if (hasRecentSameMessage("assistant", q)) continue;
              content = q;
            } else {
              content = logToMarkdown(l);
            }
            useStore.getState().appendMessage({
              id,
              threadId: `plan:${planId}`,
              role: "assistant",
              content,
              contentChunks: [content],
              isStreaming: false,
              // @ts-expect-error: 兼容 store 的扩展字段
              agent: "coordinator",
            });
          }
        }
      } catch (e) {
        if (!ac.signal.aborted) {
          console.error("plan messages stream error:", e);
        }
      }
    }
    void runStream();

    return () => {
      cancelled = true;
      ac.abort();
      streamAbortRef.current = null;
    };
  }, [planId]);

  const handleSend = useCallback(
    async (
      message: string,
      options?: {
        interruptFeedback?: string;
        resources?: Array<Resource>;
      }
    ) => {
      const content = message.trim();
      if (!content) return;
      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      useStore.setState({ responding: true });
      try {
        // 先乐观回显用户消息，避免“没反应”的感觉
        const localId = `local:${nanoid()}`;
        if (!useStore.getState().messageIds.includes(localId)) {
          useStore.getState().appendMessage({
            id: localId,
            threadId: `plan:${planId}`,
            role: "user",
            content,
            contentChunks: [content],
            isStreaming: false,
          } as any);
        }

        const res = await sendPlanMessage(planId, content);
        // 发送成功后刷新计划详情（任务列表、状态等），页面无需手动刷新
        onPlanShouldRefresh?.();
        // 先追加本次响应中的 assistant 消息（与 Coze 类似：发消息后立即用服务端数据更新气泡）
        for (const m of res.messages || []) {
          const id = m.id;
          if (m.role === "user") continue;
          if (!id || useStore.getState().messageIds.includes(id)) continue;
          const role = m.role === "system" ? "assistant" : (m.role as any);
          const serverContent = m.content || "";
          if (hasRecentSameMessage(role, serverContent)) continue;
          useStore.getState().appendMessage({
            id,
            threadId: `plan:${planId}`,
            role,
            content: serverContent,
            contentChunks: [serverContent],
            isStreaming: false,
            // @ts-expect-error: 兼容 store 的扩展字段（用于 MessageListView 过滤）
            agent: agentForRole(role),
          });
        }
        // 再拉取全量消息并合并，保证退出澄清阶段后发送也能即时更新（不依赖 SSE 轮询延迟，与 Coze 的「发消息后拉取全量」思路一致）
        try {
          const full = await listPlanMessages(planId, 2000, 0);
          for (const m of full.messages || []) {
            const id = m.id;
            if (!id) continue;
            if (useStore.getState().messageIds.includes(id)) continue;
            const role = m.role === "system" ? "assistant" : (m.role as any);
            const content = m.content || "";
            // 若已有同内容的气泡（含「已查看记忆」等重复回复），跳过，避免用户连续发「继续」时重复显示
            if (hasRecentSameMessage(role, content)) continue;
            const ids = useStore.getState().messageIds;
            const msgs = useStore.getState().messages;
            // 若已有同内容的气泡（来自 log 的临时 id），去掉 log 气泡再追加 API 消息，避免重复
            const toRemove = ids.find((mid) => {
              const existing = msgs.get(mid);
              if (!existing || !String(mid).startsWith("log:")) return false;
              return (existing.role as string) === role && String(existing.content || "") === content;
            });
            if (toRemove) useStore.getState().removeMessage(toRemove);
            useStore.getState().appendMessage({
              id,
              threadId: `plan:${planId}`,
              role,
              content,
              contentChunks: [content],
              isStreaming: false,
              // @ts-expect-error: 兼容 store 的扩展字段（用于 MessageListView 过滤）
              agent: agentForRole(role),
            });
          }
        } catch (_e) {
          // 拉取失败仅依赖上面 res.messages 已追加的内容
        }
        setFeedback(null);
        setUpdateTrigger((t) => t + 1);
      } catch (e) {
        console.error("Failed to send plan message:", e);
        const errText = e instanceof Error ? e.message : String(e);
        const errorMsg = `发送失败：${errText}\n\n请检查：后端服务是否正常、是否已登录、或稍后重试。`;
        const id = `local:error:${nanoid()}`;
        if (!useStore.getState().messageIds.includes(id)) {
          useStore.getState().appendMessage({
            id,
            threadId: `plan:${planId}`,
            role: "assistant",
            content: errorMsg,
            contentChunks: [errorMsg],
            isStreaming: false,
            // @ts-expect-error: 兼容 store 的扩展字段（用于 MessageListView 过滤）
            agent: "coordinator",
          } as any);
        }
      } finally {
        useStore.setState({ responding: false });
      }
    },
    [planId, onPlanShouldRefresh]
  );

  const handleCancel = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    useStore.setState({ responding: false });
  }, []);

  const handleFeedback = useCallback((fb: { option: Option }) => setFeedback(fb), []);
  const handleRemoveFeedback = useCallback(() => setFeedback(null), []);

  const isEmpty = messageIds.length === 0;
  const emptyHint =
    !messagesLoaded
      ? "正在加载计划对话…"
      : planStatus === "draft"
        ? "暂无消息。澄清问题会在此显示，请稍候或刷新；若长时间无内容可查看后端日志排查。"
        : ["active", "running"].includes(planStatus ?? "")
          ? "暂无消息。规划与执行日志会通过实时推送显示在此，请稍候或刷新。"
          : "暂无对话记录。";

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="flex-1 overflow-auto">
        {isEmpty ? (
          <div className="h-full w-full flex flex-col items-center justify-center gap-2 px-4 text-center text-sm text-slate-500 dark:text-slate-400">
            <span>{emptyHint}</span>
          </div>
        ) : (
          <MessageListView className="h-full" onFeedback={handleFeedback} onSendMessage={handleSend} />
        )}
      </div>
      <div className="relative flex h-42 shrink-0 pb-4">
        <InputBox
          className="h-full w-full"
          responding={responding}
          feedback={feedback}
          onSend={handleSend}
          onCancel={handleCancel}
          onRemoveFeedback={handleRemoveFeedback}
        />
      </div>
    </div>
  );
}

