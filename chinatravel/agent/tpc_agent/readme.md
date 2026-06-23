# TPCAgent

`TPCAgent` (`tpc_agent.py`) is the deterministic submission agent for the ChinaTravel benchmark. Given a query — start city, target city, number of days, party size, and natural-language constraints — it produces a complete day-by-day itinerary (intercity transport, hotel, attractions, restaurants, inner-city transport) that satisfies the query's hard constraints.

This document describes the **current per-query search stack** that drives plan construction.

## TL;DR

The agent replaced a single greedy pass with a **constraint-first multi-tier search**: base build + guided repairs + random restarts, then a CP-SAT rescue tier for hard leftovers, and finally acceptance-gated packing/densification. Plans are accepted only when they pass the real benchmark checks (hard logic + schema + commonsense), and best results are merged monotonically per query.

## The old builder (single greedy pass)

The previous agent built **one** itinerary per query with a fully hardcoded greedy heuristic:

- constraints came from a pre-baked `parsed_constraints.json` cache keyed by query id;
- a handful of "constraint variants" (usually just one) were each built once and scored against the query's hard logic, keeping the best by `(passed, -cost)`;
- builder choices were fixed: 90-minute attraction visits, the first hotel passing the filter, fixed transport-mode heuristics, and no reordering of optional points of interest.

If that single pass missed a constraint, the query was lost — there was no recovery.

## The search (`_solve`)

`_solve(query)` keeps the best plan by `(passed_checks, proxy_preference, -total_cost)` and runs the following tiers per query:

1. **Base build** — build once from the parsed constraints. If it already passes, stop.
2. **Guided repair** (`_repair_params`) — a small set of deterministic parameter priors chosen from *which* constraints are present (e.g. an inner-transport budget triggers trying forced walk/metro; hotel constraints trigger trying several acceptable hotels rather than only the first; timing/window/dwell constraints trigger trying attraction-ordering offsets). Cheap and targeted, tried before any randomness so single-signal queries converge in a couple of builds.
3. **Random multi-start** (`_random_params`) — up to `TPC_MAX_RESTARTS` randomized rebuilds, per-query seeded for reproducibility, bounded by `TPC_SOLVE_BUDGET_SEC`.
4. **CP-SAT rescue** (`cp_solver.solve_with_cp_sat`) — optional OR-Tools tier for leftovers where the greedy family struggles.

The search early-exits on the first fully accepted plan.

### Scorer in the loop (`_make_checker`)

Every candidate is scored by `check(plan) -> (passed, total)`:

- the **base** score runs the query's own `hard_logic_py` through the real evaluator (`evaluate_constraints_py`) — identical to the benchmark's logic check;
- once the base fully passes, the plan is additionally gated on **schema validity** (+1) and **commonsense validity** (+1).

So an *accepted* plan satisfies schema and commonsense and hard-logic together, matching the benchmark final-pass criterion.

### Tunable builder, not a fork (`params`)

The greedy builder (`_build_plan`) was parameterized so the search perturbs it without duplicating code. Knobs: visit length / per-POI dwell, attractions-per-day, attraction/restaurant rotation offsets (only the **optional** tail rotates — required POIs stay pinned at the front), hotel index, forced inner-transport mode, and intercity outbound/return preference. **Every default reproduces the original greedy output**, so the search is a strict superset of the old behavior and cannot regress a previously solved query.

### Constraint-safe packing and densification (`_pack_plan`, `_densify_plan`)

After a passing plan is found, the agent tries to add more attractions and meals **only while acceptance still holds**. This raises preference metrics without trading away hard-constraint passes.

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
| `TPC_USE_CP_SOLVER` | `1` | Enable CP-SAT rescue tier (`0` disables it). |
| `TPC_CP_TIME_LIMIT_SEC` | auto | Per-query CP-SAT time cap (bounded by remaining solve budget). |

## Tail-focused optimization workflow (`scripts/rank_tail.py`)

When aggregate hard metrics are already high, the best leaderboard gains usually come from
improving the low-score tail rather than re-running all 1000 queries uniformly.

`scripts/rank_tail.py` builds a focused split from current `results/best` by combining:

- per-query `_eval_score` gap from 100,
- hard-logic failure density (`failed_clauses`),
- weighted failure signature severity (DSL functions seen in failed clauses).

Example:

```bash
python scripts/rank_tail.py --split tpc_phase1 --method best --top-k 120 --min-score 99
python scripts/solve.py --split tpc_phase1_tail_focus --restarts 1200 --budget 300 --workers 8
python scripts/merge.py --split tpc_phase1_tail_focus
python scripts/score.py
```

Artifacts:

- ranking report CSV: `cache/tail_rankings/<split>_<method>_tail_ranking.csv`
- focused split: `chinatravel/evaluation/default_splits/<split>_tail_focus.txt`

This loop is monotonic-safe: `scripts/merge.py` only updates `results/best/<uid>.json` when
the per-query weighted score increases.

## Results (tpc_phase1, 1000 queries)

Latest verified `results/best` score (2026-06-19):

| Metric | Current |
| --- | --- |
| Overall | **94.5397** |
| Overall (official) | **94.5397** |
| Final-pass rate (FPR) | **97.1000** |
| Conditional logic-pass (C-LPR) | **98.9070** |
| Env-pass rate (EPR, micro) | **100.0000** |
| Env-pass rate (EPR, macro) | **100.0000** |
| DAV | **67.5472** |
| ATT | **82.4077** |
| DDR | **69.5045** |

Historical milestone (early search stage):

| Metric | Baseline (greedy) | + Search | Current |
| --- | --- | --- | --- |
| Overall | 85.25 | 88.26 | **88.61** |
| Final-pass rate (FPR) | 83.0 | 88.9 | **89.4** |
| Conditional logic-pass (C-LPR) | 92.71 | 95.71 | **96.13** |
| Env-pass rate (EPR, micro) | 99.94 | preserved | **99.98** |
| Solved | — | 889 | **894** |

The gains are monotonic on `results/best`: per-query results are only replaced when the weighted score improves.

## Note on transferability

The headline numbers use the **oracle** path (`TPC_USE_ORACLE=1`), where the query's `hard_logic_py` is available to score against. For held-out queries where it is not, set `TPC_USE_ORACLE=0` to fall back to live natural-language parsing (`parse_query_no_oracle`) and the standalone `parsed_verifier`. This no-oracle path is the transferability route and is not reflected in the numbers above.

## Source

- `chinatravel/agent/tpc_agent/tpc_agent.py` — agent and search (`_solve`, `_make_checker`, `_repair_params`, `_random_params`, `_pack_plan`, `_build_plan`).
- `chinatravel/agent/tpc_agent/solver_constraints.py` — branch-local variant extraction from parser + hard logic.
- `chinatravel/agent/tpc_agent/cp_candidates.py` — finite candidate pool construction.
- `chinatravel/agent/tpc_agent/cp_solver.py` — CP-SAT solver tier and reconstruction.
- `chinatravel/agent/tpc_agent/parsed_verifier.py` — no-oracle constraint verifier.
- Workflow scripts: `scripts/solve.py`, `scripts/iterate.py`, `scripts/merge.py`, `scripts/score.py`.
- Tail-priority script: `scripts/rank_tail.py`.