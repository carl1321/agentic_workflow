"""
VASP calculation result parser
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import numpy as np

try:
    from pymatgen.io.vasp import Vasprun, Outcar, Oszicar
    from pymatgen.electronic_structure.plotter import BSPlotter, DosPlotter
    HAS_PYMATGEN = True
except ImportError:
    HAS_PYMATGEN = False


class ResultParser:
    """
    Parse VASP calculation results
    """

    def __init__(self):
        if not HAS_PYMATGEN:
            raise ImportError("pymatgen is required. Install with: pip install pymatgen")

    def parse_relaxation(self, calc_dir: str) -> Dict[str, Any]:
        """
        Parse relaxation calculation results

        Returns:
            Dict with energy, forces, stress, convergence info
        """
        result = {"success": False, "calc_type": "relaxation"}

        try:
            vasprun_path = os.path.join(calc_dir, "vasprun.xml")
            outcar_path = os.path.join(calc_dir, "OUTCAR")

            if os.path.exists(vasprun_path):
                vasprun = Vasprun(vasprun_path, parse_dos=False, parse_eigen=False)

                result.update({
                    "success": True,
                    "converged": vasprun.converged,
                    "converged_ionic": vasprun.converged_ionic,
                    "converged_electronic": vasprun.converged_electronic,
                    "final_energy": vasprun.final_energy,
                    "energy_per_atom": vasprun.final_energy / len(vasprun.final_structure),
                    "final_structure": vasprun.final_structure,
                    "ionic_steps": len(vasprun.ionic_steps),
                })

                # Get forces and stress from last ionic step
                last_step = vasprun.ionic_steps[-1]
                if "forces" in last_step:
                    forces = np.array(last_step["forces"])
                    result["max_force"] = float(np.max(np.abs(forces)))
                    result["rms_force"] = float(np.sqrt(np.mean(forces**2)))

                if "stress" in last_step:
                    result["stress"] = last_step["stress"]

            elif os.path.exists(outcar_path):
                # Fallback to OUTCAR parsing
                outcar = Outcar(outcar_path)
                result.update({
                    "success": True,
                    "final_energy": outcar.final_energy,
                    "run_stats": outcar.run_stats
                })

        except Exception as e:
            result["error"] = str(e)

        return result

    def parse_scf(self, calc_dir: str) -> Dict[str, Any]:
        """
        Parse SCF calculation results

        Returns:
            Dict with energy, band gap, Fermi level, DOS info
        """
        result = {"success": False, "calc_type": "scf"}

        try:
            vasprun_path = os.path.join(calc_dir, "vasprun.xml")

            if os.path.exists(vasprun_path):
                vasprun = Vasprun(vasprun_path)

                result.update({
                    "success": True,
                    "converged": vasprun.converged_electronic,
                    "final_energy": vasprun.final_energy,
                    "efermi": vasprun.efermi,
                })

                # Band gap info
                bs = vasprun.get_band_structure()
                gap_info = bs.get_band_gap()
                result.update({
                    "band_gap": gap_info["energy"],
                    "is_direct": gap_info["direct"],
                    "is_metal": bs.is_metal(),
                })

                # DOS if available
                if vasprun.complete_dos:
                    result["has_dos"] = True
                    result["dos"] = vasprun.complete_dos

        except Exception as e:
            result["error"] = str(e)

        return result

    def parse_band(self, calc_dir: str) -> Dict[str, Any]:
        """
        Parse band structure calculation results

        Returns:
            Dict with band structure, gap info
        """
        result = {"success": False, "calc_type": "band"}

        try:
            vasprun_path = os.path.join(calc_dir, "vasprun.xml")
            kpoints_path = os.path.join(calc_dir, "KPOINTS")

            if os.path.exists(vasprun_path):
                vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
                bs = vasprun.get_band_structure(kpoints_path, line_mode=True)

                gap_info = bs.get_band_gap()
                result.update({
                    "success": True,
                    "band_structure": bs,
                    "efermi": vasprun.efermi,
                    "band_gap": gap_info["energy"],
                    "is_direct": gap_info["direct"],
                    "is_metal": bs.is_metal(),
                    "vbm": bs.get_vbm(),
                    "cbm": bs.get_cbm(),
                })

        except Exception as e:
            result["error"] = str(e)

        return result

    def parse_dos(self, calc_dir: str) -> Dict[str, Any]:
        """
        Parse DOS calculation results
        """
        result = {"success": False, "calc_type": "dos"}

        try:
            vasprun_path = os.path.join(calc_dir, "vasprun.xml")

            if os.path.exists(vasprun_path):
                vasprun = Vasprun(vasprun_path)

                result.update({
                    "success": True,
                    "efermi": vasprun.efermi,
                    "complete_dos": vasprun.complete_dos,
                    "tdos": vasprun.tdos,
                })

                # Get band gap from DOS
                gap = vasprun.complete_dos.get_gap()
                result["band_gap"] = gap

        except Exception as e:
            result["error"] = str(e)

        return result

    def check_convergence(self, calc_dir: str) -> Dict[str, Any]:
        """
        Quick convergence check without full parsing
        """
        result = {
            "electronic_converged": False,
            "ionic_converged": False,
            "completed": False
        }

        outcar_path = os.path.join(calc_dir, "OUTCAR")
        oszicar_path = os.path.join(calc_dir, "OSZICAR")

        try:
            if os.path.exists(outcar_path):
                with open(outcar_path, 'r') as f:
                    content = f.read()
                    result["completed"] = "General timing" in content
                    result["electronic_converged"] = "reached required accuracy" in content

            if os.path.exists(oszicar_path):
                oszicar = Oszicar(oszicar_path)
                result["ionic_steps"] = len(oszicar.ionic_steps)
                if oszicar.ionic_steps:
                    result["final_energy"] = oszicar.final_energy

        except Exception as e:
            result["error"] = str(e)

        return result

    def detect_errors(self, calc_dir: str) -> Dict[str, Any]:
        """
        Detect common VASP errors

        Returns:
            Dict with error type and suggested fix
        """
        errors = []

        # Check stdout/stderr files
        for fname in ["vasp.out", "vasp.err", "stdout", "stderr"]:
            fpath = os.path.join(calc_dir, fname)
            if os.path.exists(fpath):
                with open(fpath, 'r') as f:
                    content = f.read()

                    if "ZBRENT" in content:
                        errors.append({
                            "type": "ZBRENT",
                            "message": "ZBRENT error in ionic relaxation",
                            "fix": "Reduce EDIFF or use IBRION=1"
                        })

                    if "EDDDAV" in content:
                        errors.append({
                            "type": "EDDDAV",
                            "message": "Electronic minimization failed",
                            "fix": "Try ALGO=All or reduce EDIFF"
                        })

                    if "VERY BAD NEWS" in content or "internal error" in content.lower():
                        errors.append({
                            "type": "INTERNAL",
                            "message": "VASP internal error",
                            "fix": "Check POTCAR compatibility and structure"
                        })

                    if "ran out of memory" in content.lower() or "oom" in content.lower():
                        errors.append({
                            "type": "OOM",
                            "message": "Out of memory",
                            "fix": "Increase NCORE or reduce KPOINTS"
                        })

        return {
            "has_errors": len(errors) > 0,
            "errors": errors
        }

    def get_summary(self, calc_dir: str, calc_type: str = "auto") -> Dict[str, Any]:
        """
        Get calculation summary based on type
        """
        if calc_type == "auto":
            # Detect calc type from INCAR
            incar_path = os.path.join(calc_dir, "INCAR")
            if os.path.exists(incar_path):
                with open(incar_path, 'r') as f:
                    content = f.read()
                    if "NSW" in content:
                        nsw_line = [l for l in content.split('\n') if 'NSW' in l][0]
                        nsw = int(nsw_line.split('=')[1].strip().split()[0])
                        if nsw > 0:
                            calc_type = "relaxation"
                        elif "ICHARG = 11" in content or "ICHARG=11" in content:
                            calc_type = "band"
                        else:
                            calc_type = "scf"

        if calc_type == "relaxation":
            return self.parse_relaxation(calc_dir)
        elif calc_type == "scf":
            return self.parse_scf(calc_dir)
        elif calc_type == "band":
            return self.parse_band(calc_dir)
        elif calc_type == "dos":
            return self.parse_dos(calc_dir)
        else:
            return {"error": f"Unknown calc_type: {calc_type}"}
