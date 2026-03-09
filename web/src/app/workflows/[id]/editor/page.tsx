// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getWorkflow, getDraft, saveDraft } from "~/core/api/workflow";
import type { Workflow, WorkflowDraft } from "~/core/api/workflow";
import { WorkflowEditor } from "~/components/workflow/editor/WorkflowEditor";

export default function WorkflowEditorPage() {
  const params = useParams();
  const router = useRouter();
  const workflowId = params.id as string;
  
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadWorkflow();
  }, [workflowId]);

  const loadWorkflow = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // 加载工作流基本信息
      const workflowData = await getWorkflow(workflowId);
      setWorkflow(workflowData);
      
      // 加载草稿（如果有）
      try {
        const draftData = await getDraft(workflowId);
        setDraft(draftData);
      } catch (e) {
        // 如果没有草稿，使用空配置
        console.log("No draft found, using empty config");
        setDraft(null);
      }
    } catch (err: any) {
      setError(err.message || "加载工作流失败");
      console.error("Error loading workflow:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (graph: { nodes: any[]; edges: any[] }, isAutosave: boolean = false) => {
    try {
      const savedDraft = await saveDraft(workflowId, {
        graph,
        is_autosave: isAutosave,
      });
      setDraft(savedDraft);
      return savedDraft;
    } catch (err: any) {
      console.error("Error saving draft:", err);
      throw err;
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <div className="text-lg font-semibold">加载中...</div>
          <div className="text-sm text-muted-foreground mt-2">正在加载工作流编辑器</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <div className="text-lg font-semibold text-destructive">加载失败</div>
          <div className="text-sm text-muted-foreground mt-2">{error}</div>
          <button
            onClick={() => router.back()}
            className="mt-4 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
          >
            返回
          </button>
        </div>
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <div className="text-lg font-semibold">工作流不存在</div>
          <button
            onClick={() => router.back()}
            className="mt-4 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
          >
            返回
          </button>
        </div>
      </div>
    );
  }

  // 初始化节点和边
  const initialNodes = draft?.graph?.nodes || [];
  const initialEdges = draft?.graph?.edges || [];

  return (
    <div className="flex h-screen w-screen flex-col">
      <WorkflowEditor
        workflowId={workflowId}
        workflowName={workflow.name}
        initialNodes={initialNodes}
        initialEdges={initialEdges}
        onSave={handleSave}
        onBack={() => router.push("/workflows")}
      />
    </div>
  );
}

