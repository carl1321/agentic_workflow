"""
VASPKIT POTCAR 推荐配置

目的：
    提供 vaspkit 工具的 POTCAR 推荐配置作为参考数据源。
    vaspkit 是一个广泛使用的 VASP 前后处理工具。

参考：
    vaspkit 103 功能的默认配置
    https://vaspkit.com/
"""

from typing import Any


# vaspkit 推荐的赝势类型（基于 vaspkit 103 功能的默认配置）
# 这是 vaspkit 的 "recommended" 模式配置
VASPKIT_RECOMMENDED_POTCAR = {
    # 碱金属
    "Li": "Li_sv",
    "Na": "Na_pv",
    "K": "K_sv",
    "Rb": "Rb_sv",
    "Cs": "Cs_sv",

    # 碱土金属
    "Be": "Be_sv",
    "Mg": "Mg_pv",
    "Ca": "Ca_sv",
    "Sr": "Sr_sv",
    "Ba": "Ba_sv",

    # 3d 过渡金属
    "Sc": "Sc_sv",
    "Ti": "Ti_pv",
    "V": "V_pv",
    "Cr": "Cr_pv",
    "Mn": "Mn_pv",
    "Fe": "Fe_pv",
    "Co": "Co",
    "Ni": "Ni_pv",
    "Cu": "Cu_pv",
    "Zn": "Zn",

    # 4d 过渡金属
    "Y": "Y_sv",
    "Zr": "Zr_sv",
    "Nb": "Nb_pv",
    "Mo": "Mo_pv",
    "Tc": "Tc_pv",
    "Ru": "Ru_pv",
    "Rh": "Rh_pv",
    "Pd": "Pd",
    "Ag": "Ag",
    "Cd": "Cd",

    # 5d 过渡金属
    "Hf": "Hf_pv",
    "Ta": "Ta_pv",
    "W": "W_pv",
    "Re": "Re_pv",
    "Os": "Os_pv",
    "Ir": "Ir",
    "Pt": "Pt",
    "Au": "Au",
    "Hg": "Hg",

    # 镧系
    "La": "La",
    "Ce": "Ce",
    "Pr": "Pr_3",
    "Nd": "Nd_3",
    "Pm": "Pm_3",
    "Sm": "Sm_3",
    "Eu": "Eu_2",
    "Gd": "Gd_3",
    "Tb": "Tb_3",
    "Dy": "Dy_3",
    "Ho": "Ho_3",
    "Er": "Er_3",
    "Tm": "Tm_3",
    "Yb": "Yb_2",
    "Lu": "Lu_3",

    # 锕系
    "Ac": "Ac",
    "Th": "Th",
    "Pa": "Pa",
    "U": "U",
    "Np": "Np",
    "Pu": "Pu",

    # 主族元素 - 第2周期
    "H": "H",
    "He": "He",
    "B": "B",
    "C": "C",
    "N": "N",
    "O": "O",
    "F": "F",
    "Ne": "Ne",

    # 主族元素 - 第3周期
    "Al": "Al",
    "Si": "Si",
    "P": "P",
    "S": "S",
    "Cl": "Cl",
    "Ar": "Ar",

    # 主族元素 - 第4周期
    "Ga": "Ga_d",
    "Ge": "Ge_d",
    "As": "As",
    "Se": "Se",
    "Br": "Br",
    "Kr": "Kr",

    # 主族元素 - 第5周期
    "In": "In_d",
    "Sn": "Sn_d",
    "Sb": "Sb",
    "Te": "Te",
    "I": "I",
    "Xe": "Xe",

    # 主族元素 - 第6周期
    "Tl": "Tl_d",
    "Pb": "Pb_d",
    "Bi": "Bi",
    "Po": "Po_d",
    "At": "At",
    "Rn": "Rn",
}

# vaspkit 标准模式配置（使用最基本的赝势）
VASPKIT_STANDARD_POTCAR = {
    # 碱金属
    "Li": "Li",
    "Na": "Na",
    "K": "K_pv",
    "Rb": "Rb_pv",
    "Cs": "Cs_sv",

    # 碱土金属
    "Be": "Be",
    "Mg": "Mg",
    "Ca": "Ca_pv",
    "Sr": "Sr_sv",
    "Ba": "Ba_sv",

    # 3d 过渡金属
    "Sc": "Sc_sv",
    "Ti": "Ti",
    "V": "V",
    "Cr": "Cr",
    "Mn": "Mn",
    "Fe": "Fe",
    "Co": "Co",
    "Ni": "Ni",
    "Cu": "Cu",
    "Zn": "Zn",

    # 其他元素使用标准版本
    # 大多数主族元素默认使用标准赝势
}


def get_vaspkit_potcar_suggestion(
    elements: list[str],
    mode: str = "recommended",
    functional: str = "PBE"
) -> dict[str, Any]:
    """
    获取 vaspkit 风格的 POTCAR 推荐

    Args:
        elements: 元素符号列表
        mode: "recommended" (推荐模式) 或 "standard" (标准模式)
        functional: 泛函类型

    Returns:
        vaspkit 推荐的 POTCAR 配置
    """
    if mode == "recommended":
        potcar_map = VASPKIT_RECOMMENDED_POTCAR
        source = "vaspkit recommended mode"
    else:
        potcar_map = VASPKIT_STANDARD_POTCAR
        source = "vaspkit standard mode"

    suggestions = {}
    potcar_symbols = []

    for element in elements:
        if element in potcar_map:
            potcar_type = potcar_map[element]
        elif element in VASPKIT_RECOMMENDED_POTCAR:
            # 标准模式中未定义的元素，回退到推荐模式
            potcar_type = VASPKIT_RECOMMENDED_POTCAR[element]
        else:
            # 最后回退到元素本身
            potcar_type = element

        suggestions[element] = {
            "symbol": potcar_type,
            "source": source,
            "functional": functional
        }
        potcar_symbols.append(potcar_type)

    return {
        "success": True,
        "mode": mode,
        "functional": functional,
        "suggestions": suggestions,
        "potcar_symbols": potcar_symbols,
        "note": f"Based on vaspkit {mode} POTCAR configuration"
    }


def compare_with_pymatgen(elements: list[str]) -> dict[str, Any]:
    """
    比较 vaspkit 和 pymatgen/MP 的推荐差异

    Args:
        elements: 元素列表

    Returns:
        差异对比结果
    """
    from .pymatgen_helper import MP_RECOMMENDED_POTCAR

    comparison = {}
    differences = []

    for element in elements:
        vaspkit_rec = VASPKIT_RECOMMENDED_POTCAR.get(element, element)
        mp_rec = MP_RECOMMENDED_POTCAR.get(element, element)

        comparison[element] = {
            "vaspkit": vaspkit_rec,
            "pymatgen_mp": mp_rec,
            "match": vaspkit_rec == mp_rec
        }

        if vaspkit_rec != mp_rec:
            differences.append({
                "element": element,
                "vaspkit": vaspkit_rec,
                "pymatgen_mp": mp_rec
            })

    return {
        "comparison": comparison,
        "differences": differences,
        "all_match": len(differences) == 0
    }
