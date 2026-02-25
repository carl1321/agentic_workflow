#!/usr/bin/env python3
"""
VASP POTCAR Skill - 多数据源版本

支持多个数据源的交叉验证:
1. 知识库 (VASP Wiki总结) - knowledge_base
2. Pymatgen/Materials Project 推荐 - pymatgen
3. VASPkit 推荐 - vaspkit
4. Materials Project API 查询 - api_mp
5. 计算历史数据库 (MongoDB) - mongodb

用法:
    python potcar_skill.py parse POSCAR
    python potcar_skill.py recommend Li Fe P O --calc-type standard
    python potcar_skill.py generate Li Fe P O --potcar Li_sv Fe_pv P O -o POTCAR
    python potcar_skill.py workflow POSCAR -o POTCAR
"""

import argparse
import json
import os
import re
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Any, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================================
# 尝试导入完整模块（可选）
# ============================================================================

# 添加src路径
_SKILL_DIR = Path(__file__).parent.parent.parent
_SRC_DIR = _SKILL_DIR / "src"
if _SRC_DIR.exists():
    sys.path.insert(0, str(_SRC_DIR))

# 尝试导入知识库模块
try:
    from vasp_potcar_skill.knowledge.loader import get_loader as get_knowledge_loader
    KNOWLEDGE_AVAILABLE = True
except ImportError:
    KNOWLEDGE_AVAILABLE = False
    get_knowledge_loader = None

# 尝试导入外部API模块
try:
    from vasp_potcar_skill.external.manager import ExternalAPIManager
    from vasp_potcar_skill.external.aflow import AFLOWAPI
    from vasp_potcar_skill.external.oqmd import OQMDAPI
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False
    ExternalAPIManager = None
    AFLOWAPI = None
    OQMDAPI = None

# 尝试导入决策引擎
try:
    from vasp_potcar_skill.engine.decision import DecisionEngine, merge_all_sources
    ENGINE_AVAILABLE = True
except ImportError:
    ENGINE_AVAILABLE = False
    DecisionEngine = None
    merge_all_sources = None


# ============================================================================
# 优化3: API健康检查和缓存
# ============================================================================

class APIHealthCache:
    """API健康状态缓存，避免重复检查不可用的API"""

    def __init__(self, check_interval: float = 300.0):
        """
        Args:
            check_interval: 健康检查间隔（秒），默认5分钟
        """
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._check_interval = check_interval

    def is_available(self, api_name: str) -> Optional[bool]:
        """检查API是否可用（从缓存）"""
        with self._lock:
            if api_name not in self._cache:
                return None  # 未知，需要检查

            entry = self._cache[api_name]
            # 检查是否过期
            if time.time() - entry["timestamp"] > self._check_interval:
                return None  # 过期，需要重新检查

            return entry["available"]

    def set_status(self, api_name: str, available: bool):
        """设置API状态"""
        with self._lock:
            self._cache[api_name] = {
                "available": available,
                "timestamp": time.time()
            }

    def check_and_cache(self, api_name: str, check_func) -> bool:
        """检查API状态并缓存结果"""
        cached = self.is_available(api_name)
        if cached is not None:
            return cached

        # 执行实际检查
        try:
            available = check_func()
        except Exception:
            available = False

        self.set_status(api_name, available)
        return available


# 全局API健康缓存实例
_api_health_cache = APIHealthCache()


def check_aflow_health() -> bool:
    """快速检查AFLOW API是否可用"""
    if AFLOWAPI is None:
        return False
    try:
        import requests
        response = requests.get(
            "http://aflowlib.org/API/aflux/?species(Si),paging(1)",
            timeout=3
        )
        return response.status_code == 200 and response.text.strip() != ""
    except Exception:
        return False


def check_oqmd_health() -> bool:
    """快速检查OQMD API是否可用"""
    if OQMDAPI is None:
        return False
    try:
        import requests
        response = requests.get(
            "https://oqmd.org/oqmdapi/formationenergy?composition=Si&limit=1",
            timeout=3
        )
        return response.status_code == 200
    except Exception:
        return False


def get_available_apis() -> Dict[str, bool]:
    """获取所有API的可用状态（带缓存）"""
    return {
        "aflow": _api_health_cache.check_and_cache("aflow", check_aflow_health),
        "oqmd": _api_health_cache.check_and_cache("oqmd", check_oqmd_health),
    }


# ============================================================================
# 静态数据源（作为回退）
# ============================================================================

# VASP官方推荐 (来自VASP手册和官方网站)
VASP_OFFICIAL_POTCAR = {
    # 碱金属 - 推荐包含半芯态
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    # 碱土金属
    "Be": "Be", "Mg": "Mg_pv", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    # 3d过渡金属
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
    # 4d过渡金属
    "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_pv", "Mo": "Mo_pv",
    "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
    # 5d过渡金属
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
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
    # 氢
    "H": "H",
}

# Pymatgen/Materials Project 推荐
PYMATGEN_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    "Be": "Be_sv", "Mg": "Mg_pv", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
    "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_pv", "Mo": "Mo_pv",
    "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
    "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_pv", "Re": "Re_pv",
    "Os": "Os_pv", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
    "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3",
    "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
    "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
    "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
    "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
    "H": "H",
}

# VASPkit 推荐 (与pymatgen类似，但有细微差别)
VASPKIT_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    "Be": "Be", "Mg": "Mg", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe", "Co": "Co", "Ni": "Ni", "Cu": "Cu", "Zn": "Zn",
    "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_sv", "Mo": "Mo_sv",
    "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
    "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_pv", "Re": "Re_pv",
    "Os": "Os_pv", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
    "La": "La", "Ce": "Ce",
    "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
    "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
    "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
    "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
    "H": "H",
}

# AFLOW 数据库推荐 (无需API key，350万+材料数据)
AFLOW_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    "Be": "Be", "Mg": "Mg", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    "Sc": "Sc_sv", "Ti": "Ti_sv", "V": "V_sv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe", "Co": "Co", "Ni": "Ni", "Cu": "Cu", "Zn": "Zn",
    "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_sv", "Mo": "Mo_sv",
    "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
    "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_sv", "Re": "Re",
    "Os": "Os", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
    "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3",
    "Sm": "Sm_3", "Eu": "Eu_2", "Gd": "Gd_3", "Tb": "Tb_3",
    "Dy": "Dy_3", "Ho": "Ho_3", "Er": "Er_3", "Tm": "Tm_3", "Yb": "Yb_2", "Lu": "Lu_3",
    "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
    "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
    "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
    "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
    "H": "H",
}

# OQMD 数据库推荐 (无需API key，开放量子材料数据库)
OQMD_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    "Be": "Be", "Mg": "Mg", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_sv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
    "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_pv", "Mo": "Mo_pv",
    "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
    "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_pv", "Re": "Re_pv",
    "Os": "Os_pv", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
    "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3",
    "Sm": "Sm_3", "Eu": "Eu_2", "Gd": "Gd_3", "Tb": "Tb_3",
    "Dy": "Dy_3", "Ho": "Ho_3", "Er": "Er_3", "Tm": "Tm_3", "Yb": "Yb_2", "Lu": "Lu_3",
    "B": "B", "C": "C", "N": "N", "O": "O", "F": "F",
    "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl",
    "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br",
    "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I",
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi",
    "H": "H",
}

# 计算类型特定规则
CALC_TYPE_RULES = {
    "standard": {},  # 使用默认
    "accurate": {
        "Ti": "Ti_sv", "V": "V_sv", "Cr": "Cr_pv",
        "Fe": "Fe_pv", "Ni": "Ni_pv", "Cu": "Cu_pv",
    },
    "band": {
        "Ga": "Ga_d", "Ge": "Ge_d", "In": "In_d", "Sn": "Sn_d",
    },
    "dos": {},
    "phonon": {
        "Li": "Li_sv", "Na": "Na_pv",
    },
    "magnetic": {
        "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv",
        "Mn": "Mn_pv", "Cr": "Cr_pv",
    },
    "gw": {},
    "optical": {},
}

# 特殊场景规则
SPECIAL_RULES = {
    "battery": {
        "Li": ("Li_sv", "电池材料中Li参与电化学反应，必须包含1s电子"),
        "Na": ("Na_pv", "钠离子电池需要准确描述Na"),
    },
    "high_pressure": {
        "default_suffix": "_sv",
    },
}


# ============================================================================
# POSCAR 解析
# ============================================================================

def parse_poscar(content: str) -> dict:
    """解析POSCAR文件内容"""
    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        structure = Structure.from_str(content, fmt="poscar")

        elements = []
        seen = set()
        for site in structure:
            symbol = site.specie.symbol
            if symbol not in seen:
                elements.append(symbol)
                seen.add(symbol)

        element_counts = {}
        for el in elements:
            element_counts[el] = sum(1 for site in structure if site.specie.symbol == el)

        try:
            sga = SpacegroupAnalyzer(structure, symprec=0.1)
            space_group = sga.get_space_group_symbol()
            crystal_system = sga.get_crystal_system()
        except:
            space_group = "Unknown"
            crystal_system = "Unknown"

        return {
            "success": True,
            "elements": elements,
            "element_counts": element_counts,
            "total_atoms": structure.num_sites,
            "formula": structure.composition.reduced_formula,
            "space_group": space_group,
            "crystal_system": crystal_system,
            "lattice": {
                "a": round(structure.lattice.a, 4),
                "b": round(structure.lattice.b, 4),
                "c": round(structure.lattice.c, 4),
                "volume": round(structure.lattice.volume, 2),
            }
        }
    except ImportError:
        return parse_poscar_simple(content)
    except Exception as e:
        return {"success": False, "error": str(e)}


def parse_poscar_simple(content: str) -> dict:
    """简单POSCAR解析（不依赖pymatgen）"""
    lines = content.strip().split('\n')

    try:
        line6 = lines[5].split()
        try:
            counts = [int(x) for x in line6]
            elements = None
        except ValueError:
            elements = line6
            counts = [int(x) for x in lines[6].split()]

        if elements:
            element_counts = dict(zip(elements, counts))
        else:
            element_counts = {}
            elements = []

        return {
            "success": True,
            "elements": elements,
            "element_counts": element_counts,
            "total_atoms": sum(counts),
            "formula": "".join(f"{el}{c}" for el, c in zip(elements, counts)) if elements else None,
            "space_group": "Unknown",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# INCAR 解析
# ============================================================================

def parse_incar(content: str) -> dict:
    """解析INCAR并推断计算类型"""
    params = {}

    for line in content.split('\n'):
        line = re.split(r'[#!]', line)[0].strip()
        if not line:
            continue
        match = re.match(r'^\s*(\w+)\s*[=:]\s*(.+?)\s*$', line)
        if match:
            key = match.group(1).upper()
            value = match.group(2).strip()
            params[key] = _parse_incar_value(value)

    calc_type = _infer_calc_type(params)
    precision = _infer_precision(params)

    return {
        "parameters": params,
        "inferred_calc_type": calc_type,
        "inferred_precision": precision,
    }


def _parse_incar_value(value: str) -> Any:
    """解析INCAR参数值"""
    value = value.strip()
    if value.upper() in ['.TRUE.', 'TRUE', 'T']:
        return True
    if value.upper() in ['.FALSE.', 'FALSE', 'F']:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _infer_calc_type(params: dict) -> str:
    """从INCAR参数推断计算类型"""
    algo = str(params.get('ALGO', '')).upper()

    if algo in ['GW0', 'GW', 'SCGW', 'EVGW']:
        return "gw"

    if params.get('LOPTICS'):
        return "optical"

    ibrion = params.get('IBRION', -1)
    if ibrion in [5, 6, 7, 8]:
        return "phonon"

    if params.get('ISPIN', 1) == 2:
        if params.get('LSORBIT') or params.get('MAGMOM'):
            return "magnetic"

    if params.get('ICHARG') == 11:
        return "band"

    if params.get('LORBIT') in [10, 11, 12] and params.get('ICHARG', 0) >= 10:
        return "dos"

    if params.get('EDIFF', 1e-4) < 1e-6:
        return "accurate"

    return "standard"


def _infer_precision(params: dict) -> str:
    """从INCAR参数推断精度"""
    prec = str(params.get('PREC', '')).upper()
    if 'ACCUR' in prec or 'HIGH' in prec:
        return "high"
    if 'LOW' in prec:
        return "low"

    encut = params.get('ENCUT', 0)
    if encut > 600:
        return "high"
    if encut < 300 and encut > 0:
        return "low"

    return "medium"


# ============================================================================
# 赝势推荐 - 多数据源融合
# ============================================================================

def get_multi_source_recommendation(
    elements: list,
    calc_type: str = "standard",
    precision: str = "medium",
    formula: str = None,
    enable_api: bool = True,
) -> dict:
    """
    多数据源赝势推荐

    数据源:
    1. 知识库 (VASP Wiki) - 如果knowledge模块可用
    2. Pymatgen/Materials Project 推荐
    3. VASPkit 推荐
    4. Materials Project API - 如果API模块可用且enable_api=True
    5. 计算类型特化规则

    Args:
        elements: 元素列表
        calc_type: 计算类型
        precision: 精度
        formula: 化学式（用于API查询）
        enable_api: 是否启用API查询

    Returns:
        多数据源推荐结果
    """
    results = {}
    available_sources = []

    # 收集各数据源的推荐
    for el in elements:
        sources = {}

        # 数据源1: 知识库 (VASP Wiki)
        if KNOWLEDGE_AVAILABLE:
            try:
                loader = get_knowledge_loader()
                kb_result = loader.get_element_recommendation(el, calc_type)
                kb_potcar = kb_result.get("recommended", el)
                sources["knowledge_base"] = {
                    "potcar": kb_potcar,
                    "reason": kb_result.get("reason", "VASP Wiki推荐"),
                    "confidence": 0.9
                }
                if "knowledge_base" not in available_sources:
                    available_sources.append("knowledge_base")
            except Exception as e:
                # 回退到静态字典
                kb_potcar = VASP_OFFICIAL_POTCAR.get(el, el)
                sources["knowledge_base"] = {
                    "potcar": kb_potcar,
                    "reason": "VASP官方推荐 (静态)",
                    "confidence": 0.85
                }
        else:
            kb_potcar = VASP_OFFICIAL_POTCAR.get(el, el)
            sources["knowledge_base"] = {
                "potcar": kb_potcar,
                "reason": "VASP官方推荐 (静态)",
                "confidence": 0.85
            }
            if "knowledge_base" not in available_sources:
                available_sources.append("knowledge_base")

        # 数据源2: Pymatgen/MP
        pm_potcar = PYMATGEN_POTCAR.get(el, el)
        sources["pymatgen"] = {
            "potcar": pm_potcar,
            "reason": "Pymatgen/Materials Project标准",
            "confidence": 0.85
        }
        if "pymatgen" not in available_sources:
            available_sources.append("pymatgen")

        # 数据源3: VASPkit
        vk_potcar = VASPKIT_POTCAR.get(el, el)
        sources["vaspkit"] = {
            "potcar": vk_potcar,
            "reason": "VASPkit推荐",
            "confidence": 0.8
        }
        if "vaspkit" not in available_sources:
            available_sources.append("vaspkit")

        # 数据源4: AFLOW (动态API查询，无需API key)
        aflow_potcar = None
        aflow_reason = "AFLOW数据库标准"
        aflow_confidence = 0.8

        # 优化3: 使用健康检查缓存，跳过不可用的API
        api_status = get_available_apis()

        if AFLOWAPI is not None and formula and api_status.get("aflow", False):
            try:
                aflow_api = AFLOWAPI()
                aflow_results = aflow_api.search_by_formula(formula)
                if aflow_results:
                    # 从搜索结果中提取该元素的POTCAR
                    for ref in aflow_results[:5]:  # 检查前5个结果
                        if el in ref.elements:
                            idx = ref.elements.index(el)
                            if idx < len(ref.potcar_symbols):
                                aflow_potcar = ref.potcar_symbols[idx]
                                aflow_reason = f"AFLOW API查询 (ID: {ref.material_id})"
                                aflow_confidence = min(ref.confidence + 0.05, 0.9)
                                break
            except Exception as e:
                _api_health_cache.set_status("aflow", False)  # 标记为不可用

        if aflow_potcar is None:
            aflow_potcar = AFLOW_POTCAR.get(el, el)
            aflow_reason = "AFLOW数据库标准 (静态)"

        sources["aflow"] = {
            "potcar": aflow_potcar,
            "reason": aflow_reason,
            "confidence": aflow_confidence
        }
        if "aflow" not in available_sources:
            available_sources.append("aflow")

        # 数据源5: OQMD (动态API查询，无需API key)
        oqmd_potcar = None
        oqmd_reason = "OQMD数据库标准"
        oqmd_confidence = 0.8

        if OQMDAPI is not None and formula and api_status.get("oqmd", False):
            try:
                oqmd_api = OQMDAPI()
                oqmd_results = oqmd_api.search_by_formula(formula)
                if oqmd_results:
                    # 从搜索结果中提取该元素的POTCAR
                    for ref in oqmd_results[:5]:  # 检查前5个结果
                        if el in ref.elements:
                            idx = ref.elements.index(el)
                            if idx < len(ref.potcar_symbols):
                                oqmd_potcar = ref.potcar_symbols[idx]
                                oqmd_reason = f"OQMD API查询 (ID: {ref.material_id})"
                                oqmd_confidence = min(ref.confidence + 0.05, 0.9)
                                break
            except Exception as e:
                _api_health_cache.set_status("oqmd", False)  # 标记为不可用

        if oqmd_potcar is None:
            oqmd_potcar = OQMD_POTCAR.get(el, el)
            oqmd_reason = "OQMD数据库标准 (静态)"

        sources["oqmd"] = {
            "potcar": oqmd_potcar,
            "reason": oqmd_reason,
            "confidence": oqmd_confidence
        }
        if "oqmd" not in available_sources:
            available_sources.append("oqmd")

        # 数据源6: Materials Project API (可选，需要enable_api)
        if API_AVAILABLE and enable_api and formula:
            try:
                api_manager = ExternalAPIManager({
                    "materials_project": {"enabled": True},
                    "aflow": {"enabled": False},
                    "oqmd": {"enabled": False},
                })
                api_result = api_manager.search_by_formula(formula, timeout=10.0)
                if api_result.has_results:
                    top_ref = api_result.get_top_recommendations(1)[0]
                    if el in top_ref.elements:
                        idx = top_ref.elements.index(el)
                        if idx < len(top_ref.potcar_symbols):
                            api_potcar = top_ref.potcar_symbols[idx]
                            sources["api_mp"] = {
                                "potcar": api_potcar,
                                "reason": f"Materials Project实际使用 (ID: {top_ref.material_id})",
                                "confidence": top_ref.confidence
                            }
                            if "api_mp" not in available_sources:
                                available_sources.append("api_mp")
            except Exception as e:
                pass  # API查询失败，跳过

        # 计算类型特化调整
        type_rules = CALC_TYPE_RULES.get(calc_type, {})
        calc_type_adjusted = None
        if el in type_rules:
            calc_type_adjusted = type_rules[el]
            sources["calc_type_adjust"] = {
                "potcar": calc_type_adjusted,
                "reason": f"{calc_type}计算特化调整",
                "confidence": 0.95
            }

        # 统计各推荐
        vote_count = {}
        for src_name, src_info in sources.items():
            if src_name == "calc_type_adjust":
                continue  # 特化调整单独处理
            pot = src_info["potcar"]
            if pot not in vote_count:
                vote_count[pot] = []
            vote_count[pot].append(src_name)

        # 决策逻辑
        if calc_type_adjusted:
            best_potcar = calc_type_adjusted
            final_reason = f"{calc_type}计算特化调整"
            confidence = "high"
        else:
            # 按支持数量排序
            best_potcar = max(vote_count.keys(), key=lambda x: len(vote_count[x]))
            agreement = len(vote_count[best_potcar])
            total_sources = len([s for s in sources if s != "calc_type_adjust"])

            if agreement == total_sources:
                final_reason = "所有数据源一致推荐"
                confidence = "high"
            elif agreement >= total_sources - 1:
                agreeing = vote_count[best_potcar]
                final_reason = f"{'/'.join(agreeing)}推荐"
                confidence = "high" if agreement >= 3 else "medium"
            else:
                final_reason = f"多数数据源推荐 ({agreement}/{total_sources})"
                confidence = "medium"

        # 高精度调整
        if precision == "high" and not best_potcar.endswith("_sv"):
            variants = get_available_variants(el)
            sv_variant = f"{el}_sv"
            if sv_variant in variants and el in ["Li", "Na", "K", "Ca", "Ti", "V", "Cr", "Mn", "Fe", "Ni"]:
                best_potcar = sv_variant
                final_reason = "高精度计算调整为_sv版本"
                sources["precision_adjust"] = {
                    "potcar": sv_variant,
                    "reason": "高精度计算调整"
                }

        results[el] = {
            "selected": best_potcar,
            "reason": final_reason,
            "confidence": confidence,
            "agreement": f"{len(vote_count.get(best_potcar, []))}/{len([s for s in sources if s != 'calc_type_adjust' and s != 'precision_adjust'])}",
            "sources": sources,
            "all_recommendations": vote_count,
        }

    return {
        "results": results,
        "available_sources": available_sources,
        "api_enabled": API_AVAILABLE and enable_api,
        "knowledge_enabled": KNOWLEDGE_AVAILABLE,
    }


def get_potcar_recommendation(
    elements: list,
    calc_type: str = "standard",
    precision: str = "medium",
    formula: str = None,
    enable_api: bool = False,
) -> dict:
    """获取赝势推荐 (兼容旧接口)"""

    multi_result = get_multi_source_recommendation(
        elements, calc_type, precision, formula, enable_api
    )

    recommendations = {}
    reasoning = {}

    for el in elements:
        info = multi_result["results"][el]
        recommendations[el] = info["selected"]
        reasoning[el] = info["reason"]

    return {
        "elements": elements,
        "potcar_types": recommendations,
        "potcar_symbols": [recommendations[el] for el in elements],
        "calc_type": calc_type,
        "precision": precision,
        "reasoning": reasoning,
        "details": multi_result["results"],
        "available_sources": multi_result["available_sources"],
    }


def get_available_variants(element: str) -> list:
    """获取元素可用的赝势变体"""
    pp_path = os.environ.get("VASP_PP_PATH", "")
    if not pp_path:
        known_variants = {
            "Li": ["Li", "Li_sv"],
            "Na": ["Na", "Na_pv", "Na_sv"],
            "Fe": ["Fe", "Fe_pv", "Fe_sv"],
            "Ti": ["Ti", "Ti_pv", "Ti_sv"],
            "O": ["O", "O_s", "O_h"],
        }
        return known_variants.get(element, [element])

    variants = []
    pp_path = Path(pp_path)

    for func_dir in ["", "potpaw_PBE", "potpaw_GGA", "POT_GGA_PAW_PBE"]:
        search_path = pp_path / func_dir if func_dir else pp_path
        if not search_path.exists():
            continue

        for item in search_path.iterdir():
            if item.is_dir() and item.name.startswith(element):
                name = item.name
                if name == element or name.startswith(f"{element}_"):
                    if name not in variants:
                        variants.append(name)

    return variants if variants else [element]


# ============================================================================
# POTCAR 生成
# ============================================================================

def generate_potcar(
    elements: list,
    potcar_types: dict,
    output_path: Optional[str] = None,
    functional: str = "PBE"
) -> dict:
    """生成POTCAR文件"""

    pp_path = os.environ.get("VASP_PP_PATH", "")
    if not pp_path:
        return {"success": False, "error": "VASP_PP_PATH环境变量未设置"}

    pp_path = Path(pp_path)

    func_dirs = {
        "PBE": ["potpaw_PBE", "POT_GGA_PAW_PBE", ""],
        "LDA": ["potpaw_LDA", "POT_LDA_PAW", ""],
        "PW91": ["potpaw_GGA", "POT_GGA_PAW_PW91", ""],
    }

    search_dirs = func_dirs.get(functional, [""])

    potcar_content = []
    enmax_values = []
    potcar_paths = []

    for el in elements:
        potcar_symbol = potcar_types.get(el, el)
        found = False

        for func_dir in search_dirs:
            search_path = pp_path / func_dir if func_dir else pp_path
            potcar_file = search_path / potcar_symbol / "POTCAR"

            if potcar_file.exists():
                content = potcar_file.read_text()
                potcar_content.append(content)
                potcar_paths.append(str(potcar_file))

                match = re.search(r'ENMAX\s*=\s*([\d.]+)', content)
                if match:
                    enmax_values.append(float(match.group(1)))

                found = True
                break

        if not found:
            return {
                "success": False,
                "error": f"未找到赝势文件: {potcar_symbol}",
                "searched_paths": [str(pp_path / d / potcar_symbol) for d in search_dirs]
            }

    final_content = "".join(potcar_content)

    if output_path:
        Path(output_path).write_text(final_content)

    recommended_encut = max(enmax_values) * 1.3 if enmax_values else None

    return {
        "success": True,
        "elements": elements,
        "potcar_symbols": [potcar_types.get(el, el) for el in elements],
        "potcar_paths": potcar_paths,
        "enmax_values": enmax_values,
        "recommended_encut": round(recommended_encut) if recommended_encut else None,
        "output_path": output_path,
    }


# ============================================================================
# CLI 主入口
# ============================================================================

def cmd_parse(args):
    """解析POSCAR/INCAR"""
    if os.path.isfile(args.file):
        content = Path(args.file).read_text()
    else:
        content = args.file

    if 'ENCUT' in content or 'IBRION' in content or 'EDIFF' in content:
        result = parse_incar(content)
    else:
        result = parse_poscar(content)

    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_recommend(args):
    """获取赝势推荐"""
    result = get_potcar_recommendation(
        elements=args.elements,
        calc_type=args.calc_type,
        precision=args.precision,
        formula=getattr(args, 'formula', None),
        enable_api=args.enable_api,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_generate(args):
    """生成POTCAR"""
    potcar_types = dict(zip(args.elements, args.potcar))
    result = generate_potcar(
        elements=args.elements,
        potcar_types=potcar_types,
        output_path=args.output,
        functional=args.functional,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_variants(args):
    """列出赝势变体"""
    variants = get_available_variants(args.element)
    result = {
        "element": args.element,
        "variants": variants,
        "default": VASP_OFFICIAL_POTCAR.get(args.element, args.element),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_sources(args):
    """显示可用的数据源"""
    sources = {
        "knowledge_base": {
            "available": KNOWLEDGE_AVAILABLE,
            "description": "知识库 (VASP Wiki总结)",
            "type": "动态" if KNOWLEDGE_AVAILABLE else "静态",
        },
        "pymatgen": {
            "available": True,
            "description": "Pymatgen/Materials Project推荐",
            "type": "静态",
        },
        "vaspkit": {
            "available": True,
            "description": "VASPkit推荐",
            "type": "静态",
        },
        "aflow": {
            "available": True,
            "description": "AFLOW数据库 (350万+材料)",
            "type": "动态API" if AFLOWAPI is not None else "静态",
            "api_key": "不需要",
        },
        "oqmd": {
            "available": True,
            "description": "OQMD数据库 (开放量子材料)",
            "type": "动态API" if OQMDAPI is not None else "静态",
            "api_key": "不需要",
        },
        "api_mp": {
            "available": API_AVAILABLE,
            "description": "Materials Project API实时查询",
            "type": "动态API",
            "api_key": "需要 (MP_API_KEY)",
            "enable_flag": "--enable-api",
        },
        "engine": {
            "available": ENGINE_AVAILABLE,
            "description": "决策引擎 (加权融合)",
        },
    }
    print(json.dumps(sources, indent=2, ensure_ascii=False))


def cmd_workflow(args):
    """完整工作流"""

    # 1. 解析POSCAR
    poscar_content = Path(args.poscar).read_text()
    poscar_result = parse_poscar(poscar_content)

    if not poscar_result.get("success"):
        print(json.dumps({"error": "Failed to parse POSCAR", "details": poscar_result}, indent=2))
        return

    elements = poscar_result["elements"]
    formula = poscar_result.get("formula", "")

    print(f"## 结构信息")
    print(f"- 化学式: {poscar_result.get('formula', 'Unknown')}")
    print(f"- 空间群: {poscar_result.get('space_group', 'Unknown')}")
    print(f"- 晶系: {poscar_result.get('crystal_system', 'Unknown')}")
    print(f"- 元素: {', '.join(elements)}")
    print()

    # 2. 获取参数
    calc_type = args.calc_type
    precision = args.precision
    incar_path = args.incar
    output_path = args.output
    enable_api = args.enable_api

    interactive = not (calc_type and precision and output_path)

    if interactive:
        if not incar_path and not calc_type:
            has_incar = input("是否有INCAR文件? (y/n, 默认n): ").strip().lower()
            if has_incar == 'y':
                incar_path = input("请输入INCAR文件路径: ").strip()
                if incar_path and not os.path.isfile(incar_path):
                    print(f"警告: 文件 {incar_path} 不存在，将跳过INCAR解析")
                    incar_path = None

        if not calc_type:
            print("\n可选计算类型:")
            print("  1. standard  - 结构优化/静态计算 (默认)")
            print("  2. accurate  - 高精度计算")
            print("  3. band      - 能带计算")
            print("  4. dos       - 态密度计算")
            print("  5. phonon    - 声子计算")
            print("  6. magnetic  - 磁性计算")
            print("  7. gw        - GW计算")
            print("  8. optical   - 光学性质计算")
            choice = input("请选择计算类型 (1-8, 默认1): ").strip()
            calc_type_map = {
                "1": "standard", "2": "accurate", "3": "band", "4": "dos",
                "5": "phonon", "6": "magnetic", "7": "gw", "8": "optical",
                "": "standard"
            }
            calc_type = calc_type_map.get(choice, "standard")

        if not precision:
            print("\n可选精度:")
            print("  1. low    - 低精度 (快速测试)")
            print("  2. medium - 中等精度 (默认)")
            print("  3. high   - 高精度 (发表级别)")
            choice = input("请选择精度 (1-3, 默认2): ").strip()
            precision_map = {"1": "low", "2": "medium", "3": "high", "": "medium"}
            precision = precision_map.get(choice, "medium")

        print()

    calc_type = calc_type or "standard"
    precision = precision or "medium"

    # 3. 解析INCAR
    incar_inferred = False
    if incar_path and os.path.isfile(incar_path):
        incar_content = Path(incar_path).read_text()
        incar_result = parse_incar(incar_content)
        inferred_calc = incar_result.get("inferred_calc_type", calc_type)
        inferred_prec = incar_result.get("inferred_precision", precision)

        print(f"## INCAR分析结果")
        print(f"- 推断计算类型: {inferred_calc}")
        print(f"- 推断精度: {inferred_prec}")

        if interactive:
            use_inferred = input(f"是否使用推断的设置? (y/n, 默认y): ").strip().lower()
            if use_inferred != 'n':
                calc_type = inferred_calc
                precision = inferred_prec
                incar_inferred = True
        else:
            calc_type = inferred_calc
            precision = inferred_prec
            incar_inferred = True
        print()

    # 4. 获取多数据源推荐
    recommendation = get_potcar_recommendation(
        elements, calc_type, precision, formula, enable_api
    )

    # 5. 输出推荐结果
    print(f"## 赝势推荐")
    print(f"- 计算类型: {calc_type}" + (" (从INCAR推断)" if incar_inferred else ""))
    print(f"- 精度: {precision}")
    print(f"- 可用数据源: {', '.join(recommendation.get('available_sources', []))}")
    print()

    # 显示各数据源的推荐对比
    if "details" in recommendation:
        print("### 各数据源推荐对比")
        print()

        # 动态生成表头
        sources_order = ["knowledge_base", "pymatgen", "vaspkit", "aflow", "oqmd", "api_mp"]
        source_names = {
            "knowledge_base": "知识库",
            "pymatgen": "Pymatgen",
            "vaspkit": "VASPkit",
            "aflow": "AFLOW",
            "oqmd": "OQMD",
            "api_mp": "MP API",
        }

        # 确定实际有哪些数据源
        actual_sources = []
        for el in elements:
            detail = recommendation["details"][el]
            for src in sources_order:
                if src in detail["sources"] and src not in actual_sources:
                    actual_sources.append(src)

        # 生成表头
        header = "| 元素 |"
        separator = "|------|"
        for src in actual_sources:
            header += f" {source_names.get(src, src)} |"
            separator += "--------|"
        header += " 最终选择 | 一致性 |"
        separator += "----------|--------|"

        print(header)
        print(separator)

        for el in elements:
            detail = recommendation["details"][el]
            selected = detail["selected"]
            agreement = detail["agreement"]

            row = f"| {el} |"
            for src in actual_sources:
                if src in detail["sources"]:
                    pot = detail["sources"][src]["potcar"]
                    mark = f"**{pot}**" if pot == selected else pot
                    row += f" {mark} |"
                else:
                    row += " - |"
            row += f" **{selected}** | {agreement} |"
            print(row)

        print()

        print("### 决策理由")
        print()
        for el in elements:
            detail = recommendation["details"][el]
            print(f"**{el}** -> `{detail['selected']}`")
            print(f"  - 理由: {detail['reason']}")
            print(f"  - 置信度: {detail['confidence']}")
            all_recs = detail.get("all_recommendations", {})
            if len(all_recs) > 1:
                print(f"  - 各源推荐分布:")
                for pot, sources in all_recs.items():
                    print(f"    - {pot}: {', '.join(sources)}")
            print()

    # 6. 生成POTCAR
    if interactive and not output_path:
        generate = input("是否生成POTCAR文件? (y/n, 默认y): ").strip().lower()
        if generate != 'n':
            default_output = "POTCAR"
            output_path = input(f"输出路径 (默认 {default_output}): ").strip() or default_output

    if output_path:
        gen_result = generate_potcar(
            elements=elements,
            potcar_types=recommendation["potcar_types"],
            output_path=output_path,
            functional=args.functional,
        )

        if gen_result.get("success"):
            print(f"## POTCAR生成成功")
            print(f"- 输出路径: {gen_result['output_path']}")
            print(f"- 赝势组合: {' + '.join(recommendation['potcar_symbols'])}")

            if gen_result.get('potcar_paths'):
                print(f"- 来源路径:")
                for i, path in enumerate(gen_result['potcar_paths']):
                    print(f"    - {elements[i]}: {path}")

            if gen_result.get('enmax_values'):
                print(f"- ENMAX值: {gen_result['enmax_values']}")
            print(f"- 推荐ENCUT: {gen_result['recommended_encut']} eV")

            print()
            print("### INCAR建议")
            print(f"```")
            print(f"ENCUT = {gen_result['recommended_encut']}")
            enmax_list = gen_result.get('enmax_values', [])
            if enmax_list:
                max_enmax = max(enmax_list)
                print(f"# 或高精度: ENCUT = {round(max_enmax * 1.5)}")
            print(f"```")
        else:
            print(f"## POTCAR生成失败")
            print(f"- 错误: {gen_result.get('error')}")


# ============================================================================
# 优化4: 批量并行处理
# ============================================================================

def process_single_poscar(
    poscar_path: str,
    calc_type: str = "standard",
    precision: str = "medium",
    functional: str = "PBE",
    output_suffix: str = "_POTCAR",
    quiet: bool = False
) -> Dict:
    """
    处理单个POSCAR文件（用于并行处理）

    Args:
        poscar_path: POSCAR文件路径
        calc_type: 计算类型
        precision: 精度
        functional: 泛函类型
        output_suffix: 输出文件后缀
        quiet: 静默模式

    Returns:
        处理结果字典
    """
    result = {
        "poscar": poscar_path,
        "success": False,
        "potcar": None,
        "elements": [],
        "potcar_symbols": [],
        "recommended_encut": None,
        "error": None
    }

    try:
        # 解析POSCAR
        poscar_content = Path(poscar_path).read_text()
        poscar_result = parse_poscar(poscar_content)

        if not poscar_result.get("success"):
            result["error"] = f"解析失败: {poscar_result.get('error')}"
            return result

        elements = poscar_result["elements"]
        formula = poscar_result.get("formula", "")
        result["elements"] = elements
        result["formula"] = formula

        # 获取推荐
        recommendation = get_potcar_recommendation(
            elements, calc_type, precision, formula, enable_api=False
        )
        result["potcar_symbols"] = recommendation["potcar_symbols"]

        # 生成输出路径
        poscar_name = Path(poscar_path).stem
        if poscar_name.endswith("_POSCAR"):
            output_name = poscar_name.replace("_POSCAR", "_POTCAR")
        elif poscar_name == "POSCAR":
            output_name = "POTCAR"
        else:
            output_name = poscar_name + output_suffix

        output_path = str(Path(poscar_path).parent / output_name)

        # 生成POTCAR
        gen_result = generate_potcar(
            elements=elements,
            potcar_types=recommendation["potcar_types"],
            output_path=output_path,
            functional=functional,
        )

        if gen_result.get("success"):
            result["success"] = True
            result["potcar"] = output_path
            result["recommended_encut"] = gen_result.get("recommended_encut")
        else:
            result["error"] = gen_result.get("error")

    except Exception as e:
        result["error"] = str(e)

    return result


def cmd_batch(args):
    """批量并行处理多个POSCAR文件"""
    import glob as glob_module

    # 收集所有POSCAR文件
    poscar_files = []

    for pattern in args.patterns:
        if os.path.isfile(pattern):
            poscar_files.append(pattern)
        else:
            # 作为glob模式处理
            matches = glob_module.glob(pattern, recursive=True)
            poscar_files.extend(matches)

    # 去重并排序
    poscar_files = sorted(set(poscar_files))

    if not poscar_files:
        print("错误: 未找到匹配的POSCAR文件")
        sys.exit(1)

    print(f"## 批量处理 POTCAR 生成")
    print(f"- 找到 {len(poscar_files)} 个POSCAR文件")
    print(f"- 并行线程数: {args.workers}")
    print(f"- 计算类型: {args.calc_type}")
    print(f"- 精度: {args.precision}")
    print()

    # 预先检查API健康状态（只检查一次）
    print("检查API状态...")
    api_status = get_available_apis()
    for api_name, available in api_status.items():
        status = "可用" if available else "不可用(将使用静态数据)"
        print(f"  - {api_name.upper()}: {status}")
    print()

    # 并行处理
    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_poscar = {
            executor.submit(
                process_single_poscar,
                poscar,
                args.calc_type,
                args.precision,
                args.functional,
                "_POTCAR",
                True  # quiet mode
            ): poscar
            for poscar in poscar_files
        }

        # 收集结果
        completed = 0
        for future in as_completed(future_to_poscar):
            poscar = future_to_poscar[future]
            completed += 1
            try:
                result = future.result()
                results.append(result)
                status = "OK" if result["success"] else "FAIL"
                if not args.quiet:
                    print(f"[{completed}/{len(poscar_files)}] {status}: {Path(poscar).name}")
            except Exception as e:
                results.append({
                    "poscar": poscar,
                    "success": False,
                    "error": str(e)
                })
                if not args.quiet:
                    print(f"[{completed}/{len(poscar_files)}] ERROR: {Path(poscar).name} - {e}")

    elapsed = time.time() - start_time

    # 统计结果
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    print()
    print(f"## 处理完成")
    print(f"- 成功: {success_count}/{len(results)}")
    print(f"- 失败: {fail_count}/{len(results)}")
    print(f"- 耗时: {elapsed:.2f} 秒")
    print(f"- 平均: {elapsed/len(results):.2f} 秒/文件")

    # 显示失败的文件
    if fail_count > 0:
        print()
        print("### 失败列表")
        for r in results:
            if not r["success"]:
                print(f"- {r['poscar']}: {r.get('error', '未知错误')}")

    # 输出JSON结果（如果指定）
    if args.json_output:
        with open(args.json_output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n结果已保存到: {args.json_output}")


def main():
    parser = argparse.ArgumentParser(
        description="VASP POTCAR Skill - 多数据源智能赝势选择",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
数据源 (默认启用5个):
  1. 知识库 (VASP Wiki)   - 从VASP官方文档总结的规则
  2. Pymatgen/MP          - Materials Project标准
  3. VASPkit              - VASPkit工具推荐
  4. AFLOW                - AFLOW数据库 (无需API key)
  5. OQMD                 - OQMD数据库 (无需API key)
  6. Materials Project API - 实时查询MP数据库 (需要--enable-api)

示例:
  %(prog)s workflow POSCAR                    # 使用5个默认数据源
  %(prog)s workflow POSCAR -t phonon -o POTCAR
  %(prog)s workflow POSCAR --enable-api       # 额外启用MP API查询
  %(prog)s batch "*.POSCAR" -w 4              # 批量并行处理
  %(prog)s sources                            # 查看所有数据源
  %(prog)s recommend Li Fe P O -t standard
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # parse
    p_parse = subparsers.add_parser("parse", help="解析POSCAR或INCAR")
    p_parse.add_argument("file", help="文件路径或内容")
    p_parse.set_defaults(func=cmd_parse)

    # recommend
    p_rec = subparsers.add_parser("recommend", help="获取赝势推荐")
    p_rec.add_argument("elements", nargs="+", help="元素列表")
    p_rec.add_argument("-t", "--calc-type", default="standard",
                       choices=["standard", "accurate", "band", "dos", "phonon", "magnetic", "gw", "optical"])
    p_rec.add_argument("-p", "--precision", default="medium",
                       choices=["low", "medium", "high"])
    p_rec.add_argument("--formula", help="化学式（用于AFLOW/OQMD动态查询）")
    p_rec.add_argument("--enable-api", action="store_true", help="启用Materials Project API查询")
    p_rec.set_defaults(func=cmd_recommend)

    # generate
    p_gen = subparsers.add_parser("generate", help="生成POTCAR")
    p_gen.add_argument("elements", nargs="+", help="元素列表")
    p_gen.add_argument("-p", "--potcar", nargs="+", required=True, help="赝势类型")
    p_gen.add_argument("-o", "--output", help="输出路径")
    p_gen.add_argument("-f", "--functional", default="PBE")
    p_gen.set_defaults(func=cmd_generate)

    # variants
    p_var = subparsers.add_parser("variants", help="列出赝势变体")
    p_var.add_argument("element", help="元素符号")
    p_var.set_defaults(func=cmd_variants)

    # sources
    p_src = subparsers.add_parser("sources", help="显示可用的数据源")
    p_src.set_defaults(func=cmd_sources)

    # workflow
    p_wf = subparsers.add_parser("workflow", help="完整工作流")
    p_wf.add_argument("poscar", help="POSCAR文件")
    p_wf.add_argument("--incar", help="INCAR文件（可选）")
    p_wf.add_argument("-t", "--calc-type",
                      choices=["standard", "accurate", "band", "dos", "phonon", "magnetic", "gw", "optical"])
    p_wf.add_argument("-p", "--precision",
                      choices=["low", "medium", "high"])
    p_wf.add_argument("-f", "--functional", default="PBE", help="泛函类型")
    p_wf.add_argument("-o", "--output", help="POTCAR输出路径")
    p_wf.add_argument("--enable-api", action="store_true", help="启用Materials Project API查询")
    p_wf.set_defaults(func=cmd_workflow)

    # batch - 优化4: 批量并行处理
    p_batch = subparsers.add_parser("batch", help="批量并行处理多个POSCAR文件")
    p_batch.add_argument("patterns", nargs="+", help="POSCAR文件路径或glob模式 (如 '*.POSCAR' 或 '*_POSCAR')")
    p_batch.add_argument("-w", "--workers", type=int, default=4, help="并行线程数 (默认4)")
    p_batch.add_argument("-t", "--calc-type", default="standard",
                         choices=["standard", "accurate", "band", "dos", "phonon", "magnetic", "gw", "optical"])
    p_batch.add_argument("-p", "--precision", default="medium",
                         choices=["low", "medium", "high"])
    p_batch.add_argument("-f", "--functional", default="PBE", help="泛函类型")
    p_batch.add_argument("-q", "--quiet", action="store_true", help="静默模式，只显示最终统计")
    p_batch.add_argument("--json-output", help="将结果输出为JSON文件")
    p_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
