# R24 — does a query above 300 s ever flip?

**Date** 2026-08-07 · **Branch** `eval/r22-r23-r24` · **git_sha** `54be4514` · **host** 4-core Linux (3
workers) · **Contract** per-query screen, not a `full_runs/`/`runs/` row. Evaluation workstream
instrument: [R24](../../../../docs/tpc_phase2_eval.md#r24--does-a-query-above-300-s-ever-flip-the-owners-question-open).

**Question.** [P4](../../../../docs/tpc_phase2_roadmap.md#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass)
found that every recorded row caps at `300 s`/query by an accident of wiring, and no query has ever
been solved above it — untested, not tested-and-flat. This measures the untested regime directly: a
per-query budget ladder (`--budget-sec`) on `familiar_100`'s failing subset, bypassing the whole-run
envelope entirely so the cap is the only variable.

## Method

56 of `familiar_100`'s 100 queries fail their constraints in [R19](../../../../docs/tpc_phase2_eval.md#the-closed-queue-r1r19)
(`results/phase2_e2e_r19_phrasing/`), derived at **zero solve cost** by re-scoring R19's own written
plans (`fpr_true < 1.0`) rather than guessing a random subset — this independently reproduces R19's
official `FPR 44.0` exactly (`44/100` passing). The first 30 (sorted uid) became the ladder's fixed
subset (`r24_failing30.txt`). Each budget arm re-solves all 30 **fresh** (no `--resume`, no shared
`--method` directory between arms — a shared directory would let a higher-budget arm silently inherit
a lower-budget arm's plan instead of re-solving, see `_run_whole_run`'s docstring on the same trap),
via `agent_env/scripts/solve_phase2.py --budget-sec <B>` directly (plain per-query mode, no
`--total-budget-sec`, so the sweep scheduler and its own `300 s` wiring bug are bypassed entirely — this
measures the solver's own ceiling, not the scheduler). 3 concurrent subprocesses (`cores − 1`).

## Result: zero flips, and the search isn't clock-bound at all in this range

| budget | passing (of 30) | solve_sec mean / median / max | timed out |
| --- | --- | --- | --- |
| `300 s` (re-confirms R19) | `0/30` | `107.8 / 107.4 / 192.3` | `0/30` |
| `900 s` | `0/30` | `107.4 / 105.6 / 187.1` | `0/30` |

**`solve_sec` is statistically the same at `900 s` as at `300 s`** (mean delta `−0.34 s`, max absolute
per-query delta `6.2 s` — run-to-run noise, not a budget effect). No query's solve time approaches
even the `300 s` cap; the highest observed is `192 s`. A byte-diff of two full plans (the two closest
to the cap, `83 s`→`85 s` and `192 s`→`187 s`) shows the **only field that differs is the recorded
wall-clock timestamp** — every itinerary decision is identical. `overall_true` moved by exactly `0.0000`
on all 30 queries between the two arms.

**This is a stronger result than "no flips": the solver does not use the extra budget at all.**
Something other than the clock — restart-neighborhood exhaustion, an internal convergence-patience
gate, or both — stops the search at its own fixed point around `65–190 s`, regardless of whether the
cap is `300 s` or `900 s`.

## Decision, per the doc's own table

| outcome | action |
| --- | --- |
| flips grow with budget | land P4, re-measure the envelope ladder, move P5 up |
| a few flips at 900 s, none beyond | land P4 anyway, do not pursue P5 |
| **no flips at any budget** *(this row)* | **land P4 as a correctness fix only, close P5 with this row as the evidence** |

**`2700 s` arm was not run.** Both this row's own decision-table branch and the advisor's pre-registered
gate agree: the `2700 s` arm only changes the reading if `900 s` showed flips. It showed zero — not
"few," zero, with byte-identical plans — so a `2700 s` arm (`~7.5 h` worst case on this box) would
almost certainly reproduce the same fixed point at three times the cost. Flagged here as a deliberate
scope decision, not an oversight; re-open it only if a *different* mechanism (e.g. a patience-setting
change) makes the search clock-bound again.

**Caveat that belongs in the reading, not the design** (already in the doc): this measures the
*solver's* ceiling on familiar-100, where the constraint set is [known to be extracted cleanly](../20260807_generalization_post_p15/README.md).
On the held-out distribution a large share of failures are plausibly clauses never extracted at all,
and no amount of search budget satisfies a clause that isn't in the objective — this row says nothing
about that axis.

## Files

- `r19_failing.json` — the zero-cost derivation of R19's failing/passing uids (from R19's own written
  plans, no solve).
- `r24_failing30.txt` — the fixed 30-uid subset the ladder ran on.
- `r24_scored_b300.json`, `r24_scored_b900.json` — per-uid `fpr_true`/`overall_true` for each arm.
- `telemetry_summary.json` — solve-time and score-delta statistics backing the table above.
- Raw plans and telemetry are not committed (bulky, reproducible): `results/phase2_e2e_r24_ladder_b300/`,
  `results/phase2_e2e_r24_ladder_b900/`, `agent_env/runs/phase2_e2e_r24_ladder_b{300,900}/`.
