#!/usr/bin/env bash
# Smoke A/B for the gated transport-mode upgrade (ATT lever).
# Pre-populates the method dir from results/best for the smoke UIDs (baseline), runs densify
# (which now also upgrades transport modes), then evals CANDIDATE (method dir) vs BASELINE (best)
# WITHOUT --update_best, so results/best is never mutated. Pure measurement.

#SBATCH --job-name=tpc_smoke_att
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/smoke_att_%j.log

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
SPLIT="${TPC_SMOKE_SPLIT:-smoke_att}"
METHOD="TPCAgent_TPCLLM_en_oracletranslation"

if [[ ! -f "$BASE_SIF" ]]; then echo "missing base SIF: $BASE_SIF" >&2; exit 2; fi
if [[ ! -f "$VENV_TAR" ]]; then echo "missing venv tar: $VENV_TAR" >&2; exit 2; fi

cd "$PROJECT"
mkdir -p "$PROJECT/cache/solve_logs" "results/${METHOD}"

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

PY() { singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" "$@"; }

echo "[smoke-att] === py_compile ==="
PY -m py_compile chinatravel/agent/tpc_agent/tpc_agent.py scripts/densify.py

echo "[smoke-att] === stage baseline candidates (best -> method dir) ==="
while read -r uid; do
    [[ -z "$uid" ]] && continue
    if [[ -f "results/best/${uid}.json" ]]; then
        cp -f "results/best/${uid}.json" "results/${METHOD}/${uid}.json"
    else
        rm -f "results/${METHOD}/${uid}.json"
    fi
done < "chinatravel/evaluation/default_splits/${SPLIT}.txt"

start_epoch=$(date +%s)
echo "[smoke-att] job=$SLURM_JOB_ID host=$(hostname) start=$(date -Is) split=$SPLIT"
echo "[smoke-att] === densify (with gated mode upgrade) ==="
PY scripts/densify.py --split "$SPLIT" --workers 4

echo "[smoke-att] === eval CANDIDATE (method dir, no update_best) ==="
PY eval_tpc.py --splits "$SPLIT" --method "$METHOD" --lang en

echo "[smoke-att] === eval BASELINE (best, no update_best) ==="
PY eval_tpc.py --splits "$SPLIT" --method best --lang en

end_epoch=$(date +%s)
echo "[smoke-att] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
