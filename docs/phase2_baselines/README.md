# Phase 2 Baseline Ledger

This directory is the interpretation guide.
Generated, committed rows live in [`results/phase2_baselines/`](../../results/phase2_baselines/), keeping measurements separate from active prose.

## Record a row

Run the canonical target from the repository root:

```bash
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=60 P2_LIMIT=20 P2_REPEATS=2 P2_LABEL=baseline-60s-n20
```

Use `make phase2-help` for all variants, including pinned evaluations and the regression gate.
The recorder writes:

- `history.jsonl`: append-only source ledger;
- `history.csv`: tabular projection;
- `latest.json` and `latest.md`: most recent row; and
- `runs/<run_id>.json`: immutable snapshots.
Every new row embeds a `data_source` object; its ID distinguishes repository-derived splits from the checksum-pinned familiar-100 archive. The CSV projection carries the ID, kind, dataset ID, source URL, and archive checksum.

## Compare like with like

A comparison is meaningful only when rows use the same source revision, data-source ID, split set, deterministic fold/limit, budget, repeat count, flags, parser/model configuration, and telemetry collection mode.
Treat low-`n` rows as smoke checks, not regressions or improvements.
A pinned evaluation records the source revision it executed; prefer it for long runs.

The public Phase 2 material does not currently specify a query timeout or repeat count.
`300 s` and `900 s` are local sensitivity assumptions, not organizer rules.
Do not infer final-evaluation performance from local rows or from familiar-100.

## Read the row before using it

- **No-oracle boundary:** end-to-end rows must hide every top-level `hard_logic*` verifier field from the agent.
- **Axes:** compare ceiling, solver-only, and end-to-end values separately; their gaps attribute solver headroom and parsing/harness loss.
- **Aggregate score:** `eval_tpc.py` uses 10% EPR-micro and 10% EPR-macro. Its per-query monotonic merge score uses EPR-micro for both environmental slots; that merge choice is not a second aggregate score.
- **Repetitions:** inspect mean and standard deviation together. A label alone does not prove a configured LLM was reached; check backend and failure telemetry.
- **Freshness:** compare rows produced from fresh outputs. Resumed output or mixed revisions invalidates attribution.
- **Gate:** run `make phase2-gate BASELINE=<row> CANDIDATE=<row>` before accepting an intended improvement.

Use [`docs/tpc_phase2_eval.md`](../tpc_phase2_eval.md) for methodology and [`docs/tpc_phase2_roadmap.md`](../tpc_phase2_roadmap.md) for current priorities.
