#!/usr/bin/env bash
# SLURM job: monotonic merge current method outputs into results/best, then score.
# Use after a densify/solve job; safe to run repeatedly because eval_tpc --update_best is per-query monotonic.

#SBATCH --job-name=tpc_merge_score
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/merge_score_%j.log

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
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export MALLOC_ARENA_MAX=2

BASE_SIF="${TPC_BASE_SIF:-$HOME/sif/python-312-slim.sif}"
VENV_TAR="${TPC_VENV_TAR:-$HOME/sif/tpc-venv.tar}"
PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
SPLIT="${TPC_DF_SPLIT:-tpc_phase1}"

if [[ ! -f "$BASE_SIF" ]]; then echo "missing base SIF: $BASE_SIF" >&2; exit 2; fi
if [[ ! -f "$VENV_TAR" ]]; then echo "missing venv tar: $VENV_TAR" >&2; exit 2; fi

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

start_epoch=$(date +%s)
echo "[merge-score] job=$SLURM_JOB_ID host=$(hostname) start=$(date -Is) split=$SPLIT"
RUN() { singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" "$@"; }

echo "[merge-score] === monotonic merge ==="
RUN scripts/merge.py --split "$SPLIT"

echo "[merge-score] === score ==="
RUN scripts/score.py --split "$SPLIT"

end_epoch=$(date +%s)
echo "[merge-score] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
