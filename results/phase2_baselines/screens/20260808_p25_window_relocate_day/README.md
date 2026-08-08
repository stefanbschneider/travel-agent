# P25 — cross-day timed-window relocation, quick A/B screen

**Date** 2026-08-08 · **Branch** `implementation/p25-cross-day-window-relocation` · **Box** the
coding VM (2 cores) — per the roadmap's "implementation workstream owns its own pre-gate screen,
1-2h, committed in the PR that makes the change"; this is a screen, not a promotion gate (see the
[two-measurement-contracts rule](../../../../docs/tpc_phase2_eval.md#two-measurement-contracts)).
**Contract** `scripts/phase2_quick_eval.py`-style paired A/B (same deterministic subset/budget/
seed, one flag differing), solver-only mode (oracle-derived constraints, no LLM, fully
deterministic), driven by a small wrapper
(`/tmp/.../scratchpad/run_p25_screen.py`, not committed — a thin shim around
`phase2_quick_eval._run_condition`/`check_gate`/`decide_verdict` that additionally snapshots each
arm's produced-plan directory before the next arm's `--fresh` clears it, so both arms' plans exist
side by side afterward for the shape/diff comparison the roadmap's bar requires).

## What this measures

[P25](../../../../docs/tpc_phase2_roadmap.md#p25--cross-day-timed-window-relocation) adds
`TPC_WINDOW_RELOCATE_DAY` (library default off): delete a present-but-window-missing
`timed_visit_named_poi` activity and re-insert it on a different day, in one atomic trial, when no
in-day move (anchor/push) can place it. Stacked on top of the harness-default window moves
(`TPC_PIN_TIMED_WINDOWS`, `TPC_WINDOW_ANCHOR`, `TPC_WINDOW_PUSH`, `TPC_WINDOW_INSERT`,
`TPC_COMMONSENSE_FIRST`), since the roadmap scopes it as "only meaningful together with" those.

## Pre-registered expectation (written before reading the result)

The roadmap counted **8** sole-blocker queries on the full `familiar_100_val` (`n=80`) needing a
cross-day move. At `n=40` (half the split, same seed/fold-0 prefix as every other screen in this
repo) the naive expectation is roughly half that, further cut by how many of those 8 shapes are
actually groundable (a real transport leg has to exist, the target day's own structure has to have
room) — so **1-3 flips**, and this move firing on a small minority of the 40 plans, is the expected
shape going in. A screen that shows a large fraction of plans changing must not be read as "the
move fired broadly" without checking *why* — the deterministic solver flags act inside the restart
loop, so even a query where the move never commits still spends extra wall-clock (deepcopy +
`_get_transport`/`_resolve_timed_window_poi` calls per attempt) inside `_pack_plan`, which can shift
which random-restart tuples complete within the same 60s budget. This is the same "search
perturbation" confound [R30](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
documented for P22. So: report the FPR delta, but corroborate it independently with (a) the
`timed_visit_named_poi` shape counts before/after and (b) an explicit fail→pass diff, not the mean
alone.

## Command

```bash
.venv/bin/python /tmp/.../scratchpad/run_p25_screen.py
# equivalent to:
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_WINDOW_RELOCATE_DAY \
  --extra-env "TPC_PIN_TIMED_WINDOWS=1,TPC_WINDOW_ANCHOR=1,TPC_WINDOW_PUSH=1,TPC_WINDOW_INSERT=1,TPC_COMMONSENSE_FIRST=1" \
  --split-set familiar_100_val --n 40 --budget-sec 60 --parallel 2 \
  --out results/phase2_baselines/screens/20260808_p25_window_relocate_day
```

## Results

| | baseline (`RELOCATE_DAY=0`) | candidate (`RELOCATE_DAY=1`) | Δ |
| --- | --- | --- | --- |
| FPR (pass %) | `40.0` (16/40) | `45.0` (18/40) | **+5.0** (+2 queries) |
| overall_true | `62.581` | `65.140` | +2.559 |
| commonsense pass | 40/40 | 40/40 | flat |
| logical_micro | `90.64` | `91.10` | +0.46 |
| timeouts / errors | 0 / 0 | 0 / 0 | flat |
| wall (both arms) | 1288.0s | 1281.4s | flat |
| solve_sec_mean | 60.51 | 60.63 | flat (both arms run the restart loop to the 60s cap) |

Gate: **PASS** (no reason blocked). Verdict from `decide_verdict`: **GREEN LIGHT** — candidate
improves its target signal (FPR) and passes the like-for-like monotonic gate.

### Corroboration (not just the mean)

**Explicit fail→pass diff**, re-evaluating each of the 40 uids' oracle `hard_logic_py` clauses
against both arms' plans directly (`evaluate_constraints_py`, independent of the aggregate report):
exactly **2 flips, 0 regressions**:

- `phase2_familiar_20250322201313997965_00089` (`False -> True`)
- `phase2_familiar_20250323014548418503_00037` (`False -> True`)

**`timed_visit_named_poi` shape counts** (`scripts/phase2_timed_window_shapes.py --plans <dir>
--split tpc_phase2_familiar_100_val`, `plans_off/` vs `plans_on/`):

| shape | off (instances / queries) | on (instances / queries) |
| --- | --- | --- |
| `forward_shift` | 14 / 12 | 12 / 10 |
| `backward_shift` | 7 / 7 | 7 / 7 |
| `shorten` | 6 / 5 | 6 / 5 |
| `absent_poi` | 6 / 5 | 6 / 5 |
| `all_pass` | 16 | 18 |

`forward_shift` instances/queries both drop by exactly 2, matching the two flips -- the family this
move targets shrank, not an unrelated shape. (`backward_shift`, the shape the roadmap named as the
primary "window already passed" case, is unchanged at `n=40`; the two flips this run found came
through the `forward_shift` residual instead -- see "not yet exercised" below.)

Both arms' full 40-plan directories were used to compute the tables above, then trimmed to just the
two flipped uids' plans (`evidence/<uid>.{off,on}.plan.json`, matching the `20260807_r30_...`
screen's own convention) before committing -- the full directories are regenerable byte-for-byte
from the pinned seed/subset/budget/env above and are not needed to audit the flip.

**Spot-checked both flips' plan diffs directly** (not just that clauses changed) and both show a
genuine cross-day relocation, not a coincidental reshuffle:

- `..._00089`: `One Ear Pavilion` (attraction) moves from day 2 (`15:36-17:06`, outside its window)
  to day 1 (`18:20-19:10`, inside it) — deleted from day 2, re-legged, inserted between day 1's
  dinner and the day's own accommodation tail.
- `..._00037`: `Cloudrise Art Museum` (attraction) moves from day 0 (`12:05-13:20`) to day 1
  (`15:33-16:23`) — deleted from day 0 (its neighbours re-legged directly), inserted between two
  existing day-1 attractions.

Both match `_relocate_timed_windows_across_days`'s designed behaviour (`_remove_movable_activity`
then one of the `_insert_activity_*` helpers) exactly.

### The `40/40 uids_with_plan_diff` number, read honestly

Every one of the 40 plans differs at the byte level between arms, as flagged by the pre-registered
expectation above as something to explain rather than take as "the move fired 40 times". Cause: the
per-query `solve_sec_mean` is ~60.5-60.6s in *both* arms (the restart loop runs to the fixed 60s
budget in both), so the extra grounding work `_relocate_timed_windows_across_days` does on every
`_pack_plan` call — even the large majority where no relocation is applicable or none of it commits
— consumes a few extra milliseconds per attempt and shifts which random-restart draws complete
before the budget clock hits zero. This is the exact "search perturbation, unrelated to the [flag's]
content" effect [R30's P22 screen](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
documented, not evidence the move over-fires. The shape-count and explicit-diff corroboration above
is what separates "2 real, targeted flips" from "40 plans of unrelated noise, 2 of which happened to
flip"; a plan-content diff alone (without shape/clause evidence) would not have been enough to trust
the delta on this move specifically.

### What was not exercised at `n=40`

- **The "window already passed" (`backward_shift`) shape the roadmap named as primary is
  unchanged** here (`7/7` both arms) — the two observed flips both came from residual
  `forward_shift` cases where anchor/push's in-day fix left the activity still just outside the
  window and no in-day room remained, which this move also reaches (any present-but-unsatisfied
  copy, not only the "already passed" sub-case). The `backward_shift`/`absent_poi`-driven cross-day
  flips the roadmap counted (8 on the full `n=80` val split) are simply less likely to land in a
  random 40-query half; this screen does not rule them out, it just didn't sample one.
- **Solver-only mode supplies oracle-derived `activity_time_windows`** (`activity_types` reliably
  populated). On the shipped parsed path this move may fire less often, since parse-side window
  extraction is imperfect (see [P15](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction)).
- **"Re-grounded through `ground_and_check`"** (the roadmap's atomicity bar) is satisfied in
  substance rather than by literally calling that function: `_pack_plan`'s own
  `_sanitize_plan_for_grounding` step, the insert helpers' real `_get_transport` legs, and the
  shared `check`/`_repair_commit_allowed` gate together provide the same "never occupies a `best`
  slot without being re-verified" guarantee `ground_and_check` provides for the Stage-3 LLM refine
  path specifically.

## Verdict and next step

**GREEN LIGHT, corroborated beyond the aggregate.** +2/40 flips (5.0 FPR points), 0 regressions, 0
new timeouts, and the shape/diff evidence rules out the search-perturbation confound as the
explanation for the flips specifically (only the *unrelated* 38 plan diffs are attributable to it).
Worth a pinned end-to-end gate on the eval machine — an Evaluation-workstream job (this box must not
run one; see the [two-VM rule](../../../../CLAUDE.md)). `TPC_WINDOW_RELOCATE_DAY` stays library
default off and out of `PROMOTED_SOLVER_FLAGS` until that row exists.
