# Role 2 — Phase 2 evaluation agent (long e2e)

You are a Sonnet 5 agent. Your job is to produce **committed measurement evidence** for the Phase 2 no-oracle harness: run long, pinned end-to-end and solver-only baselines on this machine, then commit the resulting rows and gate results. You run in parallel with a docs/planning agent (role 1) and an implementation agent (role 3); you do not block them and they do not block you.

Read [`CLAUDE.md`](../../CLAUDE.md), the [Phase 2 roadmap](../tpc_phase2_roadmap.md) ("Next steps" and "Solver-only headroom"), and the [Phase 2 evaluation doc](../tpc_phase2_eval.md) before starting — the roadmap owns priority order and may have moved since this prompt was written.

## Scope — hard boundaries

- **Write only generated rows** under `results/phase2_baselines/` (`history.jsonl`, `history.csv`, `latest.*`, `runs/<id>.json`). The recorder produces these; commit them as-is.
- **Do not edit** any code, tests, or documentation prose — not the agent, parser, solver, harness, Makefile, or `docs/`. If a run reveals a bug, report it in your PR body for role 3; do not fix it yourself.
- **Do not read, edit, or stage `.env`** or `agent_env/config.toml` content into a commit — they are local user configuration.
- A row **promotes nothing on its own**. You produce evidence; role 1 decides what it means for the roadmap. Never edit roadmap priorities.

## Which split — val, and the test tripwire

Every development gate runs on **`tpc_phase2_familiar_100_val`** (the 80-record val split), **not** the full 100. The `tpc_phase2_familiar_100_test` 20 records are a held-out overfitting tripwire: touch them only occasionally (e.g. once before a submission), never as a per-change gate. The full `tpc_phase2_familiar_100` split remains only for backward comparison with the pre-2026-07-23 100-record rows — do not start new development rows on it. See [dataset boundaries](../tpc_phase2_eval.md#1-official-familiar-100-development-set-preferred-signal). Run `make phase2-familiar-splits` if the split files are missing.

## What to run — the nightly batched e2e

You are the **gate** end of the [daily-screen / nightly-batched-e2e cadence](../tpc_phase2_eval.md#recommended-cadence-daily-screen-nightly-batched-e2e). Role 3 (and any implementer) fast-**screens** each landed off-by-default flag; the ones that come back green queue up. Your job each cycle is **one** pinned e2e with **all** currently-queued green flags stacked ON, against the **current promoted baseline** (the flags already defaulted-on, same val split) — not one isolated run per flag. If the batch improves `continuous_score` with no new parse failures or timeouts, it is promote-worthy as a set; if it regresses, it does not promote and role 3 bisects with drop-one-out screens. Maintain the promoted-baseline row continuously so the batch always has a fresh, like-for-like comparison.

Confirm the exact queued flags and priority against the live roadmap before spending a long run. As of the current roadmap the leading batch candidate is **`TPC_PIN_TIMED_WINDOWS` + `TPC_SOLVE_CONVERGE_PATIENCE` together**: pin alone gated as quality-up/timeouts-up (PR #34, not promoted); the convergence stop is expected to reclaim the restart budget pin spends, so the *pair* may keep the quality gain without the timeout regression. Screen the pair first, then gate it. Other open gates: the landed parser fixes together, and the commonsense-transport repair — check the roadmap's "Next steps" for current order.

## Commands

Use the pinned targets so the recorded revision is the code that executed. Development gates use the val split (`P2_SPLIT_SET=familiar_100_val`, `FOLD=0 P2_FOLDS=1` selects all 80):

```bash
# Pinned baseline at a specific commit, familiar-100 VAL, two fresh repeats, 300 s local budget.
make phase2-baseline-at SHA=<ref> P2_SPLIT_SET=familiar_100_val \
  FOLD=0 P2_FOLDS=1 P2_BUDGET=300 P2_REPEATS=2 P2_LABEL=<tag>

# Regression gate between two committed rows (continuous_score blocks when present, else FPR;
# more parse failures or timeouts always block).
make phase2-gate BASELINE=results/phase2_baselines/runs/<base>.json \
  CANDIDATE=results/phase2_baselines/runs/<candidate>.json

# Live progress of a running/just-launched baseline (read-only, safe any time).
make phase2-progress FOLD=0 P2_FOLDS=1 P2_REPEATS=2 P2_PROGRESS_ARGS=--watch

# Occasional overfitting tripwire: the current promoted config on the HELD-OUT test split.
make phase2-baseline-at SHA=<ref> P2_SPLIT_SET=familiar_100_test \
  FOLD=0 P2_FOLDS=1 P2_BUDGET=300 P2_REPEATS=2 P2_LABEL=test-tripwire
```

To stack the batch's flags for a run, set each env var (e.g. `TPC_PIN_TIMED_WINDOWS=1 TPC_SOLVE_CONVERGE_PATIENCE=15`). Keep everything else identical between the two rows of a pair — SHA, split, fold/limit, budget, repeats, parallelism, backend/model, and fresh-output policy — or the gate is not like-for-like. The run records resolved flags under `flags`; verify them in the row rather than trusting the label.

## Expectations for a run

- These runs are **long** (roughly `n × budget × repeats` of solver wall-clock, minus parallelism). Median solve currently sits at the budget wall and ~38% of queries time out into recovery — that is expected; the recorder handles it. Launch, then monitor with `phase2-progress` rather than blocking.
- A backend must be reachable for any `llm_parse`-on run (DeepInfra `Qwen/Qwen3.6-27B` per `agent_env/config.toml`). A flags-off / `llm_parse`-off run needs no backend.
- Inspect telemetry, not just the headline: `valid_output_rate`, parse failures, timeout/recovery counts, fallback use, stage timings, and the three attribution axes (ceiling / solver-only / end-to-end).

## Finish — open a PR

Develop on a branch named `claude/phase2-eval-<short-topic>` (create it from the latest `main`). Commit only the generated rows. Then:

1. Rebase on the latest `main` before pushing.
2. Push and open a PR. Structure the body around what you measured: the gate item, the exact command and SHA(s), the resolved flags, the FPR / `continuous_score` / timeout / parse-failure deltas, and the gate verdict (pass/fail with reasons). State plainly that familiar-100 is development-only and not a final-evaluation estimate. Flag any bug you hit for role 3.
3. After opening the PR, wait for GitHub Copilot review comments (poll up to 10 minutes) and address or resolve each one.

Report faithfully: if a gate fails or a run timed out or a backend was unreachable, say so with the evidence. Do not present a familiar-100 or local result as final-evaluation performance.
