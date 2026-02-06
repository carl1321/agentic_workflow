# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


PlanStatus = Literal["draft", "active", "running", "succeeded", "failed", "cancelled", "terminated"]
TaskStatus = Literal["pending", "ready", "running", "succeeded", "failed", "skipped", "canceled"]
ExecutorType = Literal["llm", "tool", "file"]
PlanMessageRole = Literal["user", "assistant", "system"]


class PlanCreateRequest(BaseModel):
  title: Optional[str] = None
  goal: str = Field(..., min_length=1, description="用户的模糊/明确需求")


class PlanCreateResponse(BaseModel):
  success: bool = True
  planId: str


class ClarifyRequest(BaseModel):
  answer: str = Field(..., min_length=1)


class ClarifyResponse(BaseModel):
  success: bool = True
  round: int
  question: Optional[str] = None
  done: bool = False
  oraDraft: Optional[Dict[str, Any]] = None


class FinalizeRequest(BaseModel):
  model: Optional[str] = None


class RunRequest(BaseModel):
  # 预留：将来支持仅跑部分任务、或 dry-run
  dryRun: bool = False


class PlanSummary(BaseModel):
  id: str
  title: Optional[str] = None
  status: PlanStatus
  createdAt: Optional[datetime] = None
  updatedAt: Optional[datetime] = None


class TaskItem(BaseModel):
  id: str
  planId: str
  name: str
  description: Optional[str] = None
  acceptanceCriteria: Optional[str] = None
  status: TaskStatus
  dependsOn: List[str] = []
  scheduledAt: Optional[datetime] = None
  startedAt: Optional[datetime] = None
  finishedAt: Optional[datetime] = None
  executorType: ExecutorType
  executorArgs: Dict[str, Any] = {}
  idempotencyKey: Optional[str] = None


class ArtifactItem(BaseModel):
  id: str
  planId: str
  taskId: str
  type: str
  filePath: str
  meta: Dict[str, Any] = {}
  createdAt: Optional[datetime] = None


class LogItem(BaseModel):
  id: str
  planId: str
  taskId: Optional[str] = None
  level: str
  event: str
  payload: Dict[str, Any] = {}
  createdAt: Optional[datetime] = None


class PlanDetail(BaseModel):
  id: str
  title: Optional[str] = None
  status: PlanStatus
  rawGoal: Optional[str] = None
  oraSpec: Optional[Dict[str, Any]] = None
  clarify: Optional[Dict[str, Any]] = None
  specVersion: int = 1
  createdAt: Optional[datetime] = None
  updatedAt: Optional[datetime] = None
  tasks: List[TaskItem] = []
  artifacts: List[ArtifactItem] = []


class PlanDetailResponse(BaseModel):
  success: bool = True
  plan: PlanDetail


class ListPlansResponse(BaseModel):
  success: bool = True
  plans: List[PlanSummary] = []


class ListLogsResponse(BaseModel):
  success: bool = True
  logs: List[LogItem] = []


class PlanMessageItem(BaseModel):
  id: str
  planId: str
  role: PlanMessageRole
  content: str
  meta: Dict[str, Any] = {}
  createdAt: Optional[datetime] = None


class ListPlanMessagesResponse(BaseModel):
  success: bool = True
  messages: List[PlanMessageItem] = []


class SendPlanMessageRequest(BaseModel):
  content: str = Field(..., min_length=1)


class SendPlanMessageResponse(BaseModel):
  success: bool = True
  messages: List[PlanMessageItem] = []


class FinalizeResponse(BaseModel):
  success: bool = True
  planId: str
  tasksCreated: int = 0


class RunResponse(BaseModel):
  success: bool = True
  planId: str
  status: PlanStatus


class TerminateRequest(BaseModel):
  reason: Optional[str] = None


class TerminateResponse(BaseModel):
  success: bool = True
  planId: str
  status: PlanStatus = "terminated"

