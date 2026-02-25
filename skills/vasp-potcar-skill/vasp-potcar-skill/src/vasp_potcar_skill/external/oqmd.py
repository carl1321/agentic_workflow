"""
OQMD API

目的：
    通过OQMD REST API查询开放量子材料数据库中的赝势配置。

API文档：
    https://oqmd.org/documentation/
"""

import logging
import requests
from typing import Optional

from .base import ExternalAPIBase, PotcarReference, APIStatus

logger = logging.getLogger(__name__)


class OQMDAPI(ExternalAPIBase):
    """
    OQMD API客户端

    特点：
        - 无需API密钥
        - 专注于热力学稳定性数据
        - 提供形成能等热力学量
    """

    BASE_URL = "https://oqmd.org/oqmdapi"
    TIMEOUT = 5  # 请求超时时间（秒）- 优化：从30秒降到5秒

    # OQMD使用的标准POTCAR映射
    # OQMD主要使用VASP的PAW-PBE赝势
    OQMD_POTCAR_MAPPING = {
        # 碱金属
        "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
        # 碱土金属
        "Be": "Be", "Mg": "Mg", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
        # 过渡金属 3d
        "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_sv", "Cr": "Cr_pv",
        "Mn": "Mn_pv", "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
        # 过渡金属 4d
        "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_pv", "Mo": "Mo_pv",
        "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
        # 过渡金属 5d
        "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_pv", "Re": "Re_pv",
        "Os": "Os_pv", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
        # 镧系
        "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3",
        "Sm": "Sm_3", "Eu": "Eu_2", "Gd": "Gd_3", "Tb": "Tb_3",
        "Dy": "Dy_3", "Ho": "Ho_3", "Er": "Er_3", "Tm": "Tm_3", "Yb": "Yb_2", "Lu": "Lu_3",
        # 主族元素
        "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
        "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
        "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
        "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
        "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi",
        # 氢
        "H": "H",
    }

    def __init__(self):
        """初始化OQMD API客户端"""
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "VASP-POTCAR-Skill/1.0"
        })

    @property
    def name(self) -> str:
        return "OQMD"

    @property
    def requires_api_key(self) -> bool:
        return False

    def check_status(self) -> APIStatus:
        """检查API连接状态"""
        try:
            # 简单查询测试连接
            url = f"{self.BASE_URL}/formationenergy"
            params = {"composition": "Si", "limit": 1}

            response = self._session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return APIStatus.AVAILABLE
            elif response.status_code == 429:
                return APIStatus.RATE_LIMITED
            else:
                return APIStatus.UNAVAILABLE

        except requests.exceptions.Timeout:
            logger.warning("OQMD API timeout")
            return APIStatus.UNAVAILABLE
        except requests.exceptions.RequestException as e:
            logger.error(f"OQMD API connection error: {e}")
            return APIStatus.UNAVAILABLE

    def search_by_formula(
        self,
        formula: str,
        functional: str = "PBE"
    ) -> list[PotcarReference]:
        """
        按化学式搜索OQMD数据库

        Args:
            formula: 化学式（如 "LiFePO4"）
            functional: 泛函类型（OQMD使用PBE）

        Returns:
            匹配的赝势参考列表
        """
        results = []

        try:
            url = f"{self.BASE_URL}/formationenergy"
            params = {
                "composition": formula,
                "limit": 50,
                "fields": "name,entry_id,formationenergy_id,composition,spacegroup,delta_e,stability"
            }

            response = self._session.get(url, params=params, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.warning(f"OQMD search failed with status {response.status_code}")
                return results

            data = response.json()
            entries = data.get("data", [])

            for entry in entries:
                entry_id = entry.get("entry_id", "")
                composition = entry.get("composition", formula)
                spacegroup = entry.get("spacegroup", "")
                delta_e = entry.get("delta_e")  # 形成能
                stability = entry.get("stability")  # 相对于凸包的稳定性

                # 解析化学式获取元素
                elements = self._parse_composition(composition)

                if not elements:
                    continue

                # 映射到POTCAR符号
                potcar_symbols = [
                    self.OQMD_POTCAR_MAPPING.get(el, el)
                    for el in elements
                ]

                # 计算置信度
                confidence = 0.7  # OQMD基础置信度

                # 稳定相提高置信度
                if stability is not None and stability < 0.025:  # eV/atom
                    confidence += 0.15
                elif stability is not None and stability == 0:
                    confidence += 0.2  # 凸包上的相

                ref = PotcarReference(
                    source=self.name,
                    material_id=str(entry_id),
                    formula=composition,
                    elements=elements,
                    potcar_symbols=potcar_symbols,
                    potcar_functional="PBE",
                    encut=None,  # OQMD不提供ENCUT信息
                    calculation_type="relaxation",
                    url=f"https://oqmd.org/materials/entry/{entry_id}",
                    confidence=min(confidence, 0.9)
                )
                results.append(ref)

            # 按置信度排序
            results.sort(key=lambda x: x.confidence, reverse=True)
            logger.info(f"OQMD search for '{formula}' returned {len(results)} results")

        except requests.exceptions.RequestException as e:
            logger.error(f"OQMD API request failed: {e}")
        except Exception as e:
            logger.error(f"OQMD search error: {e}")

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
            url = f"{self.BASE_URL}/formationenergy"

            # OQMD使用element_set进行元素搜索
            element_set = "-".join(sorted(elements))

            params = {
                "element_set": element_set,
                "limit": 30,
                "fields": "name,entry_id,formationenergy_id,composition,spacegroup,delta_e,stability"
            }

            response = self._session.get(url, params=params, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.warning(f"OQMD elements search failed with status {response.status_code}")
                return results

            data = response.json()
            entries = data.get("data", [])

            for entry in entries:
                entry_id = entry.get("entry_id", "")
                composition = entry.get("composition", "")
                stability = entry.get("stability")

                # 解析化学式获取元素
                entry_elements = self._parse_composition(composition)

                if not entry_elements:
                    continue

                # 映射到POTCAR符号
                potcar_symbols = [
                    self.OQMD_POTCAR_MAPPING.get(el, el)
                    for el in entry_elements
                ]

                # 计算置信度（按元素匹配程度）
                query_set = set(elements)
                entry_set = set(entry_elements)

                if query_set == entry_set:
                    confidence = 0.75
                elif query_set.issubset(entry_set):
                    confidence = 0.65
                else:
                    confidence = 0.55

                # 稳定相提高置信度
                if stability is not None and stability <= 0:
                    confidence += 0.1

                ref = PotcarReference(
                    source=self.name,
                    material_id=str(entry_id),
                    formula=composition,
                    elements=entry_elements,
                    potcar_symbols=potcar_symbols,
                    potcar_functional="PBE",
                    calculation_type="relaxation",
                    url=f"https://oqmd.org/materials/entry/{entry_id}",
                    confidence=min(confidence, 0.85)
                )
                results.append(ref)

            # 按置信度排序
            results.sort(key=lambda x: x.confidence, reverse=True)
            logger.info(f"OQMD elements search for {elements} returned {len(results)} results")

        except requests.exceptions.RequestException as e:
            logger.error(f"OQMD API request failed: {e}")
        except Exception as e:
            logger.error(f"OQMD elements search error: {e}")

        return results

    def get_calculation_details(
        self,
        material_id: str
    ) -> Optional[dict]:
        """
        获取特定材料的详细计算参数

        Args:
            material_id: OQMD材料ID (entry_id)

        Returns:
            完整的计算参数字典
        """
        try:
            url = f"{self.BASE_URL}/entry/{material_id}"

            response = self._session.get(url, timeout=self.TIMEOUT)

            if response.status_code != 200:
                logger.warning(f"OQMD details query failed with status {response.status_code}")
                return None

            data = response.json()

            if not data:
                return None

            # 提取详细信息
            composition = data.get("composition", "")
            elements = self._parse_composition(composition)

            potcar_symbols = [
                self.OQMD_POTCAR_MAPPING.get(el, el)
                for el in elements
            ]

            result = {
                "material_id": material_id,
                "formula": composition,
                "elements": elements,
                "potcar_symbols": potcar_symbols,
                "potcar_functional": "PBE",
                "space_group": data.get("spacegroup", ""),
                "prototype": data.get("prototype", ""),
                "formation_energy": data.get("delta_e"),
                "stability": data.get("stability"),
                "volume": data.get("volume"),
                "band_gap": data.get("band_gap"),
                "magnetic_moment": data.get("magmom"),
                "url": f"https://oqmd.org/materials/entry/{material_id}"
            }

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"OQMD API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"OQMD details query error: {e}")
            return None

    def _parse_composition(self, composition: str) -> list[str]:
        """
        解析化学式提取元素列表

        Args:
            composition: 化学式字符串（如 "Li4Fe4P4O16"）

        Returns:
            元素列表（不重复，按字母排序）
        """
        import re

        elements = []
        # 匹配元素符号（一个大写字母，可能跟一个小写字母）
        pattern = r'([A-Z][a-z]?)'
        matches = re.findall(pattern, composition)

        # 去重并保持顺序
        seen = set()
        for el in matches:
            if el not in seen:
                elements.append(el)
                seen.add(el)

        return elements

    def get_potcar_recommendation(self, element: str) -> str:
        """
        获取OQMD对特定元素的POTCAR推荐

        Args:
            element: 元素符号

        Returns:
            推荐的POTCAR符号
        """
        return self.OQMD_POTCAR_MAPPING.get(element, element)

    def get_stable_phases(
        self,
        elements: list[str],
        limit: int = 10
    ) -> list[dict]:
        """
        获取指定元素体系中的稳定相

        Args:
            elements: 元素列表
            limit: 返回数量限制

        Returns:
            稳定相列表
        """
        results = []

        try:
            url = f"{self.BASE_URL}/formationenergy"
            element_set = "-".join(sorted(elements))

            params = {
                "element_set": element_set,
                "stability": 0,  # 只返回凸包上的相
                "limit": limit,
                "fields": "name,entry_id,composition,spacegroup,delta_e"
            }

            response = self._session.get(url, params=params, timeout=self.TIMEOUT)

            if response.status_code != 200:
                return results

            data = response.json()
            entries = data.get("data", [])

            for entry in entries:
                results.append({
                    "entry_id": entry.get("entry_id"),
                    "formula": entry.get("composition"),
                    "spacegroup": entry.get("spacegroup"),
                    "formation_energy": entry.get("delta_e"),
                    "url": f"https://oqmd.org/materials/entry/{entry.get('entry_id')}"
                })

        except Exception as e:
            logger.error(f"OQMD stable phases query error: {e}")

        return results
