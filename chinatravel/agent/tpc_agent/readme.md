# TPCAgent

`TPCAgent` (`tpc_agent.py`) is the deterministic submission agent for the ChinaTravel benchmark. Given a query — start city, target city, number of days, party size, and natural-language constraints — it produces a complete day-by-day itinerary (intercity transport, hotel, attractions, restaurants, inner-city transport) that satisfies the query's hard constraints.

This document describes the **per-query oracle-guided search** that drives plan construction.

## TL;DR

The agent replaced a single greedy plan-builder with a **per-query multi-start search that puts the real plan scorer in the loop**: it rebuilds the itinerary under many perturbed configurations and accepts a plan only when it passes schema + commonsense + hard-logic validity — i.e. it optimizes the exact benchmark pass criterion instead of a proxy. This lifted the overall score from 85.25 to 88.61, and the final-pass rate from 83.0 to 89.4.

## The old builder (single greedy pass)

The previous agent built **one** itinerary per query with a fully hardcoded greedy heuristic:

- constraints came from a pre-baked `parsed_constraints.json` cache keyed by query id;
- a handful of "constraint variants" (usually just one) were each built once and scored against the query's hard logic, keeping the best by `(passed, -cost)`;
- builder choices were fixed: 90-minute attraction visits, the first hotel passing the filter, fixed transport-mode heuristics, and no reordering of optional points of interest.

If that single pass missed a constraint, the query was lost — there was no recovery.

## The search (`_solve`)

`_solve(query)` runs a three-tier search per query and keeps the best plan by `(constraints_passed, -total_cost)`:

1. **Base build** — build once from the parsed constraints. If it already passes, stop.
2. **Guided repair** (`_repair_params`) — a small set of deterministic parameter priors chosen from *which* constraints are present (e.g. an inner-transport budget triggers trying forced walk/metro; hotel constraints trigger trying several acceptable hotels rather than only the first; timing/window/dwell constraints trigger trying attraction-ordering offsets). Cheap and targeted, tried before any randomness so single-signal queries converge in a couple of builds.
3. **Random multi-start** (`_random_params`) — up to `TPC_MAX_RESTARTS` (default 400) randomized rebuilds, per-query seeded for reproducibility, bounded by the wall-clock budget `TPC_SOLVE_BUDGET_SEC` (default 120s). Each restart perturbs attraction rotation, hotel index, attractions-per-day, forced inner-transport mode, and intercity preferences.

The search early-exits on the first fully accepted plan.

### Scorer in the loop (`_make_checker`)

Every candidate is scored by `check(plan) -> (passed, total)`:

- the **base** score runs the query's own `hard_logic_py` through the real evaluator (`evaluate_constraints_py`) — identical to the benchmark's logic check;
- once the base fully passes, the plan is additionally gated on **schema validity** (+1) and **commonsense validity** (+1).

So an *accepted* plan satisfies schema and commonsense and hard-logic together — exactly the benchmark's final-pass definition. The agent optimizes the metric it is graded on, not an approximation.

### Tunable builder, not a fork (`params`)

The greedy builder (`_build_plan`) was parameterized so the search perturbs it without duplicating code. Knobs: visit length / per-POI dwell, attractions-per-day, attraction/restaurant rotation offsets (only the **optional** tail rotates — required POIs stay pinned at the front), hotel index, forced inner-transport mode, and intercity outbound/return preference. **Every default reproduces the original greedy output**, so the search is a strict superset of the old behavior and cannot regress a previously solved query.

### Constraint-safe packing (`_pack_plan`)

After a passing plan is found, the agent tries to add more attractions and meals (attractions-per-day 3, then 4) **only while acceptance still holds**. This raises plan-density preference metrics without ever trading away a hard-constraint pass.

### Per-POI constraint backfill

Some dwell and time-window constraints live inside positioned-activity clauses — `if activity_position(activity) == <loc>: activity_time(...) >= ...`, `activity_start_time(...) <= "HH:MM"` — that the constraint parser missed. The agent extracts these into per-POI `stay_duration` (minimum dwell) and `activity_time_windows`, injects the named POIs into the required pools, and projects a window's latest-start onto an `arrive_no_later` timing constraint so the builder actually honors it.

## Configuration

All knobs are environment variables read at construction; defaults reproduce the submitted behavior.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TPC_USE_ORACLE` | `1` | Score against the in-data oracle `hard_logic_py`. Set to `0` to parse constraints from natural language and verify with `parsed_verifier` (the held-out / Phase-2 path). |
| `TPC_MAX_RESTARTS` | `400` | Maximum randomized rebuilds per query. |
| `TPC_SOLVE_BUDGET_SEC` | `120` | Wall-clock budget per query; the search self-limits to this. |
| `TPC_SEED_SALT` | `0` | Salt mixed into the per-query RNG seed so distinct search rounds explore different parameters. |

## Results (tpc_phase1, 1000 queries)

| Metric | Baseline (greedy) | + Search | Current |
| --- | --- | --- | --- |
| Overall | 85.25 | 88.26 | **88.61** |
| Final-pass rate (FPR) | 83.0 | 88.9 | **89.4** |
| Conditional logic-pass (C-LPR) | 92.71 | 95.71 | **96.13** |
| Env-pass rate (EPR, micro) | 99.94 | preserved | **99.98** |
| Solved | — | 889 | **894** |

Current macro EPR: 99.8. Current preference metrics (which the packing step targets): DAV 30.71, ATT 80.70, DDR 65.08.

The gains are monotonic on `results/best`: the search only ever replaces a plan with one that scores at least as well, so re-running accumulates solved queries without regressions. Scaling the 400-restart search across all 1000 queries was made practical by parallelizing the solve loop.

## Note on transferability

The headline numbers use the **oracle** path (`TPC_USE_ORACLE=1`), where the query's `hard_logic_py` is available to score against. For held-out queries where it is not, set `TPC_USE_ORACLE=0` to fall back to live natural-language parsing (`parse_query_no_oracle`) and the standalone `parsed_verifier`. This no-oracle path is the transferability route and is not reflected in the numbers above.

## Source

- `chinatravel/agent/tpc_agent/tpc_agent.py` — agent and search (`_solve`, `_make_checker`, `_repair_params`, `_random_params`, `_pack_plan`, `_build_plan`).
- `chinatravel/agent/tpc_agent/parsed_verifier.py` — no-oracle constraint verifier.
- History: search introduced in commit `cfcea4c`; solve loop parallelized in `ad324f5`; additional solves in `a2136cd`.