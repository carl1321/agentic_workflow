"""POTCAR file generator with knowledge base integration"""

import os
from pathlib import Path
from typing import Any, Optional

from ..knowledge.loader import get_loader


# VASP赝势库路径
VASP_PP_PATH = os.environ.get("VASP_PP_PATH", "")


def generate_potcar_file(
    elements: list[str],
    potcar_types: dict[str, str],
    functional: str = "PBE",
    output_path: Optional[str] = None
) -> dict[str, Any]:
    """
    根据配置生成POTCAR文件

    Args:
        elements: 元素顺序列表（必须与POSCAR中的顺序一致）
        potcar_types: 每个元素的赝势类型，如 {'Li': 'Li_sv', 'Fe': 'Fe_pv'}
        functional: 泛函类型
        output_path: 输出路径（可选）

    Returns:
        生成结果
    """
    if not VASP_PP_PATH:
        return {
            "success": False,
            "error": "VASP_PP_PATH环境变量未设置",
            "hint": "请设置VASP_PP_PATH指向VASP赝势库目录，例如: set VASP_PP_PATH=C:/vasp/potpaw"
        }

    # 支持两种目录命名方式: potpaw_PBE 或 PBE
    pp_base = Path(VASP_PP_PATH) / f"potpaw_{functional}"
    if not pp_base.exists():
        pp_base = Path(VASP_PP_PATH) / functional

    if not pp_base.exists():
        return {
            "success": False,
            "error": f"赝势库目录不存在: {pp_base}",
            "available": list_available_functionals()
        }

    # 收集POTCAR内容和ENMAX值
    potcar_contents = []
    enmax_values = {}
    valence_electrons = {}
    missing = []

    for element in elements:
        potcar_type = potcar_types.get(element, element)
        potcar_file = pp_base / potcar_type / "POTCAR"

        if not potcar_file.exists():
            missing.append(potcar_type)
            continue

        with open(potcar_file, 'r') as f:
            content = f.read()
            potcar_contents.append(content)

        # 提取ENMAX和价电子数
        enmax = extract_enmax(content)
        valence = extract_valence(content)

        if enmax:
            enmax_values[element] = enmax
        if valence:
            valence_electrons[element] = valence

    if missing:
        return {
            "success": False,
            "error": f"找不到以下赝势: {missing}",
            "found": [e for e in elements if potcar_types.get(e, e) not in missing],
            "hint": f"请检查赝势库 {pp_base} 中是否存在这些目录"
        }

    # 计算推荐ENCUT
    max_enmax = max(enmax_values.values()) if enmax_values else 0
    recommended_encut = round(max_enmax * 1.3, 0)

    # 计算总价电子数
    total_valence = sum(valence_electrons.values()) if valence_electrons else None

    result = {
        "success": True,
        "elements": elements,
        "potcar_types": potcar_types,
        "functional": functional,
        "enmax_values": enmax_values,
        "valence_electrons": valence_electrons,
        "total_valence": total_valence,
        "max_enmax": max_enmax,
        "recommended_encut": recommended_encut,
        "recommended_encut_accurate": round(max_enmax * 1.5, 0)  # 高精度计算
    }

    # 写入文件
    if output_path:
        combined = "\n".join(potcar_contents)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            f.write(combined)

        result["output_path"] = str(output_file.absolute())
        result["message"] = f"POTCAR已生成: {output_file}"

    return result


def generate_potcar_from_knowledge(
    elements: list[str],
    calculation_type: str = "standard",
    scenario: Optional[str] = None,
    functional: str = "PBE",
    output_path: Optional[str] = None
) -> dict[str, Any]:
    """
    基于知识库自动推荐并生成POTCAR

    Args:
        elements: 元素顺序列表
        calculation_type: 计算类型 (standard/accurate/fast/gw/magnetic等)
        scenario: 特定场景（如battery_cathode, perovskite等）
        functional: 泛函类型
        output_path: 输出路径（可选）

    Returns:
        包含推荐理由和生成结果的完整信息
    """
    loader = get_loader()

    # 获取推荐
    if scenario:
        recommendations = loader.get_scenario_recommendations(elements, scenario)
        scenario_info = loader.get_scenario(scenario)
    else:
        recommendations = loader.get_batch_recommendations(elements, calculation_type)
        scenario_info = None

    # 构建potcar_types
    potcar_types = {el: rec["recommended"] for el, rec in recommendations.items()}

    # 生成POTCAR
    gen_result = generate_potcar_file(
        elements=elements,
        potcar_types=potcar_types,
        functional=functional,
        output_path=output_path
    )

    # 组合结果
    result = {
        "calculation_type": calculation_type,
        "scenario": scenario,
        "scenario_description": scenario_info.get("description") if scenario_info else None,
        "recommendations": recommendations,
        "potcar_types": potcar_types,
        **gen_result
    }

    # 如果生成失败，使用知识库中的ENMAX信息
    if not gen_result["success"]:
        enmax_from_kb = {}
        for el, rec in recommendations.items():
            if rec.get("enmax"):
                enmax_from_kb[el] = rec["enmax"]

        if enmax_from_kb:
            max_enmax = max(enmax_from_kb.values())
            result["enmax_from_knowledge_base"] = enmax_from_kb
            result["recommended_encut_estimate"] = round(max_enmax * 1.3)
            result["note"] = "POTCAR生成失败，但已从知识库获取ENMAX信息供参考"

    return result


def extract_enmax(potcar_content: str) -> Optional[float]:
    """从POTCAR内容中提取ENMAX值"""
    for line in potcar_content.split('\n'):
        if 'ENMAX' in line:
            parts = line.split()
            for i, part in enumerate(parts):
                if part == 'ENMAX':
                    try:
                        return float(parts[i + 2].rstrip(';'))
                    except (IndexError, ValueError):
                        pass
    return None


def extract_valence(potcar_content: str) -> Optional[int]:
    """从POTCAR内容中提取价电子数"""
    for line in potcar_content.split('\n'):
        if 'ZVAL' in line:
            parts = line.split()
            for i, part in enumerate(parts):
                if part == 'ZVAL':
                    try:
                        return int(float(parts[i + 2]))
                    except (IndexError, ValueError):
                        pass
    return None


def list_available_functionals() -> list[str]:
    """列出可用的泛函类型"""
    if not VASP_PP_PATH:
        return []

    pp_path = Path(VASP_PP_PATH)
    functionals = []

    if pp_path.exists():
        for d in pp_path.iterdir():
            if d.is_dir():
                # 支持两种命名方式: potpaw_PBE 或 PBE
                if d.name.startswith("potpaw_"):
                    functionals.append(d.name.replace("potpaw_", ""))
                elif d.name in ("PBE", "LDA", "PW91", "PBE_52", "PBE_54"):
                    functionals.append(d.name)

    return functionals


def validate_and_generate(
    elements: list[str],
    potcar_types: dict[str, str],
    calculation_type: str = "standard",
    functional: str = "PBE",
    output_path: Optional[str] = None
) -> dict[str, Any]:
    """
    验证赝势选择并生成POTCAR

    会检查选择是否符合计算类型的要求，给出警告但不阻止生成

    Args:
        elements: 元素顺序列表
        potcar_types: 每个元素的赝势类型
        calculation_type: 计算类型
        functional: 泛函类型
        output_path: 输出路径

    Returns:
        包含验证结果和生成结果的完整信息
    """
    loader = get_loader()

    # 验证选择
    validations = {}
    warnings = []
    suggestions = []

    for element, potcar_type in potcar_types.items():
        validation = loader.validate_potcar_choice(element, potcar_type, calculation_type)
        validations[element] = validation
        warnings.extend(validation.get("warnings", []))
        suggestions.extend(validation.get("suggestions", []))

    # 生成POTCAR
    gen_result = generate_potcar_file(
        elements=elements,
        potcar_types=potcar_types,
        functional=functional,
        output_path=output_path
    )

    return {
        "validation": {
            "all_valid": len(warnings) == 0,
            "warnings": warnings,
            "suggestions": suggestions,
            "details": validations
        },
        "generation": gen_result
    }


def get_potcar_summary(
    elements: list[str],
    potcar_types: dict[str, str],
    functional: str = "PBE"
) -> dict[str, Any]:
    """
    获取POTCAR配置的摘要信息（不生成文件）

    Args:
        elements: 元素列表
        potcar_types: 赝势类型映射
        functional: 泛函类型

    Returns:
        配置摘要
    """
    loader = get_loader()

    summary = {
        "elements": elements,
        "potcar_types": potcar_types,
        "functional": functional,
        "details": {}
    }

    total_enmax_kb = []
    total_enmax_disk = []

    for element in elements:
        potcar_type = potcar_types.get(element, element)
        element_info = loader.get_element(element)

        detail = {
            "potcar_type": potcar_type,
            "enmax_from_knowledge_base": None,
            "enmax_from_disk": None
        }

        # 从知识库获取ENMAX
        if element_info:
            enmax_kb = element_info.get("enmax", {}).get(potcar_type)
            detail["enmax_from_knowledge_base"] = enmax_kb
            if enmax_kb:
                total_enmax_kb.append(enmax_kb)

        # 从磁盘获取ENMAX
        if VASP_PP_PATH:
            # 支持两种目录命名方式
            potcar_file = Path(VASP_PP_PATH) / f"potpaw_{functional}" / potcar_type / "POTCAR"
            if not potcar_file.exists():
                potcar_file = Path(VASP_PP_PATH) / functional / potcar_type / "POTCAR"
            if potcar_file.exists():
                with open(potcar_file, 'r') as f:
                    content = f.read()
                enmax_disk = extract_enmax(content)
                valence = extract_valence(content)
                detail["enmax_from_disk"] = enmax_disk
                detail["valence_electrons"] = valence
                if enmax_disk:
                    total_enmax_disk.append(enmax_disk)

        summary["details"][element] = detail

    # 计算推荐ENCUT
    if total_enmax_disk:
        max_enmax = max(total_enmax_disk)
        summary["max_enmax"] = max_enmax
        summary["recommended_encut"] = round(max_enmax * 1.3)
        summary["source"] = "disk"
    elif total_enmax_kb:
        max_enmax = max(total_enmax_kb)
        summary["max_enmax"] = max_enmax
        summary["recommended_encut"] = round(max_enmax * 1.3)
        summary["source"] = "knowledge_base"
    else:
        summary["max_enmax"] = None
        summary["recommended_encut"] = None
        summary["source"] = None

    return summary
