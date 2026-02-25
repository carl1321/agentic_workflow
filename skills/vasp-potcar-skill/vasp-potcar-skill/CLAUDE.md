# VASP POTCAR Skill

智能VASP赝势选择工具 - 自包含版本，可直接集成到工作流。

## 快速开始

```bash
# 完整工作流
python .claude/commands/potcar_skill.py workflow POSCAR -o POTCAR

# 带INCAR自动推断
python .claude/commands/potcar_skill.py workflow POSCAR --incar INCAR -o POTCAR
```

## Skill命令

在Claude Code中使用:
```
/project:potcar
```

## CLI命令

| 命令 | 功能 | 示例 |
|------|------|------|
| `parse` | 解析POSCAR/INCAR | `parse POSCAR` |
| `recommend` | 获取推荐 | `recommend Li Fe P O -t standard` |
| `generate` | 生成POTCAR | `generate Li Fe P O -p Li_sv Fe_pv P O -o POTCAR` |
| `variants` | 列出变体 | `variants Fe` |
| `workflow` | 完整流程 | `workflow POSCAR -o POTCAR` |

## 计算类型

| 类型 | 说明 |
|------|------|
| `standard` | 结构优化/静态 |
| `accurate` | 高精度 |
| `band` | 能带 |
| `dos` | 态密度 |
| `phonon` | 声子 |
| `magnetic` | 磁性 |
| `gw` | GW |
| `optical` | 光学 |

## 环境配置

```bash
# 必需: VASP赝势库路径
export VASP_PP_PATH=/d/code/pot5.4/PBE

# 可选: pymatgen (高级解析)
pip install pymatgen
```

## 项目结构

```
.claude/commands/
├── potcar.md           # Skill说明
└── potcar_skill.py     # 核心脚本（自包含）
```

## 集成到工作流

```python
import subprocess

# 获取推荐
result = subprocess.run([
    "python", ".claude/commands/potcar_skill.py",
    "recommend", "Li", "Fe", "P", "O", "-t", "standard"
], capture_output=True, text=True)
print(result.stdout)

# 完整工作流
subprocess.run([
    "python", ".claude/commands/potcar_skill.py",
    "workflow", "POSCAR", "-o", "POTCAR"
])
```

## 特点

- **自包含**: 单文件，无需安装
- **轻依赖**: 仅pymatgen可选
- **内置知识库**: 包含VASP官方推荐规则
- **易集成**: CLI接口，可嵌入任何工作流
