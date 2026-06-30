#!/usr/bin/env bash
# SLURM job: build preference-tail smoke splits from results/best on a compute node.

#SBATCH --job-name=tpc_rank_pref
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=6G
#SBATCH --time=00:20:00
#SBATCH --output=/beegfs/home/users/f/fabimi/china-travel-agent/cache/solve_logs/rank_pref_%j.log

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
TOPK="${TPC_RANK_TOPK:-120}"
SPLIT="${TPC_DF_SPLIT:-tpc_phase1}"
METHOD="${TPC_RANK_METHOD:-best}"

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

RUN() { singularity exec --bind /beegfs --bind /tmp/drive "$BASE_SIF" "$NODE_VENV/bin/python" "$@"; }

echo "[rank-pref] job=$SLURM_JOB_ID host=$(hostname) start=$(date -Is) split=$SPLIT method=$METHOD topk=$TOPK"
RUN scripts/rank_tail.py --split "$SPLIT" --method "$METHOD" --mode preference --pref-metric dav --top-k "$TOPK" --focus-split smoke_dav --report-name smoke_dav_tail_ranking.csv
RUN scripts/rank_tail.py --split "$SPLIT" --method "$METHOD" --mode preference --pref-metric ddr --top-k "$TOPK" --focus-split smoke_ddr --report-name smoke_ddr_tail_ranking.csv
RUN scripts/rank_tail.py --split "$SPLIT" --method "$METHOD" --mode preference --pref-metric att --top-k "$TOPK" --focus-split smoke_att_tail --report-name smoke_att_tail_ranking.csv
RUN scripts/rank_tail.py --split "$SPLIT" --method "$METHOD" --mode unsolved --top-k 40 --focus-split smoke_unsolved --report-name smoke_unsolved_tail_ranking.csv

echo "[rank-pref] done end=$(date -Is)"
