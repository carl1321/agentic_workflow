import type { Resource } from "../messages";

import { resolveServiceURL } from "./resolve-service-url";

export interface RAGDocument {
  id: string;
  title: string;
  upload_date: string | null;
  size: number | null;
}

export interface RAGDocumentsResponse {
  documents: RAGDocument[];
  total: number;
}

export async function queryRAGResources(query: string) {
  // 使用 apiRequest 以便统一处理 401 错误
  const { apiRequest } = await import("./api-client");
  try {
    const res = await apiRequest<{ resources: Array<Resource> }>(
      `rag/resources?query=${encodeURIComponent(query)}`,
      { method: "GET" },
    );
    return res.resources;
  } catch {
    return [];
  }
}

export async function getRAGDocuments(
  resourceId: string,
  page: number = 1,
  pageSize: number = 50
): Promise<RAGDocumentsResponse> {
  // Extract dataset ID from resource URI if needed
  const datasetId = resourceId.startsWith("rag://dataset/")
    ? resourceId.replace("rag://dataset/", "")
    : resourceId;

  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  });

  // 使用 apiRequest 以便统一处理 401 错误
  const { apiRequest } = await import("./api-client");
  const res = await apiRequest<{ documents: Array<RAGDocument>; total: number }>(
    `rag/resources/${datasetId}/documents?${params}`,
    { method: "GET" },
  );
  return {
    documents: res.documents,
    total: res.total,
  };
}

export function downloadRAGDocument(
  resourceId: string,
  documentId: string
): Promise<void> {
  // Extract dataset ID from resource URI if needed
  const datasetId = resourceId.startsWith("rag://dataset/")
    ? resourceId.replace("rag://dataset/", "")
    : resourceId;

  return fetch(
    resolveServiceURL(`rag/resources/${datasetId}/documents/${documentId}/download`),
    {
      method: "GET",
    }
  )
    .then((res) => {
      if (!res.ok) {
        throw new Error(`Failed to download document: ${res.statusText}`);
      }
      
      // Try to get filename from Content-Disposition header
      const contentDisposition = res.headers.get("Content-Disposition");
      let filename = `document_${documentId}`;
      
      console.log("Content-Disposition header:", contentDisposition);
      
      if (contentDisposition) {
        // Try filename*=UTF-8'' format first (RFC 5987)
        // Match: filename*=UTF-8''<encoded> (may be followed by ; or end of string)
        const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+?)(?:;|$)/);
        if (filenameStarMatch && filenameStarMatch[1]) {
          try {
            filename = decodeURIComponent(filenameStarMatch[1]);
            console.log("Parsed filename from filename*:", filename);
          } catch (e) {
            console.error("Error decoding filename*:", e, "Encoded value:", filenameStarMatch[1]);
          }
        }
        
        // If we still have default filename, try regular filename format
        if (filename === `document_${documentId}`) {
          // Try filename="..." format
          const filenameMatch = contentDisposition.match(/filename="([^"]+)"/);
          if (filenameMatch && filenameMatch[1]) {
            filename = filenameMatch[1];
            console.log("Parsed filename from filename:", filename);
          } else {
            // Try filename=... format without quotes
            const filenameMatch2 = contentDisposition.match(/filename=([^;]+)/);
            if (filenameMatch2 && filenameMatch2[1]) {
              filename = filenameMatch2[1].trim();
              // Remove quotes if present
              filename = filename.replace(/^["']|["']$/g, '');
              console.log("Parsed filename from filename (no quotes):", filename);
            }
          }
        }
      }
      
      console.log("Final filename before blob processing:", filename);
      
      // Ensure filename has extension - if not, try to infer from blob type
      return res.blob().then((blob) => {
        // If filename doesn't have a valid extension, try to add one from blob type
        if (!filename.includes('.') || filename.split('.').pop()?.length === 0) {
          if (blob.type && blob.type !== 'application/octet-stream') {
            const ext = blob.type.split('/')[1];
            if (ext) {
              // Map common MIME types to extensions
              const extMap: Record<string, string> = {
                'pdf': 'pdf',
                'msword': 'doc',
                'vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                'vnd.ms-excel': 'xls',
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                'vnd.ms-powerpoint': 'ppt',
                'vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
                'plain': 'txt',
                'html': 'html',
                'xml': 'xml',
                'json': 'json',
              };
              const extension = extMap[ext] || ext.split('.')[0] || ext;
              filename = filename + '.' + extension;
            }
          }
        }
        
        // Create a download link and trigger download
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      });
    })
    .catch((error) => {
      console.error("Error downloading RAG document:", error);
      throw error;
    });
}
