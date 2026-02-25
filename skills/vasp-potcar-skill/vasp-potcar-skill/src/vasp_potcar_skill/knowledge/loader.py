"""
知识库加载器

目的：
    提供统一的知识库访问接口。
    从YAML文件加载知识，并提供查询方法。
"""

from pathlib import Path
from typing import Any, Optional
import yaml


# 知识库目录
KNOWLEDGE_DIR = Path(__file__).parent
RULES_FILE = KNOWLEDGE_DIR / "potcar_rules.yaml"


class KnowledgeLoader:
    """
    知识库加载和查询

    职责：
        1. 加载potcar_rules.yaml中的元素知识
        2. 加载场景规则
        3. 提供按元素、按场景的查询接口
        4. 缓存已加载的知识，避免重复IO
    """

    _instance = None
    _cache = None

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._cache = None
        return cls._instance

    def _load_rules(self) -> dict:
        """加载并缓存规则"""
        if self._cache is None:
            if RULES_FILE.exists():
                with open(RULES_FILE, 'r', encoding='utf-8') as f:
                    self._cache = yaml.safe_load(f)
            else:
                self._cache = {
                    "version": "0.0",
                    "elements": {},
                    "calculation_types": {},
                    "scenario_rules": {},
                    "suffix_meanings": {},
                    "vasp_recommended_defaults": {}
                }
        return self._cache

    def reload(self):
        """强制重新加载知识库"""
        self._cache = None
        return self._load_rules()

    def get_element(self, symbol: str) -> Optional[dict]:
        """
        获取单个元素的完整知识

        Args:
            symbol: 元素符号，如 'Fe'

        Returns:
            元素的完整知识，包括default, gw, accurate, fast, enmax等
        """
        rules = self._load_rules()
        return rules.get("elements", {}).get(symbol)

    def get_element_recommendation(
        self,
        symbol: str,
        calculation_type: str = "standard"
    ) -> dict:
        """
        获取元素的赝势推荐

        Args:
            symbol: 元素符号
            calculation_type: 计算类型 (standard/gw/accurate/fast/magnetic/dft_plus_u等)

        Returns:
            {
                "recommended": "Fe_pv",
                "enmax": 293,
                "reason": "...",
                "notes": "..."
            }
        """
        element_info = self.get_element(symbol)

        if element_info is None:
            # 回退到VASP默认推荐
            defaults = self._load_rules().get("vasp_recommended_defaults", {})
            default_pot = defaults.get(symbol, symbol)
            return {
                "recommended": default_pot,
                "enmax": None,
                "reason": "知识库中无此元素详细规则，使用VASP默认推荐",
                "notes": "",
                "source": "vasp_default"
            }

        # 根据计算类型选择推荐
        type_mapping = {
            "standard": "default",
            "gw": "gw",
            "optical": "gw",
            "accurate": "accurate",
            "fast": "fast",
            "reference": "reference",
            "magnetic": "accurate",  # 磁性计算用accurate
            "dft_plus_u": "dft_plus_u",
            "hybrid": "default",  # 杂化泛函不能用_s
            "hf": "default",
        }

        key = type_mapping.get(calculation_type, "default")

        # 尝试获取指定类型的推荐，如果没有则回退到default
        recommended = element_info.get(key)
        if recommended is None:
            recommended = element_info.get("default", symbol)

        # 获取ENMAX
        enmax_dict = element_info.get("enmax", {})
        enmax = enmax_dict.get(recommended)

        return {
            "recommended": recommended,
            "enmax": enmax,
            "reason": element_info.get("reason", ""),
            "notes": element_info.get("notes", ""),
            "source": "knowledge_base",
            "all_variants": list(enmax_dict.keys()) if enmax_dict else [recommended]
        }

    def get_batch_recommendations(
        self,
        elements: list[str],
        calculation_type: str = "standard"
    ) -> dict[str, dict]:
        """
        批量获取多个元素的推荐

        Args:
            elements: 元素列表
            calculation_type: 计算类型

        Returns:
            {element: recommendation_dict}
        """
        return {
            el: self.get_element_recommendation(el, calculation_type)
            for el in elements
        }

    def get_scenario(self, name: str) -> Optional[dict]:
        """
        获取场景规则

        Args:
            name: 场景名称，如 'battery_cathode', 'magnetic', 'perovskite'

        Returns:
            场景规则字典
        """
        rules = self._load_rules()
        return rules.get("scenario_rules", {}).get(name)

    def get_scenario_recommendations(
        self,
        elements: list[str],
        scenario: str
    ) -> dict[str, dict]:
        """
        根据特定场景获取推荐

        Args:
            elements: 元素列表
            scenario: 场景名称

        Returns:
            考虑场景覆盖后的推荐
        """
        scenario_rule = self.get_scenario(scenario)

        # 先获取标准推荐
        recommendations = self.get_batch_recommendations(elements, "standard")

        # 应用场景覆盖
        if scenario_rule:
            overrides = scenario_rule.get("element_overrides", {})
            for el, override_pot in overrides.items():
                if el in recommendations:
                    recommendations[el]["recommended"] = override_pot
                    recommendations[el]["reason"] = f"场景规则[{scenario}]覆盖: {scenario_rule.get('notes', '')}"
                    recommendations[el]["source"] = f"scenario:{scenario}"
                    # 更新ENMAX
                    element_info = self.get_element(el)
                    if element_info:
                        enmax_dict = element_info.get("enmax", {})
                        recommendations[el]["enmax"] = enmax_dict.get(override_pot)

        return recommendations

    def get_all_elements(self) -> dict:
        """获取所有元素知识"""
        rules = self._load_rules()
        return rules.get("elements", {})

    def get_all_scenarios(self) -> dict:
        """获取所有场景规则"""
        rules = self._load_rules()
        return rules.get("scenario_rules", {})

    def get_calculation_types(self) -> dict:
        """获取所有计算类型定义"""
        rules = self._load_rules()
        return rules.get("calculation_types", {})

    def get_suffix_meanings(self) -> dict:
        """获取后缀含义说明"""
        rules = self._load_rules()
        return rules.get("suffix_meanings", {})

    def get_vasp_defaults(self) -> dict:
        """获取VASP官方推荐的默认赝势"""
        rules = self._load_rules()
        return rules.get("vasp_recommended_defaults", {})

    def validate_potcar_choice(
        self,
        element: str,
        potcar_type: str,
        calculation_type: str = "standard"
    ) -> dict:
        """
        验证赝势选择是否合适

        Args:
            element: 元素符号
            potcar_type: 选择的赝势类型
            calculation_type: 计算类型

        Returns:
            {
                "valid": True/False,
                "warnings": [...],
                "suggestions": [...]
            }
        """
        warnings = []
        suggestions = []
        calc_type_info = self.get_calculation_types().get(calculation_type, {})

        # 检查是否使用了禁止的后缀
        forbidden = calc_type_info.get("forbidden_potcar_suffix")
        if forbidden and forbidden in potcar_type:
            warnings.append(
                f"计算类型[{calculation_type}]禁止使用{forbidden}后缀，"
                f"但选择了{potcar_type}"
            )

        # 检查是否需要特定后缀
        required = calc_type_info.get("requires_potcar_suffix")
        if required and required not in potcar_type:
            warnings.append(
                f"计算类型[{calculation_type}]建议使用{required}后缀，"
                f"但选择了{potcar_type}"
            )

        # 获取推荐并比较
        recommendation = self.get_element_recommendation(element, calculation_type)
        if recommendation["recommended"] != potcar_type:
            suggestions.append(
                f"知识库推荐使用{recommendation['recommended']}，"
                f"原因: {recommendation['reason']}"
            )

        return {
            "valid": len(warnings) == 0,
            "warnings": warnings,
            "suggestions": suggestions,
            "recommendation": recommendation
        }


# 全局实例
_loader = None


def get_loader() -> KnowledgeLoader:
    """获取知识库加载器的全局实例"""
    global _loader
    if _loader is None:
        _loader = KnowledgeLoader()
    return _loader
