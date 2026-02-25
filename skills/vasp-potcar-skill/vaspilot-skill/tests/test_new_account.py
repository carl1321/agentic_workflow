"""
Test SSH connection and explore HPC environment
"""

import sys
sys.path.insert(0, "D:/code/vaspilot-skill")

from skill_package.remote_executor import RemoteExecutor

config = {
    "host": "cancon.hpccube.com",
    "username": "wenliyang",
    "port": 65023,
    "key_path": "D:/code/wenliyang_cancon.hpccube.com_RsaKeyExpireTime_2026-05-25_16-04-32.txt"
}

print("Testing SSH connection...")
print(f"Host: {config['host']}:{config['port']}")
print(f"User: {config['username']}")
print()

executor = RemoteExecutor(
    host=config["host"],
    username=config["username"],
    port=config["port"],
    key_path=config["key_path"]
)

if executor.connect():
    print("[OK] SSH connection successful!\n")

    print("=== System Info ===")
    result = executor.execute_command("hostname && pwd")
    print(result["stdout"])
    print()

    print("=== Home Directory ===")
    result = executor.execute_command("ls -la ~ | head -30")
    print(result["stdout"])
    print()

    print("=== Check for VASP related files ===")
    result = executor.execute_command("ls -la ~/*vasp* ~/vasp* 2>/dev/null || echo 'No vasp files in home'")
    print(result["stdout"])
    print()

    print("=== Search POTCAR in home ===")
    result = executor.execute_command("find ~ -name 'POTCAR' -type f 2>/dev/null | head -5")
    print(result["stdout"] or "No POTCAR found in home")
    print()

    print("=== Search potpaw directories ===")
    result = executor.execute_command("find ~ -type d -name 'potpaw*' 2>/dev/null | head -5")
    print(result["stdout"] or "No potpaw dirs in home")
    result = executor.execute_command("find ~ -type d -name '*PBE*' 2>/dev/null | head -5")
    print(result["stdout"] or "No PBE dirs in home")
    print()

    print("=== Check software directory ===")
    result = executor.execute_command("ls -la ~/software/ 2>/dev/null || echo 'No software dir'")
    print(result["stdout"])
    print()

    print("=== Search for vasp executable ===")
    result = executor.execute_command("which vasp_std 2>/dev/null || find ~ -name 'vasp_std' -type f 2>/dev/null | head -3")
    print(result["stdout"] or "vasp_std not found")
    print()

    print("=== Check module system ===")
    result = executor.execute_command("module avail 2>&1 | grep -i vasp || echo 'No VASP modules'")
    print(result["stdout"] or result["stderr"])
    print()

    print("=== Check Slurm partitions ===")
    result = executor.execute_command("sinfo -s")
    print(result["stdout"])

    executor.disconnect()
    print("\n[OK] Connection closed")
else:
    print("[FAIL] SSH connection failed!")
