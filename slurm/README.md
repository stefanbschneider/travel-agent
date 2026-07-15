# Phase 1 HPC Workflows

The five profiles below run the deterministic, acceptance-gated Phase 1 controller.
Run all solve, merge, and score work on a compute node or through the submitted controller, never on a login node.

## Profiles

| Profile | Entry point | Intended use |
| --- | --- | --- |
| Short local tail | `scripts/iterate_tail.py` with one compact round | Fast check of a small low-score tail |
| Long local tail | `scripts/iterate_tail.py` with multiple rounds | Resumable overnight local work |
| HPC tail | `slurm/submit_tail_overnight.sh` | Containerized multi-round controller |
| Two-phase HPC | The same helper with `RANK_MODE=unsolved` then `RANK_MODE=preference` | Separate feasibility and preference work |
| Full-set densify array | `slurm/densify_array.sbatch` followed by `merge_score.sbatch` | Preference work after hard metrics are stable |

## 1. Short local tail

```bash
.venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode tail --runner solve \
  --rounds 1 --top-k 24 --restarts 120 --budget 20 --workers 4 \
  --stop-no-improve-rounds 1 --run-id short-local --skip-existing
```

## 2. Long local tail or preference

```bash
.venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode tail --runner solve \
  --rounds 6 --top-k 180 --restarts 900 --budget 180 --workers 8 \
  --stop-no-improve-rounds 2 --run-id overnight-local --resume --skip-existing

.venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode preference --pref-metric ddr --runner densify \
  --rounds 6 --top-k 180 --workers 8 \
  --stop-no-improve-rounds 2 --run-id preference-local --resume
```

`--resume` continues completed rounds only when the run ID and artifacts belong to the same configuration.

## 3. Containerized HPC tail

```bash
PARTITION=standard WORKERS=8 MEM=6G TIME=07:30:00 \
ROUNDS=8 TOPK=240 MIN_SCORE=99 RESTARTS=1200 BUDGET=300 STOP_NO_IMPROVE=2 \
RUN_ID=tail_hpc_$(date +%Y%m%d_%H%M%S) \
bash slurm/submit_tail_overnight.sh
```

The helper submits `slurm/tail_overnight.sbatch`, stages the Python 3.12 environment from the configured image and venv archive, and writes the job ID to `cache/solve_logs/.tail_overnight_jobid`.

## 4. Two-phase HPC

Run feasibility work first, then preference work on accepted plans:

```bash
RANK_MODE=unsolved RUNNER=solve ROUNDS=8 TOPK=240 RESTARTS=1200 BUDGET=300 \
STOP_NO_IMPROVE=2 RUN_ID=unsolved_hpc_$(date +%Y%m%d_%H%M%S) \
bash slurm/submit_tail_overnight.sh

RANK_MODE=preference PREF_METRIC=ddr RUNNER=densify ROUNDS=10 TOPK=400 \
STOP_NO_IMPROVE=3 RUN_ID=preference_hpc_$(date +%Y%m%d_%H%M%S) \
bash slurm/submit_tail_overnight.sh
```

Use `PREF_METRIC=overall`, `dav`, `att`, or `ddr` to select the preference ranking signal.

## 5. Full-set densify array

```bash
array_job=$(sbatch --parsable \
  --export=ALL,TPC_DENSIFY_ATTR_GAP_MIN=75,TPC_DENSIFY_ATTR_DWELL=60,TPC_DENSIFY_ATTR_CANDIDATES=24,TPC_DENSIFY_LATE_DINNER=1,TPC_DENSIFY_EARLY_BREAKFAST=1 \
  slurm/densify_array.sbatch)
sbatch --dependency=afterok:${array_job} slurm/merge_score.sbatch
```

The array writes shard logs to `cache/solve_logs/densify_array_<job>_<task>.log`.
The dependent merge job performs the serialized monotonic merge and full-set score.

## Submission overrides

| Category | Variables |
| --- | --- |
| Resources | `PARTITION`, `WORKERS`, `MEM`, `TIME` |
| Work selection | `SPLIT`, `METHOD`, `RANK_MODE`, `PREF_METRIC`, `RUNNER` |
| Search bounds | `ROUNDS`, `TOPK`, `MIN_SCORE`, `RESTARTS`, `BUDGET`, `STOP_NO_IMPROVE` |
| Reproducibility | `RUN_ID`, `ARTIFACTS_ROOT`, `SEED_PREFIX` |
| Solver tier | `TPC_USE_CP_SOLVER`, `TPC_CP_AFTER_PASS`, `TPC_CP_FOUR_SLOT_SHARE`, `TPC_CP_FOUR_SLOT_ROUNDS`, `TPC_CP_RECON_SHUFFLES` |
| Container | `TPC_PROJECT_DIR`, `BASE_SIF`, `VENV_TAR` |

The controller stops after `STOP_NO_IMPROVE` consecutive zero-update rounds or an empty focus split.
It writes `cache/hpc_tail_runs/<run-id>/run_config.json`, `summary.json`, per-round `rounds/rXX/summary.json`, `logs/rXX_{rank,solve,merge}.log`, and `logs/final_score.log`.
The submitted helper does not forward `--resume`; resume an interrupted controller only with the direct `scripts/iterate_tail.py --resume` command on an appropriate compute allocation.

Keep merges serialized.
Keep the run ID, seed prefix, container image, and staged venv fixed for a comparable run.
Use the [Phase 1 playbook](../docs/tpc_phase1_playbook.md) for the full solve-to-submission flow.
