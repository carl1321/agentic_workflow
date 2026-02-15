# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from src.config.loader import get_str_env

logger = logging.getLogger(__name__)


def get_db_connection() -> psycopg.Connection:
  """获取数据库连接（复用 conf.yaml/ENV 约定）。"""
  db_url = (
    get_str_env("DATABASE_URL")
    or get_str_env("SQLALCHEMY_DATABASE_URI")
    or get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "postgresql://localhost:5432/agenticworkflow")
  )
  if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgres://", 1)
  return psycopg.connect(db_url, row_factory=dict_row)


def _as_uuid(value: Any) -> Optional[UUID]:
  if value is None:
    return None
  return UUID(str(value))


def create_plan(
  conn: psycopg.Connection,
  user_id: Optional[UUID],
  title: Optional[str],
  raw_goal: str,
) -> UUID:
  plan_id = uuid4()
  with conn.cursor() as cursor:
    cursor.execute(
      """
      INSERT INTO agent_plans (id, user_id, title, status, raw_goal, clarify, ora_spec, spec_version)
      VALUES (%s, %s, %s, 'draft', %s, %s, NULL, 1)
      """,
      (
        plan_id,
        user_id,
        title,
        raw_goal,
        json.dumps({"round": 0, "qa": []}, ensure_ascii=False),
      ),
    )
  conn.commit()
  return plan_id


def list_plans(
  conn: psycopg.Connection,
  user_id: Optional[UUID],
  limit: int = 50,
  offset: int = 0,
) -> List[Dict[str, Any]]:
  with conn.cursor() as cursor:
    if user_id is None:
      cursor.execute(
        """
        SELECT id, title, status, created_at, updated_at
        FROM agent_plans
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
      )
    else:
      cursor.execute(
        """
        SELECT id, title, status, created_at, updated_at
        FROM agent_plans
        WHERE user_id = %s
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, limit, offset),
      )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def get_plan(
  conn: psycopg.Connection,
  plan_id: UUID,
  user_id: Optional[UUID],
) -> Optional[Dict[str, Any]]:
  with conn.cursor() as cursor:
    if user_id is None:
      cursor.execute("SELECT * FROM agent_plans WHERE id = %s", (plan_id,))
    else:
      cursor.execute("SELECT * FROM agent_plans WHERE id = %s AND user_id = %s", (plan_id, user_id))
    row = cursor.fetchone()
    return dict(row) if row else None


def delete_plan(
  conn: psycopg.Connection,
  plan_id: UUID,
  user_id: Optional[UUID],
) -> bool:
  """删除计划（关联的 tasks/artifacts/logs/messages 由外键 ON DELETE CASCADE 自动删除）。"""
  with conn.cursor() as cursor:
    if user_id is None:
      cursor.execute("DELETE FROM agent_plans WHERE id = %s", (plan_id,))
    else:
      cursor.execute("DELETE FROM agent_plans WHERE id = %s AND user_id = %s", (plan_id, user_id))
    deleted = cursor.rowcount > 0
  conn.commit()
  return deleted


def update_plan(
  conn: psycopg.Connection,
  plan_id: UUID,
  user_id: Optional[UUID],
  *,
  status: Optional[str] = None,
  title: Optional[str] = None,
  raw_goal: Optional[str] = None,
  ora_spec: Optional[Dict[str, Any]] = None,
  clarify: Optional[Dict[str, Any]] = None,
  spec_version_inc: bool = False,
) -> bool:
  updates: List[str] = ["updated_at = NOW()"]
  params: List[Any] = []

  if status is not None:
    updates.append("status = %s")
    params.append(status)
  if title is not None:
    updates.append("title = %s")
    params.append(title)
  if raw_goal is not None:
    updates.append("raw_goal = %s")
    params.append(raw_goal)
  if ora_spec is not None:
    updates.append("ora_spec = %s")
    params.append(json.dumps(ora_spec, ensure_ascii=False))
  if clarify is not None:
    updates.append("clarify = %s")
    params.append(json.dumps(clarify, ensure_ascii=False))
  if spec_version_inc:
    updates.append("spec_version = spec_version + 1")

  if len(updates) == 1:
    return True

  params.append(plan_id)
  if user_id is None:
    where = "WHERE id = %s"
  else:
    where = "WHERE id = %s AND user_id = %s"
    params.append(user_id)

  with conn.cursor() as cursor:
    cursor.execute(f"UPDATE agent_plans SET {', '.join(updates)} {where}", tuple(params))
    updated = cursor.rowcount > 0
  conn.commit()
  return updated


def create_tasks(
  conn: psycopg.Connection,
  plan_id: UUID,
  tasks: List[Dict[str, Any]],
) -> int:
  if not tasks:
    return 0
  with conn.cursor() as cursor:
    for t in tasks:
      task_id = _as_uuid(t.get("id")) or uuid4()
      cursor.execute(
        """
        INSERT INTO agent_plan_tasks (
          id, plan_id, name, description, acceptance_criteria,
          status, depends_on, scheduled_at,
          executor_type, executor_args, idempotency_key,
          max_retries
        )
        VALUES (%s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s)
        """,
        (
          task_id,
          plan_id,
          t.get("name"),
          t.get("description"),
          t.get("acceptance_criteria"),
          t.get("status", "pending"),
          json.dumps(t.get("depends_on") or [], ensure_ascii=False),
          t.get("scheduled_at"),
          t.get("executor_type"),
          json.dumps(t.get("executor_args") or {}, ensure_ascii=False),
          t.get("idempotency_key"),
          int(t.get("max_retries") or 0),
        ),
      )
  conn.commit()
  return len(tasks)


def list_tasks(conn: psycopg.Connection, plan_id: UUID) -> List[Dict[str, Any]]:
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_tasks
      WHERE plan_id = %s
      ORDER BY created_at ASC
      """,
      (plan_id,),
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def list_artifacts(conn: psycopg.Connection, plan_id: UUID) -> List[Dict[str, Any]]:
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_artifacts
      WHERE plan_id = %s
      ORDER BY created_at ASC
      """,
      (plan_id,),
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def get_artifact(conn: psycopg.Connection, plan_id: UUID, artifact_id: UUID) -> Optional[Dict[str, Any]]:
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_artifacts
      WHERE plan_id = %s AND id = %s
      LIMIT 1
      """,
      (plan_id, artifact_id),
    )
    row = cursor.fetchone()
  return dict(row) if row else None


def list_logs(
  conn: psycopg.Connection,
  plan_id: UUID,
  *,
  limit: int = 200,
  offset: int = 0,
) -> List[Dict[str, Any]]:
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_logs
      WHERE plan_id = %s
      ORDER BY created_at ASC
      LIMIT %s OFFSET %s
      """,
      (plan_id, limit, offset),
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def list_logs_since(
  conn: psycopg.Connection,
  plan_id: UUID,
  *,
  since: datetime,
  limit: int = 500,
) -> List[Dict[str, Any]]:
  """
  增量拉取日志：created_at > since。
  """
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_logs
      WHERE plan_id = %s AND created_at > %s
      ORDER BY created_at ASC
      LIMIT %s
      """,
      (plan_id, since, limit),
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def has_plan_work(conn: psycopg.Connection) -> bool:
  """是否存在待推进或待执行的任务（pending/ready），用于调度器在无任务时快速返回。"""
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT 1 FROM agent_plan_tasks
      WHERE status IN ('pending', 'ready')
      LIMIT 1
      """
    )
    return cursor.fetchone() is not None


def has_acquirable_work(conn: psycopg.Connection) -> bool:
  """
  是否存在本轮可执行的工作：到期的长耗时任务下载，或已到期的 ready 任务。
  用于 tick 早退：仅有“等待中”任务（如 awaiting_download、scheduled_at 在未来）时直接返回，不执行。
  """
  try:
    rows = list_pending_video_downloads_ready(conn)
    if rows:
      return True
  except Exception:
    pass
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT 1 FROM agent_plan_tasks
      WHERE status = 'ready' AND (scheduled_at IS NULL OR scheduled_at <= NOW())
      LIMIT 1
      """
    )
    return cursor.fetchone() is not None


def get_task(conn: psycopg.Connection, task_id: UUID) -> Optional[Dict[str, Any]]:
  with conn.cursor() as cursor:
    cursor.execute("SELECT * FROM agent_plan_tasks WHERE id = %s LIMIT 1", (task_id,))
    row = cursor.fetchone()
  return dict(row) if row else None


def get_task_by_idempotency_key(
  conn: psycopg.Connection,
  plan_id: UUID,
  idempotency_key: str,
) -> Optional[Dict[str, Any]]:
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_tasks
      WHERE plan_id = %s AND idempotency_key = %s
      LIMIT 1
      """,
      (plan_id, idempotency_key),
    )
    row = cursor.fetchone()
  return dict(row) if row else None


# 常见产出后缀，用于「depends_on 写任务名（如 分镜可视化）时」匹配 idempotency_key（如 分镜可视化.pptx）
_DEP_KEY_SUFFIXES = (".pptx", ".ppt", ".md", ".json", ".mp4", ".srt", ".txt")


def get_succeeded_dep_task(
  conn: psycopg.Connection,
  plan_id: UUID,
  key: str,
) -> Optional[Dict[str, Any]]:
  """
  按依赖 key 查找已成功的任务。
  - 先精确匹配 idempotency_key；
  - 若无则尝试 key + 常见后缀（如 分镜可视化 -> 分镜可视化.pptx）；
  - 若 key 本身带后缀（如 分镜可视化.ppt）而库里是 .pptx，则剥掉 key 的后缀再试各后缀（分镜可视化.ppt -> 分镜可视化 -> 分镜可视化.pptx）。
  """
  key = (key or "").strip()
  if not key:
    return None
  t = get_task_by_idempotency_key(conn, plan_id, key)
  if t and (t.get("status") or "").lower() == "succeeded":
    return t
  # key 无后缀或加后缀
  for ext in _DEP_KEY_SUFFIXES:
    if key.endswith(ext):
      continue
    t = get_task_by_idempotency_key(conn, plan_id, key + ext)
    if t and (t.get("status") or "").lower() == "succeeded":
      return t
  # key 已带后缀但和库里不一致（如 depends_on 写 分镜可视化.ppt，库里是 分镜可视化.pptx）
  for ext in _DEP_KEY_SUFFIXES:
    if not key.endswith(ext):
      continue
    base = key[: -len(ext)]
    if not base:
      continue
    for other in _DEP_KEY_SUFFIXES:
      if other == ext:
        continue
      t = get_task_by_idempotency_key(conn, plan_id, base + other)
      if t and (t.get("status") or "").lower() == "succeeded":
        return t
  return None


def update_task_status(
  conn: psycopg.Connection,
  task_id: UUID,
  *,
  status: str,
  started_at: Optional[datetime] = None,
  finished_at: Optional[datetime] = None,
  error: Optional[Dict[str, Any]] = None,
  scheduled_at: Optional[datetime] = None,
) -> bool:
  updates: List[str] = ["status = %s", "updated_at = NOW()"]
  params: List[Any] = [status]
  if started_at is not None:
    updates.append("started_at = %s")
    params.append(started_at)
  if finished_at is not None:
    updates.append("finished_at = %s")
    params.append(finished_at)
  if error is not None:
    updates.append("error = %s")
    params.append(json.dumps(error, ensure_ascii=False))
  if scheduled_at is not None:
    updates.append("scheduled_at = %s")
    params.append(scheduled_at)
  params.append(task_id)
  with conn.cursor() as cursor:
    cursor.execute(f"UPDATE agent_plan_tasks SET {', '.join(updates)} WHERE id = %s", tuple(params))
    ok = cursor.rowcount > 0
  conn.commit()
  return ok


def set_task_scheduled_at(conn: psycopg.Connection, task_id: UUID, scheduled_at: Optional[datetime]) -> bool:
  """仅更新任务的 scheduled_at，用于「依赖视频任务的下游至少延迟 N 分钟执行」。"""
  with conn.cursor() as cursor:
    cursor.execute(
      "UPDATE agent_plan_tasks SET scheduled_at = %s, updated_at = NOW() WHERE id = %s",
      (scheduled_at, task_id),
    )
    ok = cursor.rowcount > 0
  conn.commit()
  return ok


def increment_task_attempt(conn: psycopg.Connection, task_id: UUID) -> None:
  with conn.cursor() as cursor:
    cursor.execute(
      "UPDATE agent_plan_tasks SET attempt = attempt + 1, updated_at = NOW() WHERE id = %s",
      (task_id,),
    )
  conn.commit()


def reset_plan_tasks_for_restart(
  conn: psycopg.Connection,
  plan_id: UUID,
  mode: str = "uncompleted_only",
) -> int:
  """
  重启计划时重置任务状态：将未完成/失败的任务设为 pending，便于调度器重新推进为 ready 并执行。
  - uncompleted_only: 仅重置 failed、canceled、running；succeeded、pending、ready、awaiting_download 不变。
  - all: 将所有非 succeeded 的任务重置为 pending（全量重跑）。
  返回被重置的任务数量。
  """
  with conn.cursor() as cursor:
    if mode == "all":
      cursor.execute(
        """
        UPDATE agent_plan_tasks
        SET status = 'pending', finished_at = NULL, error = NULL, updated_at = NOW()
        WHERE plan_id = %s AND status != 'succeeded'
        """,
        (plan_id,),
      )
    else:
      cursor.execute(
        """
        UPDATE agent_plan_tasks
        SET status = 'pending', finished_at = NULL, error = NULL, updated_at = NOW()
        WHERE plan_id = %s AND status IN ('failed', 'canceled', 'running')
        """,
        (plan_id,),
      )
    count = cursor.rowcount
  conn.commit()
  return count


def reset_plan_tasks_by_ids(
  conn: psycopg.Connection,
  plan_id: UUID,
  task_ids: List[UUID],
  include_downstream: bool = True,
) -> int:
  """
  将指定任务（及可选地其下游依赖）重置为 pending。
  当大模型判断用户要求「重跑某类任务」时，由 routes 传入匹配的 task_ids，此处负责重置。
  include_downstream=True 时，会递归把依赖这些任务产出的下游任务一并重置。
  返回被重置的任务数量。
  """
  if not task_ids:
    return 0
  tasks = list_tasks(conn, plan_id)
  id_to_key = {t.get("id"): str(t.get("idempotency_key") or "") for t in tasks if t.get("id")}
  keys_of_selected = {id_to_key.get(tid) for tid in task_ids if id_to_key.get(tid)}
  keys_of_selected.discard("")
  ids_to_reset = set(task_ids)
  if include_downstream:
    while True:
      added = False
      for t in tasks:
        tid = t.get("id")
        if tid in ids_to_reset:
          continue
        deps = t.get("depends_on")
        if deps is None:
          continue
        if isinstance(deps, str):
          try:
            deps = json.loads(deps) if (deps or "").strip().startswith("[") else []
          except Exception:
            deps = []
        for d in (deps or []):
          if str(d).strip() in keys_of_selected:
            ids_to_reset.add(tid)
            keys_of_selected.add(str(t.get("idempotency_key") or ""))
            added = True
            break
      if not added:
        break
  ids_list = list(ids_to_reset)
  with conn.cursor() as cursor:
    cursor.execute(
      """
      UPDATE agent_plan_tasks
      SET status = 'pending', finished_at = NULL, error = NULL, updated_at = NOW()
      WHERE plan_id = %s AND id = ANY(%s)
      """,
      (plan_id, ids_list),
    )
    count = cursor.rowcount
  conn.commit()
  return count


def create_artifact(
  conn: psycopg.Connection,
  plan_id: UUID,
  task_id: UUID,
  *,
  type: str,
  file_path: str,
  meta: Optional[Dict[str, Any]] = None,
) -> UUID:
  artifact_id = uuid4()
  with conn.cursor() as cursor:
    cursor.execute(
      """
      INSERT INTO agent_plan_artifacts (id, plan_id, task_id, type, file_path, meta, created_at)
      VALUES (%s, %s, %s, %s, %s, %s, NOW())
      """,
      (
        artifact_id,
        plan_id,
        task_id,
        type,
        file_path,
        json.dumps(meta or {}, ensure_ascii=False),
      ),
    )
  conn.commit()
  return artifact_id


def acquire_next_task(conn: psycopg.Connection) -> Optional[Dict[str, Any]]:
  """
  获取一个可执行的 task，并使用 SKIP LOCKED 避免并发冲突。
  约束：
  - 仅领取 status='ready' 且 scheduled_at 已到期（或为空）的任务
  - 同一 plan 内仅当存在 status='running' 时阻塞该 plan 的其他任务；awaiting_download 不阻塞，故只有互相依赖的任务会受“等待视频”影响，其他任务可照常被领取
  """
  with conn.transaction():
    with conn.cursor() as cursor:
      cursor.execute(
        """
        SELECT t.*
        FROM agent_plan_tasks t
        WHERE t.status = 'ready'
          AND (t.scheduled_at IS NULL OR t.scheduled_at <= NOW())
          AND NOT EXISTS (
            SELECT 1 FROM agent_plan_tasks r
            WHERE r.plan_id = t.plan_id AND r.status = 'running'
          )
        ORDER BY t.created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """
      )
      row = cursor.fetchone()
      if not row:
        return None
      task = dict(row)
      cursor.execute(
        """
        UPDATE agent_plan_tasks
        SET status = 'running', started_at = COALESCE(started_at, NOW()), attempt = attempt + 1, updated_at = NOW()
        WHERE id = %s
        """,
        (task["id"],),
      )
      return task


def append_plan_log(
  conn: psycopg.Connection,
  plan_id: UUID,
  *,
  level: str,
  event: str,
  payload: Optional[Dict[str, Any]] = None,
  task_id: Optional[UUID] = None,
) -> UUID:
  log_id = uuid4()
  try:
    with conn.cursor() as cursor:
      cursor.execute(
        """
        INSERT INTO agent_plan_logs (id, plan_id, task_id, level, event, payload, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """,
        (
          log_id,
          plan_id,
          task_id,
          level,
          event,
          json.dumps(payload or {}, ensure_ascii=False),
        ),
      )
    conn.commit()
  except Exception as e:
    # MVP：日志写入失败不应阻断主流程（避免前端“无响应”）
    try:
      conn.rollback()
    except Exception:
      pass
    logger.warning("append_plan_log failed: plan=%s event=%s err=%s", plan_id, event, e)
  return log_id


def insert_pending_video_download(
  conn: psycopg.Connection,
  plan_id: UUID,
  task_id: UUID,
  *,
  file_id: str,
  output_path_abs: str,
  base_url: str,
  status_path: str,
  download_path: str,
  delay_minutes: int = 30,
) -> None:
  """记录待延迟下载的视频任务（文生视频 202 提交后由调度器在 delay_minutes 后检查并下载）。"""
  with conn.cursor() as cursor:
    cursor.execute(
      """
      INSERT INTO agent_plan_pending_video_downloads
        (plan_id, task_id, file_id, output_path_abs, base_url, status_path, download_path, delay_minutes)
      VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
      """,
      (plan_id, task_id, file_id, output_path_abs, base_url, status_path, download_path, delay_minutes),
    )
  conn.commit()


def list_pending_video_downloads_ready(conn: psycopg.Connection) -> List[Dict[str, Any]]:
  """列出已到期的待下载视频（submitted_at + delay_minutes 分钟 <= now）。"""
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT id, plan_id, task_id, file_id, output_path_abs, base_url, status_path, download_path,
             submitted_at, delay_minutes
      FROM agent_plan_pending_video_downloads
      WHERE submitted_at + (delay_minutes || ' minutes')::interval <= NOW()
      ORDER BY submitted_at ASC
      """
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def delete_pending_video_download(conn: psycopg.Connection, pending_id: UUID) -> None:
  with conn.cursor() as cursor:
    cursor.execute("DELETE FROM agent_plan_pending_video_downloads WHERE id = %s", (pending_id,))
  conn.commit()


def ensure_plan_message_tables(conn: psycopg.Connection) -> None:
  """
  确保 plan messages 表存在（MVP：按需创建，避免首次未执行 init 脚本导致接口不可用）。
  """
  with conn.cursor() as cursor:
    cursor.execute(
      """
      CREATE TABLE IF NOT EXISTS agent_plan_messages (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          plan_id UUID NOT NULL,
          role VARCHAR(20) NOT NULL,
          content TEXT NOT NULL,
          meta JSONB,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
          FOREIGN KEY (plan_id) REFERENCES agent_plans(id) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS idx_agent_plan_messages_plan_id ON agent_plan_messages(plan_id);
      CREATE INDEX IF NOT EXISTS idx_agent_plan_messages_created_at ON agent_plan_messages(created_at);
      """
    )
  conn.commit()


def append_plan_message(
  conn: psycopg.Connection,
  plan_id: UUID,
  *,
  role: str,
  content: str,
  meta: Optional[Dict[str, Any]] = None,
) -> UUID:
  ensure_plan_message_tables(conn)
  msg_id = uuid4()
  with conn.cursor() as cursor:
    cursor.execute(
      """
      INSERT INTO agent_plan_messages (id, plan_id, role, content, meta, created_at)
      VALUES (%s, %s, %s, %s, %s, NOW())
      """,
      (msg_id, plan_id, role, content, json.dumps(meta or {}, ensure_ascii=False)),
    )
  conn.commit()
  return msg_id


def list_plan_messages(
  conn: psycopg.Connection,
  plan_id: UUID,
  *,
  limit: int = 200,
  offset: int = 0,
) -> List[Dict[str, Any]]:
  ensure_plan_message_tables(conn)
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_messages
      WHERE plan_id = %s
      ORDER BY created_at ASC
      LIMIT %s OFFSET %s
      """,
      (plan_id, limit, offset),
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]


def list_plan_messages_since(
  conn: psycopg.Connection,
  plan_id: UUID,
  *,
  since: datetime,
  limit: int = 500,
) -> List[Dict[str, Any]]:
  """
  增量拉取消息：created_at > since。
  """
  ensure_plan_message_tables(conn)
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT *
      FROM agent_plan_messages
      WHERE plan_id = %s AND created_at > %s
      ORDER BY created_at ASC
      LIMIT %s
      """,
      (plan_id, since, limit),
    )
    rows = cursor.fetchall() or []
  return [dict(r) for r in rows]

