"""
VASP workflow orchestration
"""

import os
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from enum import Enum

from .remote_executor import RemoteExecutor, JobStatus
from .vasp_generator import VASPInputGenerator
from .structure_tools import StructureTools
from .result_parser import ResultParser

try:
    from pymatgen.core import Structure
    HAS_PYMATGEN = True
except ImportError:
    HAS_PYMATGEN = False


class CalcStatus(Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Calculation:
    """Single VASP calculation record"""
    calc_id: str
    calc_type: str
    local_dir: str
    remote_dir: str
    status: CalcStatus = CalcStatus.PENDING
    job_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    depends_on: Optional[str] = None  # calc_id of prerequisite


class VASPWorkflow:
    """
    High-level workflow manager for VASP calculations

    Orchestrates:
    - Structure preparation
    - Input generation
    - Remote execution
    - Result collection
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize workflow with configuration

        Args:
            config: Configuration dict with keys:
                - ssh: {host, username, port, key_path/password}
                - hpc: {work_dir, potcar_dir, vasp_module}
                - slurm: {partition, nodes, ntasks, time}
                - mp_api_key: (optional) Materials Project API key
                - local_work_dir: Local working directory
        """
        self.config = config

        # Initialize components
        self.executor = RemoteExecutor(
            host=config["ssh"]["host"],
            username=config["ssh"]["username"],
            port=config["ssh"].get("port", 22),
            key_path=config["ssh"].get("key_path"),
            password=config["ssh"].get("password")
        )

        self.generator = VASPInputGenerator(
            potcar_dir=config["hpc"].get("potcar_dir")
        )

        self.structure_tools = StructureTools(
            mp_api_key=config.get("mp_api_key")
        )

        self.parser = ResultParser()

        # Calculation tracking
        self.calculations: Dict[str, Calculation] = {}

        # Paths
        self.local_work_dir = Path(config.get("local_work_dir", "./vaspilot_work"))
        self.remote_work_dir = config["hpc"]["work_dir"]

        self.local_work_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        """Establish connection to HPC"""
        return self.executor.connect()

    def disconnect(self):
        """Close HPC connection"""
        self.executor.disconnect()

    def search_structure(self, formula: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search structures from Materials Project"""
        return self.structure_tools.search_materials_project(formula, max_results)

    def prepare_calculation(
        self,
        structure: Union[str, "Structure"],
        calc_type: str,
        calc_name: Optional[str] = None,
        incar_params: Optional[Dict[str, Any]] = None,
        depends_on: Optional[str] = None
    ) -> str:
        """
        Prepare a VASP calculation

        Args:
            structure: Structure file path or pymatgen Structure
            calc_type: "relaxation", "scf", "band", "dos"
            calc_name: Optional name for the calculation
            incar_params: Custom INCAR parameters
            depends_on: calc_id of prerequisite calculation

        Returns:
            calc_id for tracking
        """
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        # Generate unique ID
        calc_id = calc_name or f"{calc_type}_{uuid.uuid4().hex[:8]}"

        # Create local directory
        local_dir = self.local_work_dir / calc_id
        local_dir.mkdir(parents=True, exist_ok=True)

        # Generate input files
        self.generator.write_inputs(
            structure=structure,
            output_dir=str(local_dir),
            calc_type=calc_type,
            incar_params=incar_params
        )

        # Generate POTCAR script
        potcar_script = self.generator.generate_potcar_script(
            structure=structure,
            potcar_dir=self.config["hpc"].get("potcar_dir")
        )
        with open(local_dir / "gen_potcar.sh", "w") as f:
            f.write(potcar_script)

        # Generate Slurm script
        slurm_config = self.config.get("slurm", {})
        slurm_script = self.generator.generate_slurm_script(
            job_name=calc_id,
            nodes=slurm_config.get("nodes", 1),
            ntasks=slurm_config.get("ntasks", 32),
            partition=slurm_config.get("partition", "kshcnormal"),
            time_limit=slurm_config.get("time", "48:00:00"),
            vasp_bin=self.config["hpc"].get("vasp_bin"),
            vasp_command=self.config["hpc"].get("vasp_command", "vasp_std"),
            potcar_dir=self.config["hpc"].get("potcar_dir"),
            gen_potcar=True
        )
        with open(local_dir / "submit.sh", "w") as f:
            f.write(slurm_script)

        # Remote directory
        remote_dir = f"{self.remote_work_dir}/{calc_id}"

        # Create calculation record
        calc = Calculation(
            calc_id=calc_id,
            calc_type=calc_type,
            local_dir=str(local_dir),
            remote_dir=remote_dir,
            depends_on=depends_on
        )
        self.calculations[calc_id] = calc

        return calc_id

    def submit_calculation(self, calc_id: str) -> Dict[str, Any]:
        """
        Upload and submit a prepared calculation

        Returns:
            Submission result with job_id
        """
        calc = self.calculations.get(calc_id)
        if not calc:
            return {"success": False, "error": f"Calculation {calc_id} not found"}

        # Check dependency
        if calc.depends_on:
            dep = self.calculations.get(calc.depends_on)
            if dep and dep.status != CalcStatus.COMPLETED:
                return {"success": False, "error": f"Dependency {calc.depends_on} not completed"}

        try:
            # Upload files
            calc.status = CalcStatus.UPLOADING
            upload_result = self.executor.upload_directory(calc.local_dir, calc.remote_dir)

            if not upload_result["success"]:
                calc.status = CalcStatus.FAILED
                calc.error = f"Upload failed: {upload_result['failed']}"
                return {"success": False, "error": calc.error}

            # Submit job
            job_id = self.executor.submit_slurm_job(calc.remote_dir, "submit.sh")

            if job_id:
                calc.job_id = job_id
                calc.status = CalcStatus.SUBMITTED
                return {"success": True, "calc_id": calc_id, "job_id": job_id}
            else:
                calc.status = CalcStatus.FAILED
                calc.error = "Job submission failed"
                return {"success": False, "error": calc.error}

        except Exception as e:
            calc.status = CalcStatus.FAILED
            calc.error = str(e)
            return {"success": False, "error": str(e)}

    def check_status(self, calc_id: str) -> Dict[str, Any]:
        """Check calculation status"""
        calc = self.calculations.get(calc_id)
        if not calc:
            return {"error": f"Calculation {calc_id} not found"}

        if calc.job_id:
            job_status = self.executor.check_job_status(calc.job_id)

            # Update calc status based on job status
            status_map = {
                "PENDING": CalcStatus.SUBMITTED,
                "RUNNING": CalcStatus.RUNNING,
                "COMPLETED": CalcStatus.COMPLETED,
                "FAILED": CalcStatus.FAILED,
                "CANCELLED": CalcStatus.CANCELLED
            }
            calc.status = status_map.get(job_status.status, calc.status)

            return {
                "calc_id": calc_id,
                "calc_type": calc.calc_type,
                "status": calc.status.value,
                "job_id": calc.job_id,
                "job_status": job_status.status
            }

        return {
            "calc_id": calc_id,
            "status": calc.status.value
        }

    def download_results(self, calc_id: str) -> Dict[str, Any]:
        """Download calculation results"""
        calc = self.calculations.get(calc_id)
        if not calc:
            return {"success": False, "error": f"Calculation {calc_id} not found"}

        try:
            # Download key result files
            result_files = ["vasprun.xml", "OUTCAR", "CONTCAR", "OSZICAR", "EIGENVAL", "DOSCAR"]

            downloaded = []
            for fname in result_files:
                remote_path = f"{calc.remote_dir}/{fname}"
                local_path = f"{calc.local_dir}/{fname}"

                if self.executor.file_exists(remote_path):
                    if self.executor.download_file(remote_path, local_path):
                        downloaded.append(fname)

            return {
                "success": True,
                "calc_id": calc_id,
                "downloaded": downloaded,
                "local_dir": calc.local_dir
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def parse_results(self, calc_id: str) -> Dict[str, Any]:
        """Parse downloaded results"""
        calc = self.calculations.get(calc_id)
        if not calc:
            return {"error": f"Calculation {calc_id} not found"}

        result = self.parser.get_summary(calc.local_dir, calc.calc_type)
        calc.result = result
        return result

    def run_calculation(
        self,
        structure: Union[str, "Structure"],
        calc_type: str,
        calc_name: Optional[str] = None,
        incar_params: Optional[Dict[str, Any]] = None,
        wait: bool = True,
        poll_interval: int = 60,
        timeout: int = 86400
    ) -> Dict[str, Any]:
        """
        Complete workflow: prepare, submit, wait, download, parse

        Args:
            structure: Structure input
            calc_type: Calculation type
            calc_name: Optional name
            incar_params: Custom INCAR params
            wait: Whether to wait for completion
            poll_interval: Status check interval (seconds)
            timeout: Maximum wait time (seconds)

        Returns:
            Calculation result
        """
        # Prepare
        calc_id = self.prepare_calculation(
            structure=structure,
            calc_type=calc_type,
            calc_name=calc_name,
            incar_params=incar_params
        )

        # Submit
        submit_result = self.submit_calculation(calc_id)
        if not submit_result["success"]:
            return submit_result

        if not wait:
            return {"success": True, "calc_id": calc_id, "status": "submitted"}

        # Wait for completion
        calc = self.calculations[calc_id]
        job_status = self.executor.wait_for_job(
            calc.job_id,
            poll_interval=poll_interval,
            timeout=timeout
        )

        if job_status.status != "COMPLETED":
            return {
                "success": False,
                "calc_id": calc_id,
                "status": job_status.status,
                "error": f"Job ended with status: {job_status.status}"
            }

        # Download and parse
        self.download_results(calc_id)
        result = self.parse_results(calc_id)

        return {
            "success": result.get("success", False),
            "calc_id": calc_id,
            "result": result
        }

    def run_workflow(
        self,
        structure: Union[str, "Structure"],
        workflow_type: str = "relax_scf_band",
        base_name: Optional[str] = None,
        incar_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Run multi-step workflow

        Args:
            structure: Initial structure
            workflow_type: "relax", "relax_scf", "relax_scf_band", "scf_band"
            base_name: Base name for calculations
            incar_overrides: Per-step INCAR overrides

        Returns:
            Workflow results
        """
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        base_name = base_name or f"workflow_{uuid.uuid4().hex[:6]}"
        incar_overrides = incar_overrides or {}
        results = {}

        steps = workflow_type.split("_")

        current_structure = structure
        prev_calc_id = None

        for step in steps:
            calc_type = "relaxation" if step == "relax" else step
            calc_name = f"{base_name}_{step}"

            # For SCF/band after relaxation, use relaxed structure
            if step in ["scf", "band", "dos"] and prev_calc_id:
                prev_result = results.get(prev_calc_id, {})
                if "final_structure" in prev_result.get("result", {}):
                    current_structure = prev_result["result"]["final_structure"]

            # Run calculation
            result = self.run_calculation(
                structure=current_structure,
                calc_type=calc_type,
                calc_name=calc_name,
                incar_params=incar_overrides.get(step)
            )

            results[calc_name] = result
            prev_calc_id = calc_name

            if not result.get("success"):
                break

        return {
            "workflow_type": workflow_type,
            "base_name": base_name,
            "results": results,
            "success": all(r.get("success") for r in results.values())
        }

    def get_all_status(self) -> List[Dict[str, Any]]:
        """Get status of all calculations"""
        statuses = []
        for calc_id, calc in self.calculations.items():
            statuses.append({
                "calc_id": calc_id,
                "calc_type": calc.calc_type,
                "status": calc.status.value,
                "job_id": calc.job_id
            })
        return statuses

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
