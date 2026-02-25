"""
Remote executor for HPC cluster operations via SSH
"""

import os
import stat
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


@dataclass
class JobStatus:
    """Slurm job status"""
    job_id: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    node: Optional[str] = None
    time_used: Optional[str] = None
    exit_code: Optional[int] = None


class RemoteExecutor:
    """
    SSH-based remote executor for HPC clusters

    Handles:
    - SSH connection management
    - File upload/download via SFTP
    - Slurm job submission and monitoring
    """

    def __init__(
        self,
        host: str,
        username: str,
        port: int = 22,
        key_path: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30
    ):
        if not HAS_PARAMIKO:
            raise ImportError("paramiko is required. Install with: pip install paramiko")

        self.host = host
        self.username = username
        self.port = port
        self.key_path = key_path
        self.password = password
        self.timeout = timeout

        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> bool:
        """Establish SSH connection"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username,
                "timeout": self.timeout
            }

            if self.key_path:
                key_path = os.path.expanduser(self.key_path)
                connect_kwargs["key_filename"] = key_path
            elif self.password:
                connect_kwargs["password"] = self.password

            self.client.connect(**connect_kwargs)
            self.sftp = self.client.open_sftp()
            return True

        except Exception as e:
            print(f"SSH connection failed: {e}")
            return False

    def disconnect(self):
        """Close SSH connection"""
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.client:
            self.client.close()
            self.client = None

    def execute_command(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        """Execute remote command"""
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()

            return {
                "success": exit_code == 0,
                "stdout": stdout.read().decode('utf-8').strip(),
                "stderr": stderr.read().decode('utf-8').strip(),
                "exit_code": exit_code
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1
            }

    def _ensure_remote_dir(self, remote_path: str):
        """Ensure remote directory exists"""
        dirs_to_create = []
        current = remote_path

        while current and current != '/':
            try:
                self.sftp.stat(current)
                break
            except FileNotFoundError:
                dirs_to_create.append(current)
                current = os.path.dirname(current)

        for dir_path in reversed(dirs_to_create):
            try:
                self.sftp.mkdir(dir_path)
            except IOError:
                pass  # Directory might already exist

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """Upload single file"""
        if not self.sftp:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            remote_dir = os.path.dirname(remote_path)
            self._ensure_remote_dir(remote_dir)
            self.sftp.put(local_path, remote_path)
            return True
        except Exception as e:
            print(f"Upload failed: {e}")
            return False

    def upload_directory(self, local_dir: str, remote_dir: str) -> Dict[str, Any]:
        """Upload entire directory recursively"""
        if not self.sftp:
            raise RuntimeError("Not connected. Call connect() first.")

        local_path = Path(local_dir)
        uploaded = []
        failed = []

        self._ensure_remote_dir(remote_dir)

        for item in local_path.rglob('*'):
            if item.is_file():
                rel_path = item.relative_to(local_path)
                remote_path = f"{remote_dir}/{rel_path}".replace('\\', '/')

                try:
                    remote_file_dir = os.path.dirname(remote_path)
                    self._ensure_remote_dir(remote_file_dir)
                    self.sftp.put(str(item), remote_path)
                    uploaded.append(str(rel_path))
                except Exception as e:
                    failed.append({"file": str(rel_path), "error": str(e)})

        return {
            "success": len(failed) == 0,
            "uploaded": uploaded,
            "failed": failed,
            "total": len(uploaded) + len(failed)
        }

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """Download single file"""
        if not self.sftp:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            local_dir = os.path.dirname(local_path)
            os.makedirs(local_dir, exist_ok=True)
            self.sftp.get(remote_path, local_path)
            return True
        except Exception as e:
            print(f"Download failed: {e}")
            return False

    def download_directory(
        self,
        remote_dir: str,
        local_dir: str,
        patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Download directory contents

        Args:
            remote_dir: Remote directory path
            local_dir: Local destination path
            patterns: Optional list of filename patterns to download (e.g., ['OUTCAR', 'vasprun.xml'])
        """
        if not self.sftp:
            raise RuntimeError("Not connected. Call connect() first.")

        os.makedirs(local_dir, exist_ok=True)
        downloaded = []
        failed = []

        def download_recursive(r_dir: str, l_dir: str):
            try:
                items = self.sftp.listdir_attr(r_dir)
            except Exception as e:
                failed.append({"path": r_dir, "error": str(e)})
                return

            for item in items:
                r_path = f"{r_dir}/{item.filename}"
                l_path = os.path.join(l_dir, item.filename)

                if stat.S_ISDIR(item.st_mode):
                    os.makedirs(l_path, exist_ok=True)
                    download_recursive(r_path, l_path)
                else:
                    # Check pattern filter
                    if patterns and item.filename not in patterns:
                        continue

                    try:
                        self.sftp.get(r_path, l_path)
                        downloaded.append(item.filename)
                    except Exception as e:
                        failed.append({"file": item.filename, "error": str(e)})

        download_recursive(remote_dir, local_dir)

        return {
            "success": len(failed) == 0,
            "downloaded": downloaded,
            "failed": failed
        }

    def submit_slurm_job(self, remote_dir: str, script_name: str = "slurm.sh") -> Dict[str, Any]:
        """Submit Slurm job"""
        script_path = f"{remote_dir}/{script_name}"
        result = self.execute_command(f"cd {remote_dir} && sbatch {script_name}")

        if result["success"]:
            # Parse job ID from "Submitted batch job 12345"
            output = result["stdout"]
            try:
                job_id = output.strip().split()[-1]
                return {
                    "success": True,
                    "job_id": job_id,
                    "message": output
                }
            except:
                return {
                    "success": False,
                    "job_id": None,
                    "error": f"Could not parse job ID from: {output}"
                }
        else:
            return {
                "success": False,
                "job_id": None,
                "error": result["stderr"]
            }

    def check_job_status(self, job_id: str) -> JobStatus:
        """Check Slurm job status"""
        # Try squeue first for running/pending jobs
        result = self.execute_command(
            f"squeue -j {job_id} -h -o '%T %N %M' 2>/dev/null"
        )

        if result["success"] and result["stdout"]:
            parts = result["stdout"].split()
            status = parts[0] if parts else "UNKNOWN"
            node = parts[1] if len(parts) > 1 else None
            time_used = parts[2] if len(parts) > 2 else None

            return JobStatus(
                job_id=job_id,
                status=status,
                node=node,
                time_used=time_used
            )

        # Job not in queue, check sacct for completed jobs
        result = self.execute_command(
            f"sacct -j {job_id} -n -o State,ExitCode -X 2>/dev/null"
        )

        if result["success"] and result["stdout"]:
            parts = result["stdout"].split()
            status = parts[0] if parts else "UNKNOWN"
            exit_code = None
            if len(parts) > 1:
                try:
                    exit_code = int(parts[1].split(':')[0])
                except:
                    pass

            return JobStatus(
                job_id=job_id,
                status=status,
                exit_code=exit_code
            )

        return JobStatus(job_id=job_id, status="UNKNOWN")

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel Slurm job"""
        result = self.execute_command(f"scancel {job_id}")
        return {
            "success": result["success"],
            "message": result["stdout"] or result["stderr"]
        }

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: int = 30,
        timeout: int = 86400,
        callback=None
    ) -> JobStatus:
        """
        Wait for job completion

        Args:
            job_id: Slurm job ID
            poll_interval: Seconds between status checks
            timeout: Maximum wait time in seconds
            callback: Optional callback function(status) called on each poll
        """
        start_time = time.time()

        while True:
            status = self.check_job_status(job_id)

            if callback:
                callback(status)

            if status.status in ["COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL"]:
                return status

            if time.time() - start_time > timeout:
                return JobStatus(job_id=job_id, status="TIMEOUT")

            time.sleep(poll_interval)

    def list_remote_dir(self, remote_dir: str) -> List[str]:
        """List files in remote directory"""
        if not self.sftp:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            return self.sftp.listdir(remote_dir)
        except Exception as e:
            print(f"List directory failed: {e}")
            return []

    def file_exists(self, remote_path: str) -> bool:
        """Check if remote file exists"""
        if not self.sftp:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            self.sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
