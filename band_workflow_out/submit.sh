#!/bin/bash
#SBATCH -J vasp_job
#SBATCH -p kshcnormal
#SBATCH -N 1
#SBATCH -n 32
#SBATCH -t 48:00:00
#SBATCH -o vasp_%j.out
#SBATCH -e vasp_%j.err

# Load modules (config: hpc.modules)
module purge
module load compiler/intel/2017.5.239
module load mpi/intelmpi/2017.4.239

WORK_DIR=$SLURM_SUBMIT_DIR
cd $WORK_DIR

# Generate POTCAR
bash gen_potcar.sh
test -f POTCAR || { echo 'ERROR: POTCAR was not created. Check gen_potcar.sh and hpc.potcar_dir in config.'; exit 1; }

# ============================================================
# Step 1: SCF calculation
# ============================================================
echo "Starting SCF calculation..."
cp INCAR_scf INCAR
cp KPOINTS_scf KPOINTS
mpirun -np $SLURM_NTASKS /public/home/wenliyang/softwares/vasp.6.3.0/bin/vasp_std > vasp_scf.log 2>&1

# Check if SCF converged (OUTCAR may be missing if VASP failed to run)
if [ ! -f OUTCAR ]; then
    echo "OUTCAR not found - VASP may have failed. Check vasp_scf.log"
    tail -100 vasp_scf.log
    exit 1
fi
# 离子弛豫用 "reached required accuracy"；单点 SCF(NSW=0) 用 "EDIFF is reached" 或 "General timing" 表示正常结束
if grep -q "reached required accuracy" OUTCAR || grep -q "EDIFF is reached" OUTCAR || grep -q "General timing" OUTCAR; then
    echo "SCF converged successfully!"
else
    echo "SCF did not converge. Check vasp_scf.log"
    tail -50 vasp_scf.log
    exit 1
fi
mkdir -p scf_results
cp OUTCAR CHGCAR DOSCAR vasprun.xml scf_results/ 2>/dev/null || true

# ============================================================
# Step 2: Band structure calculation
# ============================================================
echo "Starting band calculation..."
cp INCAR_band INCAR
cp KPOINTS_band KPOINTS
mpirun -np $SLURM_NTASKS /public/home/wenliyang/softwares/vasp.6.3.0/bin/vasp_std > vasp_band.log 2>&1

echo "Band calculation finished!"
mkdir -p band_results
cp OUTCAR EIGENVAL PROCAR vasprun.xml band_results/ 2>/dev/null || true
echo "All calculations completed!"
