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

## Parallel workstreams

Phase 2 development is split across concurrent workstreams. Each workstream uses its own branch and opens its own PR; none blocks the others.

| Workstream | Job | Writes | Must not |
| --- | --- | --- | --- |
| **Analysis / docs / plan** | Review status, shortcomings, and options; keep the roadmap and eval docs current with the latest `main`. | `docs/tpc_phase2_*.md`, `CLAUDE.md`, `README.md`. | Change agent/solver behavior, or run long e2e itself. |
| **Evaluation** | Run long pinned e2e / solver-only baselines on a separate machine and commit the resulting rows. Non-blocking and long-running. | `results/phase2_baselines/` (generated rows only). | Edit agent, parser, solver, or doc prose. |
| **Implementation** | Implement the next improvement from the roadmap's "Next steps", with focused tests. | `chinatravel/`, `agent_env/`, `tests/`, `scripts/`. | Rewrite roadmap priorities or promote a row (that is the gate's job). |

Shared rules for every workstream: obey the [non-negotiable invariants](#non-negotiable-invariants) and the [change and branch protocol](#change-and-branch-protocol); rebase on the latest `main` before pushing; a measurement promotes a change only through the gate, never by assertion alone. Priority order is maintained in the roadmap, and focused prompts live in [`docs/agents/`](docs/agents/).

## Source of truth

| Topic | Read this |
| --- | --- |
| Project setup and canonical entry | [README.md](README.md) |
| Shared solver architecture | [README architecture snapshot](README.md#architecture-at-a-glance) and [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md) |
| Phase 1 operation | [Phase 1 playbook](docs/tpc_phase1_playbook.md) |
| Phase 2 architecture | [README architecture snapshot](README.md#architecture-at-a-glance) and [Phase 2 roadmap](docs/tpc_phase2_roadmap.md) |
| Phase 2 metrics, gates, dataset boundaries, and the fast pre-gate A/B screen + cadence | [Phase 2 evaluation](docs/tpc_phase2_eval.md) |
| Phase 2 priorities and solver headroom | [Phase 2 roadmap](docs/tpc_phase2_roadmap.md) |
| Cross-phase open shortcomings and the implementation plan for each | [Shortcomings and plan](docs/tpc_shortcomings_and_plan.md) |
| Parallel-agent focused prompts (evaluation and implementation) | [Agent prompts](docs/agents/README.md) |
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
- **Upstream evaluator parity.** `chinatravel/evaluation/`, `chinatravel/symbol_verification/`, `eval_tpc.py`'s scoring and `chinatravel/data/load_datasets.py` must reproduce `LAMDA-NeSy/ChinaTravel` `main` exactly (parity point: `764614c`, 2026-07-28, integrated 2026-07-30). Local additions there are limited to performance (lazy per-language tools) and defensive guards on malformed plans; never a scoring difference, and never a private "patched" score. Re-sync upstream before trusting a number.

## Measurements and ledgers

Promotable Phase 2 evidence is a committed row under `results/phase2_baselines/` produced from a pinned source revision when the run is long.
Compare rows only when data source, split/fold/limit, budget, repeat count, flags, model/backend, parallelism, fresh-output policy, and evaluator contract match; rows straddling the 2026-07-28 upstream evaluator change are never comparable.
Parser diagnostics prioritize a failure investigation; they do not by themselves promote a change.
Gate a like-for-like end-to-end candidate and inspect parse failures, timeouts, recovery/fallback use, stage telemetry, and LLM failure telemetry.
Familiar-100, local released data, HF data, and final held-out evaluation remain separate signals.
Familiar-100 is split 80/20 into `tpc_phase2_familiar_100_val` (screens + development gates) and a held-out `tpc_phase2_familiar_100_test` (occasional overfitting tripwire, never a per-change signal); `make phase2-familiar-splits` regenerates them and the [eval doc](docs/tpc_phase2_eval.md#1-official-familiar-100-development-set-preferred-signal) states the boundary.

## Change and branch protocol

1. Read the owning document and existing code path before editing.
2. Make a coherent, acceptance-preserving change with focused tests for a new observable contract.
3. Run the relevant test or smoke path before committing.
4. Pull/rebase the shared branch before committing and again before pushing; resolve unexpected changes as user work, never overwrite them.
5. Commit the completed unit of work locally, then push the reviewed branch. Do not create a competing ledger branch.
6. When asked to open a PR, after opening it wait for GitHub Copilot review comments (poll up to 10 minutes), then address or resolve each one before proceeding.

Use Python 3.12 through `.venv/bin/python`.
Do not read, edit, stage, or overwrite `.env`; it is local user configuration. To run an LLM-backed
path (e.g. a `--mode end-to-end` [quick screen](docs/tpc_phase2_eval.md#llm-backed-flags-tpc_p2_llm_parse-tpc_p2_llm_refine)
of `TPC_P2_LLM_PARSE` / `TPC_P2_LLM_REFINE`), do **not** source or echo `.env`: set
`TPC_P2_LLM_BACKEND=deepinfra` and the code's `build_llm_client` → `load_local_env()` loads
`DEEPINFRA_API_KEY` from `.env` into the process itself. On a reduced screen budget also set
`TPC_P2_LLM_TIMEOUT_SEC` below the parse/improve slice (`6` at a `90 s` budget) or the LLM stage
silently no-ops; confirm the `flag=on` arm's telemetry shows the call fired before trusting the result.
