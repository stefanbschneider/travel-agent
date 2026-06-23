PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi)
WORKERS ?= $(shell sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 1)

SPLIT ?= tpc_phase1

HEAVY_ROUNDS ?= 10
HEAVY_RESTARTS ?= 800
HEAVY_BUDGET ?= 240

LIGHT_RESTARTS ?= 40
LIGHT_BUDGET ?= 30

TAIL_METHOD ?= best
TAIL_TOPK ?= 120
TAIL_MIN_SCORE ?= 99
TAIL_FOCUS_SPLIT ?= $(SPLIT)_tail_focus
TAIL_RESTARTS ?= 1200
TAIL_BUDGET ?= 300

.PHONY: all heavy light tail-round merge score submission upload upload-check clean-light help

# Default: the full recommended workflow.
all: heavy light score submission

# Heavy resumable search over the unsolved split.
heavy:
	$(PYTHON) scripts/iterate.py \
		--rounds $(HEAVY_ROUNDS) \
		--restarts $(HEAVY_RESTARTS) \
		--budget $(HEAVY_BUDGET) \
		--workers $(WORKERS)

# Light pass + monotonic merge across all 1000.
light:
	$(PYTHON) scripts/solve.py \
		--split $(SPLIT) \
		--restarts $(LIGHT_RESTARTS) \
		--budget $(LIGHT_BUDGET) \
		--seed-salt light \
		--workers $(WORKERS)
	$(PYTHON) scripts/merge.py --split $(SPLIT)

# Tail-focused optimization round: rank low-score queries, solve focused split, merge, score.
tail-round:
	$(PYTHON) scripts/rank_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--top-k $(TAIL_TOPK) \
		--min-score $(TAIL_MIN_SCORE) \
		--focus-split $(TAIL_FOCUS_SPLIT)
	$(PYTHON) scripts/solve.py \
		--split $(TAIL_FOCUS_SPLIT) \
		--restarts $(TAIL_RESTARTS) \
		--budget $(TAIL_BUDGET) \
		--workers $(WORKERS)
	$(PYTHON) scripts/merge.py --split $(TAIL_FOCUS_SPLIT)
	$(PYTHON) scripts/score.py

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
	  'make                - full recommended workflow (heavy -> light -> score -> submission)' \
	  'make heavy          - resumable heavy search on the unsolved split' \
	  'make light          - light packing pass across all 1000 + merge' \
	  'make tail-round     - rank low-score tail -> focused solve -> merge -> score' \
	  'make merge          - monotonic merge only' \
	  'make score          - evaluate results/best' \
	  'make submission     - build the next submission zip (version from git tags; override with VERSION=vN)' \
	  'make upload         - upload the newest built submission zip to the TPC portal (override VERSION=vN)' \
	  'make upload-check   - resolve the portal link and show what would be uploaded (no send)' \
	  'make clean-light    - remove partial oracletranslation solve outputs' \
	  '' \
	  'Tunables:' \
	  '  WORKERS=<n>            default: all cores' \
	  '  SPLIT=<name>           default: $(SPLIT)' \
	  '  HEAVY_ROUNDS=<n>       default: $(HEAVY_ROUNDS)' \
	  '  HEAVY_RESTARTS=<n>     default: $(HEAVY_RESTARTS)' \
	  '  HEAVY_BUDGET=<sec>     default: $(HEAVY_BUDGET)' \
	  '  LIGHT_RESTARTS=<n>     default: $(LIGHT_RESTARTS)' \
	  '  LIGHT_BUDGET=<sec>     default: $(LIGHT_BUDGET)' \
	  '  TAIL_METHOD=<name>     default: $(TAIL_METHOD)' \
	  '  TAIL_TOPK=<n>          default: $(TAIL_TOPK)' \
	  '  TAIL_MIN_SCORE=<n>     default: $(TAIL_MIN_SCORE)' \
	  '  TAIL_FOCUS_SPLIT=<n>   default: $(TAIL_FOCUS_SPLIT)' \
	  '  TAIL_RESTARTS=<n>      default: $(TAIL_RESTARTS)' \
	  '  TAIL_BUDGET=<sec>      default: $(TAIL_BUDGET)' \
	  '  VERSION=<vN>           default: next version after the highest v<N> git tag'
