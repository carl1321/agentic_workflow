#!/bin/bash
#SBATCH -J vasp
#SBATCH -N 10
#SBATCH --ntasks-per-node=32
#SBATCH -p test

module purge
module load compiler/intel/2017.5.239
module load mpi/hpcx/2.7.4/intel-2017.5.239

export MKL_DEBUG_CPU_TYPE=5

srun --mpi=pmix_v3 /public/software/apps/vasp/5.4.4/hpcx-2.4.1-intel2017/vasp_std
