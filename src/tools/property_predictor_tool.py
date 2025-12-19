# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Molecular Property Predictor Tool for LangChain"""

import logging
import re
from langchain.tools import tool

from src.tools.property_predictor.prop_predictor import Predictor

logger = logging.getLogger(__name__)

# Initialize predictor
_predictor = None

def get_predictor():
    """Lazy initialization of predictor."""
    global _predictor
    if _predictor is None:
        _predictor = Predictor()
    return _predictor


@tool
def predict_molecular_properties(smiles_text: str, properties: str = "HOMO,LUMO,DM") -> str:
    """预测分子性质
    
    从文本中提取 SMILES 字符串，并预测其分子性质（HOMO、LUMO、偶极矩等）。
    
    Args:
        smiles_text: 包含 SMILES 字符串的文本
        properties: 要预测的性质，用逗号分隔。可选值: "HOMO", "LUMO", "DM"
    
    Returns:
        包含分子 SMILES 和预测性质的格式化文本
    """
    try:
        from rdkit import Chem
        
        # Extract SMILES from text (supports numbered lists or plain lists)
        smiles_pattern = re.compile(r'\d+\.\s*SMILES:\s*`?([^`\n]+)`?', re.IGNORECASE)
        matches = smiles_pattern.findall(smiles_text)
        
        if not matches:
            # Try simpler pattern without numbering
            smiles_pattern = re.compile(r'`([^`]+)`')
            matches = smiles_pattern.findall(smiles_text)
        
        if not matches:
            # Try to extract from lines
            lines = smiles_text.split('\n')
            for line in lines:
                line = line.strip()
                if '=' in line and Chem.MolFromSmiles(line):
                    matches.append(line)
        
        if not matches:
            # Try to split by comma and validate each part as SMILES
            # This handles cases where LLM passes comma-separated SMILES strings
            potential_smiles = [s.strip() for s in smiles_text.split(',')]
            for potential in potential_smiles:
                # Remove any leading/trailing quotes or backticks
                cleaned = potential.strip().strip('`').strip('"').strip("'")
                # Validate if it's a valid SMILES
                if cleaned and Chem.MolFromSmiles(cleaned):
                    matches.append(cleaned)
        
        if not matches:
            return "错误：未能从输入中提取有效的 SMILES 字符串。"
        
        smiles_list = [m.strip() for m in matches]
        logger.info(f"Extracted {len(smiles_list)} SMILES for property prediction: {smiles_list}")
        
        # Parse properties to predict
        prop_list = [p.strip().upper() for p in properties.split(',')]
        HOMO = 'HOMO' in prop_list
        LUMO = 'LUMO' in prop_list
        DM = 'DM' in prop_list
        
        if not (HOMO or LUMO or DM):
            return "错误：未指定要预测的性质。请提供 HOMO、LUMO 或 DM 中的一个或多个。"
        
        # Predict properties
        predictor = get_predictor()
        results = predictor.prop_pred(smiles_list, generated=False, HOMO=HOMO, LUMO=LUMO, DM=DM)
        
        # Format results
        output = "分子性质预测结果：\n\n"
        for i, smiles in enumerate(smiles_list):
            output += f"分子 {i+1}: {smiles}\n"
            
            if 'HOMO' in results:
                homo_vals = results['HOMO']
                if isinstance(homo_vals, dict) and 'raw_data' in homo_vals:
                    homo_pred = homo_vals['raw_data'].get('predict_HOMO', homo_vals['raw_data'].get('HOMO'))
                    output += f"  HOMO: {homo_pred}\n"
                elif hasattr(homo_vals, '__getitem__'):
                    output += f"  HOMO: {homo_vals[i] if i < len(homo_vals) else 'N/A'}\n"
                
            if 'LUMO' in results:
                lumo_vals = results['LUMO']
                if isinstance(lumo_vals, dict) and 'raw_data' in lumo_vals:
                    lumo_pred = lumo_vals['raw_data'].get('predict_LUMO', lumo_vals['raw_data'].get('LUMO'))
                    output += f"  LUMO: {lumo_pred}\n"
                elif hasattr(lumo_vals, '__getitem__'):
                    output += f"  LUMO: {lumo_vals[i] if i < len(lumo_vals) else 'N/A'}\n"
                
            if 'DM' in results:
                dm_vals = results['DM']
                if isinstance(dm_vals, dict) and 'raw_data' in dm_vals:
                    dm_pred = dm_vals['raw_data'].get('predict_DM', dm_vals['raw_data'].get('DM'))
                    output += f"  偶极矩 (DM): {dm_pred}\n"
                elif hasattr(dm_vals, '__getitem__'):
                    output += f"  偶极矩 (DM): {dm_vals[i] if i < len(dm_vals) else 'N/A'}\n"
            
            output += "\n"
        
        logger.info(f"Property prediction completed for {len(smiles_list)} molecules")
        return output
        
    except Exception as e:
        logger.error(f"Error predicting molecular properties: {e}")
        return f"预测分子性质时出错：{str(e)}"

