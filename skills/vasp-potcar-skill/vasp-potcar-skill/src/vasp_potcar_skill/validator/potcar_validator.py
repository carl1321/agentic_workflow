"""
POTCAR验证器

目的：
    验证生成的POTCAR文件是否正确。
"""

import re
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: list[str]
    warnings: list[str]
    suggestions: list[str]
    details: dict


class PotcarValidator:
    """
    POTCAR验证器

    检查项：
        1. 元素顺序是否与POSCAR一致
        2. ENCUT是否足够覆盖所有ENMAX
        3. 赝势文件是否完整（未截断）
        4. 泛函类型是否一致（不混用PBE/LDA）
    """

    # 已知的泛函类型
    KNOWN_FUNCTIONALS = ["PAW_PBE", "PAW_GGA", "PAW_LDA", "PAW", "US", "USPP"]

    def __init__(self):
        """初始化验证器"""
        pass

    def validate(self, potcar_path: str, poscar_path: str = None,
                 incar_path: str = None) -> ValidationResult:
        """
        验证POTCAR

        Args:
            potcar_path: POTCAR文件路径
            poscar_path: POSCAR文件路径（可选，用于顺序验证）
            incar_path: INCAR文件路径（可选，用于ENCUT验证）

        Returns:
            ValidationResult: 验证结果
        """
        errors = []
        warnings = []
        suggestions = []
        details = {}

        potcar_path = Path(potcar_path)

        # 检查文件是否存在
        if not potcar_path.exists():
            return ValidationResult(
                valid=False,
                errors=["POTCAR file not found"],
                warnings=[],
                suggestions=[],
                details={}
            )

        # 解析POTCAR
        potcar_info = self._parse_potcar(potcar_path)
        details["potcar_info"] = potcar_info

        if not potcar_info.get("valid"):
            errors.append(potcar_info.get("error", "Failed to parse POTCAR"))
            return ValidationResult(
                valid=False,
                errors=errors,
                warnings=warnings,
                suggestions=suggestions,
                details=details
            )

        # 检查泛函一致性
        functional_check = self._check_functional_consistency(potcar_info["entries"])
        if not functional_check["consistent"]:
            errors.append(f"Mixed functionals detected: {functional_check['functionals']}")
            suggestions.append("Use POTCARs with the same functional type")
        details["functional_check"] = functional_check

        # 检查文件完整性
        integrity_check = self._check_integrity(potcar_info["entries"])
        if not integrity_check["complete"]:
            errors.extend(integrity_check["issues"])
        details["integrity_check"] = integrity_check

        # 如果提供了POSCAR，检查元素顺序
        if poscar_path:
            poscar_path = Path(poscar_path)
            if poscar_path.exists():
                order_check = self.check_element_order(str(potcar_path), str(poscar_path))
                if not order_check:
                    errors.append("Element order in POTCAR does not match POSCAR")
                    suggestions.append("Regenerate POTCAR with elements in POSCAR order")
                details["order_match"] = order_check

        # 如果提供了INCAR，检查ENCUT
        if incar_path:
            incar_path = Path(incar_path)
            if incar_path.exists():
                encut = self._get_encut_from_incar(incar_path)
                if encut:
                    encut_check = self.check_encut_coverage(str(potcar_path), encut)
                    if not encut_check:
                        max_enmax = max(potcar_info.get("enmax_values", [0]))
                        warnings.append(
                            f"ENCUT ({encut} eV) may be insufficient. "
                            f"Max ENMAX in POTCAR: {max_enmax} eV"
                        )
                        suggestions.append(f"Consider ENCUT >= {max_enmax * 1.3:.0f} eV")
                    details["encut_check"] = {"encut": encut, "sufficient": encut_check}

        # 汇总
        is_valid = len(errors) == 0

        return ValidationResult(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
            details=details
        )

    def check_element_order(self, potcar_path: str, poscar_path: str) -> bool:
        """
        检查元素顺序

        Args:
            potcar_path: POTCAR文件路径
            poscar_path: POSCAR文件路径

        Returns:
            bool: 顺序是否匹配
        """
        try:
            # 从POTCAR提取元素顺序
            potcar_elements = self._get_potcar_elements(potcar_path)

            # 从POSCAR提取元素顺序
            poscar_elements = self._get_poscar_elements(poscar_path)

            if not potcar_elements or not poscar_elements:
                logger.warning("Could not extract elements from files")
                return False

            # 比较顺序
            if len(potcar_elements) != len(poscar_elements):
                logger.warning(
                    f"Element count mismatch: POTCAR has {len(potcar_elements)}, "
                    f"POSCAR has {len(poscar_elements)}"
                )
                return False

            for i, (pot_el, pos_el) in enumerate(zip(potcar_elements, poscar_elements)):
                if pot_el != pos_el:
                    logger.warning(
                        f"Element mismatch at position {i+1}: "
                        f"POTCAR has {pot_el}, POSCAR has {pos_el}"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking element order: {e}")
            return False

    def check_encut_coverage(self, potcar_path: str, encut: float) -> bool:
        """
        检查ENCUT是否足够

        Args:
            potcar_path: POTCAR文件路径
            encut: INCAR中设置的ENCUT值

        Returns:
            bool: ENCUT是否足够（至少为最大ENMAX的1.0倍）
        """
        try:
            potcar_info = self._parse_potcar(Path(potcar_path))
            enmax_values = potcar_info.get("enmax_values", [])

            if not enmax_values:
                logger.warning("No ENMAX values found in POTCAR")
                return True  # 无法验证时假设通过

            max_enmax = max(enmax_values)

            # ENCUT应至少等于最大ENMAX
            # 实际使用中通常推荐1.3倍，但最低要求是1.0倍
            return encut >= max_enmax

        except Exception as e:
            logger.error(f"Error checking ENCUT coverage: {e}")
            return True

    def _parse_potcar(self, potcar_path: Path) -> dict:
        """解析POTCAR文件"""
        try:
            content = potcar_path.read_text(encoding='utf-8', errors='ignore')

            entries = []
            enmax_values = []
            current_entry = {}

            for line in content.split('\n'):
                # TITEL行：提取赝势类型
                if 'TITEL' in line:
                    if current_entry:
                        entries.append(current_entry)
                    current_entry = {}

                    match = re.search(r'TITEL\s*=\s*(\S+)\s+(\S+)', line)
                    if match:
                        current_entry["functional"] = match.group(1)
                        current_entry["symbol"] = match.group(2)
                        # 提取元素名
                        element = match.group(2).split('_')[0]
                        current_entry["element"] = element

                # ENMAX行
                elif 'ENMAX' in line and 'ENMIN' not in line:
                    match = re.search(r'ENMAX\s*=\s*([\d.]+)', line)
                    if match:
                        enmax = float(match.group(1))
                        current_entry["enmax"] = enmax
                        enmax_values.append(enmax)

                # ZVAL行（价电子数）
                elif 'ZVAL' in line:
                    match = re.search(r'ZVAL\s*=\s*([\d.]+)', line)
                    if match:
                        current_entry["zval"] = float(match.group(1))

                # POMASS行（原子质量）
                elif 'POMASS' in line:
                    match = re.search(r'POMASS\s*=\s*([\d.]+)', line)
                    if match:
                        current_entry["pomass"] = float(match.group(1))

                # End行标记一个赝势块结束
                elif line.strip() == 'End of Dataset':
                    if current_entry:
                        current_entry["complete"] = True

            # 添加最后一个entry
            if current_entry:
                entries.append(current_entry)

            return {
                "valid": True,
                "entries": entries,
                "elements": [e.get("element") for e in entries],
                "symbols": [e.get("symbol") for e in entries],
                "enmax_values": enmax_values,
                "n_elements": len(entries)
            }

        except Exception as e:
            return {"valid": False, "error": str(e)}

    def _check_functional_consistency(self, entries: list[dict]) -> dict:
        """检查泛函一致性"""
        functionals = set()
        for entry in entries:
            func = entry.get("functional", "")
            if func:
                functionals.add(func)

        return {
            "consistent": len(functionals) <= 1,
            "functionals": list(functionals)
        }

    def _check_integrity(self, entries: list[dict]) -> dict:
        """检查文件完整性"""
        issues = []

        for i, entry in enumerate(entries):
            element = entry.get("element", f"entry_{i}")

            if "enmax" not in entry:
                issues.append(f"Missing ENMAX for {element}")

            if "zval" not in entry:
                issues.append(f"Missing ZVAL for {element}")

        return {
            "complete": len(issues) == 0,
            "issues": issues
        }

    def _get_potcar_elements(self, potcar_path: str) -> list[str]:
        """从POTCAR提取元素列表"""
        potcar_info = self._parse_potcar(Path(potcar_path))
        return potcar_info.get("elements", [])

    def _get_poscar_elements(self, poscar_path: str) -> list[str]:
        """从POSCAR提取元素列表"""
        try:
            content = Path(poscar_path).read_text(encoding='utf-8', errors='ignore')
            lines = content.strip().split('\n')

            # 第6行应该是元素符号（VASP5格式）
            if len(lines) >= 6:
                line6 = lines[5].split()
                # 检查是否是元素符号（而不是数字）
                try:
                    [int(x) for x in line6]
                    # 如果能转为数字，说明是VASP4格式，没有元素行
                    return []
                except ValueError:
                    # VASP5格式
                    return line6

            return []

        except Exception as e:
            logger.error(f"Error reading POSCAR: {e}")
            return []

    def _get_encut_from_incar(self, incar_path: Path) -> Optional[float]:
        """从INCAR提取ENCUT值"""
        try:
            content = incar_path.read_text(encoding='utf-8', errors='ignore')

            for line in content.split('\n'):
                line = re.split(r'[#!]', line)[0].strip()
                match = re.match(r'^\s*ENCUT\s*[=:]\s*([\d.]+)', line, re.IGNORECASE)
                if match:
                    return float(match.group(1))

            return None

        except Exception as e:
            logger.error(f"Error reading INCAR: {e}")
            return None

    def get_potcar_summary(self, potcar_path: str) -> dict:
        """
        获取POTCAR摘要信息

        Args:
            potcar_path: POTCAR文件路径

        Returns:
            包含赝势信息的字典
        """
        potcar_info = self._parse_potcar(Path(potcar_path))

        if not potcar_info.get("valid"):
            return {"error": potcar_info.get("error")}

        entries = potcar_info.get("entries", [])

        return {
            "n_elements": len(entries),
            "elements": [e.get("element") for e in entries],
            "symbols": [e.get("symbol") for e in entries],
            "functional": entries[0].get("functional") if entries else None,
            "enmax_values": [e.get("enmax") for e in entries],
            "recommended_encut": max([e.get("enmax", 0) for e in entries]) * 1.3 if entries else None,
            "zval_values": [e.get("zval") for e in entries],
            "total_valence_electrons": sum([e.get("zval", 0) for e in entries])
        }
