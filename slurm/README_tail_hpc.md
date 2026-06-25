# Tail Optimization Workflows

This repository now supports four deterministic workflows targeting different runtimes.

## 1) Short Local Run (~10 min, M1 MacBook)

Use a single compact tail round:

```bash
make short-local
```

Typical override examples:

```bash
make short-local SHORT_LOCAL_WORKERS=4 SHORT_LOCAL_TOPK=24 SHORT_LOCAL_RESTARTS=120 SHORT_LOCAL_BUDGET=20
```

## 2) Long Local Overnight (~7 h, M1 MacBook)

Use multi-round tail iteration with conservative stop-on-no-improve:

```bash
make overnight-local
```

For preference-only optimization on already-valid plans:

```bash
make preference-local
```

For a single quick local preference round:

```bash
make preference-quick
```

Typical override examples:

```bash
make overnight-local \
  OVERNIGHT_LOCAL_WORKERS=8 \
  OVERNIGHT_LOCAL_ROUNDS=6 \
  OVERNIGHT_LOCAL_TOPK=180 \
  OVERNIGHT_LOCAL_RESTARTS=900 \
  OVERNIGHT_LOCAL_BUDGET=180 \
  OVERNIGHT_LOCAL_STOP=2
```

## 3) Long Overnight On HPC (SLURM)

Submit one controller job that runs `scripts/iterate_tail.py` inside the containerized environment.

```bash
make hpc-tail-submit
```

Or with explicit resource/profile overrides:

```bash
make hpc-tail-submit \
  HPC_PARTITION=standard \
  HPC_WORKERS=8 \
  HPC_MEM=6G \
  HPC_TIME=07:30:00 \
  HPC_ROUNDS=8 \
  HPC_TOPK=240 \
  HPC_RESTARTS=1200 \
  HPC_BUDGET=300 \
  HPC_STOP=2 \
  HPC_RUN_ID=tail_hpc_$(date +%Y%m%d_%H%M%S)
```

Equivalent direct submit helper:

```bash
bash slurm/submit_tail_overnight.sh
```

## 4) Two-Phase HPC Workflow (Recommended)

For stronger preference gains, split overnight compute into two deterministic phases:

```bash
# Phase A: resolve hard-constraint tail first
make hpc-unsolved

# Phase B: then optimize preference on accepted plans
make hpc-preference

# Or submit Phase B as a dedicated SLURM controller job
make hpc-preference-submit
```

Typical override examples:

```bash
make hpc-unsolved \
  HPC_UNSOLVED_WORKERS=8 \
  HPC_UNSOLVED_ROUNDS=8 \
  HPC_UNSOLVED_TOPK=240 \
  HPC_UNSOLVED_RESTARTS=1200 \
  HPC_UNSOLVED_BUDGET=300 \
  HPC_UNSOLVED_STOP=2

make hpc-preference \
  HPC_PREFERENCE_WORKERS=8 \
  HPC_PREFERENCE_ROUNDS=10 \
  HPC_PREFERENCE_TOPK=400 \
  HPC_PREFERENCE_MIN_SCORE=99.5 \
  HPC_PREFERENCE_METRIC=ddr \
  HPC_PREFERENCE_STOP=3
```

Why this split helps:
- unresolved-tail rounds are dominated by hard-logic feasibility search
- preference rounds avoid those cases and spend budget on improving DAV/ATT/DDR of already-valid plans
- focus a single preference component with `HPC_PREFERENCE_METRIC` (`ddr` has the most headroom): each round ranks its focus split by that component's per-query gap instead of the blended total; `overall` (default) keeps the blended remaining-score behavior

## Determinism Guidance

- Keep `RUN_ID`/`TAIL_RUN_ID` fixed per run to freeze split names and seed salts.
- `iterate_tail.py` seed salt format is deterministic by round:
  - `<seed-prefix>_<run-id>_rXX`
- Keep container image and staged venv tar fixed for the run.
- Merge is serialized inside each round; do not run concurrent merges.

## Artifact Layout

All profile runs write to `cache/hpc_tail_runs/<run-id>/`:

- `run_config.json`: full config used for the run.
- `summary.json`: final summary across rounds.
- `logs/rXX_rank.log`: rank output for round `XX`.
- `logs/rXX_solve.log`: solve output for round `XX`.
- `logs/rXX_merge.log`: merge output for round `XX`.
- `logs/final_score.log`: final full-set score, run once after the loop.
- `rounds/rXX/summary.json`: per-round summary. Its `metrics` are the focus-subset evaluation from the merge stage; the true full-set `overall` is in top-level `summary.json` under `final_metrics`.

These files are intended for reproducibility and auditability of overnight runs.
