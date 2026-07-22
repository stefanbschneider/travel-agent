# TPC 2026 Phase 2 Evaluation and Dataset Boundaries

This document defines how to measure a no-oracle harness without confusing local diagnostics for organizer results, and which data source each measurement is drawn from.
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

## Dataset boundaries

Phase 2 measurements must name their data source.
These four sources have different trust and generalization properties; none substitutes for the organizer's final held-out set.
Do not compare rows across sources as if they had the same distribution or oracle exposure.

### 1. Official familiar-100 development set (preferred signal)

The organizers released the [familiar-100 archive](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip) on 2026-07-15 with the Agent Environment Guide.
The 100 source records are imported unchanged under `chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/` and selected by `tpc_phase2_familiar_100`.
`_provenance.json` pins the source URL, release/retrieval dates, archive SHA-256, and every extracted member's size, CRC32, and SHA-256.
The records contain `hard_logic_py`; loaders retain it only for scoring and attribution, while the adapter and both harnesses expose only `uid`, trip metadata, and `nature_language` to the agent path.
Familiar-100 is drawn from the same distribution as final evaluation, so it is the preferred new-development signal — but a familiar-100 result must identify this imported artifact and run configuration and must not be presented as a final-evaluation estimate.

### 2. Repository-local released data

The repository contains the released Phase 1 English queries and their oracle fields under `chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/`.
`make phase2-splits` deterministically partitions that released source into `tpc_phase2_val` and `tpc_phase2_test` for local development.
Despite the local `test` name, these are not organizer-held-out Phase 2 data.
They average `~16` `hard_logic_py` constraints per record versus `~38` in familiar-100, so a val result under-represents the constraint density of the final distribution.
They remain useful only when the agent path hides `hard_logic_py` and other oracle-only fields.

### 3. Hugging Face ChinaTravel

[`LAMDA-NeSy/ChinaTravel`](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel) is public benchmark data with multiple configurations and splits.
It is useful only as an out-of-distribution phrasing-generalization probe for an auxiliary parser or solver, never as a tuning target.
The set is natively Chinese; `load_hf_queries` uses its English translation field (`nature_language_en`), so the "OOD" gap versus familiar-100 is a phrasing-register difference within English (free prose vs. rigid templates), not a cross-language difference.
Keep the HF configuration and split names with every result; do not merge different configurations into one comparison.
The repository comparison utility is:

```bash
.venv/bin/python scripts/compare_hf_dataset.py --hf-config default
```

### 4. Organizer final held-out set

The final Phase 2 set is separate, unavailable locally, and evaluated only through the organizer-run no-oracle harness on Qwen3.6-27B via SGLang.
No local split, HF subset, or familiar-100 result proves performance on it.
Use those sources to diagnose and rank work, then preserve no-oracle boundaries and regression gates so the submitted harness remains robust to unseen requests.

## Baselines and repetitions

Use a deterministic fold, fresh outputs, and a pinned source revision for a promotable baseline.
Long runs should use `make phase2-baseline-at SHA=<ref> ...` so the recorded revision is the code that executed.
Record a local repeat count whenever variance matters.
The public competition material does not specify a repeat count or per-query timeout; `300 s` and `900 s` remain local sensitivity settings.
Familiar-100 ledger rows must carry the manifest-derived data-source ID and remain separate from the repository-local `tpc_phase2_val`/`tpc_phase2_test` partitions and the organizer final held-out set.

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

## Measurement rule

Record the source name, selected split, deterministic selection, budget, flags, and model/backend with every measurement.
Do not infer final-evaluation performance from local rows or from familiar-100.
For ledger semantics, see the [baseline ledger guide](phase2_baselines/README.md); for current priorities, see the [Phase 2 roadmap](tpc_phase2_roadmap.md).
