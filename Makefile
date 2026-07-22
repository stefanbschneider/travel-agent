PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi)

SPLIT ?= tpc_phase1

# ===========================================================================
# PHASE 1 — public leaderboard helpers
# ===========================================================================

.PHONY: p1eval merge score submission upload upload-check clean-light help \
	phase2-help phase2-test phase2-splits phase2-solve phase2-query phase2-rehearse \
	phase2-parser-report phase2-timing phase2-gate phase2-budget-sweep \
	phase2-baseline phase2-baseline-at

# Run phase 1 evaluation
p1eval:
	$(PYTHON) eval_tpc.py --split $(SPLIT) --method best

# Re-run the monotonic merge alone.
merge:
	$(PYTHON) scripts/merge.py --split $(SPLIT)

# Print headline metrics for results/best.
score:
	$(PYTHON) scripts/score.py

# Build the submission zip from results/best.
submission:
	$(PYTHON) scripts/assemble_submission.py $(if $(VERSION),--version $(VERSION))

# Upload a built submission zip to the TPC portal (default: newest submissions/fabiundstefan_v*.zip).
upload:
	$(PYTHON) scripts/submit.py $(if $(VERSION),--version $(VERSION))

# Resolve the portal link and show what would be uploaded, without sending.
upload-check:
	$(PYTHON) scripts/submit.py --dry-run $(if $(VERSION),--version $(VERSION))

# Remove partial light-pass outputs (safe; never touches results/best or submissions).
clean-light:
	rm -rf results/TPCAgent_TPCLLM_en_oracletranslation cache/TPCAgent_TPCLLM_en_oracletranslation

help:
	@printf '%s\n' \
	  'make p1eval         - run phase-1 evaluation for SPLIT (default: tpc_phase1)' \
	  'make merge          - monotonic merge only' \
	  'make score          - evaluate results/best' \
	  'make submission     - build the next submission zip (version from git tags; override with VERSION=vN)' \
	  'make upload         - upload the newest built submission zip to the TPC portal (override VERSION=vN)' \
	  'make upload-check   - resolve the portal link and show what would be uploaded (no send)' \
	  'make clean-light    - remove partial oracletranslation solve outputs' \
	  '' \
	  'Tunables:' \
	  '  SPLIT=<name>           default: $(SPLIT)' \
	  '  VERSION=<vN>           default: next version after the highest v<N> git tag' \
	  '' \
	  'Phase 2 (harness + eval): run make phase2-help for phase2-* targets.'

# ===========================================================================
# PHASE 2 — final harness (per-query, no oracle, bounded budget) + evaluation
# No-oracle parsing + orchestration around the deterministic TPCAgent. LLM is
# off by default. See docs/tpc_phase2_design.md and docs/tpc_phase2_eval.md.
# ===========================================================================

# Per-query budgets are local sensitivity settings; the official timeout/repeat contract is not
# public. `300` is the working default and `900` is a longer sensitivity check. Override with P2_BUDGET.
P2_SPLIT_SET ?= val
FOLD ?= 0
P2_FOLDS ?= 10
P2_BUDGET ?= 300
P2_LIMIT ?=
P2_METHOD ?= phase2_e2e_tpc_phase2_$(P2_SPLIT_SET)
P2_SPLIT ?= tpc_phase2_$(P2_SPLIT_SET)
P2_BUDGETS ?= 30,60,120,300,900
P2_SWEEP_CSV ?= cache/phase2_budget_sweep/budget_sweep.csv
P2_SWEEP_JSON ?= cache/phase2_budget_sweep/budget_sweep.json
P2_BRANCH_AWARE ?= 0
P2_REPEATS ?= 1
P2_LABEL ?=
# Chunk subprocesses to run concurrently (1 = sequential, original behavior). Each query's
# CP-SAT solve uses 1 core by default, so size this to (core count - 1); memory is usually not
# the limit -- see docs/tpc_phase2_design.md for the per-process RSS floor (~250MB).
P2_PARALLEL ?= 1
P2_LIMIT_FLAG = $(if $(P2_LIMIT),--limit $(P2_LIMIT),)
P2_BRANCH_AWARE_FLAG = $(if $(filter 1,$(P2_BRANCH_AWARE)),--branch-aware,)
P2_LABEL_FLAG = $(if $(P2_LABEL),--label $(P2_LABEL),)
# Evaluation tooling only: stop each query's solve at the first accepted plan instead of spending
# the full budget on preference polishing. Never set by the real harness.
P2_FAST_FPR ?= 0
P2_FAST_FPR_FLAG = $(if $(filter 1,$(P2_FAST_FPR)),--fast-fpr,)
# Passed through verbatim to scripts/run_query.py, e.g.:
#   make phase2-query P2_QUERY_ARGS="--uid 20250322063246301376 --budget-sec 60"
#   make phase2-query P2_QUERY_ARGS="--query-file my_query.json --budget-sec 120"
#   make phase2-query P2_QUERY_ARGS='--query-text "3 days Beijing to Chengdu, 2 people" --start-city Beijing --target-city Chengdu --days 3'
P2_QUERY_ARGS ?=

phase2-help:
	@printf '%s\n' \
	  'Phase 2 targets (docs/tpc_phase2_design.md, docs/tpc_phase2_eval.md, docs/tpc_phase2_roadmap.md):' \
	  '  make phase2-test            - run the Phase 2 pytest suite (unit; add integration below)' \
	  '  make phase2-splits          - (re)create tpc_phase2_val/test split files' \
	  '  make phase2-solve           - run the no-oracle harness over a split (LLM off)' \
	  '  make phase2-query           - run ONE query end to end: P2_QUERY_ARGS="--uid <id> | --query-file <path> | --query-text ..."' \
	  '  make phase2-rehearse        - end-to-end + solver-only rehearsal + attribution + timing' \
	  '  make phase2-budget-sweep    - sweep budgets and export attribution CSV/JSON' \
	  '  make phase2-baseline        - run deterministic baseline and append results/phase2_baselines history' \
	  '  make phase2-baseline-at     - same as phase2-baseline, but pinned to SHA=<ref> via a disposable git worktree' \
	  '  make phase2-parser-report   - parser-vs-oracle attribution (Axis 1)' \
	  '  make phase2-timing          - per-stage timing + reliability from a run dir (Axis 3)' \
	  '  make phase2-gate            - regression gate: BASELINE=<json> CANDIDATE=<json>' \
	  '  make phase2-quick-eval      - fast A/B SCREEN of an off-by-default flag: P2_FLAG=<env var> (docs/tpc_phase2_eval.md#quick-ab-screen-pre-gate-triage)' \
	  '  make phase2-progress        - live progress counter for a running phase2-baseline job (--watch)' \
	  'Variables: P2_SPLIT_SET=val|test  FOLD=$(FOLD)  P2_FOLDS=$(P2_FOLDS)  P2_BUDGET=$(P2_BUDGET)  P2_BUDGETS=$(P2_BUDGETS)  P2_LIMIT=<n>  P2_METHOD=$(P2_METHOD)  P2_BRANCH_AWARE=0|1  P2_PARALLEL=$(P2_PARALLEL)  P2_FAST_FPR=0|1  P2_QUERY_ARGS="..."'

# Run the Phase 2 test suite (unit by default; integration is opt-in).
phase2-test:
	.venv/bin/python -m pytest tests/phase2
	@echo "(integration: .venv/bin/python -m pytest -m integration tests/phase2)"

# (Re)create the validation / held-out-test split files (idempotent; --force to overwrite).
phase2-splits:
	.venv/bin/python scripts/make_phase2_splits.py

# Run the no-oracle harness over a split (oracle hidden from the agent; LLM off by default).
phase2-solve:
	.venv/bin/python agent_env/scripts/solve_phase2.py --split $(P2_SPLIT) \
	  --method $(P2_METHOD) --budget-sec $(P2_BUDGET) $(P2_LIMIT_FLAG)

# Run ONE query end to end (existing uid / a query file / raw NL text). See scripts/run_query.py.
phase2-query:
	.venv/bin/python scripts/run_query.py $(P2_QUERY_ARGS)

# Full rehearsal dashboard: rehearse (both modes, three-way attribution) -> parser-vs-oracle -> timing.
phase2-rehearse:
	@echo "=== [1/3] Rehearsal (end-to-end + solver-only), three-way attribution ==="
	.venv/bin/python scripts/rehearse_phase2.py --mode both --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budget-sec $(P2_BUDGET) $(P2_LIMIT_FLAG) \
	  --parallel $(P2_PARALLEL) $(P2_FAST_FPR_FLAG)
	@echo "=== [2/3] Parser-vs-oracle attribution (Axis 1) ==="
	.venv/bin/python scripts/parser_vs_oracle.py --split-set $(P2_SPLIT_SET) --behavioral $(P2_LIMIT_FLAG)
	@echo "=== [3/3] Timing + reliability telemetry (Axis 3) ==="
	.venv/bin/python scripts/phase2_timing.py --work-dir agent_env/runs/$(P2_METHOD) --budget-sec $(P2_BUDGET)

# Sweep multiple budgets and export one attribution CSV/JSON.
phase2-budget-sweep:
	.venv/bin/python scripts/phase2_budget_sweep.py --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budgets "$(P2_BUDGETS)" $(P2_LIMIT_FLAG) \
	  --out-csv $(P2_SWEEP_CSV) --out-json $(P2_SWEEP_JSON)

# Run deterministic fold baseline and append trend files under results/phase2_baselines.
phase2-baseline:
	.venv/bin/python scripts/phase2_record_baseline.py --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budget-sec $(P2_BUDGET) $(P2_LIMIT_FLAG) \
	  --repeats $(P2_REPEATS) $(P2_LABEL_FLAG) $(P2_BRANCH_AWARE_FLAG) --parallel $(P2_PARALLEL) \
	  $(P2_FAST_FPR_FLAG)

# Same as phase2-baseline, but uses a pinned `git worktree` checkout of SHA. The main tree stays
# free for development mid-run, and the row's git_sha is truthful by construction.
phase2-baseline-at:
	.venv/bin/python scripts/phase2_eval_at.py --sha $(SHA) -- --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budget-sec $(P2_BUDGET) $(P2_LIMIT_FLAG) \
	  --repeats $(P2_REPEATS) $(P2_LABEL_FLAG) $(P2_BRANCH_AWARE_FLAG) --parallel $(P2_PARALLEL) \
	  $(P2_FAST_FPR_FLAG)

# Parser-vs-oracle attribution only (Axis 1), incl. behavioral equivalence.
phase2-parser-report:
	.venv/bin/python scripts/parser_vs_oracle.py --split-set $(P2_SPLIT_SET) --behavioral $(P2_LIMIT_FLAG)

# Per-stage timing + reliability from a completed run directory (Axis 3).
phase2-timing:
	.venv/bin/python scripts/phase2_timing.py --work-dir agent_env/runs/$(P2_METHOD) --budget-sec $(P2_BUDGET)

# Monotonic regression gate: fails if CANDIDATE is worse than BASELINE. Requires BASELINE/CANDIDATE.
phase2-gate:
	.venv/bin/python scripts/phase2_gate.py --baseline $(BASELINE) --candidate $(CANDIDATE)

# Quick A/B screen for an off-by-default flag (docs/tpc_phase2_eval.md, "Quick A/B screen"). Reduced-budget paired
# baseline-vs-candidate SCREEN, not a promotion gate -- decides in ~1-2h whether a change is worth a
# pinned end-to-end gate. Requires P2_FLAG=<env var>; override P2_ON/P2_OFF/P2_N/P2_BUDGET/P2_PARALLEL
# and P2_QE_MODE (solver-only|end-to-end) as needed.
#   make phase2-quick-eval P2_FLAG=TPC_PIN_TIMED_WINDOWS P2_N=40 P2_BUDGET=60 P2_PARALLEL=3
P2_FLAG ?=
P2_ON ?= 1
P2_OFF ?= 0
P2_N ?= 40
P2_QE_MODE ?= solver-only
P2_QE_SPLIT_SET ?= familiar_100
P2_QE_EXTRA_ENV ?=
P2_QE_BASELINE_JSON ?=
P2_QE_OUT ?=
phase2-quick-eval:
	.venv/bin/python scripts/phase2_quick_eval.py --flag $(P2_FLAG) --on $(P2_ON) --off $(P2_OFF) \
	  --mode $(P2_QE_MODE) --split-set $(P2_QE_SPLIT_SET) --n $(P2_N) --budget-sec $(P2_BUDGET) \
	  --parallel $(P2_PARALLEL) \
	  $(if $(P2_QE_EXTRA_ENV),--extra-env $(P2_QE_EXTRA_ENV),) \
	  $(if $(P2_QE_BASELINE_JSON),--baseline-json $(P2_QE_BASELINE_JSON),) \
	  $(if $(P2_QE_OUT),--out $(P2_QE_OUT),)

# Live progress counter for a running/just-launched phase2-baseline job. Read-only (never touches
# code the harness imports), safe to run at any time including mid-freeze. Add --watch for a
# live-updating view: make phase2-progress FOLD=0 P2_FOLDS=10 P2_REPEATS=2 P2_PROGRESS_ARGS=--watch
P2_PROGRESS_ARGS ?=
phase2-progress:
	.venv/bin/python scripts/phase2_progress.py --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --repeats $(P2_REPEATS) $(P2_LIMIT_FLAG) $(P2_PROGRESS_ARGS)
