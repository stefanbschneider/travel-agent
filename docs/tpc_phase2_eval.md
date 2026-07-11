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

### Resolved: in-process rehearsal memory growth (2026-07-10)

A larger fold (n=30–40, 120s) previously failed to complete locally past ~26 cumulative solves as
memory accumulated in-process. Root-caused, not just worked around:

1. `chinatravel/agent/llms.py` imported `transformers`/`vllm` (→ torch, ~600MB) unconditionally at
   module top; `init_llm("TPCLLM")` — called for every solve, even solver-only, since the
   deterministic orchestrator wires a stub backbone LLM — triggered that import despite Phase 2
   never using a local-model backend. Fixed by moving the imports into the local-model classes'
   constructors. **Measured:** a single-uid solver-only solve's RSS dropped 898MB → 281MB.
2. A timed-out solve leaves a thread `func_timeout` cannot kill running in the background —
   verified directly (a 6-query run with one timeout left a stray thread alive and elevated RSS
   after the harness moved on).

Fix for (2): `scripts/rehearse_phase2.py` now runs both end-to-end and solver-only rehearsal as
**chunked subprocesses** rather than in one long-lived process (`P2_CHUNK` env var, default 5
uids/subprocess; `--chunk-size 0` reverts to the old single-process behavior for short smoke runs
where subprocess startup overhead would dominate). `agent_env/scripts/solve_phase2.py` gained
`--uids-file` to support this; solver-only mode (which had no standalone script) gained a self-exec
`--worker solver-only --uids-file ...` entry point. Whatever a chunk's process leaks — memory,
threads, anything — is fully reclaimed by the OS when it exits, so fold size is no longer
memory-bounded regardless of root cause. `make phase2-baseline`/`phase2-rehearse` get chunking for
free (their `rehearse()` call sites don't pass `chunk_size`, so the new default applies). Per-query
`rss_mb` (via `psutil`) is now recorded in both loops' telemetry for future soak monitoring.

**Final-agent soak, 2026-07-11.** Chunked subprocesses only cover rehearsal; the actual competition
runner (`agent_env/scripts/solve_phase2.py`) is a single long-lived process for the whole split, so
it needed its own soak: `--split tpc_phase2_val --limit 150 --budget-sec 10 --method phase2_soak`.
RSS stayed flat across all 150 queries (235–262 MB range, 8.9 MB first→last delta, ~0.07 MB/query
linear-fit slope) even with 128/150 queries hitting `timed_out` — the `func_timeout` thread leak
theorized above does not reproduce at this scale in-process. A warn-only `TPC_P2_MAX_RSS_MB` guard
was added to `run_split` for future longer soaks (prints past-threshold growth, never aborts); it
was silent throughout. No escalation beyond the existing telemetry was needed.

### Parser metrics are now always measured on the full val split (2026-07-10)

Fold-scoped parser metrics (`parser_precision` etc. in the ledger) can miss whatever a parser fix
touched if the small seeded fold doesn't happen to contain those uids — this happened for real: full
val behavioral agreement moved 0.706 → 0.757 across the roadmap-1c fixes while an n=20 fold-0
ledger row's `behavioral_agreement_rate` stayed completely flat. `parser_vs_oracle.run_report` is
solver-free (diff-only against cached oracle constraints from `hard_logic_py`) and measured at
~20s for the full 850-uid val split with `--behavioral --disjunction --branch-aware`, so
`scripts/phase2_record_baseline.py` now runs it unconditionally on every row (`parser_full_*`
columns), in addition to the existing fold-scoped `parser_*` columns (kept only for continuity with
pre-2026-07-10 rows). **`parser_full_*` is the row-to-row comparable headline signal going
forward** — see `docs/phase2_baselines/README.md` for the full comparability rules, including that
`llm_backend`/`llm_parse` must match before comparing two rows' numbers.

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

### Full-fold baseline (run `20260711T000602Z`, fold 0, n=85, 60s) — and a discovered `llm_parse` mislabel

```
FPR:          ceiling 100.0 | solver-only 94.12 | end-to-end 85.88  (headroom 5.88, parsing loss 8.24)
overall_true: ceiling 100.0 | solver-only 91.76 | end-to-end 87.40  (headroom 8.24, parsing loss 4.36)
```

- First full-fold row (n=85, not a 20-uid subset). Disjunction assist on by default. e2e FPR is
  flat vs the n=20 baseline above (85.0 → 85.88) and inside this row's own repeat-to-repeat noise
  (`e2e_fpr_std=1.76` across 2 repeats) — no regression.
- **This row's `llm_parse=true`/`llm_backend=infradeep` label is misleading — it is really a
  deterministic+disjunction row.** Root cause: the infradeep backend's default model string was
  broken (`"qwen3.6-27b"`, no org prefix — 404s on DeepInfra; correct id is `Qwen/Qwen3.6-27B`,
  verified live), so every LLM audit call silently failed and fell back to the deterministic parse
  via `parse_to_ir`'s by-design fallback-on-exception. `parser_full_behavioral_agreement_rate` =
  0.7788, byte-identical to the pre-LLM deterministic number, is consistent with this (not, as
  first assumed, evidence that `parser_full` is merely LLM-blind by construction — that gap is
  real too, see `docs/phase2_baselines/README.md`, but it wasn't the operative explanation here).
  The non-trivial `stage_sec.parse` latency (0.47–1.26s) initially read as "the LLM genuinely ran"
  was actually the round-trip time of a *failing* request — indistinguishable from a success by
  latency alone. Fixed in a follow-up commit: correct default model string + a new
  `llm_parse_failed` telemetry counter (`timing_llm_parse_attempted`/`timing_llm_parse_failed` in
  the ledger) so a broken backend surfaces as a nonzero count instead of passing silently.
- Regression gate (`scripts/phase2_gate.py`) vs `20260710T144747Z`: **passed** on `fpr`
  (85.0 → 85.88), `parse_failures` (0 → 0), and `timeouts` mapped to `budget_overruns` (0 → 0).
  Deliberately did not gate on raw solve-slice `timed_out` counts (15 at n=20 vs 73 at n=85): these
  are by-design solve-restart-until-budget events (see above), not failures, and are not
  comparable as raw counts across different n. This gate result is unaffected by the mislabel
  above (it never depended on the LLM actually running).
- **Measuring the real LLM-parse effect turned out to need a different approach than an e2e
  baseline row.** Steady-state DeepInfra latency for this model/prompt is ~20–35s/call (one
  observed outlier at 116s, likely a cold queue), so a full 850-uid audit takes on the order of
  6-8h — the plan's "~30-60 min" estimate was based on the (unknowingly broken) fast-failing calls,
  not real generations, and an e2e rehearsal re-run with a working LLM backend would cost even
  more (8h+) for a 60s-budget harness that barely uses the parse-stage latency anyway. The
  solver-free `scripts/parser_vs_oracle.py --llm-parse` full-val run is the right tool for this
  measurement (see the next section once it lands); a further e2e re-run is not planned unless that
  cheaper measurement shows the LLM meaningfully changes parsing quality.
- Reliability: valid-output rate 1.0, 0/85 fallbacks, 0 parse failures, 0 budget overruns.

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
| Parsing precision/recall + buckets (full val, headline signal) | `python scripts/parser_vs_oracle.py --split-set val --behavioral --disjunction --branch-aware` |
| Behavioral equivalence | `python scripts/parser_vs_oracle.py --split-set val --behavioral` |
| Per-family loss attribution (top spurious/missing families + example uids) | same as above; read the `family_stats` field of the JSON output |
| Same, with the LLM corrective audit applied | add `--llm-parse` (uses `TPC_P2_LLM_BACKEND`/`agent_env/config.toml`; responses cached by default) |
| Per-stage timing p50/p95 + reliability | `python scripts/phase2_timing.py --work-dir agent_env/runs/<method>` |
| Run-to-run valid-output-rate variance | `python scripts/phase2_timing.py --work-dir <run> --repeat-dirs <run2> <run3> ...` |
| Run-to-run score variance (FPR + overall_true) | `python scripts/phase2_record_baseline.py ... --repeats <N>` (recorded as `*_std` columns) |
| LLM-parse fix/regression probe (no solver, 1 LLM call per uid) | `python scripts/phase2_llm_parse_probe.py --limit 60 --max-probes 8` |
| Regression gate | `python scripts/phase2_gate.py --baseline <base.json> --candidate <cand.json>` |
| Full dashboard | `make phase2-rehearse FOLD=<i> P2_FOLDS=<n> P2_BUDGET=900` |
| Deterministic baseline ledger entry (full-val parser metrics always included) | `make phase2-baseline FOLD=<i> P2_FOLDS=<n> P2_BUDGET=<sec> P2_LIMIT=<n> P2_REPEATS=<r> P2_LABEL=<tag>` |
| Baseline tracker (direct) | `python scripts/phase2_record_baseline.py --split-set val --fold <i> --folds <n> --budget-sec <sec> [--limit <n>] [--repeats <r>] [--label <tag>]` |
| Rehearsal chunk size (memory isolation; default 5) | env `P2_CHUNK=<n>` or `rehearse_phase2.py --chunk-size <n>` (`0` = old single-process behavior) |

Milestones 1 and 2 built `rehearse_phase2.py` (fold selection, both modes, three-way attribution),
the `solve_phase2.py` runner, `parser_vs_oracle.py` (Axis 1), `phase2_timing.py` (Axis 3),
`phase2_gate.py`, and the `make phase2-rehearse` dashboard. The flag-gated improvement stubs and the
HF dataset compare are Milestone 3 (see `docs/tpc_phase2_implementation_plan.md`).

Baseline tracking automation (`scripts/phase2_record_baseline.py`, `make phase2-baseline`) was added
after Milestone 7 to close roadmap Step 1 (establish deterministic baseline with committed history).
