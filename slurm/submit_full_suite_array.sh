#!/usr/bin/env bash
# Prepare balanced full-suite shards and submit solve+per-shard-merge array jobs.
#
# Defaults target the current cluster without over-asking:
#   64 array tasks x 8 CPUs = up to 512 CPUs
#   4G RAM per task (8 workers), based on the 8-worker probe MaxRSS ~2.6G
#   20m wall time per task (conservative for solve plus per-shard merge/eval)
#
# Tunables:
#   SHARDS=64 CONCURRENCY=64 WORKERS=8 MEM=4G TIME=00:20:00 PARTITION=standard \
#   RESTARTS=40 BUDGET=30 SPLIT_SOURCE=tpc_phase1 SPLIT_PREFIX=_cluster_full \
#   CLEAN=1 bash slurm/submit_full_suite_array.sh
set -euo pipefail

PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
SPLIT_DIR="$PROJECT/chinatravel/evaluation/default_splits"
SHARDS="${SHARDS:-64}"
CONCURRENCY="${CONCURRENCY:-$SHARDS}"
WORKERS="${WORKERS:-8}"
MEM="${MEM:-4G}"
TIME="${TIME:-00:20:00}"
PARTITION="${PARTITION:-standard}"
RESTARTS="${RESTARTS:-40}"
BUDGET="${BUDGET:-30}"
SPLIT_SOURCE="${SPLIT_SOURCE:-tpc_phase1}"
SPLIT_PREFIX="${SPLIT_PREFIX:-_cluster_full}"
CLEAN="${CLEAN:-1}"
PYTHON_BIN="${PYTHON:-python3}"

cd "$PROJECT"
mkdir -p "$PROJECT/cache/solve_logs"

if [[ "$CLEAN" == "1" ]]; then
    make clean-light
fi
rm -f "$SPLIT_DIR"/"${SPLIT_PREFIX}"_*.txt

"$PYTHON_BIN" - <<PY
from pathlib import Path
split_dir = Path(${SPLIT_DIR@Q})
source = ${SPLIT_SOURCE@Q}
prefix = ${SPLIT_PREFIX@Q}
shards = int(${SHARDS@Q})
uids = [line.strip() for line in (split_dir / f"{source}.txt").read_text().splitlines() if line.strip()]
if not uids:
    raise SystemExit(f"empty source split: {source}")
counts = []
for i in range(shards):
    shard = uids[i::shards]
    counts.append(len(shard))
    (split_dir / f"{prefix}_{i:02d}.txt").write_text("\n".join(shard) + "\n")
print({"source": source, "prefix": prefix, "shards": shards, "total": sum(counts), "min": min(counts), "max": max(counts), "counts": counts})
PY

ARRAY_SPEC="0-$((SHARDS - 1))%${CONCURRENCY}"
EXPORTS="ALL,TPC_FULL_PREFIX=${SPLIT_PREFIX},TPC_FULL_WORKERS=${WORKERS},TPC_FULL_RESTARTS=${RESTARTS},TPC_FULL_BUDGET=${BUDGET},TPC_PROJECT_DIR=${PROJECT}"

echo "Submitting full-suite array: partition=$PARTITION array=$ARRAY_SPEC workers=$WORKERS mem=$MEM time=$TIME restarts=$RESTARTS budget=$BUDGET"
JOB=$(sbatch --parsable \
    --partition "$PARTITION" \
    --output="$PROJECT/cache/solve_logs/full_suite_%A_%a.log" \
    --array "$ARRAY_SPEC" \
    --cpus-per-task "$WORKERS" \
    --mem "$MEM" \
    --time "$TIME" \
    --export "$EXPORTS" \
    slurm/full_suite_array.sbatch)

echo "$JOB" > cache/solve_logs/.full_suite_array_jobid
echo "JOBID=$JOB"
squeue -j "$JOB" -o '%i %P %j %u %T %M %D %R'
