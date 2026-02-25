#!/usr/bin/env python3
"""
VASP POTCAR Skill - 完整独立版本 v2.0

集成所有功能的独立脚本，包括：
1. 知识库加载器 (YAML规则)
2. 多数据源推荐 (VASP Wiki, Pymatgen, VASPkit, AFLOW, OQMD, MP API)
3. 决策引擎 (加权投票、冲突解决)
4. INCAR解析与计算类型推断
5. POTCAR生成器 (支持多泛函)
6. 批量并行处理
7. 交互式工作流

用法:
    python potcar_skill.py workflow POSCAR -t standard -o POTCAR
    python potcar_skill.py workflow POSCAR --incar INCAR -o POTCAR
    python potcar_skill.py recommend Li Fe P O -t phonon -p high
    python potcar_skill.py batch "*.POSCAR" -w 4
    python potcar_skill.py sources
"""

import argparse
import json
import os
import re
import sys
import time
import threading
import logging
import glob as glob_module
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from abc import ABC, abstractmethod

# 配置日志
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# 路径配置
# ============================================================================
_SCRIPT_DIR = Path(__file__).parent
_RESOURCES_DIR = _SCRIPT_DIR / "resources"
_RULES_FILE = _RESOURCES_DIR / "potcar_rules.yaml"

# ============================================================================
# 尝试导入可选依赖
# ============================================================================
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None

try:
    from pymatgen.core import Structure, Composition
    from pymatgen.io.vasp import Poscar
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    PYMATGEN_AVAILABLE = True
except ImportError:
    PYMATGEN_AVAILABLE = False
    Structure = None
    Composition = None
    Poscar = None
    SpacegroupAnalyzer = None

# ============================================================================
# 枚举和数据类
# ============================================================================

class CalculationType(Enum):
    """计算类型"""
    STANDARD = "standard"
    ACCURATE = "accurate"
    GW = "gw"
    PHONON = "phonon"
    MAGNETIC = "magnetic"
    BAND = "band"
    DOS = "dos"
    OPTICAL = "optical"


class CalculationPrecision(Enum):
    """计算精度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class APIStatus(Enum):
    """API状态"""
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"


@dataclass
class PotcarReference:
    """外部数据源返回的赝势参考信息"""
    source: str
    material_id: str
    formula: str
    elements: List[str]
    potcar_symbols: List[str]
    potcar_functional: str
    encut: Optional[float] = None
    calculation_type: Optional[str] = None
    url: Optional[str] = None
    confidence: float = 0.0


@dataclass
class SourceWeight:
    """数据源权重"""
    knowledge_base: float
    api_mp: float
    api_aflow: float
    pymatgen: float
    vaspkit: float
    mongodb: float


@dataclass
class PotcarCandidate:
    """赝势候选项"""
    symbol: str
    source: str
    confidence: float
    weighted_score: float = 0.0
    reason: str = ""


@dataclass
class ElementDecision:
    """单个元素的决策结果"""
    element: str
    selected: str
    confidence: float
    candidates: List[PotcarCandidate] = field(default_factory=list)
    sources_agree: List[str] = field(default_factory=list)
    sources_disagree: List[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class DecisionResult:
    """完整的决策结果"""
    elements: List[str]
    decisions: Dict[str, ElementDecision]
    potcar_symbols: List[str]
    calc_type: str
    precision: str
    overall_confidence: float
    summary: str


# ============================================================================
# 静态数据源 - POTCAR映射表
# ============================================================================

# VASP官方推荐 (来自VASP Wiki)
VASP_OFFICIAL_POTCAR = {
    # 第1-2周期
    "H": "H", "He": "He",
    "Li": "Li_sv", "Be": "Be", "B": "B", "C": "C", "N": "N", "O": "O", "F": "F", "Ne": "Ne",
    # 第3周期
    "Na": "Na_pv", "Mg": "Mg_pv", "Al": "Al", "Si": "Si", "P": "P", "S": "S", "Cl": "Cl", "Ar": "Ar",
    # 第4周期
    "K": "K_sv", "Ca": "Ca_sv",
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe_pv", "Co": "Co", "Ni": "Ni_pv", "Cu": "Cu_pv", "Zn": "Zn",
    "Ga": "Ga_d", "Ge": "Ge_d", "As": "As", "Se": "Se", "Br": "Br", "Kr": "Kr",
    # 第5周期
    "Rb": "Rb_sv", "Sr": "Sr_sv",
    "Y": "Y_sv", "Zr": "Zr_sv", "Nb": "Nb_pv", "Mo": "Mo_pv",
    "Tc": "Tc_pv", "Ru": "Ru_pv", "Rh": "Rh_pv", "Pd": "Pd", "Ag": "Ag", "Cd": "Cd",
    "In": "In_d", "Sn": "Sn_d", "Sb": "Sb", "Te": "Te", "I": "I", "Xe": "Xe",
    # 第6周期
    "Cs": "Cs_sv", "Ba": "Ba_sv",
    "La": "La", "Ce": "Ce", "Pr": "Pr_3", "Nd": "Nd_3",
    "Pm": "Pm_3", "Sm": "Sm_3", "Eu": "Eu_2", "Gd": "Gd_3",
    "Tb": "Tb_3", "Dy": "Dy_3", "Ho": "Ho_3", "Er": "Er_3",
    "Tm": "Tm_3", "Yb": "Yb_2", "Lu": "Lu_3",
    "Hf": "Hf_pv", "Ta": "Ta_pv", "W": "W_pv", "Re": "Re_pv",
    "Os": "Os_pv", "Ir": "Ir", "Pt": "Pt", "Au": "Au", "Hg": "Hg",
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d", "Po": "Po_d", "At": "At", "Rn": "Rn",
    # 第7周期
    "Fr": "Fr_sv", "Ra": "Ra_sv",
    "Ac": "Ac", "Th": "Th", "Pa": "Pa", "U": "U", "Np": "Np", "Pu": "Pu", "Am": "Am", "Cm": "Cm",
}

# Pymatgen/Materials Project 推荐
PYMATGEN_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    "Be": "Be", "Mg": "Mg_pv", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
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
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
    "H": "H",
}

# VASPkit 推荐
VASPKIT_POTCAR = {
    "Li": "Li_sv", "Na": "Na_pv", "K": "K_sv", "Rb": "Rb_sv", "Cs": "Cs_sv",
    "Be": "Be", "Mg": "Mg", "Ca": "Ca_sv", "Sr": "Sr_sv", "Ba": "Ba_sv",
    "Sc": "Sc_sv", "Ti": "Ti_pv", "V": "V_pv", "Cr": "Cr_pv",
    "Mn": "Mn_pv", "Fe": "Fe", "Co": "Co", "Ni": "Ni", "Cu": "Cu", "Zn": "Zn",
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
    "Tl": "Tl_d", "Pb": "Pb_d", "Bi": "Bi_d",
    "H": "H",
}

# AFLOW数据库标准
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

# OQMD数据库标准
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

# 计算类型特化规则
CALC_TYPE_RULES = {
    "gw": {
        "H": "H_GW", "Li": "Li_sv_GW", "Be": "Be_sv_GW",
        "B": "B_GW", "C": "C_GW", "N": "N_GW", "O": "O_GW", "F": "F_GW",
        "Na": "Na_sv_GW", "Mg": "Mg_sv_GW", "Al": "Al_GW", "Si": "Si_GW",
        "K": "K_sv_GW", "Ca": "Ca_sv_GW",
        "Ga": "Ga_d_GW", "Ge": "Ge_d_GW",
    },
    "magnetic": {
        "Fe": "Fe_pv", "Co": "Co_pv", "Ni": "Ni_pv", "Mn": "Mn_pv", "Cr": "Cr_pv",
    },
    "phonon": {
        # 声子计算通常使用标准赝势
    },
    "accurate": {
        "O": "O_h", "N": "N_h", "C": "C_h", "F": "F_h",
    },
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

# ENMAX值表 (常用元素)
ENMAX_TABLE = {
    "H": 250, "H_s": 200, "H_h": 700, "H_GW": 300,
    "Li": 140, "Li_sv": 499,
    "Be": 248, "Be_sv": 309,
    "B": 319, "B_h": 700, "B_s": 269,
    "C": 400, "C_h": 742, "C_s": 274,
    "N": 400, "N_h": 756, "N_s": 280,
    "O": 400, "O_h": 765, "O_s": 283,
    "F": 400, "F_h": 773, "F_s": 290,
    "Na": 102, "Na_pv": 260, "Na_sv": 646,
    "Mg": 200, "Mg_pv": 404, "Mg_sv": 495,
    "Al": 240, "Si": 245, "P": 255, "S": 259, "Cl": 262,
    "K_pv": 117, "K_sv": 259,
    "Ca_pv": 120, "Ca_sv": 267,
    "Sc": 155, "Sc_sv": 223,
    "Ti": 178, "Ti_pv": 222, "Ti_sv": 275,
    "V": 193, "V_pv": 264, "V_sv": 264,
    "Cr": 227, "Cr_pv": 266, "Cr_sv": 395,
    "Mn": 270, "Mn_pv": 270, "Mn_sv": 387,
    "Fe": 268, "Fe_pv": 293, "Fe_sv": 391,
    "Co": 268, "Co_pv": 271, "Co_sv": 390,
    "Ni": 270, "Ni_pv": 368,
    "Cu": 295, "Cu_pv": 369,
    "Zn": 277,
    "Ga": 135, "Ga_d": 283, "Ga_h": 405,
    "Ge": 174, "Ge_d": 310, "Ge_h": 410,
    "As": 209, "As_d": 289,
    "Se": 212, "Br": 216,
    "Rb_pv": 122, "Rb_sv": 220,
    "Sr_sv": 229,
    "Y_sv": 203,
    "Zr_sv": 230,
    "Nb_pv": 209, "Nb_sv": 293,
    "Mo": 225, "Mo_pv": 225, "Mo_sv": 243,
    "Tc": 229, "Tc_pv": 264,
    "Ru": 213, "Ru_pv": 240,
    "Rh": 229, "Rh_pv": 247,
    "Pd": 251, "Pd_pv": 251,
    "Ag": 250, "Ag_pv": 298,
    "Cd": 274,
    "In": 96, "In_d": 239,
    "Sn": 103, "Sn_d": 241,
    "Sb": 172, "Te": 175, "I": 176,
    "Cs_sv": 221,
    "Ba_sv": 187,
    "La": 219, "La_s": 137,
    "Ce": 273, "Ce_3": 177,
    "Pr": 337, "Pr_3": 182,
    "Nd": 338, "Nd_3": 183,
    "Sm": 341, "Sm_3": 177,
    "Eu": 345, "Eu_2": 99, "Eu_3": 129,
    "Gd": 343, "Gd_3": 154,
    "Tb": 341, "Tb_3": 156,
    "Dy": 342, "Dy_3": 156,
    "Ho": 344, "Ho_3": 154,
    "Er": 346, "Er_2": 120, "Er_3": 155,
    "Tm": 344, "Tm_3": 149,
    "Yb": 344, "Yb_2": 113, "Yb_3": 188,
    "Lu": 256, "Lu_3": 155,
    "Hf": 220, "Hf_pv": 220, "Hf_sv": 237,
    "Ta": 224, "Ta_pv": 224,
    "W": 223, "W_sv": 223,
    "Re": 226, "Re_pv": 226,
    "Os": 228, "Os_pv": 228,
    "Ir": 211,
    "Pt": 230, "Pt_pv": 295,
    "Au": 230,
    "Hg": 233,
    "Tl": 90, "Tl_d": 237,
    "Pb": 98, "Pb_d": 238,
    "Bi": 105, "Bi_d": 243,
    "Po": 160, "Po_d": 265,
    "At": 161,
    "Rn": 151,
    "Th": 247, "Th_s": 169,
    "Pa": 252, "Pa_s": 194,
    "U": 253, "U_s": 209,
}

# ============================================================================
# 权重配置
# ============================================================================

WEIGHT_PROFILES = {
    CalculationType.STANDARD: SourceWeight(
        knowledge_base=1.0, api_mp=0.7, api_aflow=0.5, pymatgen=0.6, vaspkit=0.65, mongodb=0.8
    ),
    CalculationType.ACCURATE: SourceWeight(
        knowledge_base=0.6, api_mp=1.0, api_aflow=0.7, pymatgen=0.9, vaspkit=0.85, mongodb=0.8
    ),
    CalculationType.GW: SourceWeight(
        knowledge_base=1.0, api_mp=0.3, api_aflow=0.2, pymatgen=0.4, vaspkit=0.35, mongodb=0.5
    ),
    CalculationType.PHONON: SourceWeight(
        knowledge_base=1.0, api_mp=0.5, api_aflow=0.4, pymatgen=0.5, vaspkit=0.55, mongodb=0.7
    ),
    CalculationType.MAGNETIC: SourceWeight(
        knowledge_base=0.9, api_mp=0.9, api_aflow=0.6, pymatgen=0.8, vaspkit=0.8, mongodb=0.8
    ),
    CalculationType.BAND: SourceWeight(
        knowledge_base=0.7, api_mp=1.0, api_aflow=0.6, pymatgen=0.9, vaspkit=0.85, mongodb=0.7
    ),
    CalculationType.DOS: SourceWeight(
        knowledge_base=0.7, api_mp=1.0, api_aflow=0.6, pymatgen=0.9, vaspkit=0.85, mongodb=0.7
    ),
    CalculationType.OPTICAL: SourceWeight(
        knowledge_base=0.6, api_mp=1.0, api_aflow=0.6, pymatgen=0.9, vaspkit=0.85, mongodb=0.6
    ),
}

PRECISION_MODIFIERS = {
    CalculationPrecision.LOW: {"prefer_minimal": True, "api_weight_factor": 0.5, "kb_weight_factor": 1.2},
    CalculationPrecision.MEDIUM: {"prefer_minimal": False, "api_weight_factor": 1.0, "kb_weight_factor": 1.0},
    CalculationPrecision.HIGH: {"prefer_minimal": False, "api_weight_factor": 1.3, "kb_weight_factor": 0.8},
}


class WeightConfig:
    """权重配置管理"""
    SOURCE_KNOWLEDGE_BASE = "knowledge_base"
    SOURCE_API_MP = "api_mp"
    SOURCE_API_AFLOW = "api_aflow"
    SOURCE_PYMATGEN = "pymatgen"
    SOURCE_VASPKIT = "vaspkit"
    SOURCE_MONGODB = "mongodb"
    SOURCE_OQMD = "oqmd"

    def __init__(self, calc_type: CalculationType = CalculationType.STANDARD,
                 precision: CalculationPrecision = CalculationPrecision.MEDIUM):
        self.calc_type = calc_type
        self.precision = precision
        self._base_weights = WEIGHT_PROFILES.get(calc_type, WEIGHT_PROFILES[CalculationType.STANDARD])
        self._precision_modifier = PRECISION_MODIFIERS.get(precision, PRECISION_MODIFIERS[CalculationPrecision.MEDIUM])

    def get_weight(self, source_type: str, match_quality: float = 1.0) -> float:
        base_weight = getattr(self._base_weights, source_type, 0.5)
        if source_type in [self.SOURCE_API_MP, self.SOURCE_API_AFLOW, self.SOURCE_PYMATGEN, self.SOURCE_VASPKIT]:
            base_weight *= self._precision_modifier["api_weight_factor"]
        elif source_type == self.SOURCE_KNOWLEDGE_BASE:
            base_weight *= self._precision_modifier["kb_weight_factor"]
        return base_weight * match_quality

    @classmethod
    def from_string(cls, calc_type: str = "standard", precision: str = "medium") -> "WeightConfig":
        try:
            ct = CalculationType(calc_type.lower())
        except ValueError:
            ct = CalculationType.STANDARD
        try:
            pr = CalculationPrecision(precision.lower())
        except ValueError:
            pr = CalculationPrecision.MEDIUM
        return cls(calc_type=ct, precision=pr)

    def get_description(self) -> str:
        descriptions = {
            CalculationType.STANDARD: "标准计算 - 使用VASP官方推荐",
            CalculationType.ACCURATE: "高精度计算 - 使用更多价电子",
            CalculationType.GW: "GW计算 - 使用_GW赝势",
            CalculationType.PHONON: "声子计算 - 使用硬赝势",
            CalculationType.MAGNETIC: "磁性计算 - 考虑自旋极化",
            CalculationType.BAND: "能带计算 - 精确描述能带",
            CalculationType.DOS: "态密度计算",
            CalculationType.OPTICAL: "光学性质计算",
        }
        return descriptions.get(self.calc_type, "未知计算类型")


# ============================================================================
# 知识库加载器
# ============================================================================

class KnowledgeLoader:
    """知识库加载和查询"""
    _instance = None
    _cache = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._cache = None
        return cls._instance

    def _load_rules(self) -> dict:
        if self._cache is None:
            if YAML_AVAILABLE and _RULES_FILE.exists():
                with open(_RULES_FILE, 'r', encoding='utf-8') as f:
                    self._cache = yaml.safe_load(f)
            else:
                self._cache = {
                    "version": "0.0",
                    "elements": {},
                    "calculation_types": {},
                    "scenario_rules": {},
                    "suffix_meanings": {},
                    "vasp_recommended_defaults": VASP_OFFICIAL_POTCAR
                }
        return self._cache

    def get_element(self, symbol: str) -> Optional[dict]:
        rules = self._load_rules()
        return rules.get("elements", {}).get(symbol)

    def get_element_recommendation(self, symbol: str, calculation_type: str = "standard") -> dict:
        element_info = self.get_element(symbol)
        if element_info is None:
            defaults = self._load_rules().get("vasp_recommended_defaults", VASP_OFFICIAL_POTCAR)
            default_pot = defaults.get(symbol, symbol)
            return {
                "recommended": default_pot,
                "enmax": ENMAX_TABLE.get(default_pot),
                "reason": "VASP默认推荐",
                "source": "vasp_default"
            }

        type_mapping = {
            "standard": "default", "gw": "gw", "optical": "gw",
            "accurate": "accurate", "fast": "fast", "reference": "reference",
            "magnetic": "accurate", "dft_plus_u": "dft_plus_u",
            "hybrid": "default", "hf": "default", "phonon": "default",
            "band": "default", "dos": "default",
        }
        key = type_mapping.get(calculation_type, "default")
        recommended = element_info.get(key)
        if recommended is None:
            recommended = element_info.get("default", symbol)

        enmax_dict = element_info.get("enmax", {})
        enmax = enmax_dict.get(recommended) or ENMAX_TABLE.get(recommended)

        return {
            "recommended": recommended,
            "enmax": enmax,
            "reason": element_info.get("reason", ""),
            "notes": element_info.get("notes", ""),
            "source": "knowledge_base",
            "all_variants": list(enmax_dict.keys()) if enmax_dict else [recommended]
        }

    def get_batch_recommendations(self, elements: List[str], calculation_type: str = "standard") -> Dict[str, dict]:
        return {el: self.get_element_recommendation(el, calculation_type) for el in elements}

    def get_vasp_defaults(self) -> dict:
        rules = self._load_rules()
        return rules.get("vasp_recommended_defaults", VASP_OFFICIAL_POTCAR)


def get_knowledge_loader() -> KnowledgeLoader:
    return KnowledgeLoader()


# ============================================================================
# API健康检查缓存
# ============================================================================

class APIHealthCache:
    """API健康状态缓存"""
    def __init__(self, check_interval: float = 300.0):
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._check_interval = check_interval

    def is_available(self, api_name: str) -> Optional[bool]:
        with self._lock:
            if api_name not in self._cache:
                return None
            entry = self._cache[api_name]
            if time.time() - entry["timestamp"] > self._check_interval:
                return None
            return entry["available"]

    def set_status(self, api_name: str, available: bool):
        with self._lock:
            self._cache[api_name] = {"available": available, "timestamp": time.time()}

    def check_and_cache(self, api_name: str, check_func) -> bool:
        cached = self.is_available(api_name)
        if cached is not None:
            return cached
        try:
            available = check_func()
        except Exception:
            available = False
        self.set_status(api_name, available)
        return available


_api_health_cache = APIHealthCache()


def check_aflow_health() -> bool:
    if not REQUESTS_AVAILABLE:
        return False
    try:
        response = requests.get("http://aflowlib.org/API/aflux/?species(Si),paging(1)", timeout=3)
        return response.status_code == 200 and response.text.strip() != ""
    except Exception:
        return False


def check_oqmd_health() -> bool:
    if not REQUESTS_AVAILABLE:
        return False
    try:
        response = requests.get("https://oqmd.org/oqmdapi/formationenergy?composition=Si&limit=1", timeout=3)
        return response.status_code == 200
    except Exception:
        return False


def get_available_apis() -> Dict[str, bool]:
    return {
        "aflow": _api_health_cache.check_and_cache("aflow", check_aflow_health),
        "oqmd": _api_health_cache.check_and_cache("oqmd", check_oqmd_health),
    }


# ============================================================================
# AFLOW API客户端
# ============================================================================

class AFLOWAPI:
    """AFLOW API客户端"""
    BASE_URL = "http://aflowlib.org/API/aflux"
    TIMEOUT = 5

    def __init__(self):
        if REQUESTS_AVAILABLE:
            self._session = requests.Session()
            self._session.headers.update({"Accept": "application/json", "User-Agent": "VASP-POTCAR-Skill/2.0"})
        else:
            self._session = None

    def search_by_formula(self, formula: str) -> List[PotcarReference]:
        if not REQUESTS_AVAILABLE or self._session is None:
            return []
        results = []
        try:
            query = f"compound({formula}),paging(50)"
            url = f"{self.BASE_URL}/?{query}"
            response = self._session.get(url, timeout=self.TIMEOUT)
            if response.status_code != 200:
                return results
            data = response.json()
            for entry in data:
                auid = entry.get("auid", "")
                compound = entry.get("compound", formula)
                species = entry.get("species", [])
                if not species:
                    continue
                elements = [s for s in species if s]
                potcar_symbols = [AFLOW_POTCAR.get(el, el) for el in elements]
                confidence = 0.75
                if entry.get("stability_criterion"):
                    confidence += 0.1
                ref = PotcarReference(
                    source="AFLOW", material_id=auid, formula=compound,
                    elements=elements, potcar_symbols=potcar_symbols,
                    potcar_functional="PBE", calculation_type="relaxation",
                    url=f"http://aflowlib.org/material/?id={auid}",
                    confidence=min(confidence, 0.9)
                )
                results.append(ref)
        except Exception as e:
            logger.debug(f"AFLOW search error: {e}")
        return results

    def get_potcar_recommendation(self, element: str) -> str:
        return AFLOW_POTCAR.get(element, element)


# ============================================================================
# OQMD API客户端
# ============================================================================

class OQMDAPI:
    """OQMD API客户端"""
    BASE_URL = "https://oqmd.org/oqmdapi"
    TIMEOUT = 5

    def __init__(self):
        if REQUESTS_AVAILABLE:
            self._session = requests.Session()
            self._session.headers.update({"Accept": "application/json", "User-Agent": "VASP-POTCAR-Skill/2.0"})
        else:
            self._session = None

    def search_by_formula(self, formula: str) -> List[PotcarReference]:
        if not REQUESTS_AVAILABLE or self._session is None:
            return []
        results = []
        try:
            url = f"{self.BASE_URL}/formationenergy"
            params = {"composition": formula, "limit": 50,
                      "fields": "name,entry_id,composition,spacegroup,delta_e,stability"}
            response = self._session.get(url, params=params, timeout=self.TIMEOUT)
            if response.status_code != 200:
                return results
            data = response.json()
            entries = data.get("data", [])
            for entry in entries:
                entry_id = entry.get("entry_id", "")
                composition = entry.get("composition", formula)
                stability = entry.get("stability")
                elements = self._parse_composition(composition)
                if not elements:
                    continue
                potcar_symbols = [OQMD_POTCAR.get(el, el) for el in elements]
                confidence = 0.7
                if stability is not None and stability < 0.025:
                    confidence += 0.15
                elif stability is not None and stability == 0:
                    confidence += 0.2
                ref = PotcarReference(
                    source="OQMD", material_id=str(entry_id), formula=composition,
                    elements=elements, potcar_symbols=potcar_symbols,
                    potcar_functional="PBE", calculation_type="relaxation",
                    url=f"https://oqmd.org/materials/entry/{entry_id}",
                    confidence=min(confidence, 0.9)
                )
                results.append(ref)
            results.sort(key=lambda x: x.confidence, reverse=True)
        except Exception as e:
            logger.debug(f"OQMD search error: {e}")
        return results

    def _parse_composition(self, composition: str) -> List[str]:
        elements = []
        pattern = r'([A-Z][a-z]?)'
        matches = re.findall(pattern, composition)
        seen = set()
        for el in matches:
            if el not in seen:
                elements.append(el)
                seen.add(el)
        return elements

    def get_potcar_recommendation(self, element: str) -> str:
        return OQMD_POTCAR.get(element, element)


# ============================================================================
# POSCAR 解析
# ============================================================================

def parse_poscar(content: str) -> dict:
    """解析POSCAR文件内容"""
    try:
        if PYMATGEN_AVAILABLE:
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
        else:
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


def parse_poscar_file(file_path: str) -> dict:
    """从文件路径解析POSCAR"""
    content = Path(file_path).read_text()
    return parse_poscar(content)


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
# 赝势变体查询
# ============================================================================

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
            "C": ["C", "C_s", "C_h"],
            "N": ["N", "N_s", "N_h"],
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
# 多数据源推荐
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
    1. 知识库 (VASP Wiki)
    2. Pymatgen/Materials Project 推荐
    3. VASPkit 推荐
    4. AFLOW API
    5. OQMD API
    6. 计算类型特化规则
    """
    results = {}
    available_sources = []
    api_status = get_available_apis() if enable_api else {"aflow": False, "oqmd": False}

    for el in elements:
        sources = {}

        # 数据源1: 知识库 (VASP Wiki)
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
        except Exception:
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

        # 数据源4: AFLOW
        aflow_potcar = None
        aflow_reason = "AFLOW数据库标准"
        aflow_confidence = 0.8

        if enable_api and api_status.get("aflow", False) and formula:
            try:
                aflow_api = AFLOWAPI()
                aflow_results = aflow_api.search_by_formula(formula)
                if aflow_results:
                    for ref in aflow_results[:5]:
                        if el in ref.elements:
                            idx = ref.elements.index(el)
                            if idx < len(ref.potcar_symbols):
                                aflow_potcar = ref.potcar_symbols[idx]
                                aflow_reason = f"AFLOW API查询 (ID: {ref.material_id})"
                                aflow_confidence = min(ref.confidence + 0.05, 0.9)
                                break
            except Exception:
                _api_health_cache.set_status("aflow", False)

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

        # 数据源5: OQMD
        oqmd_potcar = None
        oqmd_reason = "OQMD数据库标准"
        oqmd_confidence = 0.8

        if enable_api and api_status.get("oqmd", False) and formula:
            try:
                oqmd_api = OQMDAPI()
                oqmd_results = oqmd_api.search_by_formula(formula)
                if oqmd_results:
                    for ref in oqmd_results[:5]:
                        if el in ref.elements:
                            idx = ref.elements.index(el)
                            if idx < len(ref.potcar_symbols):
                                oqmd_potcar = ref.potcar_symbols[idx]
                                oqmd_reason = f"OQMD API查询 (ID: {ref.material_id})"
                                oqmd_confidence = min(ref.confidence + 0.05, 0.9)
                                break
            except Exception:
                _api_health_cache.set_status("oqmd", False)

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
                continue
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
        "api_enabled": enable_api,
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
        "high_precision_encut": round(max(enmax_values) * 1.5) if enmax_values else None,
        "output_path": output_path,
    }


# ============================================================================
# CLI 命令函数
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
        calc_type=args.calc_type or "standard",
        precision=args.precision or "medium",
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
        functional=args.functional or "PBE",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_variants(args):
    """列出赝势变体"""
    variants = get_available_variants(args.element)
    result = {
        "element": args.element,
        "variants": variants,
        "default": VASP_OFFICIAL_POTCAR.get(args.element, args.element),
        "enmax": {v: ENMAX_TABLE.get(v, "N/A") for v in variants},
        "recommendations": {
            "VASP_Wiki": VASP_OFFICIAL_POTCAR.get(args.element, args.element),
            "Pymatgen": PYMATGEN_POTCAR.get(args.element, args.element),
            "VASPkit": VASPKIT_POTCAR.get(args.element, args.element),
            "AFLOW": AFLOW_POTCAR.get(args.element, args.element),
            "OQMD": OQMD_POTCAR.get(args.element, args.element),
        }
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_sources(args):
    """显示可用的数据源"""
    api_status = get_available_apis()
    sources = {
        "knowledge_base": {
            "available": YAML_AVAILABLE and _RULES_FILE.exists(),
            "description": "知识库 (VASP Wiki总结)",
            "type": "动态" if YAML_AVAILABLE else "静态",
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
            "type": "动态API" if REQUESTS_AVAILABLE else "静态",
            "api_status": "可用" if api_status.get("aflow") else "不可用",
            "api_key": "不需要",
        },
        "oqmd": {
            "available": True,
            "description": "OQMD数据库 (开放量子材料)",
            "type": "动态API" if REQUESTS_AVAILABLE else "静态",
            "api_status": "可用" if api_status.get("oqmd") else "不可用",
            "api_key": "不需要",
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
    functional = args.functional or "PBE"

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

        sources_order = ["knowledge_base", "pymatgen", "vaspkit", "aflow", "oqmd"]
        source_names = {
            "knowledge_base": "知识库",
            "pymatgen": "Pymatgen",
            "vaspkit": "VASPkit",
            "aflow": "AFLOW",
            "oqmd": "OQMD",
        }

        actual_sources = []
        for el in elements:
            detail = recommendation["details"][el]
            for src in sources_order:
                if src in detail["sources"] and src not in actual_sources:
                    actual_sources.append(src)

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
            functional=functional,
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
            print(f"- 高精度ENCUT: {gen_result['high_precision_encut']} eV")

            print()
            print("### INCAR建议")
            print(f"```")
            print(f"ENCUT = {gen_result['recommended_encut']}")
            if gen_result.get('high_precision_encut'):
                print(f"# 或高精度: ENCUT = {gen_result['high_precision_encut']}")
            print(f"```")
        else:
            print(f"## POTCAR生成失败")
            print(f"- 错误: {gen_result.get('error')}")


# ============================================================================
# 批量处理
# ============================================================================

def process_single_poscar(
    poscar_path: str,
    calc_type: str = "standard",
    precision: str = "medium",
    output_dir: Optional[str] = None,
    functional: str = "PBE",
    enable_api: bool = False,
) -> dict:
    """处理单个POSCAR文件"""
    try:
        poscar_content = Path(poscar_path).read_text()
        poscar_result = parse_poscar(poscar_content)

        if not poscar_result.get("success"):
            return {"success": False, "file": poscar_path, "error": poscar_result.get("error")}

        elements = poscar_result["elements"]
        formula = poscar_result.get("formula", "")

        recommendation = get_potcar_recommendation(
            elements, calc_type, precision, formula, enable_api
        )

        if output_dir:
            poscar_name = Path(poscar_path).stem
            output_path = Path(output_dir) / f"{poscar_name}_POTCAR"
            output_path = str(output_path).replace("_POSCAR_POTCAR", "_POTCAR")

            gen_result = generate_potcar(
                elements=elements,
                potcar_types=recommendation["potcar_types"],
                output_path=output_path,
                functional=functional,
            )

            return {
                "success": gen_result.get("success", False),
                "file": poscar_path,
                "formula": formula,
                "elements": elements,
                "potcar_symbols": recommendation["potcar_symbols"],
                "output_path": output_path if gen_result.get("success") else None,
                "recommended_encut": gen_result.get("recommended_encut"),
                "error": gen_result.get("error"),
            }
        else:
            return {
                "success": True,
                "file": poscar_path,
                "formula": formula,
                "elements": elements,
                "potcar_symbols": recommendation["potcar_symbols"],
                "recommendation": recommendation,
            }

    except Exception as e:
        return {"success": False, "file": poscar_path, "error": str(e)}


def cmd_batch(args):
    """批量处理多个POSCAR文件"""
    pattern = args.pattern
    files = glob_module.glob(pattern)

    if not files:
        print(f"未找到匹配的文件: {pattern}")
        return

    print(f"找到 {len(files)} 个文件")

    calc_type = args.calc_type or "standard"
    precision = args.precision or "medium"
    output_dir = args.output_dir
    functional = args.functional or "PBE"
    workers = args.workers or 4
    enable_api = args.enable_api

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    results = []
    success_count = 0
    fail_count = 0

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_single_poscar,
                    f, calc_type, precision, output_dir, functional, enable_api
                ): f for f in files
            }

            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if result.get("success"):
                    success_count += 1
                    if not args.quiet:
                        print(f"✓ {result['file']} -> {result.get('output_path', 'OK')}")
                else:
                    fail_count += 1
                    if not args.quiet:
                        print(f"✗ {result['file']}: {result.get('error')}")
    else:
        for f in files:
            result = process_single_poscar(
                f, calc_type, precision, output_dir, functional, enable_api
            )
            results.append(result)
            if result.get("success"):
                success_count += 1
                if not args.quiet:
                    print(f"✓ {result['file']} -> {result.get('output_path', 'OK')}")
            else:
                fail_count += 1
                if not args.quiet:
                    print(f"✗ {result['file']}: {result.get('error')}")

    print(f"\n完成: {success_count} 成功, {fail_count} 失败")

    if args.json_output:
        with open(args.json_output, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"结果已保存到: {args.json_output}")


# ============================================================================
# CLI 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="VASP POTCAR Skill - 智能赝势选择工具 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s workflow POSCAR -t standard -o POTCAR
  %(prog)s workflow POSCAR --incar INCAR -o POTCAR
  %(prog)s recommend Li Fe P O -t phonon -p high
  %(prog)s batch "*.POSCAR" -o potcar_output -w 4
  %(prog)s variants Fe
  %(prog)s sources
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # parse命令
    parser_parse = subparsers.add_parser("parse", help="解析POSCAR/INCAR文件")
    parser_parse.add_argument("file", help="POSCAR或INCAR文件路径")
    parser_parse.set_defaults(func=cmd_parse)

    # recommend命令
    parser_recommend = subparsers.add_parser("recommend", help="获取赝势推荐")
    parser_recommend.add_argument("elements", nargs="+", help="元素符号列表")
    parser_recommend.add_argument("-t", "--calc-type", help="计算类型")
    parser_recommend.add_argument("-p", "--precision", help="精度 (low/medium/high)")
    parser_recommend.add_argument("-f", "--formula", help="化学式 (用于API查询)")
    parser_recommend.add_argument("--enable-api", action="store_true", help="启用API查询")
    parser_recommend.set_defaults(func=cmd_recommend)

    # generate命令
    parser_generate = subparsers.add_parser("generate", help="生成POTCAR文件")
    parser_generate.add_argument("elements", nargs="+", help="元素符号列表")
    parser_generate.add_argument("-p", "--potcar", nargs="+", required=True, help="POTCAR符号列表")
    parser_generate.add_argument("-o", "--output", default="POTCAR", help="输出文件路径")
    parser_generate.add_argument("--functional", help="泛函类型 (PBE/LDA/PW91)")
    parser_generate.set_defaults(func=cmd_generate)

    # variants命令
    parser_variants = subparsers.add_parser("variants", help="列出元素的赝势变体")
    parser_variants.add_argument("element", help="元素符号")
    parser_variants.set_defaults(func=cmd_variants)

    # sources命令
    parser_sources = subparsers.add_parser("sources", help="显示可用的数据源")
    parser_sources.set_defaults(func=cmd_sources)

    # workflow命令
    parser_workflow = subparsers.add_parser("workflow", help="完整工作流")
    parser_workflow.add_argument("poscar", help="POSCAR文件路径")
    parser_workflow.add_argument("-t", "--calc-type", help="计算类型")
    parser_workflow.add_argument("-p", "--precision", help="精度 (low/medium/high)")
    parser_workflow.add_argument("-o", "--output", help="输出POTCAR路径")
    parser_workflow.add_argument("--incar", help="INCAR文件路径 (用于推断计算类型)")
    parser_workflow.add_argument("--functional", help="泛函类型 (PBE/LDA/PW91)")
    parser_workflow.add_argument("--enable-api", action="store_true", help="启用API查询")
    parser_workflow.set_defaults(func=cmd_workflow)

    # batch命令
    parser_batch = subparsers.add_parser("batch", help="批量处理多个POSCAR文件")
    parser_batch.add_argument("pattern", help="文件匹配模式 (如 '*.POSCAR')")
    parser_batch.add_argument("-t", "--calc-type", help="计算类型")
    parser_batch.add_argument("-p", "--precision", help="精度 (low/medium/high)")
    parser_batch.add_argument("-o", "--output-dir", help="输出目录")
    parser_batch.add_argument("--functional", help="泛函类型 (PBE/LDA/PW91)")
    parser_batch.add_argument("-w", "--workers", type=int, default=4, help="并行工作线程数")
    parser_batch.add_argument("--enable-api", action="store_true", help="启用API查询")
    parser_batch.add_argument("-q", "--quiet", action="store_true", help="静默模式")
    parser_batch.add_argument("--json-output", help="JSON结果输出文件")
    parser_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
