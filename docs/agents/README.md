# Parallel agent prompts

Phase 2 development runs as concurrent workstreams (see [Parallel workstreams](../../CLAUDE.md#parallel-workstreams) in `CLAUDE.md`). Each workstream owns a branch and opens its own PR; none blocks the others.

The generic role-level prompts were retired. The active docs in this folder are focused task briefs only.

## Active focused prompts

| Workstream | Task | Prompt | Status |
| --- | --- | --- | --- |
| Evaluation | Tier 1: commonsense-transport repair gate (`TPC_REPAIR_TRANSPORT_GAPS`) | [`tier1_transport_repair_gate.md`](tier1_transport_repair_gate.md) | Keep active. Runnable now, no new code required; shares baseline with other `900 s` val gates. |
| Implementation | Intercity-transport endpoint grounding (`TPC_REPAIR_INTERCITY`) | [`intercity_transport_grounding.md`](intercity_transport_grounding.md) | Active and prioritized deterministic implementation item. |
| Implementation | Stage 3 bounded LLM refine (`TPC_P2_LLM_REFINE`) | [`stage3_llm_refine.md`](stage3_llm_refine.md) | Active, lower priority than intercity deterministic grounding. |

## How to use these

Pick the focused brief that matches the current roadmap item in [Phase 2 roadmap](../tpc_phase2_roadmap.md), then run it as a self-contained task. Each brief contains branch naming, exact commands, invariants, and finish criteria.

The division of labor remains strict:

- **Evaluation writes only generated rows** under `results/phase2_baselines/`.
- **Implementation writes only code and tests** under `chinatravel/`, `agent_env/`, `tests/`, `scripts/`.
- **Docs/planning updates docs and priority order** in the roadmap/eval docs.

All workstreams obey the [non-negotiable invariants](../../CLAUDE.md#non-negotiable-invariants) and the [change and branch protocol](../../CLAUDE.md#change-and-branch-protocol).
