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
- deterministic no-oracle disjunctive branch expansion behind `TPC_P2_DISJUNCTION`
- a tested injection seam so the harness, not `TPCAgent`, owns parsing and variant selection

What is verified:

- the Phase 2 pytest slice passes: `.venv/bin/python -m pytest tests/phase2 -q`
- the deterministic harness path, fallback path, disjunction wiring, and evaluation tooling are all
  implemented and covered by dedicated tests

What is still incomplete:

- Stage 1 still mostly wraps `parse_query_no_oracle()`; the richer parser IR exists but most of its
  uncertainty, confidence, and entity-resolution fields are not populated yet
- normalization still does not perform the intended `WorldEnv`-backed entity resolution and validation
- `TPC_P2_LLM_PARSE` is still an additive second-pass stub, not a robust corrective parser
- `TPC_P2_LLM_REFINE` is still a no-op placeholder
- no checked-in rehearsal run artifacts currently exist under `agent_env/runs/` or `results/phase2_*`

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
4. The current LLM parse path is too conservative to repair many real held-out failures, because it
   mostly adds missing detail instead of correcting wrong extracted values.
5. Evaluation coverage is solid for functionality, but operational benchmarking is still missing:
   the repo has scripts for rehearsal and timing, yet no committed Phase 2 run outputs.

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

## Roadmap From Here (priority order)

### 1. Establish the deterministic baseline on validation folds

Before adding new behavior, run the implemented rehearsal/eval stack on `tpc_phase2_val` and capture:

- end-to-end no-oracle score
- solver-only score
- parser-vs-oracle structural and behavioral gaps
- timing, fallback rate, timeout rate, and valid-output rate

This is the immediate next step because there are currently no checked-in Phase 2 run artifacts. Until
those numbers exist, roadmap decisions remain partly qualitative.

### 2. Finish Stage 1 normalization before adding refinement

The next highest-leverage code work is in `chinatravel/agent/phase2/normalize.py` and
`chinatravel/agent/phase2/schema.py`:

- populate `confidence`, `entity_candidates`, and other IR fields with real signal
- use `WorldEnv` in normalization for entity resolution and validation
- add explicit low-confidence / ambiguous-parse handling instead of flattening everything into one raw dict

This is more important than Stage 3 refinement because current Phase 2 risk is parsing loss, not
post-solve preference quality.

### 3. Upgrade LLM parsing from additive to corrective

The current `llm_parse_stub` shape is a good safety-first starting point, but the next version needs to
be able to:

- repair wrong extracted values, not only add missing ones
- propose OR-arm recovery when deterministic splitting fails
- emit field-level alternatives or confidence so deterministic normalization can choose safely

The LLM should still propose and never decide; final authority stays with deterministic validation.

### 4. Extend evaluation to score variance, not only valid-output variance

The docs correctly treat 5-run variance as important, but `scripts/phase2_timing.py` currently reports
variance only for valid-output rate across repeat runs. Extend this to report variance for at least:

- FPR
- `overall_true`
- optionally `overall_parsed`

This makes the organizer's average-over-5 execution model measurable locally.

### 5. Defer Stage 3 refinement until the parser gap is no longer dominant

`TPC_P2_LLM_REFINE` should remain lower priority than Stage 1 work. Refinement becomes worth doing only
after end-to-end runs show that parser loss has been reduced and solver-only performance is no longer the
main bottleneck.

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
| `TPC_P2_LLM_BACKEND` | `none` | `none` / `fixture` / `openai` |
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
