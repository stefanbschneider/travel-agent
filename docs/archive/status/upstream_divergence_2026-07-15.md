# Upstream divergence

Upstream remote: `upstream https://github.com/LAMDASZ-ML/ChinaTravel.git`.

Checked on branch `merge-remote-changes` against `origin/main` and `upstream/main` after
`git fetch upstream` on 2026-06-22 14:24 CEST.

## Scoring and verifier code

No local scoring-harness edits were found in the checker modules compared with `upstream/main`:

- `chinatravel/evaluation/commonsense_constraint.py`
- `chinatravel/evaluation/hard_constraint.py`
- `chinatravel/evaluation/schema_constraint.py`
- `chinatravel/evaluation/preference.py`
- `chinatravel/symbol_verification/*.py`
- `chinatravel/environment/world_env.py`

Command used:

```text
git diff --stat upstream/main -- chinatravel/evaluation/*.py chinatravel/symbol_verification/*.py chinatravel/environment/world_env.py
```

Result: no output.

## Data and split files

The relevant tree diff is data-heavy, not checker-code-heavy:

```text
git diff --stat upstream/main -- chinatravel/evaluation chinatravel/symbol_verification chinatravel/environment
```

Observed result: 267 files changed, 334877 insertions, 0 deletions. The additions are local benchmark artifacts such as `chinatravel/environment/database/**` CSV files and split/query data needed for offline Phase-1 scoring. The only deletion in this scoped diff is `chinatravel/environment/.DS_Store`.

## Current upstream evaluation state

The current upstream main branch now includes concept-name canonicalization in
`symbol_verification/concept_func.py`, so the earlier case-sensitive unsatisfiable-query
issue is fixed there.

The remaining parity issue is the benchmark `eval_tpc.py` overall score: it still
double-counts EPR-micro and omits EPR-macro. Local scoring reports both the parity
`overall` and the corrected `overall_official`.

These notes are mirrored in `README.md`.

## Solver-scope note

The local agent now handles parsed inner-city transport exclusions, conditional transport preferences, taxi-car-count constraints, and a CP-SAT inner-transport budget reserve. Remaining failures after the leftover solve are not silently papered over: marginal ordering and POI-distance cases were not given ad-hoc special cases because they need a larger route-ordering subsystem and the oracle gate correctly rejects unsafe plans.
