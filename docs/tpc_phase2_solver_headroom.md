# Phase 2 solver-only headroom on familiar-100

Diagnostic analysis of the **solver-only** failure surface (oracle constraints fed to a bounded
solve, parser removed) on the official familiar-100 development set, plus the first, opt-in step to
close it. This is a development signal, not a promotable result — see
[Phase 2 evaluation](tpc_phase2_eval.md) for the gate discipline and
[Phase 2 roadmap](tpc_phase2_roadmap.md) for priorities. The relevant invariant is G8 in the
[archived gap map](archive/phase2/tpc_phase2_plan3.md): the small, concentrated solver headroom.

## Why solver-only now

The landed parser fixes took familiar-100 parser F1 from `~0.20` to `~0.95` with zero missing
families. Once parsing is that good, the **solver-only ceiling becomes the binding constraint on
end-to-end score**: with oracle-perfect constraints the solver still passes only `26/100`
(`solver_only_fpr = 26.0`, stable across both committed familiar rows and both repeats). Every one of
those `74` failures is genuine, not a timeout artifact — all `23` solver-only timeouts recovered into
*pass* cases, and none of the `74` failures timed out (roadmap "Current evidence"). More wall-clock
will not move it.

## Where the solver fails (attribution)

Reproduce with the committed diagnostic (offline; reads the committed baseline's per-clause verdicts
and the split's oracle `hard_logic_py`, makes no LLM calls and re-solves nothing):

```
python3 scripts/phase2_solver_failure_attribution.py            # latest familiar row, solver-only
python3 scripts/phase2_solver_failure_attribution.py --mode end-to-end
```

Against `results/phase2_baselines/runs/20260718T155006Z.json`:

| Layer | pass (macro) | micro |
| --- | --- | --- |
| Schema | 100/100 | — |
| Commonsense (EPR) | 76/100 | 98.19 |
| Logical (C-LPR) | 28/100 | 88.91 |
| **All (FPR)** | **26/100** | — |

Logical satisfaction is the binding surface, and one family dominates it:

| logical family | failing queries | failed instances | sole blocker |
| --- | --- | --- | --- |
| **timed_visit_named_poi** | **70** | **104** | **53** |
| required_attractions | 6 | 6 | 1 |
| required_restaurants | 6 | 6 | 0 |
| room_count | 2 | 2 | 0 |
| required_cuisine_types | 2 | 2 | 0 |
| (others) | ≤1 each | | |

`sole_blocker` = queries where the family is the *only* failing logical family, so fixing it alone
flips the query to logical-pass. **timed_visit_named_poi is the sole blocker in 53 of the 74
failures** — the single highest-leverage target by a wide margin, quantitatively confirming G8.

The commonsense residual (24 queries) is a separate, smaller surface dominated by
"Invalid Transport information across positions" (18) and intercity-event grounding (6); out of scope
for this step.

### The failure mechanism

The clause requires *an activity of a given type, at a named position, within `[earliest,
end_before]`*. The `104` failing instances split by the named position's database:

- **44 meals at a named accommodation** (a hotel breakfast, e.g. "dine at *Nanyang Inn* between
  07:50 and 08:40" where the inn is an accommodation, not a restaurant),
- **39 attraction visits at a named attraction** (e.g. "*Bear Grandma's Garden* 17:57-19:47"),
- **21 meals at a named restaurant**.

Two concrete gaps, confirmed by reproducing failing plans:

1. **Pool routing.** `_apply_search_constraints` projected window/position names only into
   `required_attractions`/`required_restaurants`. An accommodation name resolves in neither, so
   "meal at *Nanyang Inn*" never pinned hotel selection to that inn — the plan stayed elsewhere and
   the named meal was absent.
2. **Timing.** The greedy slotter schedules included POIs by visit order, not by clause window, so a
   present named POI lands at the wrong time (a required 07:50-08:40 hotel breakfast placed
   07:30-08:30; a required evening attraction placed in the morning).

## Step 1: opt-in timed-window pinning (`TPC_PIN_TIMED_WINDOWS`, default off)

Implemented in `chinatravel/agent/tpc_agent/tpc_agent.py`, gated behind `TPC_PIN_TIMED_WINDOWS`
(default **off**, so the deterministic floor is byte-identical; asserted by unit tests). When on:

- **Pool routing** — `_apply_search_constraints` also projects window/position names into
  `required_hotels` (the per-DB resolver keeps a name only in the pool it matches), so a named
  accommodation pins hotel selection there and its hotel breakfast can satisfy the clause.
- **Retiming** — `_pin_timed_windows` (run in `_pack_plan` *before* the acceptance gate, since a
  window-failing plan is by definition not yet accepted) shifts a present-but-mistimed matching
  activity into `[earliest, end_before]`, recomputing its own inbound leg and the following
  activity's inbound leg. Every shift is trialed on a deepcopy and committed only if the full checker
  then accepts and the preference key does not regress — so it can flip a sole-window-blocker to
  accepted and never regresses a plan.

Verified: the retime mechanics (`tests/phase2/test_pin_timed_windows.py`) and, on failing uid
`...00062`, the `required_hotels` projection moving the required breakfast onto the named inn.

### Known limits / what the gate must check

- **Cascade.** Retiming is *local* — no day resequencing. On back-to-back-packed days a morning→
  evening move (the 39 attraction cases) is rejected for lack of slack. The next increment is a
  within-day resequencer (order a day's non-intercity activities by target window, recompute the
  full day's inbound legs, commit acceptance-gated on a deepcopy, intercity anchors fixed), staged
  in the [roadmap](tpc_phase2_roadmap.md) follow-on item 6.
- **A rejected idea.** Emitting `arrive_no_later` from `end_before` (to time morning meals)
  **regressed commonsense** on the floor — its ceiling pruned proper transport, producing
  transport-less plans that fail "Invalid Transport information across positions." It was dropped;
  do not reintroduce it without gating.
- **No promotion without the gate.** No committed familiar row records flags, and both ran a Qwen
  backend (auto-enabling `llm_parse`), so none is a true flags-off baseline. Before promoting this
  step: record a clean flags-off solver-only familiar-100 baseline, then run flag-on through the
  pinned no-oracle gate (`make phase2-gate`) against `20260718T155006Z` and promote only if
  solver-only FPR improves with no new parse failures or timeouts.

## Out of scope

The constraint-light feasible fallback (G7, `fallback.py`'s empty itinerary) does not move
solver-only FPR — those failures are produced-but-invalid plans, not solver failures/timeouts — so it
is tracked separately.
