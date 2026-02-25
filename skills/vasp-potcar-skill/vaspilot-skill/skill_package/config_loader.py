"""
Configuration loader with environment variable support
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
import yaml


def get_default_config_paths() -> list:
    """Get list of default config file locations"""
    paths = []

    # 1. Environment variable
    if os.environ.get("VASPILOT_CONFIG"):
        paths.append(Path(os.environ["VASPILOT_CONFIG"]))

    # 2. User home directory
    paths.append(Path.home() / ".vaspilot" / "config.yaml")

    # 3. Current directory
    paths.append(Path.cwd() / "vaspilot_config.yaml")

    # 4. Package configs directory
    package_dir = Path(__file__).parent.parent
    paths.append(package_dir / "configs" / "config.yaml")

    return paths


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from file with environment variable overrides

    Priority:
    1. Explicit config_path argument
    2. VASPILOT_CONFIG environment variable
    3. ~/.vaspilot/config.yaml
    4. ./vaspilot_config.yaml
    5. Package default config

    Environment variables can override any config value:
    - VASPILOT_SSH_HOST
    - VASPILOT_SSH_USERNAME
    - VASPILOT_SSH_PORT
    - VASPILOT_SSH_KEY_PATH
    - VASPILOT_HPC_WORK_DIR
    - VASPILOT_HPC_POTCAR_DIR
    - VASPILOT_HPC_VASP_BIN
    - VASPILOT_SLURM_PARTITION
    - VASPILOT_MP_API_KEY
    """
    config = {}

    # Find config file
    if config_path:
        config_file = Path(config_path)
    else:
        config_file = None
        for path in get_default_config_paths():
            if path.exists():
                config_file = path
                break

    # Load from file
    if config_file and config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}

    # Ensure nested dicts exist
    config.setdefault("ssh", {})
    config.setdefault("hpc", {})
    config.setdefault("slurm", {})

    # Environment variable overrides
    env_mappings = {
        "VASPILOT_SSH_HOST": ("ssh", "host"),
        "VASPILOT_SSH_USERNAME": ("ssh", "username"),
        "VASPILOT_SSH_PORT": ("ssh", "port", int),
        "VASPILOT_SSH_KEY_PATH": ("ssh", "key_path"),
        "VASPILOT_SSH_PASSWORD": ("ssh", "password"),
        "VASPILOT_HPC_WORK_DIR": ("hpc", "work_dir"),
        "VASPILOT_HPC_POTCAR_DIR": ("hpc", "potcar_dir"),
        "VASPILOT_HPC_VASP_BIN": ("hpc", "vasp_bin"),
        "VASPILOT_HPC_VASP_COMMAND": ("hpc", "vasp_command"),
        "VASPILOT_SLURM_PARTITION": ("slurm", "partition"),
        "VASPILOT_SLURM_NODES": ("slurm", "nodes", int),
        "VASPILOT_SLURM_NTASKS": ("slurm", "ntasks", int),
        "VASPILOT_SLURM_TIME": ("slurm", "time"),
        "VASPILOT_LOCAL_WORK_DIR": ("local_work_dir",),
        "VASPILOT_MP_API_KEY": ("mp_api_key",),
        "VASPILOT_POTCAR_METHOD": ("potcar_method",),
        "VASPILOT_POTCAR_SKILL_PATH": ("potcar_skill_path",),
    }

    for env_var, mapping in env_mappings.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Handle type conversion
            if len(mapping) == 3:
                section, key, converter = mapping
                value = converter(value)
            elif len(mapping) == 2:
                section, key = mapping
            else:
                # Top-level key
                config[mapping[0]] = value
                continue

            config[section][key] = value

    # Expand ~ in paths
    if config["ssh"].get("key_path"):
        config["ssh"]["key_path"] = os.path.expanduser(config["ssh"]["key_path"])

    if config.get("local_work_dir"):
        config["local_work_dir"] = os.path.expanduser(config["local_work_dir"])

    return config


def validate_config(config: Dict[str, Any]) -> list:
    """
    Validate configuration and return list of errors
    """
    errors = []

    # Required SSH settings
    if not config.get("ssh", {}).get("host"):
        errors.append("Missing ssh.host")
    if not config.get("ssh", {}).get("username"):
        errors.append("Missing ssh.username")

    # Either key_path or password required
    ssh = config.get("ssh", {})
    if not ssh.get("key_path") and not ssh.get("password"):
        errors.append("Missing ssh.key_path or ssh.password")

    # Check key file exists
    if ssh.get("key_path"):
        key_path = Path(ssh["key_path"])
        if not key_path.exists():
            errors.append(f"SSH key file not found: {key_path}")

    # Required HPC settings
    if not config.get("hpc", {}).get("work_dir"):
        errors.append("Missing hpc.work_dir")
    if not config.get("hpc", {}).get("potcar_dir"):
        errors.append("Missing hpc.potcar_dir")

    return errors


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).parent.parent


def get_potcar_skill_path() -> Optional[Path]:
    """Auto-detect vasp-potcar-skill path"""
    # Check common locations
    candidates = [
        Path(__file__).parent.parent.parent / "vasp-potcar-skill",
        Path.home() / "vasp-potcar-skill",
        Path.cwd() / "vasp-potcar-skill",
    ]

    # Check environment variable
    if os.environ.get("VASP_POTCAR_SKILL_PATH"):
        candidates.insert(0, Path(os.environ["VASP_POTCAR_SKILL_PATH"]))

    for path in candidates:
        skill_script = path / ".claude" / "commands" / "potcar_skill.py"
        if skill_script.exists():
            return skill_script

    return None
