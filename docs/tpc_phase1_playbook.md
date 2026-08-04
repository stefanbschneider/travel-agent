# TPC 2026 Phase 1 Playbook

Phase 1 is offline prediction generation on the released `tpc_phase1` data.
Only prediction files are submitted.
The local workflow may use the released oracle fields, including `hard_logic_py`, to optimize and check plans; that privilege does not transfer to Phase 2.

## Current status (2026-08-02, after clearing all but one of the commonsense tail)

Score `results/best` with:

```bash
make p1eval SPLIT=tpc_phase1
```

Latest local result on the upstream-aligned evaluator (measured against upstream `main` `764614c`, PRs
[#29](https://github.com/LAMDA-NeSy/ChinaTravel/pull/29) / [#30](https://github.com/LAMDA-NeSy/ChinaTravel/pull/30);
the 2026-08-04 sync to `c89cfca` left the scoring rules untouched, so these numbers still stand):
MicEPR `99.99`, MacEPR `99.9`, C-LPR `99.83`, FPR `99.9`, DAV `95.41`, ATT `98.62`, DDR `87.36`,
**overall `98.98`** — up from `97.47`, in the two steps recorded as W1b and W2b below. Submitted
as **v9**.

Two earlier conclusions in this document turned out to be wrong, and both errors had the same shape:
a residual was recorded as *structural* on evidence that only showed the tried approach had stopped
working. Neither the 12-query commonsense tail nor the preference deficit was actually structural.

### W1b: the "genuinely-resistant" 12 were an overfull-day artifact (2026-08-02)

[W1 below](#w1-repairing-the-22-query-commonsense-tail-2026-07-31) closed with 10 of 22 repaired and
the remaining 12 recorded as a residual that "no forward-only shift or drop can satisfy". That
diagnosis was wrong in one specific way, and the fix follows directly from correcting it: those days
are **overfull**, and R3's forward shift is the wrong move on an overfull day. Every shift ripples
into the next activity and eventually pushes a clause-pinned POI out of its own window, so the repair
trades one failure for another and the full-checker gate correctly refuses to commit — which is what
made the tail look irreducible.

`scripts/repair_commonsense.py` now builds four variants and keeps the best by `_variant_key` (full
acceptance, then the schema+commonsense gate every other component is conditioned on, then satisfied
clauses, then the DAV/ATT/DDR sum):

| variant | move | for |
| --- | --- | --- |
| shift-first | R1-R4, unchanged | a merely mistimed day |
| drop-first | R1 + **R5** | an overfull day: rebuild it as a maximal feasible chain, dropping what a grounded leg cannot reach inside its own opening hours and meal band |
| drop-first, unprotected | R5 without the clause-named-POI rule | a clause that only names a POI rather than pinning its window |
| drop-first, cheapest legs | R5 preferring the cheapest *fitting* leg | a query whose clauses cap inner-city transport spend |

Three details inside R5 each fixed real failures in this tail, and each is a fact about the
evaluator rather than a tuning knob:

- **The day anchor is the previous day's last position**, not the stored opening leg's origin. The
  space checker walks one global position chain across days, so deriving the anchor from a leg R1
  may have just dropped silently moves where the day starts.
- **A leg is rebuilt in the activity's own stored mode first**, falling back to the fastest valid
  mode. A repair should fix a broken timing, not silently upgrade a free walk to a paid taxi and blow
  an inner-city-cost clause. When a clause does cap that spend, the fourth variant goes further and
  takes the cheapest leg that still fits.
- **A fixed departure leg is only reachable if the last kept activity leaves time to *travel* to the
  boarding point.** "Ends before the flight departs" is the weaker test, and the gap between the two
  is exactly what leaves `transport_before_prev_end` flagged after R4 declines to reground the leg.

```bash
.venv/bin/python scripts/scan_commonsense_residual.py \
  --out chinatravel/evaluation/default_splits/p1_commonsense_tail.txt
.venv/bin/python scripts/repair_commonsense.py --split p1_commonsense_tail
.venv/bin/python scripts/merge.py --split p1_commonsense_tail --method repair_commonsense
make p1eval SPLIT=tpc_phase1
```

**Result: 11 of 12 repaired** — FPR `98.8 -> 99.8`, C-LPR `97.98 -> 99.66`, MacEPR `98.8 -> 99.8`,
overall `97.47 -> 98.53`.

**The twelfth (`20250324200212786306`) is a real solver-level gap, not a repair gap**, and is the
honest residual this section leaves open. Its clauses require a visit to a named restaurant between
`11:10` and `12:10`; the stored plan does not contain that activity at all, and repair moves only
drop and re-time what is already there. A fresh solve of all 12 at `900 s` / `6000` restarts with
`TPC_COMMONSENSE_FIRST=1` produced nothing acceptable for any of them, so it is not reachable from
that direction either — closing it needs the solver to construct the missing meal, not the repair to
rearrange what exists.

### W2b: three unused preference paths, not a converged residual (2026-08-02)

[W2 below](#w2-preference-residual-over-the-post-w1-split-2026-07-31) recorded the preference deficit
as structural because the densify controller converged with `best_updates: 0`. The controller had
converged — against a densify pass that never reached three code paths already sitting in
`tpc_agent.py`, each implemented, flag-gated, and called from nowhere:

- **`_insert_restaurant_breakfast`.** The DDR top-up only ever tried lunch and dinner. Every Phase 1
  day missing a breakfast is an **arrival day** (`399` of them; not one middle or final day in the
  split lacks one), so this was the entire breakfast headroom. Now reached from `TPC_PACK_DDR`, at a
  real priced restaurant inside the evaluator's `06:00 -- 09:00` band — never the free
  hotel-breakfast variant, which keeps its own flag and stays off.
- **`_upgrade_transport_modes` / `_swap_attractions_for_att` / `_swap_restaurants_for_att`.** These
  are the ATT optimizers W2 itself described as "already implemented … and just needs to run
  standalone over already-accepted plans". They ran only from `scripts/maxpack.py`, a pre-sync
  loophole tool nothing calls any more. New `TPC_PACK_ATT` runs them in a bounded convergence loop
  *after* the top-ups, so it also shortens the hops those introduce. Every move preserves activity
  counts, so DAV/DDR/C-LPR/FPR cannot regress.
- **`_compress_activity_windows`.** Trims an over-long visit back to the standard dwell, which is
  what a day whose meal band is merely *occupied* rather than genuinely full needs before a top-up
  can place anything. Opt-in via `TPC_DENSIFY_COMPRESS_BEFORE`; each trim reverts unless the full
  checker still accepts, so a `stay_duration` clause that needs the longer visit keeps it.

One further limitation was structural rather than unused: the attraction top-up stopped at a hard
four per day, but DAV is `attraction_count / (4 * day_count)` — a **plan-level** ratio. A day that
physically cannot hold four (a travel day around a fixed intercity leg) permanently capped the plan
even when a later day had room. The stop condition is now the plan's remaining deficit, bounded by
`TPC_DENSIFY_ATTR_DAY_CAP` (default `8`).

```bash
TPC_PACK_DAV=1 TPC_PACK_DDR=1 TPC_PACK_ATT=1 \
  .venv/bin/python scripts/densify.py --split tpc_phase1 --workers 4
make merge SPLIT=tpc_phase1
# second pass, with the compress-before knob on
TPC_PACK_DAV=1 TPC_PACK_DDR=1 TPC_PACK_ATT=1 TPC_DENSIFY_COMPRESS_BEFORE=1 \
  .venv/bin/python scripts/densify.py --split tpc_phase1 --workers 4
make merge SPLIT=tpc_phase1
make p1eval SPLIT=tpc_phase1
```

**Result: **Result: `+0.44` overall over three passes** (`98.53 -> 98.79 -> 98.98 -> 98.98`, the third pass merging 2 plans and converging). DAV `92.02 -> 95.41`, ATT `96.43 -> 98.62`, DDR `85.95 -> 87.36`, with FPR and C-LPR unchanged — every move is acceptance-gated, so they cannot move. W2's original ship bar ("DAV/ATT/DDR each not lower and at least one materially higher, with FPR and C-LPR unchanged") is met on all three.

**What is still structural, on the measurement that supports it:** the DDR residual. Of the `1107` missing meal-slots W2 counted, `696` fall on travel days where an intercity leg eats the meal band; leaving those empty is correct rather than a defect. That part of W2's conclusion survives — it was the *other* `411` the pass could not reach.**

All four packing flags stay **default off**, so the library floor is byte-identical and the Phase 2
deterministic path is unchanged. They are Phase 1 offline-optimization switches until a Phase 2
screen says otherwise ([S9/W9](tpc_shortcomings_and_plan.md#w9-re-decide-preference-packing-on-post-sync-evidence)).

### W1: repairing the 22-query commonsense tail (2026-07-31)

> Superseded in part by [W1b](#w1b-the-genuinely-resistant-12-were-an-overfull-day-artifact-2026-08-02):
> the "genuinely-resistant residual" this section describes was 11 repairable plans and one real
> solver gap. Kept as the record of the first round.

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

> Superseded by [W2b](#w2b-three-unused-preference-paths-not-a-converged-residual-2026-08-02): the
> null result below is real, but it measured a densify pass that could not reach breakfast, the ATT
> optimizers, or the compress-before trim, and that capped attractions per day rather than per plan.
> Kept as the record of what was tried.

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
