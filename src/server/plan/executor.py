# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID

import psycopg

from src.llms.llm import get_llm_by_model_name, get_llm_by_type
from src.server.plan.db import append_plan_log, update_task_status

logger = logging.getLogger(__name__)


def _outputs_root() -> Path:
  return Path(__file__).resolve().parents[3] / "outputs" / "plans"


def _ensure_parent(path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)


async def _run_llm(prompt: str, model_name: Optional[str] = None) -> str:
  llm = None
  if model_name:
    llm = get_llm_by_model_name(model_name)
  else:
    llm = get_llm_by_type("basic")

  # langchain BaseChatModel 支持 ainvoke；否则用线程池执行 invoke
  if hasattr(llm, "ainvoke"):
    msg = await llm.ainvoke(prompt)
  else:  # pragma: no cover
    loop = asyncio.get_event_loop()
    msg = await loop.run_in_executor(None, lambda: llm.invoke(prompt))

  # msg 可能是 BaseMessage 或 string
  content = getattr(msg, "content", None)
  return str(content if content is not None else msg)


def _run_cmd(cmd: str, cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> tuple[int, str, str]:
  """同步执行 shell 命令，返回 (returncode, stdout, stderr)。"""
  env = env or {}
  full_env = {**os.environ, **env}
  try:
    r = subprocess.run(
      cmd,
      shell=True,
      cwd=str(cwd) if cwd else None,
      env=full_env,
      capture_output=True,
      text=True,
      timeout=600,
    )
    return r.returncode, r.stdout or "", r.stderr or ""
  except subprocess.TimeoutExpired:
    return -1, "", "Command timed out (600s)"
  except Exception as e:
    return -1, "", str(e)


async def _run_shell(
  conn: psycopg.Connection,
  plan_id: UUID,
  task_id: UUID,
  executor_args: Dict[str, Any],
) -> None:
  """
  执行 shell 类型任务。支持：
  - command: 主命令（必填）
  - setup_command: 先执行的安装/准备命令（如 pip install -r requirements.txt）
  - cwd: 工作目录（相对 outputs/plans/{plan_id} 或绝对路径）
  - env: 环境变量
  若缺少工具，可在 setup_command 中安装后再执行 command。
  """
  command = executor_args.get("command")
  if not command or not str(command).strip():
    raise ValueError("executor_args.command is required for shell executor")
  setup_command = executor_args.get("setup_command")
  cwd_arg = executor_args.get("cwd")
  work_root = _outputs_root() / str(plan_id)
  _ensure_parent(work_root / ".keep")
  cwd = work_root
  if cwd_arg:
    p = Path(cwd_arg)
    if p.is_absolute():
      cwd = p
    else:
      cwd = work_root / p

  # 1) 先执行安装/准备命令
  if setup_command and str(setup_command).strip():
    code, out, err = await asyncio.get_event_loop().run_in_executor(
      None, lambda: _run_cmd(str(setup_command), cwd=cwd)
    )
    if code != 0:
      raise RuntimeError(f"安装/准备命令失败 (exit {code}): {err or out}")

  # 2) 执行主命令
  code, out, stderr = await asyncio.get_event_loop().run_in_executor(
    None, lambda: _run_cmd(str(command), cwd=cwd)
  )
  if code != 0:
    raise RuntimeError(f"命令执行失败 (exit {code}): {stderr or out}")

  # 3) 若有 output_relpath，仅落盘（不登记 DB 产物）
  output_rel = executor_args.get("output_relpath")
  if output_rel:
    out_path = (cwd if cwd.is_absolute() else work_root) / output_rel
    if out_path.exists():
      # 保留落盘行为，DB 不再登记 artifact
      pass

  update_task_status(conn, task_id, status="succeeded", finished_at=datetime.now())
  append_plan_log(
    conn,
    plan_id,
    level="info",
    event="task_succeeded",
    payload={
      "taskId": str(task_id),
      "title": "任务完成（shell）",
      "icon": "success",
      "bullets": [f"命令已成功执行", output_rel if output_rel else "无产出文件"],
    },
    task_id=task_id,
  )


class PlanTaskExecutor:
  """
  任务执行器（MVP）

  支持：
  - llm：调用 LLM 生成文本并写入文件
  - file：直接写入文件（占位/模板）
  """

  async def execute(self, conn: psycopg.Connection, task: Dict[str, Any]) -> None:
    task_id: UUID = task["id"]
    plan_id: UUID = task["plan_id"]
    executor_type = task.get("executor_type") or "file"
    executor_args: Dict[str, Any] = task.get("executor_args") or {}

    task_name = task.get("name") or "未命名任务"
    try:
      append_plan_log(
        conn,
        plan_id,
        level="info",
        event="task_start",
        payload={
          "taskId": str(task_id),
          "name": task_name,
          "title": f"任务已启动：{task_name}",
          "icon": "info",
          "bullets": [task.get("description") or "正在执行…"],
        },
        task_id=task_id,
      )

      output_rel = executor_args.get("output_relpath") or ""
      if executor_type == "shell":
        await _run_shell(conn, plan_id, task_id, executor_args)
        return
      if not output_rel:
        raise ValueError("executor_args.output_relpath is required")
      out_path = _outputs_root() / str(plan_id) / str(output_rel)
      _ensure_parent(out_path)

      if executor_type == "file":
        content = executor_args.get("content") or ""
        out_path.write_text(str(content), encoding="utf-8")
      elif executor_type == "llm":
        prompt = executor_args.get("prompt") or ""
        model = executor_args.get("model")
        content = await _run_llm(prompt, model_name=model)
        out_path.write_text(content, encoding="utf-8")
      else:
        raise ValueError(f"Unsupported executor_type: {executor_type}")

      update_task_status(conn, task_id, status="succeeded", finished_at=datetime.now())
      append_plan_log(
        conn,
        plan_id,
        level="info",
        event="task_succeeded",
        payload={
          "taskId": str(task_id),
          "output": str(out_path),
          "title": f"任务完成：{task_name}",
          "icon": "success",
          "bullets": [f"产出：{output_rel}", str(out_path)],
        },
        task_id=task_id,
      )
    except Exception as e:
      logger.exception(f"Task execution failed: plan={plan_id} task={task_id}: {e}")
      update_task_status(conn, task_id, status="failed", finished_at=datetime.now(), error={"error": str(e)})
      append_plan_log(
        conn,
        plan_id,
        level="error",
        event="task_failed",
        payload={
          "taskId": str(task_id),
          "error": str(e),
          "title": f"任务失败：{task_name}",
          "icon": "error",
          "bullets": [str(e)],
        },
        task_id=task_id,
      )
      raise

