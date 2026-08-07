# Repository Agent Guidance

Use this file as a routing and invariant document, not as a second runbook.
The human entry point is [README.md](README.md).

## Phase boundary

| Phase | Agent policy |
| --- | --- |
| Phase 1 | Offline work on released data may use released oracle fields locally. Preserve the accepted-plan and monotonic-merge workflow. |
| Phase 2 | The agent path receives visible query text and environment tools only. It must not read, derive from, or retain oracle verifier fields. |

Phase 2 runs in an organizer harness on a held-out set, invoked automatically from the package root as
exactly `python agent_env/scripts/solve_script_with_harness.py --method <method> --split <split>` —
no other flags (2026-08-06 clarification; the earlier wording omitted `--method`). Both values are
the organizers', so **neither the split, the query list, the query count, nor the method name may be
hard-coded**, and every plan must land at `results/<method>/<uid>.json`. All harness-specific
init/launch logic must be integrated behind that one command. Held-out queries carry **no**
`hard_logic`, `hard_logic.py`, `hard_logic_py`, `hard_logic_nl`, or any other DSL / constraint-code /
ground-truth / verifier-only field — code may treat those fields as absent, never as required.
There is no per-query timeout: the organizers confirmed (2026-08-04) a single 5-hour wall-clock budget
for the entire 100-query run, excluding setup. At most two submitted versions are evaluated per team
(higher score wins if both succeed). Local `300 s`/`900 s` settings remain per-query development gate
budgets for solver A/Bs, never a description of what the submission does: the shipped run schedules the
whole split against the 5-hour envelope (`chinatravel/agent/phase2/sweeps.py` — triage, then repair,
then polish, in parallel, keep-best, fallbacks pre-written), and `make phase2-full-run` is the
measurement that matches it. See the [competition reference](docs/reference/competition.md#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply)
for the full confirmed contract. That command now runs the repository's real deterministic solver:
its default `--harness tpc` dispatches in-process to `solve_phase2.run_split` (zero LLM calls, zero
subprocesses), and the run is bounded by the 5-hour envelope rather than a fixed per-query budget
(roadmap item 0a, closed 2026-08-04). Install for that path is `requirements-submission.txt`, and
`scripts/assemble_phase2_submission.py` packages and verifies the archive.
**Submission status (2026-08-06): `v1` is uploaded and its held-out score came back at `33.2473`.**
The archive (`submissions/phase2/fabiundstefan_v1.zip`, built from `be196d00`, tagged `phase2-v1`) was
the team's first official submission under the 2026-08-04 resubmission reset, so **one slot (`v2`)
remains**, due with the technical report on 2026-08-10, 24:00 Beijing Time.

**`33.2473` is roughly half the `64.17` the same code scores locally on familiar-100
([R17](docs/tpc_phase2_eval.md#the-closed-queue-r1r19), `git_sha efbfea96`), and closing that gap is
now the work.** The leaderboard published the per-metric breakdown on 2026-08-07
([artifact](results/phase2_baselines/heldout/20260807_v1_leaderboard.json)) and it is sharper than the
aggregate: EPR-micro `99.48` (vs `99.67` locally — **grounding generalizes**), EPR-macro `95.00`,
C-LPR **`55.20`** (vs `90.08`), **FPR `0.0000`** (vs `44.0`), all three preference terms `0`. Three
things follow, and every agent should read them before choosing work: the failure is *only* in knowing
what to satisfy, not in grounding it; `FPR = 0` is the arithmetic consequence of a `58 %` per-clause
rate over ~11 clauses, **not a second bug to hunt**; and `55 %` of the total weight yields exactly zero
and unlocks at a *threshold* (`p ≈ 0.8`), so rank work by whether it can cross that, not by how many
clauses it fixes. The largest identified cause is measured: our constraint extraction has **zero**
clause-level gaps on familiar-100 — the numbered-template split it was built against — and
**12–29 %** on every differently-phrased released set, so we optimized against the one register we were
already perfect on. It is not the *only* cause: held-out C-LPR sits below our worst local free-prose
number, which is [P19](docs/tpc_phase2_roadmap.md#p19--find-the-unidentified-half-of-the-gap). Read
[the eval doc's opening section](docs/tpc_phase2_eval.md#the-one-fact-that-reorganizes-this-document)
before trusting any local number, and treat a familiar-100 result as evidence about *one phrasing
register* only. A first fix landed (bare total budgets, plain room-type wording; free-prose e2e
`41.62 → 49.99`, familiar-100 byte-identical), and the ranked residual is
[P15–P19](docs/tpc_phase2_roadmap.md#work-items).

**Do not package or upload `v2`. Never upload automatically.** The owner submits manually, shortly
before the deadline and only with a substantial measured improvement; agents prepare and measure,
nothing more. The leaderboard's rank `1` is rank 1 of 1 and carries no information. The packaging path,
when it is wanted, is in the [competition
reference](docs/reference/competition.md#the-v1-archive-as-built-2026-08-05). That same 2026-08-04
email also gave the
organizers' exact evaluation LLM deployment (SGLang, `Qwen3.6-27B`, `http://127.0.0.1:30000/v1`,
OpenAI-compatible); see the [competition
reference](docs/reference/competition.md#harness-resubmission-and-the-confirmed-llm-endpoint-2026-08-04-second-organizer-email)
for the full contract — this does not change the zero-LLM-calls library default.

## Parallel workstreams

Phase 2 development is split across concurrent workstreams. Each workstream uses its own branch and opens its own PR; none blocks the others.

| Workstream | Job | Writes | Must not |
| --- | --- | --- | --- |
| **Analysis / docs / plan** | Review status, shortcomings, and options; keep the three Phase 2 docs (eval roadmap, implementation roadmap, design) current with the latest `main`. | `docs/tpc_phase2_*.md`, `CLAUDE.md`, `README.md`. | Change agent/solver behavior, or run long e2e itself. |
| **Evaluation** | Work the [evaluation roadmap](docs/tpc_phase2_eval.md#run-this-next) in order on a separate machine and commit the resulting rows: whole-run rows (`make phase2-full-run`, the 5 h envelope — this is what decides the submission) and per-query rows for solver A/Bs. Non-blocking and long-running. | `results/phase2_baselines/full_runs/`, `results/phase2_baselines/runs/` (generated rows only). | Edit agent, parser, solver, or doc prose. |
| **Implementation** | Implement the next item from the [implementation roadmap's work items](docs/tpc_phase2_roadmap.md#work-items), with focused tests, and commit the [pre-gate screen](docs/tpc_phase2_eval.md#quick-ab-screen) that triaged it. | `chinatravel/`, `agent_env/`, `tests/`, `scripts/`, `results/phase2_baselines/screens/`. | Rewrite roadmap priorities or promote a row (that is the gate's job). |

**Who owns which measurement directory**, since the two are easy to confuse. A **screen**
(`results/phase2_baselines/screens/`) is the *implementation* workstream's own pre-gate triage: it
runs on the developer's box in 1–2 h, is paired against the same subset/budget/seed, and its whole
purpose is to decide whether a change is worth an eval-machine slot. It belongs in the PR that makes
the change, next to the code it justifies — a change whose evidence lives in a different PR cannot be
reviewed. A **row** (`full_runs/`, `runs/`) is the promotion instrument, produced by the Evaluation
workstream on the eval machine under a pinned contract. Only a row can flip a default; a screen never
promotes, whoever commits it.

Shared rules for every workstream: obey the [non-negotiable invariants](#non-negotiable-invariants) and the [change and branch protocol](#change-and-branch-protocol); rebase on the latest `main` before pushing; a measurement promotes a change only through the gate, never by assertion alone. Priority order is maintained in the roadmap, and focused prompts live in [`docs/agents/`](docs/agents/).

## Source of truth

| Topic | Read this |
| --- | --- |
| Project setup and canonical entry | [README.md](README.md) |
| Shared solver architecture | [Phase 2 design](docs/tpc_phase2_design.md) and [TPCAgent internals](chinatravel/agent/tpc_agent/readme.md) |
| Phase 1 operation | [Phase 1 playbook](docs/tpc_phase1_playbook.md) |
| Phase 2 architecture and flag policy | [Phase 2 design](docs/tpc_phase2_design.md) |
| Phase 2 metrics, gates, dataset boundaries, and the fast pre-gate A/B screen + cadence | [Phase 2 evaluation roadmap](docs/tpc_phase2_eval.md) |
| **What to evaluate next** (5 h whole-run envelope, parallel) | [Phase 2 evaluation roadmap](docs/tpc_phase2_eval.md#run-this-next) |
| Phase 2 diagnosis, open work items, and the landed/closed record | [Phase 2 implementation roadmap](docs/tpc_phase2_roadmap.md) |
| Parallel-agent focused prompts (evaluation and implementation) | [Agent prompts](docs/agents/README.md) |
| Competition facts | [Competition reference](docs/reference/competition.md) |
| Phase 2 submission packaging and the technical report | [Competition reference](docs/reference/competition.md#packaging-this-into-a-submission) and [report guide](report/README.md) |
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
- **Cold start is the only start that counts.** The submitted archive runs in a tree that has never been run in, with `CPU-1` worker processes. A development tree is always warm, so warm-tree evidence proves nothing about it: verify from a pristine directory with more than one worker before any upload (`tests/phase2/test_cold_start.py`, `scripts/assemble_phase2_submission.py --verify-budget-sec`). A worker that dies during start-up breaks the pool, and the run still **exits 0** while shipping empty fallback plans — check plan contents, never exit status. See the [pre-submission checklist](docs/reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).
- **Upstream evaluator parity.** `chinatravel/evaluation/`, `chinatravel/symbol_verification/`, `chinatravel/environment/concept_labels.py`, `chinatravel/environment/tools/`, `eval_tpc.py`'s scoring and `chinatravel/data/load_datasets.py` must reproduce `LAMDA-NeSy/ChinaTravel` `main` exactly (parity point: `c89cfca`, 2026-08-04, integrated 2026-08-04; previously `764614c`, 2026-07-28). Upstream `main` is at `456b60a` as of 2026-08-06 and is byte-identical to `c89cfca` across every path above (PR #33 touched only `agent_env/` and the baseline harness), so the parity point does **not** move and no recorded row's comparability changes — re-check this, do not assume it, whenever upstream advances. Local additions there are limited to performance (lazy per-language tools) and defensive guards on malformed plans; never a scoring difference, and never a private "patched" score. Re-sync upstream before trusting a number.

## Measurements and ledgers

Promotable Phase 2 evidence is a committed row under `results/phase2_baselines/` produced from a pinned source revision when the run is long.
Two contracts coexist and their rows are never comparable: **whole-run** rows (`full_runs/`, one 5 h envelope for the split, parallel, triage-first — what the submission is judged by) and **per-query** rows (`runs/`, fixed `900 s`/query, sequential — for solver A/Bs). See [Phase 2 evaluation](docs/tpc_phase2_eval.md#two-measurement-contracts).
Compare rows only when data source, split/fold/limit, budget, repeat count, flags, model/backend, parallelism, fresh-output policy, and evaluator contract match; rows straddling either upstream evaluator sync (2026-07-28 `764614c`, 2026-08-04 `c89cfca`) are never comparable — `evaluator_parity` on each recorded row says which side it is on.
Parser diagnostics prioritize a failure investigation; they do not by themselves promote a change.
Gate a like-for-like end-to-end candidate and inspect parse failures, timeouts, recovery/fallback use, stage telemetry, and LLM failure telemetry.
Familiar-100, local released data, HF data, and final held-out evaluation remain separate signals.
Familiar-100 is split 80/20 into `tpc_phase2_familiar_100_val` (screens + development gates) and a held-out `tpc_phase2_familiar_100_test` (occasional overfitting tripwire, never a per-change signal); `make phase2-familiar-splits` regenerates them and the [eval doc](docs/tpc_phase2_eval.md#1-official-familiar-100) states the boundary.

## Change and branch protocol

1. Read the owning document and existing code path before editing.
2. Make a coherent, acceptance-preserving change with focused tests for a new observable contract.
3. Run the relevant test or smoke path before committing.
4. Pull/rebase the shared branch before committing and again before pushing; resolve unexpected changes as user work, never overwrite them.
5. Commit the completed unit of work locally, then push the reviewed branch. Do not create a competing ledger branch.
6. When asked to open a PR, after opening it wait for GitHub Copilot review comments (poll up to 10 minutes), then address or resolve each one before proceeding.

Use Python 3.12 through `.venv/bin/python`.
Do not read, edit, stage, or overwrite `.env`; it is local user configuration. To run an LLM-backed
path (e.g. a `--mode end-to-end` [quick screen](docs/tpc_phase2_eval.md#llm-backed-flags)
of `TPC_P2_LLM_PARSE` / `TPC_P2_LLM_REFINE`), do **not** source or echo `.env`: set
`TPC_P2_LLM_BACKEND=deepinfra` and the code's `build_llm_client` → `load_local_env()` loads
`DEEPINFRA_API_KEY` from `.env` into the process itself. On a reduced screen budget also set
`TPC_P2_LLM_TIMEOUT_SEC` below the parse/improve slice (`6` at a `90 s` budget) or the LLM stage
silently no-ops; confirm the `flag=on` arm's telemetry shows the call fired before trusting the result.
