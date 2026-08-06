#!/bin/bash
# Paired e2e arms for the 2026-08-06 parser phrasing fix (ladder step 3).
# Same shape as the generalization probe's §4 runs: n=30, --total-budget-sec 1800, --workers 3,
# lang en, zero LLM calls. Sequential, never overlapping, so neither arm steals the other's CPU.
set -u
ROOT="/Users/stefanshschneider/Projects/private/china-travel-agent"
cd "$ROOT" || exit 1
OUT="results/phase2_baselines/screens/20260806_parser_phrasing_fix/e2e"
PY=".venv/bin/python"
mkdir -p "$OUT"

# --- fresh 30-uid splits -----------------------------------------------------
head -30 chinatravel/evaluation/default_splits/tpc_phase2_familiar_100.txt \
    > chinatravel/evaluation/default_splits/probe2_fam30.txt
HF_HUB_OFFLINE=1 $PY scripts/materialize_hf_split.py --hf-split medium \
    --name hf_medium_probe30 --limit 30 > "$OUT/materialize.log" 2>&1

rm -rf results/probe2_fam30 results/probe2_hfmedium30
rm -rf agent_env/runs/probe2_fam30 agent_env/runs/probe2_hfmedium30

# --- arm 1: hf_medium first-30 (the arm that must move 41.62 -> >50) --------
echo "=== arm1 hf_medium start $(date +%H:%M:%S) ==="
HF_HUB_OFFLINE=1 $PY agent_env/scripts/solve_phase2.py --split hf_medium_probe30 \
    --method probe2_hfmedium30 --total-budget-sec 1800 --workers 3 \
    > "$OUT/solve_hfmedium30.log" 2>&1
HF_HUB_OFFLINE=1 $PY eval_tpc.py --splits hf_medium_probe30 --method probe2_hfmedium30 \
    > "$OUT/eval_hfmedium30.log" 2>&1
echo "=== arm1 done $(date +%H:%M:%S) ==="

# --- arm 2: familiar-100 first-30 control (must hold at 64.57 +/- 1) -------
echo "=== arm2 familiar start $(date +%H:%M:%S) ==="
$PY agent_env/scripts/solve_phase2.py --split probe2_fam30 \
    --method probe2_fam30 --total-budget-sec 1800 --workers 3 \
    > "$OUT/solve_fam30.log" 2>&1
$PY eval_tpc.py --splits probe2_fam30 --method probe2_fam30 \
    > "$OUT/eval_fam30.log" 2>&1
echo "=== arm2 done $(date +%H:%M:%S) ==="

# --- keep the scheduler summaries as evidence ------------------------------
for m in probe2_hfmedium30 probe2_fam30; do
    mkdir -p "$OUT/$m"
    cp agent_env/runs/$m/*_summary.json "$OUT/$m/" 2>/dev/null
done
echo "ALL DONE $(date +%H:%M:%S)"
