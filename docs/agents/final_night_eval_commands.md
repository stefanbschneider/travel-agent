# Second-Machine Eval Commands (final night, 2026-07-26)

Copy-paste only. Nothing here needs interpretation: run the blocks in order, then commit and push
the generated rows. No decisions are required from the operator, and no result changes the shipped
configuration tonight — these rows exist to confirm at the `900 s` working budget what the
`120 s` screen already showed.

**What is being confirmed.** `TPC_COMMONSENSE_FIRST` was promoted to harness-default-on from a
paired `120 s` screen (`overall_true` `51.34 → 60.98`, C-LPR `67.35 → 89.95`, commonsense pass
`30/40 → 40/40`, FPR `32.5 → 35.0`). Its one open caveat is that timeouts rose `4 → 7` at that
deliberately tight budget, where the baseline solve `p50` was already `108 s` of `120 s`. These two
rows measure the same pair at `900 s`, where the promoted row's `p50` is `265 s` and there is real
headroom.

Promoted SHA: `c599570b614512681c8aec6c2e6305a5490d7e3a`
Branch: `claude/phase2-commonsense-first`

## How long this takes — pick a variant before you start

Each recorder invocation runs **both** axes (end-to-end *and* solver-only) for **every** repeat, so
`P2_REPEATS=2` means four full passes over 80 queries. At a `900 s` budget the promoted row's solve
`p50` is `265 s` / `p95` `499 s`, so with `P2_PARALLEL=3` one pass is roughly `2.5 h` and one arm at
two repeats is `8-10 h` — the same order as the existing pinned rows in the ledger.

| variant | wall clock | what you get |
| --- | --- | --- |
| **A) both arms, `P2_REPEATS=1`** (recommended for one night) | `~9-10 h` | the same-SHA paired comparison the measurement rules require, without repeat-to-repeat variance |
| B) promoted arm only, `P2_REPEATS=2` | `~8-10 h` | variance on the shipped config, but the comparison is cross-SHA against `20260724T192503Z`, which the roadmap forbids treating as like-for-like |
| C) both arms, `P2_REPEATS=2` | `~16-20 h` | the full gate-grade pair; only if the machine has more than one night |

The blocks below use `P2_REPEATS=1` (variant A). Change it to `2` only if you are running variant B
or C. Run the **promoted arm first** so that if only one arm finishes, the one you have is the
configuration that actually ships.

## 0. Prerequisites (once)

```bash
git fetch --all
git checkout claude/phase2-commonsense-first
git log --oneline -1          # expect c599570b
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The environment database must be installed under `chinatravel/environment/database/` (see
`agent_env/README.md`). Leave the LLM backend unset: both arms below run fully deterministic with
zero LLM calls, which is what makes them comparable.

Confirm the database and harness work before starting the long runs:

```bash
make phase2-solve P2_SPLIT_SET=val P2_BUDGET=60 P2_LIMIT=1
```

Expect a line like `[1/1] <uid> valid=True fallback=False ...`.

## 1. Arm B first — promoted default (`TPC_COMMONSENSE_FIRST` left unset)

```bash
make phase2-baseline-at \
  SHA=c599570b614512681c8aec6c2e6305a5490d7e3a \
  P2_SPLIT_SET=familiar_100_val \
  FOLD=0 P2_FOLDS=1 \
  P2_BUDGET=900 \
  P2_REPEATS=1 \
  P2_PARALLEL=3 \
  P2_LABEL=final-night-csfirst-on
```

## 2. Arm A second — flags-off baseline (`TPC_COMMONSENSE_FIRST=0`)

```bash
TPC_COMMONSENSE_FIRST=0 \
make phase2-baseline-at \
  SHA=c599570b614512681c8aec6c2e6305a5490d7e3a \
  P2_SPLIT_SET=familiar_100_val \
  FOLD=0 P2_FOLDS=1 \
  P2_BUDGET=900 \
  P2_REPEATS=1 \
  P2_PARALLEL=3 \
  P2_LABEL=final-night-csfirst-off
```

Run the arms **one after the other**, not concurrently: each already uses `P2_PARALLEL=3`, and
overlapping them would make the wall-clock/timeout numbers — the exact thing being measured —
meaningless.

The pinned `git worktree` at `SHA=c599570b…` means further commits on the branch cannot affect a
run that is already going, so it is safe to keep developing elsewhere while these run.

## 3. Commit and push the rows

```bash
git add results/phase2_baselines/
git commit -m "phase2: final night pinned 900s rows (commonsense-first on/off)"
git push
```

That is the whole job. The row files land under `results/phase2_baselines/runs/<run_id>.json` with
their `label` set to the values above.

## 4. Optional: print the comparison (no judgement needed)

If both arms finished, this prints the paired numbers so they are in the log next to the rows:

```bash
ls -t results/phase2_baselines/runs/*.json | head -2
.venv/bin/python scripts/phase2_gate.py \
  --baseline results/phase2_baselines/runs/<ARM_A_run_id>.json \
  --candidate results/phase2_baselines/runs/<ARM_B_run_id>.json
```

Also useful, and equally interpretation-free:

```bash
.venv/bin/python scripts/phase2_commonsense_headroom.py \
  --row results/phase2_baselines/runs/<ARM_B_run_id>.json --quiet
```

A remaining commonsense-failure count near zero in arm B means the lever landed as designed; the
gate's own `PASS`/`FAIL` line is advisory here because the promotion decision was already made from
the screen.

## If a run dies

The recorder is resumable at the run level: re-issue the exact same command. Partial per-uid
artifacts under `agent_env/runs/` and `results/phase2_e2e_*` are reused. If a worktree is left
behind under `/tmp/phase2_eval`, `scripts/phase2_eval_at.py` cleans it up on the next run unless
`--keep` was passed.
