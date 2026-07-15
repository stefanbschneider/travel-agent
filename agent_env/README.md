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

## Interface categories

- **Query:** list splits and load visible query metadata.
- **World facts:** attraction, restaurant, and accommodation search; opening checks; nearby lookup; cuisine and feature lookup.
- **Transport:** in-city `goto`, intercity selection, and POI-coordinate lookup.
- **Raw compatibility:** a constrained `WorldEnv` command interface when no structured call covers the need.

Query loading is fixed to visible mode and defensively strips every top-level `hard_logic*` verifier field.
Raw commands accept only direct calls to allowlisted `WorldEnv` functions with literal arguments or safe one-argument predicates; arbitrary Python is rejected.

For exact tool names, request shapes, semantic itinerary rules, and output constraints, read [SKILL.md](SKILL.md).

## One CLI example

```bash
.venv/bin/python -m agent_env.cli call attractions_keys '{"city":"上海"}'
```

Run `.venv/bin/python -m agent_env.cli tools` to inspect the local tool catalog.

## Server and harness entry points

```bash
# Stdio MCP-style server
.venv/bin/python -m agent_env.mcp_stdio

# Local HTTP service
.venv/bin/python -m agent_env.http_server --host 127.0.0.1 --port 8765

# Repository Phase 2 per-query runner
.venv/bin/python agent_env/scripts/solve_phase2.py --split tpc_phase2_val --limit 1 --budget-sec 300
```

`agent_env/scripts/solve_script_with_harness.py` is the generic OpenCode/Codex compatibility harness; `solve_phase2.py` is this repository's deterministic-orchestrator runner.
Both must hide oracle-only fields before the agent path.

## Outputs

The Phase 2 runner writes the plan to `results/<method>/<uid>.json`.
It writes per-query `evaluation.json` and `telemetry.json` under `agent_env/runs/<method>/<uid>/`, plus `<split>_summary.json` in that method directory.
Use [Phase 2 design](../docs/tpc_phase2_design.md) for the no-oracle architecture and [Phase 2 evaluation](../docs/tpc_phase2_eval.md) for measurement.
