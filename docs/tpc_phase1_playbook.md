# TPC 2026 Phase 1 Playbook

Phase 1 is offline prediction generation on the released `tpc_phase1` data.
Only prediction files are submitted.
The local workflow may use the released oracle fields, including `hard_logic_py`, to optimize and check plans; that privilege does not transfer to Phase 2.

## Current status (2026-07-30, after the upstream evaluator sync)

Score `results/best` with:

```bash
make p1eval SPLIT=tpc_phase1
```

Latest local result on the upstream-aligned evaluator (upstream `main` `764614c`, PRs
[#29](https://github.com/LAMDA-NeSy/ChinaTravel/pull/29) / [#30](https://github.com/LAMDA-NeSy/ChinaTravel/pull/30)):
MicEPR `98.17`, MacEPR `58.20`, C-LPR `54.04`, FPR `58.20`, DAV `58.20`, ATT `58.20`, DDR `58.20`,
overall `61.16`.

The same `results/best` directory scored `100.0` on every metric under the pre-2026-07-28 evaluator.
Nothing about the stored plans changed — the checker did. `418/1000` accepted plans are now rejected,
in exactly two families (counted with the commonsense evaluator, no other sub-check regressed):

| Failing commonsense column | Queries | Cause |
| --- | --- | --- |
| `Does not follow Chronological Order` | `344` | Upstream `Is_time_correct` now rejects intra-day activity overlap and an inbound transport that departs before the previous activity ends. |
| `Repeated Meal Types in One Day` | `149` | Upstream `Is_restaurants_correct` now allows at most one breakfast/lunch/dinner per day; the maxpack hotel-breakfast stacking that lifted DDR to `100` is a failure. |

DAV/ATT/DDR all read `58.20` because every still-passing plan scores a perfect `1.0` on each, while a
failing query now contributes a hard zero to the average (upstream PR #30) instead of being dropped
from it. Recovering the score means **re-solving the rejected queries**, not re-scoring them: the
solver's own acceptance gate calls the same evaluator, so a fresh solve cannot re-create either
failure family. `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` is rewritten by
every `make p1eval` run and is the work list for that re-solve.

## Objective and invariants

The operating loop is:

```text
solve released queries -> validate candidates -> monotonically merge -> score -> package submission
```

- Ground every POI, opening window, price, and transport record in `WorldEnv`.
- Keep OR-style constraint variants branch-local.
- Retain a candidate only after logic, schema, and commonsense acceptance.
- Improve DAV, ATT, or DDR only when that full acceptance remains true.
- Let `scripts/merge.py` be the serialized writer of `results/best/`; do not hand-edit result files or run concurrent merges.
- Keep a stable run ID and seed configuration when a run must be resumed or compared.

## Canonical local flow

From the repository root, run a small resumable search, merge its accepted improvements, then score:

```bash
.venv/bin/python scripts/solve.py --split tpc_phase1 --skip --restarts 120 --budget 60 --workers 1
make merge SPLIT=tpc_phase1
make p1eval SPLIT=tpc_phase1
```

Primary solve knobs are `--restarts`, `--budget`, `--workers`, and `--skip`.
Increase search breadth only after a clean score establishes the target set.

## Focused tail and preference flow

Use the multi-round controller for work that should stop once it no longer improves `results/best`:

```bash
.venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode tail --runner solve \
  --rounds 4 --top-k 120 --restarts 1200 --budget 300 --workers 8 \
  --stop-no-improve-rounds 1 --run-id phase1-tail --resume --skip-existing
```

For already accepted plans whose preference score remains low, rank the preference tail and use the densify runner:

```bash
.venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode preference --pref-metric overall --runner densify \
  --rounds 4 --top-k 120 --stop-no-improve-rounds 1 \
  --run-id phase1-preference --resume
```

`--top-k`, `--rounds`, `--stop-no-improve-rounds`, `--run-id`, and `--resume` define the bounded, resumable controller behavior.
The run directory under `cache/hpc_tail_runs/<run-id>/` records configuration, round summaries, logs, and final full-split score.

## HPC entry

Use the containerized controller rather than solving or merging on a login node:

```bash
PARTITION=standard WORKERS=8 MEM=6G TIME=07:30:00 \
ROUNDS=8 TOPK=240 RESTARTS=1200 BUDGET=300 STOP_NO_IMPROVE=2 \
RUN_ID=tail_hpc_$(date +%Y%m%d_%H%M%S) \
bash slurm/submit_tail_overnight.sh
```

The helper passes the profile to `slurm/tail_overnight.sbatch`.
For the five supported local and Slurm profiles, resource overrides, artifacts, and resume/stop semantics, use [HPC workflows](../slurm/README.md).

## Score and submit

After a completed merge, inspect the full-set score and build the submission archive:

```bash
make p1eval SPLIT=tpc_phase1
make submission VERSION=vN
make upload-check VERSION=vN
```

Run `make upload VERSION=vN` only after the upload check identifies the intended archive.
The competition website, not a local score, is authoritative for leaderboard evaluation and submission rules.

## Reusable solver lessons

- Use `WorldEnv`/`Transportation.poi_search` for POI grounding. CSV coordinates can disagree with the lookup used by `goto`.
- Query the actual `goto` modes for each hop. Do not assume walking is shortest or feasible; choose a returned mode that satisfies the query's time, cost, and mode constraints.
- Rebuild adjacent transports whenever a POI, hotel, or intercity endpoint changes. Validate the whole itinerary, not just the edited activity.
- Keep feasibility ahead of preference. A low-cost or dense candidate is not useful if a verifier rejects it.

## Scope caveat

Local Phase 1 results are evidence about the released data and evaluator only.
They are not a no-oracle Phase 2 result.
The status-heavy chronology, historical score discussions, and experiment notes are preserved in the [2026-07-15 Phase 1 archive](archive/phase1/tpc_phase1_playbook_2026-07-15.md).
