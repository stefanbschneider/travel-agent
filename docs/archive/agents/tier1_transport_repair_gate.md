# Tier 1 gate: commonsense-transport repair (`TPC_REPAIR_TRANSPORT_GAPS`)

Evaluation-focused brief. Self-contained: hand this file to a separate agent. It runs
**in parallel with the cascade gate** (PR #39 / `TPC_CASCADE_TIMED_WINDOWS`) — the two gates are
independent and **share one baseline**, so this does not wait on the cascade run.

## What this is (and is not)

- **No new code.** `TPC_REPAIR_TRANSPORT_GAPS` is already landed opt-in (default off, floor
  byte-identical). See the roadmap's [Commonsense-transport repair](../tpc_phase2_roadmap.md#commonsense-transport-repair)
  section for the mechanism. This brief is purely a **900 s gate**, which is long-running eval work
  — not an implementation change.
- **Target metric is commonsense (EPR), not logical FPR.** The pass grounds broken inner-city legs,
  targeting the *"Invalid Transport information across positions"* commonsense residual — the dominant
  commonsense-transport failure family in the post-pin solver-only attribution (run
  `scripts/phase2_solver_failure_attribution.py` on the current baseline row for the live count rather
  than trusting a hard-coded number here). Watch the EPR/commonsense component and that specific
  failure count — not `overall_true`/FPR alone.

## Baseline is the current promoted default — and is shared with the cascade gate

Since [PR #41](https://github.com/stefanbschneider/china-travel-agent/pull/41), `TPC_PIN_TIMED_WINDOWS`
and `TPC_SOLVE_CONVERGE_PATIENCE=15` are **harness-default-on** (via
`solve_phase2.apply_deterministic_solver_defaults()`, applied inside `run_split`). So a plain baseline
row at current `main` already runs **pin+converge on**. Both this gate and the cascade gate measure a
candidate flag *on top of that same default baseline*, so:

- **Record the baseline once**, reuse it for both gates. Don't pay for it twice.
- The transport-repair candidate and the cascade candidate are **independent runs** — launch them
  concurrently (separate cores/machines/folds).

All runs: `familiar_100_val` (the 80-query dev split), `900 s`, 2 repeats, **one pinned sha shared by
all three rows**. Pick it at run time and export it (do not trust a hard-coded hash — `main` moves):

```bash
export MAIN_SHA=$(git rev-parse origin/main)   # or a specific reviewed sha you intend to gate
```

## Step 0 (optional, ~15–20 min): fast screen first

Confirm the pass fires and moves the commonsense component before spending the long gate:

```bash
make phase2-quick-eval P2_FLAG=TPC_REPAIR_TRANSPORT_GAPS \
  P2_QE_MODE=solver-only P2_QE_SPLIT_SET=familiar_100_val P2_N=40 P2_BUDGET=60 P2_PARALLEL=3
```

Green-ish screen (EPR/commonsense up, `Invalid Transport` count down, no runaway new timeouts) →
proceed to the gate. Flat/negative → report and stop; do not gate.

## Step 1: record the shared baseline (once)

```bash
make phase2-baseline-at SHA=$MAIN_SHA P2_SPLIT_SET=familiar_100_val \
  P2_BUDGET=900 P2_REPEATS=2 P2_PARALLEL=3 P2_LABEL=tier1-baseline-pinconv
```

This is the pin+converge default (no extra env). **Reuse this row for the cascade gate too.**

## Step 2: record the transport-repair candidate (parallel-safe)

Same sha, same split/budget/repeats — the only difference is the env flag:

```bash
TPC_REPAIR_TRANSPORT_GAPS=1 make phase2-baseline-at SHA=$MAIN_SHA P2_SPLIT_SET=familiar_100_val \
  P2_BUDGET=900 P2_REPEATS=2 P2_PARALLEL=3 P2_LABEL=tier1-transport-repair-on
```

The env var propagates to the solve subprocesses (same mechanism as the fast-fpr flags). Confirm the
telemetry shows the repair pass actually ran before trusting the row.

## Step 3: gate

```bash
make phase2-gate \
  BASELINE=results/phase2_baselines/runs/<tier1-baseline-pinconv row>.json \
  CANDIDATE=results/phase2_baselines/runs/<tier1-transport-repair-on row>.json
```

## Promote only if

- The **commonsense / EPR** component improves (the *"Invalid Transport information across
  positions"* failures drop), **and**
- **no new parse failures and no new timeouts**, **and**
- `continuous_score` / FPR does not regress.

If it clears, promotion is a one-line addition to `apply_deterministic_solver_defaults()` in
`agent_env/scripts/solve_phase2.py` (mirror the pin/converge default:
`if "TPC_REPAIR_TRANSPORT_GAPS" not in os.environ: os.environ["TPC_REPAIR_TRANSPORT_GAPS"] = "1"`),
plus a test case and a roadmap note — that flip is a small implementation PR, **not** part of this gate.

## Invariants (unchanged)

- Compare only like-for-like rows: same data source, split, budget, repeats, parallelism, and
  flags-except-the-one-under-test. All three rows here share everything but `TPC_REPAIR_TRANSPORT_GAPS`.
- A committed ledger row promotes a change; a screen only triages.
- No oracle in the agent path; the row's telemetry must be self-describing.

## Known limit already documented

Cascading time-shifts are out of transport-repair's scope (it grounds legs, never re-times). Those
cases are the cascade move's job ([PR #39](https://github.com/stefanbschneider/china-travel-agent/pull/39)),
gated separately against this same baseline.
