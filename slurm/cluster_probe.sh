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

# Batch shells do not always define `module`; source the modules init explicitly.
source /usr/share/modules/init/bash

module purge
module load singularity/4.4

BASE_SIF="$HOME/sif/python-312-slim.sif"
VENV_TAR="$HOME/sif/tpc-venv.tar"   # packed venv for fast node-local staging
if [[ ! -f "$VENV_TAR" ]]; then
    echo "missing venv tar: $VENV_TAR" >&2
    exit 2
fi

# Singularity/apptainer cache on shared BeeGFS so pulls are reused across nodes.
export APPTAINER_CACHEDIR="$HOME/.apptainer/cache"
export SINGULARITY_CACHEDIR="$HOME/.apptainer/cache"

PROJECT=/beegfs/home/users/f/fabimi/china-travel-agent
cd "$PROJECT"

# Stage the solver venv to node-local scratch once per node. BeeGFS small-file
# walks are slow; extracting one sequential tarball avoids cp -a metadata churn.
# flock + atomic mv => stage exactly once; pyvenv.cfg is the staged-marker.
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

python_in_img() {
    singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" "$@"
}

echo "[probe] host=$(hostname) date=$(date -Is)"
echo "[probe] base=$BASE_SIF venv_tar=$VENV_TAR"
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
