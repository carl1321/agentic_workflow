"""
Test SSH connection to HPC cluster
"""

import sys
sys.path.insert(0, "D:/code/vaspilot-skill")

from skill_package.remote_executor import RemoteExecutor

# SSH配置
config = {
    "host": "cancon.hpccube.com",
    "username": "acndczol6t",
    "port": 65023,
    "key_path": "D:/code/acndczol6t_cancon.hpccube.com_RsaKeyExpireTime_2026-05-25_15-56-33.txt"
}

print("Testing SSH connection...")
print(f"Host: {config['host']}:{config['port']}")
print(f"User: {config['username']}")
print(f"Key: {config['key_path']}")
print()

executor = RemoteExecutor(
    host=config["host"],
    username=config["username"],
    port=config["port"],
    key_path=config["key_path"]
)

if executor.connect():
    print("[OK] SSH connection successful!")
    print()

    # 测试基本命令
    print("=== System Info ===")
    result = executor.execute_command("hostname && uname -a")
    print(result["stdout"])
    print()

    # 检查home目录
    print("=== Home Directory ===")
    result = executor.execute_command("pwd && ls -la ~")
    print(result["stdout"])
    print()

    # 检查可用模块
    print("=== Available VASP Modules ===")
    result = executor.execute_command("module avail vasp 2>&1 || echo 'module command not available'")
    print(result["stdout"] or result["stderr"])
    print()

    # 检查Slurm
    print("=== Slurm Info ===")
    result = executor.execute_command("which sbatch && sinfo 2>&1 || echo 'Slurm not available'")
    print(result["stdout"] or result["stderr"])
    print()

    # 检查POTCAR路径
    print("=== Check Common POTCAR Paths ===")
    potcar_paths = [
        "/opt/vasp/potpaw_PBE",
        "/share/vasp/potpaw_PBE",
        "/public/software/vasp/potpaw_PBE",
        "$HOME/POTCAR"
    ]
    for path in potcar_paths:
        result = executor.execute_command(f"ls {path} 2>/dev/null | head -5")
        if result["stdout"]:
            print(f"Found: {path}")
            print(f"  {result['stdout'][:100]}...")
            break
    else:
        print("POTCAR path not found in common locations")

    executor.disconnect()
    print("\n[OK] Connection closed")
else:
    print("[FAIL] SSH connection failed!")
