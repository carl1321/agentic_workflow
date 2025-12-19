# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Molecule Visualization Tool for LangChain"""

import base64
import io
import logging
import re
import json
import uuid
import os
from langchain.tools import tool

try:
    from rdkit import Chem
    from rdkit.Chem import Draw
    from rdkit.Chem.Draw import MolsToGridImage
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False
    MolsToGridImage = None

logger = logging.getLogger(__name__)


@tool
def visualize_molecules(smiles_text: str) -> str:
    """将SMILES字符串列表可视化为分子结构图
    
    IMPORTANT: This tool extracts SMILES from text and ignores any base64 images.
    Use this in Step 2 after generate_sam_molecules outputs text results in Step 1.
    
    从输入文本中提取所有SMILES字符串，并为每个分子生成2D结构图（base64编码的网格图）。
    
    Args:
        smiles_text: 包含SMILES字符串的文本（可以包含base64图片，会自动忽略）。
                    Smart extraction supports multiple formats:
                    - "1. SMILES: CCO
                       2. SMILES: CCCO"
                    - Pure SMILES list (one per line)
                    - Text with embedded base64 images (will be ignored)
    
    Returns:
        包含分子结构网格图的Markdown文本，图片以base64格式嵌入（SVG或PNG）
    
    Examples:
        >>> visualize_molecules("1. SMILES: CCO\\n2. SMILES: CCCO")
        >>> visualize_molecules("CCO\\nCCCO\\nCCCCO")
    """
    if not RDKIT_AVAILABLE:
        return "错误：RDKit未安装。请运行 `pip install rdkit-pypi` 安装依赖。"
    
    try:
        # First, remove base64 image data from text to avoid interference
        # Remove lines that look like base64 data (very long lines, or data:image patterns)
        cleaned_text = re.sub(r'!\[.*?\]\(data:image[^\n]+\)', '', smiles_text)  # Remove markdown image tags
        cleaned_text = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+', '', cleaned_text, flags=re.MULTILINE)  # Remove base64 data
        
        # Extract SMILES from cleaned text using regex patterns
        smiles_list = []
        
        # Pattern 1: "SMILES: xxx" or "smiles: xxx"  (most common format)
        pattern1 = re.compile(r'SMILES:\s*`?([^\s\n`]+)`?', re.IGNORECASE)
        matches1 = pattern1.findall(cleaned_text)
        smiles_list.extend(matches1)
        
        # Pattern 2: Numbered list with SMILES (e.g., "1. SMILES: xxx" or "1. xxx")
        pattern2 = re.compile(r'\d+\.\s*(?:SMILES:\s*)?`?([A-Za-z0-9@+\-\[\]\(\)=#@\:\/\\\\]+)`?', re.IGNORECASE)
        matches2 = pattern2.findall(cleaned_text)
        smiles_list.extend(matches2)
        
        # Pattern 3: Pure SMILES lines (if no matches found above)
        if not smiles_list:
            lines = cleaned_text.strip().split('\n')
            for line in lines:
                line = line.strip()
                # Skip empty lines and lines that look like headers/metadata
                if line and not any(keyword in line.lower() for keyword in ['骨架', '锚定', 'scaffold', 'anchor', '条件', 'condition', '成功生成', '生成', 'molecular']):
                    # Try to extract potential SMILES (alphanumeric with special chars)
                    potential_smiles = re.findall(r'([A-Za-z0-9@+\-\[\]\(\)=#:\/\\\\]+)', line)
                    for smiles in potential_smiles:
                        if len(smiles) > 3 and '=' in smiles or '(' in smiles:  # Likely a SMILES
                            smiles_list.append(smiles)
        
        if not smiles_list:
            return "错误：未能从文本中提取到有效的SMILES字符串。\n\n请确保输入包含SMILES字符串。"
        
        # Remove duplicates while preserving order
        seen = set()
        unique_smiles = []
        for smiles in smiles_list:
            if smiles not in seen and len(smiles) > 2:  # Filter out very short strings
                seen.add(smiles)
                unique_smiles.append(smiles)
        
        if not unique_smiles:
            return "错误：提取到的SMILES字符串无效。"
        
        logger.info(f"Extracted {len(unique_smiles)} unique SMILES for visualization")
        
        # Generate molecules from SMILES
        mols = []
        for smiles in unique_smiles:
            try:
                mol = Chem.MolFromSmiles(smiles)
                if mol is not None:
                    mols.append(mol)
                else:
                    logger.warning(f"Invalid SMILES: {smiles}")
            except Exception as e:
                logger.error(f"Error parsing SMILES '{smiles}': {e}")
        
        if not mols:
            return "错误：未能从SMILES字符串生成有效的分子对象。请检查SMILES格式。"
        
        # Generate grid image using MolsToGridImage (like perovskite_agents)
        try:
            # Default: 5 molecules per row
            molsPerRow = 5
            
            # Generate SVG grid image (faster, smaller, better quality)
            grid_img = MolsToGridImage(mols, molsPerRow=molsPerRow, useSVG=True)
            
            # Convert SVG to base64
            # SVG is already a string from MolsToGridImage when useSVG=True
            img_str = str(grid_img)
            img_base64 = base64.b64encode(img_str.encode('utf-8')).decode('utf-8')
            
            # Build structured result (summary + image metadata)
            summary = f"已生成 {len(mols)} 个分子的 2D 结构图（Grid 格式）。分子 SMILES:\n\n"
            for i, smiles in enumerate(unique_smiles[:len(mols)], 1):
                summary += f"{i}. SMILES: `{smiles}`\n"
            
            logger.info(f"Successfully generated grid image for {len(mols)} molecules")
            
            # Store image in web/public directory
            image_id = str(uuid.uuid4())
            
            # Use web/public directory for static file access
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            public_dir = os.path.join(project_root, "web", "public", "molecular_images")
            os.makedirs(public_dir, exist_ok=True)
            
            # Decode base64 and save as .svg file
            svg_content = base64.b64decode(img_base64)
            svg_file = os.path.join(public_dir, f"{image_id}.svg")
            with open(svg_file, 'wb') as f:
                f.write(svg_content)
            
            logger.info(f"=== VISUALIZE_MOLECULES RETURN ===")
            logger.info(f"Summary length: {len(summary)}")
            logger.info(f"Saved SVG to {svg_file}")
            logger.info(f"Image URL: /molecular_images/{image_id}.svg")
            logger.info(f"=== END VISUALIZE_MOLECULES RETURN ===")
            
            # Return summary with hidden image ID marker
            return f"{summary}\n<!-- MOLECULAR_IMAGE_ID:{image_id} -->"
            
        except Exception as e:
            logger.error(f"Error generating grid image: {e}")
            return f"错误：无法生成分子网格图：{str(e)}"
        
    except Exception as e:
        logger.error(f"Error in visualize_molecules: {e}")
        return f"可视化分子时出错：{str(e)}"

