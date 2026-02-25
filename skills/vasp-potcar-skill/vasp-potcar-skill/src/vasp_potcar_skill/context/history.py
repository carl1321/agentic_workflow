"""
用户历史记录管理

目的：
    记录用户的赝势选择历史，用于个性化推荐。
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class UserHistory:
    """
    用户历史管理

    职责：
        1. 记录用户采纳的赝势配置
        2. 按材料体系索引历史记录
        3. 提供"相似材料历史配置"查询
        4. 本地存储，保护隐私
    """

    DEFAULT_HISTORY_FILE = ".vasp_potcar_history.json"

    def __init__(self, history_path: Optional[str] = None):
        """
        初始化用户历史管理器

        Args:
            history_path: 历史记录文件路径，默认存储在用户目录
        """
        if history_path:
            self.history_path = Path(history_path)
        else:
            # 默认存储在用户目录
            home = Path.home()
            self.history_path = home / self.DEFAULT_HISTORY_FILE

        self._history = self._load_history()

    def _load_history(self) -> dict:
        """加载历史记录"""
        if self.history_path.exists():
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"Loaded {len(data.get('records', []))} history records")
                return data
            except Exception as e:
                logger.warning(f"Failed to load history: {e}")

        return {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "records": [],
            "preferences": {},
            "statistics": {}
        }

    def _save_history(self):
        """保存历史记录"""
        try:
            self._history["last_updated"] = datetime.now().isoformat()
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def record(self, formula: str, elements: list, potcar_config: dict,
               metadata: Optional[dict] = None):
        """
        记录一次赝势选择

        Args:
            formula: 化学式（如 "LiFePO4"）
            elements: 元素列表（如 ["Li", "Fe", "P", "O"]）
            potcar_config: 赝势配置字典，如 {"Li": "Li_sv", "Fe": "Fe_pv", ...}
            metadata: 额外的元数据（计算类型、精度等）
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "formula": formula,
            "elements": elements,
            "potcar_config": potcar_config,
            "element_set": "-".join(sorted(elements)),  # 用于快速索引
            "metadata": metadata or {}
        }

        self._history["records"].append(record)

        # 更新统计信息
        self._update_statistics(elements, potcar_config)

        # 保存
        self._save_history()
        logger.info(f"Recorded POTCAR selection for {formula}")

    def query_similar(self, formula: str = None, elements: list = None,
                      limit: int = 10) -> list[dict]:
        """
        查询相似材料的历史配置

        Args:
            formula: 化学式（精确匹配）
            elements: 元素列表（匹配包含这些元素的记录）
            limit: 返回结果数量限制

        Returns:
            匹配的历史记录列表，按相关性排序
        """
        records = self._history.get("records", [])
        if not records:
            return []

        results = []

        for record in records:
            score = 0

            # 化学式精确匹配得分最高
            if formula and record.get("formula") == formula:
                score += 10

            # 元素集合匹配
            if elements:
                record_elements = set(record.get("elements", []))
                query_elements = set(elements)

                # 完全匹配
                if record_elements == query_elements:
                    score += 8
                # 包含关系
                elif query_elements.issubset(record_elements):
                    score += 5
                elif record_elements.issubset(query_elements):
                    score += 4
                # 部分重叠
                else:
                    overlap = len(record_elements & query_elements)
                    if overlap > 0:
                        score += overlap

            if score > 0:
                results.append({
                    "record": record,
                    "score": score
                })

        # 按分数排序
        results.sort(key=lambda x: (-x["score"], x["record"]["timestamp"]), reverse=True)

        # 返回前N条
        return [r["record"] for r in results[:limit]]

    def get_user_preferences(self) -> dict:
        """
        获取用户偏好统计

        Returns:
            {
                "preferred_precision": "high",  # 用户倾向的精度
                "element_preferences": {        # 各元素的常用选择
                    "Li": {"Li_sv": 5, "Li": 2},
                    ...
                },
                "calc_type_usage": {...},       # 计算类型使用频率
                "total_records": 42
            }
        """
        stats = self._history.get("statistics", {})
        records = self._history.get("records", [])

        # 元素偏好统计
        element_prefs = defaultdict(lambda: defaultdict(int))
        calc_types = defaultdict(int)
        precision_counts = defaultdict(int)

        for record in records:
            potcar_config = record.get("potcar_config", {})
            for element, potcar in potcar_config.items():
                element_prefs[element][potcar] += 1

            metadata = record.get("metadata", {})
            if "calc_type" in metadata:
                calc_types[metadata["calc_type"]] += 1
            if "precision" in metadata:
                precision_counts[metadata["precision"]] += 1

        # 确定主要偏好
        preferred_precision = "medium"
        if precision_counts:
            preferred_precision = max(precision_counts.items(), key=lambda x: x[1])[0]

        # 为每个元素确定最常用的选择
        element_most_used = {}
        for element, choices in element_prefs.items():
            if choices:
                element_most_used[element] = max(choices.items(), key=lambda x: x[1])[0]

        return {
            "preferred_precision": preferred_precision,
            "element_preferences": dict(element_prefs),
            "element_most_used": element_most_used,
            "calc_type_usage": dict(calc_types),
            "precision_usage": dict(precision_counts),
            "total_records": len(records)
        }

    def _update_statistics(self, elements: list, potcar_config: dict):
        """更新统计信息"""
        if "statistics" not in self._history:
            self._history["statistics"] = {}

        stats = self._history["statistics"]

        # 更新元素使用计数
        if "element_usage" not in stats:
            stats["element_usage"] = {}

        for element in elements:
            stats["element_usage"][element] = stats["element_usage"].get(element, 0) + 1

        # 更新赝势使用计数
        if "potcar_usage" not in stats:
            stats["potcar_usage"] = {}

        for element, potcar in potcar_config.items():
            key = f"{element}:{potcar}"
            stats["potcar_usage"][key] = stats["potcar_usage"].get(key, 0) + 1

    def get_element_history(self, element: str) -> list[dict]:
        """
        获取特定元素的选择历史

        Args:
            element: 元素符号

        Returns:
            该元素的所有赝势选择记录
        """
        records = self._history.get("records", [])
        element_records = []

        for record in records:
            if element in record.get("elements", []):
                potcar_config = record.get("potcar_config", {})
                if element in potcar_config:
                    element_records.append({
                        "timestamp": record["timestamp"],
                        "formula": record.get("formula"),
                        "potcar": potcar_config[element],
                        "metadata": record.get("metadata", {})
                    })

        return element_records

    def suggest_potcar_from_history(self, element: str) -> Optional[str]:
        """
        基于历史记录为元素推荐赝势

        Args:
            element: 元素符号

        Returns:
            最常使用的赝势，如果没有历史则返回None
        """
        prefs = self.get_user_preferences()
        element_most_used = prefs.get("element_most_used", {})
        return element_most_used.get(element)

    def clear_history(self):
        """清空所有历史记录"""
        self._history = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "records": [],
            "preferences": {},
            "statistics": {}
        }
        self._save_history()
        logger.info("History cleared")

    def export_history(self, output_path: str):
        """导出历史记录"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self._history, f, indent=2, ensure_ascii=False)
        logger.info(f"History exported to {output_path}")

    def import_history(self, input_path: str, merge: bool = True):
        """
        导入历史记录

        Args:
            input_path: 输入文件路径
            merge: 是否与现有记录合并，False则覆盖
        """
        with open(input_path, 'r', encoding='utf-8') as f:
            imported = json.load(f)

        if merge:
            # 合并记录
            existing_timestamps = {r["timestamp"] for r in self._history.get("records", [])}
            for record in imported.get("records", []):
                if record.get("timestamp") not in existing_timestamps:
                    self._history["records"].append(record)
        else:
            self._history = imported

        self._save_history()
        logger.info(f"History imported from {input_path}")
