# TPC 2026 Phase 2 Roadmap

This is the only active Phase 2 plan.
Historical step plans, chronology, and superseded priorities are preserved in the [Phase 2 archive](archive/README.md).

## Completed capabilities

- A per-query no-oracle orchestrator wraps the deterministic `TPCAgent` and CP-SAT tier.
- Parser output is normalized into branch-local solver variants with optional entity resolution and disjunction handling.
- The harness records stage telemetry, recovers a best available solver plan after errors or timeouts, and has a schema-shaped fallback.
- Rehearsal supports ceiling, solver-only, and end-to-end attribution; parser comparison and regression gates are available.
- Baselines can run from a pinned source revision and publish committed rows under `results/phase2_baselines/`.

These capabilities are not evidence of final-evaluation performance.

## Current evidence

The current local reference is [run `20260713T130105Z`](../results/phase2_baselines/runs/20260713T130105Z.json), with its configuration, attribution, repetitions, parser statistics, and telemetry preserved in the row.
Use the [latest summary](../results/phase2_baselines/latest.md) only as a pointer; make decisions from the immutable run row and like-for-like comparisons.
The row is repository-local evidence, not an organizer result and not a familiar-100 measurement.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Highest priority

1. **Import familiar-100.** Retrieve the official archive, preserve source URL, date, checksum, member manifest, and an explicit no-oracle loading boundary.
2. **Establish a pinned no-oracle Qwen baseline.** Run the imported familiar-100 path from a pinned revision, record all local runtime and repetition assumptions, and publish the resulting ledger evidence.
3. **Re-rank failures from that evidence.** Separate parser/normalization failures from solver, timeout, and output failures before choosing a fix.

Familiar-100 is a development-only set drawn from the final distribution; its result must not be reported as a final-evaluation estimate.

## Follow-on order

1. Fix the dominant measured failure family with a focused regression test and a flags-off-safe implementation.
2. Measure the winning change through the normal no-oracle gate.
3. Run the longer local-budget assumption as a sensitivity check after the short baseline identifies the failure mix.
4. Package and smoke-test the official harness interface, including oracle hiding, output layout, and tool access.

The public material still does not specify a runtime contract.
Until it does, `300 s` and `900 s` are local assumptions for sensitivity analysis, not organizer-confirmed limits.

## References

- [Stable design](tpc_phase2_design.md)
- [Evaluation methodology](tpc_phase2_eval.md)
- [Dataset boundaries](tpc_phase2_hf_dataset.md)
- [Competition reference](reference/competition.md)
- [Baseline ledger guide](phase2_baselines/README.md)
