#!/usr/bin/env bash
# SLURM array job: shard a split across compute-node tasks and run ghost_densify per shard.
# Writes candidates to an isolated method dir; merge with eval_tpc --update_best only after scoring.

#SBATCH --job-name=tpc_ghost_array
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=6G
#SBATCH --time=01:00:00
#SBATCH --array=0-63%64
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/ghost_array_%A_%a.log

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
BASE_SPLIT="${TPC_GHOST_SPLIT:-tpc_phase1}"
METHOD="${TPC_GHOST_METHOD:-TPCAgent_TPCLLM_en_oracletranslation_ghost_densify}"
MAX_CANDIDATES="${TPC_GHOST_MAX_CANDIDATES:-12}"
TASKS="${SLURM_ARRAY_TASK_COUNT:-64}"
TASK_ID="${SLURM_ARRAY_TASK_ID:?missing task id}"
SHARD_SPLIT="_ghost_array_${SLURM_ARRAY_JOB_ID}_${TASK_ID}_${BASE_SPLIT}"
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
echo "[ghost-array] job=$SLURM_JOB_ID array=$SLURM_ARRAY_JOB_ID task=$TASK_ID host=$(hostname) start=$(date -Is) split=$BASE_SPLIT shard=$SHARD_SPLIT count=$COUNT method=$METHOD max_candidates=$MAX_CANDIDATES"

singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/ghost_densify.py \
    --split "$SHARD_SPLIT" --method "$METHOD" --workers 1 --max-candidates "$MAX_CANDIDATES"

rm -f "$SHARD_FILE"
end_epoch=$(date +%s)
echo "[ghost-array] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
