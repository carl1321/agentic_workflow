# 测试数据文件夹

此目录包含用于测试的VASP输入/输出文件样例。

## 目录结构

```
fixtures/
├── poscar/          # POSCAR样例文件
│   ├── LiFePO4_POSCAR       # 磷酸铁锂（电池正极材料）
│   ├── LiCoO2_POSCAR        # 钴酸锂（电池正极材料）
│   ├── BaTiO3_POSCAR        # 钛酸钡（钙钛矿铁电材料）
│   ├── Fe2O3_POSCAR         # 氧化铁（磁性材料）
│   └── Si_diamond_POSCAR    # 金刚石结构硅（半导体）
└── potcar/          # POTCAR参考文件（需手动生成）
    └── README.md    # POTCAR生成说明
```

## POSCAR样例说明

| 文件 | 材料 | 场景 | 推荐赝势 |
|------|------|------|---------|
| LiFePO4_POSCAR | 磷酸铁锂 | battery_cathode | Li_sv, Fe_pv, P, O |
| LiCoO2_POSCAR | 钴酸锂 | battery_cathode | Li_sv, Co, O |
| BaTiO3_POSCAR | 钛酸钡 | perovskite | Ba_sv, Ti_pv, O |
| Fe2O3_POSCAR | 氧化铁 | magnetic | Fe_pv, O |
| Si_diamond_POSCAR | 金刚石硅 | semiconductor | Si |

## 使用方法

### 在测试中使用

```python
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
POSCAR_DIR = FIXTURES_DIR / "poscar"

# 读取测试POSCAR
with open(POSCAR_DIR / "LiFePO4_POSCAR") as f:
    poscar_content = f.read()
```

### 生成对应POTCAR

设置环境变量后运行生成脚本：

```bash
set VASP_PP_PATH=D:\code\pot5.4
python -c "
from vasp_potcar_skill.tools.potcar_generator import generate_potcar_from_knowledge
result = generate_potcar_from_knowledge(
    elements=['Li', 'Fe', 'P', 'O'],
    scenario='battery_cathode',
    output_path='tests/fixtures/potcar/LiFePO4_POTCAR'
)
print(result)
"
```
