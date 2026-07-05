# TPC 2026 Phase 2 — Skeleton Harness + Eval Implementation Plan

This is the **step-by-step build plan** for the Phase 2 skeleton harness and evaluation pipeline. It is
documentation only; no code has been written yet. Design rationale lives in `docs/tpc_phase2_design.md`;
measurement methodology lives in `docs/tpc_phase2_eval.md`.

## Ground rules

- **Skeleton + placeholders only.** No real parser/solver/LLM improvements yet. New behavior sits behind
  feature flags that default OFF.
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

## Eval split task (built in Milestone 1)

`scripts/make_phase2_splits.py` deterministically partitions the 1000 `tpc_phase1` uids into
`tpc_phase2_val.txt` (~850) and a frozen `tpc_phase2_test.txt` (~150), idempotent unless `--force`.
Rehearsal folds are drawn from the validation split only; `rehearse_phase2.py --split-set test`
(with a warning) is required to touch the held-out set. See `docs/tpc_phase2_eval.md`.

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
| `TPC_P2_DISJUNCTION` | `0` | true no-oracle disjunctive branch generation (stub) |
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
