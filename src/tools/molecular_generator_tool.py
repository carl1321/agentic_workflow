# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""SAM Molecule Generator Tool for LangChain"""

import logging
from langchain.tools import tool

logger = logging.getLogger(__name__)


@tool
def generate_sam_molecules(
    scaffold_condition: str,
    anchoring_group: str,
    gen_size: int = 10,
) -> str:
    """生成自组装单分子层（SAM）分子
    
    This tool ONLY generates SMILES strings. Do NOT visualize molecules in this step.
    Use the visualize_molecules tool separately in a later step to generate structure images.
    
    Args:
        scaffold_condition: 骨架SMILES，多个骨架用逗号分隔，例如 "c1ccccc1,c1ccc2c(c1)[nH]c1ccccc12"
        anchoring_group: 锚定基团SMILES，例如 "O=P(O)(O)" 表示磷酸基团
        gen_size: 要生成的分子数量，默认10个
    
    Returns:
        生成的分子列表，包含SMILES和骨架信息（纯文本格式，不包含图片）
    """
    try:
        from src.tools.molecular_generator.sam_generator import SAMGenerator
    except ImportError as e:
        logger.error(f"Failed to import SAMGenerator: {e}")
        return f"错误：无法导入SAMGenerator。请确保依赖已正确安装。\n错误详情：{str(e)}"
    
    try:
        # Parse scaffold conditions
        scaffolds = [s.strip() for s in scaffold_condition.split(',')]
        
        logger.info(f"Generating SAM molecules with {len(scaffolds)} scaffolds, anchoring group: {anchoring_group}, count: {gen_size}")
        
        # Initialize and run generator
        generator = SAMGenerator(scaffolds, anchoring_group, gen_size)
        molecules = generator.generate_with_scaffold()
        
        if not molecules:
            return "未能生成有效的SAM分子。请检查骨架条件和锚定基团是否有效。"
        
        # Format results - only return SMILES and scaffold info
        result = f"成功生成 {len(molecules)} 个SAM分子：\n\n"
        for i, mol in enumerate(molecules, 1):
            result += f"{i}. SMILES: {mol['smiles']}\n"
            result += f"   骨架条件: {mol['scaffold_condition']}\n"
            result += f"   实际骨架: {mol['scaffold_smiles']}\n\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error generating SAM molecules: {e}")
        return f"生成SAM分子时出错：{str(e)}"

