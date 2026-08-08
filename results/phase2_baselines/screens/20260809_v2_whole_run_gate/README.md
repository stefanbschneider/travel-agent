# R33 — the `v2` whole-run gate on familiar-100

**Date** 2026-08-08 · **Branch** `submission/v2-candidate` · **host** 10-core macOS (Apple M1 Pro),
`.venv` Python 3.12.13 · **Contract** `make phase2-full-run`'s script
(`scripts/phase2_full_run.py`), i.e. the organizers' own entry point under the full `18000 s`
envelope, `--workers 4`, `--fresh`, split `tpc_phase2_familiar_100`, then `eval_tpc.py`. **Two rows,
run concurrently at 4 workers each** so both arms see identical host contention; each arm runs from
its **own pinned `git worktree`**, so an edit in the development tree cannot reach a live measurement
(it did once during this session's first attempt, which is why that attempt was discarded).

Evaluation-workstream instrument: [R33](../../../../docs/tpc_phase2_eval.md#r33--the-v2-whole-run-gate-on-familiar-100).
The complementary free-prose measurement is
[R32](../20260808_v2_candidate_freeprose/README.md); this row asks the *regression* question in the
shipped shape.

## Arms

| arm | revision | configuration | row |
| --- | --- | --- | --- |
| baseline | `0b4c44a4` (`main` tip before this branch) | harness defaults only | [`full_runs/20260808T200402Z_v2gate_base.json`](../../full_runs/20260808T200402Z_v2gate_base.json) |
| candidate | `104a90d8` (adds P26) | `TPC_P2_DROP_UNSATISFIABLE_NAMES=1`, `TPC_WINDOW_RELOCATE_DAY=1` | [`full_runs/20260808T200402Z_v2gate_cand.json`](../../full_runs/20260808T200402Z_v2gate_cand.json) |

Both rows record `git_dirty: false`, `plans_written 100`, `empty_plans 0`, `run_wall 0.63 h` of the
`5 h` envelope, and the same three passes (triage 100 × 120 s, repair, polish).

## Result: GREEN — `+1.0476` overall, `+2.0` FPR, nothing regresses

| metric | baseline | candidate | Δ |
| --- | --- | --- | --- |
| MicEPR | `99.6667` | `99.6667` | `0` |
| MacEPR | `98.0000` | `98.0000` | `0` |
| C-LPR | `90.1713` | `90.4418` | **`+0.2705`** |
| FPR | `45.0000` | `47.0000` | **`+2.0000`** |
| DAV | `26.3542` | `27.4542` | `+1.1000` |
| ATT | `35.4623` | `36.6953` | `+1.2330` |
| DDR | `25.7500` | `27.0167` | `+1.2667` |
| **overall** | **`64.6878`** | **`65.7354`** | **`+1.0476`** |
| `constraints_ok` (oracle-free self-score) | `50/100` | `54/100` | `+4` |
| `empty_plans` | `0/100` | `0/100` | `0` |

**Attribution.** P26 is *structurally inert* on this register — familiar-100's template always states
the intercity mode in the directional form the pre-existing patterns already covered, and the
byte-identity test in `tests/phase2/test_parser_phrasing_generalization.py` asserts that for all 100
queries. So the movement here belongs to the two flags, principally `TPC_WINDOW_RELOCATE_DAY`, whose
own quick screen predicted exactly this shape (`+2/40` at n=40 → `+2/100` here) and
`TPC_P2_DROP_UNSATISFIABLE_NAMES`, which R32 measured as small-but-positive on free prose. The
preference terms move because two more queries pass their constraints, not because packing changed:
a failing query scores `0` on all three.

## What this row is not

- **Not comparable to [R28](../../full_runs/20260807T152009Z.json)** (`64.1725`), which ran on a
  4-core Linux box with 3 workers. The baseline arm here scores `64.6878` on the same code for that
  reason — a faster host spends the same envelope on more restarts. Only the *pair* above is a
  like-for-like comparison, which is why both arms were re-run rather than reusing R28.
- **Not evidence about free prose.** Familiar-100 cannot exercise the phrasing or precision work; that
  is [R32](../20260808_v2_candidate_freeprose/README.md) and
  [R34](../20260809_r34_intercity_e2e/README.md).
- **One repeat each.** Whole-run rows on a fixed host and seed have been bit-identical across repeats
  in this project (R7's three), so a single pair is the established contract, but a `+1.05` delta is
  not so large that it could not partly be scheduling luck.
