"""
外部API管理器

目的：
    统一管理所有外部API，支持并行查询和结果聚合。
"""

import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass, field

from .base import ExternalAPIBase, PotcarReference, APIStatus
from .materials_project import MaterialsProjectAPI
from .aflow import AFLOWAPI
from .oqmd import OQMDAPI

logger = logging.getLogger(__name__)


@dataclass
class AggregatedResult:
    """
    聚合查询结果

    Attributes:
        references: 所有数据源返回的赝势参考
        source_status: 各数据源的查询状态
        errors: 查询过程中的错误信息
    """
    references: list[PotcarReference] = field(default_factory=list)
    source_status: dict[str, APIStatus] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def has_results(self) -> bool:
        """是否有查询结果"""
        return len(self.references) > 0

    @property
    def available_sources(self) -> list[str]:
        """返回成功查询的数据源列表"""
        return [
            name for name, status in self.source_status.items()
            if status == APIStatus.AVAILABLE
        ]

    def get_top_recommendations(self, n: int = 5) -> list[PotcarReference]:
        """获取置信度最高的前N个推荐"""
        sorted_refs = sorted(self.references, key=lambda x: x.confidence, reverse=True)
        return sorted_refs[:n]

    def get_by_source(self, source: str) -> list[PotcarReference]:
        """按数据源筛选结果"""
        return [ref for ref in self.references if ref.source == source]


class ExternalAPIManager:
    """
    外部API管理器

    功能：
        1. 统一初始化和管理所有外部API客户端
        2. 并行查询多个数据源
        3. 聚合和去重查询结果
        4. 处理API错误和超时

    使用示例：
        manager = ExternalAPIManager(config)
        results = manager.search_all(formula="LiFePO4")
    """

    # 默认数据源权重配置
    DEFAULT_WEIGHTS = {
        "Materials Project": 1.0,  # MP权重最高，数据质量最好
        "AFLOW": 0.8,
        "OQMD": 0.7,
    }

    def __init__(self, config: Optional[dict] = None):
        """
        初始化API管理器

        Args:
            config: 配置字典，包含各API的启用状态和参数
                {
                    "materials_project": {
                        "enabled": True,
                        "api_key": "xxx"  # 可选，也可从环境变量读取
                    },
                    "aflow": {"enabled": True},
                    "oqmd": {"enabled": True},
                    "weights": {...}  # 可选，自定义权重
                }
        """
        self.config = config or {}
        self._apis: dict[str, ExternalAPIBase] = {}
        self._weights = self.config.get("weights", self.DEFAULT_WEIGHTS)
        self._initialize_apis()

    def _initialize_apis(self):
        """根据配置初始化各API客户端"""
        # Materials Project
        mp_config = self.config.get("materials_project", {})
        if mp_config.get("enabled", True):  # 默认启用
            try:
                api_key = mp_config.get("api_key")
                mp_api = MaterialsProjectAPI(api_key=api_key)
                self._apis["Materials Project"] = mp_api
                logger.info("Materials Project API 已注册")
            except Exception as e:
                logger.warning(f"Materials Project API 初始化失败: {e}")

        # AFLOW
        aflow_config = self.config.get("aflow", {})
        if aflow_config.get("enabled", False):  # 默认禁用（未实现）
            try:
                self._apis["AFLOW"] = AFLOWAPI()
                logger.info("AFLOW API 已注册")
            except Exception as e:
                logger.warning(f"AFLOW API 初始化失败: {e}")

        # OQMD
        oqmd_config = self.config.get("oqmd", {})
        if oqmd_config.get("enabled", False):  # 默认禁用（未实现）
            try:
                self._apis["OQMD"] = OQMDAPI()
                logger.info("OQMD API 已注册")
            except Exception as e:
                logger.warning(f"OQMD API 初始化失败: {e}")

        logger.info(f"已初始化 {len(self._apis)} 个外部API")

    def get_enabled_apis(self) -> list[str]:
        """获取已启用的API列表"""
        return list(self._apis.keys())

    def get_api(self, name: str) -> Optional[ExternalAPIBase]:
        """获取指定的API客户端"""
        return self._apis.get(name)

    def check_all_status(self) -> dict[str, APIStatus]:
        """检查所有API的状态"""
        status_dict = {}

        def check_single(name: str, api: ExternalAPIBase) -> tuple[str, APIStatus]:
            try:
                return name, api.check_status()
            except Exception as e:
                logger.error(f"检查 {name} 状态失败: {e}")
                return name, APIStatus.UNAVAILABLE

        # 并行检查所有API状态
        with ThreadPoolExecutor(max_workers=len(self._apis)) as executor:
            futures = {
                executor.submit(check_single, name, api): name
                for name, api in self._apis.items()
            }

            for future in as_completed(futures, timeout=10.0):
                try:
                    name, status = future.result()
                    status_dict[name] = status
                except Exception as e:
                    name = futures[future]
                    status_dict[name] = APIStatus.UNAVAILABLE
                    logger.error(f"检查 {name} 状态超时: {e}")

        return status_dict

    def search_by_formula(
        self,
        formula: str,
        functional: str = "PBE",
        sources: Optional[list[str]] = None,
        timeout: float = 30.0
    ) -> AggregatedResult:
        """
        并行查询所有数据源（按化学式）

        Args:
            formula: 化学式
            functional: 泛函类型
            sources: 指定查询的数据源，None表示查询所有已启用的
            timeout: 总超时时间

        Returns:
            聚合后的查询结果
        """
        return self._parallel_search(
            search_method="search_by_formula",
            formula=formula,
            functional=functional,
            sources=sources,
            timeout=timeout
        )

    def search_by_elements(
        self,
        elements: list[str],
        functional: str = "PBE",
        sources: Optional[list[str]] = None,
        timeout: float = 30.0
    ) -> AggregatedResult:
        """
        并行查询所有数据源（按元素组合）

        Args:
            elements: 元素列表
            functional: 泛函类型
            sources: 指定查询的数据源
            timeout: 总超时时间

        Returns:
            聚合后的查询结果
        """
        return self._parallel_search(
            search_method="search_by_elements",
            elements=elements,
            functional=functional,
            sources=sources,
            timeout=timeout
        )

    def _parallel_search(
        self,
        search_method: str,
        sources: Optional[list[str]] = None,
        timeout: float = 30.0,
        **kwargs
    ) -> AggregatedResult:
        """
        并行执行搜索

        Args:
            search_method: 搜索方法名
            sources: 指定数据源
            timeout: 超时时间
            **kwargs: 传递给搜索方法的参数
        """
        result = AggregatedResult()

        # 确定要查询的数据源
        if sources:
            apis_to_query = {
                name: api for name, api in self._apis.items()
                if name in sources
            }
        else:
            apis_to_query = self._apis

        if not apis_to_query:
            logger.warning("没有可用的API进行查询")
            return result

        def query_single(name: str, api: ExternalAPIBase) -> tuple[str, list[PotcarReference], Optional[str]]:
            """查询单个数据源"""
            try:
                method = getattr(api, search_method)
                refs = method(**kwargs)
                return name, refs, None
            except Exception as e:
                error_msg = str(e)
                logger.error(f"{name} 查询失败: {error_msg}")
                return name, [], error_msg

        # 并行查询
        all_references = []
        with ThreadPoolExecutor(max_workers=len(apis_to_query)) as executor:
            futures = {
                executor.submit(query_single, name, api): name
                for name, api in apis_to_query.items()
            }

            for future in as_completed(futures, timeout=timeout):
                name = futures[future]
                try:
                    source_name, refs, error = future.result(timeout=timeout)

                    if error:
                        result.errors[source_name] = error
                        result.source_status[source_name] = APIStatus.UNAVAILABLE
                    else:
                        result.source_status[source_name] = APIStatus.AVAILABLE
                        all_references.extend(refs)
                        logger.info(f"{source_name} 返回 {len(refs)} 条结果")

                except TimeoutError:
                    result.errors[name] = "查询超时"
                    result.source_status[name] = APIStatus.UNAVAILABLE
                    logger.warning(f"{name} 查询超时")
                except Exception as e:
                    result.errors[name] = str(e)
                    result.source_status[name] = APIStatus.UNAVAILABLE
                    logger.error(f"{name} 查询异常: {e}")

        # 应用权重调整置信度
        weighted_refs = self._merge_with_weights(all_references, self._weights)

        # 去重
        result.references = self._deduplicate_results(weighted_refs)

        logger.info(f"聚合查询完成: {len(result.references)} 条唯一结果")
        return result

    def _deduplicate_results(
        self,
        references: list[PotcarReference]
    ) -> list[PotcarReference]:
        """
        去重并排序结果

        去重策略：
            - 相同material_id视为重复
            - 相同potcar_symbols组合视为相似
            - 保留置信度最高的结果
        """
        if not references:
            return []

        # 按 (元素组合, potcar_symbols) 分组
        seen_configs: dict[tuple, PotcarReference] = {}

        for ref in references:
            # 创建唯一键：排序后的元素 + 排序后的potcar符号
            elements_key = tuple(sorted(ref.elements))
            potcar_key = tuple(ref.potcar_symbols)  # 保持顺序，因为顺序对应元素
            config_key = (elements_key, potcar_key)

            if config_key not in seen_configs:
                seen_configs[config_key] = ref
            else:
                # 保留置信度更高的
                if ref.confidence > seen_configs[config_key].confidence:
                    seen_configs[config_key] = ref

        # 按置信度排序
        unique_refs = list(seen_configs.values())
        unique_refs.sort(key=lambda x: x.confidence, reverse=True)

        return unique_refs

    def _merge_with_weights(
        self,
        references: list[PotcarReference],
        source_weights: dict[str, float]
    ) -> list[PotcarReference]:
        """
        根据数据源权重调整置信度

        Args:
            references: 原始参考列表
            source_weights: 各数据源的权重配置

        Returns:
            调整置信度后的参考列表
        """
        for ref in references:
            weight = source_weights.get(ref.source, 0.5)
            # 置信度 = 原始置信度 * 数据源权重
            ref.confidence = ref.confidence * weight

        return references

    def get_material_details(
        self,
        material_id: str,
        source: str = "Materials Project"
    ) -> Optional[dict]:
        """
        获取特定材料的详细信息

        Args:
            material_id: 材料ID
            source: 数据源名称

        Returns:
            材料详细信息字典
        """
        api = self._apis.get(source)
        if not api:
            logger.warning(f"数据源 {source} 未启用")
            return None

        try:
            return api.get_calculation_details(material_id)
        except Exception as e:
            logger.error(f"获取材料 {material_id} 详情失败: {e}")
            return None
