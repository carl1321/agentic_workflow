# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse

from src.server.auth.dependencies import CurrentUser, get_current_user_optional
from src.server.plan import coordinator, planner
from src.server.plan import spec as plan_spec
from src.server.plan.db import (
  append_plan_log,
  append_plan_message,
  create_plan,
  create_tasks,
  delete_plan,
  get_db_connection,
  get_artifact,
  get_plan,
  list_artifacts,
  list_logs,
  list_logs_since,
  list_plan_messages,
  list_plan_messages_since,
  list_plans,
  list_tasks,
  update_plan,
  update_task_status,
)
from src.server.plan.models import (
  ClarifyRequest,
  ClarifyResponse,
  FinalizeRequest,
  FinalizeResponse,
  ListPlansResponse,
  ListLogsResponse,
  LogItem,
  ListPlanMessagesResponse,
  PlanCreateRequest,
  PlanCreateResponse,
  PlanDetail,
  PlanDetailResponse,
  PlanSummary,
  RunRequest,
  RunResponse,
  SendPlanMessageRequest,
  SendPlanMessageResponse,
  PlanMessageItem,
  TaskItem,
  ArtifactItem,
  TerminateRequest,
  TerminateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _json_or_obj(v: Any):
  if v is None:
    return None
  if isinstance(v, (dict, list)):
    return v
  if isinstance(v, str):
    try:
      return json.loads(v)
    except Exception:
      return v
  return v


def _outputs_root_for_plan(plan_id: UUID) -> Path:
  # workspace_root/outputs/plans/{plan_id}
  return Path(__file__).resolve().parents[3] / "outputs" / "plans" / str(plan_id)


def _safe_resolve_under(root: Path, relpath: str) -> Path:
  """
  防止路径穿越：只允许访问 root 目录下的文件。
  relpath 为空或指向 root 外会抛 HTTPException(400)。
  """
  if not relpath or not str(relpath).strip():
    raise HTTPException(status_code=400, detail="path is required")
  # 统一分隔符，去掉开头的 /
  rel = str(relpath).replace("\\", "/").lstrip("/")
  if ".." in rel.split("/"):
    raise HTTPException(status_code=400, detail="invalid path")
  p = (root / rel).resolve()
  root_resolved = root.resolve()
  try:
    p.relative_to(root_resolved)
  except Exception:
    raise HTTPException(status_code=400, detail="invalid path")
  return p


async def _auto_finalize_and_run(
  conn,
  plan_uuid: UUID,
  *,
  raw_goal: str,
  clarify: Dict[str, Any],
  user_id: Optional[UUID],
  model: Optional[str] = None,
  auto_run: bool = True,
) -> None:
  """当澄清完成后，自动生成任务并启动计划执行。"""
  ora_spec = coordinator.build_ora_spec(raw_goal or "", clarify or {})
  existing_tasks = list_tasks(conn, plan_uuid)
  created = 0
  if not existing_tasks:
    tasks = await planner.build_tasks_from_goal(
      plan_id=str(plan_uuid),
      ora_spec=ora_spec,
      use_llm=True,
      model_name=model,
      plan_type=clarify.get("plan_type") if clarify else None,
      sub_type=clarify.get("sub_type") if clarify else None,
    )
    tasks = planner.make_ready_status(tasks)
    created = create_tasks(conn, plan_uuid, tasks)

  update_plan(conn, plan_uuid, user_id=user_id, status="active", ora_spec=ora_spec, spec_version_inc=True)
  append_plan_log(conn, plan_uuid, level="info", event="plan_finalized", payload={"tasksCreated": created})

  if auto_run:
    update_plan(conn, plan_uuid, user_id=user_id, status="running")
    append_plan_log(
      conn,
      plan_uuid,
      level="info",
      event="plan_run",
      payload={
        "dryRun": False,
        "title": "计划已开始执行",
        "icon": "info",
        "bullets": ["任务将按依赖顺序依次执行，请查看下方实时日志。"],
      },
    )


async def _run_initial_clarify(
  plan_id: UUID,
  goal: str,
  user_id: Optional[UUID],
) -> None:
  """后台执行首轮澄清（LLM）：目标清晰则直接启动规划任务链，不清晰则追加澄清问题。"""
  conn = get_db_connection()
  try:
    clarify_state: Dict[str, Any] = {"round": 0, "qa": []}
    done, question, extra = await coordinator.get_next_question_llm(goal or "", clarify_state)
    clarify_state["done"] = done
    clarify_state["last_question"] = question
    if extra:
      clarify_state["plan_type"] = extra.get("plan_type", "simple")
      clarify_state["sub_type"] = extra.get("sub_type")
    update_plan(conn, plan_id, user_id=user_id, clarify=clarify_state)

    if done:
      # 目标清晰，直接启动规划任务链
      try:
        await _auto_finalize_and_run(
          conn,
          plan_id,
          raw_goal=goal or "",
          clarify=clarify_state,
          user_id=user_id,
          model=None,
          auto_run=True,
        )
      except Exception as e:
        logger.exception("Auto finalize_and_run failed: %s", e)
        append_plan_message(
          conn,
          plan_id,
          role="assistant",
          content="计划生成任务时遇到问题，请稍后重试。",
          meta={"event": "error"},
        )
      return

    if question:
      # 目标不清晰，追加澄清问题
      append_plan_message(conn, plan_id, role="assistant", content=question, meta={"event": "clarify_question"})
      append_plan_log(
        conn,
        plan_id,
        level="info",
        event="clarify_question",
        payload={"question": question, "round": clarify_state.get("round", 0)},
      )
  except Exception as e:
    logger.exception("Auto clarify failed: %s", e)
  finally:
    try:
      conn.close()
    except Exception:
      pass


@router.post("", response_model=PlanCreateResponse)
async def create_plan_endpoint(
  request: PlanCreateRequest,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_id = create_plan(
      conn,
      user_id=current_user.id if current_user else None,
      title=request.title,
      raw_goal=request.goal,
    )
    append_plan_log(conn, plan_id, level="info", event="plan_created", payload={"title": request.title})

    # 初始化：通用欢迎语
    try:
      welcome = "请描述你的目标或补充信息，我会据此判断是否需要进一步澄清。"
      append_plan_message(conn, plan_id, role="assistant", content=welcome, meta={"event": "plan_created"})
    except Exception as e:
      logger.warning(f"Failed to append initial plan message: {e}")

    # 先返回 planId，首轮澄清放到后台执行，避免接口超时、前端弹框不关
    asyncio.create_task(
      _run_initial_clarify(
        plan_id,
        goal=request.goal or "",
        user_id=current_user.id if current_user else None,
      )
    )
    return PlanCreateResponse(planId=str(plan_id))
  finally:
    conn.close()


@router.get("", response_model=ListPlansResponse)
async def list_plans_endpoint(
  limit: int = Query(50, ge=1, le=200),
  offset: int = Query(0, ge=0),
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    rows = list_plans(conn, user_id=current_user.id if current_user else None, limit=limit, offset=offset)
    plans = [
      PlanSummary(
        id=str(r["id"]),
        title=r.get("title"),
        status=r.get("status") or "draft",
        createdAt=r.get("created_at"),
        updatedAt=r.get("updated_at"),
      )
      for r in rows
    ]
    return ListPlansResponse(plans=plans)
  finally:
    conn.close()


@router.get("/{plan_id}", response_model=PlanDetailResponse)
async def get_plan_endpoint(
  plan_id: str,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    tasks = list_tasks(conn, plan_uuid)
    artifacts = list_artifacts(conn, plan_uuid)

    plan = PlanDetail(
      id=str(p["id"]),
      title=p.get("title"),
      status=p.get("status") or "draft",
      rawGoal=p.get("raw_goal"),
      oraSpec=_json_or_obj(p.get("ora_spec")),
      clarify=_json_or_obj(p.get("clarify")),
      specVersion=int(p.get("spec_version") or 1),
      createdAt=p.get("created_at"),
      updatedAt=p.get("updated_at"),
      tasks=[
        TaskItem(
          id=str(t["id"]),
          planId=str(t["plan_id"]),
          name=t.get("name") or "",
          description=t.get("description"),
          acceptanceCriteria=t.get("acceptance_criteria"),
          status=t.get("status") or "pending",
          dependsOn=_json_or_obj(t.get("depends_on")) or [],
          scheduledAt=t.get("scheduled_at"),
          startedAt=t.get("started_at"),
          finishedAt=t.get("finished_at"),
          executorType=t.get("executor_type") or "file",
          executorArgs=_json_or_obj(t.get("executor_args")) or {},
          idempotencyKey=t.get("idempotency_key"),
        )
        for t in tasks
      ],
      artifacts=[
        ArtifactItem(
          id=str(a["id"]),
          planId=str(a["plan_id"]),
          taskId=str(a["task_id"]),
          type=a.get("type") or "file",
          filePath=a.get("file_path") or "",
          meta=_json_or_obj(a.get("meta")) or {},
          createdAt=a.get("created_at"),
        )
        for a in artifacts
      ],
    )

    return PlanDetailResponse(plan=plan)
  finally:
    conn.close()


@router.delete("/{plan_id}", status_code=204)
async def delete_plan_endpoint(
  plan_id: str,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """删除长期计划（关联任务、日志、消息等由数据库级联删除）。"""
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    deleted = delete_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not deleted:
      raise HTTPException(status_code=404, detail="Plan not found")
  finally:
    conn.close()


@router.get("/{plan_id}/logs", response_model=ListLogsResponse)
async def list_plan_logs_endpoint(
  plan_id: str,
  limit: int = Query(200, ge=1, le=2000),
  offset: int = Query(0, ge=0),
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    rows = list_logs(conn, plan_uuid, limit=limit, offset=offset)
    logs = [
      LogItem(
        id=str(r["id"]),
        planId=str(r["plan_id"]),
        taskId=str(r["task_id"]) if r.get("task_id") else None,
        level=r.get("level") or "info",
        event=r.get("event") or "",
        payload=_json_or_obj(r.get("payload")) or {},
        createdAt=r.get("created_at"),
      )
      for r in rows
    ]
    return ListLogsResponse(logs=logs)
  finally:
    conn.close()


@router.get("/{plan_id}/artifacts/{artifact_id}/content")
async def get_artifact_content_endpoint(
  plan_id: str,
  artifact_id: str,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """
  获取产物文件内容（MVP：仅文本预览）。
  """
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    art = get_artifact(conn, plan_uuid, UUID(artifact_id))
    if not art:
      raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = art.get("file_path") or ""
    if not file_path:
      raise HTTPException(status_code=404, detail="Artifact file_path is empty")

    try:
      # 限制读取大小，避免大文件拖垮响应
      max_bytes = 200_000
      with open(file_path, "rb") as f:
        data = f.read(max_bytes + 1)
      truncated = len(data) > max_bytes
      text = data[:max_bytes].decode("utf-8", errors="replace")
    except FileNotFoundError:
      raise HTTPException(status_code=404, detail="Artifact file not found on disk")

    return {
      "success": True,
      "filePath": file_path,
      "content": text,
      "truncated": truncated,
    }
  finally:
    conn.close()


@router.post("/{plan_id}/clarify", response_model=ClarifyResponse)
async def clarify_plan_endpoint(
  plan_id: str,
  request: ClarifyRequest,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    clarify = _json_or_obj(p.get("clarify")) or {"round": 0, "qa": []}
    clarify2 = coordinator.apply_answer(clarify, request.answer)
    done, q, extra = await coordinator.get_next_question_llm(p.get("raw_goal") or "", clarify2)
    clarify2["done"] = done
    clarify2["last_question"] = q
    if extra:
      clarify2["plan_type"] = extra.get("plan_type", "simple")
      clarify2["sub_type"] = extra.get("sub_type")
    ora_draft = coordinator.build_ora_spec(p.get("raw_goal") or "", clarify2)

    update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, clarify=clarify2)
    append_plan_log(conn, plan_uuid, level="info", event="clarify_answer", payload={"round": clarify2.get("round"), "answer": request.answer})

    # 若澄清已完成，自动生成任务并启动执行；否则继续追问
    if done:
      await _auto_finalize_and_run(
        conn,
        plan_uuid,
        raw_goal=p.get("raw_goal") or "",
        clarify=clarify2,
        user_id=current_user.id if current_user else None,
        model=request.model if hasattr(request, "model") else None,
        auto_run=True,
      )
    elif q:
      # 继续追问时，把问题写入对话消息，前端聊天区可直接展示
      append_plan_message(conn, plan_uuid, role="assistant", content=q, meta={"event": "clarify_question"})
      append_plan_log(
        conn,
        plan_uuid,
        level="info",
        event="clarify_question",
        payload={"question": q, "round": clarify2.get("round", 0)},
      )

    return ClarifyResponse(
      round=int(clarify2.get("round") or 0),
      question=q,
      done=done,
      oraDraft=ora_draft,
    )
  finally:
    conn.close()


@router.get("/{plan_id}/clarify", response_model=ClarifyResponse)
async def get_clarify_question_endpoint(
  plan_id: str,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """获取当前轮的澄清状态（从存储的 clarify 读取 last_question 与 done，不触发 LLM）。"""
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    clarify = _json_or_obj(p.get("clarify")) or {"round": 0, "qa": []}
    done = clarify.get("done", False)
    q = clarify.get("last_question")
    ora_draft = coordinator.build_ora_spec(p.get("raw_goal") or "", clarify)
    return ClarifyResponse(
      round=int(clarify.get("round") or 0),
      question=q,
      done=done,
      oraDraft=ora_draft,
    )
  finally:
    conn.close()


@router.post("/{plan_id}/finalize", response_model=FinalizeResponse)
async def finalize_plan_endpoint(
  plan_id: str,
  request: FinalizeRequest,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    clarify = _json_or_obj(p.get("clarify")) or {"round": 0, "qa": []}
    ora_spec = coordinator.build_ora_spec(p.get("raw_goal") or "", clarify)

    tasks = await planner.build_tasks_from_goal(
      plan_id=str(plan_uuid),
      ora_spec=ora_spec,
      use_llm=True,
      model_name=request.model,
      plan_type=clarify.get("plan_type"),
      sub_type=clarify.get("sub_type"),
    )
    tasks = planner.make_ready_status(tasks)

    created = create_tasks(conn, plan_uuid, tasks)
    update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, status="active", ora_spec=ora_spec, spec_version_inc=True)
    append_plan_log(conn, plan_uuid, level="info", event="plan_finalized", payload={"tasksCreated": created})

    return FinalizeResponse(planId=plan_id, tasksCreated=created)
  finally:
    conn.close()


@router.post("/{plan_id}/run", response_model=RunResponse)
async def run_plan_endpoint(
  plan_id: str,
  request: RunRequest,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, status="running")
    append_plan_log(
      conn,
      plan_uuid,
      level="info",
      event="plan_run",
      payload={
        "dryRun": request.dryRun,
        "title": "计划已开始执行",
        "icon": "info",
        "bullets": ["任务将按依赖顺序依次执行，请查看下方实时日志。"],
      },
    )

    # 调度器在 executor-worker todo 中接入；这里先仅更新状态即可
    return RunResponse(planId=plan_id, status="running")
  finally:
    conn.close()


@router.post("/{plan_id}/terminate", response_model=TerminateResponse)
async def terminate_plan_endpoint(
  plan_id: str,
  request: TerminateRequest,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """终止计划：取消所有未执行任务，写日志/spec，并发布计划事件。"""
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    reason = request.reason or "用户手动终止计划"
    update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, status="terminated")

    tasks = list_tasks(conn, plan_uuid)
    canceled: list[str] = []
    now = datetime.now()
    for t in tasks:
      if (t.get("status") or "").lower() in {"pending", "ready", "skipped"}:
        update_task_status(
          conn,
          t.get("id"),
          status="canceled",
          finished_at=now,
          error={"canceled": True, "reason": f"计划终止：{reason}"},
        )
        canceled.append(t.get("name") or str(t.get("id")))

    append_plan_log(
      conn,
      plan_uuid,
      level="warning",
      event="plan_terminated",
      payload={
        "title": "计划已终止",
        "icon": "error",
        "reason": reason,
        "canceled": canceled,
        "bullets": [
          f"终止原因：{reason}",
          f"取消未执行任务数：{len(canceled)}",
        ],
      },
    )
    plan_spec.append_spec_milestone(
      plan_uuid,
      f"计划已终止，原因：{reason}；取消任务：{', '.join(canceled) if canceled else '无'}",
    )
    return TerminateResponse(planId=str(plan_uuid), status="terminated")
  finally:
    conn.close()


def _as_dt(v: Any) -> Optional[datetime]:
  if v is None:
    return None
  if isinstance(v, datetime):
    return v
  if isinstance(v, str):
    # 支持 ISO 字符串；无 tz 时按 UTC 处理
    try:
      dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
      if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
      return dt
    except Exception:
      return None
  return None


@router.get("/{plan_id}/messages", response_model=ListPlanMessagesResponse)
async def list_plan_messages_endpoint(
  plan_id: str,
  limit: int = Query(200, ge=1, le=2000),
  offset: int = Query(0, ge=0),
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")
    rows = list_plan_messages(conn, plan_uuid, limit=limit, offset=offset)
    msgs = [
      PlanMessageItem(
        id=str(r["id"]),
        planId=str(r["plan_id"]),
        role=str(r.get("role") or "assistant"),
        content=str(r.get("content") or ""),
        meta=_json_or_obj(r.get("meta")) or {},
        createdAt=r.get("created_at"),
      )
      for r in rows
    ]
    return ListPlanMessagesResponse(messages=msgs)
  finally:
    conn.close()


@router.post("/{plan_id}/messages", response_model=SendPlanMessageResponse)
async def send_plan_message_endpoint(
  plan_id: str,
  request: SendPlanMessageRequest,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """
  计划对话：用户发一条消息，服务端会推进澄清/生成任务，并返回新增的消息（user + assistant）。
  """
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")

    user_content = request.content.strip()
    if not user_content:
      raise HTTPException(status_code=400, detail="content is required")

    created_msgs: list[PlanMessageItem] = []

    # 1) 写入用户消息
    user_msg_id = append_plan_message(conn, plan_uuid, role="user", content=user_content, meta={})
    created_msgs.append(
      PlanMessageItem(id=str(user_msg_id), planId=plan_id, role="user", content=user_content, meta={}, createdAt=None)
    )

    # 2) 推进澄清或给出回复（由 LLM 动态判断是否还需澄清）
    clarify = _json_or_obj(p.get("clarify")) or {"round": 0, "qa": []}
    in_clarify = (p.get("status") or "draft") == "draft"
    raw_goal = (p.get("raw_goal") or "").strip()
    # 若创建时未填目标，用首条用户消息作为目标并写回
    if in_clarify and coordinator.get_round(clarify) == 0 and not raw_goal:
      update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, raw_goal=user_content)
      raw_goal = user_content

    assistant_content: str
    if in_clarify:
      clarify2 = coordinator.apply_answer(clarify, user_content)
      done, next_q, extra = await coordinator.get_next_question_llm(raw_goal, clarify2)
      clarify2["done"] = done
      clarify2["last_question"] = next_q
      if extra:
        clarify2["plan_type"] = extra.get("plan_type", "simple")
        clarify2["sub_type"] = extra.get("sub_type")
      ora_spec = coordinator.build_ora_spec(raw_goal, clarify2)

      update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, clarify=clarify2)
      append_plan_log(conn, plan_uuid, level="info", event="clarify_answer", payload={"round": clarify2.get("round"), "answer": user_content})

      if not done and next_q:
        assistant_content = next_q
      else:
        # 澄清结束：由大模型根据用户目标规划任务并开始执行
        tasks = await planner.build_tasks_from_goal(
          plan_id=str(plan_uuid),
          ora_spec=ora_spec,
          use_llm=True,
          model_name=None,
          plan_type=clarify2.get("plan_type"),
          sub_type=clarify2.get("sub_type"),
        )
        tasks = planner.make_ready_status(tasks)
        created = create_tasks(conn, plan_uuid, tasks)
        update_plan(conn, plan_uuid, user_id=current_user.id if current_user else None, status="running", ora_spec=ora_spec, spec_version_inc=True)
        append_plan_log(
          conn,
          plan_uuid,
          level="info",
          event="plan_finalized",
          payload={
            "tasksCreated": created,
            "title": "已生成执行任务，开始依次执行",
            "icon": "success",
            "bullets": [f"已创建 {created} 个任务，将按依赖顺序自动执行。", "你可以在下方查看实时日志与产物。"],
          },
        )
        assistant_content = f"澄清完成：我已经为你生成了 {created} 个任务，并已开始自动执行。你可以在右侧查看实时日志与产物。"
    else:
      # 已非澄清阶段：用户输入当作补充信息
      append_plan_log(conn, plan_uuid, level="info", event="plan_message", payload={"content": user_content})
      assistant_content = "收到你的补充。我会在后续任务执行与复盘中参考这条信息。"

    assistant_msg_id = append_plan_message(conn, plan_uuid, role="assistant", content=assistant_content, meta={})
    created_msgs.append(
      PlanMessageItem(id=str(assistant_msg_id), planId=plan_id, role="assistant", content=assistant_content, meta={}, createdAt=None)
    )

    return SendPlanMessageResponse(messages=created_msgs)
  finally:
    conn.close()


@router.get("/{plan_id}/events")
async def plan_events_sse(
  request: Request,
  plan_id: str,
  since: Optional[str] = Query(None, description="ISO timestamp; stream items with created_at > since"),
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """
  SSE：推送计划消息 + 计划日志（Coze-like 实时滚动体验）。
  """
  plan_uuid = UUID(plan_id)
  since_dt = _as_dt(since) or datetime(1970, 1, 1, tzinfo=timezone.utc)

  async def gen():
    conn = get_db_connection()
    msg_cursor = since_dt
    log_cursor = since_dt
    last_ping = datetime.now(timezone.utc)
    try:
      # 权限校验
      p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
      if not p:
        yield "event: error\ndata: " + json.dumps({"error": "Plan not found"}) + "\n\n"
        return

      while True:
        if await request.is_disconnected():
          return
        # 每次轮询前结束当前事务，以便看到后台任务新提交的消息（如首轮澄清）
        try:
          conn.rollback()
        except Exception:
          pass

        # 1) messages
        new_msgs = list_plan_messages_since(conn, plan_uuid, since=msg_cursor, limit=500)
        for m in new_msgs:
          created_at = _as_dt(m.get("created_at")) or msg_cursor
          if created_at > msg_cursor:
            msg_cursor = created_at
          payload = {
            "id": str(m["id"]),
            "planId": str(m["plan_id"]),
            "role": m.get("role") or "assistant",
            "content": m.get("content") or "",
            "meta": _json_or_obj(m.get("meta")) or {},
            "createdAt": m.get("created_at").isoformat() if m.get("created_at") else None,
          }
          yield "event: message\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        # 2) logs
        new_logs = list_logs_since(conn, plan_uuid, since=log_cursor, limit=500)
        for l in new_logs:
          created_at = _as_dt(l.get("created_at")) or log_cursor
          if created_at > log_cursor:
            log_cursor = created_at
          payload = {
            "id": str(l["id"]),
            "planId": str(l["plan_id"]),
            "taskId": str(l["task_id"]) if l.get("task_id") else None,
            "level": l.get("level") or "info",
            "event": l.get("event") or "",
            "payload": _json_or_obj(l.get("payload")) or {},
            "createdAt": l.get("created_at").isoformat() if l.get("created_at") else None,
          }
          yield "event: log\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        # keepalive ping (comment)
        now = datetime.now(timezone.utc)
        if (now - last_ping).total_seconds() >= 15:
          last_ping = now
          yield ": ping\n\n"

        await asyncio.sleep(0.5)
    finally:
      conn.close()

  return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{plan_id}/outputs")
async def list_plan_outputs_endpoint(
  plan_id: str,
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """列出 outputs/plans/{plan_id} 下的文件（不依赖 artifact 表）。"""
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")
  finally:
    conn.close()

  root = _outputs_root_for_plan(plan_uuid)
  items: List[Dict[str, Any]] = []
  if root.exists():
    # 控制规模：最多收集 2000 项，避免大目录拖垮接口
    for dirpath, dirnames, filenames in os.walk(root):
      # 按相对路径稳定排序
      dirnames.sort()
      filenames.sort()
      for d in dirnames:
        full = Path(dirpath) / d
        rel = str(full.relative_to(root)).replace("\\", "/")
        try:
          st = full.stat()
          items.append({"relpath": rel, "isDir": True, "size": 0, "mtime": datetime.fromtimestamp(st.st_mtime).isoformat()})
        except Exception:
          items.append({"relpath": rel, "isDir": True, "size": 0, "mtime": None})
        if len(items) >= 2000:
          break
      if len(items) >= 2000:
        break
      for f in filenames:
        full = Path(dirpath) / f
        rel = str(full.relative_to(root)).replace("\\", "/")
        try:
          st = full.stat()
          items.append(
            {"relpath": rel, "isDir": False, "size": int(st.st_size), "mtime": datetime.fromtimestamp(st.st_mtime).isoformat()}
          )
        except Exception:
          items.append({"relpath": rel, "isDir": False, "size": 0, "mtime": None})
        if len(items) >= 2000:
          break
      if len(items) >= 2000:
        break

  # 目录优先、再按 relpath
  items.sort(key=lambda x: (0 if x.get("isDir") else 1, str(x.get("relpath") or "")))
  return {"success": True, "items": items}


@router.get("/{plan_id}/outputs/preview")
async def preview_plan_output_endpoint(
  plan_id: str,
  path: str = Query(..., description="相对 outputs/plans/{plan_id} 的路径"),
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """文本预览：限制最大读取字节，避免大文件拖垮响应。"""
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")
  finally:
    conn.close()

  root = _outputs_root_for_plan(UUID(plan_id))
  full = _safe_resolve_under(root, path)
  if not full.exists() or not full.is_file():
    raise HTTPException(status_code=404, detail="File not found")

  max_bytes = 200_000
  with open(full, "rb") as f:
    data = f.read(max_bytes + 1)
  truncated = len(data) > max_bytes
  text = data[:max_bytes].decode("utf-8", errors="replace")
  return {"success": True, "path": path, "content": text, "truncated": truncated}


@router.get("/{plan_id}/outputs/download")
async def download_plan_output_endpoint(
  plan_id: str,
  path: str = Query(..., description="相对 outputs/plans/{plan_id} 的路径"),
  current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
  """下载 outputs 文件（二进制也支持）。"""
  conn = get_db_connection()
  try:
    plan_uuid = UUID(plan_id)
    p = get_plan(conn, plan_uuid, user_id=current_user.id if current_user else None)
    if not p:
      raise HTTPException(status_code=404, detail="Plan not found")
  finally:
    conn.close()

  root = _outputs_root_for_plan(UUID(plan_id))
  full = _safe_resolve_under(root, path)
  if not full.exists() or not full.is_file():
    raise HTTPException(status_code=404, detail="File not found")

  return FileResponse(path=str(full), filename=full.name)

