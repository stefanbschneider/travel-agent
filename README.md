# ChinaTravel TPC 2026 Entry

This repository contains a solver-first travel-planning agent for the [Travel Planning Challenge at IJCAI 2026](https://chinatravel-competition.github.io/IJCAI2026/). It builds grounded, verifier-checked multi-day China itineraries from traveler requests. The shared deterministic solver is used in both competition phases; the trust boundary and delivery model differ.

## Phase boundary

| | Phase 1: public leaderboard | Phase 2: final harness |
| --- | --- | --- |
| Input | Released query set | One visible natural-language query at a time |
| Oracle policy | Offline tooling may use released oracle fields locally | Oracle verifier fields are hidden from the agent |
| Runtime | Local, resumable prediction generation | Organizer-run bounded harness |
| Submission | Prediction zip | Self-contained code, prompts, and scaffolding |
| Evaluation | Public leaderboard (to be re-scored on the updated evaluator) | Separate held-out set on Qwen3.6-27B via SGLang on 2 × A800 80 GB GPUs without NVLink; the harness process gets **16 logical CPUs** and 112 GiB host RAM ([confirmed 2026-07-30](docs/reference/competition.md#confirmed-evaluation-host-2026-07-30)) |

## Architecture at a glance

Phase 2 no-oracle execution contract:

- Input to the planning path is visible query text plus allowed environment tools only.
- Oracle verifier fields (`hard_logic*`) are evaluation-only and must be stripped before parsing/solving.
- LLM steps may propose parse/refine edits but cannot authorize facts; all facts are grounded in `WorldEnv` and pass deterministic acceptance checks.

Shared planner flow:

```text
query input
	-> parse + normalize (branch-local variants)
	-> deterministic base build
	-> bounded repairs/restarts (+ optional CP-SAT)
	-> acceptance-gated packing/refinement
	-> finalization + telemetry + output
```

Ownership map:

| Component | Responsibility | Primary source |
| --- | --- | --- |
| Constraint extraction | Convert query/oracle inputs into solver-facing, branch-local constraints | `chinatravel/agent/tpc_agent/solver_constraints.py`, `parse_constraints.py` |
| Deterministic planner | Build, repair, restart, rank, pack, and densify itinerary candidates | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| CP-SAT tier | Construct candidate pools and solve hard residuals | `chinatravel/agent/tpc_agent/cp_candidates.py`, `chinatravel/agent/tpc_agent/cp_solver.py` |
| Acceptance path | Apply parsed/oracle constraints, then schema and commonsense checks | `chinatravel/agent/tpc_agent/parsed_verifier.py`, `chinatravel/agent/tpc_agent/tpc_agent.py` |
| Phase 2 orchestration | Allocate bounded stage budgets, call TPCAgent, finalize output | `chinatravel/agent/phase2/orchestrator.py` |
| Harness boundary | Hide oracle fields, expose tools, and emit official layout | `agent_env/scripts/solve_phase2.py`, `agent_env/` |
| World facts | POIs, schedules, prices, restaurants, hotels, transport | `chinatravel/environment/` and `WorldEnv` |

## Setup

Use Python 3.12 from the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make help
```

The environment database remains a prerequisite for real environment lookups and solves. See the [agent-environment guide](agent_env/README.md) for its setup boundary.

## Canonical workflows

### Phase 1

Run a resumable local solve, merge only accepted improvements, then score the merged result:

```bash
.venv/bin/python scripts/solve.py --split tpc_phase1 --skip --restarts 120 --budget 60 --workers 1
make merge SPLIT=tpc_phase1
make p1eval SPLIT=tpc_phase1
```

Use the [Phase 1 playbook](docs/tpc_phase1_playbook.md) for tail, preference, and HPC profiles.

### Phase 2

Run the no-oracle local harness on a small deterministic validation slice:

```bash
make phase2-solve P2_SPLIT_SET=val P2_BUDGET=300 P2_LIMIT=1
```

`300 s` is a local working assumption, not an organizer timeout. Use `make phase2-help` for recorder, pinned-evaluation, rehearsal, and gate commands.

## Current state

**The evaluator changed on 2026-07-28 and is integrated here as of 2026-07-30** (upstream `LAMDA-NeSy/ChinaTravel` `main` `764614c`, PRs [#29](https://github.com/LAMDA-NeSy/ChinaTravel/pull/29)/[#30](https://github.com/LAMDA-NeSy/ChinaTravel/pull/30)). The organizers confirmed the updated public evaluator is canonical for Phase 2 and that the Phase 1 leaderboard will be re-scored against it. Every score recorded before that date — here or on the leaderboard — is on the old contract. See the [competition reference](docs/reference/competition.md#evaluator-version).

Phase 1: `results/best` scored `100.0` under the old evaluator and scores **`61.16` overall** under the new one (`make p1eval SPLIT=tpc_phase1`: MicEPR `98.17`, MacEPR `58.20`, C-LPR `54.04`, FPR `58.20`, DAV/ATT/DDR `58.20`). Nothing about the plans changed; `418/1000` now fail the new intra-day chronology rule (`344`) or the one-meal-type-per-day rule (`149`). Re-solving those queries is the open Phase 1 work — see the [Phase 1 playbook](docs/tpc_phase1_playbook.md).

Phase 2 is largely unaffected by the stricter checks: a post-sync sanity screen ([`20260730_upstream_eval_sync`](results/phase2_baselines/screens/20260730_upstream_eval_sync/README.md), `familiar_100_val`, `n=20`, `120 s`, LLM off) shows the end-to-end path emitting **zero** commonsense failures, with `overall 54.30` versus `61.10` for the same plans on the old contract — the entire delta is the new preference denominator (DAV/ATT/DDR are now averaged over all queries, so they are bounded by FPR).

Phase 2's promoted configuration was measured pre-sync and needs a fresh baseline. It runs on a promoted `900 s` familiar-100-val baseline with timed-window pinning + converge patience enabled in harness defaults. The latest recorded baseline is [run `20260724T192503Z`](results/phase2_baselines/runs/20260724T192503Z.json): end-to-end FPR `25.0`, solver-only FPR `27.5`, end-to-end `overall_true` `47.04`, solver-only `overall_true` `49.72`, zero parse failures, and zero timeouts/fallbacks.

Since `2026-07-26` a commonsense-first finalization policy (`TPC_COMMONSENSE_FIRST`) is also harness-default-on. The scored C-LPR is conditional on the commonsense checker passing, so an emitted plan that fails commonsense forfeits logical credit the solver already earned. Promoted on a paired same-SHA quick screen (not yet a full `900 s` gate): end-to-end `overall_true` `51.34 -> 60.98`, C-LPR `67.35 -> 89.95`, commonsense pass `30/40 -> 40/40`, FPR `32.5 -> 35.0`, with `logical_micro` unchanged. The parser is no longer the dominant bottleneck; remaining leverage is solver-side and transport/refine roadmap items. See [Phase 2 roadmap](docs/tpc_phase2_roadmap.md) for active priorities.

## Documentation

- [Phase 1 playbook](docs/tpc_phase1_playbook.md): operating flow and reusable solver lessons.
- [Phase 2 evaluation](docs/tpc_phase2_eval.md): methodology, metrics, gates, and dataset boundaries (HF, local, familiar-100, final).
- [Phase 2 roadmap](docs/tpc_phase2_roadmap.md): current decisions, evidence-backed priorities, and solver headroom.
- [Architecture at a glance](README.md#architecture-at-a-glance): no-oracle contract, ownership map, and planner flow.
- [Parallel agent prompts](docs/agents/README.md): concurrent workstreams and currently active focused briefs.
- [Baseline ledger guide](docs/phase2_baselines/README.md): how to compare generated rows in `results/phase2_baselines/`.
- [Competition reference](docs/reference/competition.md): dated local summary of official facts.
- [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md): planner internals and tuning knobs.
- [HPC workflows](slurm/README.md): Phase 1 resource profiles and resume behavior.

## Sources

The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative for rules and dates. The official [Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) defines the wrapper interface, and the [familiar-100 download](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip) is development-only data. Upstream benchmark context is at [LAMDA-NeSy/ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel).
