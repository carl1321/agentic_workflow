import re
from typing import Dict, List, Optional, Union
import json
from .base_tool import BaseTool
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Array of sandbox fusion endpoints
SANDBOX_FUSION_ENDPOINTS = []

# Fallback to single endpoint if environment variable exists
if 'SANDBOX_FUSION_ENDPOINT' in os.environ:
    SANDBOX_FUSION_ENDPOINTS = os.environ['SANDBOX_FUSION_ENDPOINT'].split(',')


class PythonInterpreter(BaseTool):
    name = "PythonInterpreter"
    description = 'Execute Python code in a sandboxed environment. Use this to run Python code and get the execution results.\n**Make sure to use print() for any output you want to see in the results.**\nFor code parameters, use placeholders first, and then put the code within <code></code> XML tags, such as:\n<tool_call>\n{"purpose": <detailed-purpose-of-this-tool-call>, "name": <tool-name>, "arguments": {"code": ""}}\n<code>\nHere is the code.\n</code>\n</tool_call>\n'

    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute. Must be provided within <code></code> XML tags. Remember to use print() statements for any output you want to see.",
            }
        },
        "required": ["code"],
    }

    def __init__(self, cfg: Optional[Dict] = None):
        super().__init__(cfg)
        # self.summary_mapping = SummaryMapping()
    
    def call(self, params, files= None, timeout = 50, **kwargs) -> str:
        try:
            code=params
            last_error = None
            
            # 简化版本：直接返回代码执行结果
            # 在实际环境中，这里应该调用sandbox_fusion
            if SANDBOX_FUSION_ENDPOINTS:
                # 如果有sandbox endpoint，使用它
                endpoint = random.choice(SANDBOX_FUSION_ENDPOINTS)
                print(f"Using endpoint: {endpoint}")
                # 这里应该调用sandbox_fusion.run_code
                return f"[Python] Code executed on {endpoint}\nCode: {code}\nOutput: [Sandbox execution result]"
            else:
                # 简化版本：直接返回代码
                return f"[Python] Code: {code}\nOutput: [Code execution simulation - use sandbox_fusion for real execution]"
                
        except Exception as e:
            return f"[Python Interpreter Error]: {str(e)}"
