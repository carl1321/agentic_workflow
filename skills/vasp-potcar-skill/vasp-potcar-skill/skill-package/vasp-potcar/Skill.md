---
name: VASP POTCAR Generator
description: Generate VASP POTCAR files with intelligent pseudopotential selection using multi-source verification. Invoke when user mentions POTCAR, pseudopotentials, or VASP calculation preparation.
dependencies: python>=3.10, pymatgen>=2024.1.1, pyyaml>=6.0, requests>=2.28.0
---

# VASP POTCAR Generator

Generate POTCAR files with intelligent pseudopotential selection using **multi-source verification**.

## When to Use This Skill

Automatically invoke this skill when ANY of the following conditions are met:

1. **User mentions POTCAR**: Keywords like "POTCAR", "赝势", "pseudopotential"
2. **User provides structure file**: POSCAR, CONTCAR, .vasp, .cif files with VASP calculation context
3. **User asks about pseudopotential selection**: "which pseudopotential", "what POTCAR", "哪个赝势"
4. **User mentions VASP calculation types**: "band calculation", "phonon", "声子计算", "能带计算"

**Example triggers:**
- "帮我生成POTCAR" → Invoke skill, ask for POSCAR path
- "Generate POTCAR for my POSCAR" → Invoke skill directly
- "Bi2Te3结构做声子计算用什么赝势" → Invoke skill with phonon type

## Environment Setup

```bash
# Required: VASP pseudopotential library path
export VASP_PP_PATH=/path/to/pot5.4/PBE

# Optional: Materials Project API key for enhanced recommendations
export MP_API_KEY=your_api_key
```

## Quick Start

```bash
# Basic workflow (5 default sources)
python potcar_skill.py workflow POSCAR -t standard -o POTCAR

# With Materials Project API (6 sources)
python potcar_skill.py workflow POSCAR --enable-api -o POTCAR

# Check available data sources
python potcar_skill.py sources
```

## Data Sources

The skill uses **multi-source verification** with 5 default sources + 1 optional API:

| Source | Description | Type |
|--------|-------------|------|
| **knowledge_base** | VASP Wiki official recommendations | Dynamic (YAML) |
| **pymatgen** | Pymatgen/Materials Project standard | Static |
| **vaspkit** | VASPkit tool recommendations | Static |
| **aflow** | AFLOW database (3.5M+ materials) | Dynamic (API) |
| **oqmd** | OQMD database | Dynamic (API) |
| **api_mp** | Materials Project API (optional) | Dynamic (API) |

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

- **Alkali metals**: Always use `_sv` for battery materials (Li_sv, Na_sv, K_sv)
- **3d transition metals**: Use `_pv` for magnetic calculations (Fe_pv, Mn_pv, Cr_pv)
- **ENCUT**: Report both standard (1.3×ENMAX) and high-precision (1.5×ENMAX) values
- **GW calculations**: Use `_GW` variants when available

## Workflow Output

The workflow command provides:
1. Structure parsing (formula, space group, crystal system)
2. Multi-source recommendation comparison table
3. Decision reasoning with confidence levels
4. POTCAR generation with source paths
5. Recommended ENCUT values

## Example Output

```
=== Structure Info ===
Formula: LiFePO4
Space Group: Pnma (62)
Crystal System: orthorhombic
Elements: Li, Fe, P, O

=== Multi-Source Recommendations ===
Element | knowledge_base | pymatgen | vaspkit | aflow | oqmd
--------|----------------|----------|---------|-------|-----
Li      | Li_sv          | Li_sv    | Li_sv   | Li_sv | Li_sv
Fe      | Fe_pv          | Fe_pv    | Fe      | Fe_pv | Fe_pv
P       | P              | P        | P       | P     | P
O       | O              | O        | O       | O     | O

=== Decision ===
Li: Li_sv (confidence: high) - All sources agree
Fe: Fe_pv (confidence: high) - 4/5 sources recommend _pv variant
P: P (confidence: high) - All sources agree
O: O (confidence: high) - All sources agree

=== POTCAR Generated ===
Output: POTCAR
ENCUT (standard): 520 eV
ENCUT (high-precision): 600 eV
```

## Resources

See the `resources/` folder for:
- `potcar_rules.yaml` - Knowledge base rules
- `vasp_wiki_*.md` - VASP Wiki reference documents
