"""
统一知识库模块

目的：
    将所有赝势选择相关的专业知识集中管理，避免知识分散在多处导致不一致。
    Skill只负责推理流程，具体知识从此模块获取。

包含：
    - schema.py: 知识库数据结构定义
    - loader.py: 知识库加载和查询接口
    - elements/: 按元素组织的赝势知识（YAML文件）
    - scenarios/: 按应用场景组织的决策规则（YAML文件）

设计原则：
    1. 单一数据源：所有专业知识只在此处维护
    2. 结构化存储：使用YAML便于人工维护和LLM理解
    3. 版本化：支持知识库版本管理和回滚
"""

from .loader import KnowledgeLoader
from .schema import ElementKnowledge, ScenarioRule
