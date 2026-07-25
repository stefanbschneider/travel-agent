# Intercity-transport endpoint grounding (implementation brief)

Focused implementation brief. Self-contained: hand to an implementation agent. Targets the **intercity
commonsense residual** the post-pin solver-only attribution surfaces — a failure family that neither
pinning/cascade (timed windows) nor transport-repair (inner-city legs) touches.

## The failure, precisely

The official commonsense check `Is_intercity_transport_correct`
(`chinatravel/symbol_verification/commonsense_constraint.py:175`) requires **the first activity of day 1
and the last activity of the last day to each be a valid intercity transport** — a `train`/`airplane`
activity whose `FlightID`/`TrainID`, `start`/`end`, `start_time`/`end_time`, and `price` exactly match a
real row returned by `intercity_transport.select(start_city, target_city, type)` (outbound) or
`select(target_city, start_city, type)` (return).

Crucially, its checks **cascade**: if the plan has no first/last activity, or that activity isn't an
intercity transport, the evaluator sets **all four columns to 1 at once** and returns:

```
"Intercity transportation events must occur"
"Invalid Trains or Airplanes, given TrainID/FlightID, origin and destination"
"Incorrect Information of Intercity Transport on price or duration"
"Incorrect Cost on Intercity Transportation"
```

This is confirmed empirically on the pin-on solver-only row
(`results/phase2_baselines/runs/20260722T195341Z.json`): the **same 4 queries** fail **all four
columns simultaneously** — the identical uid lists prove one structural defect, not four independent
price/time errors. So closing the structural defect flips all four columns for those queries.

**Repro uids (solve these solver-only and inspect `itinerary[0].activities[0]` and
`itinerary[-1].activities[-1]`):**

```
phase2_familiar_e20241028160321868761_00024
phase2_familiar_e20241028160403455246_00065
phase2_familiar_e20241028160409480928_00071
phase2_familiar_e20241028160444030851_00066
```

Reproduce (no LLM): `make phase2-query P2_QUERY_ARGS="--uid <uid> --budget-sec 60"` (or the solver-only
rehearse path), then check whether the first/last activity is a grounded intercity transport.

## Root-cause hypothesis (verify before coding)

The greedy `_build_plan` (`chinatravel/agent/tpc_agent/tpc_agent.py`) selects the return leg via
`_get_intercity` with time fallbacks (`17:00 → 14:00 → 00:00`, lines ~3227–3236). When **all** of those
return `None` (no feasible return row under the day's timing), `return_transport` stays `None` and the
last-day tail is built without a valid grounded return endpoint — so the plan's last activity is not an
intercity transport and the evaluator cascade fires. The outbound endpoint has the analogous path.
Likely triggers to check on the 4 repro uids: a return that departs before the last-day activities can
finish (so every candidate row is infeasible), an endpoint dropped by the mid-itinerary intercity
sanitizer (`_prune_middle_intercity` / `_is_intercity_activity`), or a timeout-recovery snapshot that
predates the endpoint being set.

Confirm which of these it is on each uid before implementing — the fix differs slightly if the row
exists but is infeasibly timed (needs a later/earlier valid row) vs. genuinely absent.

## Proposed mechanism: opt-in `TPC_REPAIR_INTERCITY` (default off, floor byte-identical)

Mirror the landed `_repair_transport_gaps` pass exactly (same shape, same guarantees):

- A new `_repair_intercity_endpoints(plan, query, constraints, check)` run inside `_pack_plan`
  (`tpc_agent.py`), gated behind `TPC_REPAIR_INTERCITY` — default **off**, so the deterministic floor
  and the existing unit tests stay byte-identical (assert this with a flag-off test). Add a
  `_repair_intercity_enabled()` predicate next to `_repair_transport_gaps_enabled()`.
- **Verify** `itinerary[0].activities[0]` (outbound) and `itinerary[-1].activities[-1]` (return) are
  intercity activities whose `(type, ID, start/end, start_time/end_time, price)` match a real row from
  the corresponding `env.intercitytransport.select(...)`. Compare against the *same* selection the
  evaluator uses (start/target city + type), not a time-filtered subset.
- **Repair** a missing/mismatched endpoint by re-selecting a feasible grounded row — outbound must end
  before day-1's first in-city activity begins; return must depart after the last-day activities finish
  — and rebuilding the activity with the existing `self._make_intercity_activity(row, people, transports)`
  helper (`tpc_agent.py:4414`). Endpoint-replacement machinery already exists at lines ~2264
  (`tacts[-1] = self._make_intercity_activity(later, ...)`) and ~2309 (`tacts[0] = ...`) — reuse it
  rather than writing new field-mapping, so `price`/`cost`/`BeginTime` mapping stays identical to the
  build path and can't drift from the evaluator.
- **Bounded, acceptance-gated, deepcopy-trialed:** apply in one deepcopy trial; commit only if the full
  checker then accepts and the preference key does not regress (same rule as `_repair_transport_gaps` /
  `_pin_timed_windows`). If no feasible grounded return exists at all (the itinerary genuinely can't fit
  one), leave the plan unchanged — do **not** fabricate a row the environment can't ground (invariant).

### Out of scope

- Do not re-time the whole day to *make room* for a return (that is a cascade/resequence concern). If
  the only blocker is a too-tight last day, decline — note it as a follow-on, like transport-repair's
  cascading-shift limit.
- Do not touch the CP-SAT path's intercity construction (`cp_solver.py`) — it already grounds via
  `_make_intercity_activity`; this pass is a repair for the greedy/recovery outputs.

## Tests (`tests/phase2/test_repair_intercity_endpoints.py`)

Bare-`TPCAgent` pattern from `test_repair_transport_gaps.py` / `test_cascade_timed_windows.py`, with a
stubbed `env.intercitytransport.select` returning a small fixed table:

1. Flag off → byte-identical floor (pass not invoked), even on a plan with a broken endpoint.
2. Flag on, missing return endpoint → repaired to a grounded row, commits, checker accepts.
3. Flag on, endpoint present but mismatched (wrong `price`/`ID`) → re-grounded to the matching row.
4. Flag on, no feasible return row exists → declines, plan unchanged (no fabrication).
5. Flag on, outbound endpoint broken → repaired symmetrically.

## Gate criteria (after implementation)

Gate `TPC_REPAIR_INTERCITY=1` at `900 s` on `familiar_100_val` against the pin+converge default
baseline (shareable with the other gates — see
[`tier1_transport_repair_gate.md`](tier1_transport_repair_gate.md)). Screen first with
`make phase2-quick-eval P2_FLAG=TPC_REPAIR_INTERCITY P2_QE_MODE=solver-only ... P2_BUDGET=60`. Promote
only if the **commonsense/EPR** component improves (the four intercity families drop) with **no new
parse failures or timeouts** and no FPR/`continuous_score` regression. Promotion is then the one-line
default-on in `apply_deterministic_solver_defaults()` plus a test and roadmap note.

## Invariants (unchanged)

Ground before acceptance (every field re-derived from `env`, never fabricated); flags-off is the floor;
deepcopy-trial + commit-on-accept only; no oracle in the agent path.
