#!/bin/bash
#SBATCH -J Si_band
#SBATCH -p normal
#SBATCH -N 1
#SBATCH -n 24
#SBATCH -t 2:00:00

# Load VASP module (adjust for your cluster)
module load vasp/6.3.2

# Work directory
WORK_DIR=$SLURM_SUBMIT_DIR

cd $WORK_DIR

# ============================================================
# Step 1: SCF calculation
# ============================================================
echo "Starting SCF calculation..."

cp INCAR_scf INCAR
cp KPOINTS_scf KPOINTS

mpirun -np $SLURM_NTASKS vasp_std > vasp_scf.log 2>&1

# Check if SCF converged
if grep -q "reached required accuracy" OUTCAR; then
    echo "SCF converged successfully!"
else
    echo "SCF did not converge. Check vasp_scf.log"
    exit 1
fi

# Backup SCF results
mkdir -p scf_results
cp OUTCAR CHGCAR DOSCAR vasprun.xml scf_results/

# ============================================================
# Step 2: Band structure calculation
# ============================================================
echo "Starting band calculation..."

cp INCAR_band INCAR
cp KPOINTS_band KPOINTS

mpirun -np $SLURM_NTASKS vasp_std > vasp_band.log 2>&1

echo "Band calculation finished!"
echo "Results: EIGENVAL, PROCAR, vasprun.xml"

# Backup band results
mkdir -p band_results
cp OUTCAR EIGENVAL PROCAR vasprun.xml band_results/

echo "All calculations completed!"
