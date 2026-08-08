# R34 — does the intercity recall fix (P26) convert end to end?

**Date** 2026-08-08 (recorded under the 08-09 queue date) · **Branch** `submission/v2-candidate` ·
**host** 10-core macOS (Apple M1 Pro) · **Contract** paired free-prose A/B on `hf_medium` (n=150),
per-query mode (`agent_env/scripts/solve_phase2.py`, no `--total-budget-sec`), `--budget-sec 90`,
`--lang en`, both arms launched **simultaneously** with two shards each, each arm from its **own
pinned `git worktree`**. Scored against both the untranslated control oracle and R31's translated one.
Screen, not a `full_runs/` row.

Evaluation-workstream instrument: [R34](../../../../docs/tpc_phase2_eval.md#r34--does-the-intercity-recall-fix-convert),
gating [P26](../../../../docs/tpc_phase2_roadmap.md#p26--free-prose-intercity-transport-mode).

## Arms

Identical except for the parser, which is the point: both carry the `v2` candidate flag pair, so this
row isolates P26 rather than compounding it with the flag decision R32/R33 already made.

| arm | revision | flags |
| --- | --- | --- |
| `v2r34_pre` | `0b4c44a4` (pre-P26) | `TPC_P2_DROP_UNSATISFIABLE_NAMES=1`, `TPC_WINDOW_RELOCATE_DAY=1` |
| `v2r34_p26` | `104a90d8` (P26) | same |

## Result: GREEN — C-LPR `+0.95`, FPR `+2.67`, overall `+1.61`

Scored against the translated oracle (the arm with a real FPR denominator):

| metric | pre-P26 | P26 | Δ |
| --- | --- | --- | --- |
| MicEPR / MacEPR | `100.0` / `100.0` | `100.0` / `100.0` | flat |
| C-LPR | `88.6867` | `89.6361` | **`+0.9494`** |
| FPR | `45.3333` | `48.0000` | **`+2.6667`** (4 more queries pass every clause) |
| DAV / ATT / DDR | `26.71` / `42.35` / `25.09` | `28.58` / `44.62` / `26.98` | up (they follow FPR) |
| **overall** | **`65.0127`** | **`66.6182`** | **`+1.6055`** |

Control (untranslated) oracle, for continuity: C-LPR `82.8323 → 83.7025`, FPR `21.3333 → 24.6667`,
overall `51.5239 → 53.4361`. Full logs in [`eval/`](eval/).

**Clause level, per uid** (`clause_diff_tool.py`, reusing `evaluate_hard_constraints_v2`): **`14`
clauses fail→pass, `2` pass→fail**, net `+12` of `1264`. The bar this row set before running required
`fail→pass > pass→fail`; it is `7×`.

**A reproducibility check worth recording.** The `v2r34_pre` arm is the same configuration as
[R32](../20260808_v2_candidate_freeprose/README.md)'s `main`+drop+relocate arm but was solved again
under a *different* concurrency (4 concurrent solver processes here, 8 there). It reproduced
**every metric to the last decimal** (`C-LPR 88.6867088607595`, `FPR 45.33333333333333`,
`overall 65.01269329179868`). The per-query solve is therefore not sensitive to host load at this
budget, which is what licenses comparing arms across the two screens.

## Limits

- One free-prose register, one budget (`90 s`/query), one host, one repeat per arm.
- The translated oracle is a measurement device (P23), not the organizers' oracle.
- P26 is provably inert on familiar-100 (byte-identity test over all 100 queries), so this row and
  [R33](../20260809_v2_whole_run_gate/README.md) together cover both registers without overlapping.
- `2` clauses do regress. Both are the expected cost of *adding* a constraint: a query whose intercity
  mode is now pinned has a smaller feasible set, so the solver can land on a worse plan elsewhere. The
  net is `+12`, and the promotion question is the net.
