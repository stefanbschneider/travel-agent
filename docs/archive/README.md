# Documentation archive

This directory preserves dated plans, status notes, and evidence-heavy document snapshots.
It is non-authoritative.
Use the active documents linked below for current operating guidance.

| Archived file | Former role | Active replacement |
| --- | --- | --- |
| [phase1/tpc_phase1_playbook_2026-07-15.md](phase1/tpc_phase1_playbook_2026-07-15.md) | Phase 1 operations, measurements, and chronology | [Phase 1 playbook](../tpc_phase1_playbook.md) |
| [phase2/tpc_phase2_implementation_plan.md](phase2/tpc_phase2_implementation_plan.md) | Historical implementation plan | [Phase 2 roadmap](../tpc_phase2_roadmap.md) |
| [phase2/tpc_phase2_sonnet_plan.md](phase2/tpc_phase2_sonnet_plan.md) | Historical Phase 2 plan | [Phase 2 roadmap](../tpc_phase2_roadmap.md) |
| [phase2/tpc_phase2_sonnet_plan2.md](phase2/tpc_phase2_sonnet_plan2.md) | Historical Phase 2 plan | [Phase 2 roadmap](../tpc_phase2_roadmap.md) |
| [phase2/tpc_phase2_normalization_plan.md](phase2/tpc_phase2_normalization_plan.md) | Historical normalization plan | [Phase 2 roadmap](../tpc_phase2_roadmap.md) |
| [phase2/tpc_phase2_plan3.md](phase2/tpc_phase2_plan3.md) | Historical Phase 2 roadmap and evidence | [Phase 2 roadmap](../tpc_phase2_roadmap.md) |
| [phase2/tpc_phase2_design_2026-07-15.md](phase2/tpc_phase2_design_2026-07-15.md) | Status-heavy Phase 2 design snapshot | [Phase 2 design](../tpc_phase2_design.md) |
| [phase2/tpc_phase2_eval_2026-07-15.md](phase2/tpc_phase2_eval_2026-07-15.md) | Status-heavy Phase 2 evaluation snapshot | [Phase 2 evaluation](../tpc_phase2_eval.md) |
| [status/agent_env_progress_2026-07-15.md](status/agent_env_progress_2026-07-15.md) | Agent-environment progress log | [Agent environment guide](../../agent_env/README.md) |
| [status/upstream_divergence_2026-07-15.md](status/upstream_divergence_2026-07-15.md) | Point-in-time upstream comparison | None; historical provenance only |
| [reference/ijcai2026_competition_2026-07-15.md](reference/ijcai2026_competition_2026-07-15.md) | Competition website summary | [Competition reference](../reference/competition.md) |

Archive contents are preserved verbatim from the 2026-07-15 cleanup unless their filename explicitly says otherwise.

## Agent briefs archived 2026-08-04

Moved when the organizers' confirmed execution contract (one 5-hour envelope for the whole run, no
per-query timeout) made a per-query-budget run plan the wrong shape. Preserved verbatim.

| Archived file | Former role | Active replacement |
| --- | --- | --- |
| [agents/final_night_commonsense_first.md](agents/final_night_commonsense_first.md) | Brief for the `TPC_COMMONSENSE_FIRST` lever | Landed and harness-default-on; rationale lives in the [roadmap](../tpc_phase2_roadmap.md) |
| [agents/final_night_eval_commands.md](agents/final_night_eval_commands.md) | Pinned `900 s` per-query evaluation commands | [Evaluation roadmap](../tpc_phase2_eval.md) |
| [agents/next_steps_after_final_night.md](agents/next_steps_after_final_night.md) | Three post-final-night implementation tasks | All resolved; open work is in the [implementation roadmap](../tpc_phase2_roadmap.md) |

## Phase 2 doc consolidation, 2026-08-05

Five active Phase 2 documents were collapsed into three: an [evaluation
roadmap](../tpc_phase2_eval.md) (definitions plus the run queue), an [implementation
roadmap](../tpc_phase2_roadmap.md) (diagnosis, work items, landed record) and a [design
doc](../tpc_phase2_design.md). The versions below are the last state of each superseded document,
preserved verbatim because they carry evidence tables, per-run write-ups and closed-item briefs in
more detail than the merged docs keep.

| Archived file | Former role | Active replacement |
| --- | --- | --- |
| [phase2/tpc_phase2_eval_2026-08-05.md](phase2/tpc_phase2_eval_2026-08-05.md) | Metrics, gates, dataset boundaries, full quick-screen methodology and worked examples | [Evaluation roadmap](../tpc_phase2_eval.md) |
| [phase2/tpc_phase2_eval_roadmap_2026-08-05.md](phase2/tpc_phase2_eval_roadmap_2026-08-05.md) | R1–R6 run queue with the full per-run write-up and row-by-row corrections | [Evaluation roadmap](../tpc_phase2_eval.md#what-the-closed-queue-r1r6-established) |
| [phase2/tpc_phase2_roadmap_2026-08-05.md](phase2/tpc_phase2_roadmap_2026-08-05.md) | Landed-capability record, gate tables, commonsense-first and pinning write-ups, closed "Next steps" list | [Implementation roadmap](../tpc_phase2_roadmap.md) |
| [phase2/tpc_phase2_improvement_plan_2026-08-05.md](phase2/tpc_phase2_improvement_plan_2026-08-05.md) | Search-space diagnosis and the P0–P7 work items | [Implementation roadmap](../tpc_phase2_roadmap.md#work-items) |
| [phase2/tpc_shortcomings_and_plan_2026-08-04.md](phase2/tpc_shortcomings_and_plan_2026-08-04.md) | Cross-phase W1–W11 briefs and session updates; Phase 1 items all closed | [Phase 1 playbook](../tpc_phase1_playbook.md) for Phase 1; [implementation roadmap](../tpc_phase2_roadmap.md) for Phase 2 |
| [agents/tier1_transport_repair_gate.md](agents/tier1_transport_repair_gate.md) | `TPC_REPAIR_TRANSPORT_GAPS` gate brief | Superseded by the commonsense-first work |
