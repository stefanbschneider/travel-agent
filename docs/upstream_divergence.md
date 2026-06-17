# Upstream divergence

Upstream remote: `upstream https://github.com/LAMDASZ-ML/ChinaTravel.git`.

Checked on branch `fabi/dev2` after `git fetch upstream`.

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

## Known upstream bugs retained for leaderboard parity

The local verifier keeps upstream behavior for parity:

1. Case-sensitive type/cuisine/feature matching in `symbol_verification/concept_func.py` can make some generated queries unsatisfiable when literal casing differs from the database value.
2. The benchmark `eval_tpc.py` overall score double-counts EPR-micro and omits EPR-macro. Local scoring reports both the parity `overall` and the corrected `overall_official`.

Both issues were confirmed still present in `upstream/main`; they are documented in `README.md`.

## Solver-scope note

The local agent now handles parsed inner-city transport exclusions, conditional transport preferences, taxi-car-count constraints, and a CP-SAT inner-transport budget reserve. Remaining failures after the leftover solve are not silently papered over: marginal ordering and POI-distance cases were not given ad-hoc special cases because they need a larger route-ordering subsystem and the oracle gate correctly rejects unsafe plans.
