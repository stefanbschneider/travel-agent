# Agent Design Overview

This file is the shared overview of the current TPCAgent stack.

Phase-specific details now live in:

- `docs/tpc_phase1_playbook.md` — public leaderboard strategy and operating workflows
- `docs/tpc_phase2_design.md` — final harness design, no-oracle parsing, and orchestration plan

## Competition Split

- **Phase 1:** offline prediction generation on the released query set, with oracle constraints available locally when `--oracle_translation` is enabled
- **Phase 2:** organizer-run per-query harness on held-out queries, with only visible natural-language input exposed to the agent

The deterministic core below is shared across both phases, but the top-level control logic differs.

## Current Agent (TPCAgent)

`chinatravel/agent/tpc_agent/tpc_agent.py` — `TPCAgent`  
`chinatravel/agent/tpc_agent/solver_constraints.py` — branch-local constraint variants  
`chinatravel/agent/tpc_agent/cp_candidates.py` — candidate pool extraction  
`chinatravel/agent/tpc_agent/cp_solver.py` — CP-SAT tier + reconstruction  
`chinatravel/agent/tpc_agent/parsed_verifier.py` — no-oracle verifier

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│  1. CONSTRAINT EXTRACTION + VARIANTS                    │
│  parse_constraints + branch-local hard-logic extraction │
│  (one normalized constraint dict per OR branch)         │
└───────────────────────┬──────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────┐
│  2. ACCEPTANCE CHECKER                                  │
│  base: oracle hard_logic_py (or parsed verifier)        │
│  gate: schema + commonsense once base is fully passed   │
└───────────────────────┬──────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────┐
│  3. MULTI-TIER PLAN SEARCH                              │
│  base build -> guided repair priors -> random restarts  │
│  optional CP-SAT rescue for hard leftovers              │
└───────────────────────┬──────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────┐
│  4. CONSTRAINT-SAFE PREFERENCE PACKING                  │
│  pack + densify only when acceptance remains true       │
│  monotonic best-of updates via eval_tpc --update_best   │
└──────────────────────────────────────────────────────────┘
```

### Key Principles

- **Constraint-first optimization.** Optimize the exact acceptance criterion (logic + schema + commonsense), not a proxy.
- **Deterministic data grounding.** POIs, prices, schedules, and transport details are read from `WorldEnv`; no fabricated values.
- **Branch-local correctness.** OR-style constraints are solved per branch to avoid cross-branch contamination.
- **Any preference lift is gated by validity.** Packing/densification is accepted only when full checks still pass.

## What Is Shared Across Phases

The following design choices remain correct in both phases:

- deterministic-first planning
- branch-local constraint reasoning
- environment-grounded costs, times, and transport
- CP-SAT as a targeted rescue or refinement tier
- acceptance-gated preference improvement

## What Changes Between Phases

### Phase 1

The system can optimize directly against released oracle hard logic and be rerun for as long as needed.

### Phase 2

The system must infer constraints from the visible natural-language query, run inside a bounded
harness budget, and return a final result safely before timeout.

That means Phase 2 is not primarily a new planning problem. It is a stronger **no-oracle parsing
and orchestration** problem wrapped around the same deterministic planner.

## Current Main Risk For Phase 2

The core planner is already aligned with a Phase 2 direction, but parser parity is not. In the
current no-oracle path, ambiguity and disjunctive branches are flattened too early, which is the
highest-priority gap to close before final harness packaging.

See `docs/tpc_phase2_design.md` for the recommended fix direction.
