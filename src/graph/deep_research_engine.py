# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from src.config.configuration import Configuration
from src.utils.json_utils import repair_json_output

logger = logging.getLogger(__name__)


@dataclass
class DeepResearchResult:
    """Final deep research result"""
    final_report: str
    iteration_count: int
    tools_used: List[str]
    iterations: List[Dict[str, Any]]
    success: bool
    error_message: Optional[str] = None


class WorkspaceManager:
    """
    管理每轮迭代的精简上下文 - 对齐DeepResearch
    """
    
    def __init__(self, tools: List[BaseTool] = None):
        self.tools = tools or []
    
    def build_workspace(
        self,
        messages: List[Dict[str, str]],
        step_info: Dict[str, Any],
        iteration: int = 0,
        step_context: Dict[str, Any] = None
    ) -> List[Dict[str, str]]:
        """构建工作空间 - 完全对齐DeepResearch"""
        
        if iteration == 1:
            # 获取步骤上下文信息
            current_step = step_context.get('current_step', 1)
            total_steps = step_context.get('total_steps', 1)
            is_final_step = step_context.get('is_final_step', True)
            research_depth = step_context.get('research_depth', 'simple')
            completed_steps = step_context.get('completed_steps', [])
            
            # 根据研究深度过滤工具
            # 新工具集：knowledge_base (local_search_tool), google_scholar, pdf_crawler (fetch_pdf_text), python_repl_tool
            tool_names_simple = ['local_search_tool', 'google_scholar', 'python_repl_tool']
            tool_names_deep = ['local_search_tool', 'google_scholar', 'pdf_crawler', 'python_repl_tool']
            
            if research_depth == 'simple':
                available_tools = [t for t in self.tools if t.name in tool_names_simple]
            else:
                available_tools = [t for t in self.tools if t.name in tool_names_deep]
            
            # 生成工具定义
            tools_str = self._generate_tools_str(available_tools)
            
            # 检查是否有知识库工具
            has_knowledge_base = any(t.name == 'local_search_tool' for t in available_tools)
            
            # 格式化已完成步骤
            completed_steps_summary = self._format_completed_steps_summary(completed_steps)
            
            # 知识库优先级说明
            knowledge_base_priority = ""
            if has_knowledge_base:
                knowledge_base_priority = """
**CRITICAL: Knowledge Base Priority**
- If knowledge base (local_search_tool) is available, you MUST use it FIRST before any other search tools
- Only use google_scholar or pdf_crawler if knowledge base doesn't provide sufficient information
- The knowledge base contains curated, high-quality information that should be prioritized
"""
            
            system_prompt = f"""You are a deep research assistant conducting a multi-step research task.

# Research Context

**Current Status**: Step {current_step} of {total_steps}
**Research Depth**: {research_depth.upper()}
**Is Final Step**: {"Yes" if is_final_step else "No"}

{completed_steps_summary}

{knowledge_base_priority}

# CRITICAL Instructions

{"⚠️  THIS IS NOT THE FINAL STEP - Focus ONLY on the current step task. Do NOT use <answer> tag yet" if not is_final_step else "✓ THIS IS THE FINAL STEP - Complete current task first, then review ALL previous steps and provide comprehensive answer"}

**STEP BOUNDARY ENFORCEMENT**: 
- You are ONLY working on Step {current_step}: "{step_info.get('title', '')}"
- Do NOT work on other steps' tasks
- Do NOT mix tasks from different steps
- Focus exclusively on: {step_info.get('description', '')}

{f"**Important**: All findings from previous {current_step-1} steps are available in the conversation history above. Review them carefully before providing your final answer." if is_final_step and current_step > 1 else ""}

# Response Format

You MUST structure your response with these XML tags:

1. **Thinking Process** (Optional but recommended):
<think>
Explain your reasoning, what information you need, which tools to use...
</think>

2. **Tool Calls**:
<tool_call>
{{"name": "local_search_tool", "arguments": {{"keywords": "keyword1 keyword2"}}}}
</tool_call>
OR
<tool_call>
{{"name": "google_scholar", "arguments": {{"query": ["keyword1 keyword2", "keyword3"]}}}}
</tool_call>
OR
<tool_call>
{{"name": "pdf_crawler", "arguments": {{"url": "https://example.com/paper.pdf"}}}}
</tool_call>

3. **Final Answer** (ONLY in last step):
{"Do NOT use <answer> tag - there are more steps to complete" if not is_final_step else """<answer>
... comprehensive answer synthesizing ALL previous findings ...
</answer>"""}

# Tools

<tools>
{tools_str}
</tools>

# Tool Usage Guidelines

{("- **local_search_tool** (Knowledge Base): Search curated knowledge base FIRST if available\n  - Format: {{\"keywords\": \"search keywords\"}}\n  - Example: {{\"keywords\": \"钙钛矿 NIP 结构\"}}\n  - Priority: Use this FIRST before any other search tools\n" if has_knowledge_base else "")}- **google_scholar**: Search academic literature and research papers
  - Format: {{"query": ["keyword1 keyword2", "keyword3 keyword4"]}}
  - Example: {{"query": ["钙钛矿 NIP 结构 性能", "钙钛矿 PIN 结构 对比"]}}
  - Use when: Knowledge base doesn't provide sufficient information or for academic papers
{"- **pdf_crawler**: Extract text content from PDF documents\n  - Format: {{\"url\": \"https://example.com/paper.pdf\"}}\n  - Example: {{\"url\": \"https://arxiv.org/pdf/1234.5678.pdf\"}}\n  - Use when: You need to extract detailed content from PDF documents\n" if research_depth == "deep" else ""}- **python_repl_tool**: Data analysis and calculations (REQUIRED for deep research)
  - Format: {{"code": "python code here"}}
  - Use when: You need to perform calculations, data analysis, or process research data
  - **Note**: This tool is essential for literature research and data processing. If it's disabled, please enable it in configuration.

# Multi-Round Conversation

You can make multiple tool calls in sequence:

Round 1:
<think>Need to search for information. {"Checking knowledge base first..." if has_knowledge_base else "Searching academic literature..."}</think>
<tool_call>
{("{{\"name\": \"local_search_tool\", \"arguments\": {{\"keywords\": \"keyword1 keyword2\"}}}}" if has_knowledge_base else "{{\"name\": \"google_scholar\", \"arguments\": {{\"query\": [\"keyword1\", \"keyword2\"]}}}}")}
</tool_call>

[Tool response will be provided]

Round 2:
<think>{"Knowledge base provided some info, but need more academic sources..." if has_knowledge_base else "Found promising papers, need to extract detailed content..."}</think>
<tool_call>
{"{{\"name\": \"google_scholar\", \"arguments\": {{\"query\": [\"keyword3\", \"keyword4\"]}}}}" if has_knowledge_base else "{{\"name\": \"pdf_crawler\", \"arguments\": {{\"url\": \"https://arxiv.org/pdf/1234.5678.pdf\"}}}}"}
</tool_call>

[Tool response will be provided]

Round 3:
<think>{"Based on knowledge base and academic sources, I have enough information..." if has_knowledge_base else "Have enough information now..."}</think>
{"Provide findings without <answer> tag" if not is_final_step else "<answer>Comprehensive analysis...</answer>"}

**Current date**: {datetime.now().strftime("%Y-%m-%d")}"""
            
            user_content = f"""Research Task: {step_info.get('title', '')}

Description: {step_info.get('description', '')}

**CRITICAL STEP BOUNDARY**:
- You are working on Step {current_step} of {total_steps}
- Focus ONLY on: {step_info.get('description', '')}
- Do NOT work on other steps' tasks
- Do NOT mix tasks from different steps

**Guidelines**:
- Research depth: {research_depth.upper()}
- {"Use <think> tags to show your reasoning" if not is_final_step else "Complete current task first, then review ALL previous steps in the conversation history and synthesize findings"}
- {"Focus on gathering information" if not is_final_step else "Provide comprehensive final answer with <answer> tag"}

**Research Strategy**:
{"- **PRIORITY 1**: Use `local_search_tool` (knowledge base) FIRST if available - it contains curated, high-quality information\n" if has_knowledge_base else ""}- Use `google_scholar` for academic literature and research papers
{"- Use `pdf_crawler` to extract detailed content from PDF documents (deep research mode only)\n" if research_depth == "deep" else ""}- Use `python_repl_tool` for data analysis and calculations

**Smart Tool Selection**:
{"- **If knowledge base is available**: Always start with `local_search_tool`, then use `google_scholar` if more information is needed\n" if has_knowledge_base else ""}- For simple concepts/definitions: {"`local_search_tool` (if available) or " if has_knowledge_base else ""}`google_scholar`
- For detailed academic research: {"`local_search_tool` (if available) + " if has_knowledge_base else ""}`google_scholar`{" + `pdf_crawler` for PDF extraction" if research_depth == "deep" else ""}
- For data analysis: `python_repl_tool`

**Information Sufficiency Judgment**:
- **Simple depth**: Basic information is sufficient - stop when you have core facts
- **Deep depth**: Comprehensive information required - continue until you have detailed analysis, multiple sources, and thorough coverage

**REMEMBER**: Stay focused on the current step task only!"""
            
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        else:
            # 后续轮次：返回完整消息历史
            return messages
    
    def _generate_tools_str(self, tools: List[BaseTool]) -> str:
        """生成工具定义字符串"""
        tools_json = []
        for tool in tools:
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                }
            }
            if hasattr(tool, 'args_schema') and tool.args_schema:
                tool_schema["function"]["parameters"] = tool.args_schema.schema()
            tools_json.append(json.dumps(tool_schema))
        
        return "\n".join(tools_json)
    
    def _format_completed_steps_summary(self, completed_steps: List[Any]) -> str:
        """格式化已完成步骤摘要"""
        if not completed_steps:
            return ""
        
        summary_lines = ["**Previous Steps Summary**:", ""]
        for i, step in enumerate(completed_steps, 1):
            title = getattr(step, 'title', f'Step {i}')
            summary_lines.append(f"Step {i}: {title} ✓ Completed")
        
        summary_lines.append("")
        summary_lines.append("**Current Step**: You can see all previous findings in the conversation history above.")
        
        return "\n".join(summary_lines)


class IterativeResearchEngine:
    """
    实现DeepResearch的迭代研究引擎
    - 支持步骤级别的研究深度控制
    - 输出think和tool_call标签供前端展示
    - 最后一步综合所有结果
    """
    
    def __init__(
        self,
        max_iterations: int,
        llm,
        tools: List[BaseTool],
        config: Configuration
    ):
        self.max_iterations = max_iterations
        self.llm = llm
        self.tools = tools
        self.config = config
        self.workspace_manager = WorkspaceManager(tools=tools)
        self.tool_map = {tool.name: tool for tool in tools}
        
    async def iterate_research(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any]
    ) -> DeepResearchResult:
        """迭代研究 - 支持步骤上下文和answer判断"""
        
        # 获取步骤上下文
        current_plan = context.get('current_plan')
        if current_plan:
            total_steps = len(current_plan.steps)
            completed_steps = [s for s in current_plan.steps if s.execution_res]
            completed_count = len(completed_steps)
            current_step_index = completed_count + 1
            is_final_step = (current_step_index == total_steps)
            
            # 获取当前步骤对象和研究深度
            current_step_obj = next((s for s in current_plan.steps if not s.execution_res), None)
            research_depth = getattr(current_step_obj, 'research_depth', 'simple') if current_step_obj else 'simple'
            
            step_context = {
                'current_step': current_step_index,
                'total_steps': total_steps,
                'is_final_step': is_final_step,
                'research_depth': research_depth,
                'completed_steps': completed_steps  # 传递完整的已完成步骤
            }
        else:
            step_context = {
                'current_step': 1,
                'total_steps': 1,
                'is_final_step': True,
                'research_depth': 'deep',
                'completed_steps': []
            }
        
        messages = []
        tools_used = set()
        
        logger.info(f"Starting research: Step {step_context['current_step']}/{step_context['total_steps']}, Depth: {step_context['research_depth']}, Is Final: {step_context['is_final_step']}")
        logger.info(f"Completed steps count: {len(step_context['completed_steps'])}")
        
        try:
            for iteration in range(1, self.max_iterations + 1):
                logger.info(f"Iteration {iteration}/{self.max_iterations}")
                
                # 第一次迭代：构建工作空间
                if iteration == 1:
                    messages = self.workspace_manager.build_workspace(
                        messages=messages,
                        step_info=step,
                        iteration=iteration,
                        step_context=step_context
                    )
                
                # 调用LLM
                response = await self._get_llm_response(messages)
                logger.info(f"LLM Response: {response[:200]}...")
                
                # 添加assistant消息
                messages.append({"role": "assistant", "content": response})
                
                # 解析响应
                parsed = self._parse_response(response)
                
                # 执行工具调用
                if parsed["tool_calls"]:
                    tool_response = await self._execute_tool_calls(
                        parsed["tool_calls"],
                        iteration
                    )
                    if tool_response:
                        messages.append({"role": "user", "content": tool_response})
                        
                        # 记录工具使用
                        for tc_str in parsed["tool_calls"]:
                            try:
                                tc = json.loads(repair_json_output(tc_str))
                                tools_used.add(tc.get('name', 'unknown'))
                            except:
                                pass
                
                # 检查answer标签
                if parsed["answer"]:
                    if not step_context['is_final_step']:
                        # 非最后步骤：忽略<answer>，作为普通结果返回
                        logger.warning(f"Ignoring <answer> tag in step {step_context['current_step']}/{step_context['total_steps']}")
                        return DeepResearchResult(
                            final_report=parsed["answer"],
                            iteration_count=iteration,
                            tools_used=list(tools_used),
                            iterations=[],
                            success=True
                        )
                    else:
                        # 最后步骤：接受<answer>
                        logger.info(f"Final answer received in step {step_context['current_step']}/{step_context['total_steps']}")
                        return DeepResearchResult(
                            final_report=parsed["answer"],
                            iteration_count=iteration,
                            tools_used=list(tools_used),
                            iterations=[],
                            success=True
                        )
            
            # 达到最大迭代次数，返回收集到的信息
            last_assistant_message = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), "No findings")
            logger.warning(f"Max iterations reached in step {step_context['current_step']}/{step_context['total_steps']}")
            
            # 如果没有有效的回答，尝试从工具响应中提取信息
            if not last_assistant_message or last_assistant_message.strip() == "":
                # 从工具响应中提取信息
                tool_responses = [m["content"] for m in messages if m["role"] == "user" and "<tool_response>" in m["content"]]
                if tool_responses:
                    last_assistant_message = f"Research findings from tools:\n\n" + "\n\n".join(tool_responses[-2:])  # 取最后2个工具响应
                else:
                    last_assistant_message = f"Step {step_context['current_step']} research completed with {len(tools_used)} tools used."
            
            return DeepResearchResult(
                final_report=last_assistant_message,
                iteration_count=self.max_iterations,
                tools_used=list(tools_used),
                iterations=[],
                success=True
            )
            
        except Exception as e:
            logger.error(f"Error in research: {str(e)}")
            return DeepResearchResult(
                final_report="",
                iteration_count=0,
                tools_used=[],
                iterations=[],
                success=False,
                error_message=str(e)
            )
    
    async def _get_llm_response(self, workspace: List[Dict[str, str]]) -> str:
        """获取LLM响应 - 添加停止词"""
        try:
            messages = []
            for msg in workspace:
                if msg["role"] == "system":
                    messages.append(SystemMessage(content=msg["content"]))
                elif msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
            
            # 添加停止词防止LLM生成tool_response
            response = await self.llm.ainvoke(
                messages,
                stop=["\n<tool_response>", "<tool_response>"]
            )
            return response.content
            
        except Exception as e:
            logger.error(f"Error getting LLM response: {str(e)}")
            raise
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应 - 对齐DeepResearch"""
        parsed = {
            "raw_content": response,
            "tool_calls": [],
            "answer": None
        }
        
        # 提取tool_call
        if '<tool_call>' in response and '</tool_call>' in response:
            tool_call_str = response.split('<tool_call>')[1].split('</tool_call>')[0]
            parsed["tool_calls"].append(tool_call_str)
        
        # 提取answer
        if '<answer>' in response and '</answer>' in response:
            parsed["answer"] = response.split('<answer>')[1].split('</answer>')[0]
        
        return parsed
    
    async def _execute_tool_calls(
        self,
        tool_calls: List[str],
        iteration: int
    ) -> str:
        """执行工具调用 - 对齐DeepResearch"""
        
        if not tool_calls:
            return None
        
        logger.info(f"Available tools: {list(self.tool_map.keys())}")
        
        results = []
        for tool_call_str in tool_calls:
            try:
                # 特殊处理Python工具（支持 python_interpreter 和 python_repl_tool）
                if "PythonInterpreter" in tool_call_str or "python_interpreter" in tool_call_str or "python_repl_tool" in tool_call_str:
                    # 提取code标签内的代码
                    if '<code>' in tool_call_str and '</code>' in tool_call_str:
                        code = tool_call_str.split('<code>')[1].split('</code>')[0].strip()
                        # 尝试匹配工具名称（python_repl_tool 或 python_interpreter）
                        tool_name = "python_repl_tool" if "python_repl_tool" in tool_call_str else "python_interpreter"
                        tool_args = {"code": code}
                    else:
                        # 如果没有 code 标签，尝试从 JSON 中解析
                        try:
                            tool_call = json.loads(repair_json_output(tool_call_str))
                            tool_name = tool_call.get('name')
                            if tool_name in ['python_interpreter', 'python_repl_tool']:
                                tool_args = tool_call.get('arguments', {})
                            else:
                                results.append("[Python Tool Error]: Invalid tool name or format.")
                                continue
                        except:
                            results.append("[Python Tool Error]: Formatting error.")
                            continue
                else:
                    # 解析JSON工具调用（支持所有其他工具：local_search_tool, google_scholar, pdf_crawler）
                    tool_call = json.loads(repair_json_output(tool_call_str))
                    tool_name = tool_call.get('name')
                    tool_args = tool_call.get('arguments', {})
                
                logger.info(f"Calling tool: {tool_name} with args: {tool_args}")
                
                # 工具名称映射（处理可能的名称差异）
                tool_name_mapping = {
                    'python_interpreter': 'python_repl_tool',  # 向后兼容
                    'fetch_pdf_text': 'pdf_crawler',  # 函数名到工具名的映射
                }
                actual_tool_name = tool_name_mapping.get(tool_name, tool_name)
                
                if actual_tool_name in self.tool_map:
                    tool = self.tool_map[actual_tool_name]
                    result = await tool.ainvoke(tool_args)
                    results.append(str(result))
                    logger.info(f"Tool {actual_tool_name} executed successfully")
                else:
                    error_msg = f"Tool {tool_name} (mapped to {actual_tool_name}) not found. Available: {list(self.tool_map.keys())}"
                    results.append(error_msg)
                    logger.error(error_msg)
                    
            except Exception as e:
                error_msg = f"Error executing tool call: {str(e)}"
                results.append(error_msg)
                logger.error(error_msg)
        
        # 格式化为tool_response
        combined_result = "\n\n".join(results)
        return f"<tool_response>\n{combined_result}\n</tool_response>"