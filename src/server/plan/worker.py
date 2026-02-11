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
import os
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
# 注意：PPT 产物为二进制（zip container），必须按二进制预览，否则验收模型可能误判“内容不像 PPT”
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".wav", ".mp3", ".webm", ".avi", ".mov", ".pptx", ".ppt"}

def _required_tool_for_output(output_relpath: str) -> Optional[str]:
  """根据产出后缀推断必须调用的工具名（用于根因提示/精确检索关键词）。"""
  ext = (Path(output_relpath).suffix or "").lower()
  return {
    ".mp4": "video_generation_tool",
    ".png": "image_generation_tool",
    ".jpg": "image_generation_tool",
    ".jpeg": "image_generation_tool",
    ".wav": "tts_tool",
    ".mp3": "tts_tool",
    ".pptx": "ppt_generate_tool",
    ".ppt": "ppt_generate_tool",  # 历史/模型误输出
  }.get(ext)


def _root_cause_hint(
  *,
  reason: str,
  output_rel: str,
  output_path: str,
  content_preview: str,
) -> Optional[str]:
  """对常见验收失败做本地归因提示，能判断就不做网页搜索。"""
  r = (reason or "").strip()
  out = (output_rel or "").strip()
  ext = (Path(out).suffix or "").lower()
  tool = _required_tool_for_output(out) or "对应工具"

  # 1) 产物文件缺失/未落盘
  if ("产物文件缺失" in r) or ("未在指定路径生成文件" in r) or ("未生成文件" in r):
    bullets: List[str] = []
    if ext in {".ppt", ".pptx"}:
      bullets.append("如果任务写的是 .ppt（旧后缀），而工具只能生成 .pptx，会导致“期望路径/文件名不一致”从而验收失败；建议统一使用 .pptx。")
    bullets.append(f"检查日志里是否出现过「工具调用：{tool}」且 status=ok；没有的话通常是模型没调用到工具，或该任务没绑定到包含该工具的执行器。")
    bullets.append("检查 output_relpath 是否正确（不要带错目录/后缀），验收只认 `outputs/plans/{plan_id}/{output_relpath}`。")
    bullets.append("如果你刚重启过后端/模型超时，可能出现流程中断；点一次“继续/重试”触发自愈重跑。")
    return "根因定位（本地判断）：产物未落盘到指定路径。\n- " + "\n- ".join(bullets[:4])

  # 2) 伪二进制/内容不符合
  if ("并非二进制" in r) or ("内容明显不符" in r):
    return (
      "根因定位（本地判断）：产物疑似被当作文本写入或生成了“伪文件”。\n"
      f"- 该类型（{ext or '未知后缀'}）必须由 `{tool}` 生成真实二进制文件，不能用 create_file_tool 写文本冒充。\n"
      "- 请确认工具确实被调用，且工具返回的输出路径与验收路径一致。"
    )

  # 3) 模型未调用工具
  if ("仍未发起工具调用" in r) or ("必须调用" in r and "并落盘" in r):
    return (
      "根因定位（本地判断）：模型没有发起必要的工具调用。\n"
      f"- 该任务产物为 `{ext}`，必须调用 `{tool}` 并落盘到指定路径。\n"
      "- 请确认当前所用模型支持 function calling（工具调用），或切换到支持工具调用的模型后重试。"
    )

  # 4) 配置/依赖问题
  s = (r + "\n" + (content_preview or "")).lower()
  if ("pip install" in s) or ("未配置" in r) or ("is not set" in s) or ("not installed" in s):
    return "根因定位（本地判断）：工具依赖或配置缺失。请按日志提示安装依赖/配置环境变量后再重试。"

  return None


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
            error={"rejected": True, "reason": reason},
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
          error={"error": str(err)},
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

        # 超过最大重试次数则不再执行，标记失败并提示用户
        attempt = int(task.get("attempt") or 0)
        max_retries = int(task.get("max_retries") or 1)
        if attempt > max_retries + 1:
          task_name = task.get("name") or "未命名任务"
          update_task_status(
            conn,
            task_id,
            status="failed",
            finished_at=datetime.now(),
            error={"error": "超过最大重试次数，请检查失败原因或手动处理", "attempt": attempt, "max_retries": max_retries},
          )
          append_plan_log(
            conn, plan_id, level="warning", event="task_failed",
            payload={
              "taskId": str(task_id),
              "title": f"任务跳过（超过重试次数）：{task_name}",
              "icon": "error",
              "bullets": [f"已执行 {attempt} 次，超过最大重试次数 {max_retries}，请查看日志或重新启动计划后重试。"],
            },
            task_id=task_id,
          )
          return

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
                      error={"canceled": True, "reason": f"上游任务「{task_name}」验收失败"},
                    )
                    canceled_scope.append(t_name)
            except Exception:
              # 不阻断主流程，保持验收失败处理可继续
              pass

          update_task_status(
            conn, task_id, status="failed", finished_at=datetime.now(),
            error={"rejected": True, "reason": reason},
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
          # 验收失败后：优先给出“本地根因提示”，能解释就不做网页搜索（避免搜到无关页面）
          try:
            hint = _root_cause_hint(
              reason=reason or "",
              output_rel=output_rel or "",
              output_path=output_path or "",
              content_preview=content_preview or "",
            )
            if hint:
              append_plan_log(
                conn,
                plan_id,
                level="warning",
                event="root_cause_hint",
                payload={
                  "taskId": str(task_id),
                  "title": "根因提示（无需网页搜索）",
                  "icon": "info",
                  "bullets": [x for x in hint.split("\n") if x.strip()][:8],
                },
                task_id=task_id,
              )
            else:
              # 仅在显式开启时才做网页搜索（默认关闭）
              if str(os.getenv("PLAN_WEB_SEARCH_ON_REJECTED", "")).lower() in ("1", "true", "yes", "on"):
                from src.tools.search import get_general_web_search_tool
                tool = _required_tool_for_output(output_rel or "") or ""
                ext = (Path(output_rel or "").suffix or "").lower()
                reason_short = (reason or "").split("\n")[0].strip()[:120]
                query = " ".join([x for x in [tool, ext, "验收不通过", reason_short] if x]).strip() or "任务验收不通过 原因定位"
                ws = get_general_web_search_tool(5)
                if hasattr(ws, "ainvoke"):
                  res = await ws.ainvoke({"query": query})
                else:
                  res = await asyncio.get_event_loop().run_in_executor(None, lambda: ws.invoke({"query": query}))
                search_str = str(res)[:2000]
                append_plan_log(
                  conn,
                  plan_id,
                  level="info",
                  event="failure_recovery_search",
                  payload={
                    "taskId": str(task_id),
                    "searchQuery": query,
                    "resultPreview": search_str[:500],
                    "title": "已根据验收失败原因搜索解决方案",
                    "icon": "info",
                    "bullets": [f"关键词：{query}", search_str.split("\n")[0][:200] if search_str else ""],
                  },
                  task_id=task_id,
                )
          except Exception as e:
            logger.warning("Acceptance root_cause_hint/search failed: %s", e)
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

