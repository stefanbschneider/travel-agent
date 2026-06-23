#!/usr/bin/env bash
# SLURM controller job for multi-round tail optimization (iterate_tail.py).
#
# Use via:
#   bash slurm/submit_tail_overnight.sh
#
# Required environment exports are injected by submit_tail_overnight.sh.

#SBATCH --job-name=tpc_tail_overnight
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=6G
#SBATCH --time=07:30:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/tail_overnight_%j.log

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

if [[ ! -f "$BASE_SIF" ]]; then
    echo "missing base SIF: $BASE_SIF" >&2
    exit 2
fi
if [[ ! -f "$VENV_TAR" ]]; then
    echo "missing venv tar: $VENV_TAR" >&2
    exit 2
fi

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

SPLIT="${TPC_TAIL_SPLIT:-tpc_phase1}"
METHOD="${TPC_TAIL_METHOD:-best}"
ROUNDS="${TPC_TAIL_ROUNDS:-8}"
TOPK="${TPC_TAIL_TOPK:-240}"
MIN_SCORE="${TPC_TAIL_MIN_SCORE:-99}"
RESTARTS="${TPC_TAIL_RESTARTS:-1200}"
BUDGET="${TPC_TAIL_BUDGET:-300}"
WORKERS="${TPC_TAIL_WORKERS:-${SLURM_CPUS_PER_TASK:-8}}"
STOP_NO_IMPROVE="${TPC_TAIL_STOP_NO_IMPROVE:-2}"
RUN_ID="${TPC_TAIL_RUN_ID:-tail_hpc_${SLURM_JOB_ID}}"
ARTIFACTS_ROOT="${TPC_TAIL_ARTIFACTS_ROOT:-cache/hpc_tail_runs}"
SEED_PREFIX="${TPC_TAIL_SEED_PREFIX:-tailhpc}"

start_epoch=$(date +%s)
echo "[tail-hpc] job=$SLURM_JOB_ID host=$(hostname) start=$(date -Is)"
echo "[tail-hpc] split=$SPLIT method=$METHOD rounds=$ROUNDS topk=$TOPK min_score=$MIN_SCORE"
echo "[tail-hpc] restarts=$RESTARTS budget=$BUDGET workers=$WORKERS stop_no_improve=$STOP_NO_IMPROVE run_id=$RUN_ID"

singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/iterate_tail.py \
    --split "$SPLIT" \
    --method "$METHOD" \
    --rounds "$ROUNDS" \
    --top-k "$TOPK" \
    --min-score "$MIN_SCORE" \
    --restarts "$RESTARTS" \
    --budget "$BUDGET" \
    --workers "$WORKERS" \
    --stop-no-improve-rounds "$STOP_NO_IMPROVE" \
    --run-id "$RUN_ID" \
    --artifacts-root "$ARTIFACTS_ROOT" \
    --seed-prefix "$SEED_PREFIX"

end_epoch=$(date +%s)
echo "[tail-hpc] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
