# TPC 2026 Phase 2 — Skeleton Harness + Eval Implementation Plan

This document started as the **step-by-step build plan** for the Phase 2 skeleton harness and evaluation
pipeline. The core skeleton is now implemented. It should now be read as a combined build log,
status snapshot, and next-step roadmap for the current Phase 2 agent. Design rationale lives in
`docs/tpc_phase2_design.md`; measurement methodology lives in `docs/tpc_phase2_eval.md`.

## Current status snapshot (2026-07-10)

What is already implemented:

- a dedicated `chinatravel/agent/phase2/` package with `llm_client`, `schema`, `normalize`, `budget`,
  `fallback`, and `orchestrator`
- a Phase 2 runner in `agent_env/scripts/solve_phase2.py`
- rehearsal and measurement scripts in `scripts/rehearse_phase2.py`, `scripts/parser_vs_oracle.py`,
  `scripts/phase2_timing.py`, and `scripts/phase2_gate.py`
- deterministic baseline recorder `scripts/phase2_record_baseline.py` + `make phase2-baseline`
- committed baseline history under `docs/phase2_baselines/` (`history.jsonl`, `history.csv`, latest/run snapshots)
- deterministic no-oracle disjunctive branch expansion behind `TPC_P2_DISJUNCTION`
- a tested injection seam so the harness, not `TPCAgent`, owns parsing and variant selection

What is verified:

- the Phase 2 pytest slice passes: `.venv/bin/python -m pytest tests/phase2 -q`
- the deterministic harness path, fallback path, disjunction wiring, and evaluation tooling are all
  implemented and covered by dedicated tests

**2026-07-10 (later same day) update:** memory fixes landed (see roadmap item below) so fold size
is no longer bounded by in-process memory growth; parser metrics are now measured on the full val
split (n=850) unconditionally in every baseline ledger row, not just on request
(`parser_full_*` columns in `docs/phase2_baselines/history.csv`); `TPC_P2_LLM_PARSE` now defaults
on in `solve_phase2.py` once a backend is configured, gated on a robustness fix that keeps the
deterministic parse on any LLM failure; and the deterministic disjunction detector, a stray-label
regex bug, and a proper-noun/type-keyword collision were fixed, raising full-val behavioral
agreement 0.7565 → 0.7788 with the LLM off. Details in the roadmap items below.

What is still incomplete:

- Stage 1 still mostly wraps `parse_query_no_oracle()`; the richer parser IR exists but most of its
  uncertainty, confidence, and entity-resolution fields are not populated yet
- normalization still does not perform the intended `WorldEnv`-backed entity resolution and validation
- `TPC_P2_LLM_PARSE` now accepts corrective proposals (replace/remove/add), OR-arm recovery proposals,
  and field alternatives/confidence, but remains dependent on deterministic parsing/validation.
  First live probe against DeepInfra Qwen3.6-27B (2026-07-10): 4/8 behavioral disagreements fixed,
  0 regressions, but too conservative in 3/4 unfixed cases (returned no patches)
- `TPC_P2_LLM_REFINE` is still a no-op placeholder
- ~~solver-only baseline stability~~ resolved 2026-07-10: the instability was an n=1-smoke-row +
  stale-resume measurement artifact, fixed in the recorder (fresh runs, smoke labels, `--repeats`
  score variance); see `docs/tpc_phase2_eval.md`

## Review summary (2026-07-10)

The main architectural decision remains correct: **own the Phase 2 harness, keep the deterministic
planner, and improve parsing/orchestration around it**.

The main implementation reality is that the repo now has a real Phase 2 harness surface, but the
largest remaining risk has shifted from "missing harness" to **Stage 1 parser quality on held-out
phrasing**.

Current review findings:

1. The deterministic harness path is real and usable now; Phase 2 is no longer only a paper plan.
2. The parser-side IR and flag structure are in place, but the live path is still dominated by the
   regex-based no-oracle parser.
3. Deterministic disjunction handling is implemented and should stay enabled in production unless a
   run explicitly overrides it.
4. The LLM parse path is now corrective (replace/remove/add) and measurably useful (4/8
   disagreements fixed, 0 regressions in the first DeepInfra probe), but its prompting is still too
   conservative: in most unfixed cases it proposed no patches at all.
5. Operational benchmarking is now in place: fresh-run baseline recording with labels and
   run-to-run score variance, plus a first trustworthy attribution row (`20260710T124113Z`:
   parsing loss 10 FPR pts vs solver headroom 5 at a 60s budget).

## Ground rules

- **Flag-gated evolution.** The original skeleton kept new behavior behind feature flags that default
  OFF. That invariant still holds: deterministic disjunction and parser fixes are implemented, while
  LLM-assisted parse/refine paths remain placeholders until promoted by measurement.
- **Reuse the existing `TPCAgent`** (`chinatravel/agent/tpc_agent/`) in no-oracle mode
  (`TPC_USE_ORACLE=0`). Do not rewrite the planner.
- **Deterministic path byte-identical when all flags are off.** Every task that adds a flag ships a test
  asserting unchanged output when the flag is off.
- **Resumable / cache-friendly**, matching the Phase 1 scripts (skip existing result files, write state to
  disk).

## Test convention (pytest + TDD)

The team adopted **pytest** for the Phase 2 work (installed into `.venv`; declared under
`[project.optional-dependencies].dev` in `pyproject.toml`). The older `scripts/test_solver.py`
self-contained script remains runnable, but new Phase 2 tests use pytest.

- Tests live under `tests/phase2/` (package with `conftest.py`). Run: `.venv/bin/python -m pytest`.
- **TDD loop:** for each step, write the test(s) first and confirm they fail, then implement until
  green, then refactor.
- Config in `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths=["tests"]`,
  `addopts="-q -m 'not integration'"`, and a registered `integration` marker.
- **Integration tests are opt-in.** Slow tests that touch the real `WorldEnv`/`TPCAgent` are marked
  `@pytest.mark.integration` and excluded from the default run; run them with
  `.venv/bin/python -m pytest -m integration`.
- `tests/phase2/conftest.py` provides shared fixtures: `sample_queries`/`sample_uids`/`one_query`,
  `SpyLLMClient`/`spy_llm` (records calls; asserts the deterministic path never calls the LLM),
  `fast_solve_fn` (injectable Stage-2 stub, signature `solve_fn(query, variants, budget_sec) -> plan`),
  and `no_network` (fails loudly on socket use). It also adds `scripts/` and `agent_env/scripts/` to
  `sys.path` so script modules are importable.

The note above describes the original development posture. As of 2026-07-10, Milestones 1–7 below are
implemented; the remaining placeholders are mainly the LLM-assisted parse/refine paths and richer
normalization logic.

## Milestone sequencing and status

- **Milestone 1 (DONE):** pure end-to-end no-oracle skeleton + minimal eval — pytest infra, the
  validation/held-out-test split (`make_phase2_splits.py`), `llm_client`, `schema`, `normalize`,
  `budget`, `fallback`, `orchestrator`, the `solve_phase2` runner, and the basic `rehearse_phase2`
  (fold selection + both modes + three-way attribution).
- **Milestone 2 (DONE):** measurement depth — `parser_vs_oracle.py` (Task 8: structural diff +
  behavioral equivalence), `phase2_timing.py` (Task 9: per-stage p50/p95, budget overruns, variance),
  `phase2_gate.py` + the `make phase2-rehearse` dashboard target (Task 10).
- **Milestone 3 (DONE):** extension points + generalization data — flag-gated improvement stubs
  (Task 11: `llm_parse_stub`, `disjunction_stub`, `llm_refine_stub`, all no-ops, off by default) and
  the HF dataset compare (Task 12: `scripts/compare_hf_dataset.py`). All Phase 2 make targets live in a
  clearly separated `PHASE 2` section of the `Makefile` (`make phase2-help`).
- **Milestone 4 (DONE):** first real improvement behind a flag — true no-oracle **disjunctive branch
  generation** (`TPC_P2_DISJUNCTION`). `parse_to_ir` now deterministically detects OR-groups from NL
  (`detect_disjunctive` / `split_disjunctive_groups` / `parse_single_constraint_text`) and populates
  `ParsedIR.or_groups`; `ir_to_solver_variants` (via `disjunction_stub`) expands them into one
  branch-local solver variant per arm, mirroring the oracle path (strip `_BRANCH_LOCAL_KEYS` from the
  shared base, re-add per-arm facts, normalize through `solver_constraint_variants(use_oracle=False)`).
  The harness became the single parsing owner: `TPCAgent` gained an `_injected_variants` seam and
  `make_tpcagent_solve_fn` injects the (expanded) variants so the agent's existing per-variant loop
  provides OR (accept-any-branch) semantics end-to-end. LLM-assisted arm splitting is **deferred** —
  only a `TODO(phase2, LLM disjunction assist)` marker sits at the split site in `normalize.py`,
  gated on both `TPC_P2_DISJUNCTION` and `TPC_P2_LLM_PARSE` with a deterministic fallback and no
  network on the default path.
  - **Measured (val, first 200):** `disjunction_flattened` 72 → 25 (−65%), precision 0.642 → 0.703,
    F1 0.594 → 0.613, recall ~flat (0.552 → 0.544). The tiny recall dip is a metric artifact:
    `parser_vs_oracle.diff_variants` scores only `parsed_variants[0]`, so a flattened "A and B"
    variant over-populates families and inflates single-branch recall; `disjunction_flattened` is the
    correct structural signal here. Reproduce with `scripts/parser_vs_oracle.py --disjunction`.
  - **Scope reality:** 474/1000 phase-1 queries are oracle-disjunctive; only ~309 are
    *deterministically recoverable* (NL splits into ≥2 arms that each parse to a non-empty
    constraint). The rest have an unparseable arm (e.g. an unlisted attraction name) and stay flat —
    that residual is the deferred LLM-assist territory. Pre-existing per-field no-oracle parser
    inaccuracies (e.g. "do not want restaurants X" mis-mapped) are out of scope for this
    structure-only milestone.
  - **Flags-off invariant:** byte-identical to the prior no-oracle path (enforced by
    `tests/phase2/test_flags.py`, `test_schema_normalize.py`, and `test_disjunction.py`).
- **Milestone 5 (DONE):** deterministic no-oracle **parser-accuracy** fixes (Phase A), driven by a
  per-family val-split diagnosis (`tests/phase2/test_parser_accuracy.py`):
  - **A1** derive `taxi_cars_equals = ceil(people_number/4)` in `parse_query_no_oracle` (the oracle
    always encodes it; the NL rarely states it) — closed the single largest recall sink (449/850
    missing). Also switched `normalize.disjunction_stub` to strip only *arm-claimed* branch-local
    keys, so global constraints (taxi, a one-off budget) survive across OR branches.
  - **A2** negation guard so "do **not** want to try restaurant X" maps to `excluded_restaurants`
    (singular/plural, "the following", "the restaurant:") / `excluded_cuisine_types`
    ("of the type X"), never to `required_restaurants`; dropped the bogus
    `cuisine_preference:'the following'` leak.
  - **A3** budget disambiguation: the intra-city regex's bare `city` alternative no longer matches
    inside "cross-city"/"inter-city"/"intercity", so those no longer duplicate into
    `inner_transport`.
  - **Measured (val, n=850):** recall **0.488 → 0.693** (flat) / **0.466 → 0.677** (disjunction),
    value-accuracy **0.747 → 0.838**, behavioral agreement **0.539 → 0.581** (parsed-verifier now
    accepts 494/850 oracle-valid `results/best` plans, up from 458). `disjunction_flattened`
    essentially unchanged (137 → 139).
  - **Phase-1 oracle regression gate:** on the shared `parse_constraints.py`, the oracle path
    (`parse_query`) changed for 31/850 val queries — **all bogus-field removals** (24
    `required_restaurants`, 12 `cuisine_preference`) plus 1 correct `excluded_restaurants`
    conversion, zero spurious additions. Phase-1 *scoring* uses `hard_logic_py`
    (`evaluate_constraints_py`) independently of the parser, so `results/best` is unaffected; the
    change only makes the oracle *search* heuristic more accurate.
- **Milestone 6 (DONE):** acceptance-gate **OR-awareness** (Phase C). Diagnosis showed the
  behavioral regression in Milestone 5 was a *measurement* artifact: the flat behavioral check ANDs
  OR-arm constraints, so disjunctive queries scored 0.41 agreement vs 0.67 non-disjunctive, and
  `activity_time_windows` caused **0** agree→disagree flips on non-disjunctive queries. The agent
  itself already accepts a plan satisfying *any* branch (`TPCAgent._solve` variant loop), so the fix
  is to make the gate and its metric OR-aware:
  - `parser_vs_oracle.behavioral_check(..., disjunction=True)` now accepts if any
    disjunction-expanded variant passes (wired to the `--disjunction` CLI flag).
  - `agent_env/scripts/solve_phase2.py` enables disjunctive branch generation **by default** (unless
    `TPC_P2_DISJUNCTION` is explicitly set), so the production acceptance gate is OR-correct. The
    library default (`Flags()`) stays off, preserving the byte-identical invariant tests.
  - **Measured (val):** behavioral agreement **0.478 → 0.633** (first 400) / **0.547 → 0.711**
    (n=850) flat → disjunction-aware; `disjunction_flattened` in the report drops 169 → 53. No
    `parse_constraints.py` change, so the Phase-1 oracle gate is untouched.
  - Note: the verifier deliberately still fails a time-window/dwell constraint whose location is
    absent from the plan — that matches the oracle (`any([])` is False), confirmed by the 0 non-
    disjunctive flips, so it is not softened.
- **Milestone 7 (DONE):** branch-aware parsing metric (`scripts/parser_vs_oracle.py`). The default
  `diff_variants` scores only `parsed_variants[0]` vs its best oracle branch, so it is blind to
  branches 2..N — it neither credits a correctly parsed second branch nor penalizes a wrong one.
  Added an opt-in **matched-pair diff** (`diff_variants(..., branch_aware=True)`, CLI
  `--branch-aware`): each oracle branch is greedily matched one-to-one to a distinct parsed branch,
  per-pair family counts are summed (micro-average), unmatched oracle branches are recall misses,
  extra parsed branches are precision misses — subsuming `disjunction_flattened`. The single-branch
  limitation is now documented at the `diff_variants` source. Tests in
  `tests/phase2/test_branch_aware_diff.py`.
  - **Interpretation:** on val (first 400, `--disjunction`) branch-aware vs single-branch is
    precision 0.610 → 0.617, recall 0.713 → 0.683, value-accuracy 0.807 → 0.828. The recall *drop*
    is the honesty gain: single-branch cherry-picked the best branch, while branch-aware also counts
    the poorly-parsed second arms. It is an opt-in so historical single-branch numbers and existing
    tests are unchanged; **behavioral agreement (OR-aware) remains the ground-truth signal**, with
    branch-aware precision/recall as the faster structural diagnostic.

## Eval split task (built in Milestone 1)

`scripts/make_phase2_splits.py` deterministically partitions the 1000 `tpc_phase1` uids into
`tpc_phase2_val.txt` (~850) and a frozen `tpc_phase2_test.txt` (~150), idempotent unless `--force`.
Rehearsal folds are drawn from the validation split only; `rehearse_phase2.py --split-set test`
(with a warning) is required to touch the held-out set. See `docs/tpc_phase2_eval.md`.

## Review and roadmap (2026-07-11)

A full review of the current agent identified the following bottlenecks, in priority order. The
detailed, autonomously implementable plan for closing them is
**`docs/tpc_phase2_sonnet_plan.md`** — that file supersedes the older per-step roadmap sections
below (which remain as build history).

1. **Wasted per-query budget (deterministic, free win).** `budget.py` statically reserves ~28% of
   the post-finalize budget for parse and ~11% for improve, but deterministic parse takes ~1s and
   Stage 3 is a stub; `orchestrator.solve_phase2` passes the static `b.solve_sec` to the solver,
   so at a 900s budget roughly 300s of solve time is thrown away per query (at the 60s dev budget
   the solver gets ~33s of 60). → Plan Step 1: dynamic reallocation behind `TPC_P2_DYNAMIC_BUDGET`.
2. **No LLM request timeout, parse stage not time-boxed.** `llm_client.py` sets no SDK timeout and
   Stage 1 has no deadline enforcement; one hung call (a 116s outlier was observed live) can burn
   most of a query's budget before the solver starts. → Plan Step 2.
3. **The headline LLM-parse gain (behavioral 0.7788 → 0.8694) has never been measured e2e** —
   the only ledger row labeled `llm_parse=true` was the silent-404 artifact (Step 8 below).
   → Plan Step 3 (warm-cache re-run of the fold-0 n=85 baseline with a working backend).
4. **All attribution rows used a 60s dev budget**; the competition budget is ~300–900s. → Plan
   Step 4 (one 300s attribution row; also the decision point for whether Stage 3 refinement stays
   deferred).
5. **Localized parser family gaps** (full-val family stats, LLM-audit run):
   `poi_distance_hotel` never extracted (0 matched / 32 missing); `hotel_amenity` spurious-only
   (22 spurious / 0 matched); `required_hotel_all_types`, `excluded_cuisine_types`, `room_type`,
   `stay_duration` are the other main recall sinks; 111/850 behavioral disagreements remain.
   → Plan Step 5 (TDD family fixes, same recipe as Milestones 5/1c).
6. **LLM-audit recall regression** (0.6977 → 0.6779, concentrated in `poi_distance_hotel` and the
   hotel-type families — the audit removes real constraints). → Plan Step 6 (after Step 5).
7. **SGLang endpoint parity** — the competition LLM is the organizers' SGLang endpoint, not
   DeepInfra; a config preset + smoke script is missing. → Plan Step 7.

Still deliberately deferred: Stage 3 LLM refinement (until Step 4 shows solver headroom
exceeding parsing loss at a realistic budget) and full WorldEnv-backed entity resolution (bigger,
less certain payoff than the targeted family fixes).

## Roadmap From Here (priority order)

> **Superseded 2026-07-11** by the review above and `docs/tpc_phase2_sonnet_plan.md`; kept as
> build history.

### 1. Establish the deterministic baseline on validation folds

Status: **DONE (2026-07-10, first trustworthy row recorded)**.

The implemented rehearsal/eval stack now writes committed baseline history via
`scripts/phase2_record_baseline.py` (and `make phase2-baseline`) into `docs/phase2_baselines/`.

Captured metrics include:

- end-to-end no-oracle score
- solver-only score
- parser-vs-oracle structural and behavioral gaps
- timing, fallback rate, timeout rate, and valid-output rate
- run-to-run score variance across `--repeats`

First trustworthy row (`20260710T124113Z`, fold 0, n=20, 60s, fresh, LLM off): e2e FPR 85.0,
solver-only 95.0, ceiling 100.0; e2e overall_true 85.39 with ~0.09-point run-to-run spread.
Parsing loss (10 FPR pts) is 2x solver headroom (5 pts) already at a 60s budget, and would dominate
even more at the organizer budget.

**Re-baseline after the roadmap-1c + Step-2 changes (`20260710T144747Z`, git_sha 165cd1fa, fold 0,
n=20, 60s, fresh, LLM off):** e2e FPR 85.0, solver-only 95.0, ceiling 100.0 (unchanged);
continuous `overall_true` solver-only 93.28 → 94.04, e2e 85.39 → 85.72; valid-output rate 1.0, no
fallback. The pipeline runs cleanly under the new code with no regression. Note the fold-0 n=20
parser metrics are unchanged (precision 0.525, recall 0.767, behavioral 0.750) **because this seeded
20-query fold contains none of the queries the 1c fixes touched** — the authoritative parser signal
is the full-val (n=850) measurement recorded under roadmap 1c (behavioral agreement 0.706 → 0.757),
which is a far larger sample than any single rehearsal fold. This is exactly the coarseness the
larger-fold recommendation was meant to address.

Larger-fold / 300s rehearsals were attempted (n=30–40, 120s) but the in-process rehearsal
accumulated memory across queries and did not complete locally past ~26 cumulative solves.

**Resolved 2026-07-10** by root-causing (not working around) the leak — see the "Memory fixes"
entry below and `docs/tpc_phase2_eval.md`. `scripts/rehearse_phase2.py` now runs both modes as
chunked subprocesses, so fold size is no longer memory-bounded; a full-fold (n=85) baseline is
tracked as the Step-8 re-baseline below.

### Memory fixes (2026-07-10)

Root-caused, not just worked around, in three parts:

1. `chinatravel/agent/llms.py` imported `transformers`/`vllm` (→ torch, ~600MB) unconditionally at
   module top; `init_llm("TPCLLM")` — on the hot path for every solve, even solver-only, since the
   deterministic orchestrator wires a stub backbone LLM — triggered that import despite Phase 2
   never using a local-model backend. Moved into the local-model classes' (Deepseek/Qwen/Mistral/
   Llama) constructors via lazy `_import_transformers()`/`_import_vllm()` helpers. **Measured:**
   single-uid solver-only solve RSS 898MB → 281MB; torch/vllm/transformers no longer in
   `sys.modules`.
2. Six modules (`hard_constraint.py`, `commonsense_constraint.py`, `preference.py`,
   `evaluation/preference.py`, and the two `nesy_verifier` counterparts) each built their own
   Accommodations/Restaurants/Attractions/... at import time. Added a `LazyTool` proxy
   (`chinatravel/environment/tools/_lazy.py`) deferring construction to first attribute access.
   **Measured:** the real duplication cost on the actual solve path is modest (~10–20MB per
   redundant build, not the several-hundred-MB originally hypothesized — most of the floor is
   pandas/numpy's one-time import cost, not per-instance data), but it's still a real,
   correctness-preserving win (identical scores before/after).
3. A timed-out solve leaves a thread `func_timeout` cannot kill running in the background —
   verified directly (a 6-query run with one timeout left a stray thread alive and RSS elevated
   after the harness moved on). Fixed structurally, not by chasing the leak itself: `solve_phase2.py`
   gained `--uids-file`, and `rehearse_phase2.py` now runs both end-to-end and solver-only as
   chunked subprocesses (`P2_CHUNK` env, default 5; solver-only via a new self-exec
   `--worker solver-only` mode, since it had no standalone script). Whatever a chunk leaks is
   reclaimed by the OS when that chunk's process exits. Also fixed a latent bug this surfaced:
   `rehearse_phase2.py` never put `chinatravel/` on `sys.path`, so `--mode solver-only` run
   standalone (previously it only worked by accident, when end-to-end ran first in the same
   process and added that path as a side effect) crashed with `ModuleNotFoundError`.

Per-query `rss_mb` telemetry (via `psutil`) is now recorded in both loops.

### 1b. Stabilize solver-only rehearsal before attribution decisions

Status: **DONE (2026-07-10)** — root-caused as a measurement artifact, not a solver bug.

All unstable ledger rows were n=1 (or n=4) smoke runs at 20–30s budgets, where a single
near-deadline flake flips FPR between 0 and 100, and end-to-end numbers could additionally be
stale-resume leftovers from older code (rehearsal used `resume=True` into a shared results dir).
Fixes shipped in `scripts/rehearse_phase2.py` (`--fresh`, `clear_method_outputs`) and
`scripts/phase2_record_baseline.py` (fresh by default, `--label` with auto-`smoke` for n<10,
`--repeats` run-to-run score variance recorded as `*_std` history columns). Baseline rows recorded
before 2026-07-10 should not be compared across commits.

### 1c. Deterministic Stage-1 quick wins from the behavioral triage (new, 2026-07-10)

Status: **DONE (2026-07-10).**

The behavioral-disagreement triage on the first 60 val queries (8 disagreements) exposed two cheap,
fully deterministic fixes that landed before more LLM work:

- **Extended the Milestone-5 A2 negation guard to hotels and attractions.** "Do not wish to stay at
  the following hotels: X and Y" previously also emitted a spurious `required_hotels`; a positive
  "visit X" clause followed by "and do not want to visit any Museum.../university campus" previously
  leaked the negated types into `required_attractions`/`required_attraction_types`. Fixed in
  `parse_constraints.py` via two shared helpers — `_negated_before` (negation directly preceding the
  trigger, covers "do not wish to stay ...") and `_truncate_at_negation` (cuts a greedy chunk at a
  following negated-desire clause) — applied to `parse_required_hotels`, `parse_required_attractions`,
  and `parse_required_attraction_types`. Same bug family as the restaurant guard that already shipped.
- **Made the parsed verifier's inner-transport taxi checks mirror the oracle exactly.** Root cause
  (confirmed on all 76 val queries carrying `excluded_inner_transport`): the oracle encodes the
  exclusion by scanning *top-level* activities with `activity_type=='transportation'`, a category the
  plan schema never emits (inner-city rides are embedded `transports` segments), so the oracle clause
  is **vacuously true**. The parsed verifier was instead inspecting embedded segments and rejecting
  taxi-using plans the oracle accepts. `parsed_verifier.py` now (a) computes `excluded_inner_transport`
  from top-level `transportation` activities exactly like the oracle (vacuous in practice), and
  (b) decides taxi-ness for `taxi_cars_equals` via `innercity_transport_type(...)=='taxi'` (the same
  helper the oracle uses), so a taxi-free plan is vacuously accepted. This is acceptance-gate
  correctness, so it also affects which solver plans are kept.

**Measured (val, `parser_vs_oracle.py --behavioral --disjunction`, n=850):** behavioral agreement
**0.706 → 0.757**; first-60 agreement **0.867 → 0.950**; structural precision 0.541 → 0.547, recall
0.698 → 0.698 (flat), F1 0.609 → 0.614, value-accuracy 0.810 (flat), `disjunction_flattened` 137
(unchanged). Zero new false-acceptances (no oracle-reject / parsed-accept flips). Regression tests:
`tests/phase2/test_parser_accuracy.py` (hotel/attraction guards) and
`tests/phase2/test_taxi_verifier_vacuity.py`. No LLM calls.

### Step 8. Representative fold baseline (2026-07-11)

Status: **DONE**, but with a significant correction below — read it before trusting the
`llm_parse`/`llm_backend` columns on run `20260711T000602Z`.

Full fold 0 of val (n=85, not a subset), `TPC_P2_LLM_BACKEND=infradeep make phase2-baseline FOLD=0
P2_FOLDS=10 P2_BUDGET=60 P2_REPEATS=2 P2_LABEL=llmparse-disj-fullfold0-60s`, run `20260711T000602Z`.
Ran ~2h (faster than the ~5.4h estimate).

**Measured:**

```
FPR:          ceiling 100.0 | solver-only 94.12 | end-to-end 85.88  (headroom 5.88, parsing loss 8.24)
overall_true: ceiling 100.0 | solver-only 91.76 | end-to-end 87.40  (headroom 8.24, parsing loss 4.36)
```

- e2e FPR is flat vs the n=20 `20260710T144747Z` baseline (85.0 → 85.88) and *within* this row's own
  repeat-to-repeat noise (`e2e_fpr_std=1.76` across 2 repeats) — not a regression.
- Regression gate (`scripts/phase2_gate.py`) vs `20260710T144747Z`: **passed.** Compared on
  `fpr` (85.0 → 85.88, up), `parse_failures` (0 → 0), and `timeouts` mapped to `budget_overruns`
  (0 → 0) — the gate's literal `timeouts` field is solve-slice `timed_out` in the raw JSON, which we
  deliberately did NOT feed it: baseline is n=20 and this row is n=85, so raw timeout *counts* are
  not comparable across different n, and `timed_out` here is by-design solve-restart-until-budget
  behavior (see "Resolved: in-process rehearsal memory growth" caveats), not a reliability failure —
  `valid_output_rate=1.0` and `used_fallback` counts stayed flat/near-zero in both rows regardless.
- Reliability: valid-output rate 1.0, 0/85 fallback, 0 parse failures, 0 budget overruns.
- This row is a **valid deterministic + disjunction n=85 baseline** and the gate result above holds
  regardless of the correction below (it never depended on the LLM actually running).

**Correction, found while investigating why the row's `parser_full_behavioral_agreement_rate` came
back byte-identical to the pre-LLM number (0.7788):** the row's `llm_parse=true`/
`llm_backend=infradeep` label is **materially misleading**. The infradeep backend's default model
string was broken — `"qwen3.6-27b"` (no org prefix, lowercase) 404s on DeepInfra ("model ... does
not exist"); the correct id is `Qwen/Qwen3.6-27B` (case-sensitive `Org/Name`, verified live). So
every one of the 85 LLM audit calls in this run silently failed and fell back to the deterministic
parse via `parse_to_ir`'s by-design fallback-on-exception (that fallback is correct production
behavior — a flaky backend shouldn't crash the harness — but it also means nothing recorded the
failure anywhere the ledger could see). The `stage_sec.parse` latency (0.47–1.26s, none near-zero)
that was initially read as proof the LLM genuinely ran was, in hindsight, simply the round-trip
time of a *failing* HTTP request — a 404 costs real network latency too, so "non-trivial latency"
cannot distinguish success from failure. Only `scripts/phase2_llm_parse_probe.py` escaped this bug,
because it hardcodes the correct model string directly rather than going through
`build_llm_client(_phase2_llm_config())`'s default.

Fixed in a follow-up commit: corrected `DEFAULT_INFRADEEP_MODEL` in `llm_client.py`, plus a new
`llm_parse_failed` counter (threaded from `ParsedIR.llm_parse_error` through orchestrator telemetry
into `solve_phase2.py`'s run summary and `phase2_timing.py`'s aggregate, surfaced as
`timing_llm_parse_attempted`/`timing_llm_parse_failed` in the baseline ledger) so a broken backend
now shows up as a nonzero count instead of a clean, silently-misleading pass. Regression test:
`tests/phase2/test_llm_client.py::test_infradeep_backend_default_model_is_a_real_deepinfra_id` and
`tests/phase2/test_solve_phase2_runner.py::test_llm_parse_failed_counter_catches_a_broken_backend`.

**What this means for the plan's original question (does LLM-parse fix the parsing bottleneck):**
still unanswered as of this writing — `parser_full_behavioral_agreement_rate` = 0.7788 measures the
deterministic parser only (both because it's LLM-blind by construction, per
`docs/phase2_baselines/README.md`, and because in this specific row the LLM never actually ran
regardless). Re-running Step 8's e2e baseline with a working LLM backend is not the fix: steady-state
DeepInfra latency for this model/prompt turned out to be ~20–35s/call (one 116s outlier observed,
likely a cold queue) — at that rate a full 850-uid audit is ~6–8h, and an e2e rehearsal re-run would
cost even more for a 60s-budget harness that barely benefits from the parse-stage time anyway. The
plan's original "~30–60 min" full-val LLM-parse estimate was implicitly based on the (unknowingly
broken) fast-failing calls, not real generations. The correct, cheaper tool for this measurement is
the solver-free `scripts/parser_vs_oracle.py --llm-parse` on the full val split — see
`docs/tpc_phase2_eval.md` for that measurement once it lands.

### Step 9. Final-agent memory soak (2026-07-11)

Status: **DONE.**

The chunked-subprocess fix (section "Memory fixes" above) only protects rehearsal; the actual
competition runner (`agent_env/scripts/solve_phase2.py`) is a single long-lived process for the
whole split, so it still needed a direct soak test of the real path: `--split tpc_phase2_val
--limit 150 --budget-sec 10 --method phase2_soak`.

**Measured:** RSS 235–262 MB across all 150 queries, first→last delta 8.9 MB, linear-fit slope
0.07 MB/query (≈70 MB extrapolated to 1000 queries) — flat, no monotone growth, well inside the
~500 MB acceptance bar. 128/150 (85%) solves hit `timed_out` (solve-slice exhaustion at the tight
10s budget; all recovered to valid plans) and 2/150 fell back to the schema-valid fallback, so the
`func_timeout` thread-leak concern from the memory-fixes writeup was exercised heavily and still
did not reproduce at this scale in a single process. Added a warn-only `TPC_P2_MAX_RSS_MB` env
guard to `run_split` (prints once a query's RSS grows past the threshold since the process's first
solved query; never aborts) for future longer soaks — silent throughout this run. No escalation
(func_timeout grace tuning, no-func-timeout mode, chunked wrapper for the real runner) was needed.

### 2. Finish Stage 1 normalization before adding refinement

The next highest-leverage code work is in `chinatravel/agent/phase2/normalize.py` and
`chinatravel/agent/phase2/schema.py`:

- populate `confidence`, `entity_candidates`, and other IR fields with real signal
- use `WorldEnv` in normalization for entity resolution and validation
- add explicit low-confidence / ambiguous-parse handling instead of flattening everything into one raw dict

This is more important than Stage 3 refinement because current Phase 2 risk is parsing loss, not
post-solve preference quality.

### 3. Upgrade LLM parsing from additive to corrective

Status: **mechanism DONE, prompting needs iteration (2026-07-10).**

The corrective flow (replace/remove/add patches, OR-arm recovery, field alternatives + confidence)
is implemented and was measured live against DeepInfra Qwen3.6-27B with
`scripts/phase2_llm_parse_probe.py` (solver-free, one LLM call per probed uid):

- 8 behavioral-disagreement uids: **4 fixed, 0 made worse**
- 6 correct-parse control uids: LLM proposed no changes (**0 regressions**)

**Prompt upgraded to a corrective audit (2026-07-10).** `build_llm_parse_prompt` now frames the task
as an explicit *audit* of the deterministic parse rather than optional "refinement": it states the
regex parser is known to over-extract, lists every extracted constraint family, and instructs the
model to (for each family) locate the supporting NL span, check polarity/negation, and emit a
`remove` patch (with `fields=[...]`) when the family is spurious or the wrong polarity — returning an
empty patch list only after auditing all families. Deterministic validation still owns final
authority (the model only proposes patches that are re-parsed and merged).

**Re-measured live (DeepInfra Qwen3.6-27B, `phase2_llm_parse_probe.py --limit 120 --max-probes 5`,
2026-07-10, after the roadmap-1c deterministic fixes):** disagreements **4/5 fixed**, control
**0/5 broke** (all controls left byte-unchanged, `llm_changed_raw=false`) — fix rate up from 4/8 to
4/5 with no regressions. The single unfixed uid (`20250321124345084418`) is a flattened-disjunction
case (it expanded to 2 variants but still failed), confirming the remaining gap is OR-arm recovery,
not family auditing.

**Resolved 2026-07-10 (robustness + default-on + the flagged flattened-disjunction case):**

- **Robustness fix (load-bearing for everything below).** `llm_parse_stub` is documented to raise
  on any failure "so the orchestrator can degrade safely," but nothing actually caught that raise
  near the deterministic `ir` it was meant to protect — the exception propagated out of
  `parse_to_ir`, and `orchestrator.solve_phase2` wraps the whole parse stage in one broad
  try/except that discards `ir` entirely (`variants=[]`) on any exception. A transient LLM hiccup
  (network error, malformed JSON) was therefore indistinguishable from a genuine parse bug and
  forced the query to fallback. Fixed: `parse_to_ir` now catches `llm_parse_stub`'s exception
  itself and keeps the pre-call deterministic `ir`.
- **`CachingLLMClient`** (`chinatravel/agent/phase2/llm_client.py`) wraps openai/infradeep clients
  with an on-disk response cache under `cache/phase2_llm_parse/<model>/<key>.json`, keyed by the
  existing `cache_key` plumbing. Warm evals are free and byte-deterministic (temperature is
  already 0). On by default; `TPC_P2_LLM_CACHE=0` disables it.
- **`llm_parse` now defaults on** in `solve_phase2.py::run_split` once a usable backend is
  configured (mirrors the existing `TPC_P2_DISJUNCTION` default-on pattern), gated on the
  robustness fix above being safe to rely on. `scripts/parser_vs_oracle.py` gained `--llm-parse` so
  this is measurable on the full val split, not just the probe script.
- **The flagged uid (`20250321124345084418`) is now fixed, but not by the LLM.** Investigating it
  found the deterministic disjunction detector never recognized bare "(must/need to) satisfy one of
  the following" phrasing (only "at least one/either/any one of"), missing 6/850 val queries
  entirely. Also found and fixed two more bugs on the same uid while there: a regex that leaked a
  label word ("...the following conditions:") into the first OR arm's text, and
  `parse_excluded_attraction_types` substring-matching a type keyword ("park") inside a proper-noun
  venue name ("Shenzhen Bay Park") that `parse_excluded_attractions` had already correctly captured
  as a specific name. The uid now behaviorally agrees with the oracle via the deterministic path
  alone. `build_llm_parse_prompt` still gained an explicit OR-arm-recovery section + worked example
  (the original ask) as the fallback for phrasing beyond regex reach — the plumbing already existed
  end-to-end (`or_arms` → `_parse_constraint_text` per arm → branch-local solver variants).

**Measured (val n=850, `--behavioral --disjunction --branch-aware`), cumulative over the
Step-5 + Step-7 deterministic fixes:** precision 0.5475 → 0.5577, recall 0.6524 → 0.6526,
behavioral agreement **0.7565 → 0.7788**, `disjunction_flattened` 140 → 134.

The LLM still proposes and never decides; final authority stays with deterministic validation.

**Step 6's own full-val verification, 2026-07-11 (`scripts/parser_vs_oracle.py --split-set val
--behavioral --disjunction --llm-parse`, n=850, `Qwen/Qwen3.6-27B` via DeepInfra, thinking mode
off — see below):** this is the measurement the plan asked for and had not actually been run
before this date (the Step 8 baseline row's `llm_parse=true` label was a silent-fallback artifact,
see that section). Warm-cache rerun byte-identical (fully deterministic at temperature 0).

```
                deterministic-only (post Step 5+7)   LLM corrective audit (this run)
precision:      0.5565                                0.5786
recall:         0.6977                                0.6779
f1:             0.6191                                0.6243
value_accuracy: 0.8072                                0.8270
disjunction_flattened: 134                             80
behavioral_agreement:  0.7788                          0.8694
```

**Behavioral agreement reaches the top of the plan's hoped-for 0.80–0.85 range (0.8694), and
`disjunction_flattened` nearly halves (134 → 80)** — the LLM audit is a genuine, substantial win on
parsing quality once it actually runs (see the thinking-mode fix below for why earlier attempts at
this measurement were impractically slow). Precision, f1, and value_accuracy all improve too.
**Tradeoff: recall drops 0.6977 → 0.6779** (216 → 289 `missing`), concentrated in
`poi_distance_hotel`, `required_hotel_all_types`, and `required_hotel_any_types` per
`family_stats` — the corrective audit trades some recall for a larger precision/behavioral gain
(spurious count drops 649 → 540). Net strongly positive, but worth tracking if recall on those
specific families becomes a problem later.

**Practical blocker found and fixed along the way: Qwen3 "thinking mode."** The model generates a
full chain-of-thought before every answer by default on DeepInfra (verified live: 10.6s/232
completion tokens with thinking vs 1.1s/9 tokens without, for the same trivial prompt) — this made
the first attempt at this measurement (using real audit prompts) run at ~20–45s/call
(one 116s outlier), projecting to ~9h for 850 uids against the plan's ~30–60min estimate. Disabled
via `extra_body: {"chat_template_kwargs": {"enable_thinking": false}}` (the vLLM/SGLang convention
DeepInfra honors), dropping real per-call latency to ~2–10s and the full run to ~100 minutes —
matching the original estimate. Defaults on for the infradeep backend now
(`chinatravel/agent/phase2/llm_client.py`); overridable via config/env if a future use case wants
visible reasoning.

**The genuine e2e re-run (2026-07-11, run `20260711T071751Z`) — the plan's thesis is not confirmed
at a 60s budget; it's contradicted.** Same fold/n/budget as the Step 8 mislabeled row
(`20260711T000602Z`), with a verified-genuine LLM backend
(`timing_llm_parse_attempted=85`, `timing_llm_parse_failed=0`). End-to-end FPR **dropped**
85.88 → 81.18; the regression gate (`scripts/phase2_gate.py`) against the mislabeled row
**FAILED** (`score/fpr dropped: 81.18 < 85.88`). `e2e_fpr_std=0.0` across 2 repeats (same pass/fail
set both times; `overall_true` still varies slightly, ruling out a broken/stuck cache).

The parser-level win (behavioral agreement 0.7788 → 0.8694) measures something different from the
e2e score: whether parsed constraints accept/reject a *fixed* plan like the oracle would, not
whether a *freshly solved* plan under those constraints passes within a bounded time budget. This
run is where the two diverge. Flipped-uid diagnosis (diffing `all_pass_ids` between the two runs;
5 pass→fail, 1 fail→pass): 3/5 pass→fail uids `timed_out=true` (consistent with tighter/more-
correct constraints shrinking the feasible region within 60s, compounded by
`disjunction_flattened` dropping 134 → 80 — ~54 more queries now expand into multiple
solver-searched branches competing for the same slice). But **2/5 did not time out**
(`valid_output=true`, `commonsense_pass=true`, `logical_pass=false`) — ruling out "search
difficulty" as the whole story. Traced one directly (uid `20250322103818184128`): the deterministic
parser had extracted the same NL span twice (`required_attractions` + the redundant
`required_attraction_types`, the exact proper-noun/type-keyword collision pattern from the Step 5
fixes) — a directionally *correct* LLM removal. But CP-SAT runs single-worker
(`num_search_workers=1`, `chinatravel/agent/tpc_agent/cp_solver.py:243`) with a fixed time budget,
and is sensitive to the exact constraint formulation: dropping even a redundant constraint changes
the search trajectory, and within the same wall-clock slice it converged to a *different* plan that
failed a logical check the old (redundant-constraint) run's plan happened to pass.

**Open, not resolved here:** whether this is specific to the 60s dev budget (more search headroom
at the organizer's real ~900s budget might absorb these formulation-sensitivity effects) or a more
fundamental interaction. A 900s re-run would answer this directly — feasible with `--parallel`
(Step 10 below) but still ~15x this run's cost — a decision for the user, not made here. Similarly,
whether `TPC_P2_LLM_PARSE` should remain default-on given a 60s-budget e2e regression, despite the
genuine parsing-quality improvement, is a call about the real competition budget this session
cannot resolve.

### 4. Extend evaluation to score variance, not only valid-output variance

Status: **DONE (2026-07-10)** via `phase2_record_baseline.py --repeats N`, which reruns the fresh
rehearsal N times and records mean/std of end-to-end and solver-only FPR and `overall_true`
(`*_std` columns in `history.csv`). This makes the organizer's average-over-5 execution model
measurable locally. (`phase2_timing.py --repeat-dirs` still only covers valid-output rate; optional.)

### 5. Defer Stage 3 refinement until the parser gap is no longer dominant

`TPC_P2_LLM_REFINE` should remain lower priority than Stage 1 work. Refinement becomes worth doing only
after end-to-end runs show that parser loss has been reduced and solver-only performance is no longer the
main bottleneck.

**Deferral still holds after roadmap 1c + Step 2 (2026-07-10).** Parser loss has been *reduced* (full-val
behavioral agreement 0.706 → 0.757 deterministically, plus 4/5 remaining disagreements fixed by the
corrective LLM audit) but it is not yet clear it has stopped being the dominant Phase-2 loss: the last
trustworthy attribution (fold 0, n=20, 60s) still shows parsing loss (10 FPR pts / 8.3 continuous pts)
larger than solver headroom (5 FPR pts / 6.0 continuous pts). Stage 3 refinement stays deferred until a
larger-fold / 300s end-to-end attribution confirms parser loss is no longer the bottleneck.

## Integration facts (verified while planning)

- `TPCAgent.__init__(**kwargs)` reads env vars: `TPC_USE_ORACLE` (default `1`; set `0` for no-oracle),
  `TPC_MAX_RESTARTS` (400), `TPC_SOLVE_BUDGET_SEC` (120), `TPC_SEED_SALT` (0). Construct with
  `env=WorldEnv(lang=...)`, `backbone_llm=init_llm("TPCLLM")`, `log_dir=...`, `lang=...`.
- `TPCAgent.run(query)` returns `(True, plan)`; `plan` is a dict with `people_number`, `start_city`,
  `target_city`, `itinerary`, and `elapsed_time(sec)`. On internal exception it returns an empty-itinerary
  plan (never raises).
- No-oracle parse: `parse_constraints.parse_query_no_oracle(query)` → flat dict with
  `disjunctive=False`; `solver_constraint_variants(query, raw, use_oracle=False)` → single variant.
  Oracle parse for ground truth: `parse_query(query)` + `solver_constraint_variants(..., use_oracle=True)`.
- No-oracle checker: `parsed_verifier.evaluate_parsed_constraints(constraints, plan, target_city)`.
- Query loading: `chinatravel/data/load_datasets.load_query(args)` where `args` has `splits`, `lang`,
  `oracle_translation`. With `oracle_translation=False` it strips `hard_logic*` fields.
- Official evaluators: `chinatravel/evaluation/{schema_constraint,commonsense_constraint,hard_constraint}.py`
  (already used by `agent_env/scripts/solve_script_with_harness.py::evaluate_one`).
- **Guaranteed-valid fallback:** the output schema (`chinatravel/evaluation/output_schema.json`) requires
  only `people_number`, `start_city`, `target_city`, `itinerary`. An empty `itinerary: []` is
  schema-valid, so the last-resort fallback is a minimal dict with an empty itinerary (passes schema even
  if it fails commonsense/logic — strictly better than a parse-failure zero).

## Feature flags (all default OFF)

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `TPC_P2_LLM_BACKEND` | `none` | `none` / `fixture` / `openai` / `infradeep` |
| `TPC_P2_DISJUNCTION` | `0` | true no-oracle disjunctive branch generation (implemented, Milestone 4) |
| `TPC_P2_LLM_PARSE` | `0` | LLM-assisted second-pass parse (stub) |
| `TPC_P2_LLM_REFINE` | `0` | bounded LLM plan refinement (stub) |
| `TPC_P2_BUDGET_SEC` | per-query timeout | total budget the orchestrator splits across stages |

## Module layout

```
chinatravel/agent/phase2/
  __init__.py
  llm_client.py     # Task 3
  schema.py         # Task 4
  normalize.py      # Task 4
  budget.py         # Task 5
  fallback.py       # Task 5
  orchestrator.py   # Task 5 (+ telemetry in Task 9, stubs in Task 11)
agent_env/scripts/
  solve_phase2.py   # Task 6
scripts/
  rehearse_phase2.py    # Task 7
  parser_vs_oracle.py   # Task 8
  phase2_timing.py      # Task 9
  compare_hf_dataset.py # Task 12
tests/phase2/
  conftest.py           # shared fixtures
  test_*.py             # per-task pytest modules
```

---

## Task 3 — LLM client abstraction

File: `chinatravel/agent/phase2/llm_client.py`

- `class LLMClient` with a uniform method, e.g. `complete(prompt: str, *, system: str | None = None,
  cache_key: str | None = None) -> str`.
- Backends selected by config / `TPC_P2_LLM_BACKEND`:
  - `none`: raises or returns a sentinel if called; the point is it is never called on the default path.
  - `fixture`: reads a cached response from a fixtures dir keyed by `cache_key` (or a hash of the prompt).
    Zero network. Used for dev (hand-produced parses) and tests.
  - `openai`: OpenAI-compatible client (reuse `openai==1.53.0`, already a dependency). Reads
    `base_url` + `api_key_env` from `agent_env/config.toml` (a new `[phase2]`/`[phase2.llm]` section or
    reuse the existing provider shape). OpenRouter is just a base_url/key preset.
- `def build_llm_client(config: dict | None = None) -> LLMClient` factory honoring the flag/config;
  default `none`.

Tests (`tests/phase2/test_llm_client.py`):

- `none` backend is constructible and performs no network.
- `fixture` backend returns the cached content for a known key; missing key raises a clear error.
- `openai` backend builds the request correctly with the HTTP call **mocked** (no live network).

Demo: constructing `none` and `fixture` clients runs with zero network.

---

## Task 4 — Two-layer schema + normalization skeleton

Files: `chinatravel/agent/phase2/schema.py`, `chinatravel/agent/phase2/normalize.py`

- `schema.py`:
  - `@dataclass ParsedIR` — parser-side IR: `variants: list[dict]` (alternative parses), `or_groups`,
    `confidence: dict`, `spans: dict`, `entity_candidates: dict`, `hard_vs_soft` split. All optional with
    sane defaults so a minimal IR is just one variant.
  - `SolverConstraints = dict` (type alias) — the stable solver-facing dict shape TPCAgent already
    consumes.
- `normalize.py`:
  - `def parse_to_ir(query, *, llm_client=None, flags=...) -> ParsedIR` — in the skeleton this wraps
    `parse_constraints.parse_query_no_oracle(query)` and packs it into a single-variant `ParsedIR`
    (LLM/disjunction hooks are no-ops here; see Task 11).
  - `def ir_to_solver_variants(ir, query, *, env=None) -> list[SolverConstraints]` — in the skeleton this
    reproduces exactly what `solver_constraint_variants(query, raw, use_oracle=False)` returns today
    (WorldEnv validation hook present but pass-through).

Tests (`tests/phase2/test_schema_normalize.py`):

- For a sample of `tpc_phase1` queries, `ir_to_solver_variants(parse_to_ir(q), q)` **equals**
  `solver_constraint_variants(q, parse_query_no_oracle(q), use_oracle=False)` (passthrough invariant).

Demo: IR round-trips to the same variants the current parser produces.

---

## Task 5 — Orchestrator skeleton

Files: `chinatravel/agent/phase2/{budget.py,fallback.py,orchestrator.py}`

- `budget.py`: `def split_budget(total_sec: float) -> Budget` with fractions parse/solve/improve/finalize
  (e.g. 0.25 / 0.55 / 0.10 / 0.10) and a hard finalization buffer; helpers to compute per-stage deadlines
  from a start time.
- `fallback.py`: `def fallback_plan(query) -> dict` returning the minimal schema-valid plan
  (`people_number`, `start_city`, `target_city`, `itinerary: []`). Optionally accept a "best-so-far" plan
  and return it if non-empty.
- `orchestrator.py`: `def solve_phase2(query, *, env, llm_client=None, budget_sec=None, flags=...,
  solve_fn=None) -> (plan, telemetry)`:
  1. **Stage 1 (parse):** `normalize.parse_to_ir` → `ir_to_solver_variants`. Time-boxed.
  2. **Stage 2 (solve):** default `solve_fn` drives `TPCAgent` with `TPC_USE_ORACLE=0` and
     `TPC_SOLVE_BUDGET_SEC` set from the solve slice, wrapped in `func_timeout` at the stage deadline.
     Inject `solve_fn` in tests to avoid needing `WorldEnv`.
  3. **Stage 3 (improve):** no-op stub (TPCAgent already densifies internally); flag-gated LLM refine is a
     no-op here (Task 11).
  4. **Stage 4 (finalize):** validate against schema; on empty/invalid/timeout, return `fallback_plan`.
  - Records per-stage timings into `telemetry` (fleshed out in Task 9).

Tests (`tests/phase2/test_orchestrator.py`, plus `test_budget.py` / `test_fallback.py`):

- With an injected fast `solve_fn`, a normal query yields the solver's plan and populated telemetry.
- A `solve_fn` that sleeps past the deadline / raises → finalize returns a schema-valid fallback (never
  raises, never empty-on-crash beyond the schema-valid floor).
- Flags off ⇒ the pipeline calls neither the LLM client nor any stub (assert via a spy client).

Demo: one query in → schema-valid JSON out, no oracle used.

---

## Task 6 — Per-query runner script

File: `agent_env/scripts/solve_phase2.py`

- Mirror `solve_script_with_harness.py` I/O conventions but drive `orchestrator.solve_phase2` instead of
  `opencode`/`codex`.
- Load queries via `load_datasets.load_query` with `oracle_translation=False` (oracle hidden from the
  agent). Keep a separate oracle-visible copy only for the evaluator, never passed into the orchestrator.
- Per query, write: `results/<method>/<uid>.json` (official plan), `evaluation.json` (reuse
  `evaluate_one`), and `prompt`/telemetry artifacts under a run dir.
- `--split`, `--uid`, `--limit`, `--method`, `--resume`, `--budget-sec` flags. Resume-safe (skip existing
  result files). Write a `<split>_summary.json` like the baseline.

Demo: `python agent_env/scripts/solve_phase2.py --split tpc_phase1 --limit 5` produces official result
files + evaluations.

---

## Task 7 — Rehearsal runners (end-to-end + solver-only)

File: `scripts/rehearse_phase2.py`

- One core, two `--mode` values:
  - `end-to-end`: no-oracle pipeline (what Phase 2 scores).
  - `solver-only`: feed **oracle** constraints to the solver (parsing removed) — both **cold / bounded /
    autonomous** at the Phase-2 budget.
- Deterministic seeded **fold** selection (`--fold`, `--folds N`); record the fold membership.
- Aggregate official metrics across the batch; keep per-query rows (for a tail queue).
- Print the three-way attribution: `results/best` ceiling vs solver-only vs end-to-end, plus the
  `opencode`/`codex` floor if available.

Demo: attribution lines for a fold in both modes.

---

## Task 8 — Parsing-quality report (Axis 1)

File: `scripts/parser_vs_oracle.py`

- **Structural diff:** for each query, compute no-oracle variants and oracle variants **in the same solver
  dict schema** (`solver_constraint_variants` with `use_oracle=False` vs `True`); diff per constraint
  family. Emit precision / recall / value-accuracy and buckets: `missing`, `spurious`, `wrong_value`,
  `disjunction_flattened`.
- **Behavioral equivalence (`--behavioral`):** run parsed vs oracle constraints each as a verifier
  (`evaluate_parsed_constraints` / oracle `hard_logic_py`) over a plan set (the `results/best` plan +
  simple perturbations) and flag disagreements.
- Output per-query CSV + aggregate JSON.

Demo: a report showing where score is lost and whether it is a parse or solve issue.

---

## Task 9 — Timing + variance telemetry (Axis 3)

File: `scripts/phase2_timing.py`; orchestrator emits per-stage telemetry (extends Task 5).

- Orchestrator writes per-stage timings (parse/solve/improve/finalize) + valid-output / timeout / crash
  flags into the run artifacts.
- `phase2_timing.py` aggregates p50/p95 per stage, flags budget overruns, and — with `--repeats N` — runs
  N times and reports run-to-run **score variance** (organizers average 5 runs; the LLM adds
  nondeterminism).

Demo: timing + variance summary over a fold.

---

## Task 10 — Iteration dashboard + regression gate

File: `Makefile` target `phase2-rehearse` (+ a small gate helper, e.g. `scripts/phase2_gate.py`).

- `make phase2-rehearse FOLD=<fold>` chains: rehearse (both modes) → official score → parsing report →
  timing/variance → single printed dashboard with the three-way attribution and axis metrics.
- **Regression gate:** reuse `scripts/merge.py`'s monotonic philosophy. A change is promoted only if, on
  the fold, it does not drop official score, increase parse-failure count, or increase timeout/crash
  count. The gate enforces the "flags off ⇒ unchanged" rule.

Demo: one command emits the dashboard; the gate flags a deliberately-broken change.

---

## Task 11 — Wire placeholder improvement hooks (still OFF)

Extend `orchestrator.py` / `normalize.py` with three flag-gated stubs, each a clearly-marked `TODO`:

- (a) `TPC_P2_DISJUNCTION` → real no-oracle disjunctive branch generation in `parse_to_ir` /
  `ir_to_solver_variants`. Stub returns the current single variant.
- (b) `TPC_P2_LLM_PARSE` → LLM-assisted second-pass parse via the Task 3 client. Stub is a no-op.
- (c) `TPC_P2_LLM_REFINE` → bounded LLM plan refinement in Stage 3. Stub is a no-op.

Tests (`tests/phase2/test_flags.py`):

- With all flags off, output and solver variants are **identical** to the deterministic baseline
  (byte-compare on a query sample).
- Toggling each flag routes through its stub without changing results (stubs are no-ops), proving the
  wiring without introducing behavior.

Demo: flags exist and are wired; default-off leaves results unchanged.

---

## Task 12 — Hugging Face dataset check

File: `scripts/compare_hf_dataset.py` + `docs/tpc_phase2_hf_dataset.md` (note already drafted).

- Compare HF `LAMDA-NeSy/ChinaTravel` to local `tpc_phase1`: uid overlap, field presence (esp.
  `hard_logic_py`, `nature_language_en`), city coverage, day/people distributions, constraint-family
  coverage.
- Conclude whether HF `human`/`human1000` can serve as an independent **generalization rehearsal set**
  and note any schema normalization needed to run our evaluators on it.

Demo: a compare report + a documented conclusion.

---

## Suggested build order

3 → 4 → 5 → 6 (vertical slice runs one query end-to-end) → 7 → 8 → 9 → 10 (measurement loop closed) →
11 (extension points) → 12 (generalization data). Run `.venv/bin/python -m pytest` after each
task and keep the deterministic path green. Do not commit unless asked.
