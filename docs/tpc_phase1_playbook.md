# TPC 2026 Phase 1 Playbook

This document covers the **public leaderboard** phase only.

## Objective

Phase 1 is an offline prediction-generation task on the released 1000-query split
`tpc_phase1`. Only prediction files are submitted. We control the runtime, can iterate for
days or weeks, and can optimize directly against the released benchmark data.

## What Phase 1 Gives Us

- Released English queries and split files
- Local access to the official evaluation code
- Oracle constraint fields in the dataset when `--oracle_translation` is enabled
- Unlimited resumable local or HPC reruns before submission

This makes Phase 1 primarily a **per-query optimization problem**.

## Current Strategy

The current Phase 1 system is intentionally solver-first and oracle-guided:

1. Parse released query constraints, including `hard_logic_py`
2. Build one normalized constraint dict per branch when OR-style logic is present
3. Run deterministic TPCAgent search with guided repairs, random restarts, and optional CP-SAT rescue
4. Keep the best accepted plan found within the per-query budget
5. Apply acceptance-gated densification and local preference improvements
6. Monotonically merge only better per-query results into `results/best/`

This is the right design for Phase 1 because it directly optimizes the released hard logic.

## Shared Agent Stack

The core files are:

- `chinatravel/agent/tpc_agent/tpc_agent.py`
- `chinatravel/agent/tpc_agent/solver_constraints.py`
- `chinatravel/agent/tpc_agent/cp_candidates.py`
- `chinatravel/agent/tpc_agent/cp_solver.py`
- `chinatravel/agent/tpc_agent/parsed_verifier.py`

These components also matter for Phase 2, but Phase 1 uses them in **oracle mode** by default.

## Why The Current Approach Works For Phase 1

- Hard constraints dominate the score: FPR, C-LPR, and EPR together account for 85%
- The released dataset makes exact oracle-guided search possible
- Deterministic planning is easier to rerun, cache, merge, and debug than full generative replanning
- Preference lifting is only useful after validity is already strong

## Recommended Phase 1 Workflows

Short local run:

```bash
make short-local
```

Overnight local run:

```bash
make overnight-local
```

Preference-only improvement on already-valid plans:

```bash
make preference-local
```

Focused tail rerun:

```bash
python scripts/rank_tail.py --split tpc_phase1 --method best --top-k 150 --min-score 99
python scripts/solve.py --split tpc_phase1_tail_focus --restarts 1200 --budget 300 --workers 8
python scripts/merge.py --split tpc_phase1_tail_focus
```

Low-level oracle path:

```bash
python run_tpc.py --splits tpc_phase1 --agent TPCAgent --llm TPCLLM --lang en --oracle_translation
python eval_tpc.py --splits tpc_phase1 --method best --lang en
```

## What To Keep Optimizing In Phase 1

1. Preserve hard-constraint performance first
2. Search beyond the first accepted candidate per query
3. Improve DAV, ATT, and DDR only when acceptance is preserved
4. Prioritize the weakest tail queries instead of rerunning the entire set uniformly

## What Transfers To Phase 2

The following ideas transfer well:

- deterministic-first planning
- branch-local constraint handling
- early feasibility filtering
- strict acceptance-gated preference improvement
- resumable, cached workflows
- CP-SAT as a targeted rescue or refinement tier

## What Does Not Transfer Directly

The most important non-transfer is the oracle assumption.

Phase 1 relies on released `hard_logic_py` for direct optimization. Phase 2 does not expose
that information to the agent. That means Phase 2 is not just “run the same solver faster”; it
needs a stronger no-oracle parsing and orchestration layer in front of the same deterministic core.

See `docs/tpc_phase2_design.md` for that setup.