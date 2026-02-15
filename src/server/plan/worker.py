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
from datetime import datetime, timedelta
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
  get_succeeded_dep_task,
  get_task,
  get_task_by_idempotency_key,
  has_acquirable_work,
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

# 超过该时长的 running 任务视为「僵死」，做兜底推进（有产出则验收，无则标失败）
STALE_RUNNING_MINUTES = 10

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


async def _process_pending_video_downloads(conn) -> int:
  """处理到期的待下载视频：查状态，若 completed 则下载到产物路径并跑验收。返回处理到的条数。"""
  try:
    rows = list_pending_video_downloads_ready(conn)
  except Exception as e:
    logger.warning("list_pending_video_downloads_ready failed (table may not exist): %s", e)
    try:
      conn.rollback()
    except Exception:
      pass
    return 0
  if not rows:
    return 0
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
  return len(rows)


async def _recover_stale_running_tasks(conn) -> int:
  """
  对长时间处于 running 的任务做兜底推进：若产出文件已存在则验收并更新状态，否则标为失败便于重试。
  仅处理 started_at 早于 STALE_RUNNING_MINUTES 分钟的任务，避免误伤正在执行的任务。
  """
  interval_minutes = max(1, STALE_RUNNING_MINUTES)
  with conn.cursor() as cursor:
    cursor.execute(
      """
      SELECT id, plan_id, name, executor_args
      FROM agent_plan_tasks
      WHERE status = 'running'
        AND started_at IS NOT NULL
        AND started_at < NOW() - (%s * INTERVAL '1 minute')
      LIMIT 50
      """,
      (interval_minutes,),
    )
    rows = cursor.fetchall() or []
  if not rows:
    return 0
  root = Path(__file__).resolve().parents[3]
  n_recovered = 0
  for row in rows:
    task_id = row["id"]
    plan_id = row["plan_id"]
    task_name = row.get("name") or "未命名任务"
    exec_args = row.get("executor_args")
    if isinstance(exec_args, str):
      try:
        exec_args = json.loads(exec_args) if (exec_args or "").strip().startswith("{") else {}
      except Exception:
        exec_args = {}
    if not isinstance(exec_args, dict):
      exec_args = {}
    output_rel = exec_args.get("output_relpath") or ""
    output_path = ""
    if output_rel:
      fp = root / "outputs" / "plans" / str(plan_id) / str(output_rel)
      if fp.exists() and fp.is_file():
        output_path = str(fp)
    if output_path:
      task = get_task(conn, task_id)
      if not task or (task.get("status") or "") != "running":
        continue
      content_preview = _content_preview_for_path(Path(output_path))
      spec_content = read_spec(plan_id)
      accepted, reason = await coordinator.evaluate_task_output(
        task, output_path, content_preview, (spec_content[:2000] if spec_content else "")
      )
      if accepted:
        update_task_status(conn, task_id, status="succeeded", finished_at=datetime.now())
        append_plan_log(
          conn,
          plan_id,
          level="info",
          event="task_accepted",
          payload={
            "taskId": str(task_id),
            "reason": reason or "兜底推进：长时间 running 且产出已存在，验收通过",
            "title": f"验收通过：{task_name}（兜底推进）",
            "icon": "success",
            "bullets": [reason or "产出文件存在且符合要求"],
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
            payload={"title": "计划已全部完成", "icon": "success", "bullets": [f"共 {len(tasks)} 个任务均已成功执行。"]},
          )
      else:
        update_task_status(
          conn,
          task_id,
          status="failed",
          finished_at=datetime.now(),
          error={"rejected": True, "reason": reason, "recovered": True},
        )
        append_plan_log(
          conn,
          plan_id,
          level="warning",
          event="task_rejected",
          payload={
            "taskId": str(task_id),
            "reason": reason,
            "title": f"验收不通过：{task_name}（兜底推进）",
            "icon": "error",
            "bullets": [reason or "产物不符合要求"],
          },
          task_id=task_id,
        )
      n_recovered += 1
      logger.info("兜底推进 running 任务: plan=%s task=%s %s", plan_id, task_name, "验收通过" if accepted else "验收不通过")
    else:
      update_task_status(
        conn,
        task_id,
        status="failed",
        finished_at=datetime.now(),
        error={
          "error": "任务长时间处于 running 且无产出文件，视为执行器未正常返回，已置为失败可重试",
          "recovered": True,
        },
      )
      append_plan_log(
        conn,
        plan_id,
        level="warning",
        event="task_failed",
        payload={
          "taskId": str(task_id),
          "title": f"任务已置为失败（兜底）：{task_name}",
          "icon": "error",
          "bullets": ["长时间 running 且未找到产出文件，可能执行器中断；可重试该计划或该任务。"],
        },
        task_id=task_id,
      )
      n_recovered += 1
      logger.info("兜底推进 running 任务(无产出): plan=%s task=%s -> failed", plan_id, task_name)
  return n_recovered


class PlanScheduler:
  def __init__(self):
    self._scheduler: Optional[AsyncIOScheduler] = None
    self._lock = asyncio.Lock()
    self._executor = PlanTaskExecutor()

  async def start(self):
    if self._scheduler:
      return
    self._scheduler = AsyncIOScheduler()
    # 轮询 60 秒一次，保证等待态（如视频）后也能在 1 分钟内继续推进；有用户交互时 routes 会 trigger_tick 立即响应
    self._scheduler.add_job(self.tick, "interval", seconds=60, max_instances=1, coalesce=True)
    self._scheduler.start()
    logger.info("PlanScheduler started (interval=60s, use trigger_tick for immediate response)")

  def trigger_tick(self) -> None:
    """用户交互后主动触发一次 tick，不阻塞；若当前 tick 正在执行则本次触发被忽略。"""
    if self._lock.locked():
      return
    try:
      asyncio.get_running_loop().create_task(self.tick())
    except RuntimeError:
      pass

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
    logger.info("PlanScheduler tick (interval or trigger)")
    did_work = False
    async with self._lock:
      conn = get_db_connection()
      try:
        # 0) 若有「之前某次」提交过的视频已到延迟时间，则检查状态并下载（与当前要执行的任务无关；无则跳过）
        n_processed = await _process_pending_video_downloads(conn)
        did_work = (n_processed or 0) > 0
        # 0.5) 对长时间处于 running 的任务做兜底推进（有产出则验收，无则标失败）
        n_recovered = await _recover_stale_running_tasks(conn)
        if (n_recovered or 0) > 0:
          did_work = True
        if not has_plan_work(conn):
          return
        # 1) 先把依赖已满足的 pending 推进为 ready（必须先做，否则 has_acquirable_work 会误判为「无可执行」）
        await self._promote_pending(conn)
        # 2) 若无本轮可执行工作（仅剩等待态如 awaiting_download、scheduled_at 未到），早退
        if not has_acquirable_work(conn):
          return
        # 3) 领取一个 ready 任务（串行约束 + SKIP LOCKED）
        task = acquire_next_task(conn)
        if not task:
          return
        did_work = True  # 领取了任务，执行/失败/验收等都会触发下一轮；仅等待态会再置为 False

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
          task_name = task.get("name") or "未命名任务"
          append_plan_log(
            conn,
            e.plan_id,
            level="info",
            event="video_deferred_download",
            payload={
              "taskId": str(e.task_id),
              "title": f"任务进入等待：{task_name}（等待视频下载，非完成）",
              "icon": "info",
              "bullets": [
                "视频已提交生成，调度器将按配置延迟后再检查并下载到产出路径。",
                "仅依赖本任务的下游保持 pending；其他任务（同计划或他计划）不受影响，会继续调度。",
              ],
            },
            task_id=e.task_id,
          )
          did_work = False
          # 仍触发下一 tick，让不依赖本视频的 ready 任务（同 plan 或他 plan）立刻被调度
          self.trigger_tick()
          return
        except Exception as exec_err:
          logger.warning("Executor raised (will try acceptance if output file exists): plan=%s task=%s: %s", plan_id, task_id, exec_err)
          # 若工具已落盘但执行器后续报错（如 LLM 超时、网络中断），仍按产出文件做验收，避免「工具成功却未验收」
          task_name_fallback = task.get("name") or "未命名任务"
          exec_args = task.get("executor_args") or {}
          output_rel_fallback = exec_args.get("output_relpath") or ""
          output_path_fallback = ""
          if output_rel_fallback:
            fp = Path(__file__).resolve().parents[3] / "outputs" / "plans" / str(plan_id) / str(output_rel_fallback)
            if fp.exists() and fp.is_file():
              output_path_fallback = str(fp)
          if output_path_fallback:
            logger.info("执行器报错但产出文件已存在，进行兜底验收: %s", output_path_fallback)
            content_preview_fallback = _content_preview_for_path(Path(output_path_fallback))
            spec_content = read_spec(plan_id)
            accepted_fallback, reason_fallback = await coordinator.evaluate_task_output(
              task, output_path_fallback, content_preview_fallback, (spec_content[:2000] if spec_content else "")
            )
            if accepted_fallback:
              update_task_status(conn, task_id, status="succeeded", finished_at=datetime.now())
              append_plan_log(
                conn, plan_id, level="info", event="task_accepted",
                payload={
                  "taskId": str(task_id),
                  "reason": reason_fallback,
                  "title": f"验收通过：{task_name_fallback}（执行器报错但产物已落盘，验收通过）",
                  "icon": "success",
                  "bullets": [reason_fallback or "产物文件存在且符合要求"],
                },
                task_id=task_id,
              )
              append_spec_milestone(plan_id, f"任务「{task_name_fallback}」已验收通过")
              tasks = list_tasks(conn, plan_id)
              if tasks and all((t.get("status") == "succeeded") for t in tasks):
                update_plan(conn, plan_id, user_id=None, status="succeeded")
                append_plan_log(
                  conn, plan_id, level="info", event="plan_succeeded",
                  payload={"title": "计划已全部完成", "icon": "success", "bullets": [f"共 {len(tasks)} 个任务均已成功执行。"]},
                )
              did_work = True
            else:
              update_task_status(
                conn, task_id, status="failed", finished_at=datetime.now(),
                error={"rejected": True, "reason": reason_fallback},
              )
              append_plan_log(
                conn, plan_id, level="warning", event="task_rejected",
                payload={
                  "taskId": str(task_id),
                  "reason": reason_fallback,
                  "title": f"验收不通过：{task_name_fallback}",
                  "icon": "error",
                  "bullets": [reason_fallback or "产物不符合要求"],
                },
                task_id=task_id,
              )
          else:
            logger.warning(
              "执行器报错且未找到产出文件，无法兜底验收。路径: outputs/plans/%s/%s（请确认工具是否写入该路径）",
              plan_id,
              output_rel_fallback or "(无 output_relpath)",
            )
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
        if not output_path:
          logger.warning(
            "未找到产出文件 at outputs/plans/%s/%s，验收将判不通过（工具须写入该路径）",
            plan_id,
            output_rel or "(无 output_relpath)",
          )
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
    # running 状态下完成一项子任务（含工具调用、验收）后立刻触发下一轮，以便连续执行下一任务
    if did_work:
      self.trigger_tick()

  async def _promote_pending(self, conn):
    """
    将依赖满足的 pending task 推进为 ready。
    依赖字段 depends_on 存的是 idempotency_key（例如 positioning.md）。
    """
    # 粗粒度：遍历所有 pending tasks（MVP 数据量很小）
    with conn.cursor() as cursor:
      cursor.execute(
        """
        SELECT id, plan_id, name, depends_on, status
        FROM agent_plan_tasks
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 200
        """
      )
      pending = cursor.fetchall() or []

    n_skipped_deps = 0
    for row in pending:
      task_id = row["id"]
      plan_id = row["plan_id"]
      task_name = row.get("name") or str(task_id)
      deps = _json_or_list(row.get("depends_on"))
      if not deps:
        update_task_status(conn, task_id, status="ready")
        logger.debug("pending -> ready (无依赖): %s", task_name)
        continue

      # 检查依赖任务是否全部 succeeded（支持 key 为任务名或产出文件名，见 get_succeeded_dep_task）
      dep_tasks: List[Dict[str, Any]] = []
      ok = True
      for key in deps:
        k = (key or "").strip() if isinstance(key, str) else str(key).strip()
        dep_task = get_succeeded_dep_task(conn, plan_id, k)
        if not dep_task:
          logger.debug(
            "pending 未推进: 任务=%s, depends_on_key=%r（未找到 status=succeeded 的依赖；可运行 scripts/inspect_plan_tasks.py <plan_id> 查看 idempotency_key 与 depends_on 是否一致）",
            task_name,
            k,
          )
          ok = False
          break
        dep_tasks.append(dep_task)
      if not ok:
        n_skipped_deps += 1
        continue
      logger.info("pending -> ready (依赖已满足): %s", task_name)
      # 若依赖中包含「视频任务」（产出 .mp4），下游至少延迟 N 分钟再执行，避免视频未生成完就跑下游
      delay_minutes = 30
      try:
        from src.config.loader import load_yaml_config
        cfg = load_yaml_config("conf.yaml") or {}
        delay_minutes = int(cfg.get("VIDEO_GENERATION") or {}).get("downstream_delay_minutes") or 30
      except Exception:
        pass
      scheduled_at = None
      for dep_task in dep_tasks:
        args = dep_task.get("executor_args")
        if isinstance(args, str):
          try:
            args = json.loads(args) if (args or "").strip().startswith("{") else {}
          except Exception:
            args = {}
        if not isinstance(args, dict):
          args = {}
        out_rel = (args.get("output_relpath") or "").lower()
        if not out_rel.endswith(".mp4"):
          continue
        started = dep_task.get("started_at")
        if started:
          if scheduled_at is None or (started > scheduled_at):
            scheduled_at = started
      if scheduled_at is not None and delay_minutes > 0:
        run_after = scheduled_at + timedelta(minutes=delay_minutes)
        update_task_status(conn, task_id, status="ready", scheduled_at=run_after)
      else:
        update_task_status(conn, task_id, status="ready")

    if n_skipped_deps > 0:
      logger.info(
        "本 tick 有 %s 个 pending 因依赖未满足未推进；可运行 python scripts/inspect_plan_tasks.py <plan_id> 查看 depends_on 与 idempotency_key 是否一致",
        n_skipped_deps,
      )


_SCHEDULER: Optional[PlanScheduler] = None


def get_plan_scheduler() -> PlanScheduler:
  global _SCHEDULER
  if _SCHEDULER is None:
    _SCHEDULER = PlanScheduler()
  return _SCHEDULER

