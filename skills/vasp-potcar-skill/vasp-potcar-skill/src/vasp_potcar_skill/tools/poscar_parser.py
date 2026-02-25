"""POSCAR file parser using pymatgen"""

import re
from typing import Any


def parse_poscar_content(poscar_content: str) -> dict[str, Any]:
    """
    解析POSCAR文件内容，提取结构信息

    Args:
        poscar_content: POSCAR文件的文本内容

    Returns:
        包含元素、原子数、晶格参数等信息的字典
    """
    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        # 先用简单解析获取额外信息
        simple_result = parse_poscar_simple(poscar_content)
        selective_dynamics = simple_result.get("selective_dynamics", False)
        coordinate_type = simple_result.get("coordinate_type", "Direct")
        has_velocities = simple_result.get("has_velocities", False)

        # 解析POSCAR
        structure = Structure.from_str(poscar_content, fmt="poscar")

        # 获取元素列表（按POSCAR中的顺序，去重）
        elements = []
        seen = set()
        for site in structure:
            symbol = site.specie.symbol
            if symbol not in seen:
                elements.append(symbol)
                seen.add(symbol)

        # 统计每种元素的原子数
        element_counts = {}
        for el in elements:
            element_counts[el] = sum(1 for site in structure if site.specie.symbol == el)

        # 获取晶格参数
        lattice = structure.lattice
        lattice_params = {
            "a": round(lattice.a, 6),
            "b": round(lattice.b, 6),
            "c": round(lattice.c, 6),
            "alpha": round(lattice.alpha, 4),
            "beta": round(lattice.beta, 4),
            "gamma": round(lattice.gamma, 4),
            "volume": round(lattice.volume, 4)
        }

        # 获取空间群信息
        try:
            sga = SpacegroupAnalyzer(structure, symprec=0.1)
            space_group = sga.get_space_group_symbol()
            space_group_number = sga.get_space_group_number()
            crystal_system = sga.get_crystal_system()
            point_group = sga.get_point_group_symbol()
        except Exception:
            space_group = "Unknown"
            space_group_number = None
            crystal_system = "Unknown"
            point_group = "Unknown"

        # 获取化学式
        formula = structure.composition.reduced_formula
        formula_pretty = structure.composition.formula

        # 计算密度
        density = structure.density

        return {
            "success": True,
            "elements": elements,
            "element_counts": element_counts,
            "total_atoms": structure.num_sites,
            "formula": formula,
            "formula_full": formula_pretty,
            "lattice": lattice_params,
            "space_group": space_group,
            "space_group_number": space_group_number,
            "crystal_system": crystal_system,
            "point_group": point_group,
            "is_ordered": structure.is_ordered,
            "density": round(density, 4),
            "selective_dynamics": selective_dynamics,
            "coordinate_type": coordinate_type,
            "has_velocities": has_velocities
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "elements": [],
            "element_counts": {},
            "total_atoms": 0,
            "formula": None
        }


def parse_poscar_simple(poscar_content: str) -> dict[str, Any]:
    """
    简单解析POSCAR，不依赖pymatgen（备用方案）
    同时提取pymatgen不直接暴露的信息（如选择性动力学）

    Args:
        poscar_content: POSCAR文件内容

    Returns:
        基本结构信息
    """
    lines = poscar_content.strip().split('\n')

    try:
        # 第一行：注释
        comment = lines[0].strip()

        # 第二行：缩放因子
        scale = float(lines[1].strip())

        # 第3-5行：晶格矢量
        lattice_vectors = []
        for i in range(2, 5):
            vec = [float(x) * scale for x in lines[i].split()]
            lattice_vectors.append(vec)

        # 第6行：元素符号（VASP 5+格式）
        # 第7行：原子数量
        line6 = lines[5].split()
        line7 = lines[6].split()

        # 判断是VASP 4还是VASP 5格式
        try:
            # 尝试将第6行解析为数字（VASP 4格式）
            counts = [int(x) for x in line6]
            elements = None  # VASP 4格式没有元素符号行
            coord_line_start = 7
        except ValueError:
            # VASP 5格式：第6行是元素符号
            elements = line6
            counts = [int(x) for x in line7]
            coord_line_start = 8

        total_atoms = sum(counts)

        # 检测选择性动力学和坐标类型
        selective_dynamics = False
        coordinate_type = "Direct"
        current_line = coord_line_start

        if current_line < len(lines):
            type_line = lines[current_line - 1].strip()

            # 检查是否是选择性动力学
            if type_line.upper().startswith('S'):
                selective_dynamics = True
                current_line += 1
                if current_line - 1 < len(lines):
                    type_line = lines[current_line - 1].strip()

            # 检测坐标类型
            if type_line.upper().startswith('D'):
                coordinate_type = "Direct"
            elif type_line.upper().startswith('C') or type_line.upper().startswith('K'):
                coordinate_type = "Cartesian"

        # 检测是否有速度数据（分子动力学）
        has_velocities = False
        expected_coord_lines = total_atoms
        if selective_dynamics:
            expected_coord_lines = total_atoms  # 选择性动力学每行6列
        actual_remaining_lines = len(lines) - current_line

        # 如果实际行数远多于坐标行数，可能有速度数据
        if actual_remaining_lines > expected_coord_lines * 1.5:
            has_velocities = True

        # 从注释行尝试提取化学式信息
        formula_hint = _extract_formula_from_comment(comment)

        return {
            "success": True,
            "comment": comment,
            "elements": elements,
            "counts": counts,
            "total_atoms": total_atoms,
            "lattice_vectors": lattice_vectors,
            "scale_factor": scale,
            "selective_dynamics": selective_dynamics,
            "coordinate_type": coordinate_type,
            "has_velocities": has_velocities,
            "vasp_format": "VASP5" if elements else "VASP4",
            "formula_hint": formula_hint
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _extract_formula_from_comment(comment: str) -> str | None:
    """
    尝试从POSCAR注释行提取化学式

    很多POSCAR文件的注释行包含化学式信息
    """
    if not comment:
        return None

    # 常见的化学式模式
    # 如 "LiFePO4", "Fe2O3", "SrTiO3" 等
    formula_pattern = r'^[A-Z][a-z]?(?:\d*[A-Z][a-z]?\d*)*$'

    # 清理注释
    clean_comment = comment.strip()

    # 直接匹配
    if re.match(formula_pattern, clean_comment):
        return clean_comment

    # 尝试提取第一个词
    first_word = clean_comment.split()[0] if clean_comment else ""
    if re.match(formula_pattern, first_word):
        return first_word

    return None


def validate_poscar_content(poscar_content: str) -> dict[str, Any]:
    """
    验证POSCAR文件内容的有效性

    Args:
        poscar_content: POSCAR文件内容

    Returns:
        验证结果和错误信息
    """
    issues = []
    warnings = []

    lines = poscar_content.strip().split('\n')

    if len(lines) < 8:
        issues.append("POSCAR file too short (minimum 8 lines for VASP5 format)")
        return {"valid": False, "issues": issues, "warnings": warnings}

    # 检查缩放因子
    try:
        scale = float(lines[1].strip())
        if scale <= 0:
            issues.append(f"Invalid scale factor: {scale} (must be positive)")
        elif scale > 100:
            warnings.append(f"Unusual scale factor: {scale} (typically 1.0 or lattice constant)")
    except ValueError:
        issues.append(f"Cannot parse scale factor: {lines[1]}")

    # 检查晶格矢量
    for i in range(2, 5):
        try:
            vec = [float(x) for x in lines[i].split()]
            if len(vec) != 3:
                issues.append(f"Lattice vector {i-1} should have 3 components, got {len(vec)}")
        except ValueError:
            issues.append(f"Cannot parse lattice vector {i-1}: {lines[i]}")

    # 检查元素行和原子数行
    line6 = lines[5].split()
    try:
        counts = [int(x) for x in line6]
        # VASP4 格式
        if sum(counts) == 0:
            issues.append("Total atom count is zero")
    except ValueError:
        # VASP5 格式，检查元素符号
        for el in line6:
            if not re.match(r'^[A-Z][a-z]?$', el):
                warnings.append(f"Unusual element symbol: {el}")
        try:
            counts = [int(x) for x in lines[6].split()]
            if sum(counts) == 0:
                issues.append("Total atom count is zero")
        except ValueError:
            issues.append(f"Cannot parse atom counts: {lines[6]}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings
    }
