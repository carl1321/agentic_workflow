"""
使用真实科研工作者提供的POSCAR测试知识库工作流

测试用例:
1. LiCu2AgCl4 - 锂铜银氯化物
2. AgGe(BrO)2 - 银锗溴氧化物
3. Li(BiTe2)3 - 锂铋碲化物
4. CuAgAuBr3 - 铜银金溴化物
5. Cu3AgBr4 - 铜银溴化物
"""

import os
import sys
from pathlib import Path

# 设置路径
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
FIXTURES_DIR = TEST_DIR / "fixtures"
POSCAR_DIR = FIXTURES_DIR / "poscar"
POTCAR_DIR = FIXTURES_DIR / "potcar"

# 设置赝势库路径
os.environ["VASP_PP_PATH"] = r"D:\code\pot5.4"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vasp_potcar_skill.knowledge.loader import get_loader
from vasp_potcar_skill.tools.rules_query import suggest_potcar_for_material
from vasp_potcar_skill.tools.potcar_generator import (
    generate_potcar_file,
    generate_potcar_from_knowledge,
    get_potcar_summary
)
from vasp_potcar_skill.tools.potcar_variants import list_element_variants


def parse_poscar(poscar_path: Path) -> dict:
    """解析POSCAR文件获取元素和原子数"""
    with open(poscar_path, 'r') as f:
        lines = f.readlines()

    formula = lines[0].strip()

    # 第6行是元素符号，第7行是原子数
    elements = lines[5].strip().split()
    counts = [int(x) for x in lines[6].strip().split()]

    return {
        "formula": formula,
        "elements": elements,
        "counts": counts,
        "total_atoms": sum(counts)
    }


def extract_potcar_elements(potcar_path: Path) -> list:
    """从专家提供的POTCAR中提取使用的赝势类型"""
    potcar_types = []
    with open(potcar_path, 'r') as f:
        for line in f:
            if 'TITEL' in line or 'TITEL' in line.upper():
                # TITEL行格式: "   TITEL  = PAW_PBE Li_sv 10Sep2004"
                parts = line.split()
                if len(parts) >= 4:
                    potcar_types.append(parts[3])
    return potcar_types


def compare_potcar_choice(expert_potcars: list, our_potcars: dict) -> dict:
    """比较专家选择和我们的推荐"""
    comparison = []
    match_count = 0

    for i, expert_pot in enumerate(expert_potcars):
        # 从专家选择中提取元素
        element = expert_pot.split('_')[0] if '_' in expert_pot else expert_pot
        our_pot = our_potcars.get(element, "N/A")

        match = expert_pot == our_pot
        if match:
            match_count += 1

        comparison.append({
            "element": element,
            "expert": expert_pot,
            "ours": our_pot,
            "match": match
        })

    return {
        "details": comparison,
        "total": len(expert_potcars),
        "matches": match_count,
        "match_rate": match_count / len(expert_potcars) if expert_potcars else 0
    }


def test_single_material(poscar_path: Path, potcar_path: Path, verbose: bool = True):
    """测试单个材料"""
    print(f"\n{'='*60}")

    # 解析POSCAR
    poscar_info = parse_poscar(poscar_path)
    print(f"材料: {poscar_info['formula']}")
    print(f"元素: {poscar_info['elements']}")
    print(f"原子数: {poscar_info['counts']} (总计: {poscar_info['total_atoms']})")

    # 获取专家选择的POTCAR
    expert_potcars = extract_potcar_elements(potcar_path)
    print(f"\n专家选择的赝势: {expert_potcars}")

    # 获取我们的推荐
    recommendation = suggest_potcar_for_material(
        formula=poscar_info['formula'],
        elements=poscar_info['elements'],
        calculation_type="standard"
    )

    our_potcars = recommendation['potcar_types']
    print(f"知识库推荐: {our_potcars}")

    if recommendation.get('detected_scenario'):
        print(f"检测到场景: {recommendation['detected_scenario']}")

    # 比较结果
    comparison = compare_potcar_choice(expert_potcars, our_potcars)
    print(f"\n比较结果:")
    print(f"  匹配率: {comparison['matches']}/{comparison['total']} ({comparison['match_rate']*100:.1f}%)")

    if verbose:
        for item in comparison['details']:
            status = "[OK]" if item['match'] else "[DIFF]"
            print(f"    {status} {item['element']}: 专家={item['expert']}, 推荐={item['ours']}")

    # 测试POTCAR生成
    result = generate_potcar_from_knowledge(
        elements=poscar_info['elements'],
        calculation_type="standard",
        functional="PBE",
        output_path=None
    )

    if result.get('success'):
        print(f"\n生成测试: [OK]")
        print(f"  最大ENMAX: {result.get('max_enmax', 'N/A')} eV")
        print(f"  推荐ENCUT: {result.get('recommended_encut', 'N/A')} eV")
        print(f"  总价电子: {result.get('total_valence', 'N/A')}")
    else:
        print(f"\n生成测试: [FAIL]")
        print(f"  错误: {result.get('error', 'Unknown')}")

    return {
        "formula": poscar_info['formula'],
        "elements": poscar_info['elements'],
        "expert_potcars": expert_potcars,
        "our_potcars": our_potcars,
        "comparison": comparison,
        "generation_success": result.get('success', False),
        "max_enmax": result.get('max_enmax'),
        "recommended_encut": result.get('recommended_encut')
    }


def run_all_tests():
    """运行所有测试"""
    print("="*60)
    print("VASP POTCAR 知识库测试 - 使用科研工作者提供的真实数据")
    print("="*60)

    # 动态扫描fixtures目录中的所有POSCAR/POTCAR对
    test_cases = []
    for poscar_file in sorted(POSCAR_DIR.glob("*_POSCAR")):
        material_name = poscar_file.name.replace("_POSCAR", "")
        potcar_file = POTCAR_DIR / f"{material_name}_POTCAR"
        if potcar_file.exists():
            test_cases.append((poscar_file.name, potcar_file.name))

    print(f"\n发现 {len(test_cases)} 个测试用例")

    results = []
    for poscar_name, potcar_name in test_cases:
        poscar_path = POSCAR_DIR / poscar_name
        potcar_path = POTCAR_DIR / potcar_name

        if not poscar_path.exists():
            print(f"\n跳过: {poscar_name} (文件不存在)")
            continue
        if not potcar_path.exists():
            print(f"\n跳过: {poscar_name} (对应POTCAR不存在)")
            continue

        result = test_single_material(poscar_path, potcar_path)
        results.append(result)

    # 统计汇总
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)

    total_elements = 0
    total_matches = 0
    generation_success = 0

    for r in results:
        total_elements += r['comparison']['total']
        total_matches += r['comparison']['matches']
        if r['generation_success']:
            generation_success += 1

    print(f"\n测试材料数: {len(results)}")
    print(f"赝势匹配统计: {total_matches}/{total_elements} ({total_matches/total_elements*100:.1f}%)")
    print(f"生成成功率: {generation_success}/{len(results)} ({generation_success/len(results)*100:.1f}%)")

    # 详细差异分析
    print("\n差异分析:")
    for r in results:
        for item in r['comparison']['details']:
            if not item['match']:
                print(f"  {r['formula']} - {item['element']}: 专家用{item['expert']}, 推荐{item['ours']}")

    print("\n" + "="*60)
    print("测试完成!")
    print("="*60)

    return results


if __name__ == "__main__":
    run_all_tests()
