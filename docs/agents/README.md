# Parallel agent prompts

Phase 2 development runs as concurrent workstreams (see [Parallel workstreams](../../CLAUDE.md#parallel-workstreams) in `CLAUDE.md`). Each workstream owns a branch and opens its own PR; none blocks the others.

The generic role-level prompts were retired. The active docs in this folder are focused task briefs only.

## Active focused prompts

| Workstream | Task | Prompt | Status |
| --- | --- | --- | --- |
| Implementation | **Final-evening commonsense-first lever (`TPC_COMMONSENSE_FIRST`)** | [`final_night_commonsense_first.md`](final_night_commonsense_first.md) | **Active and highest priority.** Last change window before submission; supersedes the three briefs below. |
| Implementation | **Post-final-night next steps: LLM endpoint reachability, single-day-stay intercity fix, preference packing** | [`next_steps_after_final_night.md`](next_steps_after_final_night.md) | **Next up.** Three independent tasks with flags, tests, and ship bars; written to be run by a fresh agent. |
| Evaluation | Second-machine pinned `900 s` rows for the final night | [`final_night_eval_commands.md`](final_night_eval_commands.md) | Copy-paste commands only; run after the commonsense-first promotion lands. |
| Evaluation | Tier 1: commonsense-transport repair gate (`TPC_REPAIR_TRANSPORT_GAPS`) | [`tier1_transport_repair_gate.md`](tier1_transport_repair_gate.md) | Superseded by the commonsense-first brief: the flag's commit rule was the blocker, not its budget. |
| Implementation | Intercity-transport endpoint grounding (`TPC_REPAIR_INTERCITY`) | brief removed in `7f96c614`; the flag is implemented and now enabled via `TPC_COMMONSENSE_FIRST` | Landed. Remaining residual (single-day trips ending in an overnight accommodation) is recorded in the [roadmap](../tpc_phase2_roadmap.md#known-residual-the-intercity-endpoint-cluster-has-a-different-cause). |
| Implementation | Stage 3 bounded LLM refine (`TPC_P2_LLM_REFINE`) | [`stage3_llm_refine.md`](stage3_llm_refine.md) | Active, lower priority than intercity deterministic grounding. |

## How to use these

Pick the focused brief that matches the current roadmap item in [Phase 2 roadmap](../tpc_phase2_roadmap.md), then run it as a self-contained task. Each brief contains branch naming, exact commands, invariants, and finish criteria.

The division of labor remains strict:

- **Evaluation writes only generated rows** under `results/phase2_baselines/`.
- **Implementation writes only code and tests** under `chinatravel/`, `agent_env/`, `tests/`, `scripts/`.
- **Docs/planning updates docs and priority order** in the roadmap/eval docs.

All workstreams obey the [non-negotiable invariants](../../CLAUDE.md#non-negotiable-invariants) and the [change and branch protocol](../../CLAUDE.md#change-and-branch-protocol).
