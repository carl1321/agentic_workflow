# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
任务拆解。

策略：由大模型根据用户目标动态规划任务列表，不在代码中写死任何内容类型或固定流水线。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from src.llms.llm import get_llm_by_model_name, get_llm_by_type

logger = logging.getLogger(__name__)

# 回退用：当 long_plan_tasks 模板加载失败时使用
TASK_PLAN_PROMPT_FALLBACK = """你是一个长期计划任务规划器。根据用户的目标和澄清要求，规划一系列可执行任务。每个任务会生成一个文件（Markdown 或 JSON），后续任务可以依赖前面任务的产物。所有产物文件将存放在同一目录下，引用依赖时只写文件名即可。

## 用户目标
{objective}

## 用户要求（澄清结果）
{requirements}

## 输出格式
请输出一个 JSON 数组，且只输出该数组，不要其他说明或 Markdown 代码块。每个元素表示一个任务：

{{
  "name": "任务名称（简短）",
  "output_relpath": "产出文件名（如 positioning.md、ep01_script.md、report.json）",
  "prompt": "执行该任务时发给大模型的完整提示词。引用依赖文件时只写文件名，如「基于 positioning.md 的定位」；执行器会自动注入依赖文件内容。不要假设用户做的是某一种固定类型（如修仙、美食等），严格根据用户目标撰写 prompt。",
  "depends_on": ["依赖的产出文件名列表"]
}}

## 要求
- 任务顺序和依赖要合理：被依赖的文件对应的任务必须先执行。
- 不要假设用户做的是某一种固定类型（如修仙、美食、科普等），严格根据用户目标规划任务和撰写每条 prompt。
- 第一个任务通常没有依赖（depends_on 为 []），用于根据用户目标产出「定位/方案/大纲」类文档；后续任务可依赖该文档产出具体内容。
- output_relpath 使用简短文件名，如 positioning.md、script_ep01.md、storyboard.json、report.md。
- 只输出 JSON 数组，不要 ```json 或任何前后文字。"""

# professional sub_type -> 提示词模板名（无则用 long_plan 自带规划）
PROFESSIONAL_PROMPT_MAP = {
  "video_creation": "plan_video_creation",
}


def _get_plan_prompt(
  plan_type: Optional[str],
  sub_type: Optional[str],
  objective: str,
  requirements_text: str,
) -> str:
  """根据 plan_type/sub_type 选择提示词模板并渲染；simple 或 professional 无对应 md 时用 long_plan_tasks。"""
  use_pro = plan_type == "professional" and sub_type and PROFESSIONAL_PROMPT_MAP.get(sub_type)
  template_name = PROFESSIONAL_PROMPT_MAP.get(sub_type or "") if use_pro else "long_plan_tasks"
  try:
    from src.prompts.template import render_prompt_with_vars
    return render_prompt_with_vars(
      template_name,
      objective=objective or "（未提供）",
      requirements=requirements_text or "（无）",
    )
  except Exception as e:
    logger.warning("Plan prompt template %s load failed, using fallback: %s", template_name, e)
    return TASK_PLAN_PROMPT_FALLBACK.format(
      objective=objective or "（未提供）",
      requirements=requirements_text or "（无）",
    )


async def _plan_tasks_with_llm(
  plan_id: str,
  objective: str,
  requirements_text: str,
  model_name: Optional[str] = None,
  plan_type: Optional[str] = None,
  sub_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """调用大模型根据用户目标规划任务列表，返回原始任务描述（name, output_relpath, prompt, depends_on）。"""
  prompt = _get_plan_prompt(plan_type, sub_type, objective, requirements_text)
  llm = get_llm_by_model_name(model_name) if model_name else get_llm_by_type("basic")
  if hasattr(llm, "ainvoke"):
    msg = await llm.ainvoke([HumanMessage(content=prompt)])
  else:
    import asyncio
    msg = await asyncio.get_event_loop().run_in_executor(None, lambda: llm.invoke([HumanMessage(content=prompt)]))
  content = getattr(msg, "content", None) or str(msg)
  content = content.strip()
  # 允许响应被 ```json ... ``` 包裹
  m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
  if m:
    content = m.group(1).strip()
  raw = json.loads(content)
  if not isinstance(raw, list):
    raise ValueError("LLM 未返回 JSON 数组")
  return raw


def _executor_prompt_set(
  plan_type: Optional[str],
  sub_type: Optional[str],
  output_relpath: Optional[str] = None,
) -> str:
  """执行单元使用的 prompt 集合：video_creation 或 simple。
  产出为 .mp4/.wav/.pptx 等时强制用 video_creation（含对应工具）。
  注意：历史上有模型会输出 .ppt（旧格式），我们会在任务规范化时改为 .pptx，但这里也兼容识别 .ppt。
  """
  ext = (output_relpath or "").strip().lower()
  if ext:
    ext = "." + ext.split(".")[-1] if "." in ext else ""
  if ext in {".mp4", ".wav", ".mp3", ".pptx", ".ppt"}:
    return "video_creation"
  if plan_type == "professional" and sub_type == "video_creation":
    return "video_creation"
  return "simple"


def _task_spec_to_full_task(
  plan_id: str,
  spec: Dict[str, Any],
  use_llm: bool,
  model_name: Optional[str],
  plan_type: Optional[str] = None,
  sub_type: Optional[str] = None,
) -> Dict[str, Any]:
  """将规划器返回的一条任务描述转为 create_tasks 所需的完整 task 字典。"""
  name = spec.get("name") or "未命名任务"
  output_rel = (spec.get("output_relpath") or "").strip() or "output.md"
  # 规范化：PPT 统一使用 .pptx。若模型误给 .ppt，则自动更正，确保执行器会绑定 ppt_generate_tool 并正确验收。
  try:
    from pathlib import Path
    p = Path(output_rel)
    if p.suffix.lower() == ".ppt":
      output_rel = str(p.with_suffix(".pptx"))
  except Exception:
    pass
  prompt = spec.get("prompt") or ""
  depends_on = spec.get("depends_on")
  if isinstance(depends_on, list):
    depends_on = [str(x).strip() for x in depends_on if x]
  else:
    depends_on = []
  executor_prompt_set = _executor_prompt_set(plan_type, sub_type, output_relpath=output_rel)
  return {
    "name": name,
    "description": f"生成文件：{output_rel}",
    "acceptance_criteria": f"在 outputs/plans/{plan_id}/{output_rel} 生成非空文件，内容满足任务要求。",
    "status": "pending",
    "depends_on": depends_on,
    "scheduled_at": None,
    "executor_type": "llm" if use_llm else "file",
    "executor_args": (
      {
        "model": model_name,
        "output_relpath": output_rel,
        "prompt": prompt,
        "executor_prompt_set": executor_prompt_set,
      }
      if use_llm
      else {
        "output_relpath": output_rel,
        "content": prompt,
      }
    ),
    "idempotency_key": output_rel,
    "max_retries": 1,
  }


async def build_tasks_from_goal(
  plan_id: str,
  ora_spec: Dict[str, Any],
  *,
  use_llm: bool = True,
  model_name: Optional[str] = None,
  plan_type: Optional[str] = None,
  sub_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """
  根据用户目标（ORA spec）由大模型规划任务列表。
  plan_type/sub_type 由 coordinator 在澄清结束时传入：simple 或未传则用 long_plan 自带规划（long_plan_tasks）；
  professional 且 sub_type 有对应专业提示词则加载该 md，否则沿用 long_plan 规划。
  返回与 create_tasks 兼容的 task 字典列表。
  """
  objective = ora_spec.get("objective") or ""
  requirements = ora_spec.get("requirements") or []
  req_text = "\n".join([f"- {r}" for r in requirements]) if requirements else "（无）"
  if plan_type is not None and plan_type.strip().lower() not in ("simple", "professional"):
    plan_type = "simple"
  if sub_type is not None and isinstance(sub_type, str):
    sub_type = sub_type.strip().lower() or None
  else:
    sub_type = None

  if not use_llm:
    # 无 LLM 时返回单任务占位，仅写入目标说明
    return [
      {
        "name": "目标与方案",
        "description": "生成文件：positioning.md",
        "acceptance_criteria": f"在 outputs/plans/{plan_id}/positioning.md 生成非空文件。",
        "status": "pending",
        "depends_on": [],
        "scheduled_at": None,
        "executor_type": "file",
        "executor_args": {
          "output_relpath": "positioning.md",
          "content": f"# 用户目标\n\n{objective}\n\n# 用户要求\n{req_text}\n",
        },
        "idempotency_key": "positioning.md",
        "max_retries": 1,
      },
    ]

  try:
    raw_tasks = await _plan_tasks_with_llm(
      plan_id, objective, req_text, model_name,
      plan_type=plan_type, sub_type=sub_type,
    )
  except Exception as e:
    logger.exception("LLM 任务规划失败，使用最小占位任务: %s", e)
    return [
      {
        "name": "目标与方案",
        "description": "生成文件：positioning.md",
        "acceptance_criteria": f"在 outputs/plans/{plan_id}/positioning.md 生成非空文件。",
        "status": "pending",
        "depends_on": [],
        "scheduled_at": None,
        "executor_type": "llm",
        "executor_args": {
          "model": model_name,
          "output_relpath": "positioning.md",
          "prompt": f"你是一名资深策划。用户目标：{objective}\n\n用户要求：{req_text}\n\n请输出一份可直接执行的定位与方案文档，包含：平台与受众、人设与卖点、栏目结构、更新频率与 1 周内容排期。要求中文、结构清晰、具体可执行。不要假设具体领域，严格围绕用户目标写。",
          "executor_prompt_set": "simple",
        },
        "idempotency_key": "positioning.md",
        "max_retries": 1,
      },
    ]

  tasks = [
    _task_spec_to_full_task(plan_id, t, use_llm=True, model_name=model_name, plan_type=plan_type, sub_type=sub_type)
    for t in raw_tasks
    if isinstance(t, dict) and (t.get("output_relpath") or t.get("prompt"))
  ]
  if not tasks:
    # 解析结果为空时仍给一个占位
    tasks = [
      _task_spec_to_full_task(
        plan_id,
        {
          "name": "目标与方案",
          "output_relpath": "positioning.md",
          "prompt": f"根据用户目标输出定位与方案。用户目标：{objective}\n用户要求：{req_text}",
          "depends_on": [],
        },
        use_llm=True,
        model_name=model_name,
        plan_type=plan_type,
        sub_type=sub_type,
      ),
    ]
  return tasks


def make_ready_status(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """将无依赖的任务标为 ready，其余保持 pending。"""
  for t in tasks:
    deps = t.get("depends_on") or []
    if not deps:
      t["status"] = "ready"
  return tasks
