"""
知识库数据结构定义

目的：
    定义知识库中各类数据的标准结构，确保数据一致性。
    为知识库的读写提供类型约束。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PotcarVariant:
    """单个赝势变体的信息"""
    name: str                    # 如 "Fe_pv"
    enmax: float                 # 截断能
    valence: int                 # 价电子数
    description: str             # 描述
    recommended_for: list[str]   # 推荐使用场景


@dataclass
class ElementKnowledge:
    """单个元素的完整知识"""
    symbol: str                  # 元素符号
    variants: list[PotcarVariant]
    default: str                 # 默认推荐
    rules: dict[str, str]        # 场景 -> 推荐变体的映射


@dataclass
class ScenarioRule:
    """应用场景的决策规则"""
    name: str                    # 场景名称，如 "battery"
    description: str             # 场景描述
    element_overrides: dict      # 元素级别的覆盖规则
    priority: int                # 优先级
    conditions: dict             # 触发条件
