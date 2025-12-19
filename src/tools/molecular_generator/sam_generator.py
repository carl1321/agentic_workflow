from tqdm import tqdm
import pandas as pd
from src.tools.molecular_generator.model import GPT, GPTConfig
from src.tools.molecular_generator.utils_generator import load_stoi, canonic_smiles, get_mol, sample
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit import Chem
import torch
import re



class SAMGenerator:
    # init the paras of the model
    def __init__(self,scaf_condition,anchoring_group,gen_size):
        self.regex=re.compile("(\[[^\]]+]|<|Br?|Cl?|N|O|S|P|F|I|b|c|n|o|s|p|\(|\)|\.|=|#|-|\+|\\\\|\/|:|~|@|\?|>|\*|\$|\%[0-9]{2}|[0-9])")
        self.prop = None
        # 使用本地weights目录中的权重文件
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.model_weight = os.path.join(current_dir, 'weights', 'sam_related_data_transfer_learning_2.pt')
        self.scaffold = True
        self.list = False
        self.scaf_condition = scaf_condition#['c1ccccc1', 'c1ccc2c(c1)[nH]c1ccccc12']
        self.lstm = False
        self.context = anchoring_group # "O=P(O)(O)"
        self.csv_name = 'test.csv'
        # 使用SAM-GPT的词汇表和配置
        self.stoi_name = os.path.join(current_dir, 'weights', '117_tokens_stoi')
        self.stoi, self.itos = load_stoi(self.stoi_name)
        self.batch_size = gen_size if gen_size < 100 else 100
        self.gen_size = gen_size
        self.vocab_size = 117  # SAM-GPT配置
        self.block_size = 100  # SAM-GPT配置
        self.props = []
        self.num_props = len(self.props)
        self.n_layer = 8
        self.n_head = 8
        self.n_embd = 256
        self.lstm_layers = 2
        self.model = self.load_model()
        
        
    def load_model(self):
        scaffold_max_len = 100 if self.scaffold else 0  # SAM-GPT配置
        num_props = len(self.props)
        config = GPTConfig(self.vocab_size, self.block_size, num_props = num_props,
                           n_layer=self.n_layer, n_head=self.n_head, n_embd = self.n_embd, scaffold = self.scaffold, scaffold_maxlen = scaffold_max_len,
                           lstm = self.lstm, lstm_layers = self.lstm_layers
                           )
        model = GPT(config)
        
        # 智能选择设备：优先使用 GPU，如果不可用则使用 CPU
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model.load_state_dict(torch.load(self.model_weight, map_location=self.device))
        model.to(self.device)
        
        device_name = 'GPU' if torch.cuda.is_available() else 'CPU'
        print(f'Model loaded on {device_name}')
        return model
    
    
    # Convert the medel logits to the text form.
    def process_output(self, y, scaf):
        molecules = []
        invalid=0
        for gen_mol in y:
            completion = ''.join([self.itos[int(i)] for i in gen_mol]).replace('<', '')
            mol = get_mol(completion)
            if mol:
                smiles = Chem.MolToSmiles(mol)
                scaffold_smiles = Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol))
                mol_dict = {
                    'smiles': smiles,
                    'scaffold_condition': scaf.replace('<', '') if scaf else None,
                    'scaffold_smiles': scaffold_smiles
                }
                molecules.append(mol_dict)
            else:
                invalid=1
        return molecules,invalid    
    
    
    def generate_with_scaffold(self):
        scaffold_max_len = 100 if self.scaffold else 0  # 必须与模型配置保持一致
        scaf_token = [ i + str('<')*(scaffold_max_len - len(self.regex.findall(i))) for i in self.scaf_condition]
        mol_dict = []
        seen_smiles = set()  # 用于跟踪已见过的 SMILES，确保不重复
        total_generated = 0
        
        print(f"开始生成，目标数量: {self.gen_size}, 批次大小: {self.batch_size}, scaffold数量: {len(scaf_token)}")
        
        # 持续生成直到获得足够数量的唯一有效分子
        while len(seen_smiles) < self.gen_size:
            for scaf in scaf_token:
                print(f"当前唯一有效分子数: {len(seen_smiles)}/{self.gen_size}, 总生成: {total_generated}")
                
                x = torch.tensor([self.stoi[s] for s in self.regex.findall(self.context)], dtype=torch.long)[None,...].repeat(self.batch_size, 1).to(self.device)
                sca = torch.tensor([self.stoi[s] for s in self.regex.findall(scaf)], dtype=torch.long)[None,...].repeat(self.batch_size, 1).to(self.device)
                y = sample(
                    self.model,
                    x,
                    self.block_size,
                    temperature=1,
                    sample=True,
                    top_k=10,
                    prop=None,
                    scaffold=sca
                )
                # Get both valid mols and invalid numbers
                valid_mols, invalid_count = self.process_output(y, scaf)
                total_generated += self.batch_size
                
                # 只添加新的、唯一的分子
                new_count = 0
                for mol in valid_mols:
                    smiles = mol['smiles']
                    if smiles not in seen_smiles:
                        seen_smiles.add(smiles)
                        mol_dict.append(mol)
                        new_count += 1
                
                print(f"本批: 生成 {self.batch_size} 个, 有效 {len(valid_mols)} 个, 新增唯一 {new_count} 个")
                
                # 如果已经获得足够的唯一分子，退出循环
                if len(seen_smiles) >= self.gen_size:
                    print(f"✓ 已达到目标数量 {self.gen_size} 个唯一有效分子")
                    break
            
            # 如果已经获得足够的唯一分子，退出外层循环
            if len(seen_smiles) >= self.gen_size:
                break
                

        results = pd.DataFrame(mol_dict)
        # 不需要再去重，因为已经在生成过程中保证唯一性
        results['scaffold_condition'] = results['scaffold_condition'].str.replace('<', '')
        
        # 精确截取到目标数量
        results = results.head(self.gen_size)
        
        print(f"=" * 60)
        print(f"✓ 最终输出: {len(results)} 个唯一有效分子 (目标: {self.gen_size})")
        print(f"  总生成次数: {total_generated}")
        print(f"  成功率: {len(results)/total_generated*100:.1f}%")
        print(f"=" * 60)
        
        return results.to_dict('records')

