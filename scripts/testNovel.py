#!/usr/bin/env python3
"""
LangChain 兼容的 Qwen API 客户端示例
展示如何使用 LangChain 调用部署的 Qwen 模型
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

def example_langchain_basic():
    """示例1: 基础 LangChain 调用"""
    print("=" * 70)
    print("示例1: 基础 LangChain 调用")
    print("=" * 70)
    
    # 初始化 LangChain ChatOpenAI 客户端
    # 服务器已使用 --served-model-name，可以使用简短名称
    llm = ChatOpenAI(
        model="Qwen-32B-Novel",  # 使用简短名称（服务器已配置）
        base_url="http://122.193.22.114:8888/v1",  # vLLM API 端点（注意 /v1 后缀）
        api_key="sk-6tT86nzygIVWl0naxnWo8SjI4ClTSzYl05nppF9sYuY",  # 你的 API key
        temperature=0.7,
        max_tokens=500,
        timeout=300,  # 超时时间（秒）
    )
    
    # 发送消息
    messages = [
        SystemMessage(content="你是一个专业的小说写作助手。"),
        HumanMessage(content="写一个科幻小说的开头，大约200字")
    ]
    
    try:
        response = llm.invoke(messages)
        print(f"\n响应: {response.content}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


def example_langchain_streaming():
    """示例2: 流式输出"""
    print("\n" + "=" * 70)
    print("示例2: 流式输出")
    print("=" * 70)
    
    llm = ChatOpenAI(
        model="Qwen-32B-Novel",  # 使用简短名称
        base_url="http://localhost:8888/v1",
        api_key="sk-6tT86nzygIVWl0naxnWo8SjI4ClTSzYl05nppF9sYuY",
        temperature=0.7,
        max_tokens=500,
        streaming=True,  # 启用流式输出
        timeout=300,
    )
    
    messages = [
        HumanMessage(content="写一首关于春天的诗")
    ]
    
    try:
        print("流式输出:\n")
        for chunk in llm.stream(messages):
            if chunk.content:
                print(chunk.content, end='', flush=True)
        print("\n")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


def example_langchain_async():
    """示例3: 异步调用"""
    print("\n" + "=" * 70)
    print("示例3: 异步调用")
    print("=" * 70)
    
    import asyncio
    
    llm = ChatOpenAI(
        model="Qwen-32B-Novel",  # 使用简短名称
        base_url="http://localhost:8888/v1",
        api_key="sk-6tT86nzygIVWl0naxnWo8SjI4ClTSzYl05nppF9sYuY",
        temperature=0.7,
        max_tokens=500,
        timeout=300,
    )
    
    async def async_call():
        messages = [
            HumanMessage(content="什么是人工智能？")
        ]
        
        try:
            response = await llm.ainvoke(messages)
            print(f"\n响应: {response.content}")
        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(async_call())


def example_langchain_chain():
    """示例4: 使用 LangChain Chain"""
    print("\n" + "=" * 70)
    print("示例4: 使用 LangChain Chain")
    print("=" * 70)
    
    from langchain.chains import LLMChain
    from langchain.prompts import ChatPromptTemplate
    
    llm = ChatOpenAI(
        model="Qwen-32B-Novel",  # 使用简短名称
        base_url="http://localhost:8888/v1",
        api_key="sk-6tT86nzygIVWl0naxnWo8SjI4ClTSzYl05nppF9sYuY",
        temperature=0.7,
        max_tokens=500,
        timeout=300,
    )
    
    # 创建提示模板
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个专业的小说写作助手。"),
        ("human", "{input}")
    ])
    
    # 创建链
    chain = LLMChain(llm=llm, prompt=prompt)
    
    try:
        result = chain.invoke({"input": "写一个关于时间旅行的故事开头"})
        print(f"\n响应: {result['text']}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


def example_langchain_with_custom_config():
    """示例5: 自定义配置（从配置文件加载）"""
    print("\n" + "=" * 70)
    print("示例5: 从配置加载")
    print("=" * 70)
    
    import json
    from pathlib import Path
    
    # 从配置文件加载（类似你的配置格式）
    config = {
        "name": "Qwen-32B-Novel",
        "base_url": "http://localhost:8888",
        "model": "Qwen-32B-Novel",
        "api_key": "sk-6tT86nzygIVWl0naxnWo8SjI4ClTSzYl05nppF9sYuY",
        "supports_thinking": False,
        "max_retries": 3
    }
    
    # 初始化 LangChain 客户端
    # 注意：base_url 需要添加 /v1 后缀
    # 初始化 LangChain 客户端
    # 注意：base_url 需要添加 /v1 后缀
    base_url = config['base_url']
    if not base_url.endswith('/v1'):
        base_url = f"{base_url}/v1"
    
    llm = ChatOpenAI(
        model=config["model"],  # 使用配置中的模型名称
        base_url=base_url,
        api_key=config["api_key"],
        temperature=0.7,
        max_tokens=500,
        timeout=300,
        max_retries=config.get("max_retries", 3),
    )
    
    messages = [
        HumanMessage(content="你好，请介绍一下你自己")
    ]
    
    try:
        response = llm.invoke(messages)
        print(f"\n响应: {response.content}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        print("\n💡 常见问题排查:")
        print("   1. 检查 base_url 是否正确（需要包含 /v1 后缀）")
        print("   2. 检查 API key 是否正确")
        print("   3. 检查服务器是否运行: curl http://122.193.22.114:8888/health")
        print("   4. 检查模型名称是否正确: Qwen-32B-Novel 或 Qwen-32B-Instruct")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 运行示例（根据需要取消注释）
    
    # 示例1: 基础调用
    example_langchain_basic()
    
    # 示例2: 流式输出
    # example_langchain_streaming()
    
    # 示例3: 异步调用
    # example_langchain_async()
    
    # 示例4: 使用 Chain
    # example_langchain_chain()
    
    # 示例5: 从配置加载
    # example_langchain_with_custom_config()

