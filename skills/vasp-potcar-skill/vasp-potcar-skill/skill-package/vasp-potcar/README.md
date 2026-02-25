# VASP POTCAR Skill

A professional skill for Claude that provides intelligent VASP pseudopotential (POTCAR) file generation with multi-source verification.

## Features

- **Multi-source verification**: Compares recommendations from 6 data sources
  - Knowledge base (VASP Wiki official recommendations)
  - Pymatgen/Materials Project standards
  - VASPkit recommendations
  - AFLOW database (3.5M+ materials, API)
  - OQMD database (API)
  - Materials Project API (optional)

- **Intelligent decision engine**: Resolves conflicts and provides confidence levels
- **Context-aware**: Automatically adjusts pseudopotentials based on calculation type
- **Complete workflow**: From POSCAR parsing to POTCAR generation

## Installation

### For Claude Desktop/Web

1. Unzip this skill package
2. In Claude Settings → Capabilities → Skills, click "Add Skill"
3. Select the `vasp-potcar` folder
4. Enable the skill

### For Claude Code

```bash
# Install dependencies
pip install pymatgen pyyaml requests

# Optional: Install Materials Project API support
pip install mp-api

# Set environment variable
export VASP_PP_PATH=/path/to/pot5.4/PBE
```

## Usage

Once installed, Claude will automatically invoke this skill when you:

- Ask to "generate POTCAR"
- Provide a POSCAR file and mention VASP calculations
- Ask questions about pseudopotential selection
- Mention specific calculation types (band, phonon, etc.)

### Example Prompts

```
"Generate POTCAR for my POSCAR file at /path/to/POSCAR"

"I have a LiFePO4 structure, which pseudopotentials should I use for phonon calculations?"

"帮我生成POTCAR,结构文件在 ./POSCAR"

"Generate POTCAR for band structure calculation"
```

### Direct CLI Usage

You can also use the skill script directly:

```bash
# Full workflow
python potcar_skill.py workflow POSCAR -t standard -o POTCAR

# Check available sources
python potcar_skill.py sources

# Get recommendations
python potcar_skill.py recommend Li Fe P O -t standard

# Parse structure
python potcar_skill.py parse POSCAR
```

## Configuration

### Required Environment Variables

```bash
# VASP pseudopotential library path (required)
export VASP_PP_PATH=/path/to/potpaw_PBE.64
```

### Optional Environment Variables

```bash
# Materials Project API key (for enhanced recommendations)
export MP_API_KEY=your_api_key_here
```

## Data Sources

The skill uses multiple data sources for cross-validation:

1. **knowledge_base** (Default) - VASP Wiki official recommendations
2. **pymatgen** (Default) - Materials Project standard recommendations
3. **vaspkit** (Default) - VASPkit tool recommendations
4. **aflow** (Default) - AFLOW database API queries
5. **oqmd** (Default) - OQMD database API queries
6. **api_mp** (Optional) - Materials Project API real-time queries

## Calculation Types

Supported calculation types:
- `standard` - Structure optimization/static calculations (default)
- `accurate` - High-precision calculations
- `band` - Band structure calculations
- `dos` - Density of states
- `phonon` - Phonon calculations
- `magnetic` - Magnetic property calculations
- `gw` - GW quasiparticle calculations
- `optical` - Optical property calculations

## Key Rules

The skill follows VASP official guidelines:

- **Alkali metals**: Use `_sv` variants (Li_sv, Na_pv, K_sv) for battery materials
- **3d transition metals**: Use `_pv` variants (Fe_pv, Mn_pv, Cr_pv) for magnetic calculations
- **p-block elements**: Use `_d` variants (Ga_d, Ge_d, In_d, Sn_d) when available
- **GW calculations**: Use `_GW` variants when available

## File Structure

```
vasp-potcar/
├── Skill.md                    # Main skill definition
├── README.md                   # This file
├── potcar_skill.py             # Execution script
└── resources/                  # Knowledge base
    ├── potcar_rules.yaml       # VASP Wiki rules
    ├── vasp_wiki_Available_pseudopotentials.md
    └── vasp_wiki_choosing_pseudopotentials.md
```

## Dependencies

### Required
- Python >= 3.10
- pymatgen >= 2024.1.1
- pyyaml >= 6.0
- requests >= 2.28.0

### Optional
- mp-api >= 0.39.0 (for Materials Project API)

## Troubleshooting

### "VASP_PP_PATH not set"
Set the environment variable to your VASP pseudopotential library:
```bash
export VASP_PP_PATH=/path/to/potpaw_PBE.64
```

### "API unavailable"
External APIs (AFLOW, OQMD) may be temporarily unavailable. The skill will automatically fall back to static recommendations.

### "Module not found"
Install required dependencies:
```bash
pip install pymatgen pyyaml requests
```

## License

This skill is provided as-is for research and educational purposes.

## Support

For issues and questions:
- Check the VASP Wiki: https://www.vasp.at/wiki/
- Review the skill documentation in Skill.md
- Ensure all environment variables are set correctly
