# ChinaTravel Agent Environment

`agent_env` exposes the existing ChinaTravel environment to external agents without changing the benchmark package.
The benchmark and the [official Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) remain authoritative.

## Prerequisites

Use the repository interpreter and install the project dependencies:

```bash
.venv/bin/python -m pip install -r requirements.txt
# Install the official database at chinatravel/environment/database/.
```

The wrapper can start without the database, but any environment lookup or real solve needs it.
Copy `agent_env/config.toml.example` to the ignored local `agent_env/config.toml` only when a harness or model backend needs configuration.
For the Phase 2 parser/refinement endpoint specifically, see `agent_env/config.phase2.example.toml` for a tracked OpenAI-compatible SGLang example; copy that `[phase2.llm]` block into your local `agent_env/config.toml` when you want a reachable endpoint, and note that endpoint autodetect still leaves `TPC_P2_LLM_PARSE` off unless you explicitly set it to `1`.

## Interface categories

- **Query:** list splits and load visible query metadata.
- **World facts:** attraction, restaurant, and accommodation search; opening checks; nearby lookup; cuisine and feature lookup.
- **Transport:** in-city `goto`, intercity selection, and POI-coordinate lookup.
- **Raw compatibility:** a constrained `WorldEnv` command interface when no structured call covers the need.

Query loading is fixed to visible mode and defensively strips every top-level `hard_logic*` verifier field.
Raw commands accept only direct calls to allowlisted `WorldEnv` functions with literal arguments or safe one-argument predicates; arbitrary Python is rejected.

For exact tool names, request shapes, semantic itinerary rules, and output constraints, read [SKILL.md](SKILL.md).

## Language

Every entry point takes a `zh`/`en` language that selects both the sandbox database and the query
set. **The TPC competition data is English.** The defaults differ by entry point, so be explicit:

| Entry point | Default | How to set it |
| --- | --- | --- |
| `agent_env.cli`, `agent_env.http_server` | `zh` | `--lang en`, or `CHINATRAVEL_LANG=en` |
| `agent_env.mcp_stdio` | `zh` | `CHINATRAVEL_LANG=en` |
| `solve_script_with_harness.py` | **`en`** | `--lang zh`, or `[run].lang` in `config.toml` |
| `solve_phase2.py` | **`en`** | `--lang zh` |

The harness script passes its own `--lang` down into the prompt's CLI examples, so a harnessed agent
queries the same database the evaluator scores against.

## One CLI example

```bash
.venv/bin/python -m agent_env.cli --lang en call attractions_keys '{"city":"Shanghai"}'
```

Run `.venv/bin/python -m agent_env.cli --lang en tools` to inspect the local tool catalog.

## Server and harness entry points

```bash
# Stdio MCP-style server
CHINATRAVEL_LANG=en .venv/bin/python -m agent_env.mcp_stdio

# Local HTTP service
.venv/bin/python -m agent_env.http_server --lang en --host 127.0.0.1 --port 8765

# Repository Phase 2 per-query runner
.venv/bin/python agent_env/scripts/solve_phase2.py --split tpc_phase2_val --limit 1 --budget-sec 300
```

```bash
# The organizer-confirmed Phase 2 evaluation command
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --split <split>
```

**`agent_env/scripts/solve_script_with_harness.py --split <split>` is the organizer-confirmed Phase 2
evaluation command** (2026-08-04 direct reply, no other flags — see the
[competition reference](../docs/reference/competition.md#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply)).
A second same-day email restates the command without showing `--split`; `--split` has always been
optional here (default `split="easy"`, `lang="en"`), so both invocation shapes run identically — see
the [wording-discrepancy note](../docs/reference/competition.md#harness-resubmission-and-the-confirmed-llm-endpoint-2026-08-04-second-organizer-email).
Bare, it runs `--harness tpc`: this repository's deterministic no-oracle solver, in-process, via
`solve_phase2.run_split`. Zero LLM calls, zero network calls, no subprocess. The external-CLI
harnesses are still there for the LLM-agent baseline comparison, but only on an explicit
`--harness opencode` / `--harness codex`, never by default.

| Harness | What it runs | When |
| --- | --- | --- |
| `tpc` (default) | deterministic `TPCAgent`, in-process | the submission; every bare invocation |
| `opencode` / `codex` | an external agent CLI against an external LLM API | opt-in baseline comparison only |

The `tpc` harness schedules the whole split against the confirmed **5-hour wall-clock envelope**
instead of giving each query a fixed budget (`chinatravel/agent/phase2/sweeps.py`):

1. **triage** every query once at a small budget (`120 s` cap), so cheap wins are banked first and
   every query has a real plan early;
2. **repair** the queries whose plan does not satisfy its constraints, at a larger budget each
   pass, most-nearly-passing first;
3. **polish** preference terms on constraint-satisfying queries with the time left — the evaluator
   zeroes preferences for a failing query, so they are worth nothing before this point.

Passes run across `CPU count - 1` worker processes (`--workers`, `TPC_P2_WORKERS`), each result is
scored oracle-free (`chinatravel/agent/phase2/selfscore.py`) and written only if it beats the plan
already on disk, and a schema-valid fallback for every query is written **before** the first solve.
A run killed at any instant therefore still leaves a complete, non-regressed set of plans. The
clock starts at interpreter start, so the database load counts against the envelope.

Override with `--total-budget-sec` (or `TPC_P2_TOTAL_BUDGET_SEC`; `0` disables the envelope and
falls back to a fixed per-query budget), `--budget-sec` (the per-query cap), `--workers`, and the
pass-shape variables in
[the Phase 2 design doc](../docs/tpc_phase2_design.md#run-shape).
It writes the same official layout as `solve_phase2.py` and shares its
`results/phase2_e2e_<split>/` method directory, so the two entry points build on each other.

Both entry points hide oracle-only fields before the agent path.

## Outputs

The Phase 2 runner writes the plan to `results/<method>/<uid>.json`.
It writes per-query `evaluation.json` and `telemetry.json` under `agent_env/runs/<method>/<uid>/`, plus `<split>_summary.json` in that method directory.
Use the [Phase 2 design doc](../docs/tpc_phase2_design.md) for the no-oracle architecture and the [Phase 2 evaluation roadmap](../docs/tpc_phase2_eval.md) for measurement.
