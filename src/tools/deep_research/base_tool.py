"""qwen_agent工具基类适配"""
from typing import Optional, Dict, Any


class BaseTool:
    """简化的qwen_agent BaseTool适配"""
    name = ""
    description = ""
    parameters = {}
    
    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or {}
    
    def call(self, params, **kwargs):
        """工具调用方法"""
        raise NotImplementedError
    
    def _verify_json_format_args(self, params):
        """验证JSON格式参数"""
        if isinstance(params, str):
            import json
            return json.loads(params)
        return params
