# Parallel agent prompts

Phase 2 development runs as three concurrent roles (see the [Parallel agent roles](../../CLAUDE.md#parallel-agent-roles) table in `CLAUDE.md`). Each role owns a branch and opens its own PR; none blocks the others.

| Role | Prompt | Model |
| --- | --- | --- |
| 1. Analysis / docs / plan | *(this repository's default agent — keeps the [roadmap](../tpc_phase2_roadmap.md) and [eval doc](../tpc_phase2_eval.md) current)* | — |
| 2. Evaluation (long e2e) | [`role2_evaluation.md`](role2_evaluation.md) | Sonnet 5 |
| 3. Implementation | [`role3_implementation.md`](role3_implementation.md) | Sonnet 5 |

## How to use these

Hand the role-2 and role-3 prompt files to two separate Sonnet 5 agents launched in parallel. Each prompt is self-contained: it names the branch to develop on, the exact commands to run, the invariants to obey, and ends by opening a PR. They take direction from the [roadmap](../tpc_phase2_roadmap.md)'s "Next steps" — role 1 owns that priority order, so re-read it at the start of every run in case `main` has moved.

The division of labor is strict:

- **Role 2 writes only generated rows** under `results/phase2_baselines/`. It never edits agent, parser, solver, or doc prose. Its job is to turn a roadmap gate item into committed evidence.
- **Role 3 writes only code and tests** under `chinatravel/`, `agent_env/`, `tests/`, `scripts/`. It never rewrites roadmap priorities and never claims a promotion — a measurement promotes a change only through the gate that role 2 runs.
- **Role 1 writes only docs** and reconciles both roles' evidence back into the roadmap.

All three obey the [non-negotiable invariants](../../CLAUDE.md#non-negotiable-invariants) and the [change and branch protocol](../../CLAUDE.md#change-and-branch-protocol): rebase on the latest `main` before pushing, and after opening a PR wait for GitHub Copilot review (poll up to 10 minutes) and address or resolve each comment.
