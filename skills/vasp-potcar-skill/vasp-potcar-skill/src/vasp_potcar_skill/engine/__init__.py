"""
决策引擎模块

目的：
    实现数据源权重机制和冲突解决逻辑。
    将"如何综合多个数据源做决策"的逻辑从LLM转移到代码中，
    提高决策的一致性和可解释性。

包含：
    - weights.py: 数据源权重配置和计算
    - decision.py: 核心决策逻辑
    - conflict_resolver.py: 多数据源冲突时的解决策略

设计原则：
    1. 可配置：权重通过配置文件调整，无需改代码
    2. 可解释：每个决策都能追溯到具体的数据源和规则
    3. 确定性：相同输入产生相同输出，减少LLM的随机性
"""

from .decision import DecisionEngine
from .weights import WeightConfig
