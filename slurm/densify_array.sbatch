#!/usr/bin/env bash
# SLURM array job: shard tpc_phase1 across many compute-node tasks and densify one shard per task.
# This avoids login-node compute and avoids one long single-node worker pool. Slurm throttles concurrency.

#SBATCH --job-name=tpc_densify_array
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=02:00:00
#SBATCH --array=0-39%40
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/densify_array_%A_%a.log

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

export TPC_DENSIFY_ATTR_GAP_MIN="${TPC_DENSIFY_ATTR_GAP_MIN:-75}"
export TPC_DENSIFY_ATTR_WIN_OPEN="${TPC_DENSIFY_ATTR_WIN_OPEN:-9}"
export TPC_DENSIFY_ATTR_WIN_CLOSE="${TPC_DENSIFY_ATTR_WIN_CLOSE:-21}"
export TPC_DENSIFY_ATTR_DWELL="${TPC_DENSIFY_ATTR_DWELL:-60}"
export TPC_DENSIFY_ATTR_CANDIDATES="${TPC_DENSIFY_ATTR_CANDIDATES:-24}"
# Window-meal extension (default off): swap a bounding intercity to a wider-window option
# and add the meal it unlocks. Enable with --export=...,TPC_DENSIFY_LATE_DINNER=1,TPC_DENSIFY_EARLY_BREAKFAST=1
export TPC_DENSIFY_LATE_DINNER="${TPC_DENSIFY_LATE_DINNER:-0}"
export TPC_DENSIFY_EARLY_BREAKFAST="${TPC_DENSIFY_EARLY_BREAKFAST:-0}"

BASE_SIF="${TPC_BASE_SIF:-$HOME/sif/python-312-slim.sif}"
VENV_TAR="${TPC_VENV_TAR:-$HOME/sif/tpc-venv.tar}"
PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
BASE_SPLIT="${TPC_DF_SPLIT:-tpc_phase1}"
TASKS="${SLURM_ARRAY_TASK_COUNT:-40}"
TASK_ID="${SLURM_ARRAY_TASK_ID:?missing task id}"
SHARD_SPLIT="_array_${SLURM_ARRAY_JOB_ID}_${TASK_ID}_${BASE_SPLIT}"
SHARD_FILE="$PROJECT/chinatravel/evaluation/default_splits/${SHARD_SPLIT}.txt"

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

awk -v n="$TASKS" -v i="$TASK_ID" 'NF && ((NR-1) % n == i) {print}' "chinatravel/evaluation/default_splits/${BASE_SPLIT}.txt" > "$SHARD_FILE"
COUNT=$(wc -l < "$SHARD_FILE")
start_epoch=$(date +%s)
echo "[densify-array] job=$SLURM_JOB_ID array=$SLURM_ARRAY_JOB_ID task=$TASK_ID host=$(hostname) start=$(date -Is) split=$BASE_SPLIT shard=$SHARD_SPLIT count=$COUNT"
echo "[densify-array] gap_min=$TPC_DENSIFY_ATTR_GAP_MIN win=$TPC_DENSIFY_ATTR_WIN_OPEN-$TPC_DENSIFY_ATTR_WIN_CLOSE dwell=$TPC_DENSIFY_ATTR_DWELL candidates=$TPC_DENSIFY_ATTR_CANDIDATES late_dinner=$TPC_DENSIFY_LATE_DINNER early_breakfast=$TPC_DENSIFY_EARLY_BREAKFAST"

singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/densify.py --split "$SHARD_SPLIT" --workers 1

rm -f "$SHARD_FILE"
end_epoch=$(date +%s)
echo "[densify-array] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
