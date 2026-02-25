"""
冲突解决器

目的：
    当多个数据源给出不同建议时，提供解决策略。
"""

from typing import Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ConflictStrategy(Enum):
    """冲突解决策略"""
    HIGHEST_WEIGHT = "highest_weight"      # 选择权重最高的
    CONSENSUS = "consensus"                 # 多数一致则采纳
    CONSERVATIVE = "conservative"           # 选择更保守（精度更高）的选项
    ASK_USER = "ask_user"                   # 无法自动决策时询问用户


@dataclass
class ConflictResult:
    """冲突解决结果"""
    resolved: bool                  # 是否成功解决
    chosen: Optional[str]           # 选择的赝势
    strategy_used: str              # 使用的策略
    reason: str                     # 选择原因
    alternatives: list[dict]        # 其他备选项
    needs_user_input: bool = False  # 是否需要用户输入


# 赝势精度等级（用于CONSERVATIVE策略）
# 数值越高表示包含更多价电子，精度越高
POTCAR_PRECISION_RANK = {
    # 标准版本
    "": 1,
    # 软赝势
    "_s": 0,
    # 包含d电子
    "_d": 2,
    # 包含pv半芯态
    "_pv": 3,
    # 包含sv半芯态
    "_sv": 4,
    # GW计算专用
    "_GW": 5,
}


class ConflictResolver:
    """
    冲突解决策略

    策略类型：
        1. HIGHEST_WEIGHT: 选择权重最高的
        2. CONSENSUS: 多数一致则采纳
        3. CONSERVATIVE: 选择更保守（精度更高）的选项
        4. ASK_USER: 无法自动决策时询问用户
    """

    def __init__(self, default_strategy: str = "HIGHEST_WEIGHT"):
        """
        初始化冲突解决器

        Args:
            default_strategy: 默认的冲突解决策略
        """
        self.default_strategy = default_strategy

    def resolve(
        self,
        conflicts: list[dict],
        strategy: str = None
    ) -> ConflictResult:
        """
        解决冲突，返回最终选择

        Args:
            conflicts: 冲突的候选项列表，每个项包含：
                - potcar: 赝势名称（如 "Li_sv"）
                - source: 数据来源
                - weight: 来源权重
                - confidence: 置信度
                - reason: 推荐原因
            strategy: 使用的策略，默认使用初始化时的策略

        Returns:
            ConflictResult: 解决结果
        """
        if not conflicts:
            return ConflictResult(
                resolved=False,
                chosen=None,
                strategy_used="none",
                reason="No candidates provided",
                alternatives=[]
            )

        if len(conflicts) == 1:
            return ConflictResult(
                resolved=True,
                chosen=conflicts[0].get("potcar"),
                strategy_used="single_candidate",
                reason="Only one candidate available",
                alternatives=[]
            )

        # 如果没有冲突，直接返回
        if not self.detect_conflict(conflicts):
            best = max(conflicts, key=lambda x: x.get("weight", 0) * x.get("confidence", 1))
            return ConflictResult(
                resolved=True,
                chosen=best.get("potcar"),
                strategy_used="no_conflict",
                reason="All sources agree on the same choice",
                alternatives=[]
            )

        strategy = strategy or self.default_strategy
        strategy = strategy.upper()

        if strategy == "HIGHEST_WEIGHT":
            return self._resolve_by_weight(conflicts)
        elif strategy == "CONSENSUS":
            return self._resolve_by_consensus(conflicts)
        elif strategy == "CONSERVATIVE":
            return self._resolve_by_precision(conflicts)
        elif strategy == "ASK_USER":
            return self._defer_to_user(conflicts)
        else:
            logger.warning(f"Unknown strategy '{strategy}', falling back to HIGHEST_WEIGHT")
            return self._resolve_by_weight(conflicts)

    def detect_conflict(self, candidates: list[dict]) -> bool:
        """
        检测是否存在冲突

        Args:
            candidates: 候选项列表

        Returns:
            bool: 是否存在不同的推荐
        """
        if len(candidates) <= 1:
            return False

        potcars = set()
        for c in candidates:
            potcar = c.get("potcar")
            if potcar:
                # 规范化赝势名称进行比较
                potcars.add(self._normalize_potcar_name(potcar))

        return len(potcars) > 1

    def _normalize_potcar_name(self, potcar: str) -> str:
        """规范化赝势名称"""
        return potcar.strip().replace(" ", "_")

    def _resolve_by_weight(self, conflicts: list[dict]) -> ConflictResult:
        """按权重解决：选择加权得分最高的"""
        scored = []
        for c in conflicts:
            weight = c.get("weight", 1.0)
            confidence = c.get("confidence", 1.0)
            score = weight * confidence
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]

        alternatives = [
            {
                "potcar": c.get("potcar"),
                "source": c.get("source"),
                "score": s
            }
            for s, c in scored[1:]
        ]

        return ConflictResult(
            resolved=True,
            chosen=best.get("potcar"),
            strategy_used="HIGHEST_WEIGHT",
            reason=f"Selected based on highest weighted score from {best.get('source')}",
            alternatives=alternatives
        )

    def _resolve_by_consensus(self, conflicts: list[dict]) -> ConflictResult:
        """按共识解决：多数一致则采纳"""
        # 统计每个赝势的支持数和总权重
        votes = {}
        for c in conflicts:
            potcar = self._normalize_potcar_name(c.get("potcar", ""))
            if potcar not in votes:
                votes[potcar] = {"count": 0, "total_weight": 0, "sources": [], "original": c.get("potcar")}
            votes[potcar]["count"] += 1
            votes[potcar]["total_weight"] += c.get("weight", 1.0)
            votes[potcar]["sources"].append(c.get("source"))

        # 找出得票最多的
        sorted_votes = sorted(
            votes.items(),
            key=lambda x: (x[1]["count"], x[1]["total_weight"]),
            reverse=True
        )

        top_potcar, top_info = sorted_votes[0]
        total_sources = len(conflicts)

        # 如果有多数支持（超过50%），则采纳
        if top_info["count"] > total_sources / 2:
            alternatives = [
                {"potcar": info["original"], "votes": info["count"], "sources": info["sources"]}
                for p, info in sorted_votes[1:]
            ]
            return ConflictResult(
                resolved=True,
                chosen=top_info["original"],
                strategy_used="CONSENSUS",
                reason=f"Majority consensus ({top_info['count']}/{total_sources} sources)",
                alternatives=alternatives
            )

        # 无法达成共识，回退到权重策略
        logger.info("No consensus reached, falling back to weight-based resolution")
        return self._resolve_by_weight(conflicts)

    def _resolve_by_precision(self, conflicts: list[dict]) -> ConflictResult:
        """按精度解决：选择更保守（精度更高）的选项"""
        ranked = []
        for c in conflicts:
            potcar = c.get("potcar", "")
            precision = self._get_precision_rank(potcar)
            ranked.append((precision, c))

        ranked.sort(key=lambda x: x[0], reverse=True)
        best = ranked[0][1]

        alternatives = [
            {
                "potcar": c.get("potcar"),
                "source": c.get("source"),
                "precision_rank": r
            }
            for r, c in ranked[1:]
        ]

        return ConflictResult(
            resolved=True,
            chosen=best.get("potcar"),
            strategy_used="CONSERVATIVE",
            reason=f"Selected higher precision variant with more valence electrons",
            alternatives=alternatives
        )

    def _get_precision_rank(self, potcar: str) -> int:
        """获取赝势的精度等级"""
        # 提取后缀
        for suffix, rank in sorted(POTCAR_PRECISION_RANK.items(), key=lambda x: -len(x[0])):
            if suffix and potcar.endswith(suffix):
                return rank
        return POTCAR_PRECISION_RANK.get("", 1)

    def _defer_to_user(self, conflicts: list[dict]) -> ConflictResult:
        """需要用户决策"""
        options = [
            {
                "potcar": c.get("potcar"),
                "source": c.get("source"),
                "reason": c.get("reason", "No reason provided"),
                "weight": c.get("weight", 1.0),
                "confidence": c.get("confidence", 1.0)
            }
            for c in conflicts
        ]

        return ConflictResult(
            resolved=False,
            chosen=None,
            strategy_used="ASK_USER",
            reason="Multiple conflicting recommendations require user decision",
            alternatives=options,
            needs_user_input=True
        )

    def get_conflict_summary(self, conflicts: list[dict]) -> dict:
        """
        生成冲突摘要信息

        Args:
            conflicts: 冲突的候选项列表

        Returns:
            包含冲突分析的字典
        """
        if not conflicts:
            return {"has_conflict": False, "message": "No candidates"}

        if not self.detect_conflict(conflicts):
            return {
                "has_conflict": False,
                "message": "All sources agree",
                "recommendation": conflicts[0].get("potcar")
            }

        # 分析冲突
        sources_by_potcar = {}
        for c in conflicts:
            potcar = c.get("potcar", "")
            if potcar not in sources_by_potcar:
                sources_by_potcar[potcar] = []
            sources_by_potcar[potcar].append(c.get("source"))

        return {
            "has_conflict": True,
            "message": f"Found {len(sources_by_potcar)} different recommendations",
            "options": sources_by_potcar,
            "recommended_strategy": self._recommend_strategy(conflicts)
        }

    def _recommend_strategy(self, conflicts: list[dict]) -> str:
        """根据冲突情况推荐解决策略"""
        # 如果有明显的权重差异，使用权重策略
        weights = [c.get("weight", 1.0) for c in conflicts]
        if max(weights) > 2 * min(weights):
            return "HIGHEST_WEIGHT"

        # 如果选项差异是精度相关的，使用保守策略
        potcars = [c.get("potcar", "") for c in conflicts]
        if self._is_precision_difference(potcars):
            return "CONSERVATIVE"

        # 默认使用共识策略
        return "CONSENSUS"

    def _is_precision_difference(self, potcars: list[str]) -> bool:
        """检测是否是精度等级差异"""
        # 提取元素基础名称
        bases = set()
        for p in potcars:
            # 移除后缀，获取基础元素名
            base = p
            for suffix in ["_sv", "_pv", "_d", "_s", "_GW"]:
                if p.endswith(suffix):
                    base = p[:-len(suffix)]
                    break
            bases.add(base)

        # 如果基础名称相同，说明是同一元素的不同精度版本
        return len(bases) == 1
