"""测试脚本 - 验证Skill各工具功能"""

import sys
sys.path.insert(0, "D:/code/vasp-potcar-skill/src")

from vasp_potcar_skill.tools.poscar_parser import parse_poscar_content
from vasp_potcar_skill.tools.rules_query import query_potcar_rules
from vasp_potcar_skill.tools.pymatgen_helper import get_pymatgen_potcar_suggestion
import json


def test_poscar_parser():
    """测试POSCAR解析"""
    print("=" * 50)
    print("测试 1: POSCAR解析")
    print("=" * 50)

    poscar_content = """LiFePO4 olivine structure
1.0
  10.3377   0.0000   0.0000
   0.0000   6.0080   0.0000
   0.0000   0.0000   4.6930
Li Fe P O
4 4 4 16
Direct
  0.0000  0.0000  0.0000
  0.5000  0.0000  0.5000
  0.0000  0.5000  0.0000
  0.5000  0.5000  0.5000
  0.2820  0.2500  0.9750
  0.7180  0.7500  0.0250
  0.7820  0.2500  0.5250
  0.2180  0.7500  0.4750
  0.0950  0.2500  0.4180
  0.9050  0.7500  0.5820
  0.5950  0.2500  0.0820
  0.4050  0.7500  0.9180
  0.0970  0.2500  0.7430
  0.9030  0.7500  0.2570
  0.5970  0.2500  0.2430
  0.4030  0.7500  0.7570
  0.1650  0.0460  0.2850
  0.8350  0.9540  0.7150
  0.8350  0.5460  0.7150
  0.1650  0.4540  0.2850
  0.6650  0.0460  0.2150
  0.3350  0.9540  0.7850
  0.3350  0.5460  0.7850
  0.6650  0.4540  0.2150
  0.2850  0.2500  0.2150
  0.7150  0.7500  0.7850
  0.7850  0.2500  0.7150
  0.2150  0.7500  0.2850
"""

    result = parse_poscar_content(poscar_content)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def test_rules_query():
    """测试规则查询"""
    print("\n" + "=" * 50)
    print("测试 2: 赝势规则查询")
    print("=" * 50)

    elements = ["Li", "Fe", "P", "O"]
    result = query_potcar_rules(elements, "standard")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def test_pymatgen_suggestion():
    """测试pymatgen建议"""
    print("\n" + "=" * 50)
    print("测试 3: Pymatgen赝势建议")
    print("=" * 50)

    elements = ["Li", "Fe", "P", "O"]
    result = get_pymatgen_potcar_suggestion(elements, "PBE")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def run_all_tests():
    """运行所有测试"""
    print("\nVASP Potcar Skill 功能测试\n")

    try:
        poscar_result = test_poscar_parser()
        assert poscar_result["success"], "POSCAR解析失败"
        print("\n✓ POSCAR解析测试通过")
    except Exception as e:
        print(f"\n✗ POSCAR解析测试失败: {e}")

    try:
        rules_result = test_rules_query()
        assert "recommendations" in rules_result, "规则查询失败"
        print("\n✓ 规则查询测试通过")
    except Exception as e:
        print(f"\n✗ 规则查询测试失败: {e}")

    try:
        pymatgen_result = test_pymatgen_suggestion()
        assert "suggestions" in pymatgen_result, "Pymatgen建议失败"
        print("\n✓ Pymatgen建议测试通过")
    except Exception as e:
        print(f"\n✗ Pymatgen建议测试失败: {e}")

    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    run_all_tests()
