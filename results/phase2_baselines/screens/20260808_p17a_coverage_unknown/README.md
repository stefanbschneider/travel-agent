# P17(a) — stop trusting our own "satisfied" verdict, whole-run screen

**Date** 2026-08-08 · **Branch** `implementation/p17a-coverage-unknown` · **Box** the coding VM (2
cores) — implementation-workstream pre-gate screen, not a promotion gate (see
[two-measurement-contracts](../../../../docs/tpc_phase2_eval.md#two-measurement-contracts)).
**Contract** `scripts/phase2_quick_eval.py --mode whole-run` (paired A/B, same subset/budget/seed,
one flag differing) -- required for this item specifically, unlike P25's `_pack_plan`-level flag:
`TPC_P2_COVERAGE_UNKNOWN` changes *which pass a query enters* (`_candidate_passes`/`_choose_pass`,
consumed only by `run_sweeps_split`/`sweeps.run_sweeps`), machinery a `solver-only`/`end-to-end`
screen never reaches at all.

## What this measures

[P17(a)](../../../../docs/tpc_phase2_roadmap.md#p17--stop-trusting-our-own-satisfied-verdict) adds
`TPC_P2_COVERAGE_UNKNOWN` (library default off): a query the scheduler's own checker calls
`constraints_ok` stays in the repair rotation instead of being promoted to polish when its visible
text mentions a budget amount or a room-type noun that no parsed variant carries a family for. See
`chinatravel/agent/phase2/coverage_signal.py`'s module docstring for the two shipped categories,
the cuisine detector that was built and rejected on measurement (58/100 false-positive rate on
familiar-100, from cuisine words appearing inside restaurant *names*), and the deferred named-POI
detector.

## Pre-registered expectation (written before reading the result)

Two categories, both measured `0/100` on familiar-100 and `0/150` on `local_released_150`
(`scripts/phase2_generalization_probe.py`'s `coverage_signal` table, static, no solve) before this
screen ran. **`familiar_100_val` -- the only split-set `--mode whole-run` currently
supports -- is therefore expected to fire on `0/14` queries in this screen's subset too**, since it
is a subsplit of the same set the static probe measured at `0/100`. This screen's only two possible
honest readings going in were: (a) `0` fires, confirming the trigger-rate claim held under a real
whole-run solve and showing no unrelated cost from computing the signal, or (b) `>0` fires, which
would mean the static probe's zero was an artifact and needs investigation before anything else.
**A flat FPR/`overall_true` here is the expected null result, not evidence the item does nothing** --
the signal cannot act on a register it never fires on. The two registers where it *does* fire
(`hf_human` 4/154, `local_released_150` had `6/150` before cuisine was dropped and `0/150` after)
are not reachable through `--mode whole-run`'s split-set choices (`val`/`test`/`familiar_100*` only,
no HF sets); that gap is the residual this screen closes out below rather than working around.

## Command

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_COVERAGE_UNKNOWN \
  --mode whole-run --split-set familiar_100_val --n 14 \
  --total-budget-sec 1800 --budget-sec 90 --workers 2 \
  --out results/phase2_baselines/screens/20260808_p17a_coverage_unknown
```

`n=14`/`workers=2` (not the doc's `n=40`/`workers=6` calibrated starting point) because this box has
2 cores: `rounds = ceil(n / workers)` had to stay in the same ballpark (`7` here vs. the doc's `~7`
at `40/6`) for the repair pass to clear `DEFAULT_MIN_QUERY_SEC`'s 20s floor and let
`MIN_BUDGET_GROWTH` (1.25x) meaningfully gate a second pass, rather than every pass collapsing to
the floor and measuring nothing.

## Results

| | baseline (`COVERAGE_UNKNOWN=0`) | candidate (`COVERAGE_UNKNOWN=1`) | Δ |
| --- | --- | --- | --- |
| FPR (pass %) | `35.71` (5/14) | `35.71` (5/14) | `+0.00` |
| overall_true | `59.716` | `59.716` | `+0.00` |
| commonsense pass | 14/14 | 14/14 | flat |
| all_pass (n) | 5 | 5 | flat |
| timeouts | 0 | 2 (both recovered) | +2 |
| wall | 909.2s | 888.1s | flat |

Tool verdict: **NO BENEFIT** (flat within noise, candidate arm shows +2 recovered timeouts). Taken
at face value this reads as a caution sign. It is not one -- see below.

### The pass composition did change, and that is worth reading before the verdict

| | baseline pass 2 (repair) | baseline pass 3 (polish) | candidate pass 2 (repair) | candidate pass 3 (polish) |
| --- | --- | --- | --- | --- |
| queries | 11 | 3 | 9 | 5 |
| improved | 2 | 1 | 0 | 1 |

Repair shrank and polish grew between arms -- the opposite direction from what the item is supposed
to do (keep a flagged query *in* repair). This is not the flag acting wrongly; it is two independent
solves producing different triage-stage plans (the candidate arm's own reported `+2` timeouts,
`recovered: 2`, changes which queries reach `constraints_ok` after triage on this specific run),
unrelated to `TPC_P2_COVERAGE_UNKNOWN`'s own mechanism. Proof, not inference: **both arms' raw
`agent_env/runs/<method>/tpc_phase2_familiar_100_val_summary.json` record
`"coverage_unknown_uids": []`** -- the candidate arm's flag was on
(`"coverage_unknown_flag": true`) and still found zero of the 14 queries whose text meets either
category's bar. With nothing flagged, `repair_order`/`polish_order`'s `coverage_unknown` eligibility
filter is a no-op on every uid in this run by construction (see `sweeps.repair_order`'s own
`coverage_unknown.get(uid, False)` check) -- the pass-composition and timeout deltas above are
solve-to-solve noise from running two independent whole-run solves back to back on a shared 2-core
box, not a measurable effect of this item's code. The `Δ` row correctly reads "no measurable
effect", but the *reason* is "the mechanism had nothing to act on here", which the raw evidence
above disambiguates from "the mechanism does not work" or "the mechanism regresses quality" --
neither of which this run tests.

### Multi-pass precondition, checked before trusting anything above

Baseline shows two non-triage passes (`repair`: 11 queries, `polish`: 3 queries) -- the screen is
not triage-only-degenerate, so the calibration (`n=14`, `workers=2`, `total_budget_sec=1800`,
`budget_sec=90`) is sound for what it measures, even though what it measures (zero fires) turned out
to be the expected null.

## What this screen does and does not establish

**Established, with direct evidence:**
- The mechanism itself is correct: `tests/phase2/test_sweeps.py`'s `coverage_unknown` tests prove
  `repair_order`/`polish_order`'s eligibility filter behaves exactly as specified (pure, deterministic,
  unit-level), and `tests/phase2/test_coverage_unknown_wiring.py` proves `run_sweeps_split` computes
  the signal once per query in the parent and threads it through to `sweeps.run_sweeps` correctly,
  including the flag's off-by-default no-op path.
- The flag adds no measurable cost or regression when it fires on zero queries (this screen, plus
  the static trigger-rate table) -- a real whole-run solve confirms the `0/14` prediction and shows
  no unrelated overhead from computing the signal in the parent.
- The trigger-rate precondition (P13's bar) holds under a real solve, not only statically.

**Not established, and explicitly a residual, not a gap papered over:** whether keeping a flagged
query in repair rather than polish actually helps a query whose text states an unrepresented
requirement, on a whole-run schedule. That needs a `--mode whole-run`-equivalent screen on a
register where the signal fires at nonzero volume (`hf_human`, or `local_released_150` before the
cuisine detector was dropped) -- `phase2_quick_eval.py --mode whole-run` does not currently support
an HF split-set (`--split-set` is `val|test|familiar_100|familiar_100_val|familiar_100_test` only),
so this needs either a tooling extension or a bespoke driver (mirroring the plan-snapshot shim
[P25's screen](../20260808_p25_window_relocate_day/README.md) used for a different gap). Filed as
a residual rather than built here to keep this item's scope to what was pre-registered; an
Evaluation-workstream job either way (this box must not run a long free-prose whole-run solve --
see the two-VM rule).

## Verdict and next step

**Safe, mechanism-verified, e2e-benefit-on-a-firing-register unmeasured.** Ships library default
off. Not a `PROMOTED_SOLVER_FLAGS`/`CANDIDATE_SOLVER_FLAGS` candidate the way P4/P25 are (this repo
only tracks `TPCAgent`-read solver flags there; `TPC_P2_COVERAGE_UNKNOWN` is scheduler-level, read
in `agent_env/scripts/solve_phase2.py`). Next step is the residual above, on the Evaluation
workstream's own schedule.
