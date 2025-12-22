// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { apiRequest } from "./api-client";

export interface ConversationSummary {
  id: string;
  thread_id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
  total: number;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant" | "tool" | string;
  agent?: string;
  content: string;
  finish_reason?: string;
  options?: Array<{ text: string; value: string }>;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

export async function fetchConversations(
  token: string,
  limit = 50,
  offset = 0,
): Promise<ConversationListResponse> {
  return apiRequest<ConversationListResponse>(
    `conversations?limit=${limit}&offset=${offset}`,
    {
      method: "GET",
    },
    token,
  );
}

export async function fetchConversation(
  token: string,
  threadId: string,
): Promise<ConversationDetail> {
  return apiRequest<ConversationDetail>(
    `conversations/${threadId}`,
    {
      method: "GET",
    },
    token,
  );
}

export async function deleteConversation(
  token: string,
  threadId: string,
): Promise<void> {
  return apiRequest<void>(
    `conversations/${threadId}`,
    {
      method: "DELETE",
    },
    token,
  );
}


