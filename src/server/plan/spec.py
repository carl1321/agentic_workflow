# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
计划记忆中枢：spec.txt。

- 计划协调器在关键决策节点（目标对齐、事项分派、验收调整）主动读取。
- 执行单元（Worker）不直接读取，仅依据已拆解的事项描述执行。
- 写入时机：计划创建、澄清完成并分派任务、验收完成（成功/失败）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

SPEC_FILENAME = "spec.txt"


def _spec_root() -> Path:
  return Path(__file__).resolve().parents[3] / "outputs" / "plans"


def get_spec_path(plan_id: UUID) -> Path:
  return _spec_root() / str(plan_id) / SPEC_FILENAME


def read_spec(plan_id: UUID) -> str:
  """计划协调器在决策前读取完整背景、目标、要求与进度。"""
  path = get_spec_path(plan_id)
  if not path.exists():
    return ""
  try:
    return path.read_text(encoding="utf-8")
  except Exception as e:
    logger.warning("read_spec failed for %s: %s", plan_id, e)
    return ""


def write_spec(plan_id: UUID, content: str) -> None:
  path = get_spec_path(plan_id)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content, encoding="utf-8")
  logger.info("spec.txt written: %s", path)


def append_spec_milestone(plan_id: UUID, line: str) -> None:
  """在 spec 的「里程碑与经验」下追加一条记录（用于单任务验收通过/不通过）。"""
  existing = read_spec(plan_id)
  marker = "## 里程碑与经验"
  new_line = f"- {_now()} {line}"
  if not existing or marker not in existing:
    write_spec(plan_id, (existing or "").rstrip() + "\n\n" + marker + "\n" + new_line + "\n")
    return
  parts = existing.split(marker, 1)
  before = parts[0].rstrip()
  after = parts[1]
  rest = after.split("\n## ", 1)
  milestone_block = (rest[0] + "\n" + new_line).strip()
  if len(rest) > 1:
    after_rest = "\n## " + rest[1]
  else:
    after_rest = ""
  write_spec(plan_id, before + "\n\n" + marker + "\n" + milestone_block + after_rest)


def _now() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_spec_content(
  *,
  objective: str = "",
  requirements: Optional[List[str]] = None,
  actions: Optional[List[str]] = None,
  status: str = "draft",
  tasks: Optional[List[Dict[str, Any]]] = None,
  milestones: Optional[List[str]] = None,
) -> str:
  """构建 spec.txt 正文（人类可读，协调器可解析）。"""
  requirements = requirements or []
  actions = actions or []
  tasks = tasks or []
  milestones = milestones or []

  lines = [
    "# 计划规格 (spec)",
    "",
    "> 本文件为计划协调器的记忆中枢。执行单元（Worker）不直接读取，仅依据已拆解的事项描述执行。",
    "",
    "## 目标",
    objective or "（待澄清）",
    "",
    "## 要求（澄清结果）",
  ]
  for r in requirements:
    lines.append(f"- {r}")
  if not requirements:
    lines.append("- （无）")
  lines.extend(["", "## 关键动作"])
  for a in actions:
    lines.append(f"- {a}")
  if not actions:
    lines.append("- （待生成）")
  lines.extend([
    "",
    "## 进度摘要",
    f"- 状态: {status}",
    f"- 已分派任务数: {len(tasks)}",
  ])
  done_count = sum(1 for t in tasks if t.get("status") == "succeeded")
  if tasks:
    lines.append(f"- 已完成: {done_count} / {len(tasks)}")
  lines.extend([
    "",
    "## 已分派任务（供执行单元执行；协调器据此掌握进度）",
    "| 序号 | 名称 | 状态 | 产出/备注 |",
    "| --- | --- | --- | --- |",
  ])
  for i, t in enumerate(tasks, 1):
    name = (t.get("name") or "").replace("|", "\\|")
    st = t.get("status") or "pending"
    key = t.get("idempotency_key") or t.get("executor_args", {}).get("output_relpath") or ""
    lines.append(f"| {i} | {name} | {st} | {key} |")
  lines.extend([
    "",
    "## 里程碑与经验",
  ])
  for m in milestones:
    lines.append(f"- {m}")
  if not milestones:
    lines.append("- （暂无）")
  lines.append("")
  return "\n".join(lines)


def write_spec_initial(plan_id: UUID, raw_goal: str, title: Optional[str] = None) -> None:
  """计划启动时：写入初始 spec（仅目标，待澄清）。"""
  content = build_spec_content(
    objective=raw_goal or "（待用户填写）",
    status="draft",
    milestones=[f"{_now()} 计划创建" + (f"：{title}" if title else "")],
  )
  write_spec(plan_id, content)


def write_spec_after_clarify(
  plan_id: UUID,
  ora_spec: Dict[str, Any],
  tasks: List[Dict[str, Any]],
  tasks_created: int,
) -> None:
  """澄清完成、事项分派后：写入完整 spec（目标、要求、关键动作、已分派任务）。"""
  objective = ora_spec.get("objective") or ""
  requirements = ora_spec.get("requirements") or []
  actions = ora_spec.get("actions") or []
  milestones = [
    f"{_now()} 澄清完成，已分派 {tasks_created} 个任务",
  ]
  content = build_spec_content(
    objective=objective,
    requirements=requirements,
    actions=actions,
    status="running",
    tasks=tasks,
    milestones=milestones,
  )
  write_spec(plan_id, content)


def write_spec_after_outcome(
  plan_id: UUID,
  outcome: str,
  plan: Dict[str, Any],
  tasks: List[Dict[str, Any]],
  extra_lesson: Optional[str] = None,
) -> None:
  """验收完成后：更新里程碑与经验（成功/失败）。outcome 为 'succeeded' 或 'failed'。"""
  existing = read_spec(plan_id)
  ora_spec = plan.get("ora_spec")
  if isinstance(ora_spec, str):
    try:
      import json
      ora_spec = json.loads(ora_spec) if ora_spec else {}
    except Exception:
      ora_spec = {}
  objective = (ora_spec or {}).get("objective") or (plan.get("raw_goal") or "")
  requirements = (ora_spec or {}).get("requirements") or []
  actions = (ora_spec or {}).get("actions") or []
  status = plan.get("status") or outcome

  milestones = []
  if existing and "## 里程碑与经验" in existing:
    try:
      section = existing.split("## 里程碑与经验")[1].split("##")[0].strip()
      for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- ") and line not in milestones:
          milestones.append(line)
    except Exception:
      pass
  if outcome == "succeeded":
    milestones.append(f"{_now()} 计划全部完成。共 {len(tasks)} 个任务均已成功。")
    if extra_lesson:
      milestones.append(f"经验：{extra_lesson}")
  else:
    milestones.append(f"{_now()} 计划执行失败。")
    if extra_lesson:
      milestones.append(f"经验/原因：{extra_lesson}")

  content = build_spec_content(
    objective=objective,
    requirements=requirements,
    actions=actions,
    status=status,
    tasks=tasks,
    milestones=milestones,
  )
  write_spec(plan_id, content)
