# POTCAR Test Fixtures

此目录用于存放POTCAR测试文件。

## 预期配置

| POSCAR | 场景 | 预期POTCAR | 推荐ENCUT |
|--------|------|-----------|----------|
| LiFePO4_POSCAR | battery_cathode | Li_sv, Fe_pv, P, O | 649 eV |
| BaTiO3_POSCAR | perovskite | Ba_sv, Ti_pv, O | 520 eV |
| Fe2O3_POSCAR | standard | Fe, O | 520 eV |
| Si_diamond_POSCAR | semiconductor | Si | 245 eV |
| LiCoO2_POSCAR | battery_cathode | Li_sv, Co, O | 520 eV |

## 注意事项

1. POTCAR文件受VASP许可证保护，不应提交到版本控制
2. 测试时会从 `VASP_PP_PATH` 环境变量指定的目录生成POTCAR
3. 每个子目录对应一个测试用例，包含:
   - `expected.json`: 预期的配置和参数
   - `POTCAR`: (可选) 生成的POTCAR文件用于验证
