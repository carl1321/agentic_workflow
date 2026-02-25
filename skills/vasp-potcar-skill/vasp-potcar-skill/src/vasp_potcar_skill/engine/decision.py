"""
核心决策逻辑

目的：
    综合多个数据源的建议，输出最终的赝势选择决策。
    提供决策过程的完整追溯信息。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Any

from .weights import WeightConfig, CalculationType, CalculationPrecision

logger = logging.getLogger(__name__)


@dataclass
class PotcarCandidate:
    """赝势候选项"""
    symbol: str              # 赝势符号，如 "Fe_pv"
    source: str              # 数据来源
    confidence: float        # 原始置信度
    weighted_score: float = 0.0  # 加权后得分
    reason: str = ""         # 推荐理由


@dataclass
class ElementDecision:
    """单个元素的决策结果"""
    element: str
    selected: str            # 选中的赝势符号
    confidence: float        # 最终置信度
    candidates: list[PotcarCandidate] = field(default_factory=list)
    sources_agree: list[str] = field(default_factory=list)  # 同意该选择的数据源
    sources_disagree: list[str] = field(default_factory=list)  # 有不同建议的数据源
    reasoning: str = ""      # 决策理由


@dataclass
class DecisionResult:
    """完整的决策结果"""
    elements: list[str]
    decisions: dict[str, ElementDecision]
    potcar_symbols: list[str]  # 按元素顺序的赝势符号列表
    calc_type: str
    precision: str
    overall_confidence: float
    summary: str


class DecisionEngine:
    """
    决策引擎

    职责：
        1. 接收多个数据源的建议
        2. 根据权重计算综合得分
        3. 处理冲突情况
        4. 输出决策结果和解释
    """

    def __init__(
        self,
        calc_type: str = "standard",
        precision: str = "medium"
    ):
        """
        初始化决策引擎

        Args:
            calc_type: 计算类型
            precision: 计算精度
        """
        self.weight_config = WeightConfig.from_string(calc_type, precision)
        self.calc_type = calc_type
        self.precision = precision

    def decide(
        self,
        element: str,
        candidates: list[dict],
        context: dict = None
    ) -> ElementDecision:
        """
        为单个元素做出赝势选择决策

        Args:
            element: 元素符号
            candidates: 各数据源的建议列表，每个包含:
                - symbol: 赝势符号
                - source: 数据来源 (knowledge_base, api_mp, pymatgen, mongodb)
                - confidence: 置信度 (0-1)
                - reason: 推荐理由（可选）
            context: 上下文信息（可选）

        Returns:
            ElementDecision: 决策结果
        """
        if not candidates:
            # 无候选项，返回默认值
            return ElementDecision(
                element=element,
                selected=element,
                confidence=0.5,
                reasoning=f"No recommendations found, using default: {element}"
            )

        # 转换为 PotcarCandidate 并计算加权得分
        potcar_candidates = []
        for c in candidates:
            source = c.get("source", "unknown")
            weight = self.weight_config.get_weight(source, c.get("match_quality", 1.0))
            weighted_score = c.get("confidence", 0.5) * weight

            candidate = PotcarCandidate(
                symbol=c.get("symbol", element),
                source=source,
                confidence=c.get("confidence", 0.5),
                weighted_score=weighted_score,
                reason=c.get("reason", "")
            )
            potcar_candidates.append(candidate)

        # 按加权得分排序
        potcar_candidates.sort(key=lambda x: x.weighted_score, reverse=True)

        # 选择得分最高的
        best = potcar_candidates[0]

        # 统计同意/不同意的数据源
        agree = [c.source for c in potcar_candidates if c.symbol == best.symbol]
        disagree = [c.source for c in potcar_candidates if c.symbol != best.symbol]

        # 计算最终置信度
        # 如果多个数据源同意，增加置信度
        final_confidence = best.weighted_score
        if len(agree) > 1:
            final_confidence = min(final_confidence * 1.2, 1.0)
        if len(disagree) > 0:
            final_confidence = max(final_confidence * 0.9, 0.3)

        # 生成决策理由
        reasoning = self._generate_reasoning(element, best, potcar_candidates, agree, disagree)

        return ElementDecision(
            element=element,
            selected=best.symbol,
            confidence=final_confidence,
            candidates=potcar_candidates,
            sources_agree=agree,
            sources_disagree=disagree,
            reasoning=reasoning
        )

    def decide_batch(
        self,
        elements: list[str],
        all_candidates: dict[str, list[dict]]
    ) -> DecisionResult:
        """
        批量决策，处理所有元素

        Args:
            elements: 元素列表（保持顺序）
            all_candidates: 每个元素的候选列表
                {
                    "Li": [{"symbol": "Li_sv", "source": "api_mp", ...}, ...],
                    "Fe": [...],
                }

        Returns:
            DecisionResult: 完整决策结果
        """
        decisions = {}
        potcar_symbols = []

        for element in elements:
            candidates = all_candidates.get(element, [])
            decision = self.decide(element, candidates)
            decisions[element] = decision
            potcar_symbols.append(decision.selected)

        # 计算整体置信度
        if decisions:
            overall_confidence = sum(d.confidence for d in decisions.values()) / len(decisions)
        else:
            overall_confidence = 0.0

        # 生成摘要
        summary = self._generate_summary(elements, decisions)

        return DecisionResult(
            elements=elements,
            decisions=decisions,
            potcar_symbols=potcar_symbols,
            calc_type=self.calc_type,
            precision=self.precision,
            overall_confidence=overall_confidence,
            summary=summary
        )

    def _generate_reasoning(
        self,
        element: str,
        best: PotcarCandidate,
        all_candidates: list[PotcarCandidate],
        agree: list[str],
        disagree: list[str]
    ) -> str:
        """生成决策理由"""
        parts = []

        # 选择结果
        parts.append(f"Selected {best.symbol} for {element}")

        # 数据源一致性
        if len(agree) > 1:
            parts.append(f"({len(agree)} sources agree: {', '.join(agree)})")
        else:
            parts.append(f"(recommended by {best.source})")

        # 如果有分歧，说明
        if disagree:
            other_suggestions = set()
            for c in all_candidates:
                if c.symbol != best.symbol:
                    other_suggestions.add(f"{c.symbol} ({c.source})")
            if other_suggestions:
                parts.append(f"Other suggestions: {', '.join(other_suggestions)}")

        # 原因
        if best.reason:
            parts.append(f"Reason: {best.reason}")

        return ". ".join(parts)

    def _generate_summary(
        self,
        elements: list[str],
        decisions: dict[str, ElementDecision]
    ) -> str:
        """生成决策摘要"""
        lines = []
        lines.append(f"Calculation type: {self.calc_type}, Precision: {self.precision}")
        lines.append(f"Weight profile: {self.weight_config.get_description()}")
        lines.append("")

        for element in elements:
            d = decisions.get(element)
            if d:
                status = "unanimous" if not d.sources_disagree else "consensus"
                lines.append(f"  {element}: {d.selected} [{status}, confidence={d.confidence:.2f}]")

        return "\n".join(lines)


def collect_candidates_from_sources(
    element: str,
    knowledge_base_result: Optional[dict] = None,
    api_mp_result: Optional[dict] = None,
    pymatgen_result: Optional[dict] = None,
    vaspkit_result: Optional[dict] = None,
    mongodb_result: Optional[dict] = None
) -> list[dict]:
    """
    从各数据源收集候选项

    Args:
        element: 元素符号
        knowledge_base_result: 知识库查询结果
        api_mp_result: Materials Project API 结果
        pymatgen_result: pymatgen 推荐结果
        vaspkit_result: vaspkit 推荐结果
        mongodb_result: MongoDB 搜索结果

    Returns:
        候选项列表
    """
    candidates = []

    # 知识库
    if knowledge_base_result:
        symbol = knowledge_base_result.get("recommended", element)
        candidates.append({
            "symbol": symbol,
            "source": WeightConfig.SOURCE_KNOWLEDGE_BASE,
            "confidence": 0.9,
            "reason": knowledge_base_result.get("reason", "VASP official recommendation")
        })

    # Materials Project API
    if api_mp_result:
        symbol = api_mp_result.get("symbol", element)
        candidates.append({
            "symbol": symbol,
            "source": WeightConfig.SOURCE_API_MP,
            "confidence": api_mp_result.get("confidence", 0.8),
            "reason": f"Used in Materials Project calculations"
        })

    # pymatgen
    if pymatgen_result:
        symbol = pymatgen_result.get("symbol", element)
        candidates.append({
            "symbol": symbol,
            "source": WeightConfig.SOURCE_PYMATGEN,
            "confidence": 0.85,
            "reason": "pymatgen MPRelaxSet default"
        })

    # vaspkit
    if vaspkit_result:
        symbol = vaspkit_result.get("symbol", element)
        candidates.append({
            "symbol": symbol,
            "source": WeightConfig.SOURCE_VASPKIT,
            "confidence": 0.85,
            "reason": "vaspkit recommended POTCAR"
        })

    # MongoDB
    if mongodb_result:
        symbol = mongodb_result.get("symbol", element)
        candidates.append({
            "symbol": symbol,
            "source": WeightConfig.SOURCE_MONGODB,
            "confidence": mongodb_result.get("match_quality", 0.7),
            "reason": f"Used in similar structure: {mongodb_result.get('formula', 'N/A')}"
        })

    return candidates


def merge_all_sources(
    elements: list[str],
    knowledge_base: dict[str, dict],
    api_mp: dict[str, str],
    pymatgen: dict[str, str],
    vaspkit: dict[str, str] = None,
    mongodb: list[dict] = None
) -> dict[str, list[dict]]:
    """
    合并所有数据源的结果

    Args:
        elements: 元素列表
        knowledge_base: 知识库结果 {element: {recommended: ..., reason: ...}}
        api_mp: MP API 结果 {element: symbol}
        pymatgen: pymatgen 结果 {element: symbol}
        vaspkit: vaspkit 结果 {element: symbol}
        mongodb: MongoDB 结果列表

    Returns:
        每个元素的候选列表
    """
    all_candidates = {}
    vaspkit = vaspkit or {}
    mongodb = mongodb or []

    # 从 MongoDB 结果提取元素->符号映射
    mongodb_map = {}
    if mongodb:
        for record in mongodb:
            potcar_types = record.get("potcar_types", {})
            for el, sym in potcar_types.items():
                if el not in mongodb_map:
                    mongodb_map[el] = {
                        "symbol": sym,
                        "formula": record.get("formula", ""),
                        "match_quality": record.get("match_quality", 0.7)
                    }

    for element in elements:
        candidates = collect_candidates_from_sources(
            element=element,
            knowledge_base_result=knowledge_base.get(element),
            api_mp_result={"symbol": api_mp.get(element), "confidence": 0.85} if api_mp.get(element) else None,
            pymatgen_result={"symbol": pymatgen.get(element)} if pymatgen.get(element) else None,
            vaspkit_result={"symbol": vaspkit.get(element)} if vaspkit.get(element) else None,
            mongodb_result=mongodb_map.get(element)
        )
        all_candidates[element] = candidates

    return all_candidates
