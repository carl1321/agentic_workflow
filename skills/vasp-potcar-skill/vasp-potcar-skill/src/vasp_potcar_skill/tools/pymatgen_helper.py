"""Pymatgen helper for POTCAR suggestions"""

from typing import Any


# pymatgen推荐的赝势映射（基于Materials Project）
MP_POTCAR_FUNCTIONAL_MAPPING = {
    "PBE": "PBE",
    "LDA": "LDA",
    "PW91": "PW91",
    "PBE_52": "PBE_52",
    "PBE_54": "PBE_54"
}

# Materials Project推荐的赝势类型
MP_RECOMMENDED_POTCAR = {
    "Li": "Li_sv",
    "Na": "Na_pv",
    "K": "K_sv",
    "Rb": "Rb_sv",
    "Cs": "Cs_sv",
    "Be": "Be",
    "Mg": "Mg_pv",
    "Ca": "Ca_sv",
    "Sr": "Sr_sv",
    "Ba": "Ba_sv",
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
    "Hf": "Hf_pv",
    "Ta": "Ta_pv",
    "W": "W_pv",
    "Re": "Re_pv",
    "Os": "Os_pv",
    "Ir": "Ir",
    "Pt": "Pt",
    "Au": "Au",
    "Hg": "Hg",
    "Tl": "Tl_d",
    "Pb": "Pb_d",
    "Bi": "Bi_d",
    "Po": "Po_d",
    "At": "At",
    "Ac": "Ac",
    "Th": "Th",
    "Pa": "Pa",
    "U": "U",
    "Np": "Np",
    "Pu": "Pu",
    # 主族元素
    "H": "H",
    "B": "B",
    "C": "C",
    "N": "N",
    "O": "O",
    "F": "F",
    "Al": "Al",
    "Si": "Si",
    "P": "P",
    "S": "S",
    "Cl": "Cl",
    "Ga": "Ga_d",
    "Ge": "Ge_d",
    "As": "As",
    "Se": "Se",
    "Br": "Br",
    "In": "In_d",
    "Sn": "Sn_d",
    "Sb": "Sb",
    "Te": "Te",
    "I": "I",
}


def get_pymatgen_potcar_suggestion(
    elements: list[str],
    functional: str = "PBE"
) -> dict[str, Any]:
    """
    使用pymatgen的推荐逻辑生成POTCAR建议

    Args:
        elements: 元素符号列表
        functional: 泛函类型

    Returns:
        pymatgen推荐的POTCAR配置
    """
    suggestions = {}

    for element in elements:
        if element in MP_RECOMMENDED_POTCAR:
            potcar_type = MP_RECOMMENDED_POTCAR[element]
            suggestions[element] = {
                "recommended": potcar_type,
                "source": "Materials Project推荐",
                "functional": functional
            }
        else:
            suggestions[element] = {
                "recommended": element,
                "source": "默认（无特殊推荐）",
                "functional": functional
            }

    return {
        "functional": functional,
        "suggestions": suggestions,
        "note": "基于Materials Project的推荐设置"
    }
