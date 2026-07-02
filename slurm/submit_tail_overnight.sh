#!/usr/bin/env bash
# Submit one long overnight tail-iterate controller job to SLURM.
#
# Example:
#   PARTITION=standard WORKERS=8 MEM=6G TIME=07:30:00 \
#   ROUNDS=8 TOPK=240 MIN_SCORE=99 RESTARTS=1200 BUDGET=300 STOP_NO_IMPROVE=2 \
#   RUN_ID=tail_hpc_$(date +%Y%m%d_%H%M%S) \
#   bash slurm/submit_tail_overnight.sh

set -euo pipefail

# Accept config as positional KEY=VALUE args (the Makefile passes them this way)
# in addition to the documented environment-variable form.
for _kv in "$@"; do
    case "$_kv" in
        *=*) export "$_kv" ;;
    esac
done

PROJECT="${TPC_PROJECT_DIR:-/beegfs/home/users/f/fabimi/china-travel-agent}"
cd "$PROJECT"
mkdir -p cache/solve_logs

PARTITION="${PARTITION:-standard}"
WORKERS="${WORKERS:-8}"
MEM="${MEM:-6G}"
TIME="${TIME:-07:30:00}"

SPLIT="${SPLIT:-tpc_phase1}"
METHOD="${METHOD:-best}"
RANK_MODE="${RANK_MODE:-tail}"
PREF_METRIC="${PREF_METRIC:-overall}"
RUNNER="${RUNNER:-solve}"
ROUNDS="${ROUNDS:-8}"
TOPK="${TOPK:-240}"
MIN_SCORE="${MIN_SCORE:-99}"
RESTARTS="${RESTARTS:-1200}"
BUDGET="${BUDGET:-300}"
STOP_NO_IMPROVE="${STOP_NO_IMPROVE:-2}"
RUN_ID="${RUN_ID:-tail_hpc_$(date +%Y%m%d_%H%M%S)}"
ARTIFACTS_ROOT="${ARTIFACTS_ROOT:-cache/hpc_tail_runs}"
SEED_PREFIX="${SEED_PREFIX:-tailhpc}"
TPC_USE_CP_SOLVER="${TPC_USE_CP_SOLVER:-1}"
TPC_CP_AFTER_PASS="${TPC_CP_AFTER_PASS:-1}"
TPC_CP_FOUR_SLOT_SHARE="${TPC_CP_FOUR_SLOT_SHARE:-0.75}"
TPC_CP_FOUR_SLOT_ROUNDS="${TPC_CP_FOUR_SLOT_ROUNDS:-2}"
TPC_CP_RECON_SHUFFLES="${TPC_CP_RECON_SHUFFLES:-0}"
LLM_PREF_LLM="${LLM_PREF_LLM:-gpt-4o}"
LLM_PREF_METHOD="${LLM_PREF_METHOD:-TPCAgent_TPCLLM_en_oracletranslation_llm_pref}"
LLM_PREF_CANDIDATE_MODE="${LLM_PREF_CANDIDATE_MODE:-safe}"
LLM_PREF_PASSES="${LLM_PREF_PASSES:-2}"
LLM_PREF_MAX_CANDIDATES="${LLM_PREF_MAX_CANDIDATES:-24}"

BASE_SIF="${BASE_SIF:-$HOME/sif/python-312-slim.sif}"
VENV_TAR="${VENV_TAR:-$HOME/sif/tpc-venv.tar}"

EXPORTS="ALL,TPC_PROJECT_DIR=${PROJECT},TPC_BASE_SIF=${BASE_SIF},TPC_VENV_TAR=${VENV_TAR},TPC_TAIL_SPLIT=${SPLIT},TPC_TAIL_METHOD=${METHOD},TPC_TAIL_RANK_MODE=${RANK_MODE},TPC_TAIL_PREF_METRIC=${PREF_METRIC},TPC_TAIL_RUNNER=${RUNNER},TPC_TAIL_ROUNDS=${ROUNDS},TPC_TAIL_TOPK=${TOPK},TPC_TAIL_MIN_SCORE=${MIN_SCORE},TPC_TAIL_RESTARTS=${RESTARTS},TPC_TAIL_BUDGET=${BUDGET},TPC_TAIL_WORKERS=${WORKERS},TPC_TAIL_STOP_NO_IMPROVE=${STOP_NO_IMPROVE},TPC_TAIL_RUN_ID=${RUN_ID},TPC_TAIL_ARTIFACTS_ROOT=${ARTIFACTS_ROOT},TPC_TAIL_SEED_PREFIX=${SEED_PREFIX},TPC_TAIL_LLM_PREF_LLM=${LLM_PREF_LLM},TPC_TAIL_LLM_PREF_METHOD=${LLM_PREF_METHOD},TPC_TAIL_LLM_PREF_CANDIDATE_MODE=${LLM_PREF_CANDIDATE_MODE},TPC_TAIL_LLM_PREF_PASSES=${LLM_PREF_PASSES},TPC_TAIL_LLM_PREF_MAX_CANDIDATES=${LLM_PREF_MAX_CANDIDATES},TPC_USE_CP_SOLVER=${TPC_USE_CP_SOLVER},TPC_CP_AFTER_PASS=${TPC_CP_AFTER_PASS},TPC_CP_FOUR_SLOT_SHARE=${TPC_CP_FOUR_SLOT_SHARE},TPC_CP_FOUR_SLOT_ROUNDS=${TPC_CP_FOUR_SLOT_ROUNDS},TPC_CP_RECON_SHUFFLES=${TPC_CP_RECON_SHUFFLES}"

echo "Submitting tail overnight job: partition=$PARTITION workers=$WORKERS mem=$MEM time=$TIME"
echo "  split=$SPLIT method=$METHOD rank_mode=$RANK_MODE pref_metric=$PREF_METRIC runner=$RUNNER rounds=$ROUNDS topk=$TOPK min_score=$MIN_SCORE"
echo "  llm_pref: llm=$LLM_PREF_LLM method=$LLM_PREF_METHOD candidate_mode=$LLM_PREF_CANDIDATE_MODE passes=$LLM_PREF_PASSES max_candidates=$LLM_PREF_MAX_CANDIDATES"
echo "  restarts=$RESTARTS budget=$BUDGET stop_no_improve=$STOP_NO_IMPROVE run_id=$RUN_ID"
echo "  cp: use=$TPC_USE_CP_SOLVER after_pass=$TPC_CP_AFTER_PASS share=$TPC_CP_FOUR_SLOT_SHARE rounds=$TPC_CP_FOUR_SLOT_ROUNDS recon_shuffles=$TPC_CP_RECON_SHUFFLES"

JOB=$(sbatch --parsable \
    --partition "$PARTITION" \
    --cpus-per-task "$WORKERS" \
    --mem "$MEM" \
    --time "$TIME" \
    --output "$PROJECT/cache/solve_logs/tail_overnight_%j.log" \
    --export "$EXPORTS" \
    slurm/tail_overnight.sbatch)

echo "$JOB" > cache/solve_logs/.tail_overnight_jobid
echo "JOBID=$JOB"
squeue -j "$JOB" -o '%i %P %j %u %T %M %D %R'
