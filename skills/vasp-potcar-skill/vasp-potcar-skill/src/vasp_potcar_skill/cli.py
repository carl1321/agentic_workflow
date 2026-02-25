#!/usr/bin/env python3
"""
VASP POTCAR Skill - CLI入口

提供命令行接口，供Claude Code直接调用。

用法:
    python -m vasp_potcar_skill.cli parse-poscar <file_or_content>
    python -m vasp_potcar_skill.cli parse-incar <file_or_content>
    python -m vasp_potcar_skill.cli recommend --elements Li Fe P O --calc-type standard
    python -m vasp_potcar_skill.cli generate --elements Li Fe P O --potcar Li_sv Fe_pv P O
    python -m vasp_potcar_skill.cli variants <element>
    python -m vasp_potcar_skill.cli analyze-context <poscar_path>
"""

import argparse
import json
import sys
import os
from pathlib import Path


def parse_poscar(args):
    """解析POSCAR文件"""
    from .tools.poscar_parser import parse_poscar_content

    # 检查是文件路径还是内容
    if os.path.isfile(args.input):
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = args.input

    result = parse_poscar_content(content)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def parse_incar(args):
    """解析INCAR文件"""
    from .tools.incar_parser import parse_incar_content

    if os.path.isfile(args.input):
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = args.input

    result = parse_incar_content(content)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def list_variants(args):
    """列出元素的赝势变体"""
    from .tools.potcar_variants import list_element_variants

    result = list_element_variants(args.element, args.functional)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def recommend(args):
    """获取赝势推荐"""
    from .tools.rules_query import query_potcar_rules
    from .tools.pymatgen_helper import get_pymatgen_potcar_suggestion
    from .tools.vaspkit_helper import get_vaspkit_potcar_suggestion
    from .engine.decision import DecisionEngine, merge_all_sources

    elements = args.elements
    calc_type = args.calc_type
    precision = args.precision
    functional = args.functional
    formula = args.formula

    # 1. 从知识库获取推荐
    knowledge_base = {}
    for el in elements:
        try:
            rules = query_potcar_rules(el, calc_type)
            if rules:
                knowledge_base[el] = {
                    "recommended": rules.get("recommended", el),
                    "reason": rules.get("reason", "")
                }
        except Exception:
            pass

    # 2. 从 pymatgen 获取推荐
    pymatgen_result = {}
    try:
        pm_result = get_pymatgen_potcar_suggestion(elements, functional)
        if pm_result.get("success"):
            for item in pm_result.get("potcar_symbols", []):
                el = item.get("element")
                sym = item.get("symbol")
                if el and sym:
                    pymatgen_result[el] = sym
    except Exception:
        pass

    # 3. 从 vaspkit 获取推荐
    vaspkit_result = {}
    try:
        vk_result = get_vaspkit_potcar_suggestion(elements, mode="recommended", functional=functional)
        if vk_result.get("success"):
            for el, info in vk_result.get("suggestions", {}).items():
                vaspkit_result[el] = info.get("symbol", el)
    except Exception:
        pass

    # 4. 合并所有数据源
    all_candidates = merge_all_sources(
        elements=elements,
        knowledge_base=knowledge_base,
        api_mp={},
        pymatgen=pymatgen_result,
        vaspkit=vaspkit_result,
        mongodb=[]
    )

    # 5. 使用决策引擎
    engine = DecisionEngine(calc_type=calc_type, precision=precision)
    decision_result = engine.decide_batch(elements, all_candidates)

    # 6. 格式化输出
    decisions_output = {}
    for el, dec in decision_result.decisions.items():
        decisions_output[el] = {
            "selected": dec.selected,
            "confidence": round(dec.confidence, 3),
            "sources_agree": dec.sources_agree,
            "sources_disagree": dec.sources_disagree,
            "reasoning": dec.reasoning
        }

    result = {
        "elements": elements,
        "potcar_symbols": decision_result.potcar_symbols,
        "potcar_types": dict(zip(elements, decision_result.potcar_symbols)),
        "calc_type": calc_type,
        "precision": precision,
        "overall_confidence": round(decision_result.overall_confidence, 3),
        "decisions": decisions_output,
        "summary": decision_result.summary,
        "data_sources": {
            "knowledge_base": knowledge_base,
            "pymatgen": pymatgen_result,
            "vaspkit": vaspkit_result
        }
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def generate(args):
    """生成POTCAR文件"""
    from .tools.potcar_generator import generate_potcar_file

    # 构建potcar_types字典
    potcar_types = dict(zip(args.elements, args.potcar))

    result = generate_potcar_file(
        elements=args.elements,
        potcar_types=potcar_types,
        functional=args.functional,
        output_path=args.output
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def analyze_context(args):
    """分析目录上下文"""
    from .context.analyzer import ContextAnalyzer

    analyzer = ContextAnalyzer()
    result = analyzer.analyze_directory(args.poscar_path)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def validate_potcar(args):
    """验证POTCAR文件"""
    from .validator.potcar_validator import PotcarValidator

    validator = PotcarValidator()
    result = validator.validate(
        potcar_path=args.potcar,
        poscar_path=args.poscar,
        incar_path=args.incar
    )

    output = {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "suggestions": result.suggestions
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return output


def get_options(args):
    """获取计算类型和精度选项"""
    from .engine.weights import CALCULATION_TYPE_OPTIONS, CALCULATION_PRECISION_OPTIONS

    result = {
        "calculation_types": CALCULATION_TYPE_OPTIONS,
        "precision_options": CALCULATION_PRECISION_OPTIONS
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def full_workflow(args):
    """完整工作流：解析POSCAR -> 推荐 -> 生成POTCAR"""
    from .tools.poscar_parser import parse_poscar_content
    from .tools.incar_parser import parse_incar_content
    from .tools.potcar_generator import generate_potcar_file
    from .tools.rules_query import query_potcar_rules
    from .tools.pymatgen_helper import get_pymatgen_potcar_suggestion
    from .engine.decision import DecisionEngine, merge_all_sources
    from .context.analyzer import ContextAnalyzer

    poscar_path = Path(args.poscar)

    # 1. 解析POSCAR
    with open(poscar_path, 'r', encoding='utf-8') as f:
        poscar_content = f.read()

    poscar_result = parse_poscar_content(poscar_content)
    if not poscar_result.get("success"):
        print(json.dumps({"error": "Failed to parse POSCAR", "details": poscar_result}, indent=2))
        return

    elements = poscar_result["elements"]
    formula = poscar_result.get("formula", "")

    print(f"## 结构信息")
    print(f"- 化学式: {formula}")
    print(f"- 空间群: {poscar_result.get('space_group', 'Unknown')}")
    print(f"- 元素: {', '.join(elements)}")
    print()

    # 2. 分析上下文（如果有INCAR）
    calc_type = args.calc_type or "standard"
    precision = args.precision or "medium"

    if args.incar:
        with open(args.incar, 'r', encoding='utf-8') as f:
            incar_content = f.read()
        incar_result = parse_incar_content(incar_content)
        calc_type = incar_result.get("inferred_calc_type", calc_type)
        precision = incar_result.get("inferred_precision", precision)
        print(f"## INCAR分析")
        print(f"- 推断计算类型: {calc_type}")
        print(f"- 推断精度: {precision}")
        print()
    else:
        # 尝试从目录分析
        analyzer = ContextAnalyzer()
        context = analyzer.analyze_directory(str(poscar_path))
        if context.get("calculation_type") != "unknown":
            calc_type = context["calculation_type"]
            precision = context.get("precision_level", precision)

    # 3. 获取推荐
    knowledge_base = {}
    for el in elements:
        try:
            rules = query_potcar_rules(el, calc_type)
            if rules:
                knowledge_base[el] = {
                    "recommended": rules.get("recommended", el),
                    "reason": rules.get("reason", "")
                }
        except Exception:
            pass

    pymatgen_result = {}
    try:
        pm_result = get_pymatgen_potcar_suggestion(elements, args.functional)
        if pm_result.get("success"):
            for item in pm_result.get("potcar_symbols", []):
                el = item.get("element")
                sym = item.get("symbol")
                if el and sym:
                    pymatgen_result[el] = sym
    except Exception:
        pass

    all_candidates = merge_all_sources(
        elements=elements,
        knowledge_base=knowledge_base,
        api_mp={},
        pymatgen=pymatgen_result,
        vaspkit={},
        mongodb=[]
    )

    engine = DecisionEngine(calc_type=calc_type, precision=precision)
    decision_result = engine.decide_batch(elements, all_candidates)

    # 4. 输出推荐
    print(f"## 赝势推荐 (计算类型: {calc_type}, 精度: {precision})")
    print()
    print("| 元素 | 推荐赝势 | 置信度 | 理由 |")
    print("|------|---------|--------|------|")
    for el in elements:
        dec = decision_result.decisions.get(el)
        if dec:
            print(f"| {el} | {dec.selected} | {dec.confidence:.0%} | {dec.reasoning[:50]}... |")

    print()
    print(f"总体置信度: {decision_result.overall_confidence:.0%}")
    print()

    # 5. 生成POTCAR（如果指定了输出路径）
    if args.output:
        potcar_types = dict(zip(elements, decision_result.potcar_symbols))
        gen_result = generate_potcar_file(
            elements=elements,
            potcar_types=potcar_types,
            functional=args.functional,
            output_path=args.output
        )

        if gen_result.get("success"):
            print(f"## POTCAR生成成功")
            print(f"- 输出路径: {gen_result.get('output_path')}")
            print(f"- 推荐ENCUT: {gen_result.get('recommended_encut')} eV")
        else:
            print(f"## POTCAR生成失败")
            print(f"- 错误: {gen_result.get('error')}")

    return decision_result


def main():
    parser = argparse.ArgumentParser(
        description="VASP POTCAR Skill - 智能赝势选择工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # parse-poscar
    p_poscar = subparsers.add_parser("parse-poscar", help="解析POSCAR文件")
    p_poscar.add_argument("input", help="POSCAR文件路径或内容")
    p_poscar.set_defaults(func=parse_poscar)

    # parse-incar
    p_incar = subparsers.add_parser("parse-incar", help="解析INCAR文件")
    p_incar.add_argument("input", help="INCAR文件路径或内容")
    p_incar.set_defaults(func=parse_incar)

    # variants
    p_variants = subparsers.add_parser("variants", help="列出元素的赝势变体")
    p_variants.add_argument("element", help="元素符号")
    p_variants.add_argument("--functional", default="PBE", help="泛函类型")
    p_variants.set_defaults(func=list_variants)

    # recommend
    p_recommend = subparsers.add_parser("recommend", help="获取赝势推荐")
    p_recommend.add_argument("--elements", "-e", nargs="+", required=True, help="元素列表")
    p_recommend.add_argument("--calc-type", "-t", default="standard",
                             choices=["standard", "accurate", "band", "dos", "phonon", "magnetic", "gw", "optical"],
                             help="计算类型")
    p_recommend.add_argument("--precision", "-p", default="medium",
                             choices=["low", "medium", "high"], help="精度")
    p_recommend.add_argument("--functional", "-f", default="PBE", help="泛函类型")
    p_recommend.add_argument("--formula", help="化学式（可选）")
    p_recommend.set_defaults(func=recommend)

    # generate
    p_generate = subparsers.add_parser("generate", help="生成POTCAR文件")
    p_generate.add_argument("--elements", "-e", nargs="+", required=True, help="元素列表（按POSCAR顺序）")
    p_generate.add_argument("--potcar", "-p", nargs="+", required=True, help="赝势类型列表")
    p_generate.add_argument("--functional", "-f", default="PBE", help="泛函类型")
    p_generate.add_argument("--output", "-o", help="输出路径")
    p_generate.set_defaults(func=generate)

    # analyze-context
    p_context = subparsers.add_parser("analyze-context", help="分析目录上下文")
    p_context.add_argument("poscar_path", help="POSCAR文件路径")
    p_context.set_defaults(func=analyze_context)

    # validate
    p_validate = subparsers.add_parser("validate", help="验证POTCAR文件")
    p_validate.add_argument("--potcar", required=True, help="POTCAR文件路径")
    p_validate.add_argument("--poscar", help="POSCAR文件路径（可选）")
    p_validate.add_argument("--incar", help="INCAR文件路径（可选）")
    p_validate.set_defaults(func=validate_potcar)

    # options
    p_options = subparsers.add_parser("options", help="获取计算类型和精度选项")
    p_options.set_defaults(func=get_options)

    # workflow - 完整工作流
    p_workflow = subparsers.add_parser("workflow", help="完整工作流")
    p_workflow.add_argument("poscar", help="POSCAR文件路径")
    p_workflow.add_argument("--incar", help="INCAR文件路径（可选）")
    p_workflow.add_argument("--calc-type", "-t", help="计算类型")
    p_workflow.add_argument("--precision", "-p", help="精度")
    p_workflow.add_argument("--functional", "-f", default="PBE", help="泛函类型")
    p_workflow.add_argument("--output", "-o", help="POTCAR输出路径")
    p_workflow.set_defaults(func=full_workflow)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
