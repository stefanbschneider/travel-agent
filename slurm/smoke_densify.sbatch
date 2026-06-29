#!/usr/bin/env bash
# Single-node smoke densify on a small split with tunable env knobs. Writes to an ISOLATED
# method dir (TPC_SMOKEMETHOD) so it never touches results/best or the canonical method dir.
# Usage: sbatch --export=ALL,TPC_SMOKESPLIT=smoke_ddr,TPC_SMOKEMETHOD=..._smoke_ddr_v2,... slurm/smoke_densify.sbatch

#SBATCH --job-name=tpc_smoke_df
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=6G
#SBATCH --time=00:45:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/smoke_df_%j.log

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

# Densify knobs (defaults match densify_array.sbatch; override via --export)
export TPC_DENSIFY_ATTR_GAP_MIN="${TPC_DENSIFY_ATTR_GAP_MIN:-75}"
export TPC_DENSIFY_ATTR_WIN_OPEN="${TPC_DENSIFY_ATTR_WIN_OPEN:-9}"
export TPC_DENSIFY_ATTR_WIN_CLOSE="${TPC_DENSIFY_ATTR_WIN_CLOSE:-21}"
export TPC_DENSIFY_ATTR_DWELL="${TPC_DENSIFY_ATTR_DWELL:-60}"
export TPC_DENSIFY_ATTR_CANDIDATES="${TPC_DENSIFY_ATTR_CANDIDATES:-24}"
export TPC_DENSIFY_LATE_DINNER="${TPC_DENSIFY_LATE_DINNER:-0}"
export TPC_DENSIFY_EARLY_BREAKFAST="${TPC_DENSIFY_EARLY_BREAKFAST:-0}"

BASE_SIF="${TPC_BASE_SIF:-$HOME/sif/python-312-slim.sif}"
VENV_TAR="${TPC_VENV_TAR:-$HOME/sif/tpc-venv.tar}"
PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
SPLIT="${TPC_SMOKESPLIT:-smoke_ddr}"
METHOD="${TPC_SMOKEMETHOD:-TPCAgent_TPCLLM_en_oracletranslation_smoke_tmp}"

cd "$PROJECT"
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
echo "[smoke-df] job=$SLURM_JOB_ID host=$(hostname) start=$(date -Is) split=$SPLIT method=$METHOD"
echo "[smoke-df] gap=$TPC_DENSIFY_ATTR_GAP_MIN win=$TPC_DENSIFY_ATTR_WIN_OPEN-$TPC_DENSIFY_ATTR_WIN_CLOSE dwell=$TPC_DENSIFY_ATTR_DWELL cand=$TPC_DENSIFY_ATTR_CANDIDATES late_dinner=$TPC_DENSIFY_LATE_DINNER early_bfast=$TPC_DENSIFY_EARLY_BREAKFAST"

singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/densify.py \
    --split "$SPLIT" --method "$METHOD" --workers 4

end_epoch=$(date +%s)
echo "[smoke-df] done elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
