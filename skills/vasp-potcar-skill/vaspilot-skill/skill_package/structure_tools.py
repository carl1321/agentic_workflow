"""
Crystal structure tools based on pymatgen
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import numpy as np

try:
    from pymatgen.core import Structure, Lattice, Element
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from pymatgen.io.vasp import Poscar
    HAS_PYMATGEN = True
except ImportError:
    HAS_PYMATGEN = False

try:
    from mp_api.client import MPRester
    HAS_MP_API = True
except ImportError:
    HAS_MP_API = False


class StructureTools:
    """
    Crystal structure manipulation tools
    """

    def __init__(self, mp_api_key: Optional[str] = None):
        if not HAS_PYMATGEN:
            raise ImportError("pymatgen is required. Install with: pip install pymatgen")
        self.mp_api_key = mp_api_key

    def search_materials_project(
        self,
        formula: str,
        max_results: int = 5,
        fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search structures from Materials Project

        Args:
            formula: Chemical formula (e.g., "Si", "Li2O", "Fe2O3")
            max_results: Maximum number of results
            fields: Fields to retrieve

        Returns:
            List of structure info dictionaries
        """
        if not HAS_MP_API:
            raise ImportError("mp-api is required. Install with: pip install mp-api")

        if not self.mp_api_key:
            raise ValueError("Materials Project API key is required")

        if fields is None:
            fields = ["material_id", "formula_pretty", "structure",
                     "energy_per_atom", "band_gap", "is_stable"]

        results = []
        with MPRester(self.mp_api_key) as mpr:
            docs = mpr.materials.summary.search(
                formula=formula,
                fields=fields
            )

            for doc in docs[:max_results]:
                result = {
                    "material_id": doc.material_id,
                    "formula": doc.formula_pretty,
                    "energy_per_atom": doc.energy_per_atom,
                    "band_gap": doc.band_gap,
                    "is_stable": doc.is_stable
                }
                if hasattr(doc, 'structure') and doc.structure:
                    result["structure"] = doc.structure
                results.append(result)

        return results

    def load_structure(self, file_path: str) -> Structure:
        """Load structure from file (POSCAR, CIF, etc.)"""
        return Structure.from_file(file_path)

    def save_structure(
        self,
        structure: Structure,
        file_path: str,
        fmt: str = "poscar"
    ) -> str:
        """Save structure to file"""
        os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)

        if fmt.lower() == "poscar":
            poscar = Poscar(structure)
            poscar.write_file(file_path)
        else:
            structure.to(filename=file_path, fmt=fmt)

        return file_path

    def analyze_structure(self, structure: Union[str, Structure]) -> Dict[str, Any]:
        """
        Analyze crystal structure

        Returns:
            Dict with space group, lattice parameters, composition info
        """
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        spg = SpacegroupAnalyzer(structure)

        lattice = structure.lattice
        return {
            "formula": structure.composition.reduced_formula,
            "num_atoms": len(structure),
            "space_group": {
                "symbol": spg.get_space_group_symbol(),
                "number": spg.get_space_group_number(),
                "crystal_system": spg.get_crystal_system(),
                "point_group": spg.get_point_group_symbol()
            },
            "lattice": {
                "a": lattice.a,
                "b": lattice.b,
                "c": lattice.c,
                "alpha": lattice.alpha,
                "beta": lattice.beta,
                "gamma": lattice.gamma,
                "volume": lattice.volume
            },
            "elements": list(set(str(s.specie) for s in structure)),
            "density": structure.density
        }

    def create_supercell(
        self,
        structure: Union[str, Structure],
        scaling_matrix: Union[List[int], List[List[int]]]
    ) -> Structure:
        """
        Create supercell

        Args:
            structure: Input structure or file path
            scaling_matrix: [a, b, c] or 3x3 matrix

        Returns:
            Supercell structure
        """
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        if len(scaling_matrix) == 3 and isinstance(scaling_matrix[0], int):
            scaling_matrix = np.diag(scaling_matrix)

        structure.make_supercell(scaling_matrix)
        return structure

    def create_structure(
        self,
        lattice_params: Dict[str, float],
        species: List[str],
        coords: List[List[float]],
        coords_are_cartesian: bool = False
    ) -> Structure:
        """
        Create structure from scratch

        Args:
            lattice_params: {"a": 5.0, "b": 5.0, "c": 5.0, "alpha": 90, "beta": 90, "gamma": 90}
            species: List of element symbols
            coords: List of coordinates
            coords_are_cartesian: If True, coords are Cartesian; else fractional

        Returns:
            Structure object
        """
        lattice = Lattice.from_parameters(
            a=lattice_params["a"],
            b=lattice_params["b"],
            c=lattice_params["c"],
            alpha=lattice_params.get("alpha", 90),
            beta=lattice_params.get("beta", 90),
            gamma=lattice_params.get("gamma", 90)
        )

        return Structure(
            lattice,
            species,
            coords,
            coords_are_cartesian=coords_are_cartesian
        )

    def substitute_element(
        self,
        structure: Union[str, Structure],
        original: str,
        substitute: str,
        fraction: float = 1.0
    ) -> Structure:
        """
        Substitute one element with another

        Args:
            structure: Input structure
            original: Element to replace
            substitute: New element
            fraction: Fraction of sites to substitute (0-1)

        Returns:
            Modified structure
        """
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        structure = structure.copy()

        sites_to_replace = [
            i for i, site in enumerate(structure)
            if str(site.specie) == original
        ]

        if fraction < 1.0:
            n_replace = int(len(sites_to_replace) * fraction)
            sites_to_replace = sites_to_replace[:n_replace]

        for i in sites_to_replace:
            structure.replace(i, substitute)

        return structure

    def get_conventional_cell(self, structure: Union[str, Structure]) -> Structure:
        """Get conventional standard cell"""
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        spg = SpacegroupAnalyzer(structure)
        return spg.get_conventional_standard_structure()

    def get_primitive_cell(self, structure: Union[str, Structure]) -> Structure:
        """Get primitive cell"""
        if isinstance(structure, str):
            structure = Structure.from_file(structure)

        spg = SpacegroupAnalyzer(structure)
        return spg.get_primitive_standard_structure()
