# Parallel agent prompts

Phase 2 development runs as concurrent workstreams (see [Parallel workstreams](../../CLAUDE.md#parallel-workstreams) in `CLAUDE.md`). Each workstream owns a branch and opens its own PR; none blocks the others.

The generic role-level prompts were retired. The active docs in this folder are focused task briefs only.

## Where the work queue actually lives

Two documents carry the current queue; the briefs here are supporting detail, not the queue itself.

| Workstream | Read this | What it is |
| --- | --- | --- |
| **Evaluation** | [Evaluation roadmap](../tpc_phase2_eval.md#run-this-next) | The live run queue under the 5-hour whole-run envelope (R7 onwards), plus what a measurement is allowed to prove. **Start here for any evaluation-machine time.** |
| **Implementation** | [Implementation roadmap](../tpc_phase2_roadmap.md#work-items) | The search-space diagnosis and the ranked P-items, each a self-contained brief. |

**Current assignment (2026-08-06), so neither agent has to infer it:**

P14 and R16 — the two items this table used to point agents at — are both **done**: P14 landed
(`0c80ab6b`/`241c0524`, `TPC_WINDOW_PUSH`/`TPC_WINDOW_INSERT` promoted to defaults), and
[R16](../tpc_phase2_eval.md#r16--measure-the-v2-candidate-the-last-run-before-a-rebuild-closed-2026-08-06-green)
then measured that exact shipping configuration at `n=100` and closed **GREEN** (`overall
64.14997555172528`, `+0.0183` over R14, `+0.5654` over R8/R12; `FPR 44.0` unchanged from R14). Per
R16's pre-registered rule, `main` is the `v2` candidate to ship; packaging/upload is a separate,
deliberate follow-up not covered by either row.

| Workstream | Do exactly this | Finish criterion |
| --- | --- | --- |
| **Implementation** | [P11](../tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen), [P13](../tpc_phase2_roadmap.md#p13--an-empty-parent-parse-must-mean-the-same-thing-on-both-sides) — improve the *next* cycle, not `v2`'s contents ([P12](../tpc_phase2_roadmap.md#p12--close-p10s-false-positive-half-omitted-parser-semantics) landed 2026-08-06, out of order) | listed unit tests green plus a paired screen under `results/phase2_baselines/screens/` |
| **Evaluation** | R9/R11 remain blocked on unimplemented work items ([P5](../tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds)/[P2](../tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger), [P6](../tpc_phase2_roadmap.md#p6--llm-backed-repair-proposer-v2-candidate-default-off)) | code that does not exist yet and cannot be run before the deadline |

R14/R15/R16 are closed (2026-08-06).

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
