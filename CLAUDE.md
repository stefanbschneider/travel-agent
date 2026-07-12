# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Our competition entry for the **Travel Planning Challenge (TPC) @ IJCAI 2026**, built on top of the
upstream ChinaTravel benchmark (a Chinese travel-planning agent benchmark). It plans multi-day trips
that must satisfy hard logical constraints (budget, must-visit POIs, transport types, hotel/room
requirements) plus commonsense/schema validity, then optimizes soft preference scores.

There are **two competition phases with different execution models** — understanding which one you're
working on is the single most important piece of context:

- **Phase 1** — offline, oracle-guided. The released oracle constraints (`hard_logic_py`) are
  available locally and the search runs for as long as it wants. Goal: maximize the public
  leaderboard score on `results/best`. Driven by `run_tpc.py`/`eval_tpc.py` and the `scripts/` search
  loop; entry via `make` targets like `p1eval`, `merge`, `score`, `submission`.
- **Phase 2** — the final organizer-run harness. Per-query, held-out queries, **oracle fields hidden
  from the agent**, bounded per-query timeout, fixed Qwen3.6-27B model. This is **not a new planning
  problem** — it is a **no-oracle parsing + orchestration** problem wrapped around the *same*
  deterministic solver. Most active development is here.

Authoritative docs, read these before non-trivial work:
- `AGENT_DESIGN.md` — the shared deterministic planning core (`TPCAgent`)
- `docs/tpc_phase1_playbook.md` — Phase 1 strategy/workflows
- `docs/tpc_phase2_design.md` — **Phase 2 design (authoritative)**; module layout, feature flags, execution model
- `docs/tpc_phase2_eval.md` — Phase 2 evaluation methodology (the three measurement axes, attribution, regression gate)
- `docs/tpc_phase2_sonnet_plan.md` / `_plan2.md` — the current prioritized improvement plans

## Environment / running commands

- Python **3.12**; use the venv interpreter directly: **`.venv/bin/python`** (the `Makefile`'s
  `PYTHON` var already prefers it). Don't assume a global `python`.
- Solvers: CP-SAT (`ortools`) and `z3-solver`. Heavy ML deps (`torch`/`vllm`/`transformers`) exist for
  local-LLM backbones but are **lazily imported** — Phase 2's deterministic path never loads them.
- `.env` holds API keys/config; `.env.example` documents the shape.

## Tests

Config lives in `pyproject.toml` (`[tool.pytest.ini_options]`). Default run **excludes** the
`integration` marker (slower tests that touch `WorldEnv` / the real solver).

```bash
.venv/bin/python -m pytest tests/phase2            # fast unit suite (no solver/LLM)
.venv/bin/python -m pytest -m integration tests/phase2   # opt-in slower tests
.venv/bin/python -m pytest tests/phase2/test_orchestrator.py::test_name   # single test
make phase2-test                                   # runs the unit suite
```

The suite defends the core Phase 2 invariant (see `tests/phase2/conftest.py`): a `SpyLLMClient`
asserts the deterministic path **never touches the LLM** when flags are off, and `no_network`
monkeypatches sockets to fail loudly. **`.venv/bin/python -m pytest` must be green before every
commit.**

## Phase 2 workflow commands

The LLM is **off by default**, so none of these make API calls. Suggested order: tests → parser
report → small e2e solve → rehearsal → timing/gate. All Phase 2 targets are under `make phase2-help`.

```bash
make phase2-splits                                 # one-time: create val/test split files (idempotent)
.venv/bin/python scripts/parser_vs_oracle.py --split-set val --behavioral --disjunction --branch-aware
                                                   # Axis 1: parser-vs-oracle report (~20s, no solver) — the fast loop
.venv/bin/python scripts/run_query.py --uid <id> --budget-sec 60     # run ONE query e2e (uid / --query-file / --query-text)
make phase2-rehearse FOLD=0 P2_FOLDS=10 P2_BUDGET=300   # full dashboard: 3-way attribution + parser report + timing
make phase2-gate BASELINE=<base.json> CANDIDATE=<cand.json>   # monotonic regression gate
```

Baseline ledger (committed trend history under `docs/phase2_baselines/`):
- `make phase2-baseline ...` — record a deterministic baseline row (`--repeats` for score variance,
  `--label` to tag).
- `make phase2-baseline-at SHA=<ref> ...` — **preferred for long evals**: runs against a pinned
  `git worktree` checkout so the main tree stays free and the row's `git_sha` is truthful. The old
  code-freeze rule is retired in favor of this.

## Architecture

### Deterministic core (`TPCAgent`, shared by both phases)
`chinatravel/agent/tpc_agent/` — a per-query, constraint-first search, **not** an LLM loop:
1. **Constraint extraction + variants** — one normalized constraint dict per OR branch (`solver_constraints.py`)
2. **Acceptance checker** — base is oracle `hard_logic_py` (Phase 1) or the no-oracle `parsed_verifier.py`
   (Phase 2); gated by schema + commonsense once base passes
3. **Multi-tier search** — base build → guided repair → random restarts → optional CP-SAT rescue
   (`cp_candidates.py`, `cp_solver.py`). **CP-SAT uses a single worker** — bounded-time search is
   sensitive to the exact constraint formulation handed to it.
4. **Constraint-safe preference packing** — densify only while acceptance stays true; monotonic best-of

Key principles: optimize the *exact* acceptance criterion (not a proxy); all POI/price/schedule/
transport data comes from `WorldEnv` (never fabricated); OR-constraints are solved **branch-locally**.
Behavior is controlled by env vars read by `TPCAgent`: `TPC_MAX_RESTARTS`, `TPC_SOLVE_BUDGET_SEC`,
`TPC_SEED_SALT`, and crucially **`TPC_USE_ORACLE`** (`0` = the Phase-2 no-oracle path).

### Phase 2 harness (`chinatravel/agent/phase2/`)
Our harness **owns the control loop** and calls the LLM only for targeted subproblems (LLM
*proposes*, deterministic code *validates* against `WorldEnv`). Stages 1–4 in `orchestrator.py`:
Stage 1 hybrid parse → IR → `normalize.py` → branch-local variants → Stage 2 deterministic `TPCAgent`
→ Stage 3 gated improvement (stub) → Stage 4 finalize (**always returns a schema-valid plan before
timeout**, never a bare parse-failure zero). Supporting modules: `llm_client.py` (backends
`none`/`fixture`/`openai`/`infradeep`), `schema.py`, `budget.py`, `fallback.py`.

**Iron rule: the deterministic path must be byte-identical when all LLM/improvement flags are off.**
Feature flags (all default OFF in the library `Flags()`; see the table in `docs/tpc_phase2_design.md`):
`TPC_P2_LLM_BACKEND`, `TPC_P2_DISJUNCTION`, `TPC_P2_LLM_PARSE`, `TPC_P2_LLM_REFINE`,
`TPC_P2_DYNAMIC_BUDGET`, `TPC_P2_BUDGET_SEC`. Note several default **ON inside `solve_phase2.py::run_split`**
(the runner) once a backend is configured, mirroring the `TPC_P2_DISJUNCTION` pattern — the library
default and the runner default differ deliberately.

### Runners / entry points
- `agent_env/scripts/solve_phase2.py` — the real per-query Phase 2 runner (single long-lived process,
  oracle hidden, official output layout, resume-safe). This is the actual competition path.
- `scripts/run_query.py` — run one query (uid / file / raw NL); reports estimated score always, plus
  official score + parsing-vs-solving breakdown when an oracle is present.
- `scripts/rehearse_phase2.py` — rehearsal in `end-to-end` and `solver-only` modes, **as chunked
  subprocesses** (`P2_CHUNK`, default 5) so a timed-out solve's leaked `func_timeout` thread is
  reclaimed at chunk exit — fold size is no longer memory-bounded.
- `run_tpc.py` / `eval_tpc.py`, `run_exp.py` / `eval_exp.py` — upstream Phase 1 / benchmark runners.
- New agents/LLMs are registered in `chinatravel/agent/load_model.py` (`init_agent`/`init_llm`).

### Data & evaluation
- Query data: `chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/*.json` (each has visible NL + oracle
  `hard_logic_py`/`hard_logic_nl`, which Phase 2 hides). Splits: `chinatravel/evaluation/default_splits/*.txt`.
- `parse_constraints.py` (repo root, large) — the deterministic no-oracle NL→constraints regex parser;
  `parse_query_no_oracle()` is the live Stage-1 entry point and the main Phase-2 robustness bottleneck.
- Scoring: cascading gate — Schema → Commonsense (Mic/Mac.EPR) → C-LPR → **FPR** (all three, highest
  weight) → preference (DAV/ATT/DDR). `eval_tpc.py`/`scripts/score.py` report both `overall`
  (leaderboard formula, double-counts Mic.EPR) and `overall_official`. **FPR is the primary Phase-2
  metric.**

### Phase 2 measurement model (three anchors)
```
results/best (oracle, unlimited + manual help)  = aspirational ceiling
   gap = solver headroom lost to the time budget
solver-only (oracle constraints, bounded)       = achievable in-harness solver ceiling
   gap = parsing loss
end-to-end (no-oracle, bounded)                 = what Phase 2 actually scores
```
Current standing: parsing loss dominates solver headroom, so **Stage 1 parsing quality is the
priority**, not the solver. `parser_vs_oracle.py`'s **behavioral agreement** on the full 850-uid val
split is the fast, solver-free headline signal for parser changes.

## Working conventions (important)

- **Branch:** work on `stefan/phase2`. Commit per completed plan step (`phase2(plan2 step N): ...`)
  and push after each step. **Never create or push a `phase2-eval-ledger` branch** — that's the eval
  VM's job.
- **Two-VM operating model.** This coding machine runs development, tests, and **short** checks only
  (solver-free parser reports ~20s, tiny `--limit`/`--budget-sec` integration smokes, differential
  eval). **Do NOT run long e2e evals here** (a full-fold 300s row is ~7.5h); those belong on the
  separate eval VM. The user explicitly asked to avoid long evaluations on this machine.
- **Eval-speed switches are eval-tooling-only** (e.g. `--fast-fpr`/`TPC_SOLVE_STOP_AT_ACCEPT`,
  `phase2_diff_eval.py`): default off in the library *and* in `run_split`, never affecting the
  organizers' harness path. Metrics they produce are uncalibrated — never gate-compare them against
  normal rows.
- **"Measured, not just tested."** For a step whose value is a trustworthy speedup, a passing unit
  test is not enough — run the real small-scale measured acceptance check (e.g. byte-equality against a
  full run). Byte-equality claims only hold when flags/budget are identical and only parser-layer files
  changed between the compared commits — verify this explicitly.
- **Measurement hygiene:** an LLM parse-call's latency cannot distinguish "call succeeded" from "call
  failed over the network" — always confirm `llm_parse_attempted`/`llm_parse_failed` telemetry, not
  timing, when claiming the LLM ran. Compare ledger rows only when `llm_backend`/`llm_parse`/budget
  match; pre-2026-07-10 rows are not cross-commit comparable.
