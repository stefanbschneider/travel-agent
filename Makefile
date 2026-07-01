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
TAIL_ROUNDS ?= 4
TAIL_STOP_NO_IMPROVE ?= 1
TAIL_ARTIFACTS_ROOT ?= cache/hpc_tail_runs
TAIL_RUN_ID ?=
TAIL_SEED_PREFIX ?= tail
TAIL_RESUME ?= 0
TAIL_SKIP_EXISTING ?= 1
TAIL_HEARTBEAT_SEC ?= 60
TAIL_STREAM_SOLVE_LOG ?= 0

# TPC solver tuning knobs (propagated as env vars)
TPC_USE_CP_SOLVER ?= 1
TPC_CP_AFTER_PASS ?= 1
TPC_CP_FOUR_SLOT_SHARE ?= 0.75
TPC_CP_FOUR_SLOT_ROUNDS ?= 2
TPC_CP_RECON_SHUFFLES ?= 0

# Ready-made run profiles
SHORT_LOCAL_WORKERS ?= 4
SHORT_LOCAL_TOPK ?= 24
SHORT_LOCAL_RESTARTS ?= 120
SHORT_LOCAL_BUDGET ?= 20
SHORT_LOCAL_ROUNDS ?= 1

OVERNIGHT_LOCAL_WORKERS ?= 7
OVERNIGHT_LOCAL_TOPK ?= 180
OVERNIGHT_LOCAL_RESTARTS ?= 900
OVERNIGHT_LOCAL_BUDGET ?= 180
OVERNIGHT_LOCAL_ROUNDS ?= 6
OVERNIGHT_LOCAL_STOP ?= 2

PREFERENCE_LOCAL_WORKERS ?= $(OVERNIGHT_LOCAL_WORKERS)
PREFERENCE_LOCAL_ROUNDS ?= 6
PREFERENCE_LOCAL_TOPK ?= 240
PREFERENCE_LOCAL_MIN_SCORE ?= 99.5
PREFERENCE_LOCAL_STOP ?= 2
PREFERENCE_LOCAL_METRIC ?= overall
PREFERENCE_LOCAL_RUN_ID ?=

HPC_PARTITION ?= standard
HPC_WORKERS ?= 8
HPC_MEM ?= 6G
HPC_TIME ?= 07:30:00
HPC_ROUNDS ?= 8
HPC_TOPK ?= 240
HPC_MIN_SCORE ?= 99
HPC_RESTARTS ?= 1200
HPC_BUDGET ?= 300
HPC_STOP ?= 2
HPC_RUN_ID ?= tail_hpc_$(shell date +%Y%m%d_%H%M%S)

# Two-phase HPC profiles (solve unresolved tail first, then preference on solved plans)
HPC_UNSOLVED_WORKERS ?= $(HPC_WORKERS)
HPC_UNSOLVED_ROUNDS ?= 8
HPC_UNSOLVED_TOPK ?= 240
HPC_UNSOLVED_MIN_SCORE ?= 99
HPC_UNSOLVED_RESTARTS ?= 1200
HPC_UNSOLVED_BUDGET ?= 300
HPC_UNSOLVED_STOP ?= 2
HPC_UNSOLVED_RUN_ID ?= hpc_unsolved_$(shell date +%Y%m%d_%H%M%S)

HPC_PREFERENCE_WORKERS ?= $(HPC_WORKERS)
HPC_PREFERENCE_ROUNDS ?= 10
HPC_PREFERENCE_TOPK ?= 400
HPC_PREFERENCE_MIN_SCORE ?= 99.5
HPC_PREFERENCE_STOP ?= 3
HPC_PREFERENCE_METRIC ?= overall
HPC_PREFERENCE_RUN_ID ?= hpc_preference_$(shell date +%Y%m%d_%H%M%S)

.PHONY: all heavy light tail-round tail-iterate short-local overnight-local preference-local preference-quick hpc-tail-submit hpc-unsolved hpc-preference hpc-preference-submit merge score submission upload upload-check clean-light help

# Default: preference optimization on already-solved plans.
all: preference-local score submission

# Heavy resumable search over the unsolved split.
heavy:
	$(PYTHON) scripts/iterate_unsolved.py \
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

# Multi-round tail optimization with per-round artifacts (rank -> solve -> merge -> score).
tail-iterate:
	TPC_USE_CP_SOLVER=$(TPC_USE_CP_SOLVER) \
	TPC_CP_AFTER_PASS=$(TPC_CP_AFTER_PASS) \
	TPC_CP_FOUR_SLOT_SHARE=$(TPC_CP_FOUR_SLOT_SHARE) \
	TPC_CP_FOUR_SLOT_ROUNDS=$(TPC_CP_FOUR_SLOT_ROUNDS) \
	TPC_CP_RECON_SHUFFLES=$(TPC_CP_RECON_SHUFFLES) \
	$(PYTHON) scripts/iterate_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--rounds $(TAIL_ROUNDS) \
		--top-k $(TAIL_TOPK) \
		--min-score $(TAIL_MIN_SCORE) \
		--restarts $(TAIL_RESTARTS) \
		--budget $(TAIL_BUDGET) \
		--workers $(WORKERS) \
		--stop-no-improve-rounds $(TAIL_STOP_NO_IMPROVE) \
		--artifacts-root $(TAIL_ARTIFACTS_ROOT) \
		$(if $(TAIL_RUN_ID),--run-id $(TAIL_RUN_ID)) \
		--seed-prefix $(TAIL_SEED_PREFIX) \
		--heartbeat-sec $(TAIL_HEARTBEAT_SEC) \
		$(if $(filter 1,$(TAIL_STREAM_SOLVE_LOG)),--stream-solve-log,) \
		$(if $(filter 1,$(TAIL_RESUME)),--resume,) \
		$(if $(filter 1,$(TAIL_SKIP_EXISTING)),--skip-existing,)

# Short local profile (~10min on laptop): one compact tail round.
short-local:
	TPC_USE_CP_SOLVER=$(TPC_USE_CP_SOLVER) \
	TPC_CP_AFTER_PASS=$(TPC_CP_AFTER_PASS) \
	TPC_CP_FOUR_SLOT_SHARE=$(TPC_CP_FOUR_SLOT_SHARE) \
	TPC_CP_FOUR_SLOT_ROUNDS=$(TPC_CP_FOUR_SLOT_ROUNDS) \
	TPC_CP_RECON_SHUFFLES=$(TPC_CP_RECON_SHUFFLES) \
	$(PYTHON) scripts/iterate_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--rounds $(SHORT_LOCAL_ROUNDS) \
		--top-k $(SHORT_LOCAL_TOPK) \
		--min-score $(TAIL_MIN_SCORE) \
		--restarts $(SHORT_LOCAL_RESTARTS) \
		--budget $(SHORT_LOCAL_BUDGET) \
		--workers $(SHORT_LOCAL_WORKERS) \
		--stop-no-improve-rounds 1 \
		--artifacts-root $(TAIL_ARTIFACTS_ROOT) \
		--seed-prefix short \
		--run-id short_local_$(shell date +%Y%m%d_%H%M%S)

# Long local overnight profile (~7h target on laptop).
overnight-local:
	TPC_USE_CP_SOLVER=$(TPC_USE_CP_SOLVER) \
	TPC_CP_AFTER_PASS=$(TPC_CP_AFTER_PASS) \
	TPC_CP_FOUR_SLOT_SHARE=$(TPC_CP_FOUR_SLOT_SHARE) \
	TPC_CP_FOUR_SLOT_ROUNDS=$(TPC_CP_FOUR_SLOT_ROUNDS) \
	TPC_CP_RECON_SHUFFLES=$(TPC_CP_RECON_SHUFFLES) \
	$(PYTHON) scripts/iterate_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--rounds $(OVERNIGHT_LOCAL_ROUNDS) \
		--top-k $(OVERNIGHT_LOCAL_TOPK) \
		--min-score $(TAIL_MIN_SCORE) \
		--restarts $(OVERNIGHT_LOCAL_RESTARTS) \
		--budget $(OVERNIGHT_LOCAL_BUDGET) \
		--workers $(OVERNIGHT_LOCAL_WORKERS) \
		--stop-no-improve-rounds $(OVERNIGHT_LOCAL_STOP) \
		--artifacts-root $(TAIL_ARTIFACTS_ROOT) \
		--seed-prefix overnight \
		--heartbeat-sec $(TAIL_HEARTBEAT_SEC) \
		$(if $(filter 1,$(TAIL_STREAM_SOLVE_LOG)),--stream-solve-log,) \
		$(if $(TAIL_RUN_ID),--run-id $(TAIL_RUN_ID),--run-id overnight_local_$(shell date +%Y%m%d_%H%M%S)) \
		$(if $(filter 1,$(TAIL_RESUME)),--resume,) \
		$(if $(filter 1,$(TAIL_SKIP_EXISTING)),--skip-existing,)

# Local preference optimization profile: only densify already-solved plans (constraint-safe).
preference-local:
	$(PYTHON) scripts/iterate_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--rank-mode preference \
		--pref-metric $(PREFERENCE_LOCAL_METRIC) \
		--runner densify \
		--rounds $(PREFERENCE_LOCAL_ROUNDS) \
		--top-k $(PREFERENCE_LOCAL_TOPK) \
		--min-score $(PREFERENCE_LOCAL_MIN_SCORE) \
		--workers $(PREFERENCE_LOCAL_WORKERS) \
		--stop-no-improve-rounds $(PREFERENCE_LOCAL_STOP) \
		--artifacts-root $(TAIL_ARTIFACTS_ROOT) \
		--seed-prefix preference_local \
		--heartbeat-sec $(TAIL_HEARTBEAT_SEC) \
		$(if $(filter 1,$(TAIL_RESUME)),--resume,) \
		$(if $(PREFERENCE_LOCAL_RUN_ID),--run-id $(PREFERENCE_LOCAL_RUN_ID),--run-id preference_local_$(shell date +%Y%m%d_%H%M%S))

# Quick local preference pass (~10-20 min depending on hardware).
preference-quick:
	$(MAKE) preference-local \
		PREFERENCE_LOCAL_ROUNDS=1 \
		PREFERENCE_LOCAL_TOPK=$(SHORT_LOCAL_TOPK) \
		PREFERENCE_LOCAL_WORKERS=$(SHORT_LOCAL_WORKERS) \
		PREFERENCE_LOCAL_STOP=1

# Submit one 7h tail-iterate run to SLURM (single controller job orchestrating multi-round solve/merge/score).
hpc-tail-submit:
	bash slurm/submit_tail_overnight.sh \
		PARTITION=$(HPC_PARTITION) \
		WORKERS=$(HPC_WORKERS) \
		MEM=$(HPC_MEM) \
		TIME=$(HPC_TIME) \
		ROUNDS=$(HPC_ROUNDS) \
		TOPK=$(HPC_TOPK) \
		MIN_SCORE=$(HPC_MIN_SCORE) \
		RESTARTS=$(HPC_RESTARTS) \
		BUDGET=$(HPC_BUDGET) \
		STOP_NO_IMPROVE=$(HPC_STOP) \
		RUN_ID=$(HPC_RUN_ID)

# Phase A (HPC): prioritize unresolved constraint failures with heavy solve rounds.
hpc-unsolved:
	TPC_USE_CP_SOLVER=$(TPC_USE_CP_SOLVER) \
	TPC_CP_AFTER_PASS=$(TPC_CP_AFTER_PASS) \
	TPC_CP_FOUR_SLOT_SHARE=$(TPC_CP_FOUR_SLOT_SHARE) \
	TPC_CP_FOUR_SLOT_ROUNDS=$(TPC_CP_FOUR_SLOT_ROUNDS) \
	TPC_CP_RECON_SHUFFLES=$(TPC_CP_RECON_SHUFFLES) \
	$(PYTHON) scripts/iterate_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--rank-mode unsolved \
		--runner solve \
		--rounds $(HPC_UNSOLVED_ROUNDS) \
		--top-k $(HPC_UNSOLVED_TOPK) \
		--min-score $(HPC_UNSOLVED_MIN_SCORE) \
		--restarts $(HPC_UNSOLVED_RESTARTS) \
		--budget $(HPC_UNSOLVED_BUDGET) \
		--workers $(HPC_UNSOLVED_WORKERS) \
		--stop-no-improve-rounds $(HPC_UNSOLVED_STOP) \
		--artifacts-root $(TAIL_ARTIFACTS_ROOT) \
		--seed-prefix hpc_unsolved \
		--heartbeat-sec $(TAIL_HEARTBEAT_SEC) \
		$(if $(filter 1,$(TAIL_STREAM_SOLVE_LOG)),--stream-solve-log,) \
		$(if $(filter 1,$(TAIL_RESUME)),--resume,) \
		$(if $(filter 1,$(TAIL_SKIP_EXISTING)),--skip-existing,) \
		--run-id $(HPC_UNSOLVED_RUN_ID)

# Phase B (HPC): optimize preference on already-solved plans via densification.
hpc-preference:
	$(PYTHON) scripts/iterate_tail.py \
		--split $(SPLIT) \
		--method $(TAIL_METHOD) \
		--rank-mode preference \
		--pref-metric $(HPC_PREFERENCE_METRIC) \
		--runner densify \
		--rounds $(HPC_PREFERENCE_ROUNDS) \
		--top-k $(HPC_PREFERENCE_TOPK) \
		--min-score $(HPC_PREFERENCE_MIN_SCORE) \
		--workers $(HPC_PREFERENCE_WORKERS) \
		--stop-no-improve-rounds $(HPC_PREFERENCE_STOP) \
		--artifacts-root $(TAIL_ARTIFACTS_ROOT) \
		--seed-prefix hpc_preference \
		--heartbeat-sec $(TAIL_HEARTBEAT_SEC) \
		$(if $(filter 1,$(TAIL_RESUME)),--resume,) \
		--run-id $(HPC_PREFERENCE_RUN_ID)

# Submit preference-only densify rounds to SLURM.
hpc-preference-submit:
	bash slurm/submit_tail_overnight.sh \
		PARTITION=$(HPC_PARTITION) \
		WORKERS=$(HPC_PREFERENCE_WORKERS) \
		MEM=$(HPC_MEM) \
		TIME=$(HPC_TIME) \
		SPLIT=$(SPLIT) \
		METHOD=$(TAIL_METHOD) \
		RANK_MODE=preference \
		PREF_METRIC=$(HPC_PREFERENCE_METRIC) \
		RUNNER=densify \
		ROUNDS=$(HPC_PREFERENCE_ROUNDS) \
		TOPK=$(HPC_PREFERENCE_TOPK) \
		MIN_SCORE=$(HPC_PREFERENCE_MIN_SCORE) \
		STOP_NO_IMPROVE=$(HPC_PREFERENCE_STOP) \
		RUN_ID=$(HPC_PREFERENCE_RUN_ID)

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
	  'make                - default preference workflow (preference-local -> score -> submission)' \
	  'make heavy          - resumable heavy search on the unsolved split' \
	  'make light          - light packing pass across all 1000 + merge' \
	  'make tail-round     - rank low-score tail -> focused solve -> merge -> score' \
	  'make tail-iterate   - multi-round tail optimization with reproducible artifacts' \
	  'make short-local    - short local profile (~10 min) using iterate_tail' \
	  'make overnight-local - long local profile (~7 h) using iterate_tail' \
	  'make preference-local - local preference optimization on already-solved plans (densify only)' \
	  'make preference-quick - one-round quick local preference pass' \
	  'make hpc-tail-submit - submit 7h tail iterate controller job to SLURM' \
	  'make hpc-unsolved   - HPC phase A: solve unresolved tail with CP + heavy search' \
	  'make hpc-preference - HPC phase B: improve preference on solved plans via densify' \
	  'make hpc-preference-submit - submit HPC preference-only densify run to SLURM' \
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
	  '  TAIL_ROUNDS=<n>        default: $(TAIL_ROUNDS)' \
	  '  TAIL_STOP_NO_IMPROVE=<n> default: $(TAIL_STOP_NO_IMPROVE)' \
	  '  TAIL_ARTIFACTS_ROOT=<path> default: $(TAIL_ARTIFACTS_ROOT)' \
	  '  TAIL_RUN_ID=<id>       default: auto timestamp' \
	  '  TAIL_SEED_PREFIX=<str> default: $(TAIL_SEED_PREFIX)' \
	  '  TAIL_RESUME=<0|1>      default: $(TAIL_RESUME)' \
	  '  TAIL_SKIP_EXISTING=<0|1> default: $(TAIL_SKIP_EXISTING)' \
	  '  TAIL_HEARTBEAT_SEC=<sec> default: $(TAIL_HEARTBEAT_SEC)' \
	  '  TAIL_STREAM_SOLVE_LOG=<0|1> default: $(TAIL_STREAM_SOLVE_LOG)' \
	  '  TPC_USE_CP_SOLVER=<0|1> default: $(TPC_USE_CP_SOLVER)' \
	  '  TPC_CP_AFTER_PASS=<0|1> default: $(TPC_CP_AFTER_PASS)' \
	  '  TPC_CP_FOUR_SLOT_SHARE=<0..1> default: $(TPC_CP_FOUR_SLOT_SHARE)' \
	  '  TPC_CP_FOUR_SLOT_ROUNDS=<n> default: $(TPC_CP_FOUR_SLOT_ROUNDS)' \
	  '  TPC_CP_RECON_SHUFFLES=<n> default: $(TPC_CP_RECON_SHUFFLES)' \
	  '' \
	  'Profile knobs:' \
	  '  SHORT_LOCAL_WORKERS=<n> default: $(SHORT_LOCAL_WORKERS)' \
	  '  SHORT_LOCAL_TOPK=<n>    default: $(SHORT_LOCAL_TOPK)' \
	  '  SHORT_LOCAL_RESTARTS=<n> default: $(SHORT_LOCAL_RESTARTS)' \
	  '  SHORT_LOCAL_BUDGET=<sec> default: $(SHORT_LOCAL_BUDGET)' \
	  '  SHORT_LOCAL_ROUNDS=<n>  default: $(SHORT_LOCAL_ROUNDS)' \
	  '  OVERNIGHT_LOCAL_WORKERS=<n> default: $(OVERNIGHT_LOCAL_WORKERS)' \
	  '  OVERNIGHT_LOCAL_TOPK=<n> default: $(OVERNIGHT_LOCAL_TOPK)' \
	  '  OVERNIGHT_LOCAL_RESTARTS=<n> default: $(OVERNIGHT_LOCAL_RESTARTS)' \
	  '  OVERNIGHT_LOCAL_BUDGET=<sec> default: $(OVERNIGHT_LOCAL_BUDGET)' \
	  '  OVERNIGHT_LOCAL_ROUNDS=<n> default: $(OVERNIGHT_LOCAL_ROUNDS)' \
	  '  OVERNIGHT_LOCAL_STOP=<n> default: $(OVERNIGHT_LOCAL_STOP)' \
	  '  PREFERENCE_LOCAL_WORKERS=<n> default: $(PREFERENCE_LOCAL_WORKERS)' \
	  '  PREFERENCE_LOCAL_ROUNDS=<n> default: $(PREFERENCE_LOCAL_ROUNDS)' \
	  '  PREFERENCE_LOCAL_TOPK=<n> default: $(PREFERENCE_LOCAL_TOPK)' \
	  '  PREFERENCE_LOCAL_MIN_SCORE=<n> default: $(PREFERENCE_LOCAL_MIN_SCORE)' \
	  '  PREFERENCE_LOCAL_STOP=<n> default: $(PREFERENCE_LOCAL_STOP)' \
	  '  PREFERENCE_LOCAL_RUN_ID=<id> default: auto timestamp' \
	  '  PREFERENCE_LOCAL_METRIC=<overall|ddr|dav|att> default: $(PREFERENCE_LOCAL_METRIC)' \
	  '  HPC_PARTITION=<name>    default: $(HPC_PARTITION)' \
	  '  HPC_WORKERS=<n>         default: $(HPC_WORKERS)' \
	  '  HPC_MEM=<xG>            default: $(HPC_MEM)' \
	  '  HPC_TIME=<HH:MM:SS>     default: $(HPC_TIME)' \
	  '  HPC_ROUNDS=<n>          default: $(HPC_ROUNDS)' \
	  '  HPC_TOPK=<n>            default: $(HPC_TOPK)' \
	  '  HPC_MIN_SCORE=<n>       default: $(HPC_MIN_SCORE)' \
	  '  HPC_RESTARTS=<n>        default: $(HPC_RESTARTS)' \
	  '  HPC_BUDGET=<sec>        default: $(HPC_BUDGET)' \
	  '  HPC_STOP=<n>            default: $(HPC_STOP)' \
	  '  HPC_RUN_ID=<id>         default: $(HPC_RUN_ID)' \
	  '  HPC_UNSOLVED_WORKERS=<n> default: $(HPC_UNSOLVED_WORKERS)' \
	  '  HPC_UNSOLVED_ROUNDS=<n> default: $(HPC_UNSOLVED_ROUNDS)' \
	  '  HPC_UNSOLVED_TOPK=<n>   default: $(HPC_UNSOLVED_TOPK)' \
	  '  HPC_UNSOLVED_MIN_SCORE=<n> default: $(HPC_UNSOLVED_MIN_SCORE)' \
	  '  HPC_UNSOLVED_RESTARTS=<n> default: $(HPC_UNSOLVED_RESTARTS)' \
	  '  HPC_UNSOLVED_BUDGET=<sec> default: $(HPC_UNSOLVED_BUDGET)' \
	  '  HPC_UNSOLVED_STOP=<n>   default: $(HPC_UNSOLVED_STOP)' \
	  '  HPC_UNSOLVED_RUN_ID=<id> default: $(HPC_UNSOLVED_RUN_ID)' \
	  '  HPC_PREFERENCE_WORKERS=<n> default: $(HPC_PREFERENCE_WORKERS)' \
	  '  HPC_PREFERENCE_ROUNDS=<n> default: $(HPC_PREFERENCE_ROUNDS)' \
	  '  HPC_PREFERENCE_TOPK=<n> default: $(HPC_PREFERENCE_TOPK)' \
	  '  HPC_PREFERENCE_MIN_SCORE=<n> default: $(HPC_PREFERENCE_MIN_SCORE)' \
	  '  HPC_PREFERENCE_STOP=<n> default: $(HPC_PREFERENCE_STOP)' \
	  '  HPC_PREFERENCE_RUN_ID=<id> default: $(HPC_PREFERENCE_RUN_ID)' \
	  '  HPC_PREFERENCE_METRIC=<overall|ddr|dav|att> default: $(HPC_PREFERENCE_METRIC)' \
	  '  VERSION=<vN>           default: next version after the highest v<N> git tag'
