// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { resolveServiceURL } from "./resolve-service-url";

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
  const url = resolveServiceURL(`conversations?limit=${limit}&offset=${offset}`);
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error(`Failed to fetch conversations: ${res.status}`);
  return res.json();
}

export async function fetchConversation(
  token: string,
  threadId: string,
): Promise<ConversationDetail> {
  const url = resolveServiceURL(`conversations/${threadId}`);
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    // Include status code in error message for easier handling
    throw new Error(`Failed to fetch conversation ${threadId}: ${res.status}`);
  }
  return res.json();
}

export async function deleteConversation(
  token: string,
  threadId: string,
): Promise<void> {
  const url = resolveServiceURL(`conversations/${threadId}`);
  const res = await fetch(url, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error(`Failed to delete conversation ${threadId}: ${res.status}`);
}


