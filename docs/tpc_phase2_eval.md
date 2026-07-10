# TPC 2026 Phase 2 Evaluation

This document defines how we **measure and iterate** on the Phase 2 harness described in
`docs/tpc_phase2_design.md`. It is the methodology reference; the scripts that implement it are listed
per metric.

## Current measurement status (2026-07-10, second pass)

The measurement stack itself now exists:

- `scripts/rehearse_phase2.py` for end-to-end vs solver-only rehearsal (`--fresh` clears the fold's
  stale end-to-end results first)
- `scripts/parser_vs_oracle.py` for structural and behavioral parser diagnostics
- `scripts/phase2_timing.py` for per-stage timing and reliability aggregation
- `scripts/phase2_gate.py` for regression checks
- `scripts/phase2_record_baseline.py` for deterministic baseline snapshots and longitudinal tracking
  (now with `--repeats` score variance, `--label` tagging, and fresh-run semantics by default)
- `scripts/phase2_llm_parse_probe.py` for a cheap, solver-free measurement of the corrective LLM
  parse (fixes vs regressions on behavioral-disagreement uids; one LLM call per probed uid)

Committed tracking artifacts now exist under `docs/phase2_baselines/`:

- `history.jsonl` (append-only per-run records)
- `history.csv` (tabular projection for comparisons)
- `latest.json` / `latest.md` (most recent baseline snapshot)
- `runs/<run_id>.json` (immutable per-run snapshots)

Raw per-query outputs remain intentionally uncommitted under `agent_env/runs/` and `results/`.
The committed baseline ledger is the source of truth for trend tracking in git.

### Resolved: the "solver-only instability" was a measurement artifact

The early ledger entries that showed `solver_only_fpr` flipping between 0 and 100 across identical
configs were all **n=1 smoke runs at 20–30s budgets**. Two compounding artifacts explained them:

1. **Stale-resume contamination.** The rehearsal ran end-to-end with `resume=True` into a shared
   `results/phase2_e2e_*` directory, so a "baseline" row could silently reuse plans produced by
   older code or a different budget (visible in history: identical e2e scores across different
   commits). Solver-only always recomputed, so the two modes in one row did not even have the same
   semantics.
2. **n=1 boundary flakes.** At a 20–30s budget the solve loop runs right up to its slice; a single
   near-deadline flake flips a one-query FPR between 0 and 100.

Both are addressed: the recorder now clears fold results before running (fresh by default;
`--reuse-existing` to opt out), auto-labels `n < 10` rows as `smoke`, and measures run-to-run score
variance directly via `--repeats` (recorded as `*_std` columns in `history.csv`). See
`docs/phase2_baselines/README.md` for row-comparison rules. Pre-2026-07-10 ledger rows should not be
used for cross-commit comparison.

Remaining tooling gap (minor): `scripts/phase2_timing.py --repeat-dirs` still reports variance only
for valid-output rate; headline score variance is now covered by the recorder's `--repeats`, so the
timing-script extension is optional.

### First trustworthy baseline (run `20260710T124113Z`, fold 0, n=20, 60s, LLM off)

```
FPR:          ceiling 100.0 | solver-only 95.0  | end-to-end 85.0   (headroom 5.0,  parsing loss 10.0)
overall_true: ceiling 100.0 | solver-only 93.28 | end-to-end 85.39  (headroom 6.72, parsing loss 7.89)
```

- Parser on this fold: precision 0.525, recall 0.767, value-accuracy 0.867, behavioral agreement
  0.75 — precision (spurious constraint families) is the dominant loss, consistent with the
  behavioral triage in `docs/tpc_phase2_design.md`.
- Run-to-run e2e `overall_true` spread across two fresh repeats of the same fold/budget: **0.09
  points** (85.2955 vs 85.3893) — the deterministic path is effectively stable; the organizers'
  5-run averaging is not a risk while the LLM is off.
- Reliability: valid-output rate 1.0, zero fallbacks. The high "timed_out" counts (16/20 e2e,
  19/20 solver-only) are solve-slice-exhaustion events that recovered to valid plans — by design,
  since the solve loop restarts until its slice ends; they are not failures.
- Caveat: 60s is a development budget; at the organizer budget (~900s) solver headroom should
  shrink further, making parsing loss even more dominant. Rerun with a larger budget/fold before
  drawing final attribution conclusions.
- Operational note: long-running background recorder invocations were killed twice by the
  execution sandbox during this session (not a repo bug); the recorded run itself completed all
  writes. If a run dies mid-way, the per-uid result dirs survive and the aggregation can be
  replayed from disk.

## Guiding Idea

We hold the released oracle (`hard_logic_py`) **locally** for the 1000 Phase-1 queries. Phase 2 hides
it from the agent, but we can still use it as **ground truth** to score a no-oracle run and to attribute
failures. This gives a held-out-style signal without an actual held-out set.

Two anchors bound every measurement:

- **Ceiling:** oracle `results/best` (near-optimal, but reached with unlimited iteration and some
  manually/LLM-solved plans — an aspiration, not an in-harness baseline).
- **Floor:** the generic `opencode`/`codex` baseline harness (prompt-only agent).

Our no-oracle system should climb from the floor toward the ceiling; the remaining gap to the ceiling is
our parsing + orchestration loss.

## Three Measurement Axes

### Axis 1 — Parsing quality (parsed constraints vs oracle)

Goal: how faithfully does Stage 1 recover the true constraints from natural language? Two complementary
methods, both reusing existing code:

1. **Structural diff in a shared schema.** Oracle mode already normalizes `hard_logic_py` into the
   solver dict via `solver_constraint_variants(use_oracle=True)`. Run the no-oracle parser into the
   *same* schema and diff field-by-field. Report **precision / recall / value-accuracy per constraint
   family**, with buckets:
   - `missing` — a real constraint was not extracted (recall miss),
   - `spurious` — a constraint was invented (precision miss / hallucination),
   - `wrong_value` — extracted but with the wrong value,
   - `disjunction_flattened` — an OR-group was collapsed into a single flat variant.
2. **Behavioral equivalence.** Use the parsed constraints and the oracle constraints each as a verifier
   over a plan set (the oracle-optimal `results/best` plan plus a few perturbations) and check they
   accept/reject **identically**. Catches semantic errors the structural diff misses.

Script: `scripts/parser_vs_oracle.py` → per-query and aggregate report (CSV + JSON).

### Axis 2 — Solver quality, decoupled from parsing

Goal: given the *correct* constraints, does the solver consistently produce valid plans **inside the
harness budget, autonomously**? Feed the **oracle** constraints to the solver (parsing out of the
picture) but run in **cold / bounded / autonomous** mode: single run, Phase-2 per-query budget, no
manual help, no multi-day iteration.

This is deliberately distinct from `results/best`, which used tools we will not have at inference time.

Attribution decomposition (computed across the full batch/folds):

```
results/best (oracle, unlimited + manual help)        = aspirational ceiling
   gap = solver headroom lost to the time budget
solver-only (oracle constraints, bounded, autonomous) = achievable in-harness solver ceiling
   gap = parsing loss
end-to-end (no-oracle, bounded, autonomous)           = what Phase 2 actually scores
```

Reading the gaps:

- **end-to-end far below solver-only** → invest in the parser (Axis 1).
- **solver-only far below results/best** → the solver is not robust/fast enough on its own; work on the
  solver independent of parsing.

"Must consistently solve **all** queries" becomes concrete: **solver-only FPR should approach 100%**
before parser work is even in scope. Always aggregate across the full batch/folds, but keep per-query
rows so we can rebuild a tail-focus queue like Phase 1 (`scripts/rank_tail.py`).

Script: `scripts/rehearse_phase2.py` with two modes (`--mode end-to-end`, `--mode solver-only`) sharing
one core, both cold/bounded/autonomous at the Phase-2 budget.

### Axis 3 — Harness / pipeline reliability

Goal: does the harness reliably return a valid answer on time, run after run?

Metrics:

- **valid-output rate** — fraction of queries returning a schema-valid plan (never a parse-failure zero
  when avoidable),
- **timeout rate** and **crash rate**,
- **per-stage timing** p50/p95 (parse / solve / improve / finalize) vs the budget split,
- **run-to-run score variance** across N repeats. The organizers run each harness **5× and average**,
  and the LLM (when enabled) introduces nondeterminism, so variance is a first-class metric.

Script: `scripts/phase2_timing.py` (timing + reliability today; score-variance extension still needed),
fed by per-stage telemetry the orchestrator emits.

## Validation vs Held-Out Test Split

The 1000 `tpc_phase1` queries are partitioned **once, deterministically** into two split files under
`chinatravel/evaluation/default_splits/` by `scripts/make_phase2_splits.py`
(seed `20260705`, idempotent unless `--force`):

- `tpc_phase2_val.txt` — **validation** (~850 queries): used to iterate and improve the agent.
- `tpc_phase2_test.txt` — **held-out test** (~150 queries): frozen; used sparingly, only as a final
  overfitting check.

Discipline (enforced by `scripts/rehearse_phase2.py`):

- **Rehearsal folds are drawn from the validation split only** by default (`--split-set val`). Fold
  selection is deterministic (seeded shuffle → disjoint, covering contiguous chunks via
  `select_fold`), so runs are reproducible and cover all of validation across folds.
- Touching the test split requires the explicit `--split-set test`, which prints a warning. Score on
  it rarely (e.g. right before a submission) so we do not overfit to it via repeated peeking.
- `make_phase2_splits.py` refuses to overwrite existing split files without `--force`, keeping the
  held-out set stable once created.

(Seeded random split for now; stratification by constraint-family/difficulty signature is a later
improvement.)

## Rehearsal Folds vs Full Regression Set

- **Rehearsal folds:** rotating subsets of the **validation** split used during iteration, so we do not
  overfit the parser to queries we hand-tuned on. Fold selection is deterministic (seeded) and recorded.
- **Full regression set:** all 850 validation queries (or all 1000 `tpc_phase1`), scored less
  frequently as a broader check.
- **Held-out test set:** `tpc_phase2_test.txt`, scored only sparingly (final overfitting check).
- **Generalization set (candidate):** the Hugging Face `LAMDA-NeSy/ChinaTravel` dataset, if it contains
  queries/phrasings beyond the released split (see `docs/tpc_phase2_hf_dataset.md` and Task 12). Held-out
  phrasing is the exact Phase-2 risk, so an independent generalization set is valuable.

## Baselines To Track

| Baseline | How | Role |
| -------- | --- | ---- |
| `results/best` (oracle) | existing Phase-1 best | ceiling |
| solver-only (oracle, bounded) | `rehearse_phase2.py --mode solver-only` | achievable solver ceiling |
| end-to-end (no-oracle, bounded) | `rehearse_phase2.py --mode end-to-end` | what Phase 2 scores |
| `opencode`/`codex` baseline | `agent_env/scripts/solve_script_with_harness.py` | floor |

Additionally, every rehearsal snapshot promoted for comparison should be recorded via
`scripts/phase2_record_baseline.py` so attribution metrics are versioned in git.

## Iteration Dashboard And Regression Gate

- **Dashboard:** `make phase2-rehearse` chains rehearse → official score → parsing report → timing/variance
  into one report over the current fold, printing the three-way attribution and the axis metrics.
- **Regression gate:** reuse the monotonic philosophy of `scripts/merge.py`. A change is only promoted if,
  on the rehearsal fold, it does **not**:
  - drop official score,
  - increase parse-failure count,
  - increase timeout/crash count.

  The gate makes the "flags off ⇒ deterministic path unchanged" rule enforceable and lets us add each
  improvement (disjunction expansion, LLM parse, LLM refine) and immediately see its measured effect.

## Metric → Command Map

| Metric | Command |
| ------ | ------- |
| End-to-end official score (no-oracle, bounded) | `python scripts/rehearse_phase2.py --mode end-to-end --fold <i> --folds <n>` |
| Solver-only official score (oracle, bounded) | `python scripts/rehearse_phase2.py --mode solver-only --fold <i> --folds <n>` |
| Three-way attribution | `python scripts/rehearse_phase2.py --mode both --fold <i> --folds <n>` (prints ceiling/solver/end-to-end) |
| Held-out test (sparingly) | add `--split-set test` to any rehearse command |
| Parsing precision/recall + buckets | `python scripts/parser_vs_oracle.py --split-set val` |
| Behavioral equivalence | `python scripts/parser_vs_oracle.py --split-set val --behavioral` |
| Per-stage timing p50/p95 + reliability | `python scripts/phase2_timing.py --work-dir agent_env/runs/<method>` |
| Run-to-run valid-output-rate variance | `python scripts/phase2_timing.py --work-dir <run> --repeat-dirs <run2> <run3> ...` |
| Run-to-run score variance (FPR + overall_true) | `python scripts/phase2_record_baseline.py ... --repeats <N>` (recorded as `*_std` columns) |
| LLM-parse fix/regression probe (no solver, 1 LLM call per uid) | `python scripts/phase2_llm_parse_probe.py --limit 60 --max-probes 8` |
| Regression gate | `python scripts/phase2_gate.py --baseline <base.json> --candidate <cand.json>` |
| Full dashboard | `make phase2-rehearse FOLD=<i> P2_FOLDS=<n> P2_BUDGET=900` |
| Deterministic baseline ledger entry | `make phase2-baseline FOLD=<i> P2_FOLDS=<n> P2_BUDGET=<sec> P2_LIMIT=<n> P2_REPEATS=<r> P2_LABEL=<tag>` |
| Baseline tracker (direct) | `python scripts/phase2_record_baseline.py --split-set val --fold <i> --folds <n> --budget-sec <sec> [--limit <n>] [--repeats <r>] [--label <tag>]` |

Milestones 1 and 2 built `rehearse_phase2.py` (fold selection, both modes, three-way attribution),
the `solve_phase2.py` runner, `parser_vs_oracle.py` (Axis 1), `phase2_timing.py` (Axis 3),
`phase2_gate.py`, and the `make phase2-rehearse` dashboard. The flag-gated improvement stubs and the
HF dataset compare are Milestone 3 (see `docs/tpc_phase2_implementation_plan.md`).

Baseline tracking automation (`scripts/phase2_record_baseline.py`, `make phase2-baseline`) was added
after Milestone 7 to close roadmap Step 1 (establish deterministic baseline with committed history).
