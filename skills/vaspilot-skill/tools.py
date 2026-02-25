# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
VASPilot skill tools for the full-flow UI.
Exposes create_structure, analyze_structure, generate_inputs as LangChain tools
with JSON-serializable args and return values (POSCAR passed as string).
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Tools run in the app process where skill dir is not on sys.path; add it so "from skill_package" works.
_SKILL_DIR = Path(__file__).resolve().parent


def _ensure_skill_path() -> None:
    if str(_SKILL_DIR) not in sys.path:
        sys.path.insert(0, str(_SKILL_DIR))


def _get_potcar_dir() -> Optional[str]:
    """Get potcar_dir from conf.yaml or env. Used by generate_inputs."""
    try:
        from src.config.loader import load_yaml_config
        config = load_yaml_config("conf.yaml") or {}
        vw = config.get("VASP_WORKFLOW") or {}
        if isinstance(vw, dict) and vw.get("potcar_dir"):
            return str(vw.get("potcar_dir")).strip()
        hpc = config.get("hpc") or {}
        if isinstance(hpc, dict) and hpc.get("potcar_dir"):
            return str(hpc.get("potcar_dir")).strip()
    except Exception as e:
        logger.debug("Could not load potcar_dir from config: %s", e)
    return os.environ.get("VASPILOT_HPC_POTCAR_DIR") or os.environ.get("VASP_PP_PATH") or None


@tool("vaspilot_create_structure", return_direct=False)
def vaspilot_create_structure(
    lattice_params: Dict[str, float],
    species: List[str],
    coords: List[List[float]],
    coords_are_cartesian: bool = False,
) -> str:
    """
    Create a crystal structure and return POSCAR string plus analysis.

    Args:
        lattice_params: Dict with a, b, c (angstrom) and optional alpha, beta, gamma (degrees). E.g. {"a": 5.43, "b": 5.43, "c": 5.43, "alpha": 90, "beta": 90, "gamma": 90}.
        species: List of element symbols, e.g. ["Si", "Si", "Si", "Si", "Si", "Si", "Si", "Si"].
        coords: List of fractional (or Cartesian) coordinates, e.g. [[0,0,0], [0.25,0.25,0.25], ...].
        coords_are_cartesian: If True, coords are Cartesian; otherwise fractional.

    Returns:
        JSON string with keys: poscar_content (str), analysis (dict with formula, space_group, lattice, etc.).
    """
    _ensure_skill_path()
    try:
        from skill_package.structure_tools import StructureTools
        from pymatgen.io.vasp import Poscar
        st = StructureTools()
        structure = st.create_structure(
            lattice_params=lattice_params,
            species=species,
            coords=coords,
            coords_are_cartesian=coords_are_cartesian,
        )
        poscar = Poscar(structure)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vasp", delete=False) as f:
            poscar.write_file(f.name)
            with open(f.name, "r", encoding="utf-8") as rf:
                poscar_content = rf.read()
            os.unlink(f.name)
        analysis = st.analyze_structure(structure)
        return json.dumps({
            "poscar_content": poscar_content,
            "analysis": analysis,
        }, ensure_ascii=False)
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("vaspilot_create_structure failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_load_structure", return_direct=False)
def vaspilot_load_structure(file_content: str, filename: str) -> str:
    """
    Load a structure from uploaded file content (POSCAR, CIF, etc.) and return POSCAR string plus analysis.

    Args:
        file_content: Full file content as string (UTF-8).
        filename: Original filename, used to detect format (e.g. POSCAR, *.vasp, *.cif).

    Returns:
        JSON string with keys: poscar_content (str), analysis (dict). On error: error (str).
    """
    _ensure_skill_path()
    if not file_content or not file_content.strip():
        return json.dumps({"error": "文件内容为空"}, ensure_ascii=False)
    name_lower = (filename or "").lower().strip()
    suffix = ".cif" if name_lower.endswith(".cif") else ".vasp"
    try:
        from pymatgen.core import Structure as _Structure
        from skill_package.structure_tools import StructureTools
        from pymatgen.io.vasp import Poscar
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
            f.write(file_content)
            tmp_path = f.name
        try:
            structure = _Structure.from_file(tmp_path)
            st = StructureTools()
            analysis = st.analyze_structure(structure)
            poscar = Poscar(structure)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".vasp", delete=False) as p:
                poscar.write_file(p.name)
                with open(p.name, "r", encoding="utf-8") as rf:
                    poscar_content = rf.read()
                os.unlink(p.name)
            return json.dumps({
                "poscar_content": poscar_content,
                "analysis": analysis,
            }, ensure_ascii=False)
        finally:
            os.unlink(tmp_path)
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("vaspilot_load_structure failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_analyze_structure", return_direct=False)
def vaspilot_analyze_structure(poscar_content: str) -> str:
    """
    Analyze a crystal structure given its POSCAR content.

    Args:
        poscar_content: Full POSCAR file content as string.

    Returns:
        JSON string with formula, num_atoms, space_group, lattice, elements, density.
    """
    _ensure_skill_path()
    try:
        from pymatgen.core import Structure as _Structure
        from skill_package.structure_tools import StructureTools
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vasp", delete=False) as f:
            f.write(poscar_content)
            tmp_path = f.name
        try:
            structure = _Structure.from_file(tmp_path)
            st = StructureTools()
            analysis = st.analyze_structure(structure)
            return json.dumps(analysis, ensure_ascii=False)
        finally:
            os.unlink(tmp_path)
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("vaspilot_analyze_structure failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_generate_inputs", return_direct=False)
def vaspilot_generate_inputs(
    poscar_content: str,
    calc_type: str,
    output_dir: Optional[str] = None,
    incar_params: Optional[Dict[str, Any]] = None,
    kpoints_density: int = 40,
    job_name: str = "vasp_job",
) -> str:
    """
    Generate VASP input files (INCAR, KPOINTS, POSCAR, gen_potcar.sh, submit.sh) from POSCAR content.

    Args:
        poscar_content: Full POSCAR file content as string.
        calc_type: One of "relaxation", "scf", "band", "dos".
        output_dir: Optional; if not set, a temporary directory is used.
        incar_params: Optional dict of INCAR overrides, e.g. {"ENCUT": 400}.
        kpoints_density: K-points density (default 40).
        job_name: Job name for the Slurm script (default "vasp_job").

    Returns:
        JSON string with keys: files (dict of filename -> content), paths (dict of filename -> path),
        potcar_info (optional). POTCAR must be generated on HPC by running gen_potcar.sh.
    """
    if calc_type not in ("relaxation", "scf", "band", "dos"):
        return json.dumps({"error": f"Invalid calc_type: {calc_type}. Use relaxation, scf, band, or dos."}, ensure_ascii=False)

    _ensure_skill_path()
    try:
        from pymatgen.core import Structure as _Structure
        from skill_package.vasp_generator import VASPInputGenerator
        potcar_dir = _get_potcar_dir()
        generator = VASPInputGenerator(potcar_dir=potcar_dir)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vasp", delete=False) as f:
            f.write(poscar_content)
            poscar_tmp = f.name
        try:
            structure = _Structure.from_file(poscar_tmp)
        finally:
            os.unlink(poscar_tmp)

        use_tmp = not output_dir or not output_dir.strip()
        if use_tmp:
            output_dir = tempfile.mkdtemp(prefix="vaspilot_inputs_")

        written = generator.write_inputs(
            structure=structure,
            output_dir=output_dir,
            calc_type=calc_type,
            incar_params=incar_params,
            kpoints_density=kpoints_density,
            write_potcar_script=True,
            potcar_dir=potcar_dir,
        )

        files_content: Dict[str, str] = {}
        paths_out: Dict[str, str] = {}
        potcar_info: Optional[Dict[str, Any]] = None

        for key, value in written.items():
            if key == "potcar_info":
                potcar_info = value
                continue
            if isinstance(value, str) and os.path.isfile(value):
                paths_out[key] = value
                with open(value, "r", encoding="utf-8", errors="replace") as fp:
                    files_content[key] = fp.read()

        # 从 VASPilot 配置读取 Slurm/HPC 参数，避免 partition 等与集群不一致
        slurm_partition = "normal"
        slurm_nodes = 1
        slurm_ntasks = 48
        slurm_time = "24:00:00"
        vasp_bin = None
        vasp_command = "vasp_std"
        modules = None
        run_style = "mpirun"
        try:
            from skill_package.config_loader import load_config
            cfg = load_config()
            slurm = cfg.get("slurm") or {}
            hpc = cfg.get("hpc") or {}
            p = slurm.get("partition") or slurm_partition
            slurm_partition = (str(p).strip() or "normal") if (p is not None and str(p).strip()) else (slurm_partition or "normal")
            slurm_nodes = int(slurm.get("nodes", slurm_nodes))
            slurm_ntasks = int(slurm.get("ntasks", slurm_ntasks))
            slurm_time = str(slurm.get("time", slurm_time))
            vasp_bin = hpc.get("vasp_bin")
            vasp_command = str(hpc.get("vasp_command", vasp_command))
            if hpc.get("modules") is not None:
                mods = hpc.get("modules")
                modules = mods if isinstance(mods, list) else [str(mods)]
            elif hpc.get("module"):
                modules = [str(hpc.get("module"))]
            if hpc.get("run_style"):
                run_style = str(hpc.get("run_style")).strip()
        except Exception:
            pass

        slurm_script = generator.generate_slurm_script(
            job_name=job_name,
            nodes=slurm_nodes,
            ntasks=slurm_ntasks,
            partition=slurm_partition,
            time_limit=slurm_time,
            vasp_bin=vasp_bin,
            vasp_command=vasp_command,
            potcar_dir=potcar_dir,
            gen_potcar=True,
            modules=modules,
            run_style=run_style,
            calc_type=calc_type,
        )
        submit_path = os.path.join(output_dir, "submit.sh")
        with open(submit_path, "w", newline="\n") as f:
            f.write(slurm_script)
        files_content["submit.sh"] = slurm_script
        paths_out["submit.sh"] = submit_path

        result = {"files": files_content, "paths": paths_out}
        if potcar_info is not None:
            result["potcar_info"] = potcar_info
        result["note"] = "POTCAR must be generated on HPC by running gen_potcar.sh in the job directory."
        return json.dumps(result, ensure_ascii=False)
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("vaspilot_generate_inputs failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_get_hpc_config", return_direct=False)
def vaspilot_get_hpc_config() -> str:
    """
    Get HPC/SSH connection config from VASPilot skill (configs/config.yaml, ~/.vaspilot/config.yaml, or env)
    and optional project conf.yaml VASP_WORKFLOW.ssh / VASP_WORKFLOW.hpc.
    Returns host, username, port, work_dir, key_path; password is never returned, only has_password flag.
    """
    _ensure_skill_path()
    try:
        from skill_package.config_loader import load_config
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}"}, ensure_ascii=False)

    try:
        config = load_config()
        ssh = config.get("ssh") or {}
        hpc = config.get("hpc") or {}

        # Optional: overlay from project conf.yaml VASP_WORKFLOW
        try:
            from src.config.loader import load_yaml_config
            proj = load_yaml_config("conf.yaml") or {}
            vw = proj.get("VASP_WORKFLOW") or {}
            if isinstance(vw, dict):
                if vw.get("ssh"):
                    ssh = {**ssh, **vw["ssh"]}
                if vw.get("hpc"):
                    hpc = {**hpc, **vw["hpc"]}
        except Exception:
            pass

        port = ssh.get("port", 22)
        if port is None:
            port = 22
        return json.dumps({
            "host": (ssh.get("host") or "").strip(),
            "username": (ssh.get("username") or "").strip(),
            "port": int(port) if port else 22,
            "work_dir": (hpc.get("work_dir") or "").strip(),
            "key_path": (ssh.get("key_path") or "").strip(),
            "has_password": bool(ssh.get("password")),
            "source": "VASPilot 配置（config.yaml 或环境变量）",
        }, ensure_ascii=False)
    except Exception as e:
        logger.exception("vaspilot_get_hpc_config failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_submit_to_hpc", return_direct=False)
def vaspilot_submit_to_hpc(
    files: Dict[str, str],
    host: str,
    username: str,
    remote_work_dir: str,
    job_dir_name: Optional[str] = None,
    port: int = 22,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """
    Upload VASP input files to HPC and submit the job via Slurm (sbatch).

    Args:
        files: Dict of filename -> content, e.g. {"INCAR": "...", "KPOINTS": "...", "POSCAR": "...", "gen_potcar.sh": "...", "submit.sh": "..."}.
        host: HPC SSH host (e.g. login.cluster.edu).
        username: SSH username.
        remote_work_dir: Remote base directory (e.g. /home/user/vasp_runs). Job files will be uploaded to remote_work_dir/job_dir_name.
        job_dir_name: Subdirectory name under remote_work_dir (default: vasp_job_<timestamp>).
        port: SSH port (default 22).
        key_path: Path to SSH private key (optional; use password if not set).
        password: SSH password (optional; prefer key_path for security).

    Returns:
        JSON with success, job_id, message, remote_dir; or error.
    """
    if not files or "submit.sh" not in files:
        return json.dumps({"error": "files 必须包含 submit.sh 及 INCAR、KPOINTS、POSCAR 等"}, ensure_ascii=False)
    if not host or not username:
        return json.dumps({"error": "host 与 username 必填"}, ensure_ascii=False)
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一"}, ensure_ascii=False)

    _ensure_skill_path()
    try:
        from skill_package.remote_executor import RemoteExecutor
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}. Install paramiko: pip install paramiko"}, ensure_ascii=False)

    # 当前端传 __use_config__ 或未传密码时，从 VASPilot 配置读取密码
    if (password == "__use_config__" or (not password or (isinstance(password, str) and not password.strip()))):
        try:
            from skill_package.config_loader import load_config
            cfg = load_config()
            password = (cfg.get("ssh") or {}).get("password") or None
        except Exception:
            password = None
    else:
        password = password.strip() if isinstance(password, str) else password
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一（配置中未找到密码）"}, ensure_ascii=False)

    import time
    job_dir_name = job_dir_name or f"vasp_job_{time.strftime('%Y%m%d_%H%M%S')}"
    remote_dir = f"{remote_work_dir.rstrip('/')}/{job_dir_name}"

    tmp_dir = tempfile.mkdtemp(prefix="vaspilot_submit_")
    try:
        for name, content in files.items():
            if not name or name.startswith(".") or "/" in name or "\\" in name:
                continue
            path = os.path.join(tmp_dir, name)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)

        executor = RemoteExecutor(
            host=host,
            username=username,
            port=port,
            key_path=key_path.strip() if key_path else None,
            password=password or None,
        )
        if not executor.connect():
            return json.dumps({"error": "SSH 连接失败，请检查 host/username/端口/密钥或密码"}, ensure_ascii=False)

        try:
            # 创建远程目录并上传
            executor.execute_command(f"mkdir -p {remote_dir}")
            upload_result = executor.upload_directory(tmp_dir, remote_dir)
            if not upload_result.get("success") and upload_result.get("failed"):
                return json.dumps({
                    "error": "部分文件上传失败",
                    "failed": upload_result.get("failed", []),
                }, ensure_ascii=False)

            # 提交作业（submit.sh 内通常会先执行 gen_potcar.sh 再运行 VASP）
            result = executor.submit_slurm_job(remote_dir, "submit.sh")
            if result.get("success") and result.get("job_id"):
                return json.dumps({
                    "success": True,
                    "job_id": result["job_id"],
                    "message": result.get("message", ""),
                    "remote_dir": remote_dir,
                }, ensure_ascii=False)
            return json.dumps({
                "success": False,
                "error": result.get("error", "sbatch 提交失败"),
                "stderr": result.get("error"),
            }, ensure_ascii=False)
        finally:
            executor.disconnect()
    except Exception as e:
        logger.exception("vaspilot_submit_to_hpc failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@tool("vaspilot_job_status", return_direct=False)
def vaspilot_job_status(
    job_id: str,
    host: str,
    username: str,
    port: int = 22,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """
    Query Slurm job status on HPC (squeue/sacct).

    Args:
        job_id: Slurm job ID (e.g. 12345).
        host: HPC SSH host.
        username: SSH username.
        port: SSH port (default 22).
        key_path: Path to SSH private key (optional).
        password: SSH password (optional).

    Returns:
        JSON with job_id, status, node, time_used, exit_code.
    """
    if not job_id or not host or not username:
        return json.dumps({"error": "job_id、host、username 必填"}, ensure_ascii=False)
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一"}, ensure_ascii=False)

    _ensure_skill_path()
    try:
        from skill_package.remote_executor import RemoteExecutor
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}. Install paramiko: pip install paramiko"}, ensure_ascii=False)

    if password == "__use_config__" or (isinstance(password, str) and not password.strip()):
        try:
            from skill_package.config_loader import load_config
            cfg = load_config()
            password = (cfg.get("ssh") or {}).get("password") or None
        except Exception:
            password = None
    else:
        password = password.strip() if isinstance(password, str) else password
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一（配置中未找到密码）"}, ensure_ascii=False)

    try:
        executor = RemoteExecutor(
            host=host,
            username=username,
            port=port,
            key_path=key_path.strip() if key_path else None,
            password=password or None,
        )
        if not executor.connect():
            return json.dumps({"error": "SSH 连接失败"}, ensure_ascii=False)
        try:
            status = executor.check_job_status(job_id)
            return json.dumps({
                "job_id": status.job_id,
                "status": status.status,
                "node": status.node,
                "time_used": status.time_used,
                "exit_code": status.exit_code,
            }, ensure_ascii=False)
        finally:
            executor.disconnect()
    except Exception as e:
        logger.exception("vaspilot_job_status failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_fetch_job_logs", return_direct=False)
def vaspilot_fetch_job_logs(
    job_id: str,
    remote_dir: str,
    host: str,
    username: str,
    port: int = 22,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """
    Fetch job error/output logs from HPC remote directory to diagnose failed jobs.
    Reads vasp_<job_id>.err (stderr), vasp_<job_id>.out (stdout), and last 80 lines of OUTCAR if present.

    Args:
        job_id: Slurm job ID (e.g. 108715963).
        remote_dir: Remote job directory (e.g. /public/home/user/vaspilot/vasp_job_20260225_112017).
        host: HPC SSH host.
        username: SSH username.
        port: SSH port (default 22).
        key_path: SSH private key path (optional).
        password: SSH password (optional).

    Returns:
        JSON with stderr, stdout, outcar_tail; or error.
    """
    if not job_id or not remote_dir or not host or not username:
        return json.dumps({"error": "job_id、remote_dir、host、username 必填"}, ensure_ascii=False)
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一"}, ensure_ascii=False)

    _ensure_skill_path()
    try:
        from skill_package.remote_executor import RemoteExecutor
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}. Install paramiko."}, ensure_ascii=False)

    if password == "__use_config__" or (isinstance(password, str) and not password.strip()):
        try:
            from skill_package.config_loader import load_config
            cfg = load_config()
            password = (cfg.get("ssh") or {}).get("password") or None
        except Exception:
            password = None
    else:
        password = password.strip() if isinstance(password, str) else password
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一（配置中未找到密码）"}, ensure_ascii=False)

    out = {"stderr": "", "stdout": "", "outcar_tail": "", "vasp_scf_log": "", "vasp_band_log": ""}
    try:
        executor = RemoteExecutor(
            host=host,
            username=username,
            port=port,
            key_path=key_path.strip() if key_path else None,
            password=password or None,
        )
        if not executor.connect():
            return json.dumps({"error": "SSH 连接失败"}, ensure_ascii=False)
        try:
            rd = remote_dir.rstrip("/")
            err_file = f"{rd}/vasp_{job_id}.err"
            out_file = f"{rd}/vasp_{job_id}.out"
            r = executor.execute_command(f"cat '{err_file}' 2>/dev/null || echo ''")
            out["stderr"] = (r.get("stdout") or "").strip() or "(文件不存在或为空)"
            r = executor.execute_command(f"cat '{out_file}' 2>/dev/null || echo ''")
            out["stdout"] = (r.get("stdout") or "").strip() or "(文件不存在或为空)"
            r = executor.execute_command(f"tail -n 80 '{rd}/OUTCAR' 2>/dev/null || echo ''")
            out["outcar_tail"] = (r.get("stdout") or "").strip() or "(文件不存在或为空)"
            # 能带两段式：拉取 vasp_scf.log / vasp_band.log 便于排查 VASP 未产生 OUTCAR 的原因
            r = executor.execute_command(f"tail -n 150 '{rd}/vasp_scf.log' 2>/dev/null || echo ''")
            out["vasp_scf_log"] = (r.get("stdout") or "").strip() or "(文件不存在或为空)"
            r = executor.execute_command(f"tail -n 150 '{rd}/vasp_band.log' 2>/dev/null || echo ''")
            out["vasp_band_log"] = (r.get("stdout") or "").strip() or "(文件不存在或为空)"
            return json.dumps(out, ensure_ascii=False)
        finally:
            executor.disconnect()
    except Exception as e:
        logger.exception("vaspilot_fetch_job_logs failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# 从 HPC 下载单文件时允许的最大大小（字节），避免内存/JSON 过大
_REMOTE_FILE_MAX_SIZE = 80 * 1024 * 1024  # 80 MB


@tool("vaspilot_download_remote_file", return_direct=False)
def vaspilot_download_remote_file(
    remote_dir: str,
    filename: str,
    host: str,
    username: str,
    port: int = 22,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """
    Download a single file from HPC remote directory (e.g. vasprun.xml, KPOINTS).
    Returns file content as string for text files; used by frontend to offer "从 HPC 下载" and then save or use for band plot.

    Args:
        remote_dir: Remote job directory (e.g. /public/home/user/vaspilot/vasp_job_xxx).
        filename: File name (e.g. vasprun.xml, KPOINTS).
        host: HPC SSH host.
        username: SSH username.
        port: SSH port (default 22).
        key_path: SSH private key path (optional).
        password: SSH password (optional).

    Returns:
        JSON with success, content, filename; or error. Content is empty if file missing or size > 80MB.
    """
    if not remote_dir or not filename or not host or not username:
        return json.dumps({"error": "remote_dir、filename、host、username 必填"}, ensure_ascii=False)
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一"}, ensure_ascii=False)
    # 只允许下载常见文本文件名，避免路径穿越
    if "/" in filename or "\\" in filename or filename not in ("vasprun.xml", "KPOINTS", "OUTCAR", "INCAR", "POSCAR"):
        return json.dumps({"error": "仅支持下载 vasprun.xml、KPOINTS、OUTCAR、INCAR、POSCAR"}, ensure_ascii=False)

    _ensure_skill_path()
    try:
        from skill_package.remote_executor import RemoteExecutor
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}. Install paramiko."}, ensure_ascii=False)

    if password == "__use_config__" or (isinstance(password, str) and not password.strip()):
        try:
            from skill_package.config_loader import load_config
            cfg = load_config()
            password = (cfg.get("ssh") or {}).get("password") or None
        except Exception:
            password = None
    else:
        password = password.strip() if isinstance(password, str) else password
    if not key_path and not password:
        return json.dumps({"error": "请提供 key_path 或 password 之一（配置中未找到密码）"}, ensure_ascii=False)

    try:
        executor = RemoteExecutor(
            host=host,
            username=username,
            port=port,
            key_path=key_path.strip() if key_path else None,
            password=password or None,
        )
        if not executor.connect():
            return json.dumps({"error": "SSH 连接失败"}, ensure_ascii=False)
        try:
            rd = remote_dir.rstrip("/")
            remote_path = f"{rd}/{filename}"
            # 能带两段式：vasprun.xml/KPOINTS 可能在 job 根目录（最后一步覆盖）或 band_results/ 下
            if not executor.file_exists(remote_path) and filename in ("vasprun.xml", "KPOINTS"):
                alt_path = f"{rd}/band_results/{filename}"
                if executor.file_exists(alt_path):
                    remote_path = alt_path
            if not executor.file_exists(remote_path):
                return json.dumps({
                    "error": f"远程文件不存在: {remote_path}。能带任务请确认 SCF 与 Band 均已跑完；或该作业目录与当前作业 ID 一致。",
                    "success": False,
                }, ensure_ascii=False)
            local_tmp = tempfile.mktemp(suffix=filename)
            try:
                if not executor.download_file(remote_path, local_tmp):
                    return json.dumps({"error": "下载失败"}, ensure_ascii=False)
                size = os.path.getsize(local_tmp)
                if size > _REMOTE_FILE_MAX_SIZE:
                    return json.dumps({
                        "error": f"文件超过 {_REMOTE_FILE_MAX_SIZE // (1024*1024)}MB，请用 scp 从 {remote_path} 下载",
                        "success": False,
                    }, ensure_ascii=False)
                with open(local_tmp, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return json.dumps({"success": True, "content": content, "filename": filename}, ensure_ascii=False)
            finally:
                try:
                    os.unlink(local_tmp)
                except Exception:
                    pass
        finally:
            executor.disconnect()
    except Exception as e:
        logger.exception("vaspilot_download_remote_file failed")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("vaspilot_plot_band_structure", return_direct=False)
def vaspilot_plot_band_structure(
    vasprun_xml_content: str,
    kpoints_content: Optional[str] = None,
) -> str:
    """
    Generate band structure plot from vasprun.xml content (and optional KPOINTS for line mode).
    Used when job type is band: after HPC calculation, upload vasprun.xml to get the band figure.

    Args:
        vasprun_xml_content: Full content of vasprun.xml as string.
        kpoints_content: Optional content of KPOINTS file (for line-mode k-path).

    Returns:
        JSON with image_base64 (PNG) or error.
    """
    content = (vasprun_xml_content or "").strip()
    if not content:
        return json.dumps({"error": "vasprun_xml_content 不能为空"}, ensure_ascii=False)
    if not content.startswith("<?xml") and not content.startswith("<"):
        return json.dumps({"error": "vasprun.xml 内容不是合法 XML 开头，可能被截断或损坏"}, ensure_ascii=False)
    if len(content) < 5000:
        return json.dumps({"error": "vasprun.xml 过短，可能被截断。完整能带 vasprun 通常数百 KB，请确认从 HPC 下载时未超请求大小限制。"}, ensure_ascii=False)
    _ensure_skill_path()
    import base64
    try:
        from skill_package.visualizer import ResultVisualizer
    except ImportError as e:
        return json.dumps({"error": f"Missing dependency: {e}. Install pymatgen, matplotlib."}, ensure_ascii=False)
    tmp_dir = tempfile.mkdtemp(prefix="vaspilot_band_")
    try:
        vasprun_path = os.path.join(tmp_dir, "vasprun.xml")
        with open(vasprun_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
        kpoints_path = None
        if kpoints_content and kpoints_content.strip():
            kpoints_path = os.path.join(tmp_dir, "KPOINTS")
            with open(kpoints_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(kpoints_content)
        out_png = os.path.join(tmp_dir, "band_structure.png")
        viz = ResultVisualizer()
        viz.plot_band_structure(vasprun_path, kpoints_path=kpoints_path, output_path=out_png)
        if not os.path.isfile(out_png):
            return json.dumps({"error": "生成能带图失败（未生成图片文件）"}, ensure_ascii=False)
        with open(out_png, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return json.dumps({"success": True, "image_base64": b64}, ensure_ascii=False)
    except Exception as e:
        err_msg = str(e)
        if "no element found" in err_msg or "line" in err_msg and "column" in err_msg:
            return json.dumps({
                "error": "vasprun.xml 解析失败（可能文件被截断或损坏）。若从 HPC 下载后生成，vasprun 较大时请求可能被截断，请改用「本地上传」选择已保存到本机的 vasprun.xml 再点生成能带图。",
            }, ensure_ascii=False)
        logger.exception("vaspilot_plot_band_structure failed")
        return json.dumps({"error": err_msg}, ensure_ascii=False)
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def get_tools():
    """Return list of LangChain tools for the skill (used by tool_loader)."""
    return [
        vaspilot_create_structure,
        vaspilot_load_structure,
        vaspilot_analyze_structure,
        vaspilot_generate_inputs,
        vaspilot_get_hpc_config,
        vaspilot_submit_to_hpc,
        vaspilot_job_status,
        vaspilot_fetch_job_logs,
        vaspilot_download_remote_file,
        vaspilot_plot_band_structure,
    ]
