"""
Explore HPC environment to find VASP and POTCAR paths
"""

import sys
sys.path.insert(0, "D:/code/vaspilot-skill")

from skill_package.remote_executor import RemoteExecutor

config = {
    "host": "cancon.hpccube.com",
    "username": "acndczol6t",
    "port": 65023,
    "key_path": "D:/code/acndczol6t_cancon.hpccube.com_RsaKeyExpireTime_2026-05-25_15-56-33.txt"
}

executor = RemoteExecutor(
    host=config["host"],
    username=config["username"],
    port=config["port"],
    key_path=config["key_path"]
)

if executor.connect():
    print("=== Check existing VASP slurm script ===")
    result = executor.execute_command("cat ~/vasp.slurm")
    print(result["stdout"])
    print()

    print("=== Check slurm_template directory ===")
    result = executor.execute_command("ls -la ~/slurm_template/ && cat ~/slurm_template/*vasp* 2>/dev/null || echo 'no vasp template'")
    print(result["stdout"])
    print()

    print("=== Search for POTCAR in common locations ===")
    search_paths = [
        "/public/software",
        "/share",
        "/opt",
        "/public/home/acndczol6t/software"
    ]
    for path in search_paths:
        result = executor.execute_command(f"find {path} -name 'POTCAR' -type f 2>/dev/null | head -5")
        if result["stdout"]:
            print(f"Found in {path}:")
            print(result["stdout"])
            print()

    print("=== Search for potpaw directories ===")
    result = executor.execute_command("find /public -maxdepth 4 -type d -name 'potpaw*' 2>/dev/null | head -10")
    print(result["stdout"] or "Not found in /public")
    print()

    print("=== Check module system ===")
    result = executor.execute_command("source /etc/profile && module avail 2>&1 | grep -i vasp")
    print(result["stdout"] or result["stderr"] or "No VASP modules found")
    print()

    print("=== Check software directory ===")
    result = executor.execute_command("ls -la ~/software/")
    print(result["stdout"])
    print()

    print("=== Search for vasp executable ===")
    result = executor.execute_command("which vasp_std 2>/dev/null || find /public/software -name 'vasp_std' -type f 2>/dev/null | head -3")
    print(result["stdout"] or "vasp_std not found in PATH")

    executor.disconnect()
