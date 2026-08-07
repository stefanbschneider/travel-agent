# R22 — the standing phrasing tripwire, first run after P15

**Date** 2026-08-07 · **Branch** `eval/r22-r23-r24` · **git_sha** `dbacc183` (`main` tip at run time,
carries P15 `a4d028bb`/`8688439c`) · **Contract** screen, not a `full_runs/`/`runs/` row. Evaluation
workstream instrument: [R22](../../../../docs/tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change).

P15 merged to `main` claiming it closes `9/15` `local_released_150` phrasing gaps
([roadmap](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction),
[P15's own screen](../20260807_p15_phrasing_robust_extraction/README.md)) but the *standing* tripwire
had not yet been re-run post-merge — this is that run, and the first post-P15 data point for it.

## Verdict: GREEN

Required by R22's acceptance criteria: familiar-100 parse gaps still `0/1109`, and no free-prose
set's gap count rising.

| set | pre-fix (`20260806_generalization_probe`) | post phrasing-fix, pre-P15 (`..._after_fix`) | **today, post-P15** | Δ vs pre-P15 |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 0/1109 (0.0%) | 0/1109 (0.0%) | **0/1109 (0.0%)** | flat — **PASS** |
| local_released_150 | 17/522 (3.3%) | 15/522 (2.9%) | **6/522 (1.1%)** | **−9**, exactly P15's claimed closure |
| hf_easy | 219/1579 (13.9%) | 132/1579 (8.4%) | **127/1579 (8.0%)** | −5, improved |
| hf_medium | 363/1264 (28.7%) | 126/1264 (10.0%) | **126/1264 (10.0%)** | flat |
| hf_human | 146/687 (21.2%) | 99/687 (14.4%) | **99/687 (14.4%)** | flat |
| hf_preference_base50 | 32/260 (12.3%) | 20/260 (7.7%) | **19/260 (7.3%)** | −1, improved |

Every free-prose set is flat or improved, none regressed. `familiar_100` stays perfect. This
independently reproduces P15's own screen's `15/522 → 6/522` local_released_150 number exactly, from
a run outside the PR that made the change — the standing tripwire confirms the landed claim rather
than merely failing to contradict it.

## Reading

- **P15's claim holds under the standing instrument, not just its own screen.** The two small
  additional improvements on `hf_easy` (`132 → 127`) and `hf_preference_base50` (`20 → 19`) were
  called out in P15's own writeup as unfitted evidence (no query from those sets was read while
  writing the patterns) — this run confirms those numbers too.
- **Does not touch R23's open question.** `familiar_100` and `local_released_150` remain the two
  sets closest to fully parsed; the held-out gap (`C-LPR 55.2`) is still far below even the least-gappy
  free-prose set here (`hf_medium` C-LPR ceiling `90.03`), so P15 narrows the *known* residual without
  bearing on the still-unidentified half of the gap ([R23](../../../../docs/tpc_phase2_eval.md#r23--what-else-separates-the-held-out-set-open-static-1-h)).
- No scored (e2e) confirmation is implied by this screen — it is a parse-gap instrument only, per the
  [quick-eval limits section](../../../../docs/tpc_phase2_eval.md#limits--read-before-trusting-a-screen).

## Files

- `probe.json`, `summary.md`, `fix_headroom.json`, `residual_gaps_after_fix.json` — raw
  `phase2_generalization_probe.py` output, this run only (no `_before` counterpart needed; the
  three-way historical comparison above supersedes it).
- Regenerate with `HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir <dir>`.
  On a machine with no cached HF dataset, drop `HF_HUB_OFFLINE=1` for the first run only — it fetches
  and locally caches `LAMDA-NeSy/ChinaTravel`; every subsequent run can use the offline flag.
