"""
反馈学习模块

目的：
    建立闭环反馈机制，将用户的实际选择回写到数据库，
    逐步积累领域特定的最佳实践，提升推荐质量。

包含：
    - collector.py: 反馈数据收集
    - writer.py: 回写MongoDB
    - analyzer.py: 推荐效果分析

设计原则：
    1. 被动收集：只记录用户主动确认的选择
    2. 可追溯：记录推荐值vs实际值，便于分析
    3. 增量学习：新数据自动提升后续推荐质量
"""

from .collector import FeedbackCollector
from .writer import FeedbackWriter
