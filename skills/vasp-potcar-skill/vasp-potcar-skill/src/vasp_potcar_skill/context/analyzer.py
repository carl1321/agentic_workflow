"""
上下文分析器

目的：
    分析POSCAR所在目录的其他文件，推断计算类型和参数需求。
"""

import os
import re
import logging
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class ContextAnalyzer:
    """
    上下文分析器

    职责：
        1. 读取同目录的INCAR，推断计算类型（优化/能带/声子等）
        2. 读取KPOINTS，判断计算精度需求
        3. 检测是否存在旧的POTCAR，提取历史配置
        4. 识别项目级配置文件
    """

    # 计算类型关键字映射
    CALC_TYPE_INDICATORS = {
        "band": ["ICHARG=11", "LORBIT", "LSORBIT"],
        "dos": ["NEDOS", "LORBIT=11", "LORBIT=12"],
        "phonon": ["IBRION=5", "IBRION=6", "IBRION=7", "IBRION=8", "LEPSILON"],
        "relaxation": ["IBRION=1", "IBRION=2", "IBRION=3", "NSW"],
        "static": ["IBRION=-1", "NSW=0"],
        "md": ["IBRION=0", "MDALGO", "TEBEG", "TEEND"],
        "gw": ["ALGO=GW", "ALGO=SCGW", "LHFCALC"],
        "optical": ["LOPTICS", "CSHIFT"],
        "magnetic": ["ISPIN=2", "MAGMOM", "LSORBIT", "LNONCOLLINEAR"],
    }

    # 精度指标
    PRECISION_INDICATORS = {
        "high": {
            "PREC": ["Accurate", "High"],
            "EDIFF": lambda x: x < 1e-6,
            "ENCUT": lambda x: x > 500,
            "KSPACING": lambda x: x < 0.2,
        },
        "medium": {
            "PREC": ["Normal", "Medium"],
            "EDIFF": lambda x: 1e-6 <= x <= 1e-4,
            "ENCUT": lambda x: 300 <= x <= 500,
        },
        "low": {
            "PREC": ["Low", "Single"],
            "EDIFF": lambda x: x > 1e-4,
            "ENCUT": lambda x: x < 300,
            "KSPACING": lambda x: x > 0.4,
        }
    }

    def __init__(self):
        """初始化上下文分析器"""
        self._incar_cache = {}

    def analyze_directory(self, poscar_path: str) -> dict:
        """
        分析POSCAR所在目录

        Args:
            poscar_path: POSCAR文件的路径

        Returns:
            {
                "calculation_type": "relaxation",  # 推断的计算类型
                "precision_level": "standard",     # 精度需求
                "existing_potcar": {...},          # 已有POTCAR配置
                "incar_hints": {...},              # INCAR中的相关参数
                "confidence": 0.8
            }
        """
        poscar_path = Path(poscar_path)

        if not poscar_path.exists():
            return self._empty_result("POSCAR file not found")

        directory = poscar_path.parent

        result = {
            "directory": str(directory),
            "calculation_type": "unknown",
            "precision_level": "medium",
            "existing_potcar": None,
            "incar_hints": {},
            "kpoints_info": None,
            "confidence": 0.5,
            "files_found": [],
            "warnings": []
        }

        # 扫描目录中的文件
        files_found = []
        for f in directory.iterdir():
            if f.is_file():
                files_found.append(f.name)
        result["files_found"] = files_found

        # 分析INCAR
        incar_path = directory / "INCAR"
        if incar_path.exists():
            incar_result = self._analyze_incar(incar_path)
            result["incar_hints"] = incar_result.get("parameters", {})
            result["calculation_type"] = incar_result.get("calc_type", "unknown")
            result["precision_level"] = incar_result.get("precision", "medium")
            result["confidence"] = incar_result.get("confidence", 0.5)

        # 分析KPOINTS
        kpoints_path = directory / "KPOINTS"
        if kpoints_path.exists():
            kpoints_result = self._analyze_kpoints(kpoints_path)
            result["kpoints_info"] = kpoints_result
            # 根据K点密度调整精度判断
            if kpoints_result.get("density") == "high":
                result["precision_level"] = "high"
                result["confidence"] = min(result["confidence"] + 0.1, 1.0)

        # 检查现有POTCAR
        potcar_path = directory / "POTCAR"
        if potcar_path.exists():
            potcar_result = self._analyze_existing_potcar(potcar_path)
            result["existing_potcar"] = potcar_result

        # 检查项目配置文件
        project_config = self._find_project_config(directory)
        if project_config:
            result["project_config"] = project_config

        return result

    def infer_calculation_type(self, incar_content: str) -> str:
        """
        从INCAR内容推断计算类型

        Args:
            incar_content: INCAR文件的文本内容

        Returns:
            推断的计算类型字符串
        """
        if not incar_content:
            return "unknown"

        incar_upper = incar_content.upper()

        # 按优先级检查各种计算类型
        type_scores = {}

        for calc_type, indicators in self.CALC_TYPE_INDICATORS.items():
            score = 0
            for indicator in indicators:
                if indicator.upper() in incar_upper:
                    score += 1
            if score > 0:
                type_scores[calc_type] = score

        if not type_scores:
            # 没有明显特征，根据基本参数判断
            if "NSW" in incar_upper and "IBRION" in incar_upper:
                return "relaxation"
            return "static"

        # 返回得分最高的类型
        return max(type_scores.items(), key=lambda x: x[1])[0]

    def _analyze_incar(self, incar_path: Path) -> dict:
        """分析INCAR文件"""
        try:
            content = incar_path.read_text(encoding='utf-8', errors='ignore')
            parameters = self._parse_incar_parameters(content)

            calc_type = self.infer_calculation_type(content)
            precision = self._infer_precision(parameters)

            # 计算置信度
            confidence = 0.5
            if len(parameters) > 5:
                confidence += 0.2
            if calc_type != "unknown":
                confidence += 0.2
            if precision != "medium":
                confidence += 0.1

            return {
                "parameters": parameters,
                "calc_type": calc_type,
                "precision": precision,
                "confidence": min(confidence, 0.95)
            }

        except Exception as e:
            logger.warning(f"Failed to analyze INCAR: {e}")
            return {"parameters": {}, "calc_type": "unknown", "precision": "medium", "confidence": 0.3}

    def _parse_incar_parameters(self, content: str) -> dict:
        """解析INCAR参数"""
        params = {}
        for line in content.split('\n'):
            # 移除注释
            line = re.split(r'[#!]', line)[0].strip()
            if not line:
                continue

            # 解析 KEY = VALUE
            match = re.match(r'^\s*(\w+)\s*[=:]\s*(.+?)\s*$', line)
            if match:
                key = match.group(1).upper()
                value = match.group(2).strip()
                params[key] = self._parse_value(value)

        return params

    def _parse_value(self, value: str) -> Any:
        """解析参数值"""
        value = value.strip()

        # 布尔值
        if value.upper() in ['.TRUE.', 'TRUE', 'T']:
            return True
        if value.upper() in ['.FALSE.', 'FALSE', 'F']:
            return False

        # 数值
        try:
            if '.' in value or 'E' in value.upper():
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _infer_precision(self, params: dict) -> str:
        """从参数推断精度需求"""
        scores = {"high": 0, "medium": 0, "low": 0}

        # 检查PREC参数
        prec = str(params.get("PREC", "")).upper()
        if "ACCUR" in prec or "HIGH" in prec:
            scores["high"] += 2
        elif "LOW" in prec:
            scores["low"] += 2

        # 检查ENCUT
        encut = params.get("ENCUT", 0)
        if isinstance(encut, (int, float)):
            if encut > 500:
                scores["high"] += 1
            elif encut < 300:
                scores["low"] += 1
            else:
                scores["medium"] += 1

        # 检查EDIFF
        ediff = params.get("EDIFF", 1e-4)
        if isinstance(ediff, (int, float)):
            if ediff < 1e-6:
                scores["high"] += 1
            elif ediff > 1e-4:
                scores["low"] += 1

        # 返回得分最高的精度
        return max(scores.items(), key=lambda x: x[1])[0]

    def _analyze_kpoints(self, kpoints_path: Path) -> dict:
        """分析KPOINTS文件"""
        try:
            content = kpoints_path.read_text(encoding='utf-8', errors='ignore')
            lines = [l.strip() for l in content.split('\n') if l.strip()]

            if len(lines) < 3:
                return {"valid": False, "error": "KPOINTS file too short"}

            result = {
                "valid": True,
                "comment": lines[0],
                "density": "medium"
            }

            # 第二行：网格类型或数目
            second_line = lines[1]

            # 自动生成或手动指定
            if second_line.startswith('0') or second_line.lower().startswith('auto'):
                result["type"] = "automatic"
                if len(lines) > 2:
                    third_line = lines[2].lower()
                    if 'gamma' in third_line:
                        result["mesh_type"] = "Gamma"
                    elif 'monk' in third_line or 'm' in third_line:
                        result["mesh_type"] = "Monkhorst-Pack"

                    # 尝试解析K点网格
                    if len(lines) > 3:
                        kpts = lines[3].split()
                        if len(kpts) >= 3:
                            try:
                                k_grid = [int(k) for k in kpts[:3]]
                                result["grid"] = k_grid
                                # 判断密度
                                min_k = min(k_grid)
                                if min_k >= 8:
                                    result["density"] = "high"
                                elif min_k <= 3:
                                    result["density"] = "low"
                            except ValueError:
                                pass
            else:
                # 显式K点列表
                try:
                    n_kpts = int(second_line)
                    result["type"] = "explicit"
                    result["n_kpoints"] = n_kpts
                    if n_kpts > 100:
                        result["density"] = "high"
                    elif n_kpts < 10:
                        result["density"] = "low"
                except ValueError:
                    result["type"] = "unknown"

            return result

        except Exception as e:
            logger.warning(f"Failed to analyze KPOINTS: {e}")
            return {"valid": False, "error": str(e)}

    def _analyze_existing_potcar(self, potcar_path: Path) -> dict:
        """分析现有POTCAR文件"""
        try:
            # 只读取前面部分以提取元素信息
            content = potcar_path.read_text(encoding='utf-8', errors='ignore')

            elements = []
            titles = []
            enmax_values = []

            # 查找所有TITEL行
            for line in content.split('\n'):
                if 'TITEL' in line:
                    # 格式: TITEL  = PAW_PBE Li_sv 10Sep2004
                    match = re.search(r'TITEL\s*=\s*\w+\s+(\S+)', line)
                    if match:
                        potcar_symbol = match.group(1)
                        titles.append(potcar_symbol)
                        # 提取元素名
                        element = potcar_symbol.split('_')[0]
                        elements.append(element)

                elif 'ENMAX' in line:
                    match = re.search(r'ENMAX\s*=\s*([\d.]+)', line)
                    if match:
                        enmax_values.append(float(match.group(1)))

            return {
                "exists": True,
                "elements": elements,
                "potcar_symbols": titles,
                "enmax_values": enmax_values,
                "recommended_encut": max(enmax_values) * 1.3 if enmax_values else None
            }

        except Exception as e:
            logger.warning(f"Failed to analyze existing POTCAR: {e}")
            return {"exists": True, "error": str(e)}

    def _find_project_config(self, directory: Path) -> Optional[dict]:
        """查找项目级配置文件"""
        config_files = [
            ".vasp_config.yaml",
            ".vasp_config.yml",
            "vasp_config.yaml",
            "potcar_config.yaml"
        ]

        for config_name in config_files:
            config_path = directory / config_name
            if config_path.exists():
                try:
                    import yaml
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f)
                    return {
                        "file": config_name,
                        "content": config
                    }
                except Exception as e:
                    logger.warning(f"Failed to load project config {config_name}: {e}")

        # 向上查找父目录
        parent = directory.parent
        if parent != directory:
            for config_name in config_files:
                config_path = parent / config_name
                if config_path.exists():
                    try:
                        import yaml
                        with open(config_path, 'r') as f:
                            config = yaml.safe_load(f)
                        return {
                            "file": str(config_path),
                            "content": config,
                            "inherited": True
                        }
                    except Exception:
                        pass

        return None

    def _empty_result(self, message: str) -> dict:
        """返回空结果"""
        return {
            "directory": None,
            "calculation_type": "unknown",
            "precision_level": "medium",
            "existing_potcar": None,
            "incar_hints": {},
            "confidence": 0.0,
            "error": message
        }
