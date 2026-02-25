---
name: potcar-generating
description: Generates VASP POTCAR files with intelligent pseudopotential selection using multi-source verification. Use when user needs to create POTCAR, select pseudopotentials, or prepare VASP calculations.
---

# VASP POTCAR Generator

Generate POTCAR files with intelligent pseudopotential selection using **multi-source verification**.

## Trigger Conditions (When to Use This Skill)

**IMPORTANT: Automatically invoke this skill when ANY of the following conditions are met:**

1. **User mentions POTCAR**: Keywords like "POTCAR", "赝势", "pseudopotential"
2. **User provides POSCAR/structure file**: When user provides a structure file path (POSCAR, CONTCAR, .vasp, .cif) and mentions VASP calculation preparation
3. **User asks about pseudopotential selection**: Questions like "which pseudopotential", "what POTCAR", "哪个赝势"
4. **User mentions VASP calculation types**: Combined with structure files - "band calculation", "phonon", "声子计算", "能带计算", "结构优化"

**Example triggers:**
- "帮我生成POTCAR" → Invoke skill, ask for POSCAR path
- "我的结构文件是xxx.vasp，帮我准备VASP计算" → Invoke skill with the structure file
- "Bi2Te3结构做声子计算用什么赝势" → Invoke skill with phonon type
- "Generate POTCAR for my POSCAR at /path/to/POSCAR" → Invoke skill directly

## Data Sources

The skill uses **multi-source verification** with 5 default sources + 1 optional API:

| Source | Description | Type | API Key |
|--------|-------------|------|---------|
| **knowledge_base** | VASP Wiki official recommendations | Dynamic (YAML) | No |
| **pymatgen** | Pymatgen/Materials Project standard | Static | No |
| **vaspkit** | VASPkit tool recommendations | Static | No |
| **aflow** | AFLOW database (3.5M+ materials) | Dynamic (API) | No |
| **oqmd** | OQMD database (Open Quantum Materials) | Dynamic (API) | No |
| **api_mp** | Materials Project API (real-time) | Dynamic (API) | Yes (optional) |

**Note**: AFLOW and OQMD perform real-time API queries when a formula is provided. If the API is unavailable or the query fails, they fall back to static mappings.

Check available sources:
```bash
python .claude/commands/potcar_skill.py sources
```

## Quick Start

```bash
# Set pseudopotential library path first
export VASP_PP_PATH=/path/to/pot5.4/PBE

# Basic workflow (5 default sources: knowledge_base, pymatgen, vaspkit, aflow, oqmd)
python .claude/commands/potcar_skill.py workflow POSCAR -t phonon -o POTCAR

# Enable Materials Project API for additional real-time data (6 sources)
python .claude/commands/potcar_skill.py workflow POSCAR --enable-api -o POTCAR
```

## Workflow

The workflow command provides:
1. Structure parsing (formula, space group, crystal system)
2. Multi-source recommendation comparison table
3. Decision reasoning with confidence levels
4. POTCAR generation with source paths

### Running the Workflow

```bash
# Interactive mode
python .claude/commands/potcar_skill.py workflow <POSCAR_PATH>

# Non-interactive with all options
python .claude/commands/potcar_skill.py workflow <POSCAR_PATH> -t <calc_type> -p <precision> -o <OUTPUT_PATH>

# With API query (slower but more accurate)
python .claude/commands/potcar_skill.py workflow <POSCAR_PATH> --enable-api -o POTCAR
```

### Output Includes

- Structure info (formula, space group, crystal system, elements)
- **Multi-source recommendation comparison table** (知识库 vs Pymatgen vs VASPkit vs AFLOW vs OQMD vs MP API)
- **Decision reasoning** for each element with confidence level
- Source paths for each POTCAR
- Recommended ENCUT values

## Commands Reference

| Command | Purpose |
|---------|---------|
| `workflow POSCAR` | Full workflow with multi-source verification |
| `sources` | Show available data sources |
| `parse POSCAR` | Parse structure file |
| `recommend El1 El2 -t type` | Get recommendations |
| `variants Element` | List available variants |
| `generate El1 El2 -p Pot1 Pot2 -o POTCAR` | Generate with specific potentials |

## Calculation Types

| Type | Description |
|------|-------------|
| `standard` | Structure optimization/static (default) |
| `accurate` | High precision |
| `band` | Band structure |
| `dos` | Density of states |
| `phonon` | Phonon calculation |
| `magnetic` | Magnetic properties |
| `gw` | GW quasiparticle |
| `optical` | Optical properties |

## Critical Rules

**Alkali metals**: Always use `_sv` for battery materials (Li_sv, Na_sv)

**3d transition metals**: Use `_pv` for magnetic calculations (Fe_pv, Mn_pv, Cr_pv)

**ENCUT**: Report both standard (1.3×ENMAX) and high-precision (1.5×ENMAX) values

## Environment

Requires `VASP_PP_PATH` environment variable pointing to pseudopotential library.
