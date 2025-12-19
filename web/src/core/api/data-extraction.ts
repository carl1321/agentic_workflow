// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export interface DataExtractionRecord {
  id: string;
  task_id?: string;
  task_name?: string;
  extraction_type: string;
  extraction_step: number;
  file_name?: string;
  file_size?: number;
  file_base64?: string;
  pdf_url?: string;
  model_name?: string;
  categories?: {
    materials: string[];
    processes: string[];
    properties: string[];
  };
  selected_categories?: {
    materials: string[];
    processes: string[];
    properties: string[];
  };
  table_data?: Array<{
    material: string;
    process: string;
    property: string;
  }>;
  result_json?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface DataExtractionRecordRequest {
  task_name?: string;
  extraction_type?: string;
  extraction_step?: number;
  file_name?: string;
  file_size?: number;
  file_base64?: string;
  pdf_url?: string;
  model_name?: string;
  categories?: {
    materials: string[];
    processes: string[];
    properties: string[];
  };
  selected_categories?: {
    materials: string[];
    processes: string[];
    properties: string[];
  };
  table_data?: Array<{
    material: string;
    process: string;
    property: string;
  }>;
  result_json?: string;
  metadata?: Record<string, unknown>;
  record_id?: string; // Deprecated, use task_id instead
  task_id?: string;
}

export interface DataExtractionRecordListResponse {
  records: DataExtractionRecord[];
  total: number;
  limit: number;
  offset: number;
}

import { resolveServiceURL } from "./resolve-service-url";

export async function saveExtractionRecord(
  record: DataExtractionRecordRequest
): Promise<DataExtractionRecord> {
  const response = await fetch(resolveServiceURL("data-extraction/records"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(record),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Failed to save record: ${response.statusText}`);
  }

  return response.json();
}

export async function getExtractionRecords(
  limit: number = 50,
  offset: number = 0,
  extraction_type?: string
): Promise<DataExtractionRecordListResponse> {
  const params = new URLSearchParams({
    limit: limit.toString(),
    offset: offset.toString(),
  });
  if (extraction_type) {
    params.append("extraction_type", extraction_type);
  }

  const response = await fetch(
    `${resolveServiceURL("data-extraction/records")}?${params.toString()}`,
    {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Failed to get records: ${response.statusText}`);
  }

  return response.json();
}

export async function getExtractionRecord(recordId: string): Promise<DataExtractionRecord> {
  const response = await fetch(resolveServiceURL(`data-extraction/records/${recordId}`), {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Failed to get record: ${response.statusText}`);
  }

  return response.json();
}

export async function deleteExtractionRecord(recordId: string): Promise<void> {
  const response = await fetch(resolveServiceURL(`data-extraction/records/${recordId}`), {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Failed to delete record: ${response.statusText}`);
  }
}

