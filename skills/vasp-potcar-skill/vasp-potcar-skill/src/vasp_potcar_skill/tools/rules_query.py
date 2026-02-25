"""Query pseudopotential selection rules from knowledge base"""

import os
from pathlib import Path
from typing import Any, Optional

from ..knowledge.loader import get_loader


def get_all_rules() -> dict:
    """获取完整的规则知识库"""
    loader = get_loader()
    return {
        "version": loader._load_rules().get("version", "unknown"),
        "elements": loader.get_all_elements(),
        "calculation_types": loader.get_calculation_types(),
        "scenario_rules": loader.get_all_scenarios(),
        "suffix_meanings": loader.get_suffix_meanings(),
        "vasp_recommended_defaults": loader.get_vasp_defaults()
    }


def get_potcar_library_info() -> dict:
    """获取赝势库配置信息"""
    potcar_path = os.environ.get("VASP_PP_PATH", "")

    result = {
        "potcar_path": potcar_path,
        "available_functionals": [],
        "configured": bool(potcar_path)
    }

    if potcar_path:
        pp_path = Path(potcar_path)
        if pp_path.exists():
            for d in pp_path.iterdir():
                if d.is_dir() and d.name.startswith("potpaw_"):
                    result["available_functionals"].append(
                        d.name.replace("potpaw_", "")
                    )

    if not result["available_functionals"]:
        result["available_functionals"] = ["PBE", "LDA", "PW91", "PBE_52", "PBE_54"]
        result["note"] = "未检测到实际赝势库，显示默认支持的泛函类型"

    return result


def query_potcar_rules(
    elements: list[str],
    calculation_type: str = "standard",
    scenario: Optional[str] = None
) -> dict[str, Any]:
    """
    根据元素列表查询赝势选择规则

    Args:
        elements: 元素符号列表
        calculation_type: 计算类型 (standard/accurate/fast/gw/magnetic等)
        scenario: 特定场景（如battery_cathode, perovskite等）

    Returns:
        每个元素的推荐赝势及理由
    """
    loader = get_loader()

    # 如果指定了场景，使用场景规则
    if scenario:
        recommendations = loader.get_scenario_recommendations(elements, scenario)
        scenario_info = loader.get_scenario(scenario)
        general_notes = scenario_info.get("notes", "") if scenario_info else ""
    else:
        recommendations = loader.get_batch_recommendations(elements, calculation_type)
        calc_type_info = loader.get_calculation_types().get(calculation_type, {})
        general_notes = calc_type_info.get("notes", "")

    # 计算最大ENMAX
    enmax_values = [r["enmax"] for r in recommendations.values() if r["enmax"]]
    max_enmax = max(enmax_values) if enmax_values else None

    return {
        "calculation_type": calculation_type,
        "scenario": scenario,
        "recommendations": recommendations,
        "max_enmax": max_enmax,
        "recommended_encut": round(max_enmax * 1.3) if max_enmax else None,
        "general_notes": general_notes
    }


def get_element_potcar_info(
    element: str,
    calculation_type: str = "standard"
) -> dict:
    """
    获取单个元素的详细赝势信息

    Args:
        element: 元素符号
        calculation_type: 计算类型

    Returns:
        元素的完整赝势信息
    """
    loader = get_loader()
    element_info = loader.get_element(element)
    recommendation = loader.get_element_recommendation(element, calculation_type)

    result = {
        "element": element,
        "calculation_type": calculation_type,
        "recommendation": recommendation
    }

    if element_info:
        result["all_variants"] = list(element_info.get("enmax", {}).keys())
        result["enmax_table"] = element_info.get("enmax", {})
        result["notes"] = element_info.get("notes", "")

        # 添加变体描述（如果有）
        variants = element_info.get("variants", [])
        if variants:
            result["variant_descriptions"] = {
                v["name"]: v.get("description", "")
                for v in variants
            }

    return result


def validate_potcar_selection(
    potcar_types: dict[str, str],
    calculation_type: str = "standard"
) -> dict:
    """
    验证赝势选择是否合适

    Args:
        potcar_types: {element: potcar_type} 映射
        calculation_type: 计算类型

    Returns:
        验证结果
    """
    loader = get_loader()
    results = {}
    all_valid = True
    all_warnings = []

    for element, potcar_type in potcar_types.items():
        validation = loader.validate_potcar_choice(element, potcar_type, calculation_type)
        results[element] = validation
        if not validation["valid"]:
            all_valid = False
            all_warnings.extend(validation["warnings"])

    return {
        "valid": all_valid,
        "warnings": all_warnings,
        "element_validations": results
    }


def get_available_scenarios() -> dict:
    """获取所有可用的场景规则"""
    loader = get_loader()
    scenarios = loader.get_all_scenarios()

    return {
        name: {
            "description": info.get("description", ""),
            "notes": info.get("notes", ""),
            "element_overrides": list(info.get("element_overrides", {}).keys())
        }
        for name, info in scenarios.items()
    }


def get_suffix_explanation(suffix: str) -> Optional[dict]:
    """
    获取赝势后缀的含义解释

    Args:
        suffix: 后缀，如 '_pv', '_sv', '_GW' 等

    Returns:
        后缀的详细说明
    """
    loader = get_loader()
    suffix_meanings = loader.get_suffix_meanings()

    # 标准化后缀格式
    if not suffix.startswith("_"):
        suffix = f"_{suffix}"

    return suffix_meanings.get(suffix)


def suggest_potcar_for_material(
    formula: str,
    elements: list[str],
    calculation_type: str = "standard"
) -> dict:
    """
    根据材料化学式智能推荐赝势

    Args:
        formula: 化学式，如 'LiFePO4'
        elements: 元素列表
        calculation_type: 计算类型

    Returns:
        智能推荐结果
    """
    loader = get_loader()

    # 尝试自动检测场景
    detected_scenario = None

    # 检测电池材料
    if 'Li' in elements and ('Fe' in elements or 'Co' in elements or 'Mn' in elements or 'Ni' in elements):
        if 'O' in elements or 'P' in elements:
            detected_scenario = "battery_cathode"

    # 检测钙钛矿
    if len(elements) == 3 and 'O' in elements:
        a_site = {'Ca', 'Sr', 'Ba', 'Pb', 'La'}
        b_site = {'Ti', 'Zr', 'Nb', 'Ta', 'Fe', 'Mn'}
        if any(e in a_site for e in elements) and any(e in b_site for e in elements):
            detected_scenario = "perovskite"

    # 检测磁性材料
    magnetic_elements = {'Fe', 'Co', 'Ni', 'Mn', 'Cr'}
    if any(e in magnetic_elements for e in elements):
        if calculation_type == "standard":
            # 如果没有指定特殊计算类型，建议使用磁性场景
            detected_scenario = detected_scenario or "magnetic"

    # 获取推荐
    if detected_scenario:
        recommendations = loader.get_scenario_recommendations(elements, detected_scenario)
        scenario_info = loader.get_scenario(detected_scenario)
    else:
        recommendations = loader.get_batch_recommendations(elements, calculation_type)
        scenario_info = None

    # 构建POTCAR类型映射
    potcar_types = {el: rec["recommended"] for el, rec in recommendations.items()}

    # 计算ENMAX
    enmax_values = {el: rec["enmax"] for el, rec in recommendations.items() if rec["enmax"]}
    max_enmax = max(enmax_values.values()) if enmax_values else None

    return {
        "formula": formula,
        "elements": elements,
        "calculation_type": calculation_type,
        "detected_scenario": detected_scenario,
        "scenario_description": scenario_info.get("description") if scenario_info else None,
        "potcar_types": potcar_types,
        "recommendations": recommendations,
        "enmax_values": enmax_values,
        "max_enmax": max_enmax,
        "recommended_encut": round(max_enmax * 1.3) if max_enmax else None,
        "notes": scenario_info.get("notes") if scenario_info else None
    }
