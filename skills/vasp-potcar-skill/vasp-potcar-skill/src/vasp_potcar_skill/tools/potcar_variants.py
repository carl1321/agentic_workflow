"""List available POTCAR variants for elements"""

import os
from pathlib import Path
from typing import Any, Optional

from ..knowledge.loader import get_loader


VASP_PP_PATH = os.environ.get("VASP_PP_PATH", "")


def list_element_variants(element: str, functional: str = "PBE") -> dict[str, Any]:
    """
    列出指定元素的所有可用赝势变体

    优先从实际赝势库读取，如果不可用则从知识库获取信息

    Args:
        element: 元素符号
        functional: 泛函类型

    Returns:
        该元素的所有赝势变体及其信息
    """
    result = {
        "element": element,
        "functional": functional,
        "variants": [],
        "from_disk": False,
        "recommended": None
    }

    # 获取知识库推荐
    loader = get_loader()
    element_info = loader.get_element(element)
    recommendation = loader.get_element_recommendation(element, "standard")
    result["recommended"] = recommendation["recommended"]
    result["recommendation_reason"] = recommendation.get("reason", "")

    # 尝试从实际赝势库读取
    if VASP_PP_PATH:
        # 支持两种目录命名方式: potpaw_PBE 或 PBE
        pp_base = Path(VASP_PP_PATH) / f"potpaw_{functional}"
        if not pp_base.exists():
            pp_base = Path(VASP_PP_PATH) / functional
        if pp_base.exists():
            variants = []
            for d in pp_base.iterdir():
                if d.is_dir() and (d.name == element or d.name.startswith(f"{element}_")):
                    potcar_file = d / "POTCAR"
                    if potcar_file.exists():
                        enmax = _extract_enmax_from_file(potcar_file)
                        valence = _extract_valence_from_file(potcar_file)

                        # 从知识库获取描述
                        description = _get_variant_description(element, d.name, element_info)

                        variants.append({
                            "name": d.name,
                            "enmax": enmax,
                            "valence": valence,
                            "description": description,
                            "path": str(d),
                            "is_recommended": d.name == result["recommended"]
                        })

            if variants:
                result["variants"] = sorted(variants, key=lambda x: (not x["is_recommended"], x["name"]))
                result["from_disk"] = True
                return result

    # 使用知识库信息
    if element_info:
        enmax_dict = element_info.get("enmax", {})
        variants_info = element_info.get("variants", [])

        # 创建变体名到描述的映射
        desc_map = {v["name"]: v.get("description", "") for v in variants_info}

        for var_name, enmax in enmax_dict.items():
            description = desc_map.get(var_name, _generate_description_from_suffix(var_name))
            result["variants"].append({
                "name": var_name,
                "enmax": enmax,
                "valence": None,  # 知识库中没有价电子数
                "description": description,
                "is_recommended": var_name == result["recommended"]
            })

        # 按推荐优先排序
        result["variants"] = sorted(result["variants"], key=lambda x: (not x["is_recommended"], x["name"]))
        result["source"] = "knowledge_base"
    else:
        # 回退到VASP默认推荐
        defaults = loader.get_vasp_defaults()
        default_pot = defaults.get(element, element)
        result["variants"] = [{
            "name": default_pot,
            "enmax": None,
            "valence": None,
            "description": "VASP默认推荐",
            "is_recommended": True
        }]
        result["source"] = "vasp_default"
        result["note"] = "该元素不在详细知识库中，使用VASP默认推荐"

    return result


def list_all_variants_for_elements(
    elements: list[str],
    functional: str = "PBE"
) -> dict[str, dict]:
    """
    批量获取多个元素的变体信息

    Args:
        elements: 元素列表
        functional: 泛函类型

    Returns:
        {element: variants_info}
    """
    return {el: list_element_variants(el, functional) for el in elements}


def get_variant_enmax(element: str, variant: str, functional: str = "PBE") -> Optional[float]:
    """
    获取指定赝势变体的ENMAX值

    Args:
        element: 元素符号
        variant: 变体名称
        functional: 泛函类型

    Returns:
        ENMAX值（eV）
    """
    # 先尝试从实际文件读取
    if VASP_PP_PATH:
        potcar_file = Path(VASP_PP_PATH) / f"potpaw_{functional}" / variant / "POTCAR"
        if not potcar_file.exists():
            potcar_file = Path(VASP_PP_PATH) / functional / variant / "POTCAR"
        if potcar_file.exists():
            return _extract_enmax_from_file(potcar_file)

    # 从知识库获取
    loader = get_loader()
    element_info = loader.get_element(element)
    if element_info:
        return element_info.get("enmax", {}).get(variant)

    return None


def _get_variant_description(element: str, variant_name: str, element_info: Optional[dict]) -> str:
    """从知识库获取变体描述，如果没有则根据后缀生成"""
    if element_info:
        variants = element_info.get("variants", [])
        for v in variants:
            if v["name"] == variant_name:
                return v.get("description", "")

    return _generate_description_from_suffix(variant_name)


def _generate_description_from_suffix(variant_name: str) -> str:
    """根据后缀生成描述"""
    loader = get_loader()
    suffix_meanings = loader.get_suffix_meanings()

    # 检查各种后缀
    for suffix, info in suffix_meanings.items():
        if suffix in variant_name:
            return info.get("description", "")

    # 如果没有后缀，是标准赝势
    if "_" not in variant_name:
        return "标准赝势"

    return ""


def _extract_enmax_from_file(potcar_path: Path) -> Optional[float]:
    """从POTCAR文件提取ENMAX"""
    try:
        with open(potcar_path, 'r') as f:
            for line in f:
                if 'ENMAX' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'ENMAX':
                            return float(parts[i + 2].rstrip(';'))
                    break
    except Exception:
        pass
    return None


def _extract_valence_from_file(potcar_path: Path) -> Optional[int]:
    """从POTCAR文件提取价电子数"""
    try:
        with open(potcar_path, 'r') as f:
            for line in f:
                if 'ZVAL' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'ZVAL':
                            return int(float(parts[i + 2]))
                    break
    except Exception:
        pass
    return None


def compare_variants(element: str, variants: list[str], functional: str = "PBE") -> dict:
    """
    比较同一元素的多个赝势变体

    Args:
        element: 元素符号
        variants: 要比较的变体列表
        functional: 泛函类型

    Returns:
        比较结果
    """
    loader = get_loader()
    element_info = loader.get_element(element)

    comparison = {
        "element": element,
        "variants": {},
        "recommendation": loader.get_element_recommendation(element, "standard")
    }

    for variant in variants:
        enmax = get_variant_enmax(element, variant, functional)
        description = _generate_description_from_suffix(variant) if element_info is None else \
                      _get_variant_description(element, variant, element_info)

        comparison["variants"][variant] = {
            "enmax": enmax,
            "description": description,
            "is_recommended": variant == comparison["recommendation"]["recommended"]
        }

    return comparison
