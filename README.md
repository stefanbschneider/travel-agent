# Agentic Travel Planning — A Deterministic Approach

Our entry to the [2nd Travel Planning Challenge (TPC) with Agentic AI at IJCAI
2026](https://chinatravel-competition.github.io/IJCAI2026/), built on the
[ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel) benchmark.

🏆 **Competition finalists, awarded the _Special Contribution Award_.**

Given a natural-language request such as *"Plan three days in Suzhou, visit the Humble
Administrator's Garden between 9 and 11, stay near the old town, avoid taxis, and spend at most CNY
3,000"*, the agent produces a complete multi-day
itinerary — intercity transport, hotels, attractions, meals and in-city transfers — that is grounded
in the benchmark's sandbox and checked against its rules.

## Highlights

- **Deterministic and grounded.** Every POI, opening hour, price and timetable comes from the sandbox
  `WorldEnv`; nothing is generated as free text. A plan is emitted only after the official schema,
  commonsense and logical checks pass.
- **Solver-first, zero LLM calls.** The query is parsed into branch-local constraints, then a
  deterministic builder, bounded repair search and an optional CP-SAT (OR-Tools constraint solver)
  tier construct the itinerary. No model, API key or network access is needed. This was a measured
  choice: we evaluated the provided LLM for both parsing and plan repair, and it gave no benefit or
  made results worse (see the report).
- **Anytime and robust.** A schema-valid fallback plan exists for every query before the first solve;
  results only ever replace a plan on disk when they are strictly better, so the run can be stopped at
  any moment.
- **Budget-aware scheduling.** A whole split is solved within one 5-hour wall-clock envelope across
  all CPU cores: *triage* every query quickly, *repair* failing ones, then *polish* preferences.
- **Built by AI agents, steered by humans.** Over eight weeks, coding agents proposed experiments,
  implemented changes, ran evaluations and reviewed pull requests (800+ commits, 1,300+ tests) behind
  a deterministic evaluation harness, while we made the decisions.

## Report and results

- **[Technical report](report/fabiundstefan.pdf)** (4 pages, IJCAI format) — *Agentic Travel
  Planning: Where AI Helped, and Where It Did Not*. Start here for the design, the evidence behind it,
  and our lessons on agent-driven development.
- **Competition results:** 2nd place in Phase 1, 10th place in Phase 2
  ([Phase 1](submissions/Final%20Phase%201%20Leaderboard%20—%20TPC@IJCAI2026.pdf) and
  [Phase 2](submissions/Final%20Phase%202%20Leaderboard%20—%20TPC@IJCAI2026.pdf) leaderboards).
- **Analysis of our Phase 2 gap:** the
  [held-out postmortem](docs/tpc_phase2_eval.md#r38--held-out-postmortem-why-the-improvements-did-not-transfer-closed-2026-09-29-retrospective-only)
  explains why our local improvements did not transfer to the test set.

## Quick start

Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-submission.txt   # 8 PyPI packages, no GPU
```

The travel database ships in `chinatravel/environment/database_en/`, so there is nothing to download.

Solve a split, then score it with the official evaluator (`--method` names the output directory
`results/<method>/` and must match between the two commands):

```bash
# quick check: 3 queries
.venv/bin/python agent_env/scripts/solve_script_with_harness.py \
    --method smoke --split tpc_phase2_familiar_100_val --limit 3
.venv/bin/python eval_tpc.py --splits tpc_phase2_familiar_100_val --method smoke

# the exact competition command (whole split, 5 h envelope)
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --method <method> --split <split>
```

Optional flags: `--budget-sec` (per-query cap), `--total-budget-sec` (whole-run envelope, `0`
disables it), `--workers`, `--limit`, `--resume`. Plans are written to `results/<method>/<uid>.json`,
per-query telemetry to `agent_env/runs/<method>/`.

Bundled splits: `tpc_phase1`, `tpc_phase2_test`, `tpc_phase2_familiar_100` and its `_val` / `_test`
folds. To add one, put one `<uid>.json` per query under `chinatravel/data/en/<name>/` and list the
UIDs in `chinatravel/evaluation/default_splits/<name>.txt`. Queries need only the visible fields
(`uid`, `nature_language`, `start_city`, `target_city`, `days`, `people_number`); oracle verifier
fields are stripped before the agent sees a query.

## How it works

```
query text ─► parse & normalize ─► base build ─► bounded restarts / repair ─► acceptance gate ─► plan
              (branch-local        (grounded in   (+ optional CP-SAT tier)    (schema, common-
               constraints)         WorldEnv)                                  sense, logic)
```

| Entry point | What it is |
| --- | --- |
| [`agent_env/scripts/solve_script_with_harness.py`](agent_env/scripts/solve_script_with_harness.py) | The competition command; dispatches to `solve_phase2.run_split` |
| [`chinatravel/agent/phase2/`](chinatravel/agent/phase2/) | No-oracle parsing, normalization, whole-run sweeps, fallbacks |
| [`chinatravel/agent/tpc_agent/`](chinatravel/agent/tpc_agent/readme.md) | The deterministic planner and its repair search |
| [`eval_tpc.py`](eval_tpc.py) | Official scoring, identical to upstream ChinaTravel |

The evaluator code (`chinatravel/evaluation/`, `chinatravel/symbol_verification/`,
`chinatravel/environment/tools/`, `chinatravel/data/load_datasets.py`) matches upstream
[`LAMDA-NeSy/ChinaTravel`](https://github.com/LAMDA-NeSy/ChinaTravel) at `c89cfca`, with only
performance and defensive changes — never a scoring difference.

## Development

```bash
.venv/bin/python -m pip install -r requirements.txt   # full dev environment
.venv/bin/python -m pytest tests
make help && make phase2-help                          # command catalog
```

## Further documentation

- [Phase 2 design](docs/tpc_phase2_design.md) — architecture, no-oracle contract, scheduling, flags.
- [Evaluation log](docs/tpc_phase2_eval.md) and [implementation roadmap](docs/tpc_phase2_roadmap.md) —
  every measurement and work item, including the held-out postmortem.
- [Competition reference](docs/reference/competition.md) — rules, submission packaging, final
  leaderboard ([PDF](submissions/Final%20Phase%202%20Leaderboard%20—%20TPC@IJCAI2026.pdf)).
- [Agent environment](agent_env/README.md) and [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md).
- [Phase 1 playbook](docs/tpc_phase1_playbook.md) and the [documentation archive](docs/archive/README.md).
- [CLAUDE.md](CLAUDE.md) — conventions for the coding agents that built this repository.

## Authors

[Stefan Schneider](https://github.com/stefanbschneider) and [Fabian Missbrenner](https://github.com/fabufab).
Built on [ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel) by LAMDA-NeSy — please cite their
benchmark if you use this work. Licensed under the [MIT License](LICENSE), like upstream.
