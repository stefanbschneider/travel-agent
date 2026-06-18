#!/usr/bin/env bash
# Full-suite Slurm array runner for the deterministic TPC light solver pass.
#
# Recommended entrypoint:
#   bash slurm/submit_full_suite_array.sh
#
# Direct submission also works if the shard splits already exist:
#   sbatch slurm/full_suite_array.sbatch
#
# Resource defaults are deliberately modest and measured from the green 8-worker
# probe/full-suite measurements (MaxRSS ~2.7 GB): 32 shards x 8 CPUs, 4G RAM, ~12 min wall (1000/32 ~= 31 queries/shard, ~half the 16-shard time), no GPU, no exclusive node.
#SBATCH --job-name=tpc_full
#SBATCH --partition=standard
#SBATCH --array=0-31%32
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=4G
#SBATCH --time=00:12:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/full_suite_%A_%a.log

set -euo pipefail

# Batch shells do not always define `module`; source the modules init explicitly.
source /usr/share/modules/init/bash
module purge
module load singularity/4.4

# FUSE-mount over BeeGFS ($HOME) is forbidden, forcing a slow per-exec SIF extraction.
# Point the cache/tmp at node-local xfs (/tmp/drive) so squashfuse mounts directly.
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

# Make the light CP-SAT path explicit and bounded.
export TPC_USE_CP_SOLVER=1
export TPC_CP_SEARCH_WORKERS=1
unset TPC_CP_FORCE
unset TPC_CP_TIME_LIMIT_SEC

BASE_SIF="$HOME/sif/python-312-slim.sif"
VENV_TAR="$HOME/sif/tpc-venv.tar"
PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
cd "$PROJECT"

SPLIT_PREFIX="${TPC_FULL_PREFIX:-_cluster_full}"
WORKERS="${TPC_FULL_WORKERS:-${SLURM_CPUS_PER_TASK:-8}}"
RESTARTS="${TPC_FULL_RESTARTS:-40}"
BUDGET="${TPC_FULL_BUDGET:-30}"
SPLIT=$(printf '%s_%02d' "$SPLIT_PREFIX" "$SLURM_ARRAY_TASK_ID")
SPLIT_FILE="chinatravel/evaluation/default_splits/${SPLIT}.txt"

if [[ ! -f "$BASE_SIF" ]]; then
    echo "missing base SIF: $BASE_SIF" >&2
    exit 2
fi
if [[ ! -f "$VENV_TAR" ]]; then
    echo "missing venv tar: $VENV_TAR" >&2
    exit 2
fi
if [[ ! -f "$SPLIT_FILE" ]]; then
    echo "missing split file: $SPLIT_FILE" >&2
    exit 2
fi

QUERY_COUNT=$(wc -l < "$SPLIT_FILE")
start_epoch=$(date +%s)
echo "[full] array_job=$SLURM_ARRAY_JOB_ID task=$SLURM_ARRAY_TASK_ID job=$SLURM_JOB_ID host=$(hostname) start=$(date -Is)"
echo "[full] split=$SPLIT queries=$QUERY_COUNT workers=$WORKERS cpus=$SLURM_CPUS_PER_TASK mem=${SLURM_MEM_PER_NODE:-unknown}MB restarts=$RESTARTS budget=$BUDGET"
echo "[full] base=$BASE_SIF venv_tar=$VENV_TAR"

# Stage the solver venv to node-local scratch once per node. BeeGFS small-file
# walks are slow; extracting one sequential tarball avoids a 158s cp -a metadata
# walk. flock + atomic mv => stage exactly once; pyvenv.cfg is the staged-marker.
NODE_VENV="/tmp/drive/$USER/tpc-venv"
mkdir -p "/tmp/drive/$USER"
exec 9>"/tmp/drive/$USER/.venv_stage.lock"
flock 9
if [[ ! -e "$NODE_VENV/pyvenv.cfg" ]]; then
    rm -rf "$NODE_VENV.tmp" "$NODE_VENV.stage"
    mkdir -p "$NODE_VENV.stage"
    tar -C "$NODE_VENV.stage" -xf "$VENV_TAR"
    mv "$NODE_VENV.stage/tpc-venv" "$NODE_VENV"      # atomic publish
    rm -rf "$NODE_VENV.stage"
fi
flock -u 9

singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" -c \
    "import sys; print('[full] python', sys.version.split()[0], sys.executable)"

singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" scripts/solve.py \
    --split "$SPLIT" \
    --workers "$WORKERS" \
    --restarts "$RESTARTS" \
    --budget "$BUDGET" \
    --seed-salt "clusterfull-${SLURM_ARRAY_JOB_ID}-${SLURM_ARRAY_TASK_ID}"

end_epoch=$(date +%s)
echo "[full] done task=$SLURM_ARRAY_TASK_ID elapsed_sec=$((end_epoch - start_epoch)) end=$(date -Is)"
