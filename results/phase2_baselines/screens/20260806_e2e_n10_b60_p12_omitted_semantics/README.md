# P12 screen (2026-08-06): close P10's false-positive half

**What this is not:** a `--mode whole-run` screen ([P11](../../../../docs/tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen)
does not exist on this branch) or a `--flag` screen (`scripts/phase2_quick_eval.py`; P12 has no
flag -- it is a correctness fix, always active). The roadmap item's own bar calls for the former
once P11 lands; until then it explicitly accepts a hand-rolled comparison, the same workaround
P10's own PR used (`docs/tpc_phase2_roadmap.md`, "Then P11" section).

**Method.** `end-to-end` mode (`solve_phase2.run_split`, no `total_budget_sec` -- per-query
branch), `n=10`, `budget_sec=60`, `tpc_phase2_familiar_100_val`. The 10 uids are the ones (of the
51 in val whose NL matches "dine|stay at ... between") most likely to exercise the
`activity_types` fix: a query with both a "Dine at HOTEL between A and B" and a "Stay at HOTEL
between C and D" window on the same POI name. `before` = `git stash` (pre-fix tree); `after` =
`git stash pop` (this PR). Same interpreter process family, same uids, same budget, sequential.

**Result: byte-identical.** Every one of `schema_pass` / `commonsense_pass` / `logical_pass` /
`all_pass` / `overall_true` matches per uid between `baseline.json` and `candidate.json` --
confirmed programmatically, 0 diffs. This is **expected and structurally guaranteed** in
per-query mode: `parsed_verifier.evaluate_parsed_constraints` is consulted only by the final
self-score (`selfscore.py`), never by the CP-SAT solve/accept loop this path runs, so the produced
plan cannot differ between arms no matter what the checker fix changes -- official score identity
across arms is a compile-time guarantee of *this specific screen mode*, not evidence the fix does
nothing. (Whole-run mode, where the scheduler *does* feed self-score back into repair/restart
decisions, could in principle produce a different plan; that is exactly the measurement P11 exists
to make possible, and is out of scope here.)

More surprising: the *self*-score side (`parsed_constraints_eval.checks`, the actual per-clause
booleans the fix touches) is also byte-identical on this sample -- 0 diffs. The fix did not fire.
Spot-checking the one query with a same-POI dine+stay window pair
(`phase2_familiar_20250322231032581051_00033`) confirms why: the dine-window check already failed
before the fix (the meal activity's own time missed its 07:55-08:45 window -- a genuine violation,
unrelated to activity-type confusion) and the stay-window check already passed on the correctly
typed accommodation activity in both arms. Neither is the coincidence this fix targets.

**Why that's not a null result.** The roadmap's own diagnosis put the omitted-semantics false
positive rate at **5 of 150** queries *across all five categories combined*
(`docs/tpc_phase2_roadmap.md#p12`), so `n=10` has low power to land on one by chance; a solver that
is actively trying to satisfy a window also mostly produces the correctly-typed activity anyway,
so the bug this fix closes is a coincidence on top of a coincidence (wrong-typed activity, right
place, right time window) rather than something present in every affected query. The fix's
correctness and mechanism are demonstrated directly instead, with a hand-built adversarial plan
that reproduces the exact failure this screen didn't happen to hit:
`tests/phase2/test_parsed_verifier_p12_omitted_semantics.py`. Both new checks (`required_order`,
the `activity_types` filter) are built from real released-data evidence, not speculation:

- **Required visit ordering** -- the exact oracle `idx_activity0`/`idx_activity1` index-comparison
  DSL, matched byte-for-byte against 3 real Phase-1 queries containing "visit X first, then Y" /
  "first go to X, then Y" phrasing (`chinatravel/data/en/TPC_IJCAI_2026_phase1_EN`, permitted for
  offline dev per `CLAUDE.md`'s phase boundary -- no held-out uid or field was read).
- **Meal/accommodation type confusion** -- found by cross-referencing a real familiar-100 query's
  `hard_logic_py` (`phase2_familiar_20250322231032581051_00033`, which gates a "Dine at HOTEL
  between..." window by `activity_type(activity) in ['breakfast','lunch','dinner']`, separately
  from a "Stay at HOTEL between..." window gated by `activity_type(activity)=='accommodation'`)
  against the parser, which already recorded this distinction as `activity_types` on each window
  (`parse_constraints.py::_WINDOW_VERB_ACTIVITY_TYPES`) -- the checker simply discarded it.

**The other three of the five omitted semantics** (required restaurant lists, required attraction
lists, the inner-transport budget) were investigated the same way and found to be **already
correctly represented** by the existing `required_restaurants` / `required_attractions` /
`budgets.inner_transport` checks on every case tried (see the same test file). Closing the residual
5/150 gap for those, if any survives, needs the actual held-out `official=no, parsed=yes` plans
(an Evaluation-workstream artifact per the roadmap item's own "where the evidence lives" note),
not a checker change.

**Full-`val` parser F1 unaffected.** `scripts/parser_vs_oracle.py --split
tpc_phase2_familiar_100_val` reports `f1=0.9588` identically before and after (both fixes are
checker-side; the one new parser field, `required_order`, matched 0/80 val queries, so no
`family_stats` entry moved).
