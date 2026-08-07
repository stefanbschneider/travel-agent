# R25 — separate the CP, restart and outer-budget limits

**Date** 2026-08-07 · **Branch** `eval/r25-cp-restart-separation` · **git_sha** `edb5bb20` ·
**host** 4-core Linux (3 workers) · **Contract** per-query screen, not a `full_runs/`/`runs/` row.
Evaluation workstream instrument: [R25](../../../../docs/tpc_phase2_eval.md#r25--separate-the-cp-restart-and-outer-budget-limits).

**Question.** R24 found `0` flips raising the outer budget `300 s -> 900 s`, but both arms replayed the
same `TPC_MAX_RESTARTS=400` and default `TPC_CP_TIME_LIMIT_SEC` (`min(30, remaining/2)`), so it measured
the outer timeout only. R25 isolates the two internal limits R24 left unchanged: how long CP-SAT gets per
call, and how many random-restart draws the multi-start search gets.

## Method

The first 10 of R24's 30 committed failing uids (`r24_failing30.txt`, itself a zero-cost re-score of R19's
own written plans — see R24's README). Each of three arms re-solves all 10 **fresh**
(`agent_env/scripts/solve_phase2.py --budget-sec 1800`, no `--resume`, distinct `--method` per arm, per-query
mode so the `300 s` sweep-scheduler wiring bug is bypassed entirely), sharded 4/3/3 uids across 3 concurrent
subprocesses (`cores - 1`). Arms ran **sequentially**, one at a time, so wall-clock limits stay comparable
across arms:

| Arm | `TPC_MAX_RESTARTS` | `TPC_CP_TIME_LIMIT_SEC` | Method |
| --- | --- | --- | --- |
| A — control | `400` | `30` (default) | `phase2_e2e_r25_control` |
| B — cp300 | `400` | `300` | `phase2_e2e_r25_cp300` |
| C — r4000 | `4000` | `30` (default) | `phase2_e2e_r25_r4000` |

**Sanity gate, checked before trusting anything else.** Arm A's per-uid `fpr_true`/`overall_true` are
byte-identical to R24's committed `r24_scored_b300.json` on all 10 uids, even though this run is on
`edb5bb20` (post-P16/P19) and R24's was on `54be4514`: the deterministic solver path is unaffected by the
P16/P19 changes, and this confirms the 10-uid subset still fails today exactly as R24 found it. CP-SAT is
pinned to `num_search_workers=1` by default (`cp_solver.py`), so Arm B's three concurrent shards do not
oversubscribe the 4-core box.

**Second sanity gate, run because a `+3.6 s` mean rise alone (Arm B, below) sits inside R24's own
established noise band (`max_abs 6.2 s`) and can't distinguish "CP is not the constraint" from "the CP
branch silently no-ops" — the call is wrapped in `except Exception: pass`.** A fourth, throwaway arm
(`TPC_USE_CP_SOLVER=0`, CP-SAT fully disabled rather than time-boxed) on all 10 uids produced
byte-identical plans and `overall_true` to Arm A on every uid. CP-SAT does not merely fail to move these
10 queries when given `300 s` instead of `30 s` — it contributes nothing to the accepted plan on any of
them at any time budget, including zero. That makes Arm B's null unambiguous rather than merely
consistent with one.

## Result: Arm B is fully inert; Arm C moves one query's plan and one clause, flips none

| Arm | `solve_sec` mean/median/max | restarts used mean/max | stop reason | `fpr_true` passing | plans differing from control |
| --- | --- | --- | --- | --- | --- |
| A control | `85.5 / 98.5 / 128.6` | `328.4 / 400` | `max_restarts` 8, `converged` 2 | `0/10` | — |
| B cp300 | `89.1 / 101.1 / 135.7` | `328.4 / 400` | `max_restarts` 8, `converged` 2 | `0/10` | `0/10` |
| C r4000 | `760.4 / 929.6 / 1201.3` | `3208.4 / 4000` | `max_restarts` 8, `converged` 2 | `0/10` | `6/10` |

**Arm B (CP=300s): zero effect, and the CP-off check above rules out the false-negative reading.** Every
one of the 10 uids has identical `restarts_used`, identical `stop_reason`, and byte-identical
`overall_true` to Arm A; plan JSONs are byte-identical modulo `elapsed_time(sec)` on all 10. `stage_sec.solve`
did rise slightly (`85.5s -> 89.1s` mean) but that sits inside R24's own established noise band, so it
alone would not distinguish "CP proved/exhausted fast" from "CP never ran." The CP-off arm above closes
that gap directly: CP-SAT contributes nothing to the accepted plan on these 10 queries at any budget,
including zero, so Arm B's null reflects the solver, not a silent no-op.

**Arm C (restarts=4000): 0/10 full flips, but real search-space movement.** `fpr_true` stays `0.0` on
every uid — no query became fully passing. But plan *content* differs from control on 6 of the 8 uids that
hit `stop_reason=max_restarts` (the other 2, `...00022` and `...00005`, have the identical
`best_found_at_restart` in both arms — `339` and `66` respectively — meaning nothing beat their
sub-400 incumbent even out to 4000 restarts, so their plans stay byte-identical). For the 6 that do differ,
`best_found_at_restart` in the r4000 arm lands past restart 400 (`455`-`3769`), confirming 400 restarts had
not exhausted the reachable set for them. Score moved on exactly 1 of those 6: uid `...00039`'s
`overall_true` rose `40.0 -> 42.5` because the deeper search found a cheaper
metro+walk-connector route (walk legs at the start/end of a 3-leg inner-city transport tuple are not the
counted "mode" per `innercity_transport_type`, so they don't trip the plan's own "metro/taxi only, no
walking" clauses) replacing taxi legs, pushing total activity+transport cost under the query's budget cap
and flipping that one clause (`logic_py_5`) from `0` to `1`. The query's other blocker
(a timed-window clause) is untouched, so the query overall still fails.

**Failed-clause-family inspection (the doc's own required next step for this row).** Across the 6
differing-plan uids, the clauses that remained unsatisfied in *both* arms are dominated by one family:
**timed-window POI placement** ("visit/dine at position X between time A and time B") — it accounts for
9 of the 11 still-failing clause slots across those uids, and appears in 5 of the 6 uids (the exception,
`...00014`, fails on a transport-cost budget and a required-attraction-inclusion clause, neither timed).
The one clause that *did* flip (`...00039`) was a cost-budget clause, not a timing clause. 10x the restart
budget did not close a single timed-window clause. This reads as a structural/move-set limitation —
hitting a specific narrow arrival/departure window while satisfying everything else is not something
generic random-restart diversity searches into — rather than an under-sampled search space for this
clause family.

## Decision, per the doc's own table

| outcome | this row's outcome | reading |
| --- | --- | --- |
| CP arm flips at least one uid | **no** (`0/10`, byte-identical plans) | CP-SAT contributes nothing to these 10 plans at any budget, including zero (confirmed by the CP-off arm) |
| restart arm flips at least one uid | **no** (`0/10` full passes) | — |
| either single axis flips | **no** | do not spend the combined `CP=300/restarts=4000` arm on all 30 R24 failures |
| no arm changes any plan | **no** (Arm C changes 6/10) | — |
| **plans change but no uid flips** | **yes — this row** | inspect failed-clause families before scaling (done above); do not infer headroom from runtime |

**Net:** the restart axis is not exhausted at 400 draws (Arm C proves the search keeps finding distinct,
occasionally better, candidates out to 4000), but the clause family it is failing to close —
timed-window placement — does not respond to more draws of the same random-restart move set. Per the
doc's own row for this outcome, this closes **blind compute expansion** as a lever (do not scale
restarts further and do not run the 30-uid combined arm on this evidence) and points at **P20/P6/a
timed-window-targeted move** instead: P6 (validator-in-loop Qwen repair) or a dedicated window-fit repair
pass are targeted-edit approaches that fit a "find one specific placement that satisfies a tight window"
problem better than undirected restart diversity does. **R9** (`TPC_P2_EXPLORE=1` whole-run seed-diverse
pass) stays closed: its own gating text requires "R25's restart arm flips at least one uid," and `0/10`
flipped, so seed-diverse exploration remains unmotivated regardless of the partial movement observed.
**P5**'s weaker gate ("a positive R25 arm before default-on implementation") is also not met, so it
stays un-implemented — R25 measured restart volume specifically, not the distinct-seed-diversity
mechanism P5's own argument rests on, so this is not implemented rather than closed outright. **P4**
(raise the per-query budget wiring bug fix) remains a correctness-only fix, per R24 — nothing here
changes that.

## Files

- `r25_failing10.txt` — the fixed 10-uid subset (first 10 of R24's committed `r24_failing30.txt`).
- `r25_scored_control.json`, `r25_scored_cp300.json`, `r25_scored_r4000.json` — per-uid
  `fpr_true`/`overall_true` for the three main arms. The throwaway `TPC_USE_CP_SOLVER=0` discriminator
  arm is not separately scored/committed — it needed only the plan-content/`overall_true` byte-diff
  against Arm A recorded in the text above and in `telemetry_summary.json`.
- `telemetry_summary.json` — solve-time, restart-count, stop-reason, plan-diff and failed-clause-family
  statistics backing the tables above, plus the CP-off discriminator result.
- Raw plans and telemetry are not committed (bulky, reproducible):
  `results/phase2_e2e_r25_{control,cp300,r4000}/`, `agent_env/runs/phase2_e2e_r25_{control,cp300,r4000}/`.
  The throwaway CP-off arm (`phase2_e2e_r25_nocp`) was deleted after recording its result.
