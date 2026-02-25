"""
外部API模块

目的：
    集成外部材料数据库的API查询功能，获取已发表计算的赝势配置作为参考。

支持的数据源：
    - Materials Project: 最大的DFT计算数据库，提供完整的VASP计算参数
    - AFLOW: 自动化高通量计算数据库
    - OQMD: 开放量子材料数据库
    - NOMAD: 材料科学数据共享平台

设计原则：
    1. 统一接口：所有外部API实现相同的基类接口
    2. 异步支持：支持并行查询多个数据源
    3. 缓存机制：避免重复查询，减少API调用
    4. 错误容忍：单个API失败不影响整体流程
"""

from .base import ExternalAPIBase, PotcarReference, APIStatus
from .materials_project import MaterialsProjectAPI
from .aflow import AFLOWAPI
from .oqmd import OQMDAPI
from .manager import ExternalAPIManager, AggregatedResult

__all__ = [
    "ExternalAPIBase",
    "PotcarReference",
    "APIStatus",
    "MaterialsProjectAPI",
    "AFLOWAPI",
    "OQMDAPI",
    "ExternalAPIManager",
    "AggregatedResult",
]
