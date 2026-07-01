#!/usr/bin/env bash
# Checker-gated ghost preference densify on an explicit split. Writes to an isolated method dir.
# Usage: sbatch --export=ALL,TPC_GHOST_SPLIT=...,TPC_GHOST_METHOD=... slurm/ghost_densify.sbatch

#SBATCH --job-name=tpc_ghost_df
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:45:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/ghost_df_%j.log

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
SPLIT="${TPC_GHOST_SPLIT:-stale_pref_smoke}"
METHOD="${TPC_GHOST_METHOD:-TPCAgent_TPCLLM_en_oracletranslation_ghost_densify}"
WORKERS="${TPC_GHOST_WORKERS:-4}"
MAX_CANDIDATES="${TPC_GHOST_MAX_CANDIDATES:-24}"

ATTR_CAP="${TPC_GHOST_ATTR_CAP:-4}"
ATTR_SLOTS="${TPC_GHOST_ATTR_SLOTS:-09:00-10:00,10:15-11:15,14:00-15:00,15:15-16:15,16:30-17:30,19:30-20:30}"
MEAL_DURATION="${TPC_GHOST_MEAL_DURATION:-60}"
ATTR_WINDOW_OPEN="${TPC_GHOST_ATTR_WINDOW_OPEN:-09:00}"
ATTR_WINDOW_CLOSE="${TPC_GHOST_ATTR_WINDOW_CLOSE:-21:00}"
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
echo "[ghost-df] job=$SLURM_JOB_ID host=$(hostname) split=$SPLIT method=$METHOD workers=$WORKERS max_candidates=$MAX_CANDIDATES attr_cap=$ATTR_CAP meal_duration=$MEAL_DURATION attr_slots=$ATTR_SLOTS attr_window=$ATTR_WINDOW_OPEN-$ATTR_WINDOW_CLOSE start=$(date -Is)"
singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/ghost_densify.py \
    --split "$SPLIT" --method "$METHOD" --workers "$WORKERS" --max-candidates "$MAX_CANDIDATES" --attr-cap "$ATTR_CAP" --attr-slots "$ATTR_SLOTS" --meal-duration "$MEAL_DURATION" --attr-window-open "$ATTR_WINDOW_OPEN" --attr-window-close "$ATTR_WINDOW_CLOSE"
end_epoch=$(date +%s)
echo "[ghost-df] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
