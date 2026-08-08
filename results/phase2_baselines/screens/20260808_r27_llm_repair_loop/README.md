# R27 — the P6 validator-in-loop falsification screen

**Date** 2026-08-08 · **Branch** `implementation/p6-validator-in-loop-repair` · **Box** the coding VM
(2 cores), live DeepInfra backend. **Contract**: `scripts/phase2_r27_repair_loop_screen.py`, the
roadmap's own cheap falsification screen for P6 — "ten deterministic failures split across
timed-window, name/type and transport/budget blockers, `temperature=0`, at most six calls/query.
Continue only if at least one previously failing query becomes accepted, MacEPR does not fall, all
emitted facts ground, and the call/timeout counters prove the loop ran. A partial-score move with
zero accepted flips is a RED result."

## What P6 built

`TPC_P2_LLM_REPAIR_LOOP=1` (library default off), independent of `TPC_P2_LLM_REFINE`:

- **`insert_activity`** joins `refine.py`'s typed-edit vocabulary (`REFINE_ALLOWED_OPS`) — the one
  thing `shift_activity_window`/`swap_activity`/`drop_activity`/`reorder_day` cannot express, since
  each of them only ever references an activity already in the plan. `TPCAgent._refine_insert_activity`
  resolves the named POI through `_resolve_timed_window_poi` (a real catalog lookup) before ever
  touching the plan — "never as free-form plan JSON", matching the roadmap's own requirement — and
  grounds both legs via `_best_transport_via_get_transport`, same discipline as the P8/P9/P25
  insertion helpers, without their per-op accept-gate (batch acceptance is `ground_and_check`'s job,
  like every other `_refine_*` handler).
- **`orchestrator.llm_refine`'s attempt loop is generalized** from a hardcoded "1 + optional 1 retry"
  into a `max_attempts`-bounded loop (default `2`, reproducing `TPC_P2_LLM_REFINE`'s exact existing
  behaviour byte-for-byte — all 28 pre-existing tests pass unchanged). `TPC_P2_LLM_REPAIR_LOOP=1`
  raises `max_attempts` to `6` ("keep the first spike to six rounds"). Each round still sees the
  *previous* round's post-edit failure summary — "deterministic rejection feedback" — which is what
  the roadmap says is allowed to revisit this territory even though "both refine variants show
  `improve_committed=0`" already.
- **Worker-count throttle**: when the flag is on, `run_sweeps_split` clamps the sweep scheduler's
  worker pool to `min(workers, 8)` — "throttle to at most eight concurrent requests for organizer
  parity". Each worker makes at most one LLM call at a time, so the pool size directly bounds
  concurrent requests; no cross-process semaphore needed.

36 new/updated unit tests across `test_llm_refine.py` (max_attempts loop semantics),
`test_llm_refine_agent.py` (`_refine_insert_activity`, 6 new cases), `test_flags.py`/
`test_orchestrator.py` (flag wiring, independent of `llm_refine`), and
`test_llm_repair_loop_wiring.py` (worker clamp). `pytest tests` green (full suite, `-m integration`
included).

## Methodology

**Selection** (deterministic, no LLM, no network): solved a 30-query pool from
`tpc_phase2_familiar_100_val` at a 30s budget (harness-default flags, repair loop off), classified
each still-failing query's oracle clauses by family
(`phase2_solver_failure_attribution.classify_constraint`), bucketed into the roadmap's three shapes,
and round-robinned up to 10 across buckets.

**Screen** (live, real cost): re-solved each selected query *from scratch* — not a bolt-on retry on
top of the selection plan — with `TPC_P2_LLM_REPAIR_LOOP=1`, `TPC_P2_LLM_BACKEND=deepinfra`,
`TPC_P2_LLM_TEMPERATURE=0`, `TPC_P2_LLM_TIMEOUT_SEC=15`, `budget_sec=600`. `temperature=0` per the
roadmap; timeout lowered from the 30s default so more of the ~54s `improve_sec` slice (10% of 600s)
could fit multiple rounds without the loop being cut short by the outer deadline check before it
tried.

```bash
TPC_P2_LLM_BACKEND=deepinfra TPC_P2_LLM_TEMPERATURE=0 TPC_P2_LLM_TIMEOUT_SEC=15 \
.venv/bin/python -c "... see scripts/phase2_r27_repair_loop_screen.py's select_queries/run_repair_loop_arm ..."
```

**A measurement pitfall found and corrected while writing this up.** The selection budget (30s) was
smaller than the repair-arm's budget (600s), so 2 of the 10 selected queries turned out to already
pass on the *deterministic* re-solve alone once given 20x more search time — before Stage 3 ever
got a chance to run (`improve_llm_called: false`, `improve_skip_reason: "already_accepted"` on both).
The script's first version counted these as accepted flips (`2/10`, misread as a borderline GREEN).
They are not: crediting the LLM loop for a flip it never touched would be exactly the kind of
self-deception this project's own measurement discipline exists to catch (see
[the P22/R30 and P17(a) screens](../20260808_p17a_coverage_unknown/README.md) for the same
category of trap in earlier items). Fixed in `phase2_r27_repair_loop_screen.py`: the summary now
reports `n_flipped_to_accepted_total` (raw) alongside `n_flipped_to_accepted_via_llm_repair_loop`
(`accepted and improve_llm_called`), and the verdict uses only the latter.

**Bucket distribution, honestly reported rather than forced.** The pool's residual at this
budget/size skewed heavily toward `timed_visit_named_poi`: **9 timed_window, 1 name_type, 0
transport_budget** — not the even three-way split R27's prose suggests. This matches the project's
own standing diagnosis (`timed_visit_named_poi` "accounted for almost all of the in-distribution
loss") rather than a selection bug; a larger pool would very likely still be timed-window-dominated
at this budget. Read the timed-window-heavy result as *the shape the residual actually has*, not as
an intent to stress-test that one family disproportionately.

## Results

| | value |
| --- | --- |
| queries selected | 10 (9 timed_window, 1 name_type, 0 transport_budget) |
| LLM actually called | 8/10 (2 already accepted deterministically, no call needed) |
| **accepted flips caused by the repair loop** | **0/10** |
| (accepted total, including the 2 non-LLM ones) | 2/10 |
| edits that individually grounded | 1 (`shift_activity_window`, uid `..._00005`, round 1) |
| whole-batch commits (`improve_committed`) | 0/10 |
| ungrounded facts | 0/10 |
| timeouts | 0/10 |
| max rounds any query used | 6 (`..._00005`) |

**Verdict: RED.** Zero accepted flips caused by the repair loop — the roadmap's own stated RED
condition ("a partial-score move with zero accepted flips is a RED result"). Full per-query detail:
[`r27_summary.json`](r27_summary.json).

## Reading the RED result

**The loop ran correctly and safely; it did not produce a flip in this sample.** Every safety
property held: 0 ungrounded facts, 0 timeouts, real deterministic rejection feedback flowed between
rounds (query `..._00005` used all 6 rounds), and the new `insert_activity` op fired at least once
(`..._00087`, though it failed to ground — `next_activity_unreachable`). The failure mode is
different from the two prior refine variants' `improve_committed=0`: here individual edits
sometimes ground (`..._00005`'s round-1 `shift_activity_window` committed as an edit) but the
*whole batch* still doesn't clear the full acceptance bar, and in most rounds no edit grounds at
all — the dominant per-edit rejection reasons are `no_time_left_after_arrival` and
`next_activity_unreachable`, i.e. the model's proposed times/insertions are frequently infeasible
given the day's actual transport-and-hours structure, which it cannot see in enough detail from the
compact plan + failure summary in the prompt to reliably avoid.

**This does not contradict `_relocate_timed_windows_across_days` (P25)'s `+2/40` result on the same
family.** P25's move is a *deterministic* search over grounded candidate slots (try every day, every
insertion point, keep the first that grounds); this LLM loop proposes one edit set per round and
only re-tries with the checker's own rejection reason as guidance, with no equivalent systematic
search over placements. The gap between "a deterministic move that tries every option" and "an LLM
that proposes one option informed by a text summary" is exactly what this RED result measures.

## Verdict and next step

Per the roadmap's own falsification bar, this is a stop: do not spend further effort on this
architecture without new evidence. `TPC_P2_LLM_REPAIR_LOOP` stays library default off, matching
`TPC_P2_LLM_REFINE`. The `insert_activity` op and the generalized `max_attempts` loop remain in the
codebase (both are correctness-neutral, tested additions to an off-by-default path — `llm_refine`'s
default-`max_attempts=2` behaviour is unchanged, confirmed by all 28 pre-existing tests), available
if a future architecture wants either primitive, but neither is claimed to move the score. Not
re-attempted here: increasing `n` beyond 10 (the bar is met at 10; a RED result does not become
GREEN by re-rolling), or giving the model more structured spatial context than the current compact
plan (a plausible next architecture change, but a different experiment, not a re-run of this one).
