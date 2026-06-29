#!/usr/bin/env bash
# Compare a sparse smoke method against results/best on a compute node. Read-only.
# Usage: sbatch --export=ALL,TPC_COMPARE_METHOD=... slurm/compare_method.sbatch

#SBATCH --job-name=tpc_cmp_method
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/compare_method_%j.log

set -euo pipefail

source /usr/share/modules/init/bash
module purge
module load singularity/4.4

export APPTAINER_CACHEDIR="/tmp/drive/$USER/apptainer"
export APPTAINER_TMPDIR="/tmp/drive/$USER/apptainer-tmp"
export SINGULARITY_CACHEDIR="$APPTAINER_CACHEDIR"
export SINGULARITY_TMPDIR="$APPTAINER_TMPDIR"
mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"

export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 MALLOC_ARENA_MAX=2

BASE_SIF="${TPC_BASE_SIF:-$HOME/sif/python-312-slim.sif}"
VENV_TAR="${TPC_VENV_TAR:-$HOME/sif/tpc-venv.tar}"
PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
METHOD="${TPC_COMPARE_METHOD:?missing TPC_COMPARE_METHOD}"
DENOM="${TPC_COMPARE_DENOMINATOR:-1000}"

cd "$PROJECT"
mkdir -p "$PROJECT/cache/solve_logs"

NODE_VENV="/tmp/drive/$USER/tpc-venv"
mkdir -p "/tmp/drive/$USER"
exec 9>"/tmp/drive/$USER/.venv_stage.lock"
flock 9
if [[ ! -e "$NODE_VENV/pyvenv.cfg" ]]; then
    rm -rf "$NODE_VENV.tmp" "$NODE_VENV.stage"
    mkdir -p "$NODE_VENV.stage"
    tar -C "$NODE_VENV.stage" -xf "$VENV_TAR"
    mv "$NODE_VENV.stage/tpc-venv" "$NODE_VENV"
    rm -rf "$NODE_VENV.stage"
fi
flock -u 9

echo "[compare-method] job=$SLURM_JOB_ID host=$(hostname) method=$METHOD start=$(date -Is)"
singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/compare_method_to_best.py --method "$METHOD" --denominator "$DENOM"
echo "[compare-method] done end=$(date -Is)"
