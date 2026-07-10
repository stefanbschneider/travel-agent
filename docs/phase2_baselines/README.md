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
.venv/bin/python scripts/phase2_record_baseline.py --split-set val --fold 0 --folds 10 --budget-sec 120 --limit 20
```

Or via Makefile:

```bash
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=120 P2_LIMIT=20
```

You can remove --limit for full-fold runs once runtime is acceptable for your workflow.

## Notes

- The script always uses deterministic fold selection.
- It records rehearsal attribution, parser-vs-oracle metrics, and timing/reliability metrics.
- It also records completion status per stage family: parse completed/failed, and whether
  end-to-end and solver-only finished without timeout vs were interrupted/recovered/fell back.
- Raw per-query outputs remain in existing harness locations under agent_env/runs and results.
- The aggregated `timed_out` count reflects orchestrator timeout events; a timeout can still recover to
	a valid output (`valid_output_rate=1.0`) when solve recovery succeeds.
