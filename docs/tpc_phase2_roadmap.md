# TPC 2026 Phase 2 Roadmap

This is the only active Phase 2 plan.
Historical step plans, chronology, and superseded priorities are preserved in the [Phase 2 archive](archive/README.md).

## Completed capabilities

- A per-query no-oracle orchestrator wraps the deterministic `TPCAgent` and CP-SAT tier.
- Parser output is normalized into branch-local solver variants with optional entity resolution and disjunction handling.
- The harness records stage telemetry, recovers a best available solver plan after errors or timeouts, and has a schema-shaped fallback.
- Rehearsal supports ceiling, solver-only, and end-to-end attribution; parser comparison and regression gates are available.
- Baselines can run from a pinned source revision and publish committed rows under `results/phase2_baselines/`.
- The official familiar-100 records are imported byte-for-byte with a pinned archive checksum, per-member manifest, dedicated split, and explicit no-oracle boundary.

These capabilities are not evidence of final-evaluation performance.

## Current evidence

The current local reference is the pinned no-oracle Qwen [familiar-100 run `20260716T090638Z`](../results/phase2_baselines/runs/20260716T090638Z.json). It used the official familiar-100 archive, DeepInfra `Qwen/Qwen3.6-27B`, two fresh repeats, library-default Phase 2 flags, and the local `300 s` budget assumption.
The row reports `26%` solver-only FPR versus `2%` end-to-end FPR, a `24`-point parser/normalization loss. Full-split parser precision/recall/F1 are `0.4445 / 0.1281 / 0.1988`. All outputs are schema-valid; `35%` of end-to-end runs and `23%` of solver-only runs reached the bounded-solver timeout and recovered without fallback.
The familiar release has no organizer best plans, so its ceiling is unavailable rather than zero. This repository-local development result is not an estimate of final held-out performance.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Highest priority

1. A focused deterministic parser change now maps numbered or line-start `Visit` / `Dine at` / `Stay at` intervals into contained activity windows while preserving the legacy free-form interpretation. Its solver-free familiar report matches `activity_time_windows` and `position_presence` on all `84/84` affected queries, removes `48` spurious `stay_duration` cases, and moves parser precision/recall/F1 from `0.4445 / 0.1281 / 0.1988` to `0.8180 / 0.3518 / 0.4920`. This is diagnostic evidence, not promotion.
2. Measure the committed change through the normal pinned no-oracle gate only after explicit run confirmation.
3. Keep `budgets` (`70/70` missing) as the next independent parser family. Do not combine it or the broad excluded-entity families with the first change.
Familiar-100 is a development-only set drawn from the final distribution; its result must not be reported as a final-evaluation estimate.

## Follow-on order

1. Re-rank parser families after measuring the focused time-window/position change.
2. Fix the next measured family, currently budgets, with the same regression-first gate.
3. Run a longer local-budget sensitivity only if a future short-gate failure set remains timeout-confounded. The anchor does not justify it: all `23` solver-only timeout recoveries are solver-pass cases, and none of the `74` both-mode failures timed out.
4. Package and smoke-test the official harness interface, including oracle hiding, output layout, and tool access.

The public material still does not specify a runtime contract.
Until it does, `300 s` and `900 s` are local assumptions for sensitivity analysis, not organizer-confirmed limits.

## References

- [Stable design](tpc_phase2_design.md)
- [Evaluation methodology](tpc_phase2_eval.md)
- [Dataset boundaries](tpc_phase2_hf_dataset.md)
- [Competition reference](reference/competition.md)
- [Baseline ledger guide](phase2_baselines/README.md)
