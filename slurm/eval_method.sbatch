#!/usr/bin/env bash
# Evaluate one method on one split on a compute node. Read-only.
# Usage: sbatch --export=ALL,TPC_EVAL_SPLIT=fpr_edge_one,TPC_EVAL_METHOD=... slurm/eval_method.sbatch

#SBATCH --job-name=tpc_eval_method
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/eval_method_%j.log

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
SPLIT="${TPC_EVAL_SPLIT:?missing TPC_EVAL_SPLIT}"
METHOD="${TPC_EVAL_METHOD:?missing TPC_EVAL_METHOD}"

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

echo "[eval-method] job=$SLURM_JOB_ID host=$(hostname) split=$SPLIT method=$METHOD start=$(date -Is)"
singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" eval_tpc.py --splits "$SPLIT" --method "$METHOD" --lang en
echo "[eval-method] done end=$(date -Is)"
