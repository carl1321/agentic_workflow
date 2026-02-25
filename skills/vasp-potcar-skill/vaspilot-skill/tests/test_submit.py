"""
Submit a real VASP calculation test
"""

import sys
import os
import yaml
import time

sys.path.insert(0, "D:/code/vaspilot-skill")

from skill_package import VASPWorkflow, StructureTools, VASPInputGenerator
from skill_package.remote_executor import RemoteExecutor

# Load config
config_path = "D:/code/vaspilot-skill/configs/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

print("=== VASPilot Job Submission Test ===\n")

# Create Si structure
print("1. Creating Si structure...")
structure_tools = StructureTools()
si_structure = structure_tools.create_structure(
    lattice_params={"a": 5.43, "b": 5.43, "c": 5.43},
    species=["Si", "Si"],
    coords=[
        [0.00, 0.00, 0.00],
        [0.25, 0.25, 0.25],
    ]
)
print(f"   Created: {structure_tools.analyze_structure(si_structure)['formula']}")

# Generate input files
print("\n2. Generating input files...")
generator = VASPInputGenerator(potcar_dir=config['hpc']['potcar_dir'])

local_dir = "D:/code/vaspilot-skill/work/Si_submit_test"
os.makedirs(local_dir, exist_ok=True)

files = generator.write_inputs(
    structure=si_structure,
    output_dir=local_dir,
    calc_type="relaxation",
    incar_params={"ENCUT": 400, "NSW": 5, "EDIFF": 1e-5},  # Quick test
    potcar_dir=config['hpc']['potcar_dir']
)

# Generate Slurm script
slurm_script = generator.generate_slurm_script(
    job_name="Si_submit_test",
    nodes=1,
    ntasks=32,
    partition="kshcnormal",
    time_limit="00:30:00",  # 30 min
    vasp_bin=config['hpc']['vasp_bin'],
    vasp_command=config['hpc']['vasp_command'],
    potcar_dir=config['hpc']['potcar_dir'],
    gen_potcar=True
)

with open(f"{local_dir}/submit.sh", "w", newline='\n') as f:
    f.write(slurm_script)

print(f"   Generated files in: {local_dir}")

# Connect and submit
print("\n3. Connecting to HPC...")
executor = RemoteExecutor(
    host=config['ssh']['host'],
    username=config['ssh']['username'],
    port=config['ssh']['port'],
    key_path=config['ssh']['key_path']
)

if not executor.connect():
    print("   [FAIL] Connection failed")
    sys.exit(1)

print("   [OK] Connected")

# Upload
remote_dir = f"{config['hpc']['work_dir']}/Si_submit_test"
print(f"\n4. Uploading to {remote_dir}...")
executor.execute_command(f"rm -rf {remote_dir} && mkdir -p {remote_dir}")
upload_result = executor.upload_directory(local_dir, remote_dir)
print(f"   Uploaded: {len(upload_result['uploaded'])} files")

# Submit job
print("\n5. Submitting job...")
job_id = executor.submit_slurm_job(remote_dir, "submit.sh")

if job_id:
    print(f"   [OK] Job submitted: {job_id}")

    # Monitor for a bit
    print("\n6. Monitoring job status...")
    for i in range(6):
        time.sleep(10)
        status = executor.get_job_status(job_id)
        print(f"   [{i*10}s] Status: {status.status}")
        if status.status in ["COMPLETED", "FAILED", "CANCELLED"]:
            break

    # Check output
    print("\n7. Checking output files...")
    result = executor.execute_command(f"ls -la {remote_dir}")
    print(result['stdout'])

    # Check if OUTCAR exists
    result = executor.execute_command(f"tail -20 {remote_dir}/OUTCAR 2>/dev/null || echo 'OUTCAR not ready'")
    print("\n   OUTCAR tail:")
    print(result['stdout'])

else:
    print("   [FAIL] Job submission failed")

executor.disconnect()
print("\n[DONE]")
