import os
import pandas as pd
from typing import List

# Get the directory of this file
_current_dir = os.path.dirname(os.path.abspath(__file__))

from src.tools.property_predictor.unimol_tools.predict import MolPredict

# convert input to csv 
def input_form(smiles_list):
    assert isinstance(smiles_list, list), "Input should be a list of SMILES strings."
    df = pd.DataFrame({"SMILES": smiles_list})
    output_file = "smiles_data.csv"
    return df.to_csv(output_file, index=False)
    

class Predictor:
    def __init__(self):
        # Use relative paths from src/tools/property_predictor
        self.HOMO_dir = os.path.join(_current_dir, 'homo_bs_32_lr_1e-4')
        self.LUMO_dir = os.path.join(_current_dir, 'lumo_bs_32_lr_1e-4')
        self.DM_dir = os.path.join(_current_dir, 'dm_bs_32_lr_1e-4')
        
    def HOMO_pred(self, smiles, generated):
        if generated:
            smiles_dir = "src/tools/molecular_generator/generated_data.csv"
        else:
            smiles = input_form(smiles)
            smiles_dir = "smiles_data.csv"
        HOMO_predictor = MolPredict(load_model=self.HOMO_dir)
        HOMO_pred = HOMO_predictor.predict(smiles_dir)
        return HOMO_pred
    
    def LUMO_pred(self, smiles, generated):
        if generated:
            smiles_dir = "src/tools/molecular_generator/generated_data.csv"
        else:
            smiles = input_form(smiles)
            smiles_dir = "smiles_data.csv"
        LUMO_predictor = MolPredict(load_model=self.LUMO_dir)
        LUMO_pred = LUMO_predictor.predict(smiles_dir)
        return LUMO_pred
    
    def DM_pred(self, smiles, generated):
        if generated:
            smiles_dir = "src/tools/molecular_generator/generated_data.csv"
        else:
            smiles = input_form(smiles)
            smiles_dir = "smiles_data.csv" 
        DM_predictor = MolPredict(load_model=self.DM_dir)
        DM_pred = DM_predictor.predict(smiles_dir)
        return DM_pred
    
    def prop_pred(self, smiles, generated, HOMO=False, LUMO=False, DM=False):
        results = {}
        if HOMO:
            results['HOMO'] = self.HOMO_pred(smiles, generated)
        if LUMO:
            results['LUMO'] = self.LUMO_pred(smiles, generated)
        if DM:
            results['DM'] = self.DM_pred(smiles, generated)
        return results
