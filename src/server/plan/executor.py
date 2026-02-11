# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID

import psycopg
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.llms.llm import get_llm_by_model_name, get_llm_by_type
from src.server.plan.db import append_plan_log, insert_pending_video_download, update_task_status

logger = logging.getLogger(__name__)


class DeferredVideoDownload(Exception):
  """视频已提交，等待延迟下载；任务状态应为 awaiting_download，由调度器在 N 分钟后检查并下载。"""
  def __init__(self, plan_id: UUID, task_id: UUID):
    self.plan_id = plan_id
    self.task_id = task_id
    super().__init__(f"DeferredVideoDownload plan_id={plan_id} task_id={task_id}")

# 执行单元 prompt_set -> 模板名
EXECUTOR_PROMPT_MAP = {
  "video_creation": "executor_video_creation",
  "simple": "executor_simple",
}

# 最大 Agent 步数（LLM + 工具调用轮数）
EXECUTOR_AGENT_MAX_STEPS = 20

# 产出为这些后缀时，必须通过对应工具落盘，不能仅靠 LLM 文字回复；执行后若文件不存在则视为未完成
# 注意：.ppt 为历史/模型误输出的旧后缀，系统会在执行时规范化为 .pptx
OUTPUT_EXTENSIONS_REQUIRING_TOOL = {".mp4", ".png", ".jpg", ".jpeg", ".wav", ".mp3", ".pptx", ".ppt"}

# 产出后缀 → 必须调用的工具名
OUTPUT_EXT_TOOL_MAP = {
  ".mp4": "video_generation_tool",
  ".png": "image_generation_tool",
  ".jpg": "image_generation_tool",
  ".jpeg": "image_generation_tool",
  ".wav": "tts_tool",
  ".mp3": "tts_tool",
  ".pptx": "ppt_generate_tool",
  ".ppt": "ppt_generate_tool",
}


def _outputs_root() -> Path:
  return Path(__file__).resolve().parents[3] / "outputs" / "plans"


def _parse_depends_on(depends_on: Any) -> List[str]:
  """将 task.depends_on 解析为相对路径字符串列表（如 ['ep01_script.md']）。"""
  if depends_on is None:
    return []
  if isinstance(depends_on, list):
    return [str(x).strip() for x in depends_on if x]
  if isinstance(depends_on, str):
    try:
      obj = json.loads(depends_on)
      if isinstance(obj, list):
        return [str(x).strip() for x in obj if x]
    except Exception:
      pass
  return []


def _read_dependency_contents(plan_id: UUID, depends_on: List[str]) -> str:
  """
  读取 depends_on 中列出的文件内容，拼成「依赖文件内容」段落。
  若某个文件不存在则抛出 FileNotFoundError。
  """
  if not depends_on:
    return ""
  root = _outputs_root() / str(plan_id)
  parts: List[str] = []
  for rel in depends_on:
    rel = str(rel).strip()
    if not rel or ".." in rel or rel.startswith("/"):
      continue
    path = (root / rel).resolve()
    try:
      path.relative_to(root.resolve())
    except ValueError:
      raise ValueError(f"依赖路径非法，不允许访问计划目录外: {rel}")
    if not path.exists() or not path.is_file():
      raise FileNotFoundError(f"依赖文件不存在: {rel}（路径: {path}）")
    content = path.read_text(encoding="utf-8", errors="replace")
    parts.append(f"--- {rel} ---\n\n{content}")
  if not parts:
    return ""
  return "以下是与本任务相关的依赖文件内容，请严格基于这些内容完成任务。\n\n" + "\n\n".join(parts) + "\n\n--- 任务要求 ---\n\n"


def _ensure_parent(path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)


def _get_executor_tools(prompt_set: str) -> List[Any]:
  """按 executor_prompt_set 返回工具列表（LangChain tool 对象）。"""
  from src.tools import (
    crawl_tool,
    create_file_tool,
    edit_file_tool,
    ffmpeg_tool,
    image_generation_tool,
    ppt_generate_tool,
    tts_tool,
    video_generation_tool,
  )
  try:
    from src.tools.search import get_general_web_search_tool
    web_search = get_general_web_search_tool(5)
  except Exception:
    from langchain_core.tools import tool
    @tool
    def web_search(query: str) -> str:
      """网页搜索未配置。"""
      return "网页搜索暂不可用。"

  simple_tools = [create_file_tool, edit_file_tool, web_search, crawl_tool, image_generation_tool]
  if prompt_set == "video_creation":
    return simple_tools + [tts_tool, ffmpeg_tool, video_generation_tool, ppt_generate_tool]
  return simple_tools


def _render_executor_prompt(
  prompt_set: str,
  task_name: str,
  task_prompt: str,
  dependency_content: str,
  plan_id: str,
  output_relpath: str,
) -> str:
  """渲染执行单元 prompt 模板。"""
  from src.prompts.template import render_prompt_with_vars
  template_name = EXECUTOR_PROMPT_MAP.get(prompt_set) or "executor_simple"
  work_dir = f"outputs/plans/{plan_id}"
  return render_prompt_with_vars(
    template_name,
    task_name=task_name or "未命名任务",
    task_prompt=task_prompt or "",
    dependency_content=dependency_content or "（无依赖文件）",
    plan_id=str(plan_id),
    output_relpath=output_relpath or "",
    work_dir=work_dir,
  )


def _sanitize_tool_args(args: Dict[str, Any], max_value_len: int = 200) -> Dict[str, Any]:
  """对工具参数做截断，避免日志过长或泄露大段内容。"""
  out: Dict[str, Any] = {}
  for k, v in (args or {}).items():
    if isinstance(v, str):
      out[k] = v[:max_value_len] + ("..." if len(v) > max_value_len else "")
    elif isinstance(v, (list, dict)):
      out[k] = f"<{type(v).__name__} len={len(v)}>"
    else:
      out[k] = v
  return out


def _is_unrecoverable_tool_error(tool_result: str) -> bool:
  """工具返回内容是否为「不可恢复」错误（缺依赖/未配置等），重试无意义，应直接失败并提示用户。"""
  if not (tool_result and isinstance(tool_result, str)):
    return False
  s = tool_result.strip().lower()
  unrecoverable = (
    "请安装" in tool_result or "pip install" in s or "not installed" in s
    or "未配置" in tool_result or "environment variable" in s or "is not set" in s
    or "未设置" in tool_result or "not set" in s
  )
  return bool(unrecoverable)


async def _analyze_tool_failure(
  tool_name: str,
  error_message: str,
  args_preview: Dict[str, Any],
  model_name: Optional[str] = None,
) -> tuple[str, Optional[str]]:
  """
  分析工具失败原因并给出处理建议。
  返回 (action, search_query): action 为 "retry" | "search" | "skip"；
  search 时 search_query 为搜索关键词，否则为 None。
  """
  err_short = (error_message or "")[:500]
  args_str = json.dumps(args_preview, ensure_ascii=False)[:300]
  prompt = f"""工具「{tool_name}」执行失败。
错误信息：{err_short}
参数摘要：{args_str}

请用一行回复，且仅输出以下三种之一（不要其他解释）：
- RETRY：若可能通过重试或小调整解决
- SEARCH 关键词：若需要查替代方案或解决方案，空格后写搜索关键词（中文或英文）
- SKIP：若无法处理，放弃本次调用
"""
  try:
    llm = get_llm_by_model_name(model_name) if model_name else get_llm_by_type("basic")
    if hasattr(llm, "ainvoke"):
      msg = await llm.ainvoke([HumanMessage(content=prompt)])
    else:
      msg = await asyncio.get_event_loop().run_in_executor(
        None, lambda: llm.invoke([HumanMessage(content=prompt)])
      )
    text = (getattr(msg, "content", None) or str(msg) or "").strip().upper()
    if "RETRY" in text:
      return ("retry", None)
    if "SEARCH" in text:
      parts = text.split("SEARCH", 1)
      query = (parts[1].strip() if len(parts) > 1 else "").strip()
      if not query:
        query = f"{tool_name} 失败 替代方案"
      return ("search", query)
  except Exception as e:
    logger.warning("_analyze_tool_failure failed: %s", e)
  return ("skip", None)


def _get_search_tool(tool_map: Dict[str, Any]) -> Optional[Any]:
  """从 tool_map 中取搜索类工具（web_search 或名称含 search 的）。"""
  for name, t in tool_map.items():
    if name == "web_search" or "search" in name.lower():
      return t
  return None


async def _run_executor_agent(
  conn: psycopg.Connection,
  plan_id: UUID,
  task_id: UUID,
  output_relpath: str,
  executor_prompt_set: str,
  task_name: str,
  task_prompt: str,
  dependency_content: str,
  model_name: Optional[str] = None,
) -> None:
  """
  运行执行单元 Agent：LLM + 工具，循环处理 tool_calls，由 Agent 通过 create_file_tool 等将产物落盘。
  每次工具调用会写入 plan log（event=tool_call），便于排查与观测。
  """
  tools = _get_executor_tools(executor_prompt_set)
  prompt_text = _render_executor_prompt(
    executor_prompt_set, task_name, task_prompt, dependency_content, str(plan_id), output_relpath
  )
  llm = get_llm_by_model_name(model_name) if model_name else get_llm_by_type("basic")
  if not hasattr(llm, "bind_tools"):
    raise RuntimeError("Plan executor agent requires LLM with bind_tools (e.g. OpenAI-compatible chat)")
  bound_llm = llm.bind_tools(tools)
  messages: List[Any] = [HumanMessage(content=prompt_text)]
  tool_map = {t.name: t for t in tools}
  result_preview_len = 400
  # 产出必须由某工具落盘时，若该工具已返回「不可恢复」错误（如缺依赖、未配置），则不再强制重试，直接失败并提示用户
  _ext = (output_relpath or "").strip().lower()
  _ext = "." + _ext.rsplit(".", 1)[-1] if _ext and "." in _ext else ""
  _required_tool = OUTPUT_EXT_TOOL_MAP.get(_ext) if _ext else None
  required_tool_unrecoverable = False
  already_forced_for_required_tool = False  # 已强制过一次仍无 tool_calls 时不再重复强制，直接失败

  for step in range(EXECUTOR_AGENT_MAX_STEPS):
    if hasattr(bound_llm, "ainvoke"):
      response = await bound_llm.ainvoke(messages)
    else:
      response = await asyncio.get_event_loop().run_in_executor(
        None, lambda: bound_llm.invoke(messages)
      )
    if not isinstance(response, AIMessage):
      response = AIMessage(content=str(response))
    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
      # 若产出必须由工具落盘，且文件尚未生成，则强制要求 LLM 再试一轮（必须发起工具调用）
      out_path = _outputs_root() / str(plan_id) / (output_relpath or "")
      if _required_tool and (not out_path.exists() or not out_path.is_file()):
        if required_tool_unrecoverable:
          raise RuntimeError(
            f"本任务产出为 {_ext}，需调用 {_required_tool}，但该工具因环境/配置问题无法完成（如未安装依赖或未配置）。请根据上方日志安装依赖或配置后重试。"
          )
        if already_forced_for_required_tool:
          raise RuntimeError(
            f"本任务产出为 {_ext}，需调用 {_required_tool}，但模型在收到强制提示后仍未发起工具调用。请确认当前模型支持 function calling（工具调用），或更换模型后重试。"
          )
        already_forced_for_required_tool = True
        messages.append(response)
        path_hint = f"outputs/plans/{plan_id}/{output_relpath}"
        if _required_tool in ("ppt_generate_tool", "tts_tool"):
          force_msg = (
            f"重要：本任务产出必须为 {_ext} 文件，你必须立即调用 {_required_tool}，"
            f"传 base_dir=\"outputs\"、relative_path=\"plans/{plan_id}/{output_relpath}\"，将产物落盘到 {path_hint}。"
            "不要只回复文字，必须发起工具调用。"
          )
        else:
          force_msg = (
            f"重要：本任务产出必须为 {_ext} 文件，你必须立即调用 {_required_tool} 生成并落盘到 {path_hint}。"
            "不要只回复文字，必须发起工具调用。"
          )
        messages.append(HumanMessage(content=force_msg))
        append_plan_log(
          conn,
          plan_id,
          level="info",
          event="tool_call",
          payload={
            "tool": _required_tool,
            "status": "required",
            "taskId": str(task_id),
            "title": "要求调用工具",
            "bullets": [f"LLM 未发起工具调用，已强制要求调用 {_required_tool}"],
          },
          task_id=task_id,
        )
        continue
      break
    messages.append(response)
    for tc in tool_calls:
      name = tc.get("name") or ""
      args = tc.get("args") or {}
      tid = tc.get("id") or f"call_{step}_{name}"
      tool_obj = tool_map.get(name)
      if not tool_obj:
        messages.append(ToolMessage(tool_call_id=tid, content=f"工具不存在: {name}"))
        append_plan_log(
          conn,
          plan_id,
          level="warning",
          event="tool_call",
          payload={
            "tool": name,
            "status": "skipped",
            "reason": "工具不存在",
            "taskId": str(task_id),
            "title": f"工具调用：{name}",
            "bullets": [f"未找到工具 {name}，已跳过"],
          },
          task_id=task_id,
        )
        continue
      try:
        if name == "video_generation_tool":
          append_plan_log(
            conn,
            plan_id,
            level="info",
            event="tool_call",
            payload={
              "tool": name,
              "status": "running",
              "taskId": str(task_id),
              "title": "正在调用视频生成工具",
              "bullets": ["视频生成通常需要数分钟，请稍候"],
            },
            task_id=task_id,
          )
        elif name == "ppt_generate_tool":
          append_plan_log(
            conn,
            plan_id,
            level="info",
            event="tool_call",
            payload={
              "tool": name,
              "status": "running",
              "taskId": str(task_id),
              "title": "正在调用 PPT 生成工具",
              "bullets": ["生成 PPT 中，请稍候"],
            },
            task_id=task_id,
          )
        elif name == "tts_tool":
          append_plan_log(
            conn,
            plan_id,
            level="info",
            event="tool_call",
            payload={
              "tool": name,
              "status": "running",
              "taskId": str(task_id),
              "title": "正在调用 TTS 文本转语音",
              "bullets": ["生成音频中，请稍候"],
            },
            task_id=task_id,
          )
        if hasattr(tool_obj, "ainvoke"):
          result = await tool_obj.ainvoke(args)
        else:
          result = await asyncio.get_event_loop().run_in_executor(None, lambda: tool_obj.invoke(args))
        result_str = str(result)
        messages.append(ToolMessage(tool_call_id=tid, content=result_str))
        preview = result_str[:result_preview_len] + ("..." if len(result_str) > result_preview_len else "")
        append_plan_log(
          conn,
          plan_id,
          level="info",
          event="tool_call",
          payload={
            "tool": name,
            "status": "ok",
            "args_preview": _sanitize_tool_args(args),
            "result_preview": preview,
            "taskId": str(task_id),
            "title": f"工具调用：{name}",
            "bullets": [preview.split("\n")[0][:120] if preview else "(无返回)"],
          },
          task_id=task_id,
        )
        if name == "video_generation_tool" and result_str.strip().startswith("DEFERRED_VIDEO_DOWNLOAD|"):
          parts = result_str.strip().split("|")
          if len(parts) >= 7:
            insert_pending_video_download(
              conn,
              plan_id,
              task_id,
              file_id=parts[1],
              output_path_abs=parts[2],
              base_url=parts[3],
              status_path=parts[4],
              download_path=parts[5],
              delay_minutes=int(parts[6]),
            )
            raise DeferredVideoDownload(plan_id, task_id)
        if name == _required_tool and _is_unrecoverable_tool_error(result_str):
          required_tool_unrecoverable = True
      except DeferredVideoDownload:
        raise
      except Exception as e:
        logger.warning("Executor tool %s failed: %s", name, e)
        err_msg = str(e)
        if name == _required_tool and _is_unrecoverable_tool_error(err_msg):
          required_tool_unrecoverable = True
        args_preview = _sanitize_tool_args(args)
        append_plan_log(
          conn,
          plan_id,
          level="warning",
          event="tool_call",
          payload={
            "tool": name,
            "status": "failed",
            "error": err_msg,
            "args_preview": args_preview,
            "taskId": str(task_id),
            "title": f"工具调用：{name}",
            "bullets": [f"执行失败: {err_msg}"],
          },
          task_id=task_id,
        )
        # 失败分析 -> 重试 / 搜索替代方案 / 跳过
        action, search_query = await _analyze_tool_failure(name, err_msg, args_preview, model_name)
        content_for_agent = f"执行失败: {e}"

        if action == "retry":
          try:
            if hasattr(tool_obj, "ainvoke"):
              result = await tool_obj.ainvoke(args)
            else:
              result = await asyncio.get_event_loop().run_in_executor(None, lambda: tool_obj.invoke(args))
            result_str = str(result)
            messages.append(ToolMessage(tool_call_id=tid, content=result_str))
            preview = result_str[:result_preview_len] + ("..." if len(result_str) > result_preview_len else "")
            append_plan_log(
              conn,
              plan_id,
              level="info",
              event="tool_call",
              payload={
                "tool": name,
                "status": "ok",
                "retry": True,
                "args_preview": args_preview,
                "result_preview": preview,
                "taskId": str(task_id),
                "title": f"工具调用：{name}（重试成功）",
                "bullets": [preview.split("\n")[0][:120] if preview else "(无返回)"],
              },
              task_id=task_id,
            )
            continue
          except Exception as e2:
            logger.warning("Executor tool %s retry failed: %s", name, e2)
            content_for_agent = f"执行失败（重试仍失败）: {e2}"
            append_plan_log(
              conn,
              plan_id,
              level="warning",
              event="tool_call",
              payload={
                "tool": name,
                "status": "failed",
                "retry": True,
                "error": str(e2),
                "taskId": str(task_id),
                "title": f"工具调用：{name}",
                "bullets": ["重试后仍失败"],
              },
              task_id=task_id,
            )

        if action == "search" and search_query:
          search_tool = _get_search_tool(tool_map)
          if search_tool:
            try:
              if hasattr(search_tool, "ainvoke"):
                search_result = await search_tool.ainvoke({"query": search_query})
              else:
                search_result = await asyncio.get_event_loop().run_in_executor(
                  None, lambda: search_tool.invoke({"query": search_query})
                )
              search_str = str(search_result)[:2000]
              content_for_agent = (
                f"执行失败: {e}\n\n"
                "已根据失败原因搜索替代方案，请根据以下结果尝试其他方式完成任务（例如换工具、换参数或换实现）：\n\n"
                f"{search_str}"
              )
              append_plan_log(
                conn,
                plan_id,
                level="info",
                event="failure_recovery",
                payload={
                  "tool": name,
                  "action": "search",
                  "search_query": search_query,
                  "result_preview": search_str[:400],
                  "taskId": str(task_id),
                  "title": "工具失败后搜索替代方案",
                  "bullets": [f"关键词: {search_query}", search_str.split("\n")[0][:100] if search_str else ""],
                },
                task_id=task_id,
              )
            except Exception as search_err:
              logger.warning("Failure recovery search failed: %s", search_err)
              content_for_agent = f"执行失败: {e}\n\n尝试搜索替代方案时出错: {search_err}"

        messages.append(ToolMessage(tool_call_id=tid, content=content_for_agent))

  return


async def _run_llm(prompt: str, model_name: Optional[str] = None) -> str:
  llm = None
  if model_name:
    llm = get_llm_by_model_name(model_name)
  else:
    llm = get_llm_by_type("basic")

  # 兼容：传入 list of messages 或单条 message
  if isinstance(prompt, str):
    inp = [HumanMessage(content=prompt)]
  else:
    inp = prompt
  if hasattr(llm, "ainvoke"):
    msg = await llm.ainvoke(inp)
  else:  # pragma: no cover
    loop = asyncio.get_event_loop()
    msg = await loop.run_in_executor(None, lambda: llm.invoke(inp))

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

      # 规范化：若规划器/模型给出 .ppt（旧后缀），统一改为 .pptx 执行与验收
      try:
        p = Path(str(output_rel))
        if p.suffix.lower() == ".ppt":
          normalized = str(p.with_suffix(".pptx"))
          append_plan_log(
            conn,
            plan_id,
            level="warning",
            event="output_normalized",
            payload={
              "taskId": str(task_id),
              "title": "已规范化产出后缀",
              "bullets": [f"{output_rel} → {normalized}（PPT 统一使用 .pptx）"],
            },
            task_id=task_id,
          )
          output_rel = normalized
      except Exception:
        pass

      out_path = _outputs_root() / str(plan_id) / str(output_rel)
      _ensure_parent(out_path)

      if executor_type == "file":
        content = executor_args.get("content") or ""
        out_path.write_text(str(content), encoding="utf-8")
      elif executor_type == "llm":
        base_prompt = executor_args.get("prompt") or ""
        model = executor_args.get("model")
        depends_on = _parse_depends_on(task.get("depends_on"))
        try:
          dependency_prefix = _read_dependency_contents(plan_id, depends_on)
        except FileNotFoundError:
          dependency_prefix = ""
        executor_prompt_set = executor_args.get("executor_prompt_set") or ""
        if executor_prompt_set:
          try:
            await _run_executor_agent(
              conn=conn,
              plan_id=plan_id,
              task_id=task_id,
              output_relpath=output_rel,
              executor_prompt_set=executor_prompt_set,
              task_name=task_name,
              task_prompt=base_prompt,
              dependency_content=dependency_prefix,
              model_name=model,
            )
            # 产出为 .mp4/.png/.wav 等时，必须由对应工具落盘；若文件不存在说明未调用工具，视为未完成
            out_path = _outputs_root() / str(plan_id) / str(output_rel)
            ext = (Path(output_rel).suffix or "").lower()
            if ext in OUTPUT_EXTENSIONS_REQUIRING_TOOL and (not out_path.exists() or not out_path.is_file()):
              tool_hint = OUTPUT_EXT_TOOL_MAP.get(ext, "对应工具")
              raise RuntimeError(
                f"本任务产出为 {ext}，必须调用 {tool_hint} 并落盘到指定路径；当前未生成文件，验收将不通过。请确保在对话中实际调用该工具。"
              )
          except Exception as e:
            # 产出为 .mp4/.png 等时不允许用 LLM 文本落盘，直接失败
            if "必须调用" in str(e) and "并落盘" in str(e):
              raise
            logger.warning("Executor agent failed, fallback to single LLM write: %s", e)
            prompt = (dependency_prefix + base_prompt) if dependency_prefix else base_prompt
            content = await _run_llm(prompt, model_name=model)
            out_path.write_text(content, encoding="utf-8")
        else:
          prompt = (dependency_prefix + base_prompt) if dependency_prefix else base_prompt
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
    except DeferredVideoDownload:
      raise
    except Exception as e:
      logger.exception(f"Task execution failed: plan={plan_id} task={task_id}: {e}")
      err_msg = str(e)
      update_task_status(conn, task_id, status="failed", finished_at=datetime.now(), error={"error": err_msg})
      exec_args = task.get("executor_args") or {}
      output_rel = exec_args.get("output_relpath") or ""
      append_plan_log(
        conn,
        plan_id,
        level="error",
        event="task_failed",
        payload={
          "taskId": str(task_id),
          "error": err_msg,
          "taskName": task_name,
          "outputRelpath": output_rel,
          "title": f"任务失败：{task_name}",
          "icon": "error",
          "bullets": [err_msg],
        },
        task_id=task_id,
      )
      # 失败分析：若建议搜索解决方案，则调用 web_search 并将结果写入 plan_log 供用户或重试参考
      try:
        action, search_query = await _analyze_tool_failure(
          "task_execution",
          err_msg,
          {"task_name": task_name, "output_relpath": output_rel},
          model_name=(task.get("executor_args") or {}).get("model"),
        )
        if action == "search" and search_query:
          try:
            from src.tools.search import get_general_web_search_tool
            web_search = get_general_web_search_tool(5)
            if hasattr(web_search, "ainvoke"):
              search_result = await web_search.ainvoke({"query": search_query})
            else:
              search_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: web_search.invoke({"query": search_query})
              )
            search_str = str(search_result)[:2000]
            append_plan_log(
              conn,
              plan_id,
              level="info",
              event="failure_recovery_search",
              payload={
                "taskId": str(task_id),
                "searchQuery": search_query,
                "resultPreview": search_str[:500],
                "title": "已根据失败原因搜索解决方案",
                "icon": "info",
                "bullets": [f"关键词：{search_query}", search_str.split("\n")[0][:200] if search_str else ""],
              },
              task_id=task_id,
            )
          except Exception as search_err:
            logger.warning("Task-level failure_recovery_search failed: %s", search_err)
      except Exception as analyze_err:
        logger.warning("Task-level failure analysis failed: %s", analyze_err)
      raise

