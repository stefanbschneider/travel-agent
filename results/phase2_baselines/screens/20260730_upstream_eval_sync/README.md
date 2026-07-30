# 20260730_upstream_eval_sync

Post-sync sanity screen for the upstream evaluator integration
(`LAMDA-NeSy/ChinaTravel` `main` `764614c`, PRs #29/#30).

**This is not a gate row and not a ledger row.** It is a reduced-budget, small-`n` run whose only
purpose is to answer "does the Phase 2 path still behave, and where did the score move?". Do not
compare its absolute numbers with the `900 s` rows under `../../runs/` — different budget, different
`n`, and a different evaluator contract.

| | |
| --- | --- |
| Split | `tpc_phase2_familiar_100_val`, fold `0/1`, `n=20` (`--limit 20`) |
| Budget | `120 s` per query, `--parallel 3`, `--fresh` |
| LLM | backend `none` (deterministic path, zero LLM calls) |
| Command | `.venv/bin/python scripts/rehearse_phase2.py --mode both --split-set familiar_100_val --folds 1 --fold 0 --limit 20 --budget-sec 120 --parallel 3 --fresh` |

## Result

| | MicEPR | MacEPR | C-LPR | FPR | DAV | ATT | DDR | overall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| end-to-end | `100.00` | `100.00` | `88.15` | `25.00` | `13.13` | `19.25` | `12.92` | **`54.30`** |
| solver-only | `99.07` | `75.00` | `63.03` | `15.00` | `6.88` | `10.37` | `10.83` | `40.57` |

`old_contract` in `summary.json` re-scores **the identical plans** under the pre-2026-07-28 rules
(preference averaged over passing queries only; ATT `1.0` for a transport-free plan):

- end-to-end `61.10` → `54.30` (`-6.80`), and
- every point of that delta is the preference denominator: the end-to-end plans record **zero**
  commonsense failures under the new strict checker, so the chronology and meal-cap rules cost the
  Phase 2 path nothing. `DAV/ATT/DDR` of `52.50/76.99/51.67` over the 5 passing plans are unchanged;
  they are simply now divided by 20 instead of 5.

Solver-only still emits 5 commonsense-failing plans (1 chronology, 4 transport-grounding); the
end-to-end path does not, which is the commonsense-first finalization policy doing its job.
