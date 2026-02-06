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
  get_db_connection,
  has_plan_work,
  list_artifacts,
  list_tasks,
  update_plan,
  update_task_status,
)
from src.server.plan.executor import PlanTaskExecutor
from src.server.plan.spec import append_spec_milestone, read_spec

logger = logging.getLogger(__name__)


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


class PlanScheduler:
  def __init__(self):
    self._scheduler: Optional[AsyncIOScheduler] = None
    self._lock = asyncio.Lock()
    self._executor = PlanTaskExecutor()

  async def start(self):
    if self._scheduler:
      return
    self._scheduler = AsyncIOScheduler()
    self._scheduler.add_job(self.tick, "interval", seconds=1, max_instances=1, coalesce=True)
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
        # 无待处理/可执行任务时直接返回，避免无意义的 DB 轮询与日志
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
            try:
              content_preview = fp.read_text(encoding="utf-8", errors="replace")[:2000]
            except Exception:
              content_preview = "（无法读取产物内容）"
        # 兼容旧记录：若未找到落盘文件，再尝试 artifact 表
        if not output_path:
          artifacts = list_artifacts(conn, plan_id)
          task_arts = [a for a in artifacts if str(a.get("task_id")) == str(task_id)]
          if task_arts:
            last_art = task_arts[-1]
            fp = last_art.get("file_path") or ""
            if fp:
              output_path = fp
              try:
                p = Path(fp)
                if p.exists():
                  content_preview = p.read_text(encoding="utf-8", errors="replace")[:2000]
              except Exception:
                content_preview = "（无法读取产物内容）"
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

