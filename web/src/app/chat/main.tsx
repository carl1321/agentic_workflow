// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useMemo, useState, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

import { useStore } from "~/core/store";
import { cn } from "~/lib/utils";
import { fetchConversation, type ConversationMessage } from "~/core/api/conversations";
import { useAuthStore } from "~/core/store/auth-store";
import { nanoid } from "nanoid";

import { Sidebar, type SidebarRef } from "./components/sidebar";
import { MessagesBlock } from "./components/messages-block";
import { ResearchBlock } from "./components/research-block";
import { ModelSelector } from "./components/model-selector";
import { Toolbox } from "./components/toolbox";
import { KnowledgeBase } from "./components/knowledge-base";
import { KnowledgeBaseDetail } from "./components/knowledge-base-detail";
import { ToolExecutor } from "./components/tool-executor";
import type { ToolConfig } from "~/core/config/tools";
import type { Resource } from "~/core/messages";

type ViewMode = "chat" | "toolbox" | "knowledge" | "knowledge-detail" | "tool-executor";

export default function Main() {
  const searchParams = useSearchParams();
  const { token } = useAuthStore();
  const openResearchId = useStore((state) => state.openResearchId);
  const threadId = useStore((state) => state.threadId);
  const responding = useStore((state) => state.responding);
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [selectedTool, setSelectedTool] = useState<ToolConfig | null>(null);
  const [selectedResource, setSelectedResource] = useState<Resource | null>(null);
  const sidebarRef = useRef<SidebarRef>(null);
  const prevThreadIdRef = useRef<string | undefined>(undefined);
  const prevRespondingRef = useRef<boolean | undefined>(undefined);
  
  const doubleColumnMode = useMemo(
    () => {
      return openResearchId !== null;
    },
    [openResearchId],
  );
  
  // 从 URL 参数中读取 view 参数，设置初始视图模式
  useEffect(() => {
    const viewParam = searchParams.get("view");
    if (viewParam && ["chat", "toolbox", "knowledge", "knowledge-detail", "tool-executor"].includes(viewParam)) {
      setViewMode(viewParam as ViewMode);
    }
  }, [searchParams]);
  
  // Auto-update currentChatId when threadId changes (new conversation created)
  // This ensures the sidebar shows the current conversation as selected
  // Also refresh sidebar when threadId changes from "__default__" to actual ID
  useEffect(() => {
    const prevThreadId = prevThreadIdRef.current;
    
    // If we have a threadId and it's not "__default__", update currentChatId
    // This happens when:
    // 1. A new conversation is created (backend generates new UUID)
    // 2. A historical conversation is loaded (threadId is set explicitly)
    if (threadId && threadId !== "__default__") {
      // Refresh sidebar if threadId changed from "__default__" to actual ID (new conversation created)
      if (prevThreadId === "__default__" && threadId !== "__default__") {
        // New conversation created - refresh sidebar to show it
        sidebarRef.current?.refresh();
      }
      
      // Only update if currentChatId is null or different from threadId
      // This prevents clearing the selection when loading historical conversations
      if (currentChatId !== threadId) {
        // Small delay to ensure state is stable after execution completes
        const timeoutId = setTimeout(() => {
          // Check if we have messages (indicating the conversation exists)
          const messageCount = useStore.getState().messageIds.length;
          // Update if we have messages OR if we're not responding (execution completed)
          if (messageCount > 0 || !responding) {
            setCurrentChatId(threadId);
          }
        }, 100);
        return () => clearTimeout(timeoutId);
      }
    }
    
    // Update previous threadId ref
    prevThreadIdRef.current = threadId;
  }, [threadId, responding, currentChatId]);
  
  // Refresh sidebar when responding changes from true to false (conversation completed)
  // This handles title updates that may occur after stream completes
  useEffect(() => {
    const prevResponding = prevRespondingRef.current;
    // When responding changes from true to false (stream completed)
    if (prevResponding === true && responding === false && threadId && threadId !== "__default__") {
      // Small delay to allow backend to update title
      const timeoutId = setTimeout(() => {
        sidebarRef.current?.refresh();
      }, 500);
      prevRespondingRef.current = responding;
      return () => clearTimeout(timeoutId);
    }
    prevRespondingRef.current = responding;
  }, [responding, threadId]);

  const handleNewChat = () => {
    setCurrentChatId(null);
    setViewMode("chat");
    setSelectedTool(null);
    setSelectedResource(null);
    // Clear current conversation state
    useStore.getState().resetConversation();
    // Use "__default__" to signal new conversation - backend will generate new thread_id
    useStore.getState().setThreadId("__default__");
  };

  const handleSelectChat = async (id: string) => {
    setCurrentChatId(id);
    setViewMode("chat");
    setSelectedTool(null);
    setSelectedResource(null);
    // Load chat history from backend and populate store
    try {
      if (!token) return;
      const detail = await fetchConversation(token, id);
      // Reset current state and set thread id
      useStore.getState().resetConversation();
      useStore.getState().setThreadId(detail.thread_id);
      // Convert structured messages into store Message 并按顺序写入
      const msgs: ConversationMessage[] = detail.messages || [];
      const loadedMessages: any[] = [];
      
      // Validate message structure and log for debugging
      if (process.env.NODE_ENV === "development") {
        console.log(`[Chat] Loading ${msgs.length} messages for thread_id=${detail.thread_id}`);
      }
      
      // #region debug log
      fetch('http://127.0.0.1:7243/ingest/6232be75-7c1f-49ab-bc65-3603d4853f26',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'main.tsx:handleSelectChat:137',message:'Loading messages from backend',data:{messageCount:msgs.length,threadId:detail.thread_id,agents:msgs.map((m:any)=>m.agent)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
      // #endregion
      
      // First, load all messages (including user messages)
      for (let i = 0; i < msgs.length; i++) {
        const m = msgs[i];
        
        // Validate message structure
        if (!m || typeof m !== "object") {
          console.warn(`[Chat] Invalid message at index ${i}:`, m);
          continue;
        }
        
        // #region debug log
        if (m.agent === "reporter" || m.agent === "common_reporter") {
          fetch('http://127.0.0.1:7243/ingest/6232be75-7c1f-49ab-bc65-3603d4853f26',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'main.tsx:handleSelectChat:150',message:'Found reporter message',data:{index:i,agent:m.agent,hasContent:!!m.content,contentLength:m.content?.length||0,hasFinishReason:!!m.finish_reason,finishReason:m.finish_reason},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
        }
        // #endregion
        
        const msg = {
          id: m.id || `${detail.thread_id}-${i}`,
          threadId: detail.thread_id,
          role: (m.role as any) ?? "assistant",
          agent: m.agent as any,
          content: m.content ?? "",
          contentChunks: m.content ? [m.content] : [],
          reasoningContent: (m as any).reasoning_content ?? "",
          reasoningContentChunks: (m as any).reasoning_content ? [(m as any).reasoning_content] : [],
          toolCalls: (m as any).tool_calls as any, // Add tool calls field
          finishReason: m.finish_reason as any,
          options: m.options as any, // Include options field for interrupt messages
          isStreaming: false,
        } as any;
        // Add tool_call_id for tool messages (role === "tool")
        if (m.role === "tool" && (m as any).tool_call_id) {
          (msg as any).tool_call_id = (m as any).tool_call_id;
        }
        
        // Log message structure for debugging
        if (process.env.NODE_ENV === "development") {
          const hasToolCalls = !!(msg.toolCalls && Array.isArray(msg.toolCalls) && msg.toolCalls.length > 0);
          const hasToolCallId = !!(msg as any).tool_call_id;
          const hasReasoning = !!msg.reasoningContent;
          if (hasToolCalls || hasToolCallId || hasReasoning) {
            console.log(
              `[Chat] Message ${i}: id=${msg.id}, agent=${msg.agent}, ` +
              `toolCalls=${hasToolCalls}, tool_call_id=${hasToolCallId}, reasoning=${hasReasoning}`
            );
          }
        }
        
        loadedMessages.push(msg);
        useStore.getState().appendMessage(msg);
      }
      
      // After loading all messages, rebuild plan and research mappings
      if (loadedMessages.length > 0) {
        // Merge message chunks with same ID for chunkable agents (reporter, common_reporter, coder, researcher)
        // This ensures that fragmented messages from streaming are properly merged
        const chunkableAgents = ["reporter", "common_reporter", "coder", "researcher"];
        const messageChunkMap = new Map<string, any[]>();
        const mergedMessages: any[] = [];
        
        for (const msg of loadedMessages) {
          const agent = msg.agent;
          const msgId = msg.id;
          
          // Only merge chunks for chunkable agents
          if (chunkableAgents.includes(agent)) {
            if (!messageChunkMap.has(msgId)) {
              messageChunkMap.set(msgId, []);
            }
            messageChunkMap.get(msgId)!.push(msg);
          } else {
            // Non-chunkable messages go directly to mergedMessages
            mergedMessages.push(msg);
          }
        }
        
        // Merge chunks for each message ID
        for (const [msgId, chunks] of messageChunkMap.entries()) {
          if (chunks.length === 1) {
            mergedMessages.push(chunks[0]);
          } else {
            // Merge chunks - preserve order based on original message order
            const sortedChunks = chunks.sort((a, b) => {
              const indexA = loadedMessages.findIndex(m => m.id === a.id);
              const indexB = loadedMessages.findIndex(m => m.id === b.id);
              return indexA - indexB;
            });
            const baseMsg = { ...sortedChunks[0] };
            const mergedContent = sortedChunks.map(c => c.content || "").join("");
            baseMsg.content = mergedContent;
            baseMsg.contentChunks = mergedContent ? [mergedContent] : [];
            baseMsg.isStreaming = false; // Ensure it's marked as completed
            
            // Preserve tool calls, tool_call_id, and reasoning content during merge
            // Use the first chunk's toolCalls if available, or merge from all chunks
            if (sortedChunks.some(c => c.toolCalls)) {
              baseMsg.toolCalls = sortedChunks.find(c => c.toolCalls)?.toolCalls || baseMsg.toolCalls;
            }
            if (sortedChunks.some(c => c.tool_call_id)) {
              baseMsg.tool_call_id = sortedChunks.find(c => c.tool_call_id)?.tool_call_id || baseMsg.tool_call_id;
            }
            // Merge reasoning content
            const mergedReasoning = sortedChunks.map(c => c.reasoningContent || "").join("");
            if (mergedReasoning) {
              baseMsg.reasoningContent = mergedReasoning;
              baseMsg.reasoningContentChunks = mergedReasoning ? [mergedReasoning] : [];
            }
            
            mergedMessages.push(baseMsg);
            
            // Update the merged message in store
            useStore.getState().updateMessage(baseMsg);
            
            const agent = baseMsg.agent;
            console.log(`Merged ${chunks.length} ${agent} chunks for ${msgId}, content length: ${mergedContent.length}, content preview: ${mergedContent.substring(0, 100)}`);
          }
        }
        
        // Sort merged messages by original order (preserve the order from loadedMessages)
        mergedMessages.sort((a, b) => {
          const indexA = loadedMessages.findIndex(m => {
            // For merged messages, find by ID; for others, find exact match
            if (a.id === b.id) return 0;
            return m.id === a.id ? -1 : m.id === b.id ? 1 : 0;
          });
          const indexB = loadedMessages.findIndex(m => m.id === b.id);
          return indexA - indexB;
        });
        
        const researchPlanIds = new Map<string, string>();
        const researchReportIds = new Map<string, string>();
        const researchActivityIds = new Map<string, string[]>();
        const researchIds: string[] = [];
        
        // Debug: log message agents
        console.log("Loaded messages with agents:", mergedMessages.map(m => ({ id: m.id, agent: m.agent, role: m.role, contentLen: m.content?.length || 0 })));
        
        // Find all planner messages and their associated research messages
        let currentPlanMessage: any = null;
        let currentResearchId: string | null = null;
        let currentActivityIds: string[] = [];
        
        for (const msg of mergedMessages) {
          const agent = msg.agent;
          
          // If this is a planner message, start a new research
          if (agent === "planner" || agent === "molecular_planner") {
            // Save previous research if exists
            if (currentResearchId && currentPlanMessage) {
              // Ensure activity IDs start with plan message ID and research ID
              if (currentActivityIds.length === 0 || currentActivityIds[0] !== currentPlanMessage.id) {
                currentActivityIds = [currentPlanMessage.id, currentResearchId, ...currentActivityIds.filter(id => id !== currentPlanMessage.id && id !== currentResearchId)];
              }
              researchActivityIds.set(currentResearchId, currentActivityIds);
            }
            
            // Start new research
            currentPlanMessage = msg;
            currentResearchId = null;
            currentActivityIds = [];
          }
          
          // If this is a reporter/coder/researcher message, associate it with current plan
          // 注意：对于 molecular_planner 的 plan，也需要创建 research 以显示工具执行卡片和结果卡片
          if (agent === "reporter" || agent === "common_reporter" || agent === "coder" || agent === "researcher") {
            if (currentPlanMessage) {
              // Use the first reporter/coder/researcher as research ID
              if (!currentResearchId) {
                currentResearchId = msg.id;
                researchIds.push(currentResearchId);
                researchPlanIds.set(currentResearchId, currentPlanMessage.id);
                // Initialize activity IDs with plan message ID and research ID
                // Note: researchId might be a reporter message, but we'll only add non-reporter messages to activities
                currentActivityIds = [currentPlanMessage.id, currentResearchId];
              }
              
              // Add to activity IDs ONLY if it's NOT a reporter message
              // Activity page should only show researcher and coder messages, not reporter
              // Include messages even if content is empty, as they may have toolCalls
              if (agent !== "reporter" && agent !== "common_reporter") {
                if (!currentActivityIds.includes(msg.id)) {
                  currentActivityIds.push(msg.id);
                  // Debug: log added activity message
                  const hasContent = msg.content && msg.content.trim().length > 0;
                  const hasToolCalls = msg.toolCalls && msg.toolCalls.length > 0;
                  if (!hasContent && !hasToolCalls) {
                    console.warn(`Added empty activity message ${msg.id} (agent: ${agent}) to research ${currentResearchId}`);
                  }
                }
              }
              
              // If this is a reporter, save it as report ID (but don't add to activity IDs)
              if ((agent === "reporter" || agent === "common_reporter") && currentResearchId) {
                // Only set if content is not empty (avoid setting empty report messages)
                const content = msg.content || "";
                // Check if content has meaningful content (not just whitespace or minimal text)
                const trimmedContent = content.trim();
                // Lower threshold to 5 characters to catch minimal valid reports
                if (trimmedContent.length > 5) {
                  // If there's already a report for this research, prefer the one with longer content
                  const existingReportId = researchReportIds.get(currentResearchId);
                  if (existingReportId) {
                    const existingReport = mergedMessages.find(m => m.id === existingReportId);
                    const existingContent = existingReport?.content?.trim() || "";
                    if (trimmedContent.length > existingContent.length) {
                      // Current message has more content, use it instead
                      researchReportIds.set(currentResearchId, msg.id);
                      console.log(`Updated report ID for research ${currentResearchId}: ${msg.id} (length: ${trimmedContent.length}), replaced ${existingReportId} (length: ${existingContent.length})`);
                    }
                  } else {
                    researchReportIds.set(currentResearchId, msg.id);
                    console.log(`Set report ID for research ${currentResearchId}: ${msg.id}, content length: ${trimmedContent.length}, preview: ${trimmedContent.substring(0, 50)}`);
                  }
                } else {
                  console.warn(`Skipped empty/invalid reporter message for research ${currentResearchId}: ${msg.id}, content length: ${trimmedContent.length}, content: "${content}"`);
                }
              }
            }
          }
        }
        
        // Save the last research if exists
        if (currentResearchId && currentPlanMessage) {
          // Ensure activity IDs start with plan message ID and research ID
          if (currentActivityIds.length === 0 || currentActivityIds[0] !== currentPlanMessage.id) {
            currentActivityIds = [currentPlanMessage.id, currentResearchId, ...currentActivityIds.filter(id => id !== currentPlanMessage.id && id !== currentResearchId)];
          }
          // Filter out reporter messages from activity IDs (they should only be in report IDs)
          const filteredActivityIds = currentActivityIds.filter((msgId) => {
            const msg = mergedMessages.find((m) => m.id === msgId);
            if (!msg) return true; // Keep if message not found (shouldn't happen)
            const agent = msg.agent;
            return agent !== "reporter" && agent !== "common_reporter";
          });
          researchActivityIds.set(currentResearchId, filteredActivityIds);
          
          // Debug: log research mappings
          console.log(`Restored research ${currentResearchId}:`, {
            planId: currentPlanMessage.id,
            activityIds: filteredActivityIds.length,
            reportId: researchReportIds.get(currentResearchId) || "none",
            activityAgents: filteredActivityIds.map((id) => {
              const msg = mergedMessages.find((m) => m.id === id);
              return msg?.agent || "unknown";
            }),
          });
        }
        
        // Update store with rebuilt mappings
        useStore.setState({
          researchIds,
          researchPlanIds,
          researchReportIds,
          researchActivityIds,
        });
        
        // Clear interrupt messages if final_report exists (reporter/common_reporter with finishReason="stop")
        // This ensures that "Edit plan" and "Start research" buttons are hidden for completed conversations
        const state = useStore.getState();
        const hasFinalReport = state.messageIds.some((msgId) => {
          const msg = state.messages.get(msgId);
          return (
            (msg?.agent === "reporter" || msg?.agent === "common_reporter") &&
            msg?.finishReason === "stop"
          );
        });
        
        // #region debug log - Check research mappings and toolCalls
        const debugData: any = {
          messageCount: state.messageIds.length,
          researchIds: researchIds.length,
          researchPlanIds: Array.from(researchPlanIds.entries()).length,
          researchReportIds: Array.from(researchReportIds.entries()).length,
          researchActivityIds: Array.from(researchActivityIds.entries()).length,
          hasFinalReport,
        };
        
        // Check toolCalls in messages
        const messagesWithToolCalls = state.messageIds.filter((msgId) => {
          const msg = state.messages.get(msgId);
          return msg?.toolCalls && msg.toolCalls.length > 0;
        });
        debugData.messagesWithToolCalls = messagesWithToolCalls.length;
        debugData.messagesWithToolCallsDetails = messagesWithToolCalls.map((msgId) => {
          const msg = state.messages.get(msgId);
          return {
            id: msgId,
            agent: msg?.agent,
            toolCallsCount: msg?.toolCalls?.length || 0,
            toolCallNames: msg?.toolCalls?.map((tc: any) => tc.name) || [],
          };
        });
        
        // Check activityIds for each research
        debugData.researchActivityDetails = Array.from(researchActivityIds.entries()).map(([researchId, activityIds]) => {
          const activities = activityIds.map((activityId) => {
            const msg = state.messages.get(activityId);
            return {
              id: activityId,
              agent: msg?.agent,
              hasToolCalls: !!(msg?.toolCalls && msg.toolCalls.length > 0),
              toolCallsCount: msg?.toolCalls?.length || 0,
            };
          });
          return { researchId, activityCount: activityIds.length, activities };
        });
        
        fetch('http://127.0.0.1:7243/ingest/6232be75-7c1f-49ab-bc65-3603d4853f26',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'main.tsx:handleSelectChat:400',message:'Research mappings and toolCalls check',data:debugData,timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'F'})}).catch(()=>{});
        // #endregion
        
        if (hasFinalReport) {
          // Find and clear all interrupt messages by updating their finishReason
          for (let i = state.messageIds.length - 1; i >= 0; i--) {
            const msgId = state.messageIds[i];
            if (!msgId) continue;
            const interruptMsg = state.messages.get(msgId);
            if (interruptMsg?.finishReason === "interrupt") {
              // Update interrupt message to mark it as completed
              const updatedInterruptMsg = { ...interruptMsg, finishReason: "stop" as const };
              useStore.getState().updateMessage(updatedInterruptMsg);
              // #region debug log
              fetch('http://127.0.0.1:7243/ingest/6232be75-7c1f-49ab-bc65-3603d4853f26',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'main.tsx:handleSelectChat:415',message:'Cleared interrupt message',data:{interruptMessageId:msgId,agent:interruptMsg.agent},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'E'})}).catch(()=>{});
              // #endregion
            }
          }
        }
        
        // Auto-open the first research if exists
        // 注意：不自动打开 research，让用户手动选择
        // 这样可以避免对话被挤到右侧
        // if (researchIds.length > 0) {
        //   useStore.getState().openResearch(researchIds[0]);
        // }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleOpenToolbox = () => {
    setViewMode("toolbox");
    setSelectedTool(null);
  };

  const handleOpenKnowledgeBase = () => {
    setViewMode("knowledge");
    setSelectedTool(null);
    setSelectedResource(null);
  };

  // Dify workflow removed - using ReactFlow workflow system instead
  // const handleOpenWorkflow = () => {
  //   setViewMode("workflow");
  //   setSelectedTool(null);
  //   setSelectedResource(null);
  // };

  const handleResourceSelect = (resource: Resource) => {
    setSelectedResource(resource);
    setViewMode("knowledge-detail");
  };

  const handleBackToKnowledgeBase = () => {
    setViewMode("knowledge");
    setSelectedResource(null);
  };

  const handleToolSelect = (tool: ToolConfig) => {
    setSelectedTool(tool);
    setViewMode("tool-executor");
  };

  const handleToolClose = () => {
    setSelectedTool(null);
    setViewMode("toolbox");
  };

  const handleBackToToolbox = () => {
    setSelectedTool(null);
    setViewMode("toolbox");
  };

  return (
    <div className="flex h-full w-full">
      <Sidebar
        ref={sidebarRef}
        currentChatId={currentChatId}
        onNewChat={handleNewChat}
        onSelectChat={handleSelectChat}
        onOpenToolbox={handleOpenToolbox}
        onOpenKnowledgeBase={handleOpenKnowledgeBase}
      />
      
      <div className="flex flex-1 h-full flex-col overflow-visible">
        {/* Model Selector - Top aligned with sidebar header (h-16 = 64px) */}
        {viewMode === "chat" && (
          <div className="relative flex h-16 items-center px-4 border-b border-slate-200 dark:border-slate-700 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm z-50 overflow-visible">
            <ModelSelector />
          </div>
        )}
        
        {viewMode === "chat" && (
          <div
            className={cn(
              "flex flex-1 justify-center px-4 pt-4 pb-4",
              doubleColumnMode && "gap-8",
            )}
          >
            <MessagesBlock
              className={cn(
                "shrink-0 transition-all duration-300 ease-out",
                !doubleColumnMode && "w-[768px]",
                doubleColumnMode && "w-[538px]",
              )}
            />
            {openResearchId && (
            <ResearchBlock
              className={cn(
                "w-[min(max(calc((100vw-538px)*0.75),575px),960px)] pb-4 transition-all duration-300 ease-out",
                !doubleColumnMode && "scale-0",
                doubleColumnMode && "",
              )}
              researchId={openResearchId}
            />
            )}
            {/* Dify workflow removed - using ReactFlow workflow system instead */}
          </div>
        )}

        {viewMode === "toolbox" && (
          <div className="flex-1 overflow-hidden">
            <Toolbox onToolSelect={handleToolSelect} />
          </div>
        )}

        {viewMode === "knowledge" && (
          <div className="flex-1 overflow-hidden">
            <KnowledgeBase onResourceSelect={handleResourceSelect} />
          </div>
        )}
        {viewMode === "knowledge-detail" && selectedResource && (
          <div className="flex-1 overflow-hidden">
            <KnowledgeBaseDetail resource={selectedResource} onBack={handleBackToKnowledgeBase} />
          </div>
        )}

        {viewMode === "tool-executor" && selectedTool && (
          <div className="flex-1 overflow-hidden">
            <ToolExecutor 
              tool={selectedTool} 
              onClose={handleToolClose}
              onBack={handleBackToToolbox}
            />
          </div>
        )}
        {/* Dify workflow removed - using ReactFlow workflow system instead */}
      </div>
    </div>
  );
}
