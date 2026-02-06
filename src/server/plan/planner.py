# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
任务拆解（MVP）。

策略：
- MVP 阶段先用“模板化任务列表”跑通闭环（修仙动画账号示例）。
- 每个 task 都包含：描述、验收标准、依赖、执行器类型与参数、幂等 key。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def build_tasks_for_xianxia_animation_account(
  plan_id: str,
  ora_spec: Dict[str, Any],
  *,
  use_llm: bool = True,
  model_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
  """
  根据 ORA spec 构建一组最小任务。

  - use_llm=True 时：用 llm 生成内容并写入 outputs 文件
  - use_llm=False 时：写入带占位符的文件（仍可交付）
  """

  objective = ora_spec.get("objective") or ""
  requirements = ora_spec.get("requirements") or []
  req_text = "\n".join([f"- {r}" for r in requirements]) if requirements else "- （无）"

  def llm_task(name: str, output_rel: str, prompt: str, depends_on: Optional[List[str]] = None):
    return {
      "name": name,
      "description": f"生成文件：{output_rel}",
      "acceptance_criteria": f"在 outputs/plans/{plan_id}/{output_rel} 生成非空文件，内容满足任务要求。",
      "status": "pending",
      "depends_on": depends_on or [],
      "scheduled_at": None,
      "executor_type": "llm" if use_llm else "file",
      "executor_args": (
        {
          "model": model_name,
          "output_relpath": output_rel,
          "prompt": prompt,
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

  tasks: List[Dict[str, Any]] = []

  tasks.append(
    llm_task(
      "账号定位与栏目框架",
      "positioning.md",
      f"""你是一名资深短视频运营策划。\n\n## 用户目标\n{objective}\n\n## 用户要求（澄清结果）\n{req_text}\n\n请输出一份可直接执行的账号定位与栏目框架，包含：\n- 平台与受众画像\n- 账号人设与差异化卖点\n- 栏目结构（至少3个固定栏目）\n- 更新频率与生产流程\n- 1周内容排期（7条标题+一句话梗概）\n\n要求：中文，结构清晰，尽量具体可执行。\n""",
      depends_on=[],
    )
  )

  tasks.append(
    llm_task(
      "第1集 30s 文案与分镜",
      "ep01_script.md",
      f"""基于 outputs/plans/{plan_id}/positioning.md 的定位，为“修仙动画账号”写第1集 30秒短视频。\n\n输出格式：\n1) 旁白/台词（按时间轴分段，标注每段秒数）\n2) 画面分镜（每镜头：镜头号、时长、景别、画面内容、字幕、音效/音乐建议）\n3) 结尾引导关注/评论的 CTA\n\n要求：中文，节奏快，适合竖屏短视频。\n""",
      depends_on=["positioning.md"],
    )
  )

  tasks.append(
    llm_task(
      "第1集 分镜结构化 JSON",
      "ep01_storyboard.json",
      f"""把 outputs/plans/{plan_id}/ep01_script.md 的分镜部分转换为 JSON 数组。\n\nJSON 每项字段：\n- shot: number\n- durationSec: number\n- scene: string\n- camera: string\n- subtitle: string\n- sfx: string\n- prompt: string  （用于文生图/文生视频的英文提示词，尽量包含风格词与主体/动作/镜头）\n\n只输出 JSON（不要 Markdown）。\n""",
      depends_on=["ep01_script.md"],
    )
  )

  tasks.append(
    llm_task(
      "第1集 生成提示词合集",
      "ep01_prompts.md",
      f"""基于 outputs/plans/{plan_id}/ep01_storyboard.json，整理一份可直接用于生成图片/视频的提示词合集。\n\n包含：\n- 全局风格提示词（统一画风）\n- 角色设定提示词（主角/配角）\n- 每个镜头的提示词（shot -> prompt）\n- 负向提示词（避免崩坏）\n- 生成参数建议（分辨率、帧率、时长、seed等，按常识给合理建议）\n\n中文说明 + 英文 prompt。\n""",
      depends_on=["ep01_storyboard.json"],
    )
  )

  tasks.append(
    llm_task(
      "执行报告与复盘",
      "report.md",
      f"""你是项目经理。基于本次计划的产物（positioning、脚本、分镜、提示词），输出一份执行报告与复盘：\n\n- 本次交付清单\n- 风险与假设\n- 下一步迭代计划（至少5条）\n- 成本控制建议（API/生成成本）\n\n要求：中文，条理清晰。\n""",
      depends_on=["positioning.md", "ep01_script.md", "ep01_storyboard.json", "ep01_prompts.md"],
    )
  )

  return tasks


def make_ready_status(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """
  将无依赖的任务标为 ready，其余保持 pending。
  """
  for t in tasks:
    deps = t.get("depends_on") or []
    if not deps:
      t["status"] = "ready"
  return tasks

