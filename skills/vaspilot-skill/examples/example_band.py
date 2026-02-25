"""
Example: Run a simple Si band structure calculation
"""

import os
import sys
import yaml
from pathlib import Path

# Add skill package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from skill_package import VASPWorkflow, StructureTools, VASPInputGenerator


def load_config():
    """Load configuration from file or environment"""
    config_path = os.path.expanduser("~/.vaspilot/config.yaml")

    if os.path.exists(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f)
    else:
        # Return example config for testing
        return {
            "ssh": {
                "host": "hpc.example.com",
                "username": "testuser",
                "port": 22,
                "key_path": "~/.ssh/id_ed25519"
            },
            "hpc": {
                "work_dir": "/scratch/testuser/vaspilot",
                "potcar_dir": "/opt/vasp/potpaw_PBE",
                "vasp_module": "vasp/6.4.0"
            },
            "slurm": {
                "partition": "normal",
                "nodes": 1,
                "ntasks": 48,
                "time": "24:00:00"
            },
            "local_work_dir": "./vaspilot_work",
            "mp_api_key": os.environ.get("MP_API_KEY")
        }


def example_band_calculation():
    """
    Example: Calculate band structure of Si

    Steps:
    1. Search Si structure from Materials Project
    2. Run relaxation -> SCF -> Band workflow
    3. Parse and display results
    """
    config = load_config()

    print("=== VASPilot Band Structure Example ===\n")

    # Check if we have MP API key
    if not config.get("mp_api_key"):
        print("Note: No MP_API_KEY set. Using local structure file instead.")
        # You would provide a local POSCAR file here
        return

    with VASPWorkflow(config) as workflow:
        # Step 1: Search for Si structure
        print("1. Searching for Si structure...")
        structures = workflow.search_structure("Si", max_results=3)

        if not structures:
            print("   No structures found!")
            return

        print(f"   Found {len(structures)} structures:")
        for s in structures:
            print(f"   - {s['material_id']}: {s['formula']}, "
                  f"E={s['energy_per_atom']:.3f} eV/atom, "
                  f"gap={s['band_gap']:.2f} eV")

        # Use the most stable structure
        si_structure = structures[0]["structure"]
        print(f"\n   Using: {structures[0]['material_id']}")

        # Step 2: Analyze structure
        print("\n2. Analyzing structure...")
        analysis = workflow.structure_tools.analyze_structure(si_structure)
        print(f"   Formula: {analysis['formula']}")
        print(f"   Space group: {analysis['space_group']['symbol']} "
              f"(#{analysis['space_group']['number']})")
        print(f"   Lattice: a={analysis['lattice']['a']:.3f} Å")

        # Step 3: Run workflow
        print("\n3. Running band structure workflow...")
        print("   This will execute: relaxation -> SCF -> band")

        result = workflow.run_workflow(
            structure=si_structure,
            workflow_type="band",
            base_name="Si_example"
        )

        # Step 4: Display results
        print("\n4. Results:")
        if result["success"]:
            band_result = result["results"].get("Si_example_band", {})
            print(f"   Band gap: {band_result.get('band_gap', 'N/A')} eV")
            print(f"   Is direct: {band_result.get('is_direct', 'N/A')}")
            print(f"   Is metal: {band_result.get('is_metal', 'N/A')}")
        else:
            print("   Workflow failed. Check individual calculation results.")
            for calc_id, res in result["results"].items():
                status = "OK" if res.get("success") else "FAILED"
                print(f"   - {calc_id}: {status}")


def example_local_only():
    """
    Example: Generate VASP inputs locally without HPC connection

    Useful for testing or preparing calculations offline.
    """
    print("=== Local Input Generation Example ===\n")

    # Initialize generator
    generator = VASPInputGenerator(potcar_dir="/opt/vasp/potpaw_PBE")
    structure_tools = StructureTools()

    # Create a simple Si structure
    print("1. Creating Si diamond structure...")
    si_structure = structure_tools.create_structure(
        lattice_params={"a": 5.43, "b": 5.43, "c": 5.43,
                       "alpha": 90, "beta": 90, "gamma": 90},
        species=["Si", "Si", "Si", "Si", "Si", "Si", "Si", "Si"],
        coords=[
            [0.00, 0.00, 0.00],
            [0.25, 0.25, 0.25],
            [0.50, 0.50, 0.00],
            [0.75, 0.75, 0.25],
            [0.50, 0.00, 0.50],
            [0.75, 0.25, 0.75],
            [0.00, 0.50, 0.50],
            [0.25, 0.75, 0.75],
        ]
    )

    # Analyze
    analysis = structure_tools.analyze_structure(si_structure)
    print(f"   Space group: {analysis['space_group']['symbol']}")

    # Generate inputs
    output_dir = "./test_Si_relax"
    print(f"\n2. Generating relaxation inputs in {output_dir}...")

    files = generator.write_inputs(
        structure=si_structure,
        output_dir=output_dir,
        calc_type="relaxation",
        incar_params={"ENCUT": 400}  # Custom parameter
    )

    print("   Generated files:")
    for f in files:
        print(f"   - {f}")

    # Generate Slurm script
    slurm_script = generator.generate_slurm_script(
        job_name="Si_relax",
        nodes=1,
        ntasks=48,
        partition="normal"
    )

    with open(f"{output_dir}/submit.sh", "w") as f:
        f.write(slurm_script)
    print("   - submit.sh")

    print("\n3. Done! You can now upload these files to your HPC.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VASPilot Examples")
    parser.add_argument("--local", action="store_true",
                       help="Run local-only example (no HPC connection)")

    args = parser.parse_args()

    if args.local:
        example_local_only()
    else:
        example_band_calculation()
