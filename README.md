# ChinaTravel TPC 2026 Entry

This repository contains a solver-first travel-planning agent for the [Travel Planning Challenge at IJCAI 2026](https://chinatravel-competition.github.io/IJCAI2026/). It builds grounded, verifier-checked multi-day China itineraries from traveler requests. The shared deterministic solver is used in both competition phases; the trust boundary and delivery model differ.

## Phase boundary

| | Phase 1: public leaderboard | Phase 2: final harness |
| --- | --- | --- |
| Input | Released query set | One visible natural-language query at a time |
| Oracle policy | Offline tooling may use released oracle fields locally | Oracle verifier fields are hidden from the agent |
| Runtime | Local, resumable prediction generation | Organizer-run bounded harness |
| Submission | Prediction zip | Self-contained code, prompts, and scaffolding |
| Evaluation | Public leaderboard | Separate held-out set on Qwen3.6-27B via SGLang on 2 × A800 80 GB GPUs without NVLink |

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

Phase 1 operations are mature. On the familiar-100 development set the parser is now at `~0.99` F1 with zero missing families (the latest step, the comma-in-name entity-resolution segmentation fix, moved F1 `0.9316 -> 0.9908`), so the binding ceiling has shifted from parsing to the solver: with oracle-perfect constraints the solver still passes only `~26/100` (solver-only FPR), dominated by the timed-visit-at-named-POI family. The current flags-on reference is [run `20260721T174336Z`](results/phase2_baselines/runs/20260721T174336Z.json) (mean end-to-end FPR `21.5%`, `overall_true` `45.06`, `300 s` local budget). Timed-window pinning and a within-day resequencer that target the solver ceiling have landed opt-in but are not yet gated. See the [Phase 2 roadmap](docs/tpc_phase2_roadmap.md) for the shortcomings review and prioritized next steps. The official development set has no best plans, so no ceiling is available; it is not the final held-out evaluation set.

## Documentation

- [Phase 1 playbook](docs/tpc_phase1_playbook.md): operating flow and reusable solver lessons.
- [Phase 2 design](docs/tpc_phase2_design.md): stable architecture and interfaces.
- [Phase 2 evaluation](docs/tpc_phase2_eval.md): methodology, metrics, gates, and dataset boundaries (HF, local, familiar-100, final).
- [Phase 2 roadmap](docs/tpc_phase2_roadmap.md): current decisions, evidence-backed priorities, and solver headroom.
- [Parallel agent prompts](docs/agents/README.md): the three-role split (analysis / evaluation / implementation) and the role-2 and role-3 agent prompts.
- [Baseline ledger guide](docs/phase2_baselines/README.md): how to compare generated rows in `results/phase2_baselines/`.
- [Competition reference](docs/reference/competition.md): dated local summary of official facts.
- [Agent design](AGENT_DESIGN.md): shared component and data-flow map.
- [HPC workflows](slurm/README.md): Phase 1 resource profiles and resume behavior.

## Sources

The [competition website](https://chinatravel-competition.github.io/IJCAI2026/) is authoritative for rules and dates. The official [Agent Environment Guide](https://chinatravel-competition.github.io/IJCAI2026/agent-environment.html) defines the wrapper interface, and the [familiar-100 download](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip) is development-only data. Upstream benchmark context is at [LAMDA-NeSy/ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel).
