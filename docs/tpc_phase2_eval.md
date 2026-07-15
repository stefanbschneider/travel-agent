# TPC 2026 Phase 2 Evaluation

This document defines how to measure a no-oracle harness without confusing local diagnostics for organizer results.
Generated rows live in [`results/phase2_baselines/`](../results/phase2_baselines/); this document defines their interpretation.

## Three axes

| Axis | Input and purpose | Meaning |
| --- | --- | --- |
| Ceiling | `results/best` with released oracle logic and offline iteration | Aspirational upper bound, not a harness baseline. |
| Solver-only | Oracle constraints, bounded autonomous solve | Solver headroom after parsing is removed. |
| End-to-end | Visible text, no oracle, bounded harness | The local approximation to the submitted path. |

The gap from ceiling to solver-only is bounded-solver headroom.
The gap from solver-only to end-to-end is parsing and harness loss.
Use `scripts/parser_vs_oracle.py` to diagnose constraint-family differences and behavioral agreement, but promote a parsing change only after an end-to-end measurement.

## Score semantics

`eval_tpc.py` publishes one aggregate score:

$$
0.10\,\mathrm{EPR\!\text{-}micro} + 0.10\,\mathrm{EPR\!\text{-}macro} + 0.25\,\mathrm{C\!\text{-}LPR} + 0.40\,\mathrm{FPR} + 0.05\,(\mathrm{DAV}+\mathrm{ATT}+\mathrm{DDR}).
$$

Its per-query score for monotonic merging is different: it assigns both 10% environmental slots from that query's binary commonsense result.
That implementation choice helps rank merge candidates; it is not a second official aggregate.

## Baselines and repetitions

Use a deterministic fold, fresh outputs, and a pinned source revision for a promotable baseline.
Long runs should use `make phase2-baseline-at SHA=<ref> ...` so the recorded revision is the code that executed.
Record a local repeat count whenever variance matters.
The public competition material does not specify a repeat count or per-query timeout; `300 s` and `900 s` remain local sensitivity settings.

The imported official familiar-100 set (`tpc_phase2_familiar_100`) is the preferred new development signal.
Its ledger rows must carry the manifest-derived data-source ID and remain separate from repository-local `tpc_phase2_val`/`tpc_phase2_test` partitions and the organizer final held-out set.
See [dataset boundaries](tpc_phase2_hf_dataset.md).

## Ledger comparability

Compare rows only when they match on:

- source revision, data source, split, deterministic fold/limit, and language;
- local budget, repeat count, parallelism, and fresh-output policy;
- parser, solver, and feature flags; and
- LLM backend/model and cache policy when an LLM is enabled.

A row must expose enough telemetry to explain its score: valid-output rate, parse failures, timeout and recovery counts, fallback use, stage timings, LLM attempts/failures, and the three attribution axes.
Low-`n` rows are smoke checks, not promotion evidence.

## Gates

Run the regression gate on like-for-like ledger rows:

```bash
make phase2-gate BASELINE=results/phase2_baselines/runs/<base>.json \
  CANDIDATE=results/phase2_baselines/runs/<candidate>.json
```

When both inputs supply `continuous_score`, it is the blocking score and FPR is advisory; otherwise FPR blocks.
In every case, more parse failures or timeouts block promotion.
Early-stop evaluation modes are diagnostic only and are not comparable with normal preference-scoring rows.

## Command path

Use Make targets rather than duplicating script arguments:

```bash
make phase2-rehearse FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_LIMIT=20
make phase2-parser-report P2_LIMIT=20
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_LIMIT=20 P2_REPEATS=2 P2_LABEL=<tag>
make phase2-timing P2_METHOD=<method> P2_BUDGET=300
```

Use `make phase2-help` for the full catalog.
The [baseline ledger guide](phase2_baselines/README.md) covers row fields and generated artifacts.
