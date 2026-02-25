"""
测试实际POTCAR生成（使用真实赝势库）
"""
import os
import sys
from pathlib import Path

# 获取项目根目录
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
FIXTURES_DIR = TEST_DIR / "fixtures"
OUTPUT_DIR = FIXTURES_DIR / "potcar"

# 设置赝势库路径
os.environ["VASP_PP_PATH"] = r"D:\code\pot5.4"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vasp_potcar_skill.tools.potcar_generator import (
    generate_potcar_file,
    generate_potcar_from_knowledge,
    get_potcar_summary
)
from vasp_potcar_skill.tools.potcar_variants import list_element_variants


def test_real_generation():
    """测试实际POTCAR生成"""
    print("=" * 60)
    print("测试实际POTCAR生成")
    print(f"VASP_PP_PATH: {os.environ.get('VASP_PP_PATH')}")
    print("=" * 60)

    # 测试1: 列出Fe的变体（从磁盘读取）
    print("\n1. Fe赝势变体（从磁盘读取）:")
    fe_variants = list_element_variants("Fe", "PBE")
    print(f"   来源: {'磁盘' if fe_variants['from_disk'] else '知识库'}")
    print(f"   推荐: {fe_variants['recommended']}")
    for v in fe_variants['variants'][:5]:  # 只显示前5个
        mark = "*" if v.get('is_recommended') else " "
        print(f"   {mark} {v['name']}: ENMAX={v.get('enmax')}, 价电子={v.get('valence')}")

    # 测试2: 获取POTCAR摘要（从磁盘读取ENMAX）
    print("\n2. Fe-O系统POTCAR摘要:")
    summary = get_potcar_summary(
        elements=["Fe", "O"],
        potcar_types={"Fe": "Fe_pv", "O": "O"},
        functional="PBE"
    )
    print(f"   数据来源: {summary.get('source')}")
    print(f"   推荐ENCUT: {summary.get('recommended_encut')} eV")
    for el, detail in summary['details'].items():
        print(f"   {el} ({detail['potcar_type']}): "
              f"KB={detail['enmax_from_knowledge_base']}, "
              f"Disk={detail['enmax_from_disk']}, "
              f"价电子={detail.get('valence_electrons')}")

    # 测试3: 基于知识库生成（不写入文件）
    print("\n3. LiFePO4 知识库推荐（battery_cathode场景）:")
    result = generate_potcar_from_knowledge(
        elements=["Li", "Fe", "P", "O"],
        calculation_type="standard",
        scenario="battery_cathode",
        functional="PBE",
        output_path=None  # 不实际生成文件
    )

    print(f"   场景: {result.get('scenario')}")
    print(f"   赝势类型: {result.get('potcar_types')}")

    if result.get('success'):
        print(f"   [成功] 可以生成POTCAR")
        print(f"   最大ENMAX: {result.get('max_enmax')} eV")
        print(f"   推荐ENCUT: {result.get('recommended_encut')} eV")
        print(f"   高精度ENCUT: {result.get('recommended_encut_accurate')} eV")
        print(f"   价电子数: {result.get('valence_electrons')}")
        print(f"   总价电子: {result.get('total_valence')}")
    else:
        print(f"   [失败] {result.get('error')}")

    # 测试4: 实际生成POTCAR文件
    print("\n4. 实际生成POTCAR文件:")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = str(OUTPUT_DIR / "Fe2O3_POTCAR")

    result2 = generate_potcar_from_knowledge(
        elements=["Fe", "O"],
        calculation_type="standard",
        functional="PBE",
        output_path=output_path
    )

    if result2.get('success'):
        print(f"   [成功] POTCAR已生成: {result2.get('output_path')}")
        print(f"   元素: {result2.get('elements')}")
        print(f"   赝势: {result2.get('potcar_types')}")
        print(f"   ENMAX: {result2.get('enmax_values')}")
        print(f"   推荐ENCUT: {result2.get('recommended_encut')} eV")

        # 验证文件存在
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"   文件大小: {size} bytes")
    else:
        print(f"   [失败] {result2.get('error')}")
        if result2.get('hint'):
            print(f"   提示: {result2.get('hint')}")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    test_real_generation()
