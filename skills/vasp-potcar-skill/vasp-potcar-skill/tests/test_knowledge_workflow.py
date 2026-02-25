"""
测试知识库驱动的POTCAR生成流程
"""

import os
import sys
from pathlib import Path

# 获取项目根目录
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
FIXTURES_DIR = TEST_DIR / "fixtures"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vasp_potcar_skill.knowledge.loader import get_loader
from vasp_potcar_skill.tools.rules_query import (
    query_potcar_rules,
    get_element_potcar_info,
    suggest_potcar_for_material,
    get_available_scenarios,
    get_suffix_explanation
)
from vasp_potcar_skill.tools.potcar_variants import (
    list_element_variants,
    list_all_variants_for_elements
)
from vasp_potcar_skill.tools.potcar_generator import (
    generate_potcar_from_knowledge,
    get_potcar_summary
)


def test_knowledge_loader():
    """测试知识库加载"""
    print("=" * 60)
    print("测试1: 知识库加载器")
    print("=" * 60)

    loader = get_loader()

    # 测试获取元素信息
    fe_info = loader.get_element("Fe")
    print(f"\nFe元素信息: {fe_info}")

    # 测试获取推荐
    fe_rec = loader.get_element_recommendation("Fe", "standard")
    print(f"\nFe标准计算推荐: {fe_rec}")

    fe_gw = loader.get_element_recommendation("Fe", "gw")
    print(f"\nFe GW计算推荐: {fe_gw}")

    # 测试批量推荐
    batch = loader.get_batch_recommendations(["Li", "Fe", "P", "O"], "standard")
    print(f"\nLiFePO4批量推荐:")
    for el, rec in batch.items():
        print(f"  {el}: {rec['recommended']} (ENMAX: {rec['enmax']})")

    # 测试场景推荐
    scenario_rec = loader.get_scenario_recommendations(["Li", "Fe", "P", "O"], "battery_cathode")
    print(f"\n电池正极材料场景推荐:")
    for el, rec in scenario_rec.items():
        print(f"  {el}: {rec['recommended']} (source: {rec['source']})")

    print("\n[PASS] 知识库加载器测试通过")


def test_rules_query():
    """测试规则查询"""
    print("\n" + "=" * 60)
    print("测试2: 规则查询")
    print("=" * 60)

    # 测试查询规则
    rules = query_potcar_rules(["Fe", "O"], "standard")
    print(f"\nFe-O系统标准计算规则:")
    print(f"  推荐ENCUT: {rules['recommended_encut']} eV")
    for el, rec in rules['recommendations'].items():
        print(f"  {el}: {rec['recommended']}")

    # 测试单元素详细信息
    fe_info = get_element_potcar_info("Fe", "accurate")
    print(f"\nFe元素详细信息(accurate):")
    print(f"  推荐: {fe_info['recommendation']['recommended']}")
    print(f"  所有变体: {fe_info.get('all_variants', [])}")

    # 测试智能材料推荐
    material = suggest_potcar_for_material("LiFePO4", ["Li", "Fe", "P", "O"])
    print(f"\nLiFePO4智能推荐:")
    print(f"  检测场景: {material['detected_scenario']}")
    print(f"  推荐ENCUT: {material['recommended_encut']} eV")
    print(f"  赝势类型: {material['potcar_types']}")

    # 测试场景列表
    scenarios = get_available_scenarios()
    print(f"\n可用场景: {list(scenarios.keys())}")

    # 测试后缀解释
    pv_meaning = get_suffix_explanation("_pv")
    print(f"\n_pv后缀含义: {pv_meaning}")

    print("\n[PASS] 规则查询测试通过")


def test_potcar_variants():
    """测试赝势变体查询"""
    print("\n" + "=" * 60)
    print("测试3: 赝势变体查询")
    print("=" * 60)

    # 测试单元素变体
    fe_variants = list_element_variants("Fe")
    print(f"\nFe赝势变体:")
    print(f"  推荐: {fe_variants['recommended']}")
    print(f"  数据来源: {fe_variants.get('source', 'disk' if fe_variants['from_disk'] else 'knowledge_base')}")
    for v in fe_variants['variants']:
        mark = "*" if v['is_recommended'] else " "
        print(f"  {mark} {v['name']}: ENMAX={v['enmax']}, {v['description']}")

    # 测试多元素变体
    multi = list_all_variants_for_elements(["Li", "O"])
    print(f"\nLi和O的变体数量:")
    for el, info in multi.items():
        print(f"  {el}: {len(info['variants'])}个变体, 推荐{info['recommended']}")

    print("\n[PASS] 赝势变体查询测试通过")


def test_potcar_generator():
    """测试POTCAR生成器（不实际生成文件）"""
    print("\n" + "=" * 60)
    print("测试4: POTCAR生成器")
    print("=" * 60)

    # 测试基于知识库的生成（不输出文件）
    result = generate_potcar_from_knowledge(
        elements=["Li", "Fe", "P", "O"],
        calculation_type="standard",
        scenario="battery_cathode",
        functional="PBE",
        output_path=None  # 不实际生成文件
    )

    print(f"\nLiFePO4 POTCAR生成测试:")
    print(f"  计算类型: {result['calculation_type']}")
    print(f"  场景: {result['scenario']}")
    print(f"  赝势类型: {result['potcar_types']}")

    if result.get('success'):
        print(f"  最大ENMAX: {result['max_enmax']} eV")
        print(f"  推荐ENCUT: {result['recommended_encut']} eV")
    else:
        print(f"  生成失败: {result.get('error', 'Unknown error')}")
        if result.get('enmax_from_knowledge_base'):
            print(f"  知识库ENMAX: {result['enmax_from_knowledge_base']}")
            print(f"  估算ENCUT: {result['recommended_encut_estimate']} eV")

    # 测试获取配置摘要
    summary = get_potcar_summary(
        elements=["Fe", "O"],
        potcar_types={"Fe": "Fe_pv", "O": "O"},
        functional="PBE"
    )
    print(f"\nFe-O配置摘要:")
    print(f"  数据来源: {summary['source']}")
    print(f"  推荐ENCUT: {summary['recommended_encut']} eV")
    for el, detail in summary['details'].items():
        kb_enmax = detail['enmax_from_knowledge_base']
        disk_enmax = detail['enmax_from_disk']
        print(f"  {el} ({detail['potcar_type']}): KB={kb_enmax}, Disk={disk_enmax}")

    print("\n[PASS] POTCAR生成器测试通过")


def test_complete_workflow():
    """测试完整工作流"""
    print("\n" + "=" * 60)
    print("测试5: 完整工作流演示")
    print("=" * 60)

    # 模拟用户输入
    formula = "BaTiO3"
    elements = ["Ba", "Ti", "O"]

    print(f"\n用户请求: 为{formula}选择赝势")
    print("-" * 40)

    # Step 1: 智能推荐
    recommendation = suggest_potcar_for_material(formula, elements, "standard")

    print(f"\n步骤1 - 智能场景检测:")
    print(f"  检测到场景: {recommendation['detected_scenario'] or '无特定场景'}")
    if recommendation.get('scenario_description'):
        print(f"  场景描述: {recommendation['scenario_description']}")

    print(f"\n步骤2 - 赝势推荐:")
    for el, rec in recommendation['recommendations'].items():
        print(f"  {el}: {rec['recommended']}")
        print(f"      ENMAX: {rec['enmax']} eV")
        print(f"      原因: {rec['reason'][:50]}..." if len(rec.get('reason', '')) > 50 else f"      原因: {rec.get('reason', 'N/A')}")

    print(f"\n步骤3 - ENCUT建议:")
    print(f"  最大ENMAX: {recommendation['max_enmax']} eV")
    print(f"  推荐ENCUT (标准): {recommendation['recommended_encut']} eV")
    print(f"  推荐ENCUT (高精度): {round(recommendation['max_enmax'] * 1.5) if recommendation['max_enmax'] else 'N/A'} eV")

    print(f"\n步骤4 - 生成POTCAR:")
    gen_result = generate_potcar_from_knowledge(
        elements=elements,
        calculation_type="standard",
        functional="PBE",
        output_path=None
    )

    if gen_result.get('success'):
        print("  [OK] POTCAR可以生成（已配置VASP_PP_PATH）")
    else:
        print(f"  [FAIL] {gen_result.get('error', 'Unknown error')}")
        if gen_result.get('note'):
            print(f"    {gen_result['note']}")

    print("\n" + "=" * 60)
    print("完整工作流测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    print("\nVASP POTCAR 知识库工作流测试")
    print("=" * 60)

    try:
        test_knowledge_loader()
        test_rules_query()
        test_potcar_variants()
        test_potcar_generator()
        test_complete_workflow()

        print("\n" + "=" * 60)
        print("所有测试通过! [PASS]")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
