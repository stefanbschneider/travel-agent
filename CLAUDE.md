# Repository Agent Guidance

Use this file as a routing and invariant document, not as a second runbook.
The human entry point is [README.md](README.md).

## Phase boundary

| Phase | Agent policy |
| --- | --- |
| Phase 1 | Offline work on released data may use released oracle fields locally. Preserve the accepted-plan and monotonic-merge workflow. |
| Phase 2 | The agent path receives visible query text and environment tools only. It must not read, derive from, or retain oracle verifier fields. |

Phase 2 runs in an organizer harness on a held-out set.
The public material does not specify a per-query timeout or repeat count; local `300 s` and `900 s` settings are assumptions, not rules.

## Source of truth

| Topic | Read this |
| --- | --- |
| Project setup and canonical entry | [README.md](README.md) |
| Shared solver architecture | [AGENT_DESIGN.md](AGENT_DESIGN.md) and [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md) |
| Phase 1 operation | [Phase 1 playbook](docs/tpc_phase1_playbook.md) |
| Phase 2 architecture | [Phase 2 design](docs/tpc_phase2_design.md) |
| Phase 2 metrics, gates, and dataset boundaries | [Phase 2 evaluation](docs/tpc_phase2_eval.md) |
| Phase 2 priorities and solver headroom | [Phase 2 roadmap](docs/tpc_phase2_roadmap.md) |
| Competition facts | [Competition reference](docs/reference/competition.md) |
| Agent environment | [Human guide](agent_env/README.md) and [agent contract](agent_env/SKILL.md) |
| Historical decisions and measurements | [Documentation archive](docs/archive/README.md) |

Use `make help` for Phase 1 commands and `make phase2-help` for Phase 2 commands.

## Non-negotiable invariants

- **Acceptance first.** A score, parse, or heuristic is not a valid plan. Retain a candidate only after its applicable logic, schema, and commonsense checks pass.
- **Deterministic grounding.** Query `WorldEnv` for POIs, schedules, prices, accommodations, restaurants, and transport. Do not fabricate values or compensate with plausible text.
- **No oracle leakage.** In Phase 2, remove oracle-only fields before parsing or tool use. Oracle data is evaluation-only local ground truth.
- **Branch-local alternatives.** Keep OR-style constraints separate through normalization, solving, and checking.
- **Flags off is the floor.** Library-default Phase 2 flags must keep the deterministic path and make zero LLM calls. An extension needs a bounded fallback and an explicit measured configuration.
- **Output honestly.** Return only data that meets the schema and semantic contract. Surface a genuine failure rather than inventing an itinerary fact.

## Measurements and ledgers

Promotable Phase 2 evidence is a committed row under `results/phase2_baselines/` produced from a pinned source revision when the run is long.
Compare rows only when data source, split/fold/limit, budget, repeat count, flags, model/backend, parallelism, and fresh-output policy match.
Parser diagnostics prioritize a failure investigation; they do not by themselves promote a change.
Gate a like-for-like end-to-end candidate and inspect parse failures, timeouts, recovery/fallback use, stage telemetry, and LLM failure telemetry.
Familiar-100, local released data, HF data, and final held-out evaluation remain separate signals.

## Change and branch protocol

1. Read the owning document and existing code path before editing.
2. Make a coherent, acceptance-preserving change with focused tests for a new observable contract.
3. Run the relevant test or smoke path before committing.
4. Pull/rebase the shared branch before committing and again before pushing; resolve unexpected changes as user work, never overwrite them.
5. Commit the completed unit of work locally, then push the reviewed branch. Do not create a competing ledger branch.
6. When asked to open a PR, after opening it wait for GitHub Copilot review comments (poll up to 10 minutes), then address or resolve each one before proceeding.

Use Python 3.12 through `.venv/bin/python`.
Do not read, edit, stage, or overwrite `.env`; it is local user configuration.
