from langchain_core.tools import tool
from typing import Union, List
import os

from .tool_search import Search
from .tool_visit import Visit
from .tool_scholar import Scholar
from .tool_python import PythonInterpreter
from src.config.loader import load_yaml_config

# 从conf.yaml加载配置
def load_deepresearch_config():
    """从conf.yaml加载DeepResearch配置"""
    config = load_yaml_config("conf.yaml")
    deepresearch_config = config.get("DEEPRESEARCH_APIS", {})
    basic_model = config.get("BASIC_MODEL", {})
    
    return {
        "serper_key": deepresearch_config.get("serper_key"),
        "jina_key": deepresearch_config.get("jina_key"),
        "use_unified_model": deepresearch_config.get("use_unified_model", True),
        "api_key": basic_model.get("api_key"),
        "api_base": basic_model.get("base_url"),
        "model_name": basic_model.get("model")
    }

# 检查配置是否完整
def check_deepresearch_config():
    """检查DeepResearch配置是否完整"""
    config = load_deepresearch_config()
    required_keys = ['serper_key', 'jina_key', 'api_key', 'api_base', 'model_name']
    missing_keys = [key for key in required_keys if not config.get(key)]
    return len(missing_keys) == 0, missing_keys, config

# 创建LangChain工具包装
@tool
def search(query: List[str]) -> str:
    """Perform Google web searches. Accepts multiple queries."""
    # 设置环境变量
    config = load_deepresearch_config()
    os.environ['SERPER_KEY_ID'] = config['serper_key']
    
    search_tool = Search()
    return search_tool.call({"query": query})

@tool
def visit(url: Union[str, List[str]], goal: str) -> str:
    """Visit webpage(s) and return the summary of the content."""
    # 设置环境变量
    config = load_deepresearch_config()
    os.environ['JINA_API_KEYS'] = config['jina_key']
    os.environ['API_KEY'] = config['api_key']
    os.environ['API_BASE'] = config['api_base']
    os.environ['SUMMARY_MODEL_NAME'] = config['model_name']
    
    visit_tool = Visit()
    return visit_tool.call({"url": url, "goal": goal})

@tool
def google_scholar(query: List[str]) -> str:
    """Leverage Google Scholar to retrieve academic publications."""
    # 设置环境变量
    config = load_deepresearch_config()
    os.environ['SERPER_KEY_ID'] = config['serper_key']
    
    scholar_tool = Scholar()
    return scholar_tool.call({"query": query})

@tool  
def python_interpreter(code: str) -> str:
    """Execute Python code in a sandboxed environment. Use print() for output."""
    python_tool = PythonInterpreter()
    return python_tool.call(code)

def get_deep_research_tools():
    """返回所有DeepResearch工具"""
    config_ok, missing_keys, config = check_deepresearch_config()
    
    if not config_ok:
        print(f"⚠️  DeepResearch工具需要以下配置: {', '.join(missing_keys)}")
        print("📝 请在 conf.yaml 中配置 DEEPRESEARCH_APIS 部分")
        print("🔄 将使用回退工具...")
        
        # 返回回退工具
        from src.tools import get_web_search_tool, crawl_tool, python_repl_tool
        
        return [
            get_web_search_tool(3),  # 使用现有的web_search工具
            crawl_tool,              # 使用现有的crawl工具
            python_repl_tool         # 使用现有的python工具
        ]
    
    print(f"✅ DeepResearch工具配置完整，使用统一模型: {config['model_name']}")
    return [search, visit, google_scholar, python_interpreter]