#!/usr/bin/env bash
set -euo pipefail

SCRATCH="/tmp/claude-0/-root-china-travel-agent/80de9538-3fe8-408a-b5af-fd086d0dd2c3/scratchpad"
ROOT="/root/china-travel-agent"
PRE="$SCRATCH/r26_pre_p20"
PY="$ROOT/.venv/bin/python"
LOGDIR="$SCRATCH/logs"
mkdir -p "$LOGDIR"

split_uids () {
  # split_uids <src_file> <n_shards> <out_prefix>
  local src=$1 n=$2 prefix=$3
  for i in $(seq 0 $((n-1))); do : > "${prefix}_$i.txt"; done
  local i=0
  while IFS= read -r uid; do
    [ -z "$uid" ] && continue
    echo "$uid" >> "${prefix}_$((i % n)).txt"
    i=$((i+1))
  done < "$src"
}

run_arm () {
  # run_arm <tree_dir> <label> <split> <uids_file_relpath> <n_shards> <budget_sec>
  local tree=$1 label=$2 split=$3 uids_relpath=$4 nshards=$5 budget=$6
  local method="phase2_e2e_r26_${label}_${split}"
  echo "=== ARM: $method (tree=$tree, budget=${budget}s, shards=$nshards) ==="
  local shard_prefix="$LOGDIR/${method}_shard"
  split_uids "$tree/$uids_relpath" "$nshards" "$shard_prefix"
  local pids=()
  for i in $(seq 0 $((nshards-1))); do
    local shard_file="${shard_prefix}_$i.txt"
    if [ -s "$shard_file" ]; then
      (
        cd "$tree"
        HF_HUB_OFFLINE=1 "$PY" agent_env/scripts/solve_phase2.py \
          --split "$split" --uids-file "$shard_file" \
          --method "$method" --budget-sec "$budget" --lang en \
          > "$LOGDIR/${method}_shard${i}.log" 2>&1
      ) &
      pids+=($!)
    fi
  done
  local fail=0
  for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
  done
  if [ "$fail" -ne 0 ]; then
    echo "!!! ARM $method had a failing shard; check $LOGDIR/${method}_shard*.log"
    return 1
  fi
  echo "=== ARM $method done ==="
}

# Sequential arms only -- never overlap across arms on this 4-core box (advisor gate #2).
run_arm "$PRE"  "baseline"  "r26_p20_target3"        "chinatravel/evaluation/default_splits/r26_p20_target3.txt"        3 90
run_arm "$PRE"  "baseline"  "r26_familiar_first30"   "chinatravel/evaluation/default_splits/r26_familiar_first30.txt"   3 90
run_arm "$ROOT" "candidate" "r26_p20_target3"        "chinatravel/evaluation/default_splits/r26_p20_target3.txt"        3 90
run_arm "$ROOT" "candidate" "r26_familiar_first30"   "chinatravel/evaluation/default_splits/r26_familiar_first30.txt"   3 90

echo "ALL ARMS DONE"
