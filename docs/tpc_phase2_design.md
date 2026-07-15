# TPC 2026 Phase 2 Design

This document defines the stable no-oracle architecture for the final harness.
It does not record experiment status or priorities; use the [roadmap](tpc_phase2_roadmap.md) for those.

## Execution contract

Phase 2 is an organizer-run, per-query harness on a separate held-out set.
The agent receives the visible natural-language request and permitted environment tools, not `hard_logic`, `hard_logic_py`, or `hard_logic_nl`.
Organizers run Qwen3.6-27B through SGLang on 2 × A800 80 GB GPUs without NVLink.

The public material does **not** specify an organizer-enforced per-query timeout or repeat count.
`300 s` and `900 s` are local sensitivity settings only.
The competition website remains authoritative; see [competition reference](reference/competition.md).

## Trust boundary

The harness owns all parsing and planning from visible input.
Oracle fields may exist in local released data for evaluation, but must be removed before the agent path begins.
An LLM may propose a parse or refinement; it cannot authorize an entity, constraint, transport, price, or final acceptance decision.
Those facts are grounded against `WorldEnv` and deterministic code.

## Data flow

```text
visible query
  -> parse_to_ir()
  -> normalize and environment-backed resolution
  -> branch-local solver variants
  -> TPCAgent in TPC_USE_ORACLE=0 mode
  -> bounded deterministic search and optional CP-SAT
  -> acceptance-gated packing or optional refinement
  -> finalization, telemetry, and result JSON
```

1. **Parse and normalize.** [`normalize.py`](../chinatravel/agent/phase2/normalize.py) converts visible text into a parser IR and solver variants. Alternatives remain separate. Resolution validates names and values before they reach the planner.
2. **Solve.** [`orchestrator.py`](../chinatravel/agent/phase2/orchestrator.py) injects the variants into `TPCAgent` through `make_tpcagent_solve_fn`; the solver is explicitly set to `TPC_USE_ORACLE=0`.
3. **Improve.** Deterministic packing remains inside `TPCAgent`. Any optional refinement is bounded and must preserve the last plan-shaped candidate when it fails or times out.
4. **Finalize.** The stage budget reserves time for output. On a solver timeout or error, the orchestrator recovers the solver's best plan when available; otherwise [`fallback.py`](../chinatravel/agent/phase2/fallback.py) supplies the schema-shaped last resort. Telemetry records recovery, fallback, stage time, and errors.

## Component interfaces

| Owner | Interface and contract |
| --- | --- |
| `normalize.py` | `parse_to_ir()` and `ir_to_solver_variants()` produce validated, branch-local planner input. |
| `schema.py` | Keeps parser IR separate from the stable solver-facing constraint shape. |
| `budget.py` | Splits a caller-provided local budget and reserves finalization time. |
| `orchestrator.py` | `solve_phase2()` returns `(plan, telemetry)` without propagating solver failures. |
| `tpc_agent/` | Performs deterministic candidate generation, CP-SAT rescue, and local acceptance gating. |
| `agent_env/scripts/solve_phase2.py` | Loads a query, hides oracle-only fields, invokes the orchestrator, and writes harness outputs. |
| `llm_client.py` | Supplies optional model access behind a replaceable client; callers must record backend and flags. |

## Deterministic invariant and extension points

Library-default `Flags()` has every optional Phase 2 feature off: LLM parsing, LLM refinement, disjunction expansion, dynamic budgeting, and entity resolution.
With those flags off, the path uses no LLM calls and remains deterministic for the same query, environment data, and seed configuration.
A runner may deliberately enable an extension, but the run must record that configuration and retain a deterministic fallback.

The supported extension points are parser assistance, disjunction handling, environment-backed entity resolution, budget allocation, and bounded refinement.
They may improve a proposal, never bypass grounding, branch isolation, time bounds, or acceptance gates.

## Related documents

- [Evaluation methodology](tpc_phase2_eval.md): axes, metrics, ledger, and regression gates.
- [Phase 2 roadmap](tpc_phase2_roadmap.md): current evidence and decisions.
- [Dataset boundaries](tpc_phase2_hf_dataset.md): local, HF, familiar-100, and final data.
- [Agent environment guide](../agent_env/README.md): human setup and harness interface.
