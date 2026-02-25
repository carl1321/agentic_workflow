"""
上下文分析模块

目的：
    利用更多上下文信息辅助决策，而不仅仅依赖POSCAR结构。
    包括：同目录的其他VASP文件、用户历史偏好、项目级设置等。

包含：
    - analyzer.py: 上下文分析器，读取周边文件推断计算类型
    - history.py: 用户历史记录管理

设计原则：
    1. 非侵入：上下文信息是辅助，不强制依赖
    2. 隐私：用户历史存储在本地，不上传
"""

from .analyzer import ContextAnalyzer
from .history import UserHistory
