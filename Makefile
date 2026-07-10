PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi)

SPLIT ?= tpc_phase1

# ===========================================================================
# PHASE 1 — public leaderboard helpers
# ===========================================================================

.PHONY: p1eval merge score submission upload upload-check clean-light help \
	phase2-help phase2-test phase2-splits phase2-solve phase2-rehearse \
	phase2-parser-report phase2-timing phase2-gate phase2-budget-sweep \
	phase2-baseline

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

# Per-query budget: 15 min primary (TBC), 5 min alternative. Override with P2_BUDGET.
P2_SPLIT_SET ?= val
FOLD ?= 0
P2_FOLDS ?= 10
P2_BUDGET ?= 900
P2_LIMIT ?=
P2_METHOD ?= phase2_e2e_tpc_phase2_$(P2_SPLIT_SET)
P2_SPLIT ?= tpc_phase2_$(P2_SPLIT_SET)
P2_BUDGETS ?= 30,60,120,300,900
P2_SWEEP_CSV ?= cache/phase2_budget_sweep/budget_sweep.csv
P2_SWEEP_JSON ?= cache/phase2_budget_sweep/budget_sweep.json
P2_BRANCH_AWARE ?= 0
P2_LIMIT_FLAG = $(if $(P2_LIMIT),--limit $(P2_LIMIT),)
P2_BRANCH_AWARE_FLAG = $(if $(filter 1,$(P2_BRANCH_AWARE)),--branch-aware,)

phase2-help:
	@printf '%s\n' \
	  'Phase 2 targets (docs/tpc_phase2_design.md, docs/tpc_phase2_eval.md):' \
	  '  make phase2-test            - run the Phase 2 pytest suite (unit; add integration below)' \
	  '  make phase2-splits          - (re)create tpc_phase2_val/test split files' \
	  '  make phase2-solve           - run the no-oracle harness over a split (LLM off)' \
	  '  make phase2-rehearse        - end-to-end + solver-only rehearsal + attribution + timing' \
	  '  make phase2-budget-sweep    - sweep budgets and export attribution CSV/JSON' \
	  '  make phase2-baseline        - run deterministic baseline and append docs/phase2_baselines history' \
	  '  make phase2-parser-report   - parser-vs-oracle attribution (Axis 1)' \
	  '  make phase2-timing          - per-stage timing + reliability from a run dir (Axis 3)' \
	  '  make phase2-gate            - regression gate: BASELINE=<json> CANDIDATE=<json>' \
	  'Variables: P2_SPLIT_SET=val|test  FOLD=$(FOLD)  P2_FOLDS=$(P2_FOLDS)  P2_BUDGET=$(P2_BUDGET)  P2_BUDGETS=$(P2_BUDGETS)  P2_LIMIT=<n>  P2_METHOD=$(P2_METHOD)  P2_BRANCH_AWARE=0|1'

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

# Full rehearsal dashboard: rehearse (both modes, three-way attribution) -> parser-vs-oracle -> timing.
phase2-rehearse:
	@echo "=== [1/3] Rehearsal (end-to-end + solver-only), three-way attribution ==="
	.venv/bin/python scripts/rehearse_phase2.py --mode both --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budget-sec $(P2_BUDGET) $(P2_LIMIT_FLAG)
	@echo "=== [2/3] Parser-vs-oracle attribution (Axis 1) ==="
	.venv/bin/python scripts/parser_vs_oracle.py --split-set $(P2_SPLIT_SET) --behavioral $(P2_LIMIT_FLAG)
	@echo "=== [3/3] Timing + reliability telemetry (Axis 3) ==="
	.venv/bin/python scripts/phase2_timing.py --work-dir agent_env/runs/$(P2_METHOD) --budget-sec $(P2_BUDGET)

# Sweep multiple budgets and export one attribution CSV/JSON.
phase2-budget-sweep:
	.venv/bin/python scripts/phase2_budget_sweep.py --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budgets "$(P2_BUDGETS)" $(P2_LIMIT_FLAG) \
	  --out-csv $(P2_SWEEP_CSV) --out-json $(P2_SWEEP_JSON)

# Run deterministic fold baseline and append trend files under docs/phase2_baselines.
phase2-baseline:
	.venv/bin/python scripts/phase2_record_baseline.py --split-set $(P2_SPLIT_SET) \
	  --fold $(FOLD) --folds $(P2_FOLDS) --budget-sec $(P2_BUDGET) $(P2_LIMIT_FLAG) \
	  $(P2_BRANCH_AWARE_FLAG)

# Parser-vs-oracle attribution only (Axis 1), incl. behavioral equivalence.
phase2-parser-report:
	.venv/bin/python scripts/parser_vs_oracle.py --split-set $(P2_SPLIT_SET) --behavioral $(P2_LIMIT_FLAG)

# Per-stage timing + reliability from a completed run directory (Axis 3).
phase2-timing:
	.venv/bin/python scripts/phase2_timing.py --work-dir agent_env/runs/$(P2_METHOD) --budget-sec $(P2_BUDGET)

# Monotonic regression gate: fails if CANDIDATE is worse than BASELINE. Requires BASELINE/CANDIDATE.
phase2-gate:
	.venv/bin/python scripts/phase2_gate.py --baseline $(BASELINE) --candidate $(CANDIDATE)
