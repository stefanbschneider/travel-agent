#!/usr/bin/env bash
#
# One-shot final-night Phase 2 evaluation driver (second machine).
#
# Runs the two pinned 900s arms sequentially, then commits and pushes the generated ledger rows --
# committing after EACH arm, so an interrupted night still leaves usable, pushed evidence. Start it
# once and go to bed.
#
# What it measures: TPC_COMMONSENSE_FIRST was promoted to harness-default-on from a 120s paired
# screen whose only caveat was timeouts rising 4 -> 7 at that tight budget. These arms re-measure the
# same pair at 900s, where the promoted row's solve p50 is 265s and there is real headroom. Arm B
# (the shipped default) runs FIRST so a partial night still measures what actually ships.
#
# Usage:
#   bash scripts/run_final_night_eval.sh                 # full run, both arms, commit + push
#   bash scripts/run_final_night_eval.sh --smoke         # 2-minute plumbing check, no commit/push
#   bash scripts/run_final_night_eval.sh --no-push       # commit locally, do not push
#   bash scripts/run_final_night_eval.sh --repeats 2     # variance per arm (doubles the wall clock)
#   bash scripts/run_final_night_eval.sh --limit 20      # shorter real run: first 20 queries only
#   bash scripts/run_final_night_eval.sh --arm on        # only the promoted arm
#
# Detached (survives a closed SSH session):
#   nohup bash scripts/run_final_night_eval.sh > /tmp/final_night.out 2>&1 &
#   tail -f /tmp/final_night.out
#
# Resumable: re-running re-issues the same commands. The recorder reuses completed per-uid artifacts
# under agent_env/runs/ and results/phase2_e2e_*, and the pinned git worktree means commits landing on
# the branch mid-run cannot contaminate a running arm.
#
# This script never reads, writes, or sources .env, and never enables an LLM backend: both arms are
# fully deterministic with zero LLM calls, which is what makes them comparable.

set -uo pipefail

SHA="c599570b614512681c8aec6c2e6305a5490d7e3a"
SPLIT_SET="familiar_100_val"
BUDGET=900
PARALLEL=3
REPEATS=1
ARMS="on off"
DO_PUSH=1
SMOKE=0
LIMIT_FLAG=""

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

LOG_DIR="cache/final_night_eval"
mkdir -p "$LOG_DIR"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke)    SMOKE=1; BUDGET=30; REPEATS=1; LIMIT_FLAG="P2_LIMIT=1"; DO_PUSH=0; shift ;;
    --limit)    LIMIT_FLAG="P2_LIMIT=$2"; shift 2 ;;
    --no-push)  DO_PUSH=0; shift ;;
    --repeats)  REPEATS="$2"; shift 2 ;;
    --budget)   BUDGET="$2"; shift 2 ;;
    --parallel) PARALLEL="$2"; shift 2 ;;
    --arm)      ARMS="$2"; shift 2 ;;
    --sha)      SHA="$2"; shift 2 ;;
    -h|--help)  sed -n '2,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)          echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done

log()  { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "FATAL: $*"; exit 1; }

# --- preflight -----------------------------------------------------------------------------------

log "final-night eval driver starting in $PROJECT_ROOT"
log "sha=$SHA split_set=$SPLIT_SET budget=${BUDGET}s repeats=$REPEATS parallel=$PARALLEL arms='$ARMS' push=$DO_PUSH smoke=$SMOKE"

[[ -x .venv/bin/python ]] || fail ".venv/bin/python missing. Run: python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"

git cat-file -e "${SHA}^{commit}" 2>/dev/null \
  || fail "sha $SHA not present locally. Run: git fetch --all (and check out the branch that contains it)."

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
log "current branch: $BRANCH"
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  log "WARNING: on $BRANCH. Rows will be committed here; that is usually not what you want."
fi

# The environment database is required for any real solve; a missing DB produces meaningless rows.
if [[ ! -d chinatravel/environment/database ]]; then
  fail "chinatravel/environment/database/ missing. Install the environment database (agent_env/README.md)."
fi

log "preflight solve (1 query, 60s) ..."
if ! make phase2-solve P2_SPLIT_SET=val P2_BUDGET=60 P2_LIMIT=1 > "$LOG_DIR/preflight.log" 2>&1; then
  tail -20 "$LOG_DIR/preflight.log"
  fail "preflight solve failed; see $LOG_DIR/preflight.log"
fi
if ! grep -q "valid=True" "$LOG_DIR/preflight.log"; then
  tail -20 "$LOG_DIR/preflight.log"
  fail "preflight solve produced no valid plan; see $LOG_DIR/preflight.log"
fi
log "preflight OK"

# --- helpers -------------------------------------------------------------------------------------

rows_snapshot() { ls -1 results/phase2_baselines/runs/*.json 2>/dev/null | sort; }

commit_and_push() {
  local message="$1"
  if git diff --quiet -- results/phase2_baselines && git diff --cached --quiet -- results/phase2_baselines \
     && [[ -z "$(git ls-files --others --exclude-standard results/phase2_baselines)" ]]; then
    log "nothing new under results/phase2_baselines to commit"
    return 0
  fi
  # Stage ONLY generated ledger rows: never sweep up unrelated working-tree changes.
  git add results/phase2_baselines || { log "WARNING: git add failed"; return 1; }
  if ! git commit -q -m "$message"; then
    log "WARNING: git commit failed (nothing staged?)"
    return 1
  fi
  log "committed: $message"
  if [[ "$DO_PUSH" == "1" ]]; then
    if git push -q; then
      log "pushed to origin/$BRANCH"
    elif git push -q -u origin HEAD; then
      log "pushed and set upstream for $BRANCH"
    else
      log "WARNING: push failed (credentials? offline?). The commit is safe locally; push manually later."
    fi
  else
    log "push skipped (--no-push/--smoke); commit is local only"
  fi
}

run_arm() {
  local arm="$1" label env_prefix log_file
  case "$arm" in
    on)  label="final-night-csfirst-on";  env_prefix="" ;;
    off) label="final-night-csfirst-off"; env_prefix="TPC_COMMONSENSE_FIRST=0" ;;
    *)   log "unknown arm '$arm', skipping"; return 1 ;;
  esac
  [[ "$SMOKE" == "1" ]] && label="smoke-$label"
  log_file="$LOG_DIR/arm_${arm}.log"

  log "=== arm '$arm' ($label) starting; log: $log_file ==="
  local before after started ended
  before="$(rows_snapshot)"
  started="$(date +%s)"

  # env -i is deliberately NOT used: the run needs PATH/HOME. Only the one flag differs between arms.
  if [[ -n "$env_prefix" ]]; then
    TPC_COMMONSENSE_FIRST=0 make phase2-baseline-at \
      SHA="$SHA" P2_SPLIT_SET="$SPLIT_SET" FOLD=0 P2_FOLDS=1 \
      P2_BUDGET="$BUDGET" P2_REPEATS="$REPEATS" P2_PARALLEL="$PARALLEL" \
      P2_LABEL="$label" $LIMIT_FLAG >> "$log_file" 2>&1
  else
    env -u TPC_COMMONSENSE_FIRST make phase2-baseline-at \
      SHA="$SHA" P2_SPLIT_SET="$SPLIT_SET" FOLD=0 P2_FOLDS=1 \
      P2_BUDGET="$BUDGET" P2_REPEATS="$REPEATS" P2_PARALLEL="$PARALLEL" \
      P2_LABEL="$label" $LIMIT_FLAG >> "$log_file" 2>&1
  fi
  local status=$?
  ended="$(date +%s)"
  log "arm '$arm' exited with status $status after $(( (ended - started) / 60 )) min"

  after="$(rows_snapshot)"
  local new_rows
  new_rows="$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"
  if [[ -n "${new_rows// /}" ]]; then
    log "arm '$arm' produced row(s): $new_rows"
  else
    log "WARNING: arm '$arm' produced no new row file"
  fi

  # Commit after every arm so an interrupted night still leaves pushed evidence.
  if [[ "$SMOKE" == "1" ]]; then
    log "smoke mode: skipping commit for arm '$arm'"
  else
    commit_and_push "phase2: final night pinned ${BUDGET}s row (${label})"
  fi
  return $status
}

# --- run -----------------------------------------------------------------------------------------

OVERALL=0
for arm in $ARMS; do
  run_arm "$arm" || OVERALL=1
done

# --- report (informational only; no decision is required from the operator) -----------------------

log "=== summary ==="
.venv/bin/python - <<'PY' 2>/dev/null || log "(summary unavailable)"
import glob, json, os
rows = []
for path in glob.glob("results/phase2_baselines/runs/*.json"):
    try:
        d = json.load(open(path))
    except Exception:
        continue
    if str(d.get("label", "")).startswith(("final-night-csfirst", "smoke-final-night-csfirst")):
        rows.append((os.path.basename(path), d))
rows.sort(key=lambda kv: kv[0])
if not rows:
    print("no final-night rows found yet")
for name, d in rows:
    v = d.get("variance", {}) or {}
    modes = ((d.get("rehearsal") or {}).get("modes") or {})
    e2e = (modes.get("end-to-end") or {}).get("raw") or {}
    print(f"{name}  label={d.get('label')}  n={d.get('n')}  budget={d.get('budget_sec')}  sha={str(d.get('git_sha',''))[:8]}")
    print(f"   e2e   FPR={v.get('e2e_fpr_mean', e2e.get('all_pass_count'))}  "
          f"overall_true={v.get('e2e_overall_true_mean')}")
    print(f"   layers commonsense_pass={e2e.get('commonsense_pass_count')}/{d.get('n')}  "
          f"EPR-macro={e2e.get('commonsense_macro')}  C-LPR={e2e.get('conditional_logical_micro')}  "
          f"logical_micro={e2e.get('logical_micro')}")
PY

log "logs in $LOG_DIR/ ; rows in results/phase2_baselines/runs/"
if [[ "$OVERALL" != "0" ]]; then
  log "DONE with at least one failing arm -- check the arm logs. Any completed rows were committed."
else
  log "DONE: all requested arms completed."
fi
exit "$OVERALL"
