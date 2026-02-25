"""
反馈数据收集器

目的：
    收集用户对推荐结果的反馈，包括采纳、修改、拒绝等。
"""

import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class FeedbackAction(Enum):
    """用户反馈动作类型"""
    ACCEPTED = "accepted"      # 接受推荐
    MODIFIED = "modified"      # 修改后采纳
    REJECTED = "rejected"      # 拒绝推荐
    PENDING = "pending"        # 等待反馈


@dataclass
class RecommendationRecord:
    """单个元素的推荐记录"""
    element: str
    recommended: str                    # 推荐的赝势
    sources: list[dict]                 # 各数据源的建议
    confidence: float = 0.0             # 推荐置信度
    user_choice: Optional[str] = None   # 用户最终选择
    action: str = "pending"             # 用户动作
    reason: Optional[str] = None        # 用户提供的原因


@dataclass
class FeedbackSession:
    """反馈会话"""
    session_id: str
    created_at: str
    poscar_info: dict
    recommendations: dict = field(default_factory=dict)  # element -> RecommendationRecord
    completed: bool = False
    completed_at: Optional[str] = None


class FeedbackCollector:
    """
    反馈收集器

    职责：
        1. 记录每次推荐的完整信息（输入、各数据源建议、最终推荐）
        2. 捕获用户的实际选择（采纳/修改/拒绝）
        3. 计算推荐准确率
        4. 标记需要人工审核的案例
    """

    DEFAULT_FEEDBACK_DIR = ".vasp_potcar_feedback"

    def __init__(self, feedback_dir: Optional[str] = None):
        """
        初始化反馈收集器

        Args:
            feedback_dir: 反馈数据存储目录
        """
        if feedback_dir:
            self.feedback_dir = Path(feedback_dir)
        else:
            home = Path.home()
            self.feedback_dir = home / self.DEFAULT_FEEDBACK_DIR

        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self._active_sessions = {}

    def start_session(self, poscar_info: dict) -> str:
        """
        开始一次推荐会话

        Args:
            poscar_info: POSCAR解析结果，包含元素、化学式等

        Returns:
            session_id: 会话ID
        """
        session_id = str(uuid.uuid4())[:8]

        session = FeedbackSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            poscar_info=poscar_info
        )

        self._active_sessions[session_id] = session
        logger.info(f"Started feedback session: {session_id}")

        return session_id

    def record_recommendation(
        self,
        session_id: str,
        element: str,
        recommended: str,
        sources: list[dict],
        confidence: float = 0.0
    ):
        """
        记录推荐结果

        Args:
            session_id: 会话ID
            element: 元素符号
            recommended: 推荐的赝势
            sources: 各数据源的建议列表
            confidence: 推荐置信度
        """
        session = self._active_sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            return

        record = RecommendationRecord(
            element=element,
            recommended=recommended,
            sources=sources,
            confidence=confidence
        )

        session.recommendations[element] = record
        logger.debug(f"Recorded recommendation for {element}: {recommended}")

    def record_user_choice(
        self,
        session_id: str,
        element: str,
        chosen: str,
        reason: str = None
    ):
        """
        记录用户最终选择

        Args:
            session_id: 会话ID
            element: 元素符号
            chosen: 用户选择的赝势
            reason: 选择原因（可选）
        """
        session = self._active_sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            return

        record = session.recommendations.get(element)
        if not record:
            logger.warning(f"No recommendation record for {element}")
            return

        record.user_choice = chosen
        record.reason = reason

        # 判断动作类型
        if chosen == record.recommended:
            record.action = FeedbackAction.ACCEPTED.value
        elif chosen:
            record.action = FeedbackAction.MODIFIED.value
        else:
            record.action = FeedbackAction.REJECTED.value

        logger.info(f"User {record.action} recommendation for {element}: {chosen}")

    def complete_session(self, session_id: str) -> dict:
        """
        完成会话并保存

        Args:
            session_id: 会话ID

        Returns:
            会话摘要
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return {"error": f"Session {session_id} not found"}

        session.completed = True
        session.completed_at = datetime.now().isoformat()

        # 保存到文件
        self._save_session(session)

        # 生成摘要
        summary = self._generate_session_summary(session)

        # 从活动会话中移除
        del self._active_sessions[session_id]

        return summary

    def _save_session(self, session: FeedbackSession):
        """保存会话到文件"""
        # 按日期组织目录
        date_str = datetime.now().strftime("%Y-%m")
        month_dir = self.feedback_dir / date_str
        month_dir.mkdir(exist_ok=True)

        # 转换为可序列化的格式
        session_data = {
            "session_id": session.session_id,
            "created_at": session.created_at,
            "completed_at": session.completed_at,
            "poscar_info": session.poscar_info,
            "recommendations": {
                element: asdict(record)
                for element, record in session.recommendations.items()
            }
        }

        file_path = month_dir / f"{session.session_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved session to {file_path}")

    def _generate_session_summary(self, session: FeedbackSession) -> dict:
        """生成会话摘要"""
        total = len(session.recommendations)
        accepted = sum(1 for r in session.recommendations.values()
                       if r.action == FeedbackAction.ACCEPTED.value)
        modified = sum(1 for r in session.recommendations.values()
                       if r.action == FeedbackAction.MODIFIED.value)
        rejected = sum(1 for r in session.recommendations.values()
                       if r.action == FeedbackAction.REJECTED.value)

        accuracy = accepted / total if total > 0 else 0

        return {
            "session_id": session.session_id,
            "formula": session.poscar_info.get("formula", "unknown"),
            "total_elements": total,
            "accepted": accepted,
            "modified": modified,
            "rejected": rejected,
            "accuracy": round(accuracy, 2),
            "modifications": [
                {
                    "element": r.element,
                    "recommended": r.recommended,
                    "chosen": r.user_choice,
                    "reason": r.reason
                }
                for r in session.recommendations.values()
                if r.action == FeedbackAction.MODIFIED.value
            ]
        }

    def get_accuracy_stats(self, days: int = 30) -> dict:
        """
        获取推荐准确率统计

        Args:
            days: 统计最近N天的数据

        Returns:
            统计结果
        """
        from datetime import timedelta

        cutoff_date = datetime.now() - timedelta(days=days)
        sessions = self._load_recent_sessions(cutoff_date)

        if not sessions:
            return {
                "period_days": days,
                "total_sessions": 0,
                "message": "No feedback data available"
            }

        total_recommendations = 0
        total_accepted = 0
        total_modified = 0
        total_rejected = 0

        element_stats = {}
        source_stats = {}

        for session in sessions:
            for element, rec in session.get("recommendations", {}).items():
                total_recommendations += 1

                action = rec.get("action", "pending")
                if action == "accepted":
                    total_accepted += 1
                elif action == "modified":
                    total_modified += 1
                elif action == "rejected":
                    total_rejected += 1

                # 按元素统计
                if element not in element_stats:
                    element_stats[element] = {"total": 0, "accepted": 0}
                element_stats[element]["total"] += 1
                if action == "accepted":
                    element_stats[element]["accepted"] += 1

                # 按数据源统计
                for source in rec.get("sources", []):
                    source_name = source.get("source", "unknown")
                    if source_name not in source_stats:
                        source_stats[source_name] = {"total": 0, "accepted": 0}
                    source_stats[source_name]["total"] += 1
                    if action == "accepted" and source.get("potcar") == rec.get("recommended"):
                        source_stats[source_name]["accepted"] += 1

        overall_accuracy = total_accepted / total_recommendations if total_recommendations > 0 else 0

        # 计算各元素准确率
        element_accuracy = {
            el: round(stats["accepted"] / stats["total"], 2) if stats["total"] > 0 else 0
            for el, stats in element_stats.items()
        }

        # 找出准确率最低的元素（需要改进）
        needs_improvement = [
            el for el, acc in element_accuracy.items()
            if acc < 0.7 and element_stats[el]["total"] >= 3
        ]

        return {
            "period_days": days,
            "total_sessions": len(sessions),
            "total_recommendations": total_recommendations,
            "accepted": total_accepted,
            "modified": total_modified,
            "rejected": total_rejected,
            "overall_accuracy": round(overall_accuracy, 3),
            "element_accuracy": element_accuracy,
            "needs_improvement": needs_improvement,
            "source_performance": {
                name: round(stats["accepted"] / stats["total"], 2) if stats["total"] > 0 else 0
                for name, stats in source_stats.items()
            }
        }

    def _load_recent_sessions(self, cutoff_date: datetime) -> list[dict]:
        """加载最近的会话数据"""
        sessions = []

        if not self.feedback_dir.exists():
            return sessions

        for month_dir in self.feedback_dir.iterdir():
            if not month_dir.is_dir():
                continue

            for session_file in month_dir.glob("*.json"):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session = json.load(f)

                    created_at = datetime.fromisoformat(session.get("created_at", ""))
                    if created_at >= cutoff_date:
                        sessions.append(session)

                except Exception as e:
                    logger.warning(f"Failed to load session {session_file}: {e}")

        return sessions

    def get_needs_review(self) -> list[dict]:
        """
        获取需要人工审核的案例

        返回被用户修改或拒绝的推荐，用于改进规则
        """
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=90)
        sessions = self._load_recent_sessions(cutoff_date)

        needs_review = []

        for session in sessions:
            for element, rec in session.get("recommendations", {}).items():
                action = rec.get("action", "pending")
                if action in ["modified", "rejected"]:
                    needs_review.append({
                        "session_id": session.get("session_id"),
                        "formula": session.get("poscar_info", {}).get("formula"),
                        "element": element,
                        "recommended": rec.get("recommended"),
                        "user_choice": rec.get("user_choice"),
                        "reason": rec.get("reason"),
                        "action": action,
                        "sources": rec.get("sources", [])
                    })

        return needs_review
