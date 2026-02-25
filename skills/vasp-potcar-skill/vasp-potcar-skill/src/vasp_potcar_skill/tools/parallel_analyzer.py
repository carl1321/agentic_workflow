"""Parallel analysis of POTCAR recommendations from multiple sources"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .potcar_variants import list_element_variants
from .pymatgen_helper import get_pymatgen_potcar_suggestion
from .vaspkit_helper import get_vaspkit_potcar_suggestion
from .mongodb_search import search_similar_structures


def _get_variants_for_elements(elements: list[str], functional: str) -> dict:
    """获取所有元素的赝势变体"""
    result = {}
    for el in elements:
        result[el] = list_element_variants(el, functional)
    return result


def _get_pymatgen_suggestion(elements: list[str], functional: str) -> dict:
    """获取pymatgen推荐"""
    return get_pymatgen_potcar_suggestion(elements, functional)


def _get_vaspkit_suggestion(elements: list[str], functional: str) -> dict:
    """获取vaspkit推荐"""
    return get_vaspkit_potcar_suggestion(elements, mode="recommended", functional=functional)


def _search_mongodb(formula: str, elements: list[str]) -> dict:
    """搜索MongoDB相似结构"""
    return search_similar_structures(
        formula=formula,
        elements=elements,
        limit=5
    )


def _query_materials_project(elements: list[str], formula: str, functional: str) -> dict:
    """查询Materials Project API"""
    try:
        from ..external import ExternalAPIManager
        import os
        import yaml

        # 尝试加载配置
        config_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "..", "config", "settings.yaml"
        )
        config_path = os.path.normpath(config_path)

        api_key = None
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                api_key = config.get("external_apis", {}).get("materials_project", {}).get("api_key")

        if not api_key:
            return {"success": False, "error": "No API key configured"}

        manager = ExternalAPIManager({
            "materials_project": {
                "enabled": True,
                "api_key": api_key
            }
        })

        if formula:
            result = manager.search_by_formula(formula, functional)
        else:
            result = manager.search_by_elements(elements, functional)

        if result.references:
            top_ref = result.references[0]
            return {
                "success": True,
                "source": top_ref.source,
                "material_id": top_ref.material_id,
                "potcar_symbols": top_ref.potcar_symbols,
                "elements": top_ref.elements,
                "confidence": top_ref.confidence,
                "total_results": len(result.references)
            }
        else:
            return {"success": False, "error": "No results found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_potcar_parallel(
    elements: list[str],
    formula: str = None,
    functional: str = "PBE"
) -> dict[str, Any]:
    """
    并行执行多种赝势分析方法

    Args:
        elements: 元素列表
        formula: 化学式（用于MongoDB搜索和API查询）
        functional: 泛函类型

    Returns:
        多种方法的综合结果
    """
    results = {
        "elements": elements,
        "functional": functional,
        "variants": None,
        "pymatgen": None,
        "vaspkit": None,
        "materials_project_api": None,
        "similar_structures": None,
        "errors": []
    }

    # 使用线程池并行执行
    with ThreadPoolExecutor(max_workers=5) as executor:
        # 提交所有任务
        future_variants = executor.submit(
            _get_variants_for_elements, elements, functional
        )
        future_pymatgen = executor.submit(
            _get_pymatgen_suggestion, elements, functional
        )
        future_vaspkit = executor.submit(
            _get_vaspkit_suggestion, elements, functional
        )
        future_mp_api = executor.submit(
            _query_materials_project, elements, formula, functional
        )
        future_mongodb = executor.submit(
            _search_mongodb, formula, elements
        )

        # 收集结果
        try:
            results["variants"] = future_variants.result(timeout=10)
        except Exception as e:
            results["errors"].append(f"variants: {str(e)}")

        try:
            results["pymatgen"] = future_pymatgen.result(timeout=10)
        except Exception as e:
            results["errors"].append(f"pymatgen: {str(e)}")

        try:
            results["vaspkit"] = future_vaspkit.result(timeout=10)
        except Exception as e:
            results["errors"].append(f"vaspkit: {str(e)}")

        try:
            results["materials_project_api"] = future_mp_api.result(timeout=30)
        except Exception as e:
            results["errors"].append(f"materials_project_api: {str(e)}")

        try:
            results["similar_structures"] = future_mongodb.result(timeout=10)
        except Exception as e:
            results["errors"].append(f"mongodb: {str(e)}")

    # 生成综合比较
    results["comparison"] = _generate_comparison(results, elements)

    return results


def _generate_comparison(results: dict, elements: list[str]) -> dict:
    """生成各数据源的比较结果"""
    comparison = {}

    for element in elements:
        sources = {}

        # pymatgen
        if results.get("pymatgen") and results["pymatgen"].get("suggestions"):
            pm_sug = results["pymatgen"]["suggestions"].get(element, {})
            sources["pymatgen"] = pm_sug.get("recommended", element)

        # vaspkit
        if results.get("vaspkit") and results["vaspkit"].get("suggestions"):
            vk_sug = results["vaspkit"]["suggestions"].get(element, {})
            sources["vaspkit"] = vk_sug.get("symbol", element)

        # Materials Project API
        if results.get("materials_project_api") and results["materials_project_api"].get("success"):
            mp_data = results["materials_project_api"]
            mp_elements = mp_data.get("elements", [])
            mp_symbols = mp_data.get("potcar_symbols", [])
            if element in mp_elements:
                idx = mp_elements.index(element)
                if idx < len(mp_symbols):
                    sources["materials_project_api"] = mp_symbols[idx]

        # 统计一致性
        values = list(sources.values())
        unique_values = set(values)
        all_agree = len(unique_values) == 1 if values else False

        comparison[element] = {
            "sources": sources,
            "all_agree": all_agree,
            "unique_recommendations": list(unique_values)
        }

    return comparison
