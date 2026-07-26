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

## 1. Arm A — flags-off baseline (`TPC_COMMONSENSE_FIRST=0`)

```bash
TPC_COMMONSENSE_FIRST=0 \
make phase2-baseline-at \
  SHA=c599570b614512681c8aec6c2e6305a5490d7e3a \
  P2_SPLIT_SET=familiar_100_val \
  FOLD=0 P2_FOLDS=1 \
  P2_BUDGET=900 \
  P2_REPEATS=2 \
  P2_PARALLEL=3 \
  P2_LABEL=final-night-csfirst-off
```

## 2. Arm B — promoted default (`TPC_COMMONSENSE_FIRST` left unset)

```bash
make phase2-baseline-at \
  SHA=c599570b614512681c8aec6c2e6305a5490d7e3a \
  P2_SPLIT_SET=familiar_100_val \
  FOLD=0 P2_FOLDS=1 \
  P2_BUDGET=900 \
  P2_REPEATS=2 \
  P2_PARALLEL=3 \
  P2_LABEL=final-night-csfirst-on
```

Run the arms **one after the other**, not concurrently: each already uses `P2_PARALLEL=3`, and
overlapping them would make the wall-clock/timeout numbers — the exact thing being measured —
meaningless. Expect several hours per arm.

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
