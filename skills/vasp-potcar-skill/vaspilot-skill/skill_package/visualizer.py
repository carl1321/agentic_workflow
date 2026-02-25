"""
VASP result visualization tools
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Tuple
import json

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from pymatgen.io.vasp import Vasprun, BSVasprun
    from pymatgen.electronic_structure.plotter import BSPlotter, DosPlotter, BSDOSPlotter
    from pymatgen.electronic_structure.core import Spin
    HAS_PYMATGEN = True
except ImportError:
    HAS_PYMATGEN = False


class ResultVisualizer:
    """
    Visualization tools for VASP calculation results
    """

    def __init__(self, style: str = "default"):
        """
        Initialize visualizer

        Args:
            style: Matplotlib style ('default', 'seaborn', 'ggplot', etc.)
        """
        if not HAS_MATPLOTLIB:
            raise ImportError("matplotlib is required. Install with: pip install matplotlib")

        if style != "default":
            try:
                plt.style.use(style)
            except:
                pass

        # Default plot settings
        self.default_figsize = (8, 6)
        self.default_dpi = 150
        self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

    def plot_band_structure(
        self,
        vasprun_path: str,
        kpoints_path: Optional[str] = None,
        output_path: Optional[str] = None,
        ylim: Tuple[float, float] = (-5, 5),
        zero_to_efermi: bool = True,
        figsize: Optional[Tuple[int, int]] = None,
        title: Optional[str] = None
    ) -> Union[Figure, str]:
        """
        Plot band structure from vasprun.xml

        Args:
            vasprun_path: Path to vasprun.xml
            kpoints_path: Path to KPOINTS file (for line mode)
            output_path: Output image path (if None, returns Figure)
            ylim: Y-axis limits (eV relative to Fermi level)
            zero_to_efermi: Set Fermi level to zero
            figsize: Figure size
            title: Plot title

        Returns:
            Figure object or path to saved image
        """
        if not HAS_PYMATGEN:
            raise ImportError("pymatgen is required for band structure plotting")

        # Load band structure
        vasprun = BSVasprun(vasprun_path, parse_projected_eigen=True)

        if kpoints_path:
            bs = vasprun.get_band_structure(kpoints_path, line_mode=True)
        else:
            bs = vasprun.get_band_structure(line_mode=True)

        # Create plotter
        plotter = BSPlotter(bs)

        # Get plot
        fig = plotter.get_plot(ylim=ylim, zero_to_efermi=zero_to_efermi)

        if title:
            fig.suptitle(title)

        if figsize:
            fig.set_size_inches(figsize)

        if output_path:
            fig.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
            plt.close(fig)
            return output_path
        else:
            return fig

    def plot_dos(
        self,
        vasprun_path: str,
        output_path: Optional[str] = None,
        xlim: Tuple[float, float] = (-10, 10),
        ylim: Optional[Tuple[float, float]] = None,
        sigma: Optional[float] = None,
        figsize: Optional[Tuple[int, int]] = None,
        title: Optional[str] = None,
        elements: Optional[List[str]] = None,
        orbitals: bool = False
    ) -> Union[Figure, str]:
        """
        Plot density of states from vasprun.xml

        Args:
            vasprun_path: Path to vasprun.xml
            output_path: Output image path
            xlim: X-axis limits (eV relative to Fermi level)
            ylim: Y-axis limits
            sigma: Gaussian smearing width
            figsize: Figure size
            title: Plot title
            elements: List of elements to plot (None = total DOS)
            orbitals: Plot orbital-projected DOS

        Returns:
            Figure object or path to saved image
        """
        if not HAS_PYMATGEN:
            raise ImportError("pymatgen is required for DOS plotting")

        vasprun = Vasprun(vasprun_path)
        dos = vasprun.complete_dos

        plotter = DosPlotter(sigma=sigma)

        if elements:
            # Element-projected DOS
            for el in elements:
                el_dos = dos.get_element_dos()
                if el in el_dos:
                    plotter.add_dos(el, el_dos[el])
        elif orbitals:
            # Orbital-projected DOS
            plotter.add_dos("Total", dos)
            spd = dos.get_spd_dos()
            for orbital, orbital_dos in spd.items():
                plotter.add_dos(str(orbital), orbital_dos)
        else:
            # Total DOS
            plotter.add_dos("Total", dos)

        fig = plotter.get_plot(xlim=xlim, ylim=ylim)

        if title:
            fig.suptitle(title)

        if figsize:
            fig.set_size_inches(figsize)

        if output_path:
            fig.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
            plt.close(fig)
            return output_path
        else:
            return fig

    def plot_band_dos(
        self,
        band_vasprun_path: str,
        dos_vasprun_path: str,
        kpoints_path: Optional[str] = None,
        output_path: Optional[str] = None,
        band_ylim: Tuple[float, float] = (-5, 5),
        dos_xlim: Tuple[float, float] = (-5, 5),
        figsize: Tuple[int, int] = (12, 6),
        title: Optional[str] = None
    ) -> Union[Figure, str]:
        """
        Plot combined band structure and DOS

        Args:
            band_vasprun_path: Path to band structure vasprun.xml
            dos_vasprun_path: Path to DOS vasprun.xml
            kpoints_path: Path to KPOINTS file
            output_path: Output image path
            band_ylim: Band structure Y-axis limits
            dos_xlim: DOS X-axis limits
            figsize: Figure size
            title: Plot title

        Returns:
            Figure object or path to saved image
        """
        if not HAS_PYMATGEN:
            raise ImportError("pymatgen is required")

        # Load data
        band_vasprun = BSVasprun(band_vasprun_path)
        dos_vasprun = Vasprun(dos_vasprun_path)

        if kpoints_path:
            bs = band_vasprun.get_band_structure(kpoints_path, line_mode=True)
        else:
            bs = band_vasprun.get_band_structure(line_mode=True)

        dos = dos_vasprun.complete_dos

        # Create combined plotter
        plotter = BSDOSPlotter()
        fig = plotter.get_plot(bs, dos)

        if title:
            fig.suptitle(title)

        fig.set_size_inches(figsize)

        if output_path:
            fig.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
            plt.close(fig)
            return output_path
        else:
            return fig

    def plot_convergence(
        self,
        oszicar_path: str,
        output_path: Optional[str] = None,
        figsize: Tuple[int, int] = (10, 6),
        title: Optional[str] = None
    ) -> Union[Figure, str]:
        """
        Plot energy convergence from OSZICAR

        Args:
            oszicar_path: Path to OSZICAR file
            output_path: Output image path
            figsize: Figure size
            title: Plot title

        Returns:
            Figure object or path to saved image
        """
        # Parse OSZICAR
        ionic_steps = []
        electronic_steps = []

        with open(oszicar_path, 'r') as f:
            current_ionic = []
            for line in f:
                line = line.strip()
                if line.startswith('DAV:') or line.startswith('RMM:'):
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            energy = float(parts[2])
                            current_ionic.append(energy)
                        except ValueError:
                            pass
                elif 'F=' in line:
                    # End of ionic step
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == 'F=':
                            try:
                                ionic_energy = float(parts[i+1])
                                ionic_steps.append(ionic_energy)
                            except (IndexError, ValueError):
                                pass
                            break

                    if current_ionic:
                        electronic_steps.append(current_ionic)
                        current_ionic = []

        # Create figure
        fig, axes = plt.subplots(1, 2, figsize=figsize)

        # Ionic convergence
        if ionic_steps:
            axes[0].plot(range(1, len(ionic_steps) + 1), ionic_steps, 'o-', color=self.colors[0])
            axes[0].set_xlabel('Ionic Step')
            axes[0].set_ylabel('Energy (eV)')
            axes[0].set_title('Ionic Convergence')
            axes[0].grid(True, alpha=0.3)

        # Electronic convergence (last ionic step)
        if electronic_steps:
            last_electronic = electronic_steps[-1]
            axes[1].semilogy(
                range(1, len(last_electronic) + 1),
                [abs(e - last_electronic[-1]) + 1e-10 for e in last_electronic],
                'o-', color=self.colors[1]
            )
            axes[1].set_xlabel('Electronic Step')
            axes[1].set_ylabel('|E - E_final| (eV)')
            axes[1].set_title('Electronic Convergence (Last Ionic Step)')
            axes[1].grid(True, alpha=0.3)

        if title:
            fig.suptitle(title, y=1.02)

        plt.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
            plt.close(fig)
            return output_path
        else:
            return fig

    def plot_batch_summary(
        self,
        results: Dict[str, Dict[str, Any]],
        property_name: str = "final_energy",
        output_path: Optional[str] = None,
        figsize: Tuple[int, int] = (12, 6),
        sort_by: Optional[str] = None,
        title: Optional[str] = None
    ) -> Union[Figure, str]:
        """
        Plot summary of batch calculation results

        Args:
            results: Dict mapping calc_id to result dict
            property_name: Property to plot (final_energy, band_gap, etc.)
            output_path: Output image path
            figsize: Figure size
            sort_by: Sort by this property
            title: Plot title

        Returns:
            Figure object or path to saved image
        """
        # Extract data
        labels = []
        values = []

        for calc_id, result in results.items():
            if property_name in result:
                labels.append(calc_id)
                values.append(result[property_name])

        if not values:
            raise ValueError(f"No data found for property: {property_name}")

        # Sort if requested
        if sort_by == "value":
            sorted_pairs = sorted(zip(labels, values), key=lambda x: x[1])
            labels, values = zip(*sorted_pairs)
        elif sort_by == "name":
            sorted_pairs = sorted(zip(labels, values), key=lambda x: x[0])
            labels, values = zip(*sorted_pairs)

        # Create figure
        fig, ax = plt.subplots(figsize=figsize)

        x = range(len(labels))
        bars = ax.bar(x, values, color=self.colors[0], alpha=0.8)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha='right')
        ax.set_ylabel(property_name.replace('_', ' ').title())

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f'Batch Results: {property_name}')

        ax.grid(True, axis='y', alpha=0.3)

        # Add value labels on bars
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax.annotate(
                f'{val:.3f}',
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha='center', va='bottom',
                fontsize=8
            )

        plt.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
            plt.close(fig)
            return output_path
        else:
            return fig

    def plot_energy_vs_volume(
        self,
        results: Dict[str, Dict[str, Any]],
        output_path: Optional[str] = None,
        figsize: Tuple[int, int] = (8, 6),
        fit_eos: bool = True,
        title: Optional[str] = None
    ) -> Union[Figure, str]:
        """
        Plot energy vs volume (E-V curve)

        Args:
            results: Dict mapping calc_id to result dict (must have volume and energy)
            output_path: Output image path
            figsize: Figure size
            fit_eos: Fit equation of state
            title: Plot title

        Returns:
            Figure object or path to saved image
        """
        # Extract data
        volumes = []
        energies = []
        labels = []

        for calc_id, result in results.items():
            if "volume" in result and "final_energy" in result:
                volumes.append(result["volume"])
                energies.append(result["final_energy"])
                labels.append(calc_id)

        if len(volumes) < 3:
            raise ValueError("Need at least 3 data points for E-V curve")

        volumes = np.array(volumes)
        energies = np.array(energies)

        # Sort by volume
        sort_idx = np.argsort(volumes)
        volumes = volumes[sort_idx]
        energies = energies[sort_idx]

        # Create figure
        fig, ax = plt.subplots(figsize=figsize)

        ax.plot(volumes, energies, 'o', markersize=10, color=self.colors[0], label='Data')

        # Fit EOS if requested
        if fit_eos and HAS_PYMATGEN:
            try:
                from pymatgen.analysis.eos import EOS

                eos = EOS(eos_name='birch_murnaghan')
                eos_fit = eos.fit(volumes, energies)

                v_fit = np.linspace(min(volumes) * 0.95, max(volumes) * 1.05, 100)
                e_fit = eos_fit.func(v_fit)

                ax.plot(v_fit, e_fit, '-', color=self.colors[1], label=f'BM fit (V0={eos_fit.v0:.2f})')

                # Add equilibrium point
                ax.axvline(eos_fit.v0, color=self.colors[2], linestyle='--', alpha=0.5)

            except Exception as e:
                print(f"EOS fitting failed: {e}")

        ax.set_xlabel('Volume (Å³)')
        ax.set_ylabel('Energy (eV)')
        ax.legend()
        ax.grid(True, alpha=0.3)

        if title:
            ax.set_title(title)
        else:
            ax.set_title('Energy vs Volume')

        plt.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
            plt.close(fig)
            return output_path
        else:
            return fig

    def generate_report(
        self,
        calc_dir: str,
        output_dir: Optional[str] = None,
        calc_type: str = "auto"
    ) -> Dict[str, str]:
        """
        Generate a complete visualization report for a calculation

        Args:
            calc_dir: Calculation directory
            output_dir: Output directory for images (default: calc_dir/plots)
            calc_type: Calculation type (auto-detect if "auto")

        Returns:
            Dict mapping plot type to output path
        """
        calc_dir = Path(calc_dir)
        output_dir = Path(output_dir) if output_dir else calc_dir / "plots"
        output_dir.mkdir(parents=True, exist_ok=True)

        generated = {}

        # Convergence plot (always available if OSZICAR exists)
        oszicar_path = calc_dir / "OSZICAR"
        if oszicar_path.exists():
            try:
                path = self.plot_convergence(
                    str(oszicar_path),
                    output_path=str(output_dir / "convergence.png"),
                    title="Energy Convergence"
                )
                generated["convergence"] = path
            except Exception as e:
                print(f"Convergence plot failed: {e}")

        # Band structure (if KPOINTS indicates line mode)
        vasprun_path = calc_dir / "vasprun.xml"
        kpoints_path = calc_dir / "KPOINTS"

        if vasprun_path.exists():
            # Check if it's a band calculation
            is_band = False
            if kpoints_path.exists():
                with open(kpoints_path) as f:
                    content = f.read()
                    if "Line" in content or "Reciprocal" in content:
                        is_band = True

            if is_band or calc_type == "band":
                try:
                    path = self.plot_band_structure(
                        str(vasprun_path),
                        kpoints_path=str(kpoints_path) if kpoints_path.exists() else None,
                        output_path=str(output_dir / "band_structure.png"),
                        title="Band Structure"
                    )
                    generated["band_structure"] = path
                except Exception as e:
                    print(f"Band structure plot failed: {e}")

            # DOS plot
            try:
                path = self.plot_dos(
                    str(vasprun_path),
                    output_path=str(output_dir / "dos.png"),
                    title="Density of States"
                )
                generated["dos"] = path
            except Exception as e:
                print(f"DOS plot failed: {e}")

        return generated
