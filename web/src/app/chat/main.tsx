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
      
      // First, load all messages (including user messages)
      for (let i = 0; i < msgs.length; i++) {
        const m = msgs[i];
        const msg = {
          id: m.id || `${detail.thread_id}-${i}`,
          threadId: detail.thread_id,
          role: (m.role as any) ?? "assistant",
          agent: m.agent as any,
          content: m.content ?? "",
          contentChunks: m.content ? [m.content] : [],
          finishReason: m.finish_reason as any,
          options: m.options as any, // Include options field for interrupt messages
          isStreaming: false,
        } as any;
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
          // 注意：对于 molecular_planner 的 plan，不应该创建 research（使用工作流模式）
          if (agent === "reporter" || agent === "common_reporter" || agent === "coder" || agent === "researcher") {
            if (currentPlanMessage && currentPlanMessage.agent !== "molecular_planner") {
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
