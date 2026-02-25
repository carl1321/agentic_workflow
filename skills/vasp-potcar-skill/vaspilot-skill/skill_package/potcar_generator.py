"""
POTCAR generator using vasp-potcar-skill
"""

import os
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from .config_loader import get_potcar_skill_path


class POTCARGenerator:
    """
    Generate POTCAR files using vasp-potcar-skill

    This integrates with the vasp-potcar-skill for intelligent
    pseudopotential selection based on multiple data sources.
    """

    def __init__(
        self,
        potcar_skill_path: Optional[str] = None,
        potcar_dir: Optional[str] = None,
        functional: str = "PBE"
    ):
        """
        Initialize POTCAR generator

        Args:
            potcar_skill_path: Path to potcar_skill.py script
            potcar_dir: Path to POTCAR library (for fallback)
            functional: VASP functional (PBE, LDA, etc.)
        """
        self.functional = functional
        self.potcar_dir = potcar_dir

        # Find potcar_skill.py
        if potcar_skill_path:
            self.skill_path = Path(potcar_skill_path)
        else:
            self.skill_path = get_potcar_skill_path()

        self.skill_available = self.skill_path and self.skill_path.exists()

    def get_recommendation(
        self,
        elements: List[str],
        calc_type: str = "standard",
        formula: Optional[str] = None,
        enable_api: bool = False
    ) -> Dict[str, Any]:
        """
        Get POTCAR recommendations from vasp-potcar-skill

        Args:
            elements: List of element symbols
            calc_type: Calculation type (standard, accurate, band, phonon, etc.)
            formula: Chemical formula for API queries
            enable_api: Enable online API queries (AFLOW, OQMD, MP)

        Returns:
            Dict with recommendations and confidence scores
        """
        if not self.skill_available:
            return self._fallback_recommendation(elements, calc_type)

        cmd = [
            "python", str(self.skill_path),
            "recommend"
        ] + elements + [
            "-t", calc_type
        ]

        if enable_api:
            cmd.append("--enable-api")

        if formula:
            cmd.extend(["-f", formula])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                # Parse JSON output
                output = result.stdout.strip()
                # Find JSON in output
                for line in output.split('\n'):
                    if line.startswith('{'):
                        return json.loads(line)

                # Try parsing entire output
                return json.loads(output)
            else:
                print(f"POTCAR skill warning: {result.stderr}")
                return self._fallback_recommendation(elements, calc_type)

        except subprocess.TimeoutExpired:
            print("POTCAR skill timeout, using fallback")
            return self._fallback_recommendation(elements, calc_type)
        except json.JSONDecodeError:
            # Parse text output
            return self._parse_text_recommendation(result.stdout, elements)
        except Exception as e:
            print(f"POTCAR skill error: {e}")
            return self._fallback_recommendation(elements, calc_type)

    def _parse_text_recommendation(
        self,
        output: str,
        elements: List[str]
    ) -> Dict[str, Any]:
        """Parse text output from potcar_skill"""
        recommendations = {}

        for line in output.split('\n'):
            for el in elements:
                if f"{el}:" in line or f"{el} ->" in line:
                    # Extract recommended type
                    parts = line.split('->')
                    if len(parts) >= 2:
                        rec_type = parts[-1].strip().split()[0]
                        recommendations[el] = rec_type

        # Fill missing with defaults
        for el in elements:
            if el not in recommendations:
                recommendations[el] = self._get_default_potcar(el)

        return {
            "recommendations": recommendations,
            "confidence": 0.7,
            "source": "text_parse"
        }

    def _fallback_recommendation(
        self,
        elements: List[str],
        calc_type: str
    ) -> Dict[str, Any]:
        """Fallback recommendations when skill is unavailable"""
        recommendations = {}
        for el in elements:
            recommendations[el] = self._get_default_potcar(el, calc_type)

        return {
            "recommendations": recommendations,
            "confidence": 0.5,
            "source": "fallback"
        }

    def _get_default_potcar(self, element: str, calc_type: str = "standard") -> str:
        """Get default POTCAR type for element"""
        # Standard recommendations based on VASP wiki
        sv_elements = {"Li", "Na", "K", "Rb", "Cs", "Ca", "Sr", "Ba", "Sc", "Y"}
        pv_elements = {"Ti", "V", "Cr", "Mn", "Nb", "Mo", "Ta", "W"}
        d_elements = {"Ga", "Ge", "In", "Sn", "Tl", "Pb", "Bi"}

        # GW calculations need special POTCARs
        if calc_type in ["gw", "optical"]:
            return f"{element}_GW" if element not in ["H", "He"] else element

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
        elements: List[str],
        potcar_types: Dict[str, str],
        potcar_dir: str,
        output_path: str = "POTCAR"
    ) -> str:
        """
        Generate shell script to create POTCAR on HPC

        Args:
            elements: List of elements in order
            potcar_types: Dict mapping element to POTCAR type
            potcar_dir: Remote POTCAR directory
            output_path: Output POTCAR path

        Returns:
            Shell script content
        """
        script = f"""#!/bin/bash
# POTCAR generation script
# Generated by VASPilot with vasp-potcar-skill recommendations

POTCAR_DIR="{potcar_dir}"
OUTPUT="{output_path}"

rm -f "$OUTPUT"

"""
        for el in elements:
            potcar_type = potcar_types.get(el, el)
            script += f"""
# {el} -> {potcar_type}
if [ -f "$POTCAR_DIR/{potcar_type}/POTCAR" ]; then
    cat "$POTCAR_DIR/{potcar_type}/POTCAR" >> "$OUTPUT"
elif [ -f "$POTCAR_DIR/{potcar_type}/POTCAR.gz" ]; then
    zcat "$POTCAR_DIR/{potcar_type}/POTCAR.gz" >> "$OUTPUT"
elif [ -f "$POTCAR_DIR/POTCAR.{potcar_type}" ]; then
    cat "$POTCAR_DIR/POTCAR.{potcar_type}" >> "$OUTPUT"
elif [ -f "$POTCAR_DIR/POTCAR.{potcar_type}.gz" ]; then
    zcat "$POTCAR_DIR/POTCAR.{potcar_type}.gz" >> "$OUTPUT"
else
    echo "ERROR: POTCAR for {potcar_type} not found in $POTCAR_DIR"
    exit 1
fi
"""

        script += """
echo "POTCAR generated successfully: $OUTPUT"
echo "Elements: """ + " ".join(elements) + """"
"""
        return script

    def generate_for_structure(
        self,
        structure,
        calc_type: str = "standard",
        potcar_dir: Optional[str] = None,
        enable_api: bool = False
    ) -> Dict[str, Any]:
        """
        Generate POTCAR script for a structure

        Args:
            structure: pymatgen Structure object
            calc_type: Calculation type
            potcar_dir: Remote POTCAR directory
            enable_api: Enable online API queries

        Returns:
            Dict with script content and recommendations
        """
        # Get elements in order
        elements = []
        for site in structure:
            el = str(site.specie)
            if el not in elements:
                elements.append(el)

        # Get formula
        formula = structure.composition.reduced_formula

        # Get recommendations
        rec_result = self.get_recommendation(
            elements=elements,
            calc_type=calc_type,
            formula=formula,
            enable_api=enable_api
        )

        potcar_types = rec_result.get("recommendations", {})

        # Fill missing
        for el in elements:
            if el not in potcar_types:
                potcar_types[el] = self._get_default_potcar(el, calc_type)

        # Generate script
        script = self.generate_potcar_script(
            elements=elements,
            potcar_types=potcar_types,
            potcar_dir=potcar_dir or self.potcar_dir or "/opt/vasp/potpaw_PBE"
        )

        return {
            "script": script,
            "elements": elements,
            "potcar_types": potcar_types,
            "confidence": rec_result.get("confidence", 0.5),
            "source": rec_result.get("source", "unknown")
        }
