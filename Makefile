PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi)
WORKERS ?= $(shell sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 1)

HEAVY_ROUNDS ?= 10
HEAVY_RESTARTS ?= 800
HEAVY_BUDGET ?= 240

LIGHT_RESTARTS ?= 40
LIGHT_BUDGET ?= 30

.PHONY: all heavy light merge score submission clean-light help

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
		--split tpc_phase1 \
		--restarts $(LIGHT_RESTARTS) \
		--budget $(LIGHT_BUDGET) \
		--seed-salt light \
		--workers $(WORKERS)
	$(PYTHON) scripts/merge.py --split tpc_phase1

# Re-run the monotonic merge alone.
merge:
	$(PYTHON) scripts/merge.py --split tpc_phase1

# Print headline metrics for results/best.
score:
	$(PYTHON) scripts/score.py

# Build the submission zip from results/best.
submission:
	$(PYTHON) scripts/assemble_submission.py $(if $(VERSION),--version $(VERSION))

# Remove partial light-pass outputs (safe; never touches results/best or submissions).
clean-light:
	rm -rf results/TPCAgent_TPCLLM_en_oracletranslation cache/TPCAgent_TPCLLM_en_oracletranslation

help:
	@printf '%s\n' \
	  'make                - full recommended workflow (heavy -> light -> score -> submission)' \
	  'make heavy          - resumable heavy search on the unsolved split' \
	  'make light          - light packing pass across all 1000 + merge' \
	  'make merge          - monotonic merge only' \
	  'make score          - evaluate results/best' \
	  'make submission     - build the next submission zip (version from git tags; override with VERSION=vN)' \
	  'make clean-light    - remove partial oracletranslation solve outputs' \
	  '' \
	  'Tunables:' \
	  '  WORKERS=<n>            default: all cores' \
	  '  HEAVY_ROUNDS=<n>       default: $(HEAVY_ROUNDS)' \
	  '  HEAVY_RESTARTS=<n>     default: $(HEAVY_RESTARTS)' \
	  '  HEAVY_BUDGET=<sec>     default: $(HEAVY_BUDGET)' \
	  '  LIGHT_RESTARTS=<n>     default: $(LIGHT_RESTARTS)' \
	  '  LIGHT_BUDGET=<sec>     default: $(LIGHT_BUDGET)' \
	  '  VERSION=<vN>           default: next version after the highest v<N> git tag'
