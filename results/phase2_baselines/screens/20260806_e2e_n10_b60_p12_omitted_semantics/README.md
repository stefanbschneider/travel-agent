# P12 screen (2026-08-06): close P10's false-positive half

**What this is not:** a `--mode whole-run` screen ([P11](../../../../docs/tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen-landed-2026-08-06)
did not exist on this branch; it landed later the same day) or a `--flag` screen (`scripts/phase2_quick_eval.py`; P12 has no
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
confirmed programmatically, 0 diffs.

> **⚠ Correction (2026-08-06, added by the docs workstream after this screen was committed).**
> This paragraph originally called that identity **"expected and structurally guaranteed"** on the
> grounds that `parsed_verifier.evaluate_parsed_constraints` "is consulted only by the final
> self-score (`selfscore.py`), never by the CP-SAT solve/accept loop this path runs, so the produced
> plan cannot differ between arms no matter what the checker fix changes". **That is wrong.** The
> checker is consulted by *both*. Phase 2 runs with `TPC_USE_ORACLE=0`
> (`chinatravel/agent/phase2/orchestrator.py:283`), and in that mode
> `TPCAgent._make_checker`'s `base_check` **is** `evaluate_parsed_constraints`
> (`chinatravel/agent/tpc_agent/tpc_agent.py:174`) -- the same `check(plan)` that drives
> `_accepted`, every `_pack_plan` commit rule and the restart loop's `consider()`. Probing that gate
> with the adversarial plan from this PR's own test (an `accommodation` activity inside a meal-only
> window at the right POI) returns `check -> (3, 3)`, **accepted**, under pre-P12 semantics and
> `(0, 3)`, **rejected**, under post-P12 semantics.
>
> So the 0 diffs below are a genuine **empirical** result on this sample, not a compile-time
> guarantee: the fix did not fire, which is exactly what the next paragraph reports when it finds the
> *self*-score checks byte-identical too. The fix can and does change what the shipped solver
> accepts, so it needs a measurement on the shipped path. That is
> [R17](../../../../docs/tpc_phase2_eval.md#r17--does-the-tree-we-would-actually-ship-still-score-what-r16-measured-open).
> Nothing else in this README changes -- the mechanism evidence, the unit tests and the F1 check all
> stand.


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
