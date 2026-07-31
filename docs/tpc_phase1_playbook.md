# TPC 2026 Phase 1 Playbook

Phase 1 is offline prediction generation on the released `tpc_phase1` data.
Only prediction files are submitted.
The local workflow may use the released oracle fields, including `hard_logic_py`, to optimize and check plans; that privilege does not transfer to Phase 2.

## Current status (2026-07-31, after repairing the 22-query commonsense tail)

Score `results/best` with:

```bash
make p1eval SPLIT=tpc_phase1
```

Latest local result on the upstream-aligned evaluator (upstream `main` `764614c`, PRs
[#29](https://github.com/LAMDA-NeSy/ChinaTravel/pull/29) / [#30](https://github.com/LAMDA-NeSy/ChinaTravel/pull/30)):
MicEPR `99.93`, MacEPR `98.8`, C-LPR `97.98`, FPR `98.8`, DAV `91.11`, ATT `95.46`, DDR `85.15`,
**overall `97.47`** — up from `96.45` after W1's targeted repair of the 22-query commonsense tail
(`scripts/repair_commonsense.py`, see below), on top of the recovery from the `61.16` post-sync
regression (and above the pre-sync `100.0` floor's real quality, since that score depended on a
preference loophole the new evaluator closes).

### W1: repairing the 22-query commonsense tail (2026-07-31)

The tail described below as "genuinely hard" was, per the same-day update in that section, actually
22 plans that already satisfy 100% of their own logical clauses and are rejected purely for a
scheduling/meal artifact — see
[Shortcomings and plan, W1](tpc_shortcomings_and_plan.md#w1-repair-the-22-query-phase-1-commonsense-tail)
for the full diagnosis and repair design. `scripts/scan_commonsense_residual.py` reproduces the
structural scan (`transport_before_prev_end` 19, `overlap` 16, `repeated_meal` 10, union 22) and
`scripts/repair_commonsense.py` applies four ordered, full-checker-gated repair moves (drop a
duplicate meal, restore chronological list order, re-space a real time overlap, re-ground an
inbound leg that departs too early) on a deepcopy of each stored plan, committing only when the
result is fully accepted:

```bash
.venv/bin/python scripts/scan_commonsense_residual.py --out /tmp/p1_tail.txt   # reproduce the 22
.venv/bin/python scripts/repair_commonsense.py --split p1_commonsense_tail --dry-run
.venv/bin/python scripts/repair_commonsense.py --split p1_commonsense_tail
.venv/bin/python scripts/merge.py --split p1_commonsense_tail --method repair_commonsense
make p1eval SPLIT=tpc_phase1
```

**Result: 10 of 22 repaired and merged** (FPR `97.80 -> 98.8`, C-LPR `96.47 -> 97.98`, overall
`96.45 -> 97.47`). The doc's `98.0`/`99.0` ship-bar targets were not fully reached, because the
remaining 12 are a genuinely-resistant residual, not an implementation gap: inspecting each one
individually showed a shared shape the four repair moves cannot reach without moving an intercity
activity's own ticketed time (which is out of scope by design) — the stored plan's fixed
train/flight departure is itself inconsistent with the rest of that day's (correctly-ordered)
schedule, so no forward-only shift or drop can satisfy both the flight's fixed time and the day's
other activities. A few others trade one hard-logic clause (e.g. a named-restaurant timing clause)
for the commonsense fix, which the full-checker gate correctly refuses to commit. Both are legitimate
solver-level findings the "hard tail" framing had obscured, not evidence the repair script is
incomplete. See the unresolved-uid residual reasons printed by `repair_commonsense.py` for the
current list.

### W2: preference residual over the post-W1 split (2026-07-31)

Ran the existing densify controller over the preference-ranked tail, per
[Shortcomings and plan, W2](tpc_shortcomings_and_plan.md#w2-close-the-addressable-phase-1-preference-residual):

```bash
TPC_PACK_DAV=1 TPC_PACK_DDR=1 .venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode preference --pref-metric overall --runner densify \
  --rounds 4 --top-k 240 --stop-no-improve-rounds 1 \
  --run-id phase1-preference-postW1 --resume
```

**Result: converged after round 0 with `best_updates: 0`.** The 240-query preference-ranked focus
split produced no plan whose densified preference score beat its existing `results/best` entry, so
the controller stopped after one no-improve round and the final full-split score is unchanged from
post-W1 (`97.47477963683579` to the digit). `results/best/` has zero diffs from this run. This is a
clean null result, not a failure: it means the remaining `~+0.3` to `+0.6` preference headroom
estimated pre-W1 is structural (travel-day meal gaps that are correct to leave empty, single-day
trips with no room for a fourth attraction, hops already at their shortest available mode), not
addressable by inserting more activities into already-accepted plans.

### How the recovery happened

The `2026-07-30` sync (below) turned `418/1000` accepted plans invalid: `344` failed the new
intra-day-chronology check, `149` failed the new one-meal-type-per-day check (`75` failed both).
Direct inspection of the affected `results/best` entries traced both families to one cause: a legacy
hotel-breakfast-stacking pattern (predating `TPC_PACK_HOTEL_BREAKFAST` being made opt-in and
permanently off) baked extra free hotel breakfasts into a day without re-timing the
activities/transports that followed. The old, pre-2026-07-28 evaluator had no repeated-meal-type or
intra-day-overlap check, so the stacking was invisible and inflated DDR to `100` for those queries;
the synced evaluator now rejects it outright.

The current solver already disables that stacking by default (confirmed by resolving one affected
query fresh: the result had no repeated meals and no overlaps), so no solver code change was needed.
Recovery was two safe, already-scripted operations, each gated so `results/best` can only improve:

1. **Re-solve the rejected queries** (`scripts/solve.py` against
   `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt`, then `make merge`). `make merge`
   only overwrites a `results/best/<uid>.json` when its freshly computed weighted score is *strictly*
   higher than what is already there, so this can never regress an untouched query. Three rounds
   (`60s`/`120` restarts, then `300s`/`1200` restarts on the residual, then a
   `TPC_COMMONSENSE_FIRST=1` pass on the smaller residual) took overall `61.16 -> 95.70` and cut the
   fully-failing count from `418` to `22`. The `22` that remain are a genuinely hard tail. One
   contributing cause, found while diagnosing a 3-person Nanjing<->Chongqing train-only round trip in
   that tail: the solver's random-restart search sometimes overrode a hard `intercity_mode` constraint
   with a random airplane choice (`tpc_agent.py`'s `_random_params`), burning restart budget on
   candidates guaranteed to fail acceptance — not a train-availability problem (`WorldEnv` had `31`/`22`
   train options each way for that example). Fixed directly (unconditional bug fix, shared TPCAgent
   code, so it also applies to the Phase 2 no-oracle path): `_random_params` no longer randomizes a
   direction `constraints.intercity_mode` already pins. Retrying the `22`-query tail under the fix
   (`TPC_COMMONSENSE_FIRST=1`, `300s`/`2400` restarts) recovered `0` more — the mode override was a
   real, wasted-budget bug worth fixing on its own merits, but not this tail's binding constraint;
   whatever else makes these `22` hard (tight same-day arrival/meal scheduling, per manual inspection)
   remains an open follow-up, not a quick win.

   **Update (2026-07-31): "hard tail" describes the solver, not the plans.** A structural scan of all
   `1000` stored plans flags exactly these `22`, and only on the two rules the sync added — `19` have an
   inbound leg departing before the previous activity ends, `16` have an intra-day overlap or a
   non-chronological activity list, `10` repeat a meal type (union `22`; no other structural family is
   violated anywhere in the split). All `22` satisfy **every** one of their logical clauses: they hold
   `126` of the split's `3568` `hard_logic_py` clauses (`3.53%`) and measured C-LPR is exactly
   `96.47 = 100 − 3.53`. So a fresh solve cannot recover them, but a targeted **plan-level repair** of
   the stored plan (drop the duplicate meal, restore chronological order, re-space the overlap,
   re-ground the early leg) very likely can — worth `~+2.2` overall. That repair was never attempted;
   it is specified end to end as W1 in
   [Shortcomings and plan](tpc_shortcomings_and_plan.md#w1-repair-the-22-query-phase-1-commonsense-tail).
2. **Densify already-accepted plans** (`TPC_PACK_DAV=1 TPC_PACK_DDR=1 scripts/densify.py`, then
   `make merge`). `densify.py` only mutates a plan that is already accepted, only keeps the result if
   the full checker *still* accepts it and its preference sum is strictly higher, and `make merge`
   re-applies its own strictly-greater gate on top — two independent monotonic guards. This is safe to
   run on the full split regardless of whether a query was part of the `418`; it lifted `overall`
   `95.70 -> 96.45` (`DAV` `79.63 -> 90.11`, `ATT` `92.22 -> 94.46`, `DDR` `82.04 -> 84.26`) with FPR
   unchanged, and a second pass found nothing further (converged). `TPC_PACK_HOTEL_BREAKFAST` was left
   off throughout — it is now a structural no-op, since `check()` reverts any stacked meal day.

`chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` is rewritten by every `make p1eval`
run and remains the re-solve work list (currently `418` entries — the `22` that still fail a hard
check, plus queries whose preference score is not literally `100`, which is most of the split and not
itself evidence of a problem).

### Evaluator-sync history (2026-07-30)

Nothing about the stored plans changed on sync day — the checker did. `418/1000` accepted plans were
rejected, in exactly two families (counted with the commonsense evaluator, no other sub-check
regressed):

| Failing commonsense column | Queries | Cause |
| --- | --- | --- |
| `Does not follow Chronological Order` | `344` | Upstream `Is_time_correct` now rejects intra-day activity overlap and an inbound transport that departs before the previous activity ends. |
| `Repeated Meal Types in One Day` | `149` | Upstream `Is_restaurants_correct` now allows at most one breakfast/lunch/dinner per day; the maxpack hotel-breakfast stacking that lifted DDR to `100` is a failure. |

DAV/ATT/DDR all read `58.20` on that day because every still-passing plan scored a perfect `1.0` on
each, while a failing query contributed a hard zero to the average (upstream PR #30) instead of being
dropped from it — see "How the recovery happened" above for what fixed it.

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
