"""
验证模块

目的：
    在生成POTCAR后进行自动验证，检测常见错误和兼容性问题。
    提供"防呆"机制，避免低级错误。

包含：
    - potcar_validator.py: POTCAR文件验证
    - compatibility.py: 与其他VASP文件的兼容性检查

设计原则：
    1. 非阻塞：验证失败给出警告，不强制阻止
    2. 可配置：验证规则可开关
    3. 详细报告：指出具体问题和修复建议
"""

from .potcar_validator import PotcarValidator
from .compatibility import CompatibilityChecker
