# The v2 candidate on free prose — `v1` vs current `main`, and the two candidate flags

**Date** 2026-08-08 · **Branch** `submission/v2-candidate` · **host** 10-core macOS (Apple silicon),
`.venv` Python 3.12.13 · **Contract** per-query mode
(`agent_env/scripts/solve_phase2.py`, no `--total-budget-sec`), `--budget-sec 90`, `--lang en`,
`hf_medium` free prose, **n=150**, four arms launched **simultaneously** with 2 shards each (8 solver
processes on 10 cores) so every arm sees the same host contention. Screen, not a `full_runs/` row.

**Why this screen exists.** The 2026-08-07 leaderboard breakdown says the held-out failure is in
*knowing what to satisfy*, and [R31](../../../../docs/tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate)
removed the last reason free prose could not be scored honestly (the CJK-oracle-literal FPR ceiling).
That combination makes one measurement possible for the first time: **what the code that has landed
since the `v1` submission is actually worth on a register that behaves like the held-out set.** `v1`
was built from `be196d00` (2026-08-05) and therefore predates the phrasing fix (2026-08-06), P15, P20
(recall), P22, P24 (precision), P23, P17(a), P4, P6 and P25. No committed row measures that gap,
because every existing row is on familiar-100 — the one register where all of it is structurally inert.

## Arms

| arm | tree | flags beyond the harness defaults |
| --- | --- | --- |
| `v2cmp_v1` | `be196d00` in a detached `git worktree`, its **own** `apply_deterministic_solver_defaults()` (so it reproduces the shipped `v1` configuration: `TPC_WINDOW_PUSH`/`TPC_WINDOW_INSERT` **off**) | — |
| `v2cmp_main` | current `main` (`0b4c44a4`) | — |
| `v2cmp_main_drop` | current `main` | `TPC_P2_DROP_UNSATISFIABLE_NAMES=1` |
| `v2cmp_main_drop_reloc` | current `main` | `TPC_P2_DROP_UNSATISFIABLE_NAMES=1`, `TPC_WINDOW_RELOCATE_DAY=1` |

Both splits were materialized locally and are gitignored (`hf_medium_v2`, `hf_medium_v2_en_oracle`);
the translated one reproduces R31's report exactly — `91` queries changed, `125` clauses, `1` residual
unmapped literal (`e20241028161036243215`).

## Headline: the code that landed after `v1` is worth `+19.87` overall on free prose

Scored against the **translated** (`hf_medium_v2_en_oracle`) oracle, which is the arm with a real FPR
denominator. Full `eval_tpc.py` logs for every arm/oracle pair are in [`eval/`](eval/).

| arm | MicEPR | MacEPR | C-LPR | FPR | overall |
| --- | --- | --- | --- | --- | --- |
| `v1` (`be196d00`) | 100.0 | 100.0 | `75.5538` | `10.6667` | `44.4077` |
| **current `main`** | 100.0 | 100.0 | **`88.3703`** | **`44.0000`** | **`64.2767`** |
| `main` + drop-unsatisfiable-names | 100.0 | 100.0 | `88.6867` | `45.3333` | `65.0127` |
| `main` + drop + relocate-day | 100.0 | 100.0 | `88.6867` | `45.3333` | `65.0127` |

Same arms against the untranslated control oracle, whose FPR ceiling is `38.67` — reported for
continuity with every earlier free-prose row, **not** to be read against `100`:

| arm | C-LPR | FPR | overall |
| --- | --- | --- | --- |
| `v1` | `71.2816` | `6.6667` | `41.2850` |
| current `main` | `82.6741` | `21.3333` | `51.4844` |
| `main` + drop | `82.8323` | `21.3333` | `51.5239` |
| `main` + drop + relocate-day | `82.8323` | `21.3333` | `51.5239` |

`main` reproduces R31's independently measured control row (`C-LPR 82.4367`, `FPR 20.6667`,
`overall 51.0570`, different host and shard layout) to within `0.24` C-LPR and one query of FPR, which
is the cross-check that this screen's absolute numbers are not an artifact of this host.

## Clause-level, per uid — the reading that matters for C-LPR

Produced with [`clause_diff_tool.py`](clause_diff_tool.py) (R31's helper, repo root re-pointed), which
reuses `evaluate_hard_constraints_v2` rather than reimplementing the checker. Tables:
[`clause_v2cmp_v1.json`](clause_v2cmp_v1.json), [`clause_v2cmp_main.json`](clause_v2cmp_main.json),
[`clause_v2cmp_main_drop.json`](clause_v2cmp_main_drop.json).

| comparison | clauses fail→pass | clauses pass→fail | net | file |
| --- | --- | --- | --- | --- |
| `v1` → `main` | **`191`** | `29` | **`+162`** of `1264` | [`clause_diff_v1_to_main.txt`](clause_diff_v1_to_main.txt) |
| `main` → `main`+drop | `8` | `4` | `+4` | [`clause_diff_main_to_drop.txt`](clause_diff_main_to_drop.txt) |
| `main`+drop → +relocate-day | `0` | `0` | `0` | [`clause_diff_drop_to_reloc.txt`](clause_diff_drop_to_reloc.txt) |

`+162` net clauses is `12.82` points of C-LPR, and it moves `50` queries from failing to fully passing
(`FPR 10.67 → 44.00`). The `29` losses are real and are not hidden here: this is a *code* A/B, not
R31's oracle-rewrite A/B, so a pass→fail flip is an expected consequence of changed parses and of
search perturbation, and the promotion question is the net — which is `+162`.

## The two candidate flags

**`TPC_P2_DROP_UNSATISFIABLE_NAMES`: small, positive, and this is the first register where it could
show anything at all.** `+0.74` overall, `+1.33` FPR (`66 → 68` queries fully passing), `+4` net
clauses (`8` gained, `4` lost). [R30](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
measured `0/103` flips and could not do better: it read FPR on registers capped at `38.67` by
untranslated CJK literals, so a flipped query mostly could not become visible. Under a real
denominator, two do. It is still a small effect and the `4` lost clauses are the honest cost.

**`TPC_WINDOW_RELOCATE_DAY` is provably inert on this register.** Not merely flat in aggregate: all
`150` plan files are identical between the drop and drop+relocate arms once the `elapsed_time(sec)`
field is removed (checked directly, per file). Free prose in `hf_medium` does not contain the
present-but-window-missing `timed_visit_named_poi` shape the pass targets, so it never fires. Its only
positive evidence remains the familiar-register screen
([`20260808_p25_window_relocate_day`](../20260808_p25_window_relocate_day/README.md), `+2/40`), and
this screen neither confirms nor contradicts that — it says the flag carries **no risk and no benefit**
on free prose.

## Limits

- One free-prose register (`hf_medium`), one budget (`90 s`), one host, no repeats. A screen.
- The translated oracle is a *measurement* device (P23), not the organizers' oracle; it lifts a known
  artifact of scoring English query text against Chinese literals. Its own residual cap is
  `149/150 ≈ 99.3` at the query level (one unmapped literal).
- `90 s`/query is not the shipped shape (a 5 h envelope with triage → repair → polish is). This screen
  ranks configurations; it does not predict a whole-run score.
- Nothing here is evidence about the held-out set's absolute score. It is evidence that the *ordering*
  `main` > `v1` holds by a large margin on the register whose failure signature matches the
  leaderboard's.
