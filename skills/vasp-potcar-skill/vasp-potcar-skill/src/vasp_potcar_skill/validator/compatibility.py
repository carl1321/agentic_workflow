"""
兼容性检查器

目的：
    检查POTCAR与其他VASP输入文件的兼容性。
"""

import re
import logging
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityResult:
    """兼容性检查结果"""
    compatible: bool
    issues: list[str]
    warnings: list[str]
    suggestions: list[str]


# 常见的LDAU元素和推荐U值范围
LDAU_RECOMMENDATIONS = {
    # 3d过渡金属
    "Ti": {"l": 2, "U_range": (2.0, 4.0), "J": 0.0},
    "V": {"l": 2, "U_range": (2.0, 4.0), "J": 0.0},
    "Cr": {"l": 2, "U_range": (2.0, 4.0), "J": 0.0},
    "Mn": {"l": 2, "U_range": (3.0, 5.0), "J": 0.0},
    "Fe": {"l": 2, "U_range": (3.0, 5.5), "J": 0.0},
    "Co": {"l": 2, "U_range": (3.0, 5.0), "J": 0.0},
    "Ni": {"l": 2, "U_range": (5.0, 7.0), "J": 0.0},
    "Cu": {"l": 2, "U_range": (4.0, 6.0), "J": 0.0},
    # 4d过渡金属
    "Zr": {"l": 2, "U_range": (1.0, 3.0), "J": 0.0},
    "Mo": {"l": 2, "U_range": (2.0, 4.0), "J": 0.0},
    "Ru": {"l": 2, "U_range": (2.0, 4.0), "J": 0.0},
    # 镧系/锕系 (f电子)
    "Ce": {"l": 3, "U_range": (4.0, 6.0), "J": 0.0},
    "Pr": {"l": 3, "U_range": (4.0, 6.0), "J": 0.0},
    "Nd": {"l": 3, "U_range": (4.0, 6.0), "J": 0.0},
    "Sm": {"l": 3, "U_range": (4.0, 6.0), "J": 0.0},
    "Eu": {"l": 3, "U_range": (4.0, 7.0), "J": 0.0},
    "Gd": {"l": 3, "U_range": (4.0, 7.0), "J": 0.0},
    "U": {"l": 3, "U_range": (3.0, 5.0), "J": 0.0},
}

# 需要特殊POTCAR的LDAU组合
LDAU_POTCAR_RECOMMENDATIONS = {
    # 如果使用LDAU，这些元素推荐使用_pv版本以获得更好的结果
    "Ti": ["Ti_pv", "Ti_sv"],
    "V": ["V_pv", "V_sv"],
    "Cr": ["Cr_pv"],
    "Mn": ["Mn_pv"],
    "Fe": ["Fe_pv"],
    "Co": ["Co"],
    "Ni": ["Ni_pv"],
}


class CompatibilityChecker:
    """
    兼容性检查器

    检查项：
        1. POTCAR vs INCAR: LDAU设置是否与赝势匹配
        2. POTCAR vs POSCAR: 元素数量是否一致
        3. 赝势版本兼容性: 是否混用不同版本
    """

    def __init__(self):
        """初始化兼容性检查器"""
        pass

    def check_incar_compatibility(
        self,
        potcar_config: dict,
        incar_path: str
    ) -> CompatibilityResult:
        """
        检查与INCAR的兼容性

        Args:
            potcar_config: 赝势配置，如 {"Li": "Li_sv", "Fe": "Fe_pv"}
            incar_path: INCAR文件路径

        Returns:
            CompatibilityResult: 兼容性检查结果
        """
        issues = []
        warnings = []
        suggestions = []

        incar_path = Path(incar_path)
        if not incar_path.exists():
            return CompatibilityResult(
                compatible=True,
                issues=[],
                warnings=["INCAR file not found, skipping compatibility check"],
                suggestions=[]
            )

        # 解析INCAR
        incar_params = self._parse_incar(incar_path)

        # 检查LDAU兼容性
        if incar_params.get("LDAU", False):
            ldau_check = self._check_ldau_potcar_compatibility(
                potcar_config,
                incar_params
            )
            issues.extend(ldau_check.get("issues", []))
            warnings.extend(ldau_check.get("warnings", []))
            suggestions.extend(ldau_check.get("suggestions", []))

        # 检查GW计算
        algo = str(incar_params.get("ALGO", "")).upper()
        if algo in ["GW", "GW0", "SCGW", "EVGW", "QPGW"]:
            gw_check = self._check_gw_potcar(potcar_config)
            warnings.extend(gw_check.get("warnings", []))
            suggestions.extend(gw_check.get("suggestions", []))

        # 检查SOC计算
        if incar_params.get("LSORBIT", False):
            soc_check = self._check_soc_potcar(potcar_config)
            warnings.extend(soc_check.get("warnings", []))
            suggestions.extend(soc_check.get("suggestions", []))

        return CompatibilityResult(
            compatible=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions
        )

    def check_ldau_settings(
        self,
        elements: list,
        potcar_types: dict,
        ldau_params: dict
    ) -> CompatibilityResult:
        """
        检查LDA+U设置是否合理

        Args:
            elements: 元素列表（按POSCAR顺序）
            potcar_types: 赝势类型，如 {"Fe": "Fe_pv"}
            ldau_params: LDAU参数，包含 LDAUL, LDAUU, LDAUJ

        Returns:
            CompatibilityResult: 检查结果
        """
        issues = []
        warnings = []
        suggestions = []

        ldaul = ldau_params.get("LDAUL", [])
        ldauu = ldau_params.get("LDAUU", [])
        ldauj = ldau_params.get("LDAUJ", [])

        # 确保数组长度匹配
        n_elements = len(elements)
        if ldaul and len(ldaul) != n_elements:
            issues.append(
                f"LDAUL has {len(ldaul)} values but there are {n_elements} elements"
            )
        if ldauu and len(ldauu) != n_elements:
            issues.append(
                f"LDAUU has {len(ldauu)} values but there are {n_elements} elements"
            )
        if ldauj and len(ldauj) != n_elements:
            issues.append(
                f"LDAUJ has {len(ldauj)} values but there are {n_elements} elements"
            )

        # 检查每个元素的LDAU设置
        for i, element in enumerate(elements):
            if i >= len(ldaul):
                continue

            l_value = ldaul[i] if i < len(ldaul) else -1
            u_value = ldauu[i] if i < len(ldauu) else 0
            j_value = ldauj[i] if i < len(ldauj) else 0

            # 如果应用了U修正
            if l_value >= 0 and u_value > 0:
                rec = LDAU_RECOMMENDATIONS.get(element)

                if rec:
                    # 检查l值
                    expected_l = rec["l"]
                    if l_value != expected_l:
                        warnings.append(
                            f"{element}: LDAUL={l_value} unusual, "
                            f"typically l={expected_l} for this element"
                        )

                    # 检查U值范围
                    u_min, u_max = rec["U_range"]
                    if u_value < u_min or u_value > u_max:
                        warnings.append(
                            f"{element}: LDAUU={u_value} outside typical range "
                            f"({u_min}-{u_max} eV)"
                        )

                    # 检查POTCAR是否合适
                    potcar = potcar_types.get(element, element)
                    recommended = LDAU_POTCAR_RECOMMENDATIONS.get(element, [])
                    if recommended and potcar not in recommended:
                        suggestions.append(
                            f"{element}: Consider using {recommended[0]} "
                            f"for better DFT+U results"
                        )

                else:
                    # 非典型LDAU元素
                    warnings.append(
                        f"{element}: LDAU applied to non-typical element, "
                        f"verify this is intentional"
                    )

            # 检查是否遗漏了应该用LDAU的元素
            if element in LDAU_RECOMMENDATIONS and l_value < 0:
                # 只是提示，不是错误
                pass  # 用户可能故意不对某些元素用U

        return CompatibilityResult(
            compatible=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions
        )

    def check_poscar_compatibility(
        self,
        potcar_elements: list,
        poscar_elements: list
    ) -> CompatibilityResult:
        """
        检查POTCAR与POSCAR的元素兼容性

        Args:
            potcar_elements: POTCAR中的元素列表
            poscar_elements: POSCAR中的元素列表

        Returns:
            CompatibilityResult: 检查结果
        """
        issues = []
        warnings = []
        suggestions = []

        # 检查数量
        if len(potcar_elements) != len(poscar_elements):
            issues.append(
                f"Element count mismatch: POTCAR has {len(potcar_elements)} elements, "
                f"POSCAR has {len(poscar_elements)}"
            )

        # 检查顺序
        for i, (pot_el, pos_el) in enumerate(zip(potcar_elements, poscar_elements)):
            if pot_el != pos_el:
                issues.append(
                    f"Element mismatch at position {i+1}: "
                    f"POTCAR has {pot_el}, POSCAR has {pos_el}"
                )

        # 检查是否有遗漏或多余
        pot_set = set(potcar_elements)
        pos_set = set(poscar_elements)

        missing = pos_set - pot_set
        extra = pot_set - pos_set

        if missing:
            issues.append(f"Elements in POSCAR but not in POTCAR: {missing}")
        if extra:
            warnings.append(f"Elements in POTCAR but not in POSCAR: {extra}")

        return CompatibilityResult(
            compatible=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions
        )

    def _parse_incar(self, incar_path: Path) -> dict:
        """解析INCAR文件"""
        params = {}
        try:
            content = incar_path.read_text(encoding='utf-8', errors='ignore')

            for line in content.split('\n'):
                # 移除注释
                line = re.split(r'[#!]', line)[0].strip()
                if not line:
                    continue

                # 解析参数
                match = re.match(r'^\s*(\w+)\s*[=:]\s*(.+?)\s*$', line)
                if match:
                    key = match.group(1).upper()
                    value = match.group(2).strip()
                    params[key] = self._parse_value(value)

        except Exception as e:
            logger.error(f"Failed to parse INCAR: {e}")

        return params

    def _parse_value(self, value: str) -> Any:
        """解析参数值"""
        value = value.strip()

        # 布尔值
        if value.upper() in ['.TRUE.', 'TRUE', 'T']:
            return True
        if value.upper() in ['.FALSE.', 'FALSE', 'F']:
            return False

        # 数组
        if '*' in value or ' ' in value:
            return self._parse_array(value)

        # 数值
        try:
            if '.' in value or 'E' in value.upper():
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _parse_array(self, value: str) -> list:
        """解析数组值"""
        result = []
        parts = value.split()

        for part in parts:
            if '*' in part:
                count, val = part.split('*', 1)
                try:
                    count = int(count)
                    val = self._parse_single(val)
                    result.extend([val] * count)
                except ValueError:
                    result.append(part)
            else:
                result.append(self._parse_single(part))

        return result

    def _parse_single(self, value: str) -> Any:
        """解析单个值"""
        try:
            if '.' in value or 'E' in value.upper():
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _check_ldau_potcar_compatibility(
        self,
        potcar_config: dict,
        incar_params: dict
    ) -> dict:
        """检查LDAU与POTCAR的兼容性"""
        issues = []
        warnings = []
        suggestions = []

        # 提取LDAU参数
        ldauu = incar_params.get("LDAUU", [])
        if not isinstance(ldauu, list):
            ldauu = [ldauu]

        # 检查使用了LDAU的元素
        for element, potcar in potcar_config.items():
            if element in LDAU_RECOMMENDATIONS:
                recommended = LDAU_POTCAR_RECOMMENDATIONS.get(element, [])
                if recommended and potcar not in recommended:
                    suggestions.append(
                        f"For DFT+U on {element}, consider {recommended[0]} instead of {potcar}"
                    )

        return {
            "issues": issues,
            "warnings": warnings,
            "suggestions": suggestions
        }

    def _check_gw_potcar(self, potcar_config: dict) -> dict:
        """检查GW计算的POTCAR兼容性"""
        warnings = []
        suggestions = []

        for element, potcar in potcar_config.items():
            if not potcar.endswith("_GW"):
                suggestions.append(
                    f"For GW calculation, consider {element}_GW instead of {potcar}"
                )

        if suggestions:
            warnings.append(
                "GW calculation detected but non-GW POTCARs are being used"
            )

        return {"warnings": warnings, "suggestions": suggestions}

    def _check_soc_potcar(self, potcar_config: dict) -> dict:
        """检查SOC计算的POTCAR兼容性"""
        warnings = []
        suggestions = []

        # SOC计算通常需要包含更多电子的赝势
        heavy_elements = ["Bi", "Pb", "Tl", "Hg", "Au", "Pt", "Ir", "Os", "Re", "W", "Ta"]

        for element, potcar in potcar_config.items():
            if element in heavy_elements:
                # 建议使用包含半芯态的版本
                if "_sv" not in potcar and "_pv" not in potcar:
                    suggestions.append(
                        f"For SOC on heavy element {element}, "
                        f"consider _sv or _pv variant for better accuracy"
                    )

        return {"warnings": warnings, "suggestions": suggestions}
