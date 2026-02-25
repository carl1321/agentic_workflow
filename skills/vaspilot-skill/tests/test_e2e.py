"""
End-to-end test: Submit a simple Si relaxation calculation
"""

import sys
import os
import yaml

sys.path.insert(0, "D:/code/vaspilot-skill")

from skill_package import VASPWorkflow, StructureTools, VASPInputGenerator

# Load config
config_path = "D:/code/vaspilot-skill/configs/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

print("=== VASPilot End-to-End Test ===\n")
print(f"HPC: {config['ssh']['host']}")
print(f"User: {config['ssh']['username']}")
print(f"POTCAR: {config['hpc']['potcar_dir']}")
print(f"VASP: {config['hpc']['vasp_bin']}")
print()

# Step 1: Create a simple Si structure
print("1. Creating Si diamond structure...")
structure_tools = StructureTools()
si_structure = structure_tools.create_structure(
    lattice_params={"a": 5.43, "b": 5.43, "c": 5.43},
    species=["Si", "Si"],
    coords=[
        [0.00, 0.00, 0.00],
        [0.25, 0.25, 0.25],
    ]
)

analysis = structure_tools.analyze_structure(si_structure)
print(f"   Formula: {analysis['formula']}")
print(f"   Space group: {analysis['space_group']['symbol']}")
print(f"   Atoms: {analysis['num_atoms']}")
print()

# Step 2: Generate input files locally
print("2. Generating VASP input files...")
generator = VASPInputGenerator(potcar_dir=config['hpc']['potcar_dir'])

local_dir = "D:/code/vaspilot-skill/work/Si_test"
os.makedirs(local_dir, exist_ok=True)

files = generator.write_inputs(
    structure=si_structure,
    output_dir=local_dir,
    calc_type="relaxation",
    incar_params={"ENCUT": 400, "NSW": 10},  # Quick test
    potcar_dir=config['hpc']['potcar_dir']
)
print(f"   Generated: {list(files.keys())}")

# Generate Slurm script
slurm_script = generator.generate_slurm_script(
    job_name="Si_test",
    nodes=config['slurm']['nodes'],
    ntasks=config['slurm']['ntasks'],
    partition=config['slurm']['partition'],
    time_limit="01:00:00",  # 1 hour for test
    vasp_bin=config['hpc']['vasp_bin'],
    vasp_command=config['hpc']['vasp_command'],
    potcar_dir=config['hpc']['potcar_dir'],
    gen_potcar=True
)

with open(f"{local_dir}/submit.sh", "w", newline='\n') as f:
    f.write(slurm_script)
print("   Generated: submit.sh")
print()

# Show generated files
print("3. Generated files preview:")
print("\n--- INCAR ---")
with open(f"{local_dir}/INCAR") as f:
    print(f.read()[:500])

print("\n--- gen_potcar.sh ---")
with open(f"{local_dir}/gen_potcar.sh") as f:
    print(f.read())

print("\n--- submit.sh ---")
with open(f"{local_dir}/submit.sh") as f:
    print(f.read())

# Step 3: Test SSH connection and upload
print("\n4. Testing SSH connection and upload...")
from skill_package.remote_executor import RemoteExecutor

executor = RemoteExecutor(
    host=config['ssh']['host'],
    username=config['ssh']['username'],
    port=config['ssh']['port'],
    key_path=config['ssh']['key_path']
)

if executor.connect():
    print("   [OK] SSH connected")

    # Create remote directory
    remote_dir = f"{config['hpc']['work_dir']}/Si_test"
    result = executor.execute_command(f"mkdir -p {remote_dir}")
    print(f"   Created remote dir: {remote_dir}")

    # Upload files
    print("   Uploading files...")
    upload_result = executor.upload_directory(local_dir, remote_dir)
    print(f"   Uploaded: {upload_result['uploaded']}")

    # Verify upload
    result = executor.execute_command(f"ls -la {remote_dir}")
    print(f"\n   Remote directory contents:")
    print(result['stdout'])

    # Test POTCAR generation
    print("\n5. Testing POTCAR generation on HPC...")
    result = executor.execute_command(f"cd {remote_dir} && bash gen_potcar.sh && head -5 POTCAR")
    print(result['stdout'])
    if result['stderr']:
        print(f"   stderr: {result['stderr']}")

    executor.disconnect()
    print("\n[OK] Test completed successfully!")
else:
    print("   [FAIL] SSH connection failed")
