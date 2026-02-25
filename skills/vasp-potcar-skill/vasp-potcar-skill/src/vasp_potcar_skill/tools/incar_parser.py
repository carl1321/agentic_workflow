"""
INCAR 解析器

目的：
    解析 INCAR 文件内容，推断计算类型和精度需求。
    用于自动选择合适的赝势配置。

参考：
    - pymatgen.io.vasp.inputs.Incar
    - vaspkit INCAR generation
    - VASP Wiki: https://www.vasp.at/wiki/
"""

import re
from typing import Optional, Any
from dataclasses import dataclass


@dataclass
class IncarAnalysis:
    """INCAR 分析结果"""
    calc_type: str           # 推断的计算类型
    precision: str           # 推断的精度需求
    confidence: float        # 推断置信度
    indicators: list[str]    # 判断依据
    parameters: dict         # 解析出的关键参数
    suggestions: list[str]   # 赝势选择建议


def parse_incar_content(incar_content: str) -> dict:
    """
    解析 INCAR 文件内容

    Args:
        incar_content: INCAR 文件的完整文本内容

    Returns:
        解析结果字典，包含参数和推断的计算类型
    """
    # 解析所有参数
    parameters = _extract_parameters(incar_content)

    # 推断计算类型
    calc_type, type_indicators = _infer_calculation_type(parameters)

    # 推断精度需求
    precision, prec_indicators = _infer_precision(parameters)

    # 生成赝势建议
    suggestions = _generate_potcar_suggestions(calc_type, precision, parameters)

    # 提取关键参数摘要
    key_params = _extract_key_parameters(parameters)

    return {
        "parameters": parameters,
        "key_parameters": key_params,
        "inferred_calc_type": calc_type,
        "inferred_precision": precision,
        "confidence": _calculate_confidence(type_indicators, prec_indicators),
        "indicators": {
            "calc_type_reasons": type_indicators,
            "precision_reasons": prec_indicators
        },
        "potcar_suggestions": suggestions,
        "summary": _generate_summary(calc_type, precision, type_indicators),
        "warnings": _check_common_issues(parameters)
    }


def _extract_parameters(content: str) -> dict:
    """从 INCAR 内容提取参数"""
    params = {}

    # 处理续行（行末的 \）
    content = re.sub(r'\\\s*\n', ' ', content)

    # 移除注释并提取参数
    lines = []
    for line in content.split('\n'):
        # 移除 # 或 ! 开头的注释
        line = re.split(r'[#!]', line)[0].strip()
        if line:
            lines.append(line)

    # 解析参数
    for line in lines:
        # 支持 = 或 : 作为分隔符
        # 支持一行多个参数（用分号分隔）
        for part in line.split(';'):
            part = part.strip()
            if not part:
                continue

            match = re.match(r'^\s*(\w+)\s*[=:]\s*(.+?)\s*$', part)
            if match:
                key = match.group(1).upper()
                value = match.group(2).strip()

                # 尝试转换类型
                params[key] = _parse_value(value)

    return params


def _parse_value(value: str) -> Any:
    """解析参数值，转换为适当的类型"""
    value = value.strip()

    # 布尔值
    if value.upper() in ['.TRUE.', 'TRUE', 'T', '.T.']:
        return True
    if value.upper() in ['.FALSE.', 'FALSE', 'F', '.F.']:
        return False

    # 数组值（如 MAGMOM, LDAUU 等）
    # 检测 * 重复语法，如 "4*0.0 2*5.0"
    if '*' in value or len(value.split()) > 1:
        return _parse_array_value(value)

    # 整数
    try:
        return int(value)
    except ValueError:
        pass

    # 浮点数
    try:
        return float(value)
    except ValueError:
        pass

    # 字符串（移除引号）
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    return value


def _parse_array_value(value: str) -> list:
    """解析数组值，支持 VASP 的 N*value 语法"""
    result = []
    parts = value.split()

    for part in parts:
        if '*' in part:
            # N*value 语法
            count_str, val_str = part.split('*', 1)
            try:
                count = int(count_str)
                val = _parse_single_value(val_str)
                result.extend([val] * count)
            except ValueError:
                result.append(part)
        else:
            result.append(_parse_single_value(part))

    return result


def _parse_single_value(value: str) -> Any:
    """解析单个值"""
    value = value.strip()

    if value.upper() in ['.TRUE.', 'TRUE', 'T', '.T.']:
        return True
    if value.upper() in ['.FALSE.', 'FALSE', 'F', '.F.']:
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


def _infer_calculation_type(params: dict) -> tuple[str, list[str]]:
    """
    从参数推断计算类型

    Returns:
        (calc_type, indicators)
    """
    indicators = []

    # GW 计算检测
    algo = str(params.get('ALGO', '')).upper()
    if algo in ['GW0', 'GW', 'SCGW', 'SCGW0', 'EVGW', 'EVGW0', 'QPGW', 'QPGW0']:
        indicators.append(f"ALGO={algo} indicates GW calculation")
        return "gw", indicators

    if params.get('LHFCALC', False) or algo == 'CHI':
        indicators.append("Hybrid functional or response function calculation")
        return "gw", indicators

    # 光学性质检测
    if params.get('LOPTICS', False):
        indicators.append("LOPTICS=.TRUE. indicates optical properties calculation")
        return "optical", indicators

    if params.get('CSHIFT') is not None or params.get('NEDOS', 0) > 2000:
        indicators.append("High NEDOS or CSHIFT suggests optical/DOS calculation")
        return "optical", indicators

    # 声子计算检测
    ibrion = params.get('IBRION', -1)
    if ibrion in [5, 6, 7, 8]:
        indicators.append(f"IBRION={ibrion} indicates phonon/finite differences calculation")
        return "phonon", indicators

    if params.get('LEPSILON', False) or params.get('LCALCEPS', False):
        indicators.append("LEPSILON/LCALCEPS indicates dielectric/phonon calculation")
        return "phonon", indicators

    # NEB/过渡态计算检测
    if params.get('IMAGES') is not None or params.get('LCLIMB', False):
        indicators.append("IMAGES/LCLIMB indicates NEB transition state calculation")
        return "accurate", indicators

    # 分子动力学检测
    if ibrion == 0 or params.get('MDALGO') is not None:
        indicators.append("IBRION=0 or MDALGO indicates molecular dynamics")
        # MD 通常使用标准赝势
        return "standard", indicators

    # 磁性计算检测
    ispin = params.get('ISPIN', 1)
    if ispin == 2:
        indicators.append("ISPIN=2 indicates spin-polarized calculation")
        # 检查是否有其他磁性相关设置
        if params.get('LSORBIT', False):
            indicators.append("LSORBIT=.TRUE. indicates spin-orbit coupling")
            return "magnetic", indicators
        if params.get('LNONCOLLINEAR', False):
            indicators.append("Non-collinear magnetism")
            return "magnetic", indicators
        if params.get('LORBIT') is not None:
            indicators.append("LORBIT present for magnetic analysis")
            return "magnetic", indicators

    # 能带计算检测
    icharg = params.get('ICHARG', 0)
    if icharg == 11:
        indicators.append("ICHARG=11 indicates band structure calculation")
        return "band", indicators

    # 态密度计算检测
    if params.get('LORBIT') in [10, 11, 12, 13, 14] and icharg >= 10:
        indicators.append(f"LORBIT={params.get('LORBIT')} with ICHARG>=10 indicates DOS calculation")
        return "dos", indicators

    nedos = params.get('NEDOS', 301)
    if nedos > 1000 and icharg >= 10:
        indicators.append(f"High NEDOS={nedos} suggests DOS calculation")
        return "dos", indicators

    # DFT+U 检测
    if params.get('LDAU', False) or params.get('LDAUTYPE') is not None:
        indicators.append("DFT+U calculation detected")
        # DFT+U 通常需要较好的赝势
        if ibrion in [1, 2, 3]:
            return "accurate", indicators

    # 结构优化/静态计算
    if ibrion in [1, 2, 3]:
        indicators.append(f"IBRION={ibrion} indicates geometry optimization")
        # 检查是否高精度
        if params.get('EDIFF', 1e-4) < 1e-6 or params.get('EDIFFG', -0.02) < -0.005:
            indicators.append("Tight convergence criteria suggest accurate calculation")
            return "accurate", indicators
        return "standard", indicators

    if ibrion == -1 or icharg in [0, 1, 2]:
        indicators.append("Static calculation or SCF")
        return "standard", indicators

    # 默认
    indicators.append("No specific calculation type detected, assuming standard")
    return "standard", indicators


def _infer_precision(params: dict) -> tuple[str, list[str]]:
    """
    从参数推断精度需求

    Returns:
        (precision, indicators)
    """
    indicators = []

    # 从 PREC 参数判断
    prec = str(params.get('PREC', '')).upper()
    if prec in ['ACCURATE', 'HIGH', 'ACCURA']:
        indicators.append(f"PREC={prec} indicates high precision")
        return "high", indicators
    elif prec in ['LOW', 'MEDIUM', 'MED']:
        indicators.append(f"PREC={prec} indicates {prec.lower()} precision")
        return prec.lower() if prec != 'MED' else 'medium', indicators

    # 从 ENCUT 判断
    encut = params.get('ENCUT', 0)
    if encut > 600:
        indicators.append(f"High ENCUT={encut} eV suggests high precision")
        return "high", indicators
    elif encut > 0 and encut < 300:
        indicators.append(f"Low ENCUT={encut} eV suggests quick test")
        return "low", indicators

    # 从收敛标准判断
    ediff = params.get('EDIFF', 1e-4)
    if isinstance(ediff, (int, float)):
        if ediff < 1e-7:
            indicators.append(f"Tight EDIFF={ediff} suggests high precision")
            return "high", indicators
        elif ediff > 1e-3:
            indicators.append(f"Loose EDIFF={ediff} suggests low precision")
            return "low", indicators

    # 从 EDIFFG 判断
    ediffg = params.get('EDIFFG')
    if isinstance(ediffg, (int, float)):
        if ediffg < 0 and abs(ediffg) < 0.005:
            indicators.append(f"Tight EDIFFG={ediffg} suggests high precision forces")
            return "high", indicators

    # K点密度（如果有）
    kspacing = params.get('KSPACING')
    if kspacing is not None:
        if kspacing < 0.2:
            indicators.append(f"Dense KSPACING={kspacing} suggests high precision")
            return "high", indicators
        elif kspacing > 0.5:
            indicators.append(f"Sparse KSPACING={kspacing} suggests low precision")
            return "low", indicators

    # LREAL 设置
    lreal = params.get('LREAL')
    if lreal is False or str(lreal).upper() == '.FALSE.':
        indicators.append("LREAL=.FALSE. suggests high precision (reciprocal space projection)")
        return "high", indicators

    indicators.append("Using default medium precision")
    return "medium", indicators


def _extract_key_parameters(params: dict) -> dict:
    """提取关键参数摘要"""
    key_params = {}

    # 关键参数列表
    important_keys = [
        'ENCUT', 'PREC', 'EDIFF', 'EDIFFG',
        'ISMEAR', 'SIGMA',
        'ISPIN', 'MAGMOM', 'LSORBIT',
        'IBRION', 'NSW', 'ISIF', 'POTIM',
        'ALGO', 'NELM', 'NELMIN',
        'ICHARG', 'LCHARG', 'LWAVE',
        'LDAU', 'LDAUTYPE', 'LDAUU', 'LDAUJ',
        'LORBIT', 'NEDOS',
        'NPAR', 'KPAR', 'NCORE'
    ]

    for key in important_keys:
        if key in params:
            key_params[key] = params[key]

    return key_params


def _check_common_issues(params: dict) -> list[str]:
    """检查常见问题和警告"""
    warnings = []

    # ISMEAR 设置检查
    ismear = params.get('ISMEAR', 1)
    if ismear == -5:  # Tetrahedron 方法
        if params.get('NSW', 0) > 0:
            warnings.append("ISMEAR=-5 (tetrahedron) not recommended for relaxation")
        if params.get('ISPIN', 1) == 2:
            warnings.append("ISMEAR=-5 may have issues with magnetic systems")

    # SIGMA 设置检查
    sigma = params.get('SIGMA', 0.2)
    if ismear in [0, 1, 2] and sigma > 0.3:
        warnings.append(f"SIGMA={sigma} may be too large, check entropy term in OUTCAR")

    # LREAL 检查
    lreal = params.get('LREAL')
    if str(lreal).upper() in ['AUTO', 'A', '.TRUE.', 'TRUE']:
        # 小体系可能不适合 LREAL=Auto
        warnings.append("LREAL=Auto: verify projection accuracy for small cells")

    # EDIFF/EDIFFG 一致性
    ediff = params.get('EDIFF', 1e-4)
    ediffg = params.get('EDIFFG', -0.02)
    if isinstance(ediff, (int, float)) and isinstance(ediffg, (int, float)):
        if ediff > 1e-5 and ediffg < -0.01:
            warnings.append("EDIFF may need to be tighter for the requested force convergence")

    # NSW 检查
    nsw = params.get('NSW', 0)
    ibrion = params.get('IBRION', -1)
    if nsw > 0 and ibrion == -1:
        warnings.append("NSW > 0 but IBRION=-1: no ionic relaxation will occur")

    return warnings


def _calculate_confidence(type_indicators: list, prec_indicators: list) -> float:
    """计算推断置信度"""
    # 更多指标 = 更高置信度
    total_indicators = len(type_indicators) + len(prec_indicators)
    if total_indicators >= 4:
        return 0.95
    elif total_indicators >= 2:
        return 0.85
    else:
        return 0.7


def _generate_potcar_suggestions(calc_type: str, precision: str, params: dict) -> list[str]:
    """根据计算类型生成赝势选择建议"""
    suggestions = []

    if calc_type == "gw":
        suggestions.append("Use _GW suffix POTCARs for GW calculations")
        suggestions.append("GW POTCARs have more unoccupied states for accurate response")

    elif calc_type == "phonon":
        suggestions.append("Use standard or harder POTCARs for accurate forces")
        suggestions.append("Avoid _sv variants if not necessary (larger ENCUT required)")

    elif calc_type == "magnetic":
        suggestions.append("Consider _pv variants for transition metals to include p semi-core")
        suggestions.append("Accurate magnetic moments may require more valence electrons")

    elif calc_type in ["band", "dos", "optical"]:
        suggestions.append("Consider _pv/_sv variants for better band structure description")
        suggestions.append("More valence electrons improve accuracy of electronic properties")

    elif calc_type == "accurate":
        suggestions.append("Use _pv or _sv variants for transition metals")
        suggestions.append("Include semi-core states for high accuracy")

    else:  # standard
        suggestions.append("Standard POTCARs are sufficient for routine calculations")
        suggestions.append("Use _pv for elements where it's recommended by VASP wiki")

    if precision == "high":
        suggestions.append("High precision: prefer POTCARs with more valence electrons")
    elif precision == "low":
        suggestions.append("Quick test: minimal POTCARs are acceptable")

    # DFT+U 特殊建议
    if params.get('LDAU', False):
        suggestions.append("DFT+U: ensure POTCAR valence matches LDAUU/LDAUJ configuration")

    return suggestions


def _generate_summary(calc_type: str, precision: str, indicators: list) -> str:
    """生成分析摘要"""
    type_names = {
        "standard": "Standard (structure optimization/static)",
        "accurate": "Accurate (high precision)",
        "band": "Band structure",
        "dos": "Density of states",
        "phonon": "Phonon calculation",
        "magnetic": "Magnetic calculation",
        "gw": "GW quasi-particle",
        "optical": "Optical properties"
    }

    prec_names = {
        "low": "Low (quick test)",
        "medium": "Medium (routine)",
        "high": "High (publication quality)"
    }

    summary = f"Detected: {type_names.get(calc_type, calc_type)}, Precision: {prec_names.get(precision, precision)}"

    if indicators:
        summary += f"\nBased on: {'; '.join(indicators[:2])}"

    return summary
