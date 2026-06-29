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
ATTR_CAP="${ATTR_CAP:-}"
REST_CAP="${REST_CAP:-}"
HOTEL_CAP="${HOTEL_CAP:-}"
CP_TIME_LIMIT="${CP_TIME_LIMIT:-}"
CP_FORCE="${CP_FORCE:-}"
LATE_RETURN="${LATE_RETURN:-}"
EARLY_ARRIVAL="${EARLY_ARRIVAL:-}"
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

SHARD_COUNT="$("$PYTHON_BIN" - <<PY
from pathlib import Path
import sys

split_dir = Path(${SPLIT_DIR@Q})
source = ${SPLIT_SOURCE@Q}
prefix = ${SPLIT_PREFIX@Q}
requested_shards = int(${SHARDS@Q})
uids = [line.strip() for line in (split_dir / f"{source}.txt").read_text().splitlines() if line.strip()]
if not uids:
    raise SystemExit(f"empty source split: {source}")
shard_count = min(requested_shards, len(uids))
counts = []
for i in range(shard_count):
    shard = uids[i::shard_count]
    counts.append(len(shard))
    (split_dir / f"{prefix}_{i:02d}.txt").write_text("\n".join(shard) + "\n")
print({"source": source, "prefix": prefix, "requested_shards": requested_shards, "shards": shard_count, "total": sum(counts), "min": min(counts), "max": max(counts), "counts": counts}, file=sys.stderr)
print(shard_count)
PY
)"

if (( SHARD_COUNT < 1 )); then
    echo "empty effective shard count for $SPLIT_SOURCE" >&2
    exit 2
fi
ARRAY_CONCURRENCY="$CONCURRENCY"
if (( ARRAY_CONCURRENCY > SHARD_COUNT )); then
    ARRAY_CONCURRENCY="$SHARD_COUNT"
fi
ARRAY_SPEC="0-$((SHARD_COUNT - 1))%${ARRAY_CONCURRENCY}"
EXPORTS="ALL,TPC_FULL_PREFIX=${SPLIT_PREFIX},TPC_FULL_WORKERS=${WORKERS},TPC_FULL_RESTARTS=${RESTARTS},TPC_FULL_BUDGET=${BUDGET},TPC_PROJECT_DIR=${PROJECT}"
if [[ -n "$ATTR_CAP" ]]; then EXPORTS="${EXPORTS},TPC_FULL_ATTR_CAP=${ATTR_CAP}"; fi
if [[ -n "$REST_CAP" ]]; then EXPORTS="${EXPORTS},TPC_FULL_REST_CAP=${REST_CAP}"; fi
if [[ -n "$HOTEL_CAP" ]]; then EXPORTS="${EXPORTS},TPC_FULL_HOTEL_CAP=${HOTEL_CAP}"; fi
if [[ -n "$CP_TIME_LIMIT" ]]; then EXPORTS="${EXPORTS},TPC_FULL_CP_TIME_LIMIT=${CP_TIME_LIMIT}"; fi
if [[ -n "$CP_FORCE" ]]; then EXPORTS="${EXPORTS},TPC_FULL_CP_FORCE=${CP_FORCE}"; fi
if [[ -n "$LATE_RETURN" ]]; then EXPORTS="${EXPORTS},TPC_INTERCITY_LATE_RETURN=${LATE_RETURN}"; fi
if [[ -n "$EARLY_ARRIVAL" ]]; then EXPORTS="${EXPORTS},TPC_INTERCITY_EARLY_ARRIVAL=${EARLY_ARRIVAL}"; fi

echo "Submitting full-suite array: partition=$PARTITION array=$ARRAY_SPEC workers=$WORKERS mem=$MEM time=$TIME restarts=$RESTARTS budget=$BUDGET attr_cap=${ATTR_CAP:-default} rest_cap=${REST_CAP:-default} hotel_cap=${HOTEL_CAP:-default} cp_time_limit=${CP_TIME_LIMIT:-default} cp_force=${CP_FORCE:-unset}"
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
