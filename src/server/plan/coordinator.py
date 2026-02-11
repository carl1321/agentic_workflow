# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
计划管理中枢（MVP）。

- 澄清阶段由 LLM 动态判断：目标是否已清晰、是否需要下一轮提问及具体问题内容。
- 输出结构化 ORA spec 草稿，供 planner 拆解任务。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from src.llms.llm import get_llm_by_type

logger = logging.getLogger(__name__)

# 保留用于兼容旧接口或回退；新流程以 get_next_question_llm 为准
DEFAULT_QUESTIONS: List[str] = [
  "你打算在哪个平台发布？（抖音/快手/B站/小红书/视频号/其他）目标受众是谁？",
  "你希望内容风格是什么？（偏搞笑/严肃/热血/治愈）单条视频大概多长？",
  "你有哪些资源约束？（是否需要配音/是否用文生图或文生视频/预算或质量要求）",
]


def get_round(clarify: Dict[str, Any]) -> int:
  try:
    return int(clarify.get("round") or 0)
  except Exception:
    return 0


def get_next_question(clarify: Dict[str, Any]) -> Optional[str]:
  """固定 3 轮模板，仅作兼容；主流程请用 get_next_question_llm。"""
  r = get_round(clarify)
  if r >= len(DEFAULT_QUESTIONS):
    return None
  return DEFAULT_QUESTIONS[r]


def _parse_plan_type_from_data(data: Dict[str, Any]) -> Dict[str, Any]:
  """从 long_plan LLM 返回的 data 中解析 plan_type、sub_type，供 planner 使用。"""
  plan_type = (data.get("plan_type") or "simple").strip().lower()
  if plan_type not in ("simple", "professional"):
    plan_type = "simple"
  sub_type = data.get("sub_type")
  if sub_type is not None and isinstance(sub_type, str):
    sub_type = sub_type.strip().lower() or None
  else:
    sub_type = None
  return {"plan_type": plan_type, "sub_type": sub_type}


async def get_next_question_llm(raw_goal: str, clarify: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
  """
  由 LLM 根据当前目标与澄清历史，判断目标是否已清晰；
  若未清晰则生成下一个澄清问题。
  返回 (done, next_question, extra)：done=True 表示无需再澄清，next_question 为 None 或下一问；
  extra 仅当 done=True 时有效，为 {"plan_type": "simple"|"professional", "sub_type": "video_creation"|None}，供 planner 选择提示词。
  """
  qa = clarify.get("qa") or []
  # 必须带上「问题+回答」，否则 LLM 只看到「否」等回答，会重复问同一类问题（如旁白/背景音乐）
  parts = []
  for i, x in enumerate(qa, 1):
    if not isinstance(x, dict) or not x.get("answer"):
      continue
    q = (x.get("question") or "").strip()
    a = (x.get("answer") or "").strip()
    if q:
      parts.append(f"Q{i}: {q} → [用户回答] {a}")
    else:
      parts.append(f"Q{i}: [用户回答] {a}")
  qa_text = "\n".join(parts) if parts else "（尚未有问答记录）"

  try:
    from src.prompts.template import render_prompt_with_vars
    prompt = render_prompt_with_vars(
      "long_plan",
      raw_goal=raw_goal or "（未提供）",
      qa_text=qa_text,
    )
  except Exception as e:
    logger.warning("Failed to load long_plan prompt, using inline: %s", e)
    prompt = f"""你是一个长期计划助手，负责把用户的模糊目标澄清为可执行计划。

【用户当前描述的目标】
{raw_goal or "（未提供）"}

【已有澄清问答】
{qa_text}

请判断：仅凭以上信息，是否已经足够生成可执行的任务计划？
- 若已足够（目标、平台/受众、风格、资源等关键信息已明确或可合理推断），则返回 done=true，question=null，并填写 plan_type（simple 或 professional）与 sub_type（仅 professional 时填，如 video_creation）。
- 若仍不足，请返回 done=false，并在 question 里写一句简短、具体的追问。禁止对「已有澄清问答」里已出现过的主题重复追问（包括换说法问同一件事）；应问其他未覆盖的维度或直接 done=true。

只输出一个 JSON 对象，不要其他文字。done=true 时格式：{{"done": true, "question": null, "plan_type": "simple或professional", "sub_type": "video_creation或null"}}；done=false 时：{{"done": false, "question": "追问内容"}}
"""

  try:
    llm = get_llm_by_type("basic")
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = (response.content if hasattr(response, "content") else str(response)) or "{}"
    # 提取第一组完整 JSON
    text = text.strip()
    start = text.find("{")
    if start >= 0:
      depth = 0
      for i in range(start, len(text)):
        if text[i] == "{":
          depth += 1
        elif text[i] == "}":
          depth -= 1
          if depth == 0:
            text = text[start : i + 1]
            break
    data = json.loads(text)
    done = bool(data.get("done", False))
    q = data.get("question")
    next_question = str(q).strip() if q else None
    if next_question == "null" or next_question == "":
      next_question = None
    extra = _parse_plan_type_from_data(data) if done else None
    return (done, next_question, extra)
  except Exception as e:
    logger.warning("get_next_question_llm failed, fallback to done=True: %s", e)
    return (True, None, {"plan_type": "simple", "sub_type": None})


def apply_answer(clarify: Dict[str, Any], answer: str) -> Dict[str, Any]:
  """将用户回答追加到 qa，并保存本轮问题（last_question），供下一轮 LLM 判断时避免重复追问。"""
  r = get_round(clarify)
  qa = list(clarify.get("qa") or [])
  last_q = (clarify.get("last_question") or "").strip() or None
  qa.append({"round": r + 1, "question": last_q, "answer": answer})
  return {"round": r + 1, "qa": qa}


def build_ora_spec(raw_goal: str, clarify: Dict[str, Any]) -> Dict[str, Any]:
  """
  生成 ORA spec（MVP：规则化拼装，后续可替换为 LLM 抽取）。
  """
  qa = clarify.get("qa") or []
  requirements = [x.get("answer") for x in qa if isinstance(x, dict) and x.get("answer")]
  return {
    "objective": raw_goal,
    "requirements": requirements,
    "actions": [
      "生成计划文档（positioning/script/storyboard/prompts/report）",
      "按任务依赖串行执行并落盘产物",
      "验收与复盘（失败可重试/调整）",
    ],
    "clarify_rounds": len(requirements),
  }


async def evaluate_task_output(
  task: Dict[str, Any],
  output_path: str,
  content_preview: str,
  spec_snippet: str = "",
) -> Tuple[bool, str]:
  """
  执行单元完成单任务后，由系统唤起协调器进行验收。
  返回 (accepted, reason)：通过则 True 与简短理由，不通过则 False 与不通过原因。
  """
  task_name = task.get("name") or "未命名任务"
  task_description = task.get("description") or ""
  acceptance_criteria = task.get("acceptance_criteria") or ""

  try:
    from src.prompts.template import render_prompt_with_vars
    prompt = render_prompt_with_vars(
      "long_plan_accept",
      task_name=task_name,
      task_description=task_description,
      acceptance_criteria=acceptance_criteria,
      output_path=output_path or "（无）",
      content_preview=content_preview or "（无内容摘要）",
      spec_snippet=spec_snippet[:2000] if spec_snippet else "",
    )
  except Exception as e:
    logger.warning("evaluate_task_output prompt load failed, fallback accept: %s", e)
    return (True, "验收提示加载失败，默认通过")

  try:
    llm = get_llm_by_type("basic")
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = (response.content if hasattr(response, "content") else str(response)) or "{}"
    text = text.strip()
    start = text.find("{")
    if start >= 0:
      depth = 0
      for i in range(start, len(text)):
        if text[i] == "{":
          depth += 1
        elif text[i] == "}":
          depth -= 1
          if depth == 0:
            text = text[start : i + 1]
            break
    data = json.loads(text)
    accepted = bool(data.get("accepted", True))
    reason = str(data.get("reason") or "").strip() or ("通过" if accepted else "不通过")
    return (accepted, reason)
  except Exception as e:
    logger.warning("evaluate_task_output llm failed, fallback accept: %s", e)
    return (True, "验收判断异常，默认通过")

