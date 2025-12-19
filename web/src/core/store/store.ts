// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { nanoid } from "nanoid";
import { toast } from "sonner";
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";

import { chatStream, generatePodcast } from "../api";
import type { Message, Resource } from "../messages";
import { mergeMessage } from "../messages";
import { parseJSON } from "../utils";
// Dify workflow removed - using ReactFlow workflow system instead
// import type { WorkflowConfig } from "../workflow/types";

import { getChatStreamSettings } from "./settings-store";

const THREAD_ID = nanoid();

export const useStore = create<{
  responding: boolean;
  threadId: string | undefined;
  messageIds: string[];
  messages: Map<string, Message>;
  researchIds: string[];
  researchPlanIds: Map<string, string>;
  researchReportIds: Map<string, string>;
  researchActivityIds: Map<string, string[]>;
  ongoingResearchId: string | null;
  openResearchId: string | null;
  selectedModel: string | null;

  appendMessage: (message: Message) => void;
  updateMessage: (message: Message) => void;
  updateMessages: (messages: Message[]) => void;
  resetConversation: () => void;
  setThreadId: (threadId: string) => void;
  openResearch: (researchId: string | null) => void;
  closeResearch: () => void;
  setOngoingResearch: (researchId: string | null) => void;
  setSelectedModel: (model: string | null) => void;
}>((set, get) => ({
  responding: false,
  threadId: THREAD_ID,
  messageIds: [],
  messages: new Map<string, Message>(),
  researchIds: [],
  researchPlanIds: new Map<string, string>(),
  researchReportIds: new Map<string, string>(),
  researchActivityIds: new Map<string, string[]>(),
  ongoingResearchId: null,
  openResearchId: null,
  selectedModel: null,

  appendMessage(message: Message) {
    set((state) => {
      // Check if message ID already exists to avoid duplicates
      if (state.messageIds.includes(message.id)) {
        console.warn(`Duplicate message ID detected: ${message.id}`);
        return {
          messages: new Map(state.messages).set(message.id, message),
        };
      }
      return {
        messageIds: [...state.messageIds, message.id],
        messages: new Map(state.messages).set(message.id, message),
      };
    });
  },
  updateMessage(message: Message) {
    set((state) => ({
      messages: new Map(state.messages).set(message.id, message),
    }));
  },
  updateMessages(messages: Message[]) {
    set((state) => {
      const newMessages = new Map(state.messages);
      messages.forEach((m) => newMessages.set(m.id, m));
      return { messages: newMessages };
    });
  },
  resetConversation() {
    set(() => ({
      messageIds: [],
      messages: new Map<string, Message>(),
      researchIds: [],
      researchPlanIds: new Map<string, string>(),
      researchReportIds: new Map<string, string>(),
      researchActivityIds: new Map<string, string[]>(),
      ongoingResearchId: null,
      openResearchId: null,
    }));
  },
  setThreadId(threadId: string) {
    set(() => ({ threadId }));
  },
  openResearch(researchId: string | null) {
    set({ openResearchId: researchId });
  },
  closeResearch() {
    set({ openResearchId: null });
  },
  setOngoingResearch(researchId: string | null) {
    set({ ongoingResearchId: researchId });
  },
  setSelectedModel(model: string | null) {
    set({ selectedModel: model });
  },
}));

export async function sendMessage(
  content?: string,
  {
    interruptFeedback,
    resources,
  }: {
    interruptFeedback?: string;
    resources?: Array<Resource>;
  } = {},
  options: { abortSignal?: AbortSignal } = {},
) {
  // Get current thread ID from store (may be updated when loading historical conversations)
  const currentThreadId = useStore.getState().threadId || THREAD_ID;
  
  if (content != null) {
    appendMessage({
      id: nanoid(),
      threadId: currentThreadId,
      role: "user",
      content: content,
      contentChunks: [content],
      resources,
    });
  }

  const settings = getChatStreamSettings();
  const selectedModel = useStore.getState().selectedModel;
  const stream = chatStream(
    content ?? "[REPLAY]",
    {
      thread_id: currentThreadId,
      interrupt_feedback: interruptFeedback,
      resources,
      auto_accepted_plan: settings.autoAcceptedPlan,
      enable_clarification: settings.enableClarification ?? false,
      max_clarification_rounds: settings.maxClarificationRounds ?? 3,
      enable_deep_thinking: settings.enableDeepThinking ?? false,
      enable_background_investigation:
        settings.enableBackgroundInvestigation ?? true,
      max_plan_iterations: settings.maxPlanIterations,
      max_step_num: settings.maxStepNum,
      max_search_results: settings.maxSearchResults,
      report_style: settings.reportStyle,
      selected_model: selectedModel,
      mcp_settings: settings.mcpSettings,
    },
    options,
  );

  setResponding(true);
  let messageId: string | undefined;
  let updatedThreadId: string | undefined;
  try {
    for await (const event of stream) {
      const { type, data } = event;
      messageId = data.id;
      
      // Update threadId from stream if it's different (e.g., when backend generates new UUID from "__default__")
      if (data.thread_id && data.thread_id !== currentThreadId && data.thread_id !== "__default__") {
        updatedThreadId = data.thread_id;
        useStore.getState().setThreadId(data.thread_id);
      }
      
      let message: Message | undefined;
      if (type === "tool_call_result") {
        message = findMessageByToolCallId(data.tool_call_id);
      } else if (type === "interrupt") {
        // For interrupt events, create a new message if it doesn't exist
        // The interrupt message should be associated with the planner message
        if (!existsMessage(messageId)) {
          message = {
            id: messageId,
            threadId: updatedThreadId || data.thread_id || currentThreadId,
            agent: data.agent,
            role: data.role || "assistant",
            content: data.content || "",
            contentChunks: data.content ? [data.content] : [],
            reasoningContent: "",
            reasoningContentChunks: [],
            isStreaming: false,
            finishReason: "interrupt",
            options: data.options,
            interruptFeedback,
          };
          appendMessage(message);
        } else {
          message = getMessage(messageId);
        }
      } else if (!existsMessage(messageId)) {
        message = {
          id: messageId,
          threadId: updatedThreadId || data.thread_id || currentThreadId,
          agent: data.agent,
          role: data.role,
          content: "",
          contentChunks: [],
          reasoningContent: "",
          reasoningContentChunks: [],
          isStreaming: true,
          interruptFeedback,
        };
        appendMessage(message);
      }
      message ??= getMessage(messageId);
      if (message) {
        message = mergeMessage(message, event);
        updateMessage(message);
        
        // Clear interrupt message when final_report is received (reporter/common_reporter with finish_reason="stop")
        // This ensures that "Edit plan" and "Start research" buttons are hidden after completion
        if (
          (message.agent === "reporter" || message.agent === "common_reporter") &&
          message.finishReason === "stop"
        ) {
          // Find and clear the interrupt message by updating its finishReason
          const state = useStore.getState();
          for (let i = state.messageIds.length - 1; i >= 0; i--) {
            const msgId = state.messageIds[i];
            if (!msgId) continue;
            const interruptMsg = state.messages.get(msgId);
            if (interruptMsg?.finishReason === "interrupt") {
              // Update interrupt message to mark it as completed
              const updatedInterruptMsg = { ...interruptMsg, finishReason: "stop" as const };
              useStore.getState().updateMessage(updatedInterruptMsg);
              break; // Only clear the last interrupt message
            }
          }
        }
      }
    }
    
    // After stream completes, ensure threadId is updated if changed
    if (updatedThreadId) {
      useStore.getState().setThreadId(updatedThreadId);
    }
  } catch {
    toast("An error occurred while generating the response. Please try again.");
    // Update message status.
    // TODO: const isAborted = (error as Error).name === "AbortError";
    if (messageId != null) {
      const message = getMessage(messageId);
      if (message?.isStreaming) {
        message.isStreaming = false;
        useStore.getState().updateMessage(message);
      }
    }
    useStore.getState().setOngoingResearch(null);
  } finally {
    setResponding(false);
  }
}

function setResponding(value: boolean) {
  useStore.setState({ responding: value });
}

function existsMessage(id: string) {
  return useStore.getState().messageIds.includes(id);
}

function getMessage(id: string) {
  return useStore.getState().messages.get(id);
}

function findMessageByToolCallId(toolCallId: string) {
  return Array.from(useStore.getState().messages.values())
    .reverse()
    .find((message) => {
      if (message.toolCalls) {
        return message.toolCalls.some((toolCall) => toolCall.id === toolCallId);
      }
      return false;
    });
}

function appendMessage(message: Message) {
  if (
    message.agent === "coder" ||
    message.agent === "reporter" ||
    message.agent === "common_reporter" ||
    message.agent === "researcher"
  ) {
    if (!getOngoingResearchId()) {
      const id = message.id;
      appendResearch(id);
      openResearch(id);
    }
    appendResearchActivity(message);
  }
  useStore.getState().appendMessage(message);
}

function updateMessage(message: Message) {
  // Don't clear ongoingResearchId immediately when reporter message completes
  // This allows other messages (coder/researcher) that are still streaming to be added to researchActivityIds
  // The ongoingResearchId will be cleared in sendMessage's finally block when the stream fully completes
  useStore.getState().updateMessage(message);
}

function getOngoingResearchId() {
  return useStore.getState().ongoingResearchId;
}

function appendResearch(researchId: string) {
  let planMessage: Message | undefined;
  const reversedMessageIds = [...useStore.getState().messageIds].reverse();
  for (const messageId of reversedMessageIds) {
    const message = getMessage(messageId);
    if (message?.agent === "planner" || message?.agent === "molecular_planner") {
      planMessage = message;
      break;
    }
  }
  const messageIds = [researchId];
  messageIds.unshift(planMessage!.id);
  useStore.setState({
    ongoingResearchId: researchId,
    researchIds: [...useStore.getState().researchIds, researchId],
    researchPlanIds: new Map(useStore.getState().researchPlanIds).set(
      researchId,
      planMessage!.id,
    ),
    researchActivityIds: new Map(useStore.getState().researchActivityIds).set(
      researchId,
      messageIds,
    ),
  });
}

function appendResearchActivity(message: Message) {
  const researchId = getOngoingResearchId();
  // If ongoingResearchId is not set, try to find the research ID from existing researchIds
  // This handles the case where ongoingResearchId was cleared but messages are still streaming
  let targetResearchId = researchId;
  if (!targetResearchId && (
    message.agent === "coder" ||
    message.agent === "researcher" ||
    message.agent === "reporter" ||
    message.agent === "common_reporter"
  )) {
    // Find the most recent research ID from the current researchIds
    const researchIds = useStore.getState().researchIds;
    if (researchIds.length > 0) {
      // Use the last research ID (most recent)
      targetResearchId = researchIds[researchIds.length - 1];
      // Also restore ongoingResearchId temporarily to ensure messages are added
      useStore.getState().setOngoingResearch(targetResearchId);
    }
  }
  
  if (targetResearchId) {
    // Only add non-reporter messages to activity IDs
    // Activity page should show researcher and coder messages, not reporter messages
    if (message.agent !== "reporter" && message.agent !== "common_reporter") {
      const researchActivityIds = useStore.getState().researchActivityIds;
      const current = researchActivityIds.get(targetResearchId);
      if (current) {
        if (!current.includes(message.id)) {
          useStore.setState({
            researchActivityIds: new Map(researchActivityIds).set(targetResearchId, [
              ...current,
              message.id,
            ]),
          });
        }
      } else {
        // If researchActivityIds doesn't exist for this researchId, initialize it
        // This can happen if the research was created but activityIds wasn't properly initialized
        const researchPlanIds = useStore.getState().researchPlanIds;
        const planId = researchPlanIds.get(targetResearchId);
        const initialIds = planId ? [planId, targetResearchId] : [targetResearchId];
        useStore.setState({
          researchActivityIds: new Map(researchActivityIds).set(targetResearchId, [
            ...initialIds,
            message.id,
          ]),
        });
      }
    }
    // Set report ID for reporter messages
    if (message.agent === "reporter" || message.agent === "common_reporter") {
      useStore.setState({
        researchReportIds: new Map(useStore.getState().researchReportIds).set(
          targetResearchId,
          message.id,
        ),
      });
    }
  }
}

export function openResearch(researchId: string | null) {
  useStore.getState().openResearch(researchId);
}

export function closeResearch() {
  useStore.getState().closeResearch();
}

export function openWorkflow(workflowId: string | null) {
  useStore.getState().openWorkflow(workflowId);
}

// Dify workflow removed - using ReactFlow workflow system instead
// export function closeWorkflow() {
//   useStore.getState().closeWorkflow();
// }

export async function listenToPodcast(researchId: string) {
  const planMessageId = useStore.getState().researchPlanIds.get(researchId);
  const reportMessageId = useStore.getState().researchReportIds.get(researchId);
  if (planMessageId && reportMessageId) {
    const planMessage = getMessage(planMessageId)!;
    const title = parseJSON(planMessage.content, { title: "Untitled" }).title;
    const reportMessage = getMessage(reportMessageId);
    if (reportMessage?.content) {
      appendMessage({
        id: nanoid(),
        threadId: THREAD_ID,
        role: "user",
        content: "Please generate a podcast for the above research.",
        contentChunks: [],
      });
      const podCastMessageId = nanoid();
      const podcastObject = { title, researchId };
      const podcastMessage: Message = {
        id: podCastMessageId,
        threadId: THREAD_ID,
        role: "assistant",
        agent: "podcast",
        content: JSON.stringify(podcastObject),
        contentChunks: [],
        reasoningContent: "",
        reasoningContentChunks: [],
        isStreaming: true,
      };
      appendMessage(podcastMessage);
      // Generating podcast...
      let audioUrl: string | undefined;
      try {
        audioUrl = await generatePodcast(reportMessage.content);
      } catch (e) {
        console.error(e);
        useStore.setState((state) => ({
          messages: new Map(useStore.getState().messages).set(
            podCastMessageId,
            {
              ...state.messages.get(podCastMessageId)!,
              content: JSON.stringify({
                ...podcastObject,
                error: e instanceof Error ? e.message : "Unknown error",
              }),
              isStreaming: false,
            },
          ),
        }));
        toast("An error occurred while generating podcast. Please try again.");
        return;
      }
      useStore.setState((state) => ({
        messages: new Map(useStore.getState().messages).set(podCastMessageId, {
          ...state.messages.get(podCastMessageId)!,
          content: JSON.stringify({ ...podcastObject, audioUrl }),
          isStreaming: false,
        }),
      }));
    }
  }
}

export function useResearchMessage(researchId: string) {
  return useStore(
    useShallow((state) => {
      const messageId = state.researchPlanIds.get(researchId);
      return messageId ? state.messages.get(messageId) : undefined;
    }),
  );
}

export function useMessage(messageId: string | null | undefined) {
  return useStore(
    useShallow((state) =>
      messageId ? state.messages.get(messageId) : undefined,
    ),
  );
}

export function useMessageIds() {
  return useStore(useShallow((state) => state.messageIds));
}

export function useLastInterruptMessage() {
  return useStore(
    useShallow((state) => {
      // Find the last message with finishReason === "interrupt"
      // This works for both active and loaded historical conversations
      if (state.messageIds.length >= 1) {
        // Search backwards from the end to find the last interrupt message
        for (let i = state.messageIds.length - 1; i >= 0; i--) {
          const messageId = state.messageIds[i];
          if (!messageId) continue;
          const message = state.messages.get(messageId);
          if (message?.finishReason === "interrupt") {
            return message;
          }
        }
      }
      return null;
    }),
  );
}

export function useLastFeedbackMessageId() {
  const waitingForFeedbackMessageId = useStore(
    useShallow((state) => {
      // Find the last interrupt message and return the message ID before it
      // This is the plan message that needs feedback
      if (state.messageIds.length >= 2) {
        // Search backwards from the end to find the last interrupt message
        for (let i = state.messageIds.length - 1; i >= 1; i--) {
          const messageId = state.messageIds[i];
          if (!messageId) continue;
          const message = state.messages.get(messageId);
          if (message?.finishReason === "interrupt") {
            // Return the message ID before the interrupt message (the plan message)
            return state.messageIds[i - 1] || null;
          }
        }
      }
      return null;
    }),
  );
  return waitingForFeedbackMessageId;
}

export function useToolCalls() {
  return useStore(
    useShallow((state) => {
      return state.messageIds
        ?.map((id) => getMessage(id)?.toolCalls)
        .filter((toolCalls) => toolCalls != null)
        .flat();
    }),
  );
}
