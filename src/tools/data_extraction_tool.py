# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import base64
import io
import json
import logging
from typing import Annotated, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from src.llms.llm import get_llm_by_model_name, get_llm_by_type

from .decorators import log_io

logger = logging.getLogger(__name__)


def _extract_pdf_text_from_bytes(content: bytes) -> str:
    """Extract text from PDF bytes. Tries multiple parsers."""
    # Try pdfminer.six first
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract

        with io.BytesIO(content) as fp:
            text = pdfminer_extract(fp) or ""
            if text.strip():
                return text
    except Exception:
        pass
    
    # Try PyPDF2 as fallback
    try:
        import PyPDF2

        with io.BytesIO(content) as fp:
            reader = PyPDF2.PdfReader(fp)
            out = []
            for page in reader.pages:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    continue
        text = "\n".join(out).strip()
        if text:
            return text
    except Exception:
        pass
    
    # Return empty string if all parsers fail
    return ""


def _extract_xml_text_from_bytes(content: bytes) -> str:
    """Extract text from XML bytes."""
    try:
        import xml.etree.ElementTree as ET
        
        # Try to decode and parse as XML
        root = None
        # Try UTF-8 first (most common)
        for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1', 'iso-8859-1']:
            try:
                content_str = content.decode(encoding)
                root = ET.fromstring(content_str)
                break
            except (UnicodeDecodeError, ET.ParseError) as e:
                continue
        
        if root is None:
            # Last resort: try with error handling
            try:
                content_str = content.decode('utf-8', errors='ignore')
                root = ET.fromstring(content_str)
            except ET.ParseError:
                raise ValueError("Failed to parse XML with any encoding")
        
        # Extract all text content from XML elements
        def extract_text(element):
            text_parts = []
            # Add element text
            if element.text and element.text.strip():
                text_parts.append(element.text.strip())
            # Add tail text
            if element.tail and element.tail.strip():
                text_parts.append(element.tail.strip())
            # Recursively process children
            for child in element:
                text_parts.extend(extract_text(child))
            return text_parts
        
        text_parts = extract_text(root)
        text = "\n".join(text_parts).strip()
        
        if text:
            return text
    except Exception as e:
        logger.warning(f"Failed to extract text from XML using ElementTree: {e}")
        # Fallback: try to extract text using regex or simple string operations
        try:
            # Try to decode and extract text between tags
            content_str = content.decode('utf-8', errors='ignore')
            import re
            # Remove XML tags and extract text
            text = re.sub(r'<[^>]+>', ' ', content_str)
            text = ' '.join(text.split())  # Normalize whitespace
            if text.strip():
                return text.strip()
        except Exception as e2:
            logger.warning(f"Failed to extract text using regex fallback: {e2}")
    
    return ""


def _extract_text_from_file_bytes(content: bytes, file_name: str = "") -> str:
    """Extract text from file bytes. Automatically detects file type."""
    file_name_lower = file_name.lower() if file_name else ""
    
    # Check file extension or content to determine file type
    if file_name_lower.endswith('.xml') or content.startswith(b'<?xml') or content.startswith(b'<'):
        # Try XML extraction
        text = _extract_xml_text_from_bytes(content)
        if text:
            return text
        # If XML extraction fails, fall back to PDF
        logger.warning("XML extraction failed, trying PDF parser as fallback...")
    
    # Default to PDF extraction
    return _extract_pdf_text_from_bytes(content)


def _optimize_prompt_with_llm(prompt: str, model_name: Optional[str] = None) -> str:
    """Optimize the extraction prompt using LLM."""
    try:
        if model_name and model_name.strip():
            try:
                llm = get_llm_by_model_name(model_name.strip())
            except ValueError:
                llm = get_llm_by_type("basic")
        else:
            llm = get_llm_by_type("basic")

        optimization_prompt = """你是一个提示词优化专家。请优化以下数据抽取提示词，使其更加清晰、具体和有效。
要求：
1. 保持原意不变
2. 明确指定需要抽取的数据字段
3. 强调输出格式要求
4. 添加示例说明（如需要）

原提示词：
{prompt}

请直接返回优化后的提示词，不要添加其他说明。"""

        messages = [
            SystemMessage(content="你是一个专业的提示词优化助手。"),
            HumanMessage(content=optimization_prompt.format(prompt=prompt)),
        ]

        response = llm.invoke(messages)
        optimized = response.content if hasattr(response, "content") else str(response)
        logger.info(f"Prompt optimized, original length: {len(prompt)}, optimized length: {len(optimized)}")
        return optimized.strip()
    except Exception as e:
        logger.warning(f"Failed to optimize prompt: {e}, using original prompt")
        return prompt


def _extract_material_categories(
    pdf_text: str,
    model_name: Optional[str] = None,
) -> dict:
    """Extract material, process, and property categories from PDF text."""
    try:
        # Get LLM instance
        if model_name and model_name.strip():
            try:
                llm = get_llm_by_model_name(model_name.strip())
                logger.info(f"Using model: {model_name} for category extraction")
            except ValueError as e:
                error_msg = f"Model '{model_name}' not found. Error: {str(e)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        else:
            llm = get_llm_by_type("basic")
            logger.info("Using default basic model for category extraction")

        system_prompt = """你是一个专业的材料科学文献主题分析专家。你的任务是对文献进行主题分析，识别文献中涉及的材料、工艺和性能类别。
        请你根据给定的文献文本，按以下要求完成**精细化分析与归纳**，并最终以指定的 JSON 格式输出：

1. **通读文献**
   准确理解文献的研究主题、主要研究对象以及核心内容。

2. **识别并确定“核心材料”（笔墨最多的材料，细化到具体材料）**

   2.1 **识别材料**

   * 从文献中**逐一识别所有具体材料 / 化学物质的名称**，而不是只写“聚合物、金属、陶瓷”等笼统大类。

     * 例如：聚甲基丙烯酸甲酯（PMMA）、聚乙烯醇（PVA）、ITO 导电玻璃、TiO₂ 纳米粒子、CH₃NH₃PbI₃ 钙钛矿等。

   2.2 **判断“核心材料”（笔墨最多的材料）**

   * 在已识别的材料中，找出**文献笔墨最多、最核心的材料**，综合考虑：

     * 在文献中出现频次最高；
     * 在题目、摘要、引言或结论中被重点提及；
     * 是核心研究对象、关键功能层或主要可调变量；
     * 与主要性能结果或机理分析强相关。
   * 只需要选出**若干个核心材料（建议3-10个）**，其余材料可以忽略，不必在输出中体现。 

   2.3 **核心材料的表示方式**

   * 在输出中，`materials` 数组中的每一项为一个字符串，建议采用“**具体材料名称 +（可选的大类说明）**”的形式，例如：

     * `"甲胺铅碘钙钛矿（CH₃NH₃PbI₃）【有机-无机杂化钙钛矿】"`
     * `"氧化铟锡（ITO）【金属氧化物导电基底】"`
     * `"二氧化钛（TiO₂）【无机氧化物电子传输层】"`

3. **工艺类别（仅限与“核心材料”直接相关的工艺）**

   * **只分析和列出用于这些核心材料的制备、处理或加工工艺**，忽略仅与非核心材料相关的工艺。
   * 对核心材料相关的工艺进行归纳，例如：

     * 薄膜制备：旋涂、滴涂、刮涂、真空蒸镀、溅射、化学气相沉积（CVD）、脉冲激光沉积（PLD）、溶胶-凝胶法等；
     * 后处理与表面修饰：退火处理、高温烧结、等离子体处理、化学浴沉积、表面功能化等。


4. **性能类别（仅限由“核心材料”主导或直接相关的性能）**

   * **只分析和列出与核心材料直接相关的性能指标和测试结果**，忽略与非核心材料弱相关或仅背景性提及的性能。
   * 对每个核心材料主导或显著影响的性能进行归纳，例如：

     * 光电性能：功率转换效率（PCE）、开路电压、短路电流、填充因子、光响应度等；
     * 稳定性：热稳定性、湿热稳定性、光照老化稳定性、循环稳定性等；
     * 电学性能：电导率、电阻率、载流子迁移率、电化学稳定窗口等；
     * 力学性能：拉伸强度、杨氏模量、断裂伸长率等；
     * 热性能：热导率、玻璃化转变温度、热分解温度等。
   * 在输出中，`properties` 数组中的每一项为一个字符串，表示**与核心材料直接相关的性能指标或性能类别名称**，例如：

     * `"光电转换效率（PCE）"`
     * `"器件在湿热条件下的稳定性"`
     * `"载流子迁移率"`
     * `"拉伸强度"`

5. **严格限制来源与去重要求**

   * `materials`、`processes`、`properties` 三个数组中的所有内容，都必须：

     * 来自文献文本本身，或者可由文献中**明确信息直接、合理归类**得到；
     * 不得凭空添加文献中未出现或无根据的材料、工艺或性能类别；
     * 不得重复列出同一材料 / 工艺 / 性能类别（需要将同义表述、缩写与全称视作同一项进行合并）；
     * 对工艺与性能，若与核心材料没有明确关联，则不予列出。

6. **以 JSON 格式输出**

   * 最终回答**只能输出一个合法的 JSON 对象**，不得包含任何多余的文字说明或注释。
   * JSON 结构必须严格符合以下格式（键名不能更改，数组元素均为字符串）：

```json
{
  "materials": ["类别1", "类别2", ...],
  "processes": ["类别1", "类别2", ...],
  "properties": ["类别1", "类别2", ...]
}
```

只输出有效的JSON格式，不要添加任何额外的说明或注释。"""

        user_prompt = f"""请从以下文献文本中提取材料、工艺和性能类别：

{pdf_text[:50000]}"""  # Limit text length

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        logger.info(f"[Category Extraction] Invoking LLM for category extraction, text length: {len(pdf_text)}")
        response = llm.invoke(messages)

        result_text = response.content if hasattr(response, "content") else str(response)
        # Compress log: only show length, not content (to avoid base64)
        logger.info(f"[Category Extraction] LLM response received, length: {len(result_text)}")

        # Clean up response text
        result_text = result_text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()

        # Parse JSON
        try:
            categories = json.loads(result_text)
            # Ensure all keys exist
            if "materials" not in categories:
                categories["materials"] = []
            if "processes" not in categories:
                categories["processes"] = []
            if "properties" not in categories:
                categories["properties"] = []
            logger.info(f"[Category Extraction] Successfully parsed categories: materials={len(categories.get('materials', []))}, processes={len(categories.get('processes', []))}, properties={len(categories.get('properties', []))}")
            return categories
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            # Only log first 200 chars to avoid base64 content
            logger.error(f"Response text (first 200 chars): {result_text[:200]}...")
            return {
                "error": "Failed to parse JSON from LLM response",
                "raw_response": result_text[:200] + "..." if len(result_text) > 200 else result_text,
                "parse_error": str(e),
                "materials": [],
                "processes": [],
                "properties": [],
            }

    except Exception as e:
        error_msg = f"Failed to extract categories: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "materials": [],
            "processes": [],
            "properties": [],
        }


def _extract_material_data(
    pdf_text: str,
    selected_materials: list,
    selected_processes: list,
    selected_properties: list,
    model_name: Optional[str] = None,
) -> list:
    """Extract material-process-property triplets from PDF text based on selected categories."""
    try:
        # Get LLM instance
        if model_name and model_name.strip():
            try:
                llm = get_llm_by_model_name(model_name.strip())
                logger.info(f"Using model: {model_name} for material data extraction")
            except ValueError as e:
                error_msg = f"Model '{model_name}' not found. Error: {str(e)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        else:
            llm = get_llm_by_type("basic")
            logger.info("Using default basic model for material data extraction")

        system_prompt = """你是一个专业的材料科学数据抽取专家。你的任务是从文献文本中，严格按照用户提供的"材料/工艺/性能"类别，精确提取材料-工艺-性能三元组数据。

**核心要求：每个三元组必须是一个完整的"材料-工艺-性能"对应关系，表示"某个材料在某个工艺条件下具有某个性能"。**

要求：
1. **三元组的对应关系**：
   - 每个三元组必须表示一个完整的对应关系：材料(material) + 工艺(process) → 性能(property)
   - 即：某个具体的材料，通过某个具体的工艺处理，得到或表现出某个具体的性能
   - 三个字段必须同时存在且相互关联，不能缺少任何一个字段
   - material 必须属于用户选择的材料范围（或与其在语义上等价/更具体的材料名称）
   - process 必须属于用户选择的工艺范围（或与其在语义上等价/更具体的工艺名称）
   - property 必须属于用户选择的性能范围（或与其在语义上等价/更具体的性能名称）
   - 与用户选择类别无关的三元组，一律不要提取

2. **字段要求**：
   - **material**：具体的材料名称，必须直接从文献中提取，不能使用"金属、陶瓷、聚合物"等笼统类别名称
     * 如果性能是针对某一特定配比、掺杂或结构（如：CH₃NH₃PbI₃: x% Cu 掺杂），material 中应保留这一具体形式
   - **process**：具体的工艺名称，必须直接从文献中提取，不能只写"热处理、溶液加工"等过于抽象的类别名称，尽可能保留具体方法或条件（如"旋涂"，"100 ℃ 退火 10 min"，"溶胶-凝胶法制备 TiO₂ 薄膜"等）
   - **property**：具体的性能名称及其对应数值（如文中给出），建议采用"性能名称 + 数值 + 单位"的形式，例如：
     * "光电转换效率 18.5 %"
     * "拉伸强度 120 MPa"
     * 如果只有性能名称没有数值，则仅保留性能名称

3. **数据提取原则**：
   - 只提取文献中**明确提到**且**与所选类别直接相关**的三元组数据
   - 每个三元组都必须能在文献中找到明确的依据（至少可以对应到同一段或同一逻辑片段）
   - 不要根据常识或经验进行推断，不要补全文献中没有给出的材料、工艺或性能信息
   - 如果无法确定某种材料与某个性能是否在特定工艺条件下直接对应，不要强行构造三元组

4. **性能数值的处理**：
   - 如果文献中提到了性能的数值，请在 property 字段中同时包含性能名称、数值和单位
   - 如果只给出了数值但没给单位，就保持与原文一致，不要臆造单位
   - 如果同一"材料-工艺"组合在不同条件下有多个性能值（例如不同温度或不同循环次数），应输出多个三元组，而不是混在一个 property 字段中

5. **去重与一致性**：
   - 同一"material-process-property"完全相同的三元组只保留一条，不要重复输出
   - 不要把属于不同材料、不同工艺或不同测试条件的数据混合在同一个三元组中

6. **输出格式（严格遵循）**：
   - 以 JSON 数组格式输出，每个元素是一个三元组对象
   - 每个三元组必须包含三个字段：material、process、property
   - 格式示例：
```json
[
  {"material": "CH₃NH₃PbI₃钙钛矿", "process": "旋涂法", "property": "光电转换效率 18.5 %"},
  {"material": "TiO₂纳米粒子", "process": "溶胶-凝胶法", "property": "载流子迁移率 0.5 cm²/(V·s)"},
  {"material": "PMMA薄膜", "process": "100 ℃ 退火 10 min", "property": "拉伸强度 120 MPa"}
]
```

7. **输出规范**：
   - 只输出**有效的 JSON 数组**，不要添加任何额外的文字说明、注释或代码块标记
   - JSON 中的键名必须为 "material"、"process"、"property"，不能更改
   - 字符串请使用双引号，确保整个输出是合法可解析的 JSON
   - 每个三元组必须是一个完整的对象，不能缺少任何字段

8. **缺失信息的处理**：
   - 如果某个字段无法从文献中确定，且文献没有给出任何可靠线索，则使用 null 值
   - 不要凭空编造材料名称、工艺名称或性能数值，宁可使用 null 也不要臆造
   - 但如果一个三元组中有两个或以上字段为 null，则该三元组不应被输出

9. **数据质量要求**：
   - 确保提取的数据尽可能准确、完整，不要遗漏文献中出现的、与用户选择类别相关的材料-工艺-性能三元组
   - 同时严格遵守"只来自文献文本本身"的原则，不要输出任何来源不明或推测性的数据
   - 确保每个三元组都代表一个真实的、文献中明确提到的材料-工艺-性能对应关系"""

        user_prompt = f"""请根据以下选择的类别，从文献文本中提取材料-工艺-性能三元组数据。

**重要提示**：每个三元组必须是一个完整的对应关系，表示"某个材料在某个工艺条件下具有某个性能"。三个字段（material、process、property）必须同时存在且相互关联。

选择的材料类别：{', '.join(selected_materials) if selected_materials else '无'}
选择的工艺类别：{', '.join(selected_processes) if selected_processes else '无'}
选择的性能类别：{', '.join(selected_properties) if selected_properties else '无'}

请从文献中找出所有满足以下条件的完整三元组：
- material 属于上述材料类别（或更具体的材料名称）
- process 属于上述工艺类别（或更具体的工艺名称）
- property 属于上述性能类别（或更具体的性能名称）
- 三个字段在文献中必须同时出现且相互关联

输出格式必须是 JSON 数组，每个元素包含 material、process、property 三个字段，例如：
[
  {{"material": "具体材料名称", "process": "具体工艺名称", "property": "性能名称及数值（如有）"}},
  ...
]

文献文本：
{pdf_text[:50000]}"""  # Limit text length

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        logger.info(f"[Data Extraction] Invoking LLM for material data extraction, text length: {len(pdf_text)}")
        response = llm.invoke(messages)

        result_text = response.content if hasattr(response, "content") else str(response)
        # Compress log: only show length, not content (to avoid base64)
        logger.info(f"[Data Extraction] LLM response received, length: {len(result_text)}")

        # Clean up response text
        result_text = result_text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()

        # Parse JSON
        try:
            table_data = json.loads(result_text)
            if not isinstance(table_data, list):
                logger.warning(f"LLM returned non-list data, converting to list. Type: {type(table_data)}")
                table_data = []
            
            logger.info(f"[Data Extraction] Successfully parsed {len(table_data)} data rows from LLM response")
            
            # Log compressed sample data for debugging (only first 3 rows, truncated property)
            if len(table_data) > 0:
                logger.info(f"[Data Extraction] Sample data (first 3 rows, property truncated):")
                for i, row in enumerate(table_data[:3], 1):
                    property_val = row.get('property', 'N/A')
                    property_preview = property_val[:50] + "..." if len(property_val) > 50 else property_val
                    logger.info(f"  Row {i}: material={row.get('material', 'N/A')[:30]}, "
                              f"process={row.get('process', 'N/A')[:30]}, "
                              f"property={property_preview}")
            else:
                logger.warning("[Data Extraction] No data extracted from LLM response")
            
            return table_data
        except json.JSONDecodeError as e:
            logger.error(f"[Data Extraction] Failed to parse JSON from response: {e}")
            # Only log first 200 chars to avoid base64 content
            logger.error(f"[Data Extraction] Response text (first 200 chars): {result_text[:200]}...")
            return []

    except Exception as e:
        error_msg = f"Failed to extract material data: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return []


def _extract_data_from_text(
    pdf_text: str,
    extraction_prompt: str,
    json_schema: str,
    model_name: Optional[str] = None,
) -> dict:
    """Extract structured data from PDF text using LLM."""
    try:
        # Get LLM instance
        if model_name and model_name.strip():
            try:
                llm = get_llm_by_model_name(model_name.strip())
                logger.info(f"Using model: {model_name} for data extraction")
            except ValueError as e:
                error_msg = f"Model '{model_name}' not found. Error: {str(e)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        else:
            llm = get_llm_by_type("basic")
            logger.info("Using default basic model for data extraction")

        # Build system message with extraction instructions
        system_prompt = f"""你是一个专业的数据抽取专家。你的任务是从给定的文本中提取结构化数据。

要求：
1. 仔细阅读用户提供的提示词，理解需要抽取的数据类型和字段
2. 严格按照以下JSON格式输出结果：
{json_schema}
3. 只输出有效的JSON格式，不要添加任何额外的说明或注释
4. 如果某些字段无法从文本中提取，使用null值
5. 确保JSON格式完全符合提供的schema

请严格按照要求执行数据抽取。"""

        # Build user message with PDF text and extraction prompt
        user_prompt = f"""数据抽取提示词：
{extraction_prompt}

待抽取的文本内容：
{pdf_text[:50000]}"""  # Limit text length to avoid token limits

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        logger.info(f"[Prompt Extraction] Invoking LLM for data extraction, text length: {len(pdf_text)}, prompt length: {len(extraction_prompt)}")
        response = llm.invoke(messages)

        # Extract content from response
        result_text = response.content if hasattr(response, "content") else str(response)
        # Compress log: only show length, not content (to avoid base64)
        logger.info(f"[Prompt Extraction] LLM response received, length: {len(result_text)}")

        # Try to parse JSON from response
        # Sometimes LLM adds markdown code blocks, try to extract JSON
        result_text = result_text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]  # Remove ```json
        if result_text.startswith("```"):
            result_text = result_text[3:]  # Remove ```
        if result_text.endswith("```"):
            result_text = result_text[:-3]  # Remove closing ```

        result_text = result_text.strip()

        # Parse JSON
        try:
            extracted_data = json.loads(result_text)
            logger.info(f"[Prompt Extraction] Successfully parsed JSON from LLM response, keys: {list(extracted_data.keys()) if isinstance(extracted_data, dict) else 'not a dict'}")
            return extracted_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            # Only log first 200 chars to avoid base64 content
            logger.error(f"Response text (first 200 chars): {result_text[:200]}...")
            # Return error in JSON format
            return {
                "error": "Failed to parse JSON from LLM response",
                "raw_response": result_text[:1000],  # Limit length
                "parse_error": str(e),
            }

    except Exception as e:
        error_msg = f"Failed to extract data: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}


@tool
@log_io
def data_extraction_tool(
    extraction_type: Annotated[
        Optional[str],
        "Extraction type: 'prompt_extraction' (default) or 'material_extraction'.",
    ] = "prompt_extraction",
    extraction_prompt: Annotated[
        Optional[str],
        "The prompt describing what data to extract from the PDF. Required for prompt_extraction type.",
    ] = None,
    json_schema: Annotated[
        Optional[str],
        "The expected JSON schema/format for the output. Required for prompt_extraction type.",
    ] = None,
    pdf_file_base64: Annotated[
        Optional[str],
        "Base64-encoded PDF or XML file content. Must be provided.",
    ] = None,
    model_name: Annotated[
        Optional[str],
        "Optional model name identifier. If not provided, uses the default basic model.",
    ] = None,
    optimize_prompt: Annotated[
        Optional[bool],
        "Whether to optimize the extraction prompt using LLM. Defaults to False. Only for prompt_extraction type.",
    ] = False,
    extraction_step: Annotated[
        Optional[int],
        "Extraction step for material_extraction: 1 (extract categories) or 2 (extract data). Defaults to 1.",
    ] = 1,
    selected_material_categories: Annotated[
        Optional[list],
        "Selected material categories for step 2 of material_extraction.",
    ] = None,
    selected_process_categories: Annotated[
        Optional[list],
        "Selected process categories for step 2 of material_extraction.",
    ] = None,
    selected_property_categories: Annotated[
        Optional[list],
        "Selected property categories for step 2 of material_extraction.",
    ] = None,
) -> str:
    """Extract structured data from a PDF file.
    
    Supports two extraction types:
    1. prompt_extraction (default): Extract data based on custom prompt and JSON schema
    2. material_extraction: Extract material-process-property triplets in two steps:
       - Step 1: Extract categories from PDF
       - Step 2: Extract data based on selected categories
    
    The result can be downloaded as a JSON file from the frontend.
    """
    try:
        # Normalize extraction type
        extraction_type = (extraction_type or "prompt_extraction").strip().lower()
        if extraction_type not in ["prompt_extraction", "material_extraction"]:
            extraction_type = "prompt_extraction"
        
        # Step 1: Extract text from PDF
        pdf_text = ""
        pdf_source = ""
        
        if pdf_file_base64:
            # Handle base64 encoded file (PDF or XML)
            try:
                # Decode base64
                file_bytes = base64.b64decode(pdf_file_base64)
                
                # Extract text from file bytes (auto-detect file type)
                pdf_text = _extract_text_from_file_bytes(file_bytes)
                pdf_source = "uploaded_file"
                
                if not pdf_text:
                    error_msg = "Failed to extract text from uploaded file. The file may be corrupted or not a valid PDF/XML file."
                    logger.error(error_msg)
                    return json.dumps({
                        "error": error_msg,
                        "source": "uploaded_file",
                    }, ensure_ascii=False, indent=2)
                    
            except Exception as e:
                error_msg = f"Failed to process uploaded file: {repr(e)}"
                logger.error(error_msg, exc_info=True)
                return json.dumps({
                    "error": error_msg,
                    "source": "uploaded_file",
                }, ensure_ascii=False, indent=2)
        else:
            error_msg = "pdf_file_base64 must be provided"
            logger.error(error_msg)
            return json.dumps({
                "error": error_msg,
            }, ensure_ascii=False, indent=2)

        # Branch based on extraction type
        if extraction_type == "material_extraction":
            # Material extraction mode
            extraction_step = extraction_step or 1
            
            if extraction_step == 1:
                # Step 1: Extract categories
                categories = _extract_material_categories(pdf_text, model_name)
                
                result = {
                    "step": 1,
                    "extraction_type": "material_extraction",
                    "categories": {
                        "materials": categories.get("materials", []),
                        "processes": categories.get("processes", []),
                        "properties": categories.get("properties", []),
                    },
                    "metadata": {
                        "pdf_source": pdf_source,
                        "pdf_text_length": len(pdf_text),
                        "model_used": model_name or "default",
                    },
                }
                
                if "error" in categories:
                    result["error"] = categories["error"]
                
                result_json = json.dumps(result, ensure_ascii=False, indent=2)
                return result_json
                
            elif extraction_step == 2:
                # Step 2: Extract data based on selected categories
                # Log received parameters to debug value changes
                logger.info(f"[Step 2] Received selected categories from frontend:")
                logger.info(f"  - selected_material_categories (type: {type(selected_material_categories)}, value: {selected_material_categories})")
                logger.info(f"  - selected_process_categories (type: {type(selected_process_categories)}, value: {selected_process_categories})")
                logger.info(f"  - selected_property_categories (type: {type(selected_property_categories)}, value: {selected_property_categories})")
                
                selected_materials = selected_material_categories or []
                selected_processes = selected_process_categories or []
                selected_properties = selected_property_categories or []
                
                logger.info(f"[Step 2] Processed selected categories:")
                logger.info(f"  - materials: {len(selected_materials)} items - {selected_materials}")
                logger.info(f"  - processes: {len(selected_processes)} items - {selected_processes}")
                logger.info(f"  - properties: {len(selected_properties)} items - {selected_properties}")
                
                # Material category is required (single selection)
                if not selected_materials or len(selected_materials) == 0:
                    error_msg = "必须至少选择一个材料类别（材料类别为单选）"
                    logger.error(error_msg)
                    return json.dumps({
                        "error": error_msg,
                        "step": 2,
                    }, ensure_ascii=False, indent=2)
                
                # At least one process or property should be selected
                if not selected_processes and not selected_properties:
                    error_msg = "必须至少选择一个工艺类别或性能类别"
                    logger.error(error_msg)
                    return json.dumps({
                        "error": error_msg,
                        "step": 2,
                    }, ensure_ascii=False, indent=2)
                
                table_data = _extract_material_data(
                    pdf_text=pdf_text,
                    selected_materials=selected_materials,
                    selected_processes=selected_processes,
                    selected_properties=selected_properties,
                    model_name=model_name,
                )
                
                result = {
                    "step": 2,
                    "extraction_type": "material_extraction",
                    "table_data": table_data,
                    "selected_categories": {
                        "materials": selected_materials,
                        "processes": selected_processes,
                        "properties": selected_properties,
                    },
                    "metadata": {
                        "pdf_source": pdf_source,
                        "pdf_text_length": len(pdf_text),
                        "model_used": model_name or "default",
                        "data_count": len(table_data),
                    },
                }
                
                result_json = json.dumps(result, ensure_ascii=False, indent=2)
                return result_json
            else:
                error_msg = f"Invalid extraction_step: {extraction_step}. Must be 1 or 2."
                logger.error(error_msg)
                return json.dumps({
                    "error": error_msg,
                }, ensure_ascii=False, indent=2)
        else:
            # Prompt extraction mode (default)
            if not extraction_prompt or not json_schema:
                error_msg = "extraction_prompt and json_schema are required for prompt_extraction type"
                logger.error(error_msg)
                return json.dumps({
                    "error": error_msg,
                }, ensure_ascii=False, indent=2)
            
            # Step 2: Optimize prompt if requested
            final_prompt = extraction_prompt
            if optimize_prompt:
                final_prompt = _optimize_prompt_with_llm(extraction_prompt, model_name)

            # Step 3: Extract structured data using LLM
            extracted_data = _extract_data_from_text(
                pdf_text=pdf_text,
                extraction_prompt=final_prompt,
                json_schema=json_schema,
                model_name=model_name,
            )

            # Step 4: Add metadata
            result = {
                "extraction_type": "prompt_extraction",
                "extracted_data": extracted_data,
                "metadata": {
                    "pdf_source": pdf_source,
                    "pdf_text_length": len(pdf_text),
                    "extraction_prompt": final_prompt,
                    "model_used": model_name or "default",
                    "prompt_optimized": optimize_prompt,
                },
            }

            # Return as formatted JSON string
            result_json = json.dumps(result, ensure_ascii=False, indent=2)
            return result_json

    except Exception as e:
        error_msg = f"Failed to extract data from PDF: {repr(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "pdf_source": pdf_source if 'pdf_source' in locals() else "unknown",
        }, ensure_ascii=False, indent=2)

