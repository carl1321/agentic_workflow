"""
High-throughput parallel workflow manager
"""

import os
import time
import uuid
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import threading

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
    PREPARING = "preparing"
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
    formula: str
    local_dir: str
    remote_dir: str
    status: CalcStatus = CalcStatus.PENDING
    job_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    depends_on: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class HighThroughputWorkflow:
    """
    High-throughput parallel workflow manager

    Features:
    - Parallel job submission
    - Concurrent status monitoring
    - Automatic result collection
    - Progress tracking and callbacks
    """

    def __init__(
        self,
        config: Dict[str, Any],
        max_concurrent_jobs: int = 10,
        max_workers: int = 4
    ):
        """
        Initialize high-throughput workflow

        Args:
            config: Configuration dict
            max_concurrent_jobs: Maximum jobs to have running simultaneously
            max_workers: Thread pool size for parallel operations
        """
        self.config = config
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_workers = max_workers

        # Initialize components
        self.executor = RemoteExecutor(
            host=config["ssh"]["host"],
            username=config["ssh"]["username"],
            port=config["ssh"].get("port", 22),
            key_path=config["ssh"].get("key_path"),
            password=config["ssh"].get("password")
        )

        self.generator = VASPInputGenerator(
            potcar_dir=config["hpc"].get("potcar_dir"),
            potcar_skill_path=config.get("potcar_skill_path"),
            use_potcar_skill=config.get("potcar_method") == "potcar_skill"
        )

        self.structure_tools = StructureTools(
            mp_api_key=config.get("mp_api_key")
        )

        self.parser = ResultParser()

        # Calculation tracking
        self.calculations: Dict[str, Calculation] = {}
        self._lock = threading.Lock()

        # Paths
        self.local_work_dir = Path(config.get("local_work_dir", "./vaspilot_work"))
        self.remote_work_dir = config["hpc"]["work_dir"]

        self.local_work_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self._on_status_change: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None

    def set_callbacks(
        self,
        on_status_change: Optional[Callable] = None,
        on_complete: Optional[Callable] = None
    ):
        """Set callback functions for progress tracking"""
        self._on_status_change = on_status_change
        self._on_complete = on_complete

    def connect(self) -> bool:
        """Establish connection to HPC"""
        return self.executor.connect()

    def disconnect(self):
        """Close HPC connection"""
        self.executor.disconnect()

    def _update_status(self, calc_id: str, status: CalcStatus, **kwargs):
        """Update calculation status with thread safety"""
        with self._lock:
            if calc_id in self.calculations:
                calc = self.calculations[calc_id]
                calc.status = status

                if status == CalcStatus.RUNNING and not calc.started_at:
                    calc.started_at = datetime.now().isoformat()
                elif status in [CalcStatus.COMPLETED, CalcStatus.FAILED]:
                    calc.completed_at = datetime.now().isoformat()

                for key, value in kwargs.items():
                    if hasattr(calc, key):
                        setattr(calc, key, value)

        if self._on_status_change:
            self._on_status_change(calc_id, status.value, kwargs)

    def prepare_batch(
        self,
        structures: List[Union[str, "Structure", Dict[str, Any]]],
        calc_type: str = "relaxation",
        name_prefix: str = "batch",
        incar_params: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Prepare a batch of calculations

        Args:
            structures: List of structures (paths, Structure objects, or MP search results)
            calc_type: Calculation type
            name_prefix: Prefix for calculation names
            incar_params: Custom INCAR parameters

        Returns:
            List of calc_ids
        """
        calc_ids = []

        for i, struct_input in enumerate(structures):
            # Handle different input types
            if isinstance(struct_input, str):
                structure = Structure.from_file(struct_input)
                formula = structure.composition.reduced_formula
            elif isinstance(struct_input, dict):
                # MP search result
                structure = struct_input.get("structure")
                formula = struct_input.get("formula", f"struct_{i}")
            else:
                structure = struct_input
                formula = structure.composition.reduced_formula

            calc_id = f"{name_prefix}_{formula}_{i:04d}"
            local_dir = self.local_work_dir / calc_id
            local_dir.mkdir(parents=True, exist_ok=True)

            # Generate input files
            self.generator.write_inputs(
                structure=structure,
                output_dir=str(local_dir),
                calc_type=calc_type,
                incar_params=incar_params,
                potcar_dir=self.config["hpc"].get("potcar_dir")
            )

            # Generate Slurm script
            slurm_config = self.config.get("slurm", {})
            slurm_script = self.generator.generate_slurm_script(
                job_name=calc_id[:15],  # Slurm job name limit
                nodes=slurm_config.get("nodes", 1),
                ntasks=slurm_config.get("ntasks", 32),
                partition=slurm_config.get("partition", "normal"),
                time_limit=slurm_config.get("time", "48:00:00"),
                vasp_bin=self.config["hpc"].get("vasp_bin"),
                vasp_command=self.config["hpc"].get("vasp_command", "vasp_std"),
                potcar_dir=self.config["hpc"].get("potcar_dir"),
                gen_potcar=True
            )

            with open(local_dir / "submit.sh", "w", newline='\n') as f:
                f.write(slurm_script)

            # Create calculation record
            remote_dir = f"{self.remote_work_dir}/{calc_id}"
            calc = Calculation(
                calc_id=calc_id,
                calc_type=calc_type,
                formula=formula,
                local_dir=str(local_dir),
                remote_dir=remote_dir
            )

            with self._lock:
                self.calculations[calc_id] = calc

            calc_ids.append(calc_id)

        return calc_ids

    def _submit_single(self, calc_id: str) -> Dict[str, Any]:
        """Submit a single calculation (for parallel execution)"""
        calc = self.calculations.get(calc_id)
        if not calc:
            return {"success": False, "error": f"Calculation {calc_id} not found"}

        try:
            self._update_status(calc_id, CalcStatus.UPLOADING)

            # Upload files
            upload_result = self.executor.upload_directory(calc.local_dir, calc.remote_dir)

            if not upload_result["success"]:
                self._update_status(calc_id, CalcStatus.FAILED, error=str(upload_result["failed"]))
                return {"success": False, "calc_id": calc_id, "error": upload_result["failed"]}

            # Submit job
            job_id = self.executor.submit_slurm_job(calc.remote_dir, "submit.sh")

            if job_id:
                self._update_status(calc_id, CalcStatus.SUBMITTED, job_id=job_id)
                return {"success": True, "calc_id": calc_id, "job_id": job_id}
            else:
                self._update_status(calc_id, CalcStatus.FAILED, error="Job submission failed")
                return {"success": False, "calc_id": calc_id, "error": "Submission failed"}

        except Exception as e:
            self._update_status(calc_id, CalcStatus.FAILED, error=str(e))
            return {"success": False, "calc_id": calc_id, "error": str(e)}

    def submit_batch(
        self,
        calc_ids: Optional[List[str]] = None,
        parallel: bool = True
    ) -> Dict[str, Any]:
        """
        Submit a batch of calculations

        Args:
            calc_ids: List of calc_ids to submit (None = all pending)
            parallel: Use parallel submission

        Returns:
            Summary of submission results
        """
        if calc_ids is None:
            calc_ids = [
                cid for cid, calc in self.calculations.items()
                if calc.status == CalcStatus.PENDING
            ]

        results = {"submitted": [], "failed": []}

        if parallel and len(calc_ids) > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._submit_single, cid): cid
                    for cid in calc_ids
                }

                for future in as_completed(futures):
                    calc_id = futures[future]
                    try:
                        result = future.result()
                        if result["success"]:
                            results["submitted"].append(calc_id)
                        else:
                            results["failed"].append({"calc_id": calc_id, "error": result.get("error")})
                    except Exception as e:
                        results["failed"].append({"calc_id": calc_id, "error": str(e)})
        else:
            for calc_id in calc_ids:
                result = self._submit_single(calc_id)
                if result["success"]:
                    results["submitted"].append(calc_id)
                else:
                    results["failed"].append({"calc_id": calc_id, "error": result.get("error")})

        return results

    def check_all_status(self) -> Dict[str, List[str]]:
        """
        Check status of all submitted calculations

        Returns:
            Dict grouping calc_ids by status
        """
        status_groups = {s.value: [] for s in CalcStatus}

        # Get all job IDs that need checking
        jobs_to_check = {}
        for calc_id, calc in self.calculations.items():
            if calc.status in [CalcStatus.SUBMITTED, CalcStatus.RUNNING]:
                if calc.job_id:
                    jobs_to_check[calc.job_id] = calc_id

        # Batch check job status
        if jobs_to_check:
            result = self.executor.execute_command(
                f"squeue -j {','.join(jobs_to_check.keys())} -h -o '%i %t' 2>/dev/null"
            )

            running_jobs = {}
            if result["stdout"]:
                for line in result["stdout"].strip().split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            running_jobs[parts[0]] = parts[1]

            # Update statuses
            for job_id, calc_id in jobs_to_check.items():
                if job_id in running_jobs:
                    slurm_status = running_jobs[job_id]
                    if slurm_status in ["R", "CG"]:
                        self._update_status(calc_id, CalcStatus.RUNNING)
                    elif slurm_status == "PD":
                        pass  # Still pending in queue
                else:
                    # Job not in queue - check if completed or failed
                    calc = self.calculations[calc_id]
                    check_result = self.executor.execute_command(
                        f"test -f {calc.remote_dir}/OUTCAR && grep -q 'General timing' {calc.remote_dir}/OUTCAR && echo 'DONE' || echo 'INCOMPLETE'"
                    )

                    if "DONE" in check_result["stdout"]:
                        self._update_status(calc_id, CalcStatus.COMPLETED)
                    else:
                        # Check for errors
                        err_result = self.executor.execute_command(
                            f"grep -i 'error' {calc.remote_dir}/vasp_*.err 2>/dev/null | head -1"
                        )
                        if err_result["stdout"]:
                            self._update_status(calc_id, CalcStatus.FAILED, error=err_result["stdout"])
                        else:
                            self._update_status(calc_id, CalcStatus.FAILED, error="Job ended without completion")

        # Group by status
        for calc_id, calc in self.calculations.items():
            status_groups[calc.status.value].append(calc_id)

        return status_groups

    def wait_all_complete(
        self,
        timeout: int = 86400,
        poll_interval: int = 60,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Wait for all calculations to complete

        Args:
            timeout: Maximum wait time in seconds
            poll_interval: Status check interval
            progress_callback: Called with progress updates

        Returns:
            Final status summary
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            status_groups = self.check_all_status()

            active = len(status_groups["submitted"]) + len(status_groups["running"])
            completed = len(status_groups["completed"])
            failed = len(status_groups["failed"])
            total = len(self.calculations)

            if progress_callback:
                progress_callback({
                    "active": active,
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                    "elapsed": time.time() - start_time
                })

            if active == 0:
                break

            time.sleep(poll_interval)

        return self.check_all_status()

    def download_results(
        self,
        calc_ids: Optional[List[str]] = None,
        files: List[str] = None
    ) -> Dict[str, Any]:
        """
        Download results for completed calculations

        Args:
            calc_ids: List of calc_ids (None = all completed)
            files: Specific files to download (None = all)

        Returns:
            Download summary
        """
        if files is None:
            files = ["OUTCAR", "CONTCAR", "vasprun.xml", "OSZICAR", "DOSCAR", "EIGENVAL"]

        if calc_ids is None:
            calc_ids = [
                cid for cid, calc in self.calculations.items()
                if calc.status == CalcStatus.COMPLETED
            ]

        results = {"downloaded": [], "failed": []}

        for calc_id in calc_ids:
            calc = self.calculations.get(calc_id)
            if not calc:
                continue

            try:
                for filename in files:
                    remote_path = f"{calc.remote_dir}/{filename}"
                    local_path = f"{calc.local_dir}/{filename}"

                    if self.executor.file_exists(remote_path):
                        self.executor.download_file(remote_path, local_path)

                results["downloaded"].append(calc_id)
            except Exception as e:
                results["failed"].append({"calc_id": calc_id, "error": str(e)})

        return results

    def parse_all_results(
        self,
        calc_ids: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Parse results for all completed calculations

        Returns:
            Dict mapping calc_id to parsed results
        """
        if calc_ids is None:
            calc_ids = [
                cid for cid, calc in self.calculations.items()
                if calc.status == CalcStatus.COMPLETED
            ]

        results = {}

        for calc_id in calc_ids:
            calc = self.calculations.get(calc_id)
            if not calc:
                continue

            try:
                result = self.parser.get_summary(calc.local_dir, calc.calc_type)
                result["formula"] = calc.formula
                result["calc_id"] = calc_id
                results[calc_id] = result

                # Store in calculation record
                with self._lock:
                    calc.result = result

            except Exception as e:
                results[calc_id] = {"error": str(e), "calc_id": calc_id}

        return results

    def get_summary_table(self) -> List[Dict[str, Any]]:
        """Get summary table of all calculations"""
        rows = []
        for calc_id, calc in self.calculations.items():
            row = {
                "calc_id": calc_id,
                "formula": calc.formula,
                "type": calc.calc_type,
                "status": calc.status.value,
                "job_id": calc.job_id
            }

            if calc.result:
                row["energy"] = calc.result.get("final_energy")
                row["converged"] = calc.result.get("converged")

            rows.append(row)

        return rows

    def save_state(self, filepath: str):
        """Save workflow state to JSON file"""
        state = {
            "calculations": {cid: calc.to_dict() for cid, calc in self.calculations.items()},
            "config_hash": hash(json.dumps(self.config, sort_keys=True, default=str))
        }

        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2, default=str)

    def load_state(self, filepath: str):
        """Load workflow state from JSON file"""
        with open(filepath, 'r') as f:
            state = json.load(f)

        for calc_id, calc_dict in state.get("calculations", {}).items():
            calc_dict["status"] = CalcStatus(calc_dict["status"])
            self.calculations[calc_id] = Calculation(**calc_dict)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
