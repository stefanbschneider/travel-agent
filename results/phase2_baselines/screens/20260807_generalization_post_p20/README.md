# R22 — the standing phrasing tripwire, first run after P20, and the P18 gate's seed data

**Date** 2026-08-07 · **Branch** `implementation/p18-phrasing-generalization-gate` · **git_sha**
`f413eb2a` (`main` tip at run time, carries P20 `e6cc0e65`) · **Contract** screen, not a
`full_runs/`/`runs/` row. Evaluation workstream instrument:
[R22](../../../../docs/tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change).

This is also the seed run for [P18](../../../../docs/tpc_phase2_roadmap.md#p18--make-phrasing-robustness-a-gate):
its numbers are exactly what
`results/phase2_baselines/phrasing_generalization_floor.json` records, produced with
`--check-floor --update-floor` against this same `git_sha`.

## Verdict: GREEN — and P20 moved every free-prose set, not just familiar-100

| set | post-P15 (`20260807_generalization_post_p15`) | **today, post-P20** | Δ |
| --- | --- | --- | --- |
| familiar_100 (control) | 0/1109 (0.0%) | **0/1109 (0.0%)** | flat — **PASS** |
| local_released_150 | 6/522 (1.1%) | **5/522 (1.0%)** | −1, improved |
| hf_easy | 127/1579 (8.0%) | **97/1579 (6.1%)** | −30, improved |
| hf_medium | 126/1264 (10.0%) | **78/1264 (6.2%)** | −48, improved |
| hf_human | 99/687 (14.4%) | **81/687 (11.8%)** | −18, improved |
| hf_preference_base50 | 19/260 (7.3%) | **14/260 (5.4%)** | −5, improved |

Every free-prose set improved, none regressed; `familiar_100` stays perfect.

**Attribution, checked rather than assumed.** The prior screen is `dbacc183`; three items landed in
`dbacc183..f413eb2a` (`git log --oneline dbacc183..f413eb2a`): P16, P19, P20. Of those, only P20
touches code this probe's default (`llm_parse=False`, `entity_resolution=False`) path exercises —
`git diff --stat dbacc183..f413eb2a` shows the only production-parser file changed is
`parse_constraints.py` (P20's cuisine/attraction-type fixes); P16's changes are confined to
`chinatravel/agent/phase2/normalize.py`, reachable only behind `TPC_P2_LLM_PARSE` (off by default,
never set here); P19 shipped analysis scripts only, no parser change. So this delta is P20's, not a
blend — a second, unfitted confirmation that a fix scoped as family-recall (not phrasing) generalizes
past familiar-100, consistent with the pattern P15 also showed.

## What P18 adds on top of this reading

Before P18, this table was read by eye once per parser change. Now:

- `results/phase2_baselines/phrasing_generalization_floor.json` records this run's `n_parse_gap`
  (and `n_oracle_clauses`, a snapshot fingerprint) per set, keyed by `source.name`.
- `scripts/phase2_generalization_probe.py --check-floor <path>` re-measures every
  `DEFAULT_SETS` entry and exits `1` if any set's `n_parse_gap` rose above its recorded floor, or
  prints a `SKIPPED (snapshot drift)` line — never a failure — if a set's `n_oracle_clauses`
  changed (the dataset revision moved, so the counts aren't comparable).
- `tests/phase2/test_phrasing_generalization_gate.py` runs the same check inside the default
  `pytest tests/phase2` suite (no `integration` marker needed — measuring all six sets takes
  ~14 s locally) and skips cleanly, stating why, when the local HF cache is unavailable.
- `make phase2-generalization-gate` is the explicit standalone invocation for the R22 cadence.
- `--check-floor --update-floor` ratchets the floor down only (`min(current, recorded)` per set):
  it can tighten the gate after a real fix but can never raise a set's recorded floor to launder a
  regression — asserted in the fast synthetic tests in the same test file.

## Files

- `probe.json`, `summary.md`, `fix_headroom.json`, `residual_gaps_after_fix.json` — raw
  `phase2_generalization_probe.py` output, this run only.
- `../../phrasing_generalization_floor.json` — the floor file this run seeded (lives one level up,
  outside `screens/`, since it is a standing gate artifact rather than a one-off screen).
- Regenerate with `HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir <dir>`.
  Re-check the gate with `make phase2-generalization-gate`.
