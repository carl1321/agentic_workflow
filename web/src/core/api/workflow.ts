// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { apiRequest } from "./api-client";
import { fetchStream } from "../sse";
import { resolveServiceURL } from "./resolve-service-url";
import { useAuthStore } from "../store/auth-store";

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: string;
  current_draft_id?: string;
  current_release_id?: string;
  created_by?: string;
  created_by_name?: string;
  organization_id?: string;
  department_id?: string;
  workspace_id?: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDraft {
  id: string;
  workflow_id: string;
  version: number;
  is_autosave: boolean;
  graph: {
    nodes: any[];
    edges: any[];
  };
  validation?: any;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRelease {
  id: string;
  workflow_id: string;
  release_version: number;
  source_draft_id: string;
  spec: any;
  checksum: string;
  created_by: string;
  created_at: string;
}

export interface CreateWorkflowRequest {
  name: string;
  description?: string;
  status?: string;
}

export interface UpdateWorkflowRequest {
  name?: string;
  description?: string;
  status?: string;
}

export interface SaveDraftRequest {
  graph: {
    nodes: any[];
    edges: any[];
  };
  is_autosave?: boolean;
}

export interface CreateReleaseRequest {
  source_draft_id: string;
  spec: any;
  checksum: string;
}

export interface WorkflowListResponse {
  workflows: Workflow[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * 创建工作流
 */
export async function createWorkflow(
  data: CreateWorkflowRequest
): Promise<Workflow> {
  return apiRequest<Workflow>("workflows", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * 获取工作流详情
 */
export async function getWorkflow(workflowId: string): Promise<Workflow> {
  return apiRequest<Workflow>(`workflows/${workflowId}`);
}

/**
 * 更新工作流
 */
export async function updateWorkflow(
  workflowId: string,
  data: UpdateWorkflowRequest
): Promise<Workflow> {
  return apiRequest<Workflow>(`workflows/${workflowId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

/**
 * 删除工作流
 */
export async function deleteWorkflow(workflowId: string): Promise<{ success: boolean; message: string }> {
  return apiRequest<{ success: boolean; message: string }>(`workflows/${workflowId}`, {
    method: "DELETE",
  });
}

/**
 * 获取工作流列表
 */
export async function listWorkflows(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<WorkflowListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.status) {
    queryParams.append("status", params.status);
  }
  if (params?.limit) {
    queryParams.append("limit", params.limit.toString());
  }
  if (params?.offset) {
    queryParams.append("offset", params.offset.toString());
  }
  
  const queryString = queryParams.toString();
  const path = queryString ? `workflows?${queryString}` : "workflows";
  
  return apiRequest<WorkflowListResponse>(path);
}

/**
 * 保存工作流草稿
 */
export async function saveDraft(
  workflowId: string,
  data: SaveDraftRequest
): Promise<WorkflowDraft> {
  return apiRequest<WorkflowDraft>(`workflows/${workflowId}/draft`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * 获取工作流的运行列表
 */
export async function getWorkflowRuns(
  workflowId: string,
  params?: {
    status?: string;
    limit?: number;
    offset?: number;
  }
): Promise<{
  runs: Array<{
    id: string;
    workflow_id: string;
    status: string;
    created_at: string;
    started_at?: string;
    finished_at?: string;
    created_by?: string;
    created_by_name?: string;
  }>;
  total: number;
  limit: number;
  offset: number;
}> {
  const queryParams = new URLSearchParams();
  if (params?.status) {
    queryParams.append("status", params.status);
  }
  if (params?.limit) {
    queryParams.append("limit", params.limit.toString());
  }
  if (params?.offset) {
    queryParams.append("offset", params.offset.toString());
  }
  
  const queryString = queryParams.toString();
  const path = queryString
    ? `workflows/${workflowId}/runs?${queryString}`
    : `workflows/${workflowId}/runs`;
  
  return apiRequest(path);
}

/**
 * 获取运行状态摘要（用于状态恢复）
 */
export async function getRunStatus(
  workflowId: string,
  runId: string
): Promise<{
  run_id: string;
  run_status: string;
  node_statuses: Record<string, {
    status: string;
    output?: any;
    error?: any;
    metrics?: any;
    started_at?: string;
    finished_at?: string;
  }>;
}> {
  return apiRequest(`workflows/${workflowId}/runs/${runId}/status`);
}

/**
 * 获取工作流运行的完整结果
 */
export async function getWorkflowRun(
  workflowId: string,
  runId: string
): Promise<{
  id: string;
  workflow_id: string;
  status: string;
  output?: Record<string, any>; // node_outputs
  created_at: string;
  started_at?: string;
  finished_at?: string;
  created_by?: string;
  created_by_name?: string;
}> {
  return apiRequest(`workflows/${workflowId}/runs/${runId}`);
}

/**
 * 获取工作流草稿
 */
export async function getDraft(
  workflowId: string,
  version?: number
): Promise<WorkflowDraft> {
  const queryParams = new URLSearchParams();
  if (version !== undefined) {
    queryParams.append("version", version.toString());
  }
  
  const queryString = queryParams.toString();
  const path = queryString
    ? `workflows/${workflowId}/draft?${queryString}`
    : `workflows/${workflowId}/draft`;
  
  return apiRequest<WorkflowDraft>(path);
}

/**
 * 删除工作流草稿
 */
export async function deleteDraft(
  workflowId: string,
  version?: number
): Promise<{ success: boolean; message: string }> {
  const queryParams = new URLSearchParams();
  if (version !== undefined) {
    queryParams.append("version", version.toString());
  }
  
  const queryString = queryParams.toString();
  const path = queryString
    ? `workflows/${workflowId}/draft?${queryString}`
    : `workflows/${workflowId}/draft`;
  
  return apiRequest<{ success: boolean; message: string }>(path, {
    method: "DELETE",
  });
}

/**
 * 创建工作流发布
 */
export async function createRelease(
  workflowId: string,
  data: CreateReleaseRequest
): Promise<WorkflowRelease> {
  return apiRequest<WorkflowRelease>(`workflows/${workflowId}/release`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * 获取工作流的发布列表
 */
export async function listReleases(workflowId: string): Promise<{ releases: WorkflowRelease[] }> {
  return apiRequest<{ releases: WorkflowRelease[] }>(`workflows/${workflowId}/releases`);
}

/**
 * 工具定义接口
 */
export interface ToolDefinition {
  name: string;
  description: string;
  parameters: Array<{
    name: string;
    type: string;
    description?: string;
    required?: boolean;
    default?: any;
    enum?: any[];
  }>;
}

/**
 * 获取可用工具列表
 */
export async function getAvailableTools(): Promise<ToolDefinition[]> {
  return apiRequest<ToolDefinition[]>("workflow/tools");
}

/**
 * 执行工作流请求
 */
export interface ExecuteWorkflowRequest {
  workflowId: string;
  inputs?: Record<string, any>;
  files?: string[];
  threadId?: string;
  /** 直接用草稿执行（不依赖 current_release_id） */
  useDraft?: boolean;
  /** 可选：指定草稿ID，不填则使用该工作流最新草稿 */
  draftId?: string;
}

/**
 * 执行工作流响应
 */
export interface ExecuteWorkflowResponse {
  success: boolean;
  result: {
    run_id: string;
  };
}

/**
 * 执行工作流（异步，返回 run_id）
 */
export async function executeWorkflow(
  data: ExecuteWorkflowRequest
): Promise<ExecuteWorkflowResponse> {
  return apiRequest<ExecuteWorkflowResponse>("workflow/execute", {
    method: "POST",
    body: JSON.stringify({
      workflowId: data.workflowId,
      inputs: data.inputs || {},
      files: data.files,
      threadId: data.threadId,
      useDraft: data.useDraft,
      draftId: data.draftId,
    }),
  });
}

/**
 * 工作流执行事件类型
 */
export interface WorkflowExecutionEvent {
  type: "run_start" | "log" | "node_start" | "node_success" | "node_error" | "run_end" | "error";
  run_id?: string;
  node_id?: string;
  level?: string;
  event?: string;
  payload?: any;
  success?: boolean;
  error?: string;
  time?: string;
}

/**
 * 流式执行工作流（SSE）
 */
export async function* executeWorkflowStream(
  data: ExecuteWorkflowRequest
): AsyncGenerator<WorkflowExecutionEvent> {
  const url = resolveServiceURL("workflow/execute/stream");
  const token = useAuthStore.getState().token;
  
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  
  for await (const streamEvent of fetchStream(url, {
    method: "POST",
    headers,
    body: JSON.stringify({
      workflowId: data.workflowId,
      inputs: data.inputs || {},
      files: data.files,
      threadId: data.threadId,
      useDraft: data.useDraft,
      draftId: data.draftId,
    }),
  })) {
    if (streamEvent.data) {
      try {
        const eventData = JSON.parse(streamEvent.data) as WorkflowExecutionEvent;
        yield eventData;
      } catch (e) {
        console.error("Failed to parse workflow event:", e, streamEvent.data);
      }
    }
  }
}
