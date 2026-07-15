# TPCAgent

`TPCAgent` is the deterministic itinerary planner shared by Phase 1 and the Phase 2 no-oracle path.
It builds complete day-by-day plans from grounded environment data and retains candidates only through an acceptance gate.

## Search and repair flow

For each query, `_solve` in [`tpc_agent.py`](tpc_agent.py) performs:

1. Build solver-facing constraints and one branch-local variant per alternative.
2. Create the variant's acceptance checker: released oracle logic in Phase 1, or [`parsed_verifier.py`](parsed_verifier.py) in no-oracle mode, followed by schema and commonsense validation.
3. Generate a deterministic base itinerary with `_build_plan`.
4. Run the optional CP-SAT tier from [`cp_solver.py`](cp_solver.py) over grounded candidate pools from [`cp_candidates.py`](cp_candidates.py).
5. Try deterministic repair priors, then seeded random parameter restarts until the query budget or restart bound is reached.
6. Rank accepted plans by accepted preference value and cost; retain the best valid candidate.
7. Pack or densify only while the same acceptance checker continues to pass.

The planner records the best current candidate as timeout recovery state.
If no accepted candidate appears, it returns the safest grounded candidate it produced; callers must still apply their own final output handling.

## Core invariants

- POIs, opening windows, prices, hotels, restaurants, and transport records come from `WorldEnv`.
- Constraint alternatives remain isolated by branch.
- A proxy score cannot override logic, schema, or commonsense rejection.
- Packing and densification never trade a valid plan for a higher preference score.
- Fixed query ID plus `TPC_SEED_SALT` produces repeatable restart choices.
- CP-SAT stays bounded by the remaining per-query solve budget and defaults to one search worker to avoid nested oversubscription.

## Primary knobs

| Variable | Default | Purpose |
| --- | --- | --- |
| `TPC_USE_ORACLE` | `1` | Use released `hard_logic_py`; set `0` only for the no-oracle path. |
| `TPC_MAX_RESTARTS` | `400` | Maximum seeded random rebuilds per query. |
| `TPC_SOLVE_BUDGET_SEC` | `120` | Planner wall-clock budget per query. |
| `TPC_SEED_SALT` | `0` | Deterministic exploration salt for separate rounds. |
| `TPC_USE_CP_SOLVER` | `1` | Enable the CP-SAT rescue/refinement tier. |
| `TPC_CP_AFTER_PASS` | `1` | Also try CP-SAT after a base candidate passes. |
| `TPC_CP_TIME_LIMIT_SEC` | bounded remaining budget | Cap one CP-SAT invocation. |
| `TPC_CP_SEARCH_WORKERS` | `1` | CP-SAT workers; keep at one when outer query parallelism is used. |
| `TPC_SOLVE_STOP_AT_ACCEPT` | `0` | Evaluation-only early stop; does not measure preference-calibrated behavior. |

Candidate-pool caps and packing dwell/window settings are advanced tuning parameters.
Change one bounded knob at a time, retain the full acceptance gate, and compare results through the Phase 1 merge or Phase 2 ledger workflow.

## Callers and related modules

- [`solver_constraints.py`](solver_constraints.py): branch-local constraint extraction.
- [`parsed_verifier.py`](parsed_verifier.py): local no-oracle acceptance interpretation.
- [`cp_candidates.py`](cp_candidates.py) and [`cp_solver.py`](cp_solver.py): grounded candidate pool and CP-SAT reconstruction.
- [`AGENT_DESIGN.md`](../../../AGENT_DESIGN.md): cross-phase ownership and data flow.
- [Phase 1 playbook](../../../docs/tpc_phase1_playbook.md): solve, merge, score, and submission operations.
- [Phase 2 design](../../../docs/tpc_phase2_design.md): bounded orchestration around this core.

Historical Phase 1 measurements and score discussions are preserved in the [Phase 1 archive](../../../docs/archive/phase1/tpc_phase1_playbook_2026-07-15.md).
Use current generated score output rather than copying score tables into this implementation guide.
