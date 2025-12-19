import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Union
import requests
from .base_tool import BaseTool
import asyncio
from typing import Dict, List, Optional, Union
import uuid
import http.client
import json

import os


class Search(BaseTool):
    name = "search"
    description = "Performs general web searches for Wikipedia articles, blogs, technical websites, and general information. Use this for broad exploration and conceptual understanding. Supply an array 'query'; the tool retrieves the top 10 results for each query in one call."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": "Array of query strings. Include multiple complementary search queries in a single call."
            },
        },
        "required": ["query"],
    }

    def __init__(self, cfg: Optional[dict] = None):
        super().__init__(cfg)
    def google_search_with_serp(self, query: str):
        # 动态获取API密钥
        serper_key = os.environ.get('SERPER_KEY_ID')
        if not serper_key:
            return "Error: SERPER_KEY_ID environment variable not set"
        
        def contains_chinese_basic(text: str) -> bool:
            return any('\u4E00' <= char <= '\u9FFF' for char in text)
        
        if contains_chinese_basic(query):
            payload = json.dumps({
                "q": query,
                "location": "China",
                "gl": "cn",
                "hl": "zh-cn"
            })
            
        else:
            payload = json.dumps({
                "q": query,
                "location": "United States",
                "gl": "us",
                "hl": "en"
            })
        headers = {
                'X-API-KEY': serper_key,  # 使用动态获取的密钥
                'Content-Type': 'application/json'
            }
        
        
        for i in range(3):  # 减少重试次数
            try:
                conn = http.client.HTTPSConnection("google.serper.dev", timeout=30)  # 添加超时
                conn.request("POST", "/search", payload, headers)
                res = conn.getresponse()
                
                if res.status == 200:
                    data = res.read()
                    conn.close()
                    break
                else:
                    conn.close()
                    if i == 2:  # 最后一次重试
                        return f"Google search API error: HTTP {res.status}"
                    continue
                    
            except Exception as e:
                print(f"Google search request error (attempt {i+1}): {e}")
                if i == 2:  # 最后一次重试
                    return f"Google search Timeout, return None, Please try again later."
                continue
        results = json.loads(data.decode("utf-8"))

        try:
            if "organic" not in results:
                raise Exception(f"No results found for query: '{query}'. Use a less specific query.")

            web_snippets = list()
            idx = 0
            if "organic" in results:
                for page in results["organic"]:
                    idx += 1
                    date_published = ""
                    if "date" in page:
                        date_published = "\nDate published: " + page["date"]

                    source = ""
                    if "source" in page:
                        source = "\nSource: " + page["source"]

                    snippet = ""
                    if "snippet" in page:
                        snippet = "\n" + page["snippet"]

                    redacted_version = f"{idx}. [{page['title']}]({page['link']}){date_published}{source}\n{snippet}"
                    redacted_version = redacted_version.replace("Your browser can't play this video.", "")
                    web_snippets.append(redacted_version)

            content = f"A Google search for '{query}' found {len(web_snippets)} results:\n\n## Web Results\n" + "\n\n".join(web_snippets)
            return content
        except:
            return f"No results found for '{query}'. Try with a more general query."


    
    def search_with_serp(self, query: str):
        result = self.google_search_with_serp(query)
        return result

    def call(self, params: Union[str, dict], **kwargs) -> str:
        try:
            query = params["query"]
        except:
            return "[Search] Invalid request format: Input must be a JSON object containing 'query' field"
        
        if isinstance(query, str):
            # 单个查询
            response = self.search_with_serp(query)
        else:
            # 多个查询
            assert isinstance(query, List)
            responses = []
            for q in query:
                responses.append(self.search_with_serp(q))
            response = "\n=======\n".join(responses)
            
        return response
