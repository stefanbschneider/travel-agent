# TPCAgent Architecture

This is the stable component and data-flow map for the shared ChinaTravel planner.
Use the phase documents for operations, evaluation, and priorities rather than adding status here.

## Ownership

| Component | Responsibility | Primary source |
| --- | --- | --- |
| Constraint extraction | Convert oracle logic or visible query text into solver-facing constraints and branch-local variants | `chinatravel/agent/tpc_agent/solver_constraints.py`, `parse_constraints.py` |
| Deterministic planner | Build, repair, restart, rank, pack, and densify itinerary candidates | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| CP-SAT tier | Build deterministic candidate pools and solve hard residuals | `chinatravel/agent/tpc_agent/cp_candidates.py`, `chinatravel/agent/tpc_agent/cp_solver.py` |
| Acceptance | Apply oracle logic in Phase 1 or parsed constraints in no-oracle mode, then schema and commonsense checks | `tpc_agent.py`, `parsed_verifier.py` |
| Phase 2 orchestration | Normalize parsed input, allocate bounded work, call the shared planner, and finalize output | `chinatravel/agent/phase2/orchestrator.py` |
| Harness boundary | Hide oracle-only fields, expose environment tools, and publish the official output layout | `agent_env/scripts/solve_phase2.py`, `agent_env/` |
| World facts | Supply POIs, schedules, prices, restaurants, hotels, and transport | `chinatravel/environment/` and `WorldEnv` |

## Shared flow

```text
query input
  -> constraint source
  -> normalized branch-local variants
  -> deterministic base build
  -> guided repair and deterministic restarts
  -> optional CP-SAT rescue or refinement
  -> full acceptance gate
  -> acceptance-gated packing or densification
  -> best accepted itinerary
```

A candidate is never retained merely because it improves a proxy score.
The acceptance gate controls every repair and preference lift.
Environment facts are read from `WorldEnv`; the planner does not invent POI names, prices, schedules, or transport records.
OR-style constraints stay branch-local until a candidate is checked.

## Phase boundary

| | Phase 1 | Phase 2 |
| --- | --- | --- |
| Input | Released query data | Visible natural-language query and allowed tools |
| Constraint source | Released oracle logic may be used locally | Parsed, normalized no-oracle constraints only |
| Runtime model | Offline, resumable, per-query optimization | Per-query organizer harness with a bounded local allocation |
| Acceptance path | Oracle logic, schema, and commonsense | Parsed verifier, schema, and commonsense locally; organizer evaluation remains authoritative |
| Result handling | `scripts/merge.py` monotonically updates `results/best/` | Return one final output through the harness; do not rely on oracle fields |

The common solver remains deterministic when optional features are off.
Phase 2 may add bounded parsing or refinement around it, but must preserve a safe deterministic path and a final accepted fallback.

## Related documents

- [Phase 1 playbook](docs/tpc_phase1_playbook.md): operating and merge workflow.
- [Phase 2 design](docs/tpc_phase2_design.md): no-oracle interfaces and bounded flow.
- [Phase 2 evaluation](docs/tpc_phase2_eval.md): measurement axes and regression gates.
- [Phase 2 roadmap](docs/tpc_phase2_roadmap.md): current decisions and priorities.
- [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md): search tiers and primary knobs.
