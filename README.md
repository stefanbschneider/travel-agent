# ChinaTravel TPC 2026 — Phase 2 harness

Team `fabiundstefan`'s entry for the [Travel Planning Challenge at IJCAI
2026](https://chinatravel-competition.github.io/IJCAI2026/), Phase 2.

It is a **deterministic, solver-first travel planner**. From the visible query text alone it builds
grounded multi-day China itineraries and accepts a plan only after the official schema, commonsense
and logical checks pass. Every fact comes from the sandbox `WorldEnv`; nothing is generated as prose.
The submitted path makes **zero LLM calls and zero network calls**, so it needs no model, no API key
and no egress.

This file is the run instruction for the evaluation and ships inside the submission archive; the
archive root also carries a generated `SUBMISSION.md` with the same install-and-run steps.

## Install

Setup only — not part of the timed run. Python 3.12, from this directory:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-submission.txt
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-submission.txt
```

That is the whole installation: **eight PyPI packages**, no extra index, no system packages, no GPU
stack, no model download. `pip install .` and `uv run` resolve the same set (`pyproject.toml`'s core
dependencies mirror `requirements-submission.txt`). The travel database ships in the repository at
`chinatravel/environment/database_en/`, so there is nothing to fetch.

## Run

```bash
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --split <split>
```

With the venv on `PATH`, plain `python agent_env/scripts/solve_script_with_harness.py --split
<split>` is the same thing, and so is `uv run python agent_env/scripts/solve_script_with_harness.py
--split <split>` (both routes verified from the packaged archive).

That single command is the whole system. No other flags are needed, and it is exactly the command
the organizers confirmed for automated evaluation. It:

- loads the split and **strips every oracle verifier field** (`hard_logic*`) before the agent path
  sees a query;
- solves each query with the deterministic `TPCAgent` **in-process** — no subprocess, no external
  CLI, no LLM, no network (`--harness tpc` is the shipped default; `opencode`/`codex` remain
  explicit opt-ins and never run by default);
- defaults language to `en`, whatever the split is named;
- keeps the whole run inside a **5-hour wall-clock envelope**, spending it adaptively across the
  split rather than giving each query a fixed budget;
- writes each plan to `results/phase2_e2e_<split>/<uid>.json`, with per-query telemetry and a split
  summary under `agent_env/runs/phase2_e2e_<split>/`.

A schema-valid plan for every query is written **before the first solve**, and every later result is
kept only if it beats what is already on disk. The run can therefore be interrupted at any instant
and still leaves a complete, non-regressed set of plans.

Optional overrides, none needed for evaluation: `--budget-sec` (per-query cap), `--total-budget-sec`
(whole-run envelope; `0` disables it), `--workers`, `--limit`, `--resume`, `--harness`.

## How the run spends its 5 hours

Every query is weighted equally, so one hard query must not starve the rest of the split. Passes run
across `CPU count - 1` worker processes (a single solve is single-threaded):

1. **triage** — every query once at a small budget, so every query has a real plan early;
2. **repair** — only queries whose plan does not satisfy its constraints, at a growing budget,
   most-nearly-passing first;
3. **polish** — preferences on constraint-satisfying queries with whatever time is left (the
   evaluator zeroes preference terms for a failing query, so they are worth nothing until it passes).

Per query the pipeline is: parse and normalize the visible text into branch-local constraints →
deterministic base build → bounded restarts and repairs (plus an optional CP-SAT tier) →
acceptance-gated packing → finalize with telemetry. Details:
[Phase 2 design](docs/tpc_phase2_design.md).

## Evaluator

`chinatravel/evaluation/`, `chinatravel/symbol_verification/`, `chinatravel/environment/tools/`,
`chinatravel/data/load_datasets.py` and `eval_tpc.py`'s scoring reproduce upstream
[`LAMDA-NeSy/ChinaTravel`](https://github.com/LAMDA-NeSy/ChinaTravel) `main` at `c89cfca`. The only
local deltas there are performance (lazy per-language tool loading) and defensive guards against
malformed plans — never a scoring difference. Score a produced split the usual way:

```bash
.venv/bin/python eval_tpc.py --splits <split> --method phase2_e2e_<split>
```

## Development

For the full development environment (upstream's baseline agents, plotting, the local model stack):
`pip install -r requirements.txt`, then `make help` and `make phase2-help` for the command catalog,
and `.venv/bin/python -m pytest tests` for the test suite. Contributor conventions and invariants are
in [CLAUDE.md](CLAUDE.md).

## More documentation

- [Phase 2 design](docs/tpc_phase2_design.md): no-oracle contract, entry point, whole-run
  scheduling, per-query pipeline, flag policy, outputs.
- [Phase 2 implementation roadmap](docs/tpc_phase2_roadmap.md): the search-space diagnosis, ranked
  open work items, and the landed/closed record.
- [Phase 2 evaluation roadmap](docs/tpc_phase2_eval.md): what a measurement may prove (metrics,
  gates, dataset boundaries) and what to run next.
- [Agent environment guide](agent_env/README.md) and [agent contract](agent_env/SKILL.md): the
  wrapper interface and its setup boundary.
- [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md): planner internals and tuning knobs.
- [Competition reference](docs/reference/competition.md): dated summary of official facts, the
  evaluation host, packaging and the pre-submission checklist.
- [Technical report](report/README.md): the mandatory Phase 2 report and how to build it.
- [Phase 1 playbook](docs/tpc_phase1_playbook.md) and [HPC workflows](slurm/README.md): the Phase 1
  prediction workflow, which shares this solver but not its trust boundary.
- [Documentation archive](docs/archive/README.md): superseded plans and measurement chronology.

The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative for
rules and dates; the [Agent Environment
Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) defines the
wrapper interface.
