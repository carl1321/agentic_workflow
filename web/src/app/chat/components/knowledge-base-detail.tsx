"use client";

import { ArrowLeft, FileText, Loader2, AlertCircle, Download, ChevronLeft, ChevronRight } from "lucide-react";
import { useState, useEffect } from "react";
import { cn } from "~/lib/utils";
import { getRAGDocuments, downloadRAGDocument, type RAGDocument } from "~/core/api/rag";
import type { Resource } from "~/core/messages";
import { Button } from "~/components/ui/button";

interface KnowledgeBaseDetailProps {
  resource: Resource;
  onBack: () => void;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) {
    return "未知";
  }
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "未知";
  try {
    // Try to parse as timestamp (number string) first
    const timestamp = Number(dateStr);
    let date: Date;
    if (!isNaN(timestamp) && timestamp > 0) {
      // If it's a valid number, treat as timestamp (milliseconds)
      date = new Date(timestamp);
    } else {
      // Otherwise, try to parse as ISO string
      date = new Date(dateStr);
    }
    
    // Check if date is valid
    if (isNaN(date.getTime())) {
      return dateStr;
    }
    
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

export function KnowledgeBaseDetail({ resource, onBack }: KnowledgeBaseDetailProps) {
  const [documents, setDocuments] = useState<RAGDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [downloading, setDownloading] = useState<string | null>(null);
  const pageSize = 50;

  useEffect(() => {
    const loadDocuments = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await getRAGDocuments(resource.uri, currentPage, pageSize);
        setDocuments(response.documents);
        setTotal(response.total);
      } catch (e) {
        setError((e as Error).message);
        setDocuments([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    };

    loadDocuments();
  }, [resource.uri, currentPage]);

  const handleDownload = async (documentId: string) => {
    try {
      setDownloading(documentId);
      await downloadRAGDocument(resource.uri, documentId);
    } catch (e) {
      console.error("Download failed:", e);
      alert(`下载失败: ${(e as Error).message}`);
    } finally {
      setDownloading(null);
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="flex h-full w-full flex-col bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={onBack}
            className="h-8 w-8"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/30">
            <FileText className="h-5 w-5 text-blue-600 dark:text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {resource.title}
            </h2>
            {resource.description && (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {resource.description}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-5xl mx-auto">
          {loading && (
            <div className="flex flex-col items-center justify-center h-full py-12">
              <Loader2 className="h-8 w-8 text-slate-400 animate-spin mb-2" />
              <p className="text-sm text-slate-500 dark:text-slate-400">加载文件列表...</p>
            </div>
          )}

          {error && (
            <div className="p-4 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-red-700 dark:text-red-400">
                    加载失败
                  </p>
                  <p className="text-xs text-red-600 dark:text-red-500 mt-1">
                    {error}
                  </p>
                </div>
              </div>
            </div>
          )}

          {!loading && !error && documents.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full py-12 text-center">
              <FileText className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
              <p className="text-sm text-slate-500 dark:text-slate-400">该知识库暂无文件</p>
            </div>
          )}

          {!loading && !error && documents.length > 0 && (
            <>
              <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
                      <tr>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                          文件名称
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                          上传日期
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                          大小
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                          操作
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                      {documents.map((doc) => (
                        <tr
                          key={doc.id}
                          className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                        >
                          <td className="px-4 py-3 text-sm text-slate-900 dark:text-slate-100">
                            <div className="flex items-center gap-2">
                              <FileText className="h-4 w-4 text-slate-400 flex-shrink-0" />
                              <span className="truncate">{doc.title || doc.id}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400">
                            {formatDate(doc.upload_date)}
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400">
                            {formatFileSize(doc.size)}
                          </td>
                          <td className="px-4 py-3 text-sm">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDownload(doc.id)}
                              disabled={downloading === doc.id}
                              className="h-8 w-8 p-0"
                            >
                              {downloading === doc.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Download className="h-4 w-4" />
                              )}
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              
              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <div className="text-sm text-slate-600 dark:text-slate-400">
                    共 {total} 个文件，第 {currentPage} / {totalPages} 页
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      disabled={currentPage === 1 || loading}
                    >
                      <ChevronLeft className="h-4 w-4" />
                      上一页
                    </Button>
                    <div className="flex items-center gap-1">
                      {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                        let pageNum: number;
                        if (totalPages <= 5) {
                          pageNum = i + 1;
                        } else if (currentPage <= 3) {
                          pageNum = i + 1;
                        } else if (currentPage >= totalPages - 2) {
                          pageNum = totalPages - 4 + i;
                        } else {
                          pageNum = currentPage - 2 + i;
                        }
                        return (
                          <Button
                            key={pageNum}
                            variant={currentPage === pageNum ? "default" : "outline"}
                            size="sm"
                            onClick={() => setCurrentPage(pageNum)}
                            disabled={loading}
                            className="w-8 h-8 p-0"
                          >
                            {pageNum}
                          </Button>
                        );
                      })}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      disabled={currentPage === totalPages || loading}
                    >
                      下一页
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

