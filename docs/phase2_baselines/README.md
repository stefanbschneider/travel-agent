# Phase 2 Baseline History

This directory stores commit-friendly, longitudinal Phase 2 baseline metrics.

## Files

- history.jsonl: append-only ledger, one JSON object per baseline run.
- history.csv: tabular projection generated from history.jsonl.
- latest.json: full record of the most recent baseline run.
- latest.md: short human-readable summary of the most recent run.
- runs/<run_id>.json: immutable per-run snapshot copy.

## Standard Command

Run from repo root:

```bash
.venv/bin/python scripts/phase2_record_baseline.py --split-set val --fold 0 --folds 10 \
  --budget-sec 60 --limit 20 --repeats 2 --label baseline-60s-n20
```

Or via Makefile:

```bash
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=60 P2_LIMIT=20 P2_REPEATS=2 P2_LABEL=baseline-60s-n20
```

You can remove --limit for full-fold runs once runtime is acceptable for your workflow.
Runtime scales roughly with `repeats × n × 1.9 × budget_sec` (the solve loop deliberately uses its
whole slice, in both end-to-end and solver-only modes).

## Row Semantics (read this before comparing rows)

- **Fresh by default.** Since 2026-07-10 the recorder clears the fold's end-to-end results before
  running, so a row reflects the current code. Before that, `resume=True` could silently reuse plans
  produced by older code or a different budget — treat pre-fresh rows (those with `fresh` empty/False
  in history.csv) as unreliable for cross-commit comparison.
- **`label` and n.** Rows with `n < 10` are auto-labeled `smoke`; at n=1 a single budget-boundary
  flake flips FPR between 0 and 100, which is what the "solver-only instability" in early ledger rows
  was. Only compare rows with the same fold/limit/budget and n ≥ 10.
- **`repeats` and `*_std` columns.** With `--repeats N` the rehearsal runs N times (fresh each time)
  and the row records mean/std of e2e/solver-only FPR and overall_true across repeats. Organizers run
  each harness 5x and average, so this is the local estimate of that variance.

## Notes

- The script always uses deterministic fold selection.
- It records rehearsal attribution, parser-vs-oracle metrics, and timing/reliability metrics.
- It also records completion status per stage family: parse completed/failed, and whether
  end-to-end and solver-only finished without timeout vs were interrupted/recovered/fell back.
- Raw per-query outputs remain in existing harness locations under agent_env/runs and results.
- The aggregated `timed_out` count reflects orchestrator timeout events; a timeout can still recover to
	a valid output (`valid_output_rate=1.0`) when solve recovery succeeds.
