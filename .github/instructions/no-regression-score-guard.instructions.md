---
applyTo: "{results/best/**/*.json,results/optimal/**/*.json,chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt,scripts/**/*.py,*.py}"
description: "Enforce strict score non-regression for manual query optimization workflows. Use when editing itineraries, running batch optimization, or updating best/optimal/suboptimal artifacts."
---

# No Regression Score Guard

## Core Rule

Never regress validated scores.

- Do not reduce a UID's `overall` score in `results/best`.
- Treat already optimal UIDs (`overall == 100.0`) as protected.
- Never degrade `results/optimal` entries.
- Never remove unresolved UIDs from `tpc_phase1_suboptimal.txt`.

## Required Validation Protocol

1. Baseline first:
- Before editing a UID, run:
- `/Users/stefanshschneider/Projects/private/china-travel-agent/.venv/bin/python eval_tpc.py --splits tpc_phase1 --index <uid> --method best --lang en`
- Record at least: `overall`, `DAV`, `ATT`, `DDR`, `FPR`.

2. Candidate acceptance:
- After each candidate edit, re-run per-UID eval.
- Accept edits only if all are true:
- `FPR == 100.0`
- New `overall` >= baseline `overall`
- For protected UIDs (`overall == 100.0` baseline), new `overall` must remain exactly `100.0`.

3. Checkpoint write rules:
- Write to `results/optimal/<uid>.json` only when UID is validated at `overall == 100.0`.
- Set `_eval_score` to `100.0` only after validated exact 100.0.
- Prune from `tpc_phase1_suboptimal.txt` only for validated exact 100.0 UIDs.

## Batch-Level Safeguards

- Keep a before/after table for all processed UIDs in the batch.
- If any UID regresses, immediately restore previous file content for that UID and continue with safe state.
- Prefer targeted local edits over broad rewrites.
- If a UID appears not solvable to 100.0 after substantial valid effort, move to next UID without forcing risky edits.

## Operational Constraints

- Use existing `eval_tpc.py` with split `tpc_phase1` for scoring.
- Prefer manual result construction and API-guided edits.
- Avoid relying on TPC agent or CP solver except short fallback checks when necessary.
- Do not commit or push unless explicitly requested by the user.
