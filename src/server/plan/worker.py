# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
长期计划调度器（APScheduler, MVP）。

特点：
- 单机 AsyncIOScheduler
- DB 领取 ready task 使用 FOR UPDATE SKIP LOCKED（避免并发冲突）
- 同一 plan 串行执行（acquire_next_task 已限制）
- 自动将依赖满足的 pending task 置为 ready
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.server.plan import coordinator
from src.server.plan.db import (
  acquire_next_task,
  append_plan_log,
  delete_pending_video_download,
  get_db_connection,
  get_task,
  has_plan_work,
  list_artifacts,
  list_pending_video_downloads_ready,
  list_tasks,
  update_plan,
  update_task_status,
)
from src.server.plan.executor import DeferredVideoDownload, PlanTaskExecutor
from src.server.plan.spec import append_spec_milestone, read_spec

logger = logging.getLogger(__name__)

# 按扩展名区分：文本类读内容预览，二进制类只给大小与路径
TEXT_PREVIEW_EXTENSIONS = {".md", ".json", ".srt", ".txt", ".csv", ".xml", ".html", ".yaml", ".yml"}
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".wav", ".mp3", ".webm", ".avi", ".mov"}


def _content_preview_for_path(fp: Path) -> str:
  """
  根据文件扩展名生成验收用预览：文本类读内容（截断），二进制类不读内容，返回「二进制文件，大小 xxx bytes」。
  """
  if not fp.exists() or not fp.is_file():
    return "（无产物文件）"
  suffix = fp.suffix.lower()
  if suffix in BINARY_EXTENSIONS:
    try:
      size = fp.stat().st_size
      return f"二进制文件，大小 {size} bytes"
    except Exception:
      return "二进制文件，大小未知"
  if suffix in TEXT_PREVIEW_EXTENSIONS:
    try:
      return fp.read_text(encoding="utf-8", errors="replace")[:2000]
    except Exception:
      try:
        size = fp.stat().st_size
        return f"（文本类但读取失败）二进制文件，大小 {size} bytes"
      except Exception:
        return "（无法读取产物内容）"
  # 未知扩展名：先尝试按文本读，失败则按二进制
  try:
    return fp.read_text(encoding="utf-8", errors="replace")[:2000]
  except Exception:
    try:
      size = fp.stat().st_size
      return f"二进制文件，大小 {size} bytes"
    except Exception:
      return "（无法读取产物内容）"


def _json_or_list(v: Any) -> List[str]:
  if v is None:
    return []
  if isinstance(v, list):
    return [str(x) for x in v]
  if isinstance(v, str):
    try:
      obj = json.loads(v)
      if isinstance(obj, list):
        return [str(x) for x in obj]
    except Exception:
      return []
  return []


async def _process_pending_video_downloads(conn) -> None:
  """处理到期的待下载视频：查状态，若 completed 则下载到产物路径并跑验收。"""
  try:
    rows = list_pending_video_downloads_ready(conn)
  except Exception as e:
    logger.warning("list_pending_video_downloads_ready failed (table may not exist): %s", e)
    try:
      conn.rollback()
    except Exception:
      pass
    return
  if not rows:
    return
  try:
    from src.config.loader import load_yaml_config
    cfg = load_yaml_config("conf.yaml") or {}
    video_cfg = cfg.get("VIDEO_GENERATION") or {}
    api_key = video_cfg.get("api_key") or ""
  except Exception:
    api_key = ""
  import requests
  headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
  for row in rows:
    pending_id = row["id"]
    plan_id = row["plan_id"]
    task_id = row["task_id"]
    file_id = row["file_id"]
    output_path_abs = row["output_path_abs"]
    base_url = (row["base_url"] or "").rstrip("/")
    status_path = (row["status_path"] or "").replace("{file_id}", file_id)
    download_path = (row["download_path"] or "").replace("{file_id}", file_id)
    status_url = base_url + (status_path if status_path.startswith("/") else "/" + status_path)
    download_url = base_url + (download_path if download_path.startswith("/") else "/" + download_path)
    try:
      r = requests.get(status_url, headers=headers, timeout=30)
      r.raise_for_status()
      body = r.json()
      status = (body.get("status") or "").lower()
      if status == "completed":
        r2 = requests.get(download_url, headers=headers, timeout=120)
        r2.raise_for_status()
        Path(output_path_abs).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path_abs).write_bytes(r2.content)
        delete_pending_video_download(conn, pending_id)
        update_task_status(conn, task_id, status="succeeded", finished_at=datetime.now())
        task = get_task(conn, task_id)
        task_name = task.get("name") or "未命名任务"
        append_plan_log(
          conn,
          plan_id,
          level="info",
          event="task_succeeded",
          payload={
            "taskId": str(task_id),
            "output": output_path_abs,
            "title": f"任务完成：{task_name}",
            "icon": "success",
            "bullets": [f"延迟下载完成：{output_path_abs}"],
          },
          task_id=task_id,
        )
        content_preview = _content_preview_for_path(Path(output_path_abs))
        spec_content = read_spec(plan_id)
        accepted, reason = await coordinator.evaluate_task_output(
          task, output_path_abs, content_preview, (spec_content[:2000] if spec_content else "")
        )
        if not accepted:
          update_task_status(
            conn,
            task_id,
            status="failed",
            finished_at=datetime.now(),
            error=json.dumps({"rejected": True, "reason": reason}, ensure_ascii=False),
          )
          append_plan_log(
            conn,
            plan_id,
            level="warning",
            event="task_rejected",
            payload={
              "taskId": str(task_id),
              "reason": reason,
              "title": f"验收不通过：{task_name}",
              "icon": "error",
              "bullets": [reason],
            },
            task_id=task_id,
          )
          append_spec_milestone(plan_id, f"任务「{task_name}」验收不通过，原因：{reason}")
        else:
          append_plan_log(
            conn,
            plan_id,
            level="info",
            event="task_accepted",
            payload={
              "taskId": str(task_id),
              "reason": reason,
              "title": f"验收通过：{task_name}",
              "icon": "success",
              "bullets": [reason],
            },
            task_id=task_id,
          )
          append_spec_milestone(plan_id, f"任务「{task_name}」已验收通过")
        tasks = list_tasks(conn, plan_id)
        if tasks and all((t.get("status") == "succeeded") for t in tasks):
          update_plan(conn, plan_id, user_id=None, status="succeeded")
          append_plan_log(
            conn,
            plan_id,
            level="info",
            event="plan_succeeded",
            payload={
              "title": "计划已全部完成",
              "icon": "success",
              "bullets": [f"共 {len(tasks)} 个任务均已成功执行。"],
            },
          )
      elif status == "failed":
        delete_pending_video_download(conn, pending_id)
        err = body.get("error") or body.get("message") or "任务失败"
        update_task_status(
          conn,
          task_id,
          status="failed",
          finished_at=datetime.now(),
          error=json.dumps({"error": str(err)}, ensure_ascii=False),
        )
        append_plan_log(
          conn,
          plan_id,
          level="warning",
          event="task_failed",
          payload={
            "taskId": str(task_id),
            "title": "视频生成失败",
            "icon": "error",
            "bullets": [str(err)],
          },
          task_id=task_id,
        )
    except Exception as e:
      logger.warning("pending video download failed for %s: %s", file_id, e)
  return


class PlanScheduler:
  def __init__(self):
    self._scheduler: Optional[AsyncIOScheduler] = None
    self._lock = asyncio.Lock()
    self._executor = PlanTaskExecutor()

  async def start(self):
    if self._scheduler:
      return
    self._scheduler = AsyncIOScheduler()
    # 2 秒间隔：减少无任务时的 DB 轮询与日志噪音，有任务时仍能较快响应
    self._scheduler.add_job(self.tick, "interval", seconds=2, max_instances=1, coalesce=True)
    self._scheduler.start()
    logger.info("PlanScheduler started")

  async def stop(self):
    if not self._scheduler:
      return
    self._scheduler.shutdown(wait=False)
    self._scheduler = None
    logger.info("PlanScheduler stopped")

  async def tick(self):
    # 避免重入
    if self._lock.locked():
      return
    async with self._lock:
      conn = get_db_connection()
      try:
        # 0) 先处理到期的延迟视频下载（提交后 N 分钟再检查并下载到产物）
        await _process_pending_video_downloads(conn)
        # 无待处理/可执行任务时直接返回
        if not has_plan_work(conn):
          return
        # 1) 先把依赖满足的 pending 任务推进到 ready
        await self._promote_pending(conn)
        # 2) 领取一个 ready 任务（串行约束 + SKIP LOCKED）
        task = acquire_next_task(conn)
        if not task:
          return

        plan_id: UUID = task["plan_id"]
        task_id: UUID = task["id"]

        # 标记 plan running（若尚未）
        try:
          update_plan(conn, plan_id, user_id=None, status="running")
        except Exception:
          pass

        # 3) 执行任务
        try:
          await self._executor.execute(conn, task)
        except DeferredVideoDownload as e:
          update_task_status(
            conn,
            e.task_id,
            status="awaiting_download",
            finished_at=datetime.now(),
          )
          append_plan_log(
            conn,
            e.plan_id,
            level="info",
            event="video_deferred_download",
            payload={
              "taskId": str(e.task_id),
              "title": "视频已提交，将约 30 分钟后自动检查并下载",
              "icon": "info",
              "bullets": ["文生视频已提交成功，调度器将在配置的延迟时间后检查状态并下载到产物路径。"],
            },
            task_id=e.task_id,
          )
          return
        except Exception:
          # 失败后：plan 先不直接 fail，后续可加重试策略；MVP 直接 fail
          update_plan(conn, plan_id, user_id=None, status="failed")
          return

        # 4) 验收：系统唤起协调器，对刚完成的任务进行评估
        task_name = task.get("name") or "未命名任务"
        output_path = ""
        content_preview = "（无产物文件）"
        # 优先根据任务的 output_relpath 构造路径（不再依赖 artifact 表）
        exec_args = task.get("executor_args") or {}
        output_rel = exec_args.get("output_relpath") or ""
        if output_rel:
          fp = (Path(__file__).resolve().parents[3] / "outputs" / "plans" / str(plan_id) / str(output_rel))
          if fp.exists():
            output_path = str(fp)
            content_preview = _content_preview_for_path(fp)
        # 兼容旧记录：若未找到落盘文件，再尝试 artifact 表
        if not output_path:
          artifacts = list_artifacts(conn, plan_id)
          task_arts = [a for a in artifacts if str(a.get("task_id")) == str(task_id)]
          if task_arts:
            last_art = task_arts[-1]
            fp_str = last_art.get("file_path") or ""
            if fp_str:
              output_path = fp_str
              p = Path(fp_str)
              content_preview = _content_preview_for_path(p)
        spec_content = read_spec(plan_id)
        accepted, reason = await coordinator.evaluate_task_output(
          task, output_path, content_preview, (spec_content[:2000] if spec_content else "")
        )
        if not accepted:
          # 影响范围：找出依赖当前任务的下游任务，便于前端透出
          impact_scope: List[str] = []
          canceled_scope: List[str] = []
          cur_key = task.get("idempotency_key")
          if cur_key:
            try:
              downstream_tasks = list_tasks(conn, plan_id)
              for t in downstream_tasks:
                deps = _json_or_list(t.get("depends_on"))
                if cur_key in deps:
                  t_name = t.get("name") or t.get("idempotency_key") or str(t.get("id"))
                  impact_scope.append(t_name)
                  # 仅对未启动的任务做显式取消，避免“僵尸执行”
                  if t.get("status") in {"pending", "ready", "skipped"}:
                    update_task_status(
                      conn,
                      t.get("id"),
                      status="canceled",
                      finished_at=datetime.now(),
                      error=json.dumps(
                        {"canceled": True, "reason": f"上游任务「{task_name}」验收失败"}, ensure_ascii=False
                      ),
                    )
                    canceled_scope.append(t_name)
            except Exception:
              # 不阻断主流程，保持验收失败处理可继续
              pass

          update_task_status(
            conn, task_id, status="failed", finished_at=datetime.now(),
            error=json.dumps({"rejected": True, "reason": reason}, ensure_ascii=False),
          )
          append_plan_log(
            conn, plan_id, level="warning", event="task_rejected",
            payload={
              "taskId": str(task_id),
              "reason": reason,
              "title": f"验收不通过：{task_name}",
              "icon": "error",
              "impactScope": impact_scope,
              "bullets": [
                reason,
                ("影响范围：下游任务将无法启动：" + ", ".join(impact_scope)) if impact_scope else "影响范围：无下游任务依赖",
              ],
            },
            task_id=task_id,
          )
          if canceled_scope:
            append_plan_log(
              conn,
              plan_id,
              level="warning",
              event="task_canceled_bulk",
              payload={
                "title": "下游任务已取消",
                "icon": "error",
                "impactScope": canceled_scope,
                "bullets": [f"因上游任务「{task_name}」失败，已取消：{', '.join(canceled_scope)}"],
              },
            )
            append_spec_milestone(
              plan_id,
              f"因任务「{task_name}」验收失败，取消下游任务：{', '.join(canceled_scope)}",
            )
          append_spec_milestone(plan_id, f"任务「{task_name}」验收不通过，原因：{reason}")
          return
        append_plan_log(
          conn, plan_id, level="info", event="task_accepted",
          payload={
            "taskId": str(task_id),
            "reason": reason,
            "title": f"验收通过：{task_name}",
            "icon": "success",
            "bullets": [reason],
          },
          task_id=task_id,
        )
        append_spec_milestone(plan_id, f"任务「{task_name}」已验收通过")

        # 5) 若全部任务已成功，则 plan succeeded
        tasks = list_tasks(conn, plan_id)
        if tasks and all((t.get("status") == "succeeded") for t in tasks):
          update_plan(conn, plan_id, user_id=None, status="succeeded")
          append_plan_log(
            conn,
            plan_id,
            level="info",
            event="plan_succeeded",
            payload={
              "title": "计划已全部完成",
              "icon": "success",
              "bullets": [f"共 {len(tasks)} 个任务均已成功执行。"],
            },
          )
      finally:
        conn.close()

  async def _promote_pending(self, conn):
    """
    将依赖满足的 pending task 推进为 ready。
    依赖字段 depends_on 存的是 idempotency_key（例如 positioning.md）。
    """
    # 粗粒度：遍历所有 pending tasks（MVP 数据量很小）
    with conn.cursor() as cursor:
      cursor.execute(
        """
        SELECT id, plan_id, depends_on, status
        FROM agent_plan_tasks
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 200
        """
      )
      pending = cursor.fetchall() or []

    for row in pending:
      task_id = row["id"]
      plan_id = row["plan_id"]
      deps = _json_or_list(row.get("depends_on"))
      if not deps:
        update_task_status(conn, task_id, status="ready")
        continue

      # 检查依赖任务是否全部 succeeded（按 idempotency_key）
      ok = True
      with conn.cursor() as cursor:
        for key in deps:
          cursor.execute(
            """
            SELECT status FROM agent_plan_tasks
            WHERE plan_id = %s AND idempotency_key = %s
            LIMIT 1
            """,
            (plan_id, key),
          )
          dep = cursor.fetchone()
          if not dep or dep.get("status") != "succeeded":
            ok = False
            break
      if ok:
        update_task_status(conn, task_id, status="ready")


_SCHEDULER: Optional[PlanScheduler] = None


def get_plan_scheduler() -> PlanScheduler:
  global _SCHEDULER
  if _SCHEDULER is None:
    _SCHEDULER = PlanScheduler()
  return _SCHEDULER

