"""
VASP input file generator
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import math

try:
    from pymatgen.core import Structure, Element
    from pymatgen.io.vasp import Poscar, Incar, Kpoints, Potcar
    from pymatgen.symmetry.bandstructure import HighSymmKpath
    HAS_PYMATGEN = True
except ImportError:
    HAS_PYMATGEN = False

from .potcar_generator import POTCARGenerator


# Default INCAR settings for different calculation types
DEFAULT_INCAR = {
    "relaxation": {
        "ISTART": 0,
        "ICHARG": 2,
        "ENCUT": 520,
        "EDIFF": 1e-6,
        "EDIFFG": -0.02,
        "IBRION": 2,
        "ISIF": 3,
        "NSW": 200,
        "ISMEAR": 0,
        "SIGMA": 0.05,
        "PREC": "Accurate",
        "LREAL": "Auto",
        "LWAVE": False,
        "LCHARG": True
    },
    "scf": {
        "ISTART": 1,
        "ICHARG": 1,
        "ENCUT": 520,
        "EDIFF": 1e-6,
        "IBRION": -1,
        "NSW": 0,
        "ISMEAR": -5,
        "PREC": "Accurate",
        "LREAL": False,
        "LWAVE": True,
        "LCHARG": True,
        "LORBIT": 11
    },
    "band": {
        "ISTART": 1,
        "ICHARG": 11,
        "ENCUT": 520,
        "EDIFF": 1e-6,
        "IBRION": -1,
        "NSW": 0,
        "ISMEAR": 0,
        "SIGMA": 0.05,
        "PREC": "Accurate",
        "LREAL": False,
        "LWAVE": False,
        "LCHARG": False,
        "LORBIT": 11
    },
    "dos": {
        "ISTART": 1,
        "ICHARG": 11,
        "ENCUT": 520,
        "EDIFF": 1e-6,
        "IBRION": -1,
        "NSW": 0,
        "ISMEAR": -5,
        "PREC": "Accurate",
        "LREAL": False,
        "LWAVE": False,
        "LCHARG": False,
        "LORBIT": 11,
        "NEDOS": 3001
    }
}


class VASPInputGenerator:
    """
    Generate VASP input files (INCAR, KPOINTS, POSCAR, POTCAR)
    """

    def __init__(
        self,
        potcar_dir: Optional[str] = None,
        potcar_skill_path: Optional[str] = None,
        use_potcar_skill: bool = True
    ):
        if not HAS_PYMATGEN:
            raise ImportError("pymatgen is required. Install with: pip install pymatgen")
        self.potcar_dir = potcar_dir
        self.use_potcar_skill = use_potcar_skill

        # Initialize POTCAR generator
        self.potcar_gen = POTCARGenerator(
            potcar_skill_path=potcar_skill_path,
            potcar_dir=potcar_dir
        )

    def _fix_line_endings(self, file_path: str):
        """Convert CRLF to LF for Unix compatibility"""
        with open(file_path, 'rb') as f:
            content = f.read()
        content = content.replace(b'\r\n', b'\n')
        with open(file_path, 'wb') as f:
            f.write(content)

    def generate_incar(
        self,
        calc_type: str,
        custom_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate INCAR parameters

        Args:
            calc_type: "relaxation", "scf", "band", "dos"
            custom_params: Override default parameters

        Returns:
            INCAR parameters dict
        """
        if calc_type not in DEFAULT_INCAR:
            raise ValueError(f"Unknown calc_type: {calc_type}")

        params = DEFAULT_INCAR[calc_type].copy()
        if custom_params:
            params.update(custom_params)

        return params

    def generate_kpoints(
        self,
        structure: Structure,
        calc_type: str,
        kpoints_density: int = 40,
        line_density: int = 20
    ) -> str:
        """
        Generate KPOINTS content

        Args:
            structure: Crystal structure
            calc_type: "relaxation", "scf", "band", "dos"
            kpoints_density: K-points per reciprocal atom for grid
            line_density: Points per segment for band structure

        Returns:
            KPOINTS file content as string
        """
        if calc_type == "band":
            # High-symmetry k-path for band structure
            kpath = HighSymmKpath(structure)
            kpts = kpath.get_kpoints(line_density=line_density, coords_are_cartesian=False)

            lines = ["K-Path for band structure", str(len(kpts[0])), "Reciprocal"]
            for kpt, label in zip(kpts[0], kpts[1]):
                label_str = label if label else ""
                lines.append(f"  {kpt[0]:.6f}  {kpt[1]:.6f}  {kpt[2]:.6f}  1  ! {label_str}")

            return "\n".join(lines)
        else:
            # Automatic mesh for other calculations
            kpoints = Kpoints.automatic_density(structure, kpoints_density)
            return str(kpoints)

    def get_recommended_potcar(self, element: str) -> str:
        """
        Get recommended POTCAR type for element

        Returns standard or _sv/_pv variants based on element
        """
        # Elements that typically use _sv (semi-core s and p)
        sv_elements = {"Li", "Na", "K", "Rb", "Cs", "Ca", "Sr", "Ba", "Sc", "Y"}

        # Elements that typically use _pv (semi-core p)
        pv_elements = {"Ti", "V", "Cr", "Mn", "Nb", "Mo", "Ta", "W"}

        # Elements that use _d
        d_elements = {"Ga", "Ge", "In", "Sn", "Tl", "Pb", "Bi"}

        if element in sv_elements:
            return f"{element}_sv"
        elif element in pv_elements:
            return f"{element}_pv"
        elif element in d_elements:
            return f"{element}_d"
        else:
            return element

    def generate_potcar_script(
        self,
        structure: Structure,
        potcar_dir: Optional[str] = None,
        potcar_format: str = "auto"
    ) -> str:
        """
        Generate shell script to create POTCAR on HPC

        Args:
            structure: Crystal structure
            potcar_dir: Path to POTCAR directory on HPC
            potcar_format: "folder" (element/POTCAR), "flat" (POTCAR.element), or "auto"

        Returns:
            Shell script content
        """
        potcar_dir = potcar_dir or self.potcar_dir or "/opt/vasp/potpaw_PBE"

        # Get unique elements in order they appear in POSCAR
        elements = []
        for site in structure:
            el = str(site.specie)
            if el not in elements:
                elements.append(el)

        script = "#!/bin/bash\n"
        script += "# Generate POTCAR\n"
        script += f"POTCAR_DIR={potcar_dir}\n\n"

        # Generate commands for each element
        potcar_cmds = []
        for el in elements:
            recommended = self.get_recommended_potcar(el)
            # Support both folder structure (Si/POTCAR) and flat structure (Si/POTCAR or POTCAR.Si)
            potcar_cmds.append(f'''
# {el} -> {recommended}
if [ -f "$POTCAR_DIR/{recommended}/POTCAR" ]; then
    cat "$POTCAR_DIR/{recommended}/POTCAR" >> POTCAR
elif [ -f "$POTCAR_DIR/{recommended}/POTCAR.gz" ]; then
    zcat "$POTCAR_DIR/{recommended}/POTCAR.gz" >> POTCAR
else
    echo "ERROR: POTCAR for {recommended} not found!"
    exit 1
fi''')

        script += "rm -f POTCAR\n"
        script += "\n".join(potcar_cmds)
        script += "\n\necho 'POTCAR generated successfully'\n"

        return script

    def write_inputs(
        self,
        structure: Structure,
        output_dir: str,
        calc_type: str,
        incar_params: Optional[Dict[str, Any]] = None,
        kpoints_density: int = 40,
        write_potcar_script: bool = True,
        potcar_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Write all VASP input files to directory

        Args:
            structure: Crystal structure
            output_dir: Output directory
            calc_type: Calculation type
            incar_params: Custom INCAR parameters
            kpoints_density: K-points density
            write_potcar_script: Whether to write POTCAR generation script
            potcar_dir: POTCAR directory on HPC

        Returns:
            Dict of written file paths
        """
        os.makedirs(output_dir, exist_ok=True)
        written_files = {}

        # POSCAR
        poscar_path = os.path.join(output_dir, "POSCAR")
        poscar = Poscar(structure)
        poscar.write_file(poscar_path)
        # Fix line endings for Unix
        self._fix_line_endings(poscar_path)
        written_files["POSCAR"] = poscar_path

        # INCAR
        incar_path = os.path.join(output_dir, "INCAR")
        incar_params_final = self.generate_incar(calc_type, incar_params)
        incar = Incar(incar_params_final)
        incar.write_file(incar_path)
        # Fix line endings for Unix
        self._fix_line_endings(incar_path)
        written_files["INCAR"] = incar_path

        # KPOINTS
        kpoints_path = os.path.join(output_dir, "KPOINTS")
        kpoints_content = self.generate_kpoints(
            structure, calc_type, kpoints_density=kpoints_density
        )
        with open(kpoints_path, 'w', newline='\n') as f:
            f.write(kpoints_content)
        written_files["KPOINTS"] = kpoints_path

        # POTCAR script - use potcar_skill if available
        if write_potcar_script:
            script_path = os.path.join(output_dir, "gen_potcar.sh")

            if self.use_potcar_skill and self.potcar_gen.skill_available:
                # Use intelligent POTCAR selection
                potcar_result = self.potcar_gen.generate_for_structure(
                    structure=structure,
                    calc_type=calc_type,
                    potcar_dir=potcar_dir or self.potcar_dir
                )
                script_content = potcar_result["script"]
                written_files["potcar_info"] = {
                    "types": potcar_result["potcar_types"],
                    "confidence": potcar_result["confidence"],
                    "source": potcar_result["source"]
                }
            else:
                # Fallback to simple script
                script_content = self.generate_potcar_script(structure, potcar_dir)

            with open(script_path, 'w', newline='\n') as f:
                f.write(script_content)
            written_files["gen_potcar.sh"] = script_path

        return written_files

    def generate_slurm_script(
        self,
        job_name: str = "vasp_job",
        nodes: int = 1,
        ntasks: int = 48,
        partition: str = "normal",
        time_limit: str = "24:00:00",
        vasp_bin: Optional[str] = None,
        vasp_command: str = "vasp_std",
        potcar_dir: Optional[str] = None,
        gen_potcar: bool = True
    ) -> str:
        """
        Generate Slurm submission script

        Args:
            job_name: Job name
            nodes: Number of nodes
            ntasks: Number of MPI tasks
            partition: Slurm partition
            time_limit: Time limit (HH:MM:SS)
            vasp_bin: Path to VASP bin directory
            vasp_command: VASP executable name
            potcar_dir: POTCAR directory
            gen_potcar: Whether to generate POTCAR

        Returns:
            Slurm script content
        """
        script = f"""#!/bin/bash
#SBATCH -J {job_name}
#SBATCH -N {nodes}
#SBATCH -n {ntasks}
#SBATCH -p {partition}
#SBATCH -t {time_limit}
#SBATCH -o vasp_%j.out
#SBATCH -e vasp_%j.err

# Load modules
module purge
module load compiler/intel/2017.5.239
module load mpi/intelmpi/2017.4.239

"""
        if gen_potcar and potcar_dir:
            script += "# Generate POTCAR\nbash gen_potcar.sh\n\n"

        # Set VASP path and run
        if vasp_bin:
            script += f"# Run VASP\nmpirun -np {ntasks} {vasp_bin}/{vasp_command}\n"
        else:
            script += f"# Run VASP\nmpirun -np {ntasks} {vasp_command}\n"

        return script
