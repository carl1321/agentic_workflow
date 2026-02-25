# VASPilot Skill

A comprehensive skill for automating VASP calculations on remote HPC clusters via SSH.

## Features

- SSH-based remote execution with key/password authentication
- Intelligent POTCAR selection via vasp-potcar-skill integration
- High-throughput parallel job management
- Result visualization (band structure, DOS, convergence)
- Portable configuration with environment variable support

## Installation

```bash
pip install paramiko pymatgen pyyaml matplotlib
```

## Configuration

Create `~/.vaspilot/config.yaml` or set environment variables:

```yaml
ssh:
  host: your.hpc.cluster
  username: your_username
  port: 22
  key_path: ~/.ssh/id_rsa

hpc:
  work_dir: /scratch/username/vaspilot
  potcar_dir: /path/to/potpaw_PBE
  vasp_bin: /path/to/vasp/bin
  vasp_command: vasp_std

slurm:
  partition: normal
  nodes: 1
  ntasks: 32
  time: "48:00:00"

potcar_method: potcar_skill  # or "script"
```

Environment variables: `VASPILOT_SSH_HOST`, `VASPILOT_SSH_USERNAME`, etc.

## Usage Examples

### Simple Calculation

```python
from skill_package import VASPWorkflow, load_config

config = load_config()

with VASPWorkflow(config) as workflow:
    calc_id = workflow.prepare_calculation(
        structure="POSCAR",
        calc_type="relaxation"
    )
    workflow.submit_calculation(calc_id)
    workflow.wait_for_completion(calc_id)
    result = workflow.get_result(calc_id)
    print(f"Energy: {result['final_energy']} eV")
```

### High-Throughput Batch

```python
from skill_package import HighThroughputWorkflow, load_config

config = load_config()

with HighThroughputWorkflow(config, max_concurrent_jobs=20) as workflow:
    # Prepare batch from Materials Project
    structures = workflow.search_mp_structures(["Si", "Ge", "GaAs"])
    calc_ids = workflow.prepare_batch(structures, calc_type="relaxation")

    # Submit all in parallel
    workflow.submit_batch(calc_ids, parallel=True)

    # Monitor until complete
    workflow.wait_all_complete(timeout=3600)

    # Download and parse results
    workflow.download_all_results()
    results = workflow.parse_all_results()

    # Generate summary
    workflow.export_summary("results.csv")
```

### Visualization

```python
from skill_package import ResultVisualizer

viz = ResultVisualizer()

# Band structure
viz.plot_band_structure("vasprun.xml", output_path="band.png")

# DOS
viz.plot_dos("vasprun.xml", output_path="dos.png", elements=["Si", "O"])

# Convergence
viz.plot_convergence("OSZICAR", output_path="convergence.png")

# Batch summary
viz.plot_batch_summary(results, output_path="summary.png")
```

## Module Overview

| Module | Description |
|--------|-------------|
| `remote_executor` | SSH/SFTP/Slurm operations |
| `vasp_generator` | VASP input file generation |
| `structure_tools` | Crystal structure manipulation |
| `result_parser` | VASP output parsing |
| `potcar_generator` | Intelligent POTCAR selection |
| `highthroughput` | Parallel batch workflow |
| `visualizer` | Result visualization |
| `config_loader` | Portable configuration |

## Trigger Phrases

- "Run VASP calculation", "Submit VASP job"
- "High-throughput calculation", "Batch VASP"
- "Plot band structure", "Visualize results"
