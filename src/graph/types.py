# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


from langgraph.graph import MessagesState

from src.prompts.planner_model import Plan
from src.rag import Resource


class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""

    # Runtime Variables
    locale: str = "en-US"
    research_topic: str = ""
    observations: list[str] = []
    resources: list[Resource] = []
    plan_iterations: int = 0
    current_plan: Plan | str = None
    final_report: str = ""
    auto_accepted_plan: bool = False
    enable_background_investigation: bool = False
    background_investigation_results: str = None

    # Clarification state tracking (disabled by default)
    enable_clarification: bool = (
        False  # Enable/disable clarification feature (default: False)
    )
    clarification_rounds: int = 0
    clarification_history: list[str] = []
    is_clarification_complete: bool = False
    clarified_question: str = ""
    max_clarification_rounds: int = (
        3  # Default: 3 rounds (only used when enable_clarification=True)
    )

    # Deep Research Mode state tracking
    research_mode: str = "standard"  # "standard" | "deep_research"
    current_research_iteration: int = 0
    progressive_report: str = ""  # Progressive knowledge synthesis
    research_metadata: dict = {}  # Iteration metadata (tools used, etc.)

    # Workflow control
    goto: str = "planner"  # Default next node

    # VASP 组合步：组合执行完后由 LLM 参与总结，需持久化避免重复提交
    vasp_post_composite: bool = False  # 刚跑完组合步，待 executor 总结
    vasp_composite_result: str = None  # 组合步结果 JSON，供 executor 写入 execution_res
    vasp_gen_display: str = None  # 生成输入文件的 display 文本（文件列表+内容+检查项），写入 step2 execution_res 供展示
    # 提交成功后写入，供 composite_band 轮询与下载使用（避免从 execution_res 解析失败导致跳过轮询）
    vasp_submit_job_id: str = None
    vasp_submit_remote_dir: str = None
    vasp_submit_host: str = None
    vasp_submit_username: str = None
    vasp_submit_port: int = 22
    vasp_submit_key_path: str = None
    # 第 3 步（wait_and_download_band）下载的 vasprun/kpoints 内容，避免写入 execution_res 导致上下文过大；第 4 步画图时从 state 注入
    vasp_vasprun_xml_content: str = None
    vasp_kpoints_content: str = None

    # Molecular images storage (to avoid token waste)
    molecular_images: list[dict] = []  # Store molecular structure images