#!/usr/bin/env bash
# Cluster solver viability probe.
#
# Runs the deterministic TPCAgent/CP-SAT solver on the 12-query _cluster_probe
# split on a compute node, using the rootless Singularity runtime built by
# slurm/build_image.sh (base python:3.12-slim SIF + bind-mounted 3.12 venv).
# Writes only to results/TPCAgent_TPCLLM_en_oracletranslation/ (the transient
# dir that `make clean-light` removes); it does NOT run merge.py, so results/best
# and submissions/ are never touched.
#
# Prereqs (frontend, once):
#   bash slurm/build_image.sh
#SBATCH --job-name=tpc_probe
#SBATCH --partition=standard
#SBATCH --cpus-per-task=8
#SBATCH --time=00:20:00
#SBATCH --output=cache/solve_logs/cluster_probe_%j.log

set -euo pipefail

module purge
module load singularity/4.4

BASE_SIF="$HOME/sif/python-312-slim.sif"
TPC_VENV="$HOME/tpc-venv"   # on shared BeeGFS via $HOME

# Singularity/apptainer cache on shared BeeGFS so pulls are reused across nodes.
export APPTAINER_CACHEDIR="$HOME/.apptainer/cache"
export SINGULARITY_CACHEDIR="$HOME/.apptainer/cache"

PROJECT=/beegfs/home/users/f/fabimi/china-travel-agent
cd "$PROJECT"

python_in_img() {
    singularity exec --bind /beegfs "$BASE_SIF" "$TPC_VENV/bin/python" "$@"
}

echo "[probe] host=$(hostname) date=$(date -Is)"
echo "[probe] base=$BASE_SIF venv=$TPC_VENV"
echo "[probe] interpreter: $(python_in_img -c 'import sys; print(sys.version.split()[0], sys.executable)')"

# solve.py with --workers 8 auto-sets TPC_CP_SEARCH_WORKERS=1, so each CP-SAT
# instance is single-threaded: 8 workers x 1 thread == --cpus-per-task=8.
python_in_img scripts/solve.py \
    --split _cluster_probe \
    --workers 8 \
    --restarts 40 \
    --budget 30 \
    --seed-salt clusterprobe

echo "[probe] done date=$(date -Is)"
