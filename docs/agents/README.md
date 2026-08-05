# Parallel agent prompts

Phase 2 development runs as concurrent workstreams (see [Parallel workstreams](../../CLAUDE.md#parallel-workstreams) in `CLAUDE.md`). Each workstream owns a branch and opens its own PR; none blocks the others.

The generic role-level prompts were retired. The active docs in this folder are focused task briefs only.

## Where the work queue actually lives

Two documents carry the current queue; the briefs here are supporting detail, not the queue itself.

| Workstream | Read this | What it is |
| --- | --- | --- |
| **Evaluation** | [Evaluation roadmap](../tpc_phase2_eval.md#run-this-next) | The live run queue under the 5-hour whole-run envelope (R7 onwards), plus what a measurement is allowed to prove. **Start here for any evaluation-machine time.** |
| **Implementation** | [Implementation roadmap](../tpc_phase2_roadmap.md#work-items) | The search-space diagnosis and the ranked P-items, each a self-contained brief. |

## Active focused prompts

| Workstream | Task | Prompt | Status |
| --- | --- | --- | --- |
| Implementation | Stage 3 bounded LLM refine (`TPC_P2_LLM_REFINE`) | [`stage3_llm_refine.md`](stage3_llm_refine.md) | Open, lowest priority: the shipped path makes zero LLM calls and no endpoint is reachable from the evaluation host. |

## Archived (2026-08-04)

The "final night" briefs were written for a deadline that has passed and for a per-query budget
contract the competition does not use. Their mechanisms either landed and are default-on, or were
superseded. They now live in [`../archive/agents/`](../archive/README.md) as record, not guidance:

| Brief | Why it moved |
| --- | --- |
| `final_night_commonsense_first.md` | `TPC_COMMONSENSE_FIRST` landed and is harness-default-on. |
| `final_night_eval_commands.md` | Copy-paste commands for pinned `900 s` per-query rows; replaced by the [evaluation roadmap](../tpc_phase2_eval.md). |
| `next_steps_after_final_night.md` | All three tasks resolved (1 and 3 landed; 2 landed as W5 of the plan). |
| `tier1_transport_repair_gate.md` | Superseded by the commonsense-first brief: the flag's commit rule was the blocker, not its budget. |

## How to use these

Pick the item that matches the current queue above, then run it as a self-contained task. Each brief contains branch naming, exact commands, invariants, and finish criteria.

The division of labor remains strict:

- **Evaluation writes only generated rows** under `results/phase2_baselines/`.
- **Implementation writes only code and tests** under `chinatravel/`, `agent_env/`, `tests/`, `scripts/`.
- **Docs/planning updates docs and priority order** in the roadmap/eval docs.

All workstreams obey the [non-negotiable invariants](../../CLAUDE.md#non-negotiable-invariants) and the [change and branch protocol](../../CLAUDE.md#change-and-branch-protocol).
