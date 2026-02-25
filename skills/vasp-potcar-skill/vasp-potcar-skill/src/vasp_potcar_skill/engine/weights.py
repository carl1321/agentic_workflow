"""
数据源权重配置

目的：
    定义各数据源的权重和优先级。
    根据计算类型动态调整权重。

计算类型说明：
    - standard: 标准计算，使用知识库默认推荐
    - accurate: 高精度计算，优先使用 API 推荐（更多价电子）
    - gw: GW计算，必须使用 _GW 后缀赝势
    - phonon: 声子计算，需要硬赝势
    - magnetic: 磁性计算，需要考虑自旋极化

计算精度说明：
    - low: 快速测试，使用最基础的赝势
    - medium: 常规计算（默认）
    - high: 高精度计算，使用包含更多价电子的赝势
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CalculationType(Enum):
    """计算类型"""
    STANDARD = "standard"      # 标准结构优化/静态计算
    ACCURATE = "accurate"      # 高精度计算
    GW = "gw"                  # GW准粒子计算
    PHONON = "phonon"          # 声子计算
    MAGNETIC = "magnetic"      # 磁性计算
    BAND = "band"              # 能带计算
    DOS = "dos"                # 态密度计算
    OPTICAL = "optical"        # 光学性质计算


class CalculationPrecision(Enum):
    """计算精度"""
    LOW = "low"           # 快速测试
    MEDIUM = "medium"     # 常规计算
    HIGH = "high"         # 高精度


@dataclass
class SourceWeight:
    """数据源权重"""
    knowledge_base: float    # 知识库权重
    api_mp: float           # Materials Project API 权重
    api_aflow: float        # AFLOW API 权重
    pymatgen: float         # pymatgen 推荐权重
    vaspkit: float          # vaspkit 推荐权重
    mongodb: float          # MongoDB 历史数据权重


# 不同计算类型的默认权重配置
WEIGHT_PROFILES = {
    # 标准计算：知识库优先
    CalculationType.STANDARD: SourceWeight(
        knowledge_base=1.0,
        api_mp=0.7,
        api_aflow=0.5,
        pymatgen=0.6,
        vaspkit=0.65,  # vaspkit 略高于 pymatgen
        mongodb=0.8
    ),
    # 高精度计算：API优先（包含更多价电子）
    CalculationType.ACCURATE: SourceWeight(
        knowledge_base=0.6,
        api_mp=1.0,
        api_aflow=0.7,
        pymatgen=0.9,
        vaspkit=0.85,
        mongodb=0.8
    ),
    # GW计算：知识库的GW规则优先
    CalculationType.GW: SourceWeight(
        knowledge_base=1.0,  # 必须用_GW后缀
        api_mp=0.3,
        api_aflow=0.2,
        pymatgen=0.4,
        vaspkit=0.35,
        mongodb=0.5
    ),
    # 声子计算：知识库优先（需要硬赝势）
    CalculationType.PHONON: SourceWeight(
        knowledge_base=1.0,
        api_mp=0.5,
        api_aflow=0.4,
        pymatgen=0.5,
        vaspkit=0.55,
        mongodb=0.7
    ),
    # 磁性计算：API和知识库并重
    CalculationType.MAGNETIC: SourceWeight(
        knowledge_base=0.9,
        api_mp=0.9,
        api_aflow=0.6,
        pymatgen=0.8,
        vaspkit=0.8,
        mongodb=0.8
    ),
    # 能带计算：API优先（精确能带需要更多价电子）
    CalculationType.BAND: SourceWeight(
        knowledge_base=0.7,
        api_mp=1.0,
        api_aflow=0.6,
        pymatgen=0.9,
        vaspkit=0.85,
        mongodb=0.7
    ),
    # 态密度计算：与能带类似
    CalculationType.DOS: SourceWeight(
        knowledge_base=0.7,
        api_mp=1.0,
        api_aflow=0.6,
        pymatgen=0.9,
        vaspkit=0.85,
        mongodb=0.7
    ),
    # 光学性质：高精度，API优先
    CalculationType.OPTICAL: SourceWeight(
        knowledge_base=0.6,
        api_mp=1.0,
        api_aflow=0.6,
        pymatgen=0.9,
        vaspkit=0.85,
        mongodb=0.6
    ),
}

# 精度调整因子
PRECISION_MODIFIERS = {
    CalculationPrecision.LOW: {
        "prefer_minimal": True,      # 优先使用最少价电子的赝势
        "api_weight_factor": 0.5,    # 降低API权重
        "kb_weight_factor": 1.2,     # 提高知识库权重
    },
    CalculationPrecision.MEDIUM: {
        "prefer_minimal": False,
        "api_weight_factor": 1.0,
        "kb_weight_factor": 1.0,
    },
    CalculationPrecision.HIGH: {
        "prefer_minimal": False,
        "api_weight_factor": 1.3,    # 提高API权重
        "kb_weight_factor": 0.8,     # 降低知识库权重
    },
}


class WeightConfig:
    """
    权重配置管理

    职责：
        1. 根据计算类型和精度返回对应权重
        2. 支持自定义权重调整
        3. 提供数据源优先级比较
    """

    # 数据源类型常量
    SOURCE_KNOWLEDGE_BASE = "knowledge_base"
    SOURCE_API_MP = "api_mp"
    SOURCE_API_AFLOW = "api_aflow"
    SOURCE_PYMATGEN = "pymatgen"
    SOURCE_VASPKIT = "vaspkit"
    SOURCE_MONGODB = "mongodb"
    SOURCE_USER_HISTORY = "user_history"

    def __init__(
        self,
        calc_type: CalculationType = CalculationType.STANDARD,
        precision: CalculationPrecision = CalculationPrecision.MEDIUM
    ):
        """
        初始化权重配置

        Args:
            calc_type: 计算类型
            precision: 计算精度
        """
        self.calc_type = calc_type
        self.precision = precision
        self._base_weights = WEIGHT_PROFILES.get(calc_type, WEIGHT_PROFILES[CalculationType.STANDARD])
        self._precision_modifier = PRECISION_MODIFIERS.get(precision, PRECISION_MODIFIERS[CalculationPrecision.MEDIUM])

    def get_weight(self, source_type: str, match_quality: float = 1.0) -> float:
        """
        获取数据源权重

        Args:
            source_type: 数据源类型
            match_quality: 匹配质量 (0-1)

        Returns:
            调整后的权重值
        """
        # 用户历史始终最高权重
        if source_type == self.SOURCE_USER_HISTORY:
            return 1.5 * match_quality

        # 获取基础权重
        base_weight = getattr(self._base_weights, source_type, 0.5)

        # 应用精度调整
        if source_type in [self.SOURCE_API_MP, self.SOURCE_API_AFLOW, self.SOURCE_PYMATGEN, self.SOURCE_VASPKIT]:
            base_weight *= self._precision_modifier["api_weight_factor"]
        elif source_type == self.SOURCE_KNOWLEDGE_BASE:
            base_weight *= self._precision_modifier["kb_weight_factor"]

        return base_weight * match_quality

    def get_all_weights(self) -> dict[str, float]:
        """获取所有数据源的权重"""
        return {
            self.SOURCE_KNOWLEDGE_BASE: self.get_weight(self.SOURCE_KNOWLEDGE_BASE),
            self.SOURCE_API_MP: self.get_weight(self.SOURCE_API_MP),
            self.SOURCE_API_AFLOW: self.get_weight(self.SOURCE_API_AFLOW),
            self.SOURCE_PYMATGEN: self.get_weight(self.SOURCE_PYMATGEN),
            self.SOURCE_VASPKIT: self.get_weight(self.SOURCE_VASPKIT),
            self.SOURCE_MONGODB: self.get_weight(self.SOURCE_MONGODB),
            self.SOURCE_USER_HISTORY: self.get_weight(self.SOURCE_USER_HISTORY),
        }

    def compare(self, source_a: str, source_b: str) -> int:
        """
        比较两个数据源的优先级

        Returns:
            1 if source_a > source_b
            -1 if source_a < source_b
            0 if equal
        """
        weight_a = self.get_weight(source_a)
        weight_b = self.get_weight(source_b)

        if weight_a > weight_b:
            return 1
        elif weight_a < weight_b:
            return -1
        return 0

    def should_prefer_minimal_valence(self) -> bool:
        """是否应该优先使用最少价电子的赝势"""
        return self._precision_modifier.get("prefer_minimal", False)

    @classmethod
    def from_string(
        cls,
        calc_type: str = "standard",
        precision: str = "medium"
    ) -> "WeightConfig":
        """从字符串创建配置"""
        try:
            ct = CalculationType(calc_type.lower())
        except ValueError:
            ct = CalculationType.STANDARD

        try:
            pr = CalculationPrecision(precision.lower())
        except ValueError:
            pr = CalculationPrecision.MEDIUM

        return cls(calc_type=ct, precision=pr)

    def get_description(self) -> str:
        """获取当前配置的描述"""
        descriptions = {
            CalculationType.STANDARD: "标准计算 - 使用VASP官方推荐的默认赝势",
            CalculationType.ACCURATE: "高精度计算 - 使用包含更多价电子的赝势",
            CalculationType.GW: "GW计算 - 使用专门的GW赝势（_GW后缀）",
            CalculationType.PHONON: "声子计算 - 使用硬赝势以确保力的精度",
            CalculationType.MAGNETIC: "磁性计算 - 考虑自旋极化的赝势选择",
            CalculationType.BAND: "能带计算 - 使用精确描述能带的赝势",
            CalculationType.DOS: "态密度计算 - 与能带计算类似的赝势需求",
            CalculationType.OPTICAL: "光学性质计算 - 高精度赝势以描述光学跃迁",
        }
        return descriptions.get(self.calc_type, "未知计算类型")


# 计算类型的用户友好描述（用于询问用户）
CALCULATION_TYPE_OPTIONS = [
    {
        "value": "standard",
        "label": "Standard (结构优化/静态计算)",
        "description": "常规结构优化、静态计算、能量计算"
    },
    {
        "value": "accurate",
        "label": "Accurate (高精度计算)",
        "description": "需要高精度的计算，使用更多价电子"
    },
    {
        "value": "band",
        "label": "Band Structure (能带计算)",
        "description": "能带结构计算，需要精确描述电子态"
    },
    {
        "value": "dos",
        "label": "DOS (态密度计算)",
        "description": "电子态密度计算"
    },
    {
        "value": "phonon",
        "label": "Phonon (声子计算)",
        "description": "声子频率和热力学性质计算"
    },
    {
        "value": "magnetic",
        "label": "Magnetic (磁性计算)",
        "description": "磁性材料的自旋极化计算"
    },
    {
        "value": "gw",
        "label": "GW (准粒子计算)",
        "description": "GW近似的准粒子能带计算"
    },
    {
        "value": "optical",
        "label": "Optical (光学性质)",
        "description": "介电函数、光学吸收等计算"
    },
]

CALCULATION_PRECISION_OPTIONS = [
    {
        "value": "low",
        "label": "Low (快速测试)",
        "description": "用于快速测试，使用基础赝势"
    },
    {
        "value": "medium",
        "label": "Medium (常规精度)",
        "description": "常规计算，平衡精度和效率"
    },
    {
        "value": "high",
        "label": "High (高精度)",
        "description": "发表级精度，使用更完整的赝势"
    },
]
