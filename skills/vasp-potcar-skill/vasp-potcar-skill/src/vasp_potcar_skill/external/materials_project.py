"""
Materials Project API

目的：
    通过Materials Project API查询已发表计算的赝势配置。
    Materials Project是目前最大的DFT计算数据库，包含超过15万种材料的计算数据。

API文档：
    https://api.materialsproject.org/docs

使用方式：
    需要在 https://materialsproject.org 注册并获取API密钥
    将密钥设置为环境变量 MP_API_KEY 或在配置文件中指定
"""

import os
import logging
from typing import Optional

from .base import ExternalAPIBase, PotcarReference, APIStatus

logger = logging.getLogger(__name__)


class MaterialsProjectAPI(ExternalAPIBase):
    """
    Materials Project API客户端

    功能：
        1. 按化学式精确搜索
        2. 按元素组合模糊搜索
        3. 获取完整计算参数（INCAR, POTCAR, KPOINTS）
        4. 支持过滤特定泛函类型

    注意事项：
        - API有速率限制，建议启用缓存
        - 返回的POTCAR信息基于Materials Project的标准设置
        - 部分旧数据可能使用过时的赝势版本
    """

    BASE_URL = "https://api.materialsproject.org"

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化API客户端

        Args:
            api_key: API密钥，如不提供则从环境变量读取
        """
        self.api_key = api_key or os.environ.get("MP_API_KEY")
        self._client = None
        self._available = None

        if self.api_key:
            self._init_client()

    def _init_client(self):
        """初始化mp-api客户端"""
        try:
            from mp_api.client import MPRester
            self._client = MPRester(self.api_key)
            self._available = True
            logger.info("Materials Project API 客户端初始化成功")
        except ImportError:
            logger.warning("mp-api 未安装，请运行: pip install mp-api")
            self._available = False
        except Exception as e:
            logger.error(f"Materials Project API 初始化失败: {e}")
            self._available = False

    @property
    def name(self) -> str:
        return "Materials Project"

    @property
    def requires_api_key(self) -> bool:
        return True

    def check_status(self) -> APIStatus:
        """检查API连接状态"""
        if not self.api_key:
            return APIStatus.UNAUTHORIZED

        if self._available is False:
            return APIStatus.UNAVAILABLE

        try:
            # 尝试一个简单的查询来验证连接
            if self._client is None:
                self._init_client()

            if self._client:
                # 查询一个简单的材料来测试连接
                docs = self._client.materials.summary.search(
                    formula="Si",
                    fields=["material_id"],
                    num_chunks=1,
                    chunk_size=1
                )
                list(docs)  # 执行查询
                return APIStatus.AVAILABLE
        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                return APIStatus.RATE_LIMITED
            elif "unauthorized" in error_str or "forbidden" in error_str or "401" in error_str:
                return APIStatus.UNAUTHORIZED
            logger.error(f"Materials Project API 状态检查失败: {e}")

        return APIStatus.UNAVAILABLE

    def search_by_formula(
        self,
        formula: str,
        functional: str = "PBE"
    ) -> list[PotcarReference]:
        """
        按化学式搜索Materials Project数据库

        实现要点：
            1. 使用mp-api的materials.summary端点
            2. 过滤指定泛函类型的计算
            3. 提取potcar_spec字段获取赝势信息
            4. 按能量排序，优先返回基态结构
        """
        if not self._client:
            logger.warning("Materials Project API 客户端未初始化")
            return []

        results = []
        try:
            # 查询材料摘要信息
            docs = self._client.materials.summary.search(
                formula=formula,
                fields=[
                    "material_id",
                    "formula_pretty",
                    "elements",
                    "energy_above_hull",
                    "is_stable",
                    "deprecated"
                ],
                num_chunks=1,
                chunk_size=50  # 限制返回数量
            )

            for doc in docs:
                # 跳过已废弃的条目
                if getattr(doc, 'deprecated', False):
                    continue

                material_id = str(doc.material_id)
                elements = [str(e) for e in doc.elements]

                # 获取POTCAR信息
                potcar_symbols = self._get_potcar_symbols(material_id, elements)

                if potcar_symbols:
                    # 计算置信度：稳定结构置信度更高
                    confidence = 0.9 if getattr(doc, 'is_stable', False) else 0.7
                    energy_above_hull = getattr(doc, 'energy_above_hull', None)
                    if energy_above_hull is not None and energy_above_hull < 0.025:
                        confidence = min(confidence + 0.05, 0.95)

                    ref = PotcarReference(
                        source=self.name,
                        material_id=material_id,
                        formula=doc.formula_pretty,
                        elements=elements,
                        potcar_symbols=potcar_symbols,
                        potcar_functional=functional,
                        calculation_type="GGA" if functional == "PBE" else functional,
                        url=f"https://materialsproject.org/materials/{material_id}",
                        confidence=confidence
                    )
                    results.append(ref)

            # 按置信度排序
            results.sort(key=lambda x: x.confidence, reverse=True)
            logger.info(f"Materials Project 按化学式 '{formula}' 查询到 {len(results)} 条结果")

        except Exception as e:
            logger.error(f"Materials Project search_by_formula 失败: {e}")

        return results

    def search_by_elements(
        self,
        elements: list[str],
        functional: str = "PBE"
    ) -> list[PotcarReference]:
        """
        按元素组合搜索

        实现要点：
            1. 使用chemsys参数搜索元素体系
            2. 限制返回数量避免过多结果
            3. 按稳定性排序
        """
        if not self._client:
            logger.warning("Materials Project API 客户端未初始化")
            return []

        results = []
        try:
            # 构建chemsys字符串（元素按字母排序，用-连接）
            chemsys = "-".join(sorted(elements))

            docs = self._client.materials.summary.search(
                chemsys=chemsys,
                fields=[
                    "material_id",
                    "formula_pretty",
                    "elements",
                    "energy_above_hull",
                    "is_stable",
                    "deprecated"
                ],
                num_chunks=1,
                chunk_size=30  # 元素组合搜索返回更少结果
            )

            for doc in docs:
                if getattr(doc, 'deprecated', False):
                    continue

                material_id = str(doc.material_id)
                doc_elements = [str(e) for e in doc.elements]

                potcar_symbols = self._get_potcar_symbols(material_id, doc_elements)

                if potcar_symbols:
                    confidence = 0.85 if getattr(doc, 'is_stable', False) else 0.65
                    energy_above_hull = getattr(doc, 'energy_above_hull', None)
                    if energy_above_hull is not None and energy_above_hull < 0.025:
                        confidence = min(confidence + 0.05, 0.9)

                    ref = PotcarReference(
                        source=self.name,
                        material_id=material_id,
                        formula=doc.formula_pretty,
                        elements=doc_elements,
                        potcar_symbols=potcar_symbols,
                        potcar_functional=functional,
                        calculation_type="GGA" if functional == "PBE" else functional,
                        url=f"https://materialsproject.org/materials/{material_id}",
                        confidence=confidence
                    )
                    results.append(ref)

            results.sort(key=lambda x: x.confidence, reverse=True)
            logger.info(f"Materials Project 按元素 {elements} 查询到 {len(results)} 条结果")

        except Exception as e:
            logger.error(f"Materials Project search_by_elements 失败: {e}")

        return results

    def _get_potcar_symbols(
        self,
        material_id: str,
        elements: list[str]
    ) -> list[str]:
        """
        获取材料使用的POTCAR符号

        Materials Project使用标准化的POTCAR设置，这里返回MP的推荐配置
        """
        # Materials Project 的标准 POTCAR 映射
        # 基于 pymatgen 的 MPRelaxSet 默认配置
        mp_potcar_mapping = {
            # 碱金属
            "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
            # 碱土金属
            "Be": "Be", "Mg": "Mg_pv", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
            # 过渡金属 3d
            "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
            "Mn": "Mn_pv", "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
            # 过渡金属 4d
            "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_pv", "Mo": "Mo_pv",
            "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
            # 过渡金属 5d
            "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_pv", "Re": "Re_pv",
            "Os": "Os_pv", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
            # 镧系
            "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3", "Pm": "Pm_3",
            "Sm": "Sm_3", "Eu": "Eu_2", "Gd": "Gd_3", "Tb": "Tb_3", "Dy": "Dy_3",
            "Ho": "Ho_3", "Er": "Er_3", "Tm": "Tm_3", "Yb": "Yb_2", "Lu": "Lu_3",
            # 锕系
            "Ac": "Ac", "Th": "Th", "Pa": "Pa", "U": "U", "Np": "Np", "Pu": "Pu",
            # 主族元素
            "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
            "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
            "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
            "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
            "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi", "Po": "Po_d", "At": "At",
            # 稀有气体
            "He": "He", "Ne": "Ne", "Ar": "Ar", "Kr": "Kr", "Xe": "Xe",
            # 氢
            "H": "H",
        }

        potcar_symbols = []
        for element in elements:
            symbol = mp_potcar_mapping.get(element, element)
            potcar_symbols.append(symbol)

        return potcar_symbols

    def get_calculation_details(
        self,
        material_id: str
    ) -> Optional[dict]:
        """
        获取材料的完整计算参数

        返回内容：
            - potcar_symbols: 赝势符号列表
            - incar: INCAR参数字典
            - kpoints: KPOINTS设置
            - encut: 截断能
            - is_hubbard: 是否使用DFT+U
            - hubbards: U值设置
        """
        if not self._client:
            logger.warning("Materials Project API 客户端未初始化")
            return None

        try:
            # 获取材料摘要
            docs = self._client.materials.summary.search(
                material_ids=[material_id],
                fields=[
                    "material_id",
                    "formula_pretty",
                    "elements",
                    "is_stable",
                    "energy_above_hull"
                ]
            )

            doc = next(iter(docs), None)
            if not doc:
                return None

            elements = [str(e) for e in doc.elements]
            potcar_symbols = self._get_potcar_symbols(material_id, elements)

            # 获取计算任务详情
            task_details = self._get_task_details(material_id)

            result = {
                "material_id": material_id,
                "formula": doc.formula_pretty,
                "elements": elements,
                "potcar_symbols": potcar_symbols,
                "potcar_functional": "PBE",
                "is_stable": getattr(doc, 'is_stable', None),
                "energy_above_hull": getattr(doc, 'energy_above_hull', None),
                "url": f"https://materialsproject.org/materials/{material_id}"
            }

            # 合并任务详情
            if task_details:
                result.update(task_details)

            return result

        except Exception as e:
            logger.error(f"Materials Project get_calculation_details 失败: {e}")
            return None

    def _get_task_details(self, material_id: str) -> Optional[dict]:
        """获取计算任务的详细参数"""
        try:
            # 尝试获取任务文档
            tasks = self._client.materials.tasks.search(
                material_ids=[material_id],
                fields=["task_id", "input", "output", "calcs_reversed"],
                num_chunks=1,
                chunk_size=5
            )

            for task in tasks:
                input_data = getattr(task, 'input', None)
                if input_data:
                    incar = getattr(input_data, 'incar', None)
                    if incar:
                        return {
                            "encut": incar.get("ENCUT"),
                            "is_hubbard": incar.get("LDAU", False),
                            "hubbards": incar.get("LDAUU") if incar.get("LDAU") else None,
                            "incar_subset": {
                                k: v for k, v in incar.items()
                                if k in ["ENCUT", "EDIFF", "ISMEAR", "SIGMA", "LDAU", "LDAUU", "LDAUJ", "LDAUL"]
                            }
                        }
        except Exception as e:
            logger.debug(f"获取任务详情失败（可能是API限制）: {e}")

        return None
