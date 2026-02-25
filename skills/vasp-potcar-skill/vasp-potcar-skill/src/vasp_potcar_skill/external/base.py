"""
外部API基类

目的：
    定义所有外部API的统一接口，确保不同数据源可以无缝切换和并行查询。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class APIStatus(Enum):
    """API状态"""
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"


@dataclass
class PotcarReference:
    """
    外部数据源返回的赝势参考信息

    Attributes:
        source: 数据来源（如 "Materials Project"）
        material_id: 材料在该数据库中的ID
        formula: 化学式
        elements: 元素列表
        potcar_symbols: 赝势符号列表（如 ["Li_sv", "Fe_pv", "P", "O"]）
        potcar_functional: 泛函类型（如 "PBE", "LDA"）
        encut: 使用的截断能
        calculation_type: 计算类型（如 "relaxation", "static"）
        url: 原始数据链接
        confidence: 置信度（基于匹配程度）
    """
    source: str
    material_id: str
    formula: str
    elements: list[str]
    potcar_symbols: list[str]
    potcar_functional: str
    encut: Optional[float] = None
    calculation_type: Optional[str] = None
    url: Optional[str] = None
    confidence: float = 0.0


class ExternalAPIBase(ABC):
    """
    外部API基类

    所有外部数据源API必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """是否需要API密钥"""
        pass

    @abstractmethod
    def check_status(self) -> APIStatus:
        """
        检查API状态

        Returns:
            APIStatus: 当前API状态
        """
        pass

    @abstractmethod
    def search_by_formula(
        self,
        formula: str,
        functional: str = "PBE"
    ) -> list[PotcarReference]:
        """
        按化学式搜索

        Args:
            formula: 化学式（如 "LiFePO4"）
            functional: 泛函类型

        Returns:
            匹配的赝势参考列表
        """
        pass

    @abstractmethod
    def search_by_elements(
        self,
        elements: list[str],
        functional: str = "PBE"
    ) -> list[PotcarReference]:
        """
        按元素组合搜索

        Args:
            elements: 元素列表（如 ["Li", "Fe", "P", "O"]）
            functional: 泛函类型

        Returns:
            匹配的赝势参考列表
        """
        pass

    @abstractmethod
    def get_calculation_details(
        self,
        material_id: str
    ) -> Optional[dict]:
        """
        获取特定材料的详细计算参数

        Args:
            material_id: 材料ID

        Returns:
            完整的计算参数字典，包含INCAR、KPOINTS等信息
        """
        pass
