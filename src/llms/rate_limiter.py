# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
LLM调用限流器
限制1秒内最多5次LLM调用请求
"""

import asyncio
import time
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class LLMRateLimiter:
    """
    基于滑动窗口的LLM调用限流器
    限制1秒内最多5次调用
    """
    
    def __init__(self, max_calls: int = 5, time_window: float = 1.0):
        """
        初始化限流器
        
        Args:
            max_calls: 时间窗口内允许的最大调用次数
            time_window: 时间窗口大小（秒）
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self._call_times: deque[float] = deque()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """
        获取调用许可，如果超过限制则等待
        
        这个方法会阻塞直到可以发起调用
        """
        async with self._lock:
            current_time = time.time()
            
            # 清理超过时间窗口的调用记录
            while self._call_times and current_time - self._call_times[0] > self.time_window:
                self._call_times.popleft()
            
            # 如果当前窗口内的调用次数已达到上限，需要等待
            if len(self._call_times) >= self.max_calls:
                # 计算需要等待的时间（最早的那次调用过期的时间）
                oldest_call_time = self._call_times[0]
                wait_time = self.time_window - (current_time - oldest_call_time) + 0.01  # 加0.01秒缓冲
                
                if wait_time > 0:
                    logger.debug(f"Rate limit reached ({len(self._call_times)}/{self.max_calls} calls in {self.time_window}s), waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    
                    # 等待后再次清理过期记录
                    current_time = time.time()
                    while self._call_times and current_time - self._call_times[0] > self.time_window:
                        self._call_times.popleft()
            
            # 记录本次调用时间
            self._call_times.append(time.time())
            logger.debug(f"LLM call acquired, current window: {len(self._call_times)}/{self.max_calls} calls")
    
    def get_current_count(self) -> int:
        """
        获取当前时间窗口内的调用次数（不阻塞）
        
        Returns:
            当前窗口内的调用次数
        """
        current_time = time.time()
        # 清理过期记录
        while self._call_times and current_time - self._call_times[0] > self.time_window:
            self._call_times.popleft()
        return len(self._call_times)


# 全局限流器实例
_global_rate_limiter: Optional[LLMRateLimiter] = None


def get_llm_rate_limiter() -> LLMRateLimiter:
    """
    获取全局LLM限流器实例（单例模式）
    
    Returns:
        LLMRateLimiter实例
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = LLMRateLimiter(max_calls=5, time_window=1.0)
    return _global_rate_limiter


async def acquire_llm_call_permission() -> None:
    """
    获取LLM调用许可（便捷函数）
    
    如果超过限制，此函数会阻塞直到可以调用
    """
    limiter = get_llm_rate_limiter()
    await limiter.acquire()
