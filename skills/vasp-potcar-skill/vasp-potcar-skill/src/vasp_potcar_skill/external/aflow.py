"""
AFLOW API

目的：
    通过AFLOW REST API查询自动化高通量计算数据库中的赝势配置。
    AFLOW包含超过350万种材料的计算数据。

API文档：
    http://aflowlib.org/API/
"""

import logging
import requests
from typing import Optional

from .base import ExternalAPIBase, PotcarReference, APIStatus

logger = logging.getLogger(__name__)


class AFLOWAPI(ExternalAPIBase):
    """
    AFLOW API客户端

    特点：
        - 无需API密钥
        - 数据量大，覆盖面广
        - 提供标准化的计算参数
    """

    BASE_URL = "http://aflowlib.org/API/aflux"
    TIMEOUT = 5  # 请求超时时间（秒）- 优化：从30秒降到5秒

    # AFLOW使用的标准POTCAR映射（基于VASP标准）
    AFLOW_POTCAR_MAPPING = {
        # 碱金属
        "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
        # 碱土金属
        "Be": "Be", "Mg": "Mg", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
        # 过渡金属 3d
        "Sc": "Sc_sv", "Ti": "Ti_sv", "V": "V_sv", "Cr": "Cr_pv",
        "Mn": "Mn_pv", "Fe": "Fe", "Co": "Co", "Ni": "Ni", "Cu": "Cu", "Zn": "Zn",
        # 过渡金属 4d
        "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_sv", "Mo": "Mo_sv",
        "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
        # 过渡金属 5d
        "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_sv", "Re": "Re",
        "Os": "Os", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
        # 镧系
        "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3",
        "Sm": "Sm_3", "Eu": "Eu_2", "Gd": "Gd_3", "Tb": "Tb_3",
        "Dy": "Dy_3", "Ho": "Ho_3", "Er": "Er_3", "Tm": "Tm_3", "Yb": "Yb_2", "Lu": "Lu_3",
        # 主族元素
        "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
        "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
        "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
        "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
        "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
        # 氢
        "H": "H",
    }

    def __init__(self):
        """初始化AFLOW API客户端"""
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "VASP-POTCAR-Skill/1.0"
        })

    @property
    def name(self) -> str:
        return "AFLOW"

    @property
    def requires_api_key(self) -> bool:
        return False

    def check_status(self) -> APIStatus:
        """检查API连接状态"""
        try:
            # 简单查询测试连接
            url = f"{self.BASE_URL}/?species(Si),paging(1)"
            response = self._session.get(url, timeout=10)

            if response.status_code == 200:
                return APIStatus.AVAILABLE
            elif response.status_code == 429:
                return APIStatus.RATE_LIMITED
            else:
                return APIStatus.UNAVAILABLE

        except requests.exceptions.Timeout:
            logger.warning("AFLOW API timeout")
            return APIStatus.UNAVAILABLE
        except requests.exceptions.RequestException as e:
            logger.error(f"AFLOW API connection error: {e}")
            return APIStatus.UNAVAILABLE

    def search_by_formula(
        self,
        formula: str,
        functional: str = "PBE"
    ) -> list[PotcarReference]:
        """
        按化学式搜索AFLOW数据库

        Args:
            formula: 化学式（如 "LiFePO4"）
            functional: 泛函类型（AFLOW主要使用PBE）

        Returns:
            匹配的赝势参考列表
        """
        results = []

        try:
            # 构建AFLUX查询
            # compound() 用于精确匹配化学式
            query = f"compound({formula}),paging(50)"
            url = f"{self.BASE_URL}/?{query}"

            response = self._session.get(url, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.warning(f"AFLOW search failed with status {response.status_code}")
                return results

            data = response.json()

            # 解析返回的条目
            for entry in data:
                auid = entry.get("auid", "")
                compound = entry.get("compound", formula)
                species = entry.get("species", [])

                if not species:
                    continue

                # 获取元素列表
                elements = [s for s in species if s]

                # 映射到POTCAR符号
                potcar_symbols = [
                    self.AFLOW_POTCAR_MAPPING.get(el, el)
                    for el in elements
                ]

                # 计算置信度
                confidence = 0.75  # AFLOW是高质量计算数据库

                # 如果是稳定相，提高置信度
                if entry.get("stability_criterion"):
                    confidence += 0.1

                ref = PotcarReference(
                    source=self.name,
                    material_id=auid,
                    formula=compound,
                    elements=elements,
                    potcar_symbols=potcar_symbols,
                    potcar_functional="PBE",  # AFLOW主要使用PBE
                    encut=entry.get("Egap_fit"),  # AFLOW不直接提供ENCUT
                    calculation_type="relaxation",
                    url=f"http://aflowlib.org/material/?id={auid}",
                    confidence=min(confidence, 0.9)
                )
                results.append(ref)

            logger.info(f"AFLOW search for '{formula}' returned {len(results)} results")

        except requests.exceptions.RequestException as e:
            logger.error(f"AFLOW API request failed: {e}")
        except Exception as e:
            logger.error(f"AFLOW search error: {e}")

        return results

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
        results = []

        try:
            # 使用species()搜索包含这些元素的材料
            species_query = ",".join(elements)
            query = f"species({species_query}),paging(30)"
            url = f"{self.BASE_URL}/?{query}"

            response = self._session.get(url, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.warning(f"AFLOW elements search failed with status {response.status_code}")
                return results

            data = response.json()

            for entry in data:
                auid = entry.get("auid", "")
                compound = entry.get("compound", "")
                species = entry.get("species", [])

                if not species:
                    continue

                # 获取元素列表
                entry_elements = [s for s in species if s]

                # 映射到POTCAR符号
                potcar_symbols = [
                    self.AFLOW_POTCAR_MAPPING.get(el, el)
                    for el in entry_elements
                ]

                # 计算置信度（按元素匹配程度）
                query_set = set(elements)
                entry_set = set(entry_elements)

                if query_set == entry_set:
                    confidence = 0.8
                elif query_set.issubset(entry_set):
                    confidence = 0.7
                else:
                    confidence = 0.6

                ref = PotcarReference(
                    source=self.name,
                    material_id=auid,
                    formula=compound,
                    elements=entry_elements,
                    potcar_symbols=potcar_symbols,
                    potcar_functional="PBE",
                    calculation_type="relaxation",
                    url=f"http://aflowlib.org/material/?id={auid}",
                    confidence=confidence
                )
                results.append(ref)

            # 按置信度排序
            results.sort(key=lambda x: x.confidence, reverse=True)
            logger.info(f"AFLOW elements search for {elements} returned {len(results)} results")

        except requests.exceptions.RequestException as e:
            logger.error(f"AFLOW API request failed: {e}")
        except Exception as e:
            logger.error(f"AFLOW elements search error: {e}")

        return results

    def get_calculation_details(
        self,
        material_id: str
    ) -> Optional[dict]:
        """
        获取特定材料的详细计算参数

        Args:
            material_id: AFLOW材料ID (auid)

        Returns:
            完整的计算参数字典
        """
        try:
            # 使用auid查询详细信息
            query = f"auid({material_id})"
            url = f"{self.BASE_URL}/?{query}"

            response = self._session.get(url, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.warning(f"AFLOW details query failed with status {response.status_code}")
                return None

            data = response.json()

            if not data:
                return None

            entry = data[0]

            # 提取详细信息
            species = entry.get("species", [])
            elements = [s for s in species if s]

            potcar_symbols = [
                self.AFLOW_POTCAR_MAPPING.get(el, el)
                for el in elements
            ]

            result = {
                "material_id": material_id,
                "formula": entry.get("compound", ""),
                "elements": elements,
                "potcar_symbols": potcar_symbols,
                "potcar_functional": "PBE",
                "space_group": entry.get("spacegroup_relax", ""),
                "prototype": entry.get("prototype", ""),
                "stoichiometry": entry.get("stoichiometry", []),
                "energy_atom": entry.get("energy_atom", None),
                "volume_atom": entry.get("volume_atom", None),
                "url": f"http://aflowlib.org/material/?id={material_id}"
            }

            # 提取能带/电子结构信息（如果有）
            if entry.get("Egap_type"):
                result["band_gap_type"] = entry.get("Egap_type")
            if entry.get("Egap"):
                result["band_gap"] = entry.get("Egap")

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"AFLOW API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"AFLOW details query error: {e}")
            return None

    def get_potcar_recommendation(self, element: str) -> str:
        """
        获取AFLOW对特定元素的POTCAR推荐

        Args:
            element: 元素符号

        Returns:
            推荐的POTCAR符号
        """
        return self.AFLOW_POTCAR_MAPPING.get(element, element)
