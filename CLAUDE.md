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
**Submission status: the competition is over.** Both slots were used (`v1 = 33.2473`,
`v2 = 33.3175`); the final Phase 2 leaderboard (`submissions/Final Phase 2 Leaderboard —
TPC@IJCAI2026.pdf`, committed 2026-08-13) has the team at rank **10 of 14**. Everything below this
paragraph is the historical record of how `v2` was built and reasoned about before that result was
known — read it for the method, not as an open task list. The one live thread post-competition is
[R37](docs/tpc_phase2_eval.md#r37--identity-check-the-published-held-out-test-set): the organizers
later published the actual held-out test set's oracle on Hugging Face, and replaying the frozen
`v1`/`v2` archives against it reproduces both official scores within about a point — see the
[competition reference](docs/reference/competition.md#final-leaderboard-and-the-newly-published-held-out-test-set-2026-09-05)
for the full writeup, including why the *other* newly-linked HF resource (the upstream README's new
sandbox link) is environment data only and not that test set.
**Why we placed 10th is now answered:** [R38](docs/tpc_phase2_eval.md#r38--held-out-postmortem-why-the-improvements-did-not-transfer-closed-2026-09-29-retrospective-only)
attributes the held-out gap clause by clause. The held-out set shares familiar-100's numbered-list
format but uses all 53 constraint template keys (familiar-100: 29) and `140` OR clauses (familiar-100:
0); `59 %` of its clauses sit in families our parser and solver schema never represented, and the
`v1 → v2` work was aimed at a free-prose register that was not graded. Read R38's lessons before
reusing any diagnosis below.

**The 2026-08-08 leaderboard has five teams and reorganizes the priorities again**
([artifact](results/phase2_baselines/heldout/20260808_leaderboard_5teams.json)): `36.4060` /
`35.4768` / **`33.2473` (us)** / `32.6028` / `21.0166`. Three facts follow and every agent should read
them before choosing work. **(1) `99.5 %` of the `3.16` gap to first place is C-LPR** — `12.57` clause
points at weight `0.25`. Our EPR-micro is within `0.16` of the leader's and our EPR-macro is tied, so
there is nothing else at the top of the board to fix; `+4.0` C-LPR is `+1.0` overall. **(2) `FPR = 0`
is the whole field, not our bug** — four of five teams score exactly `0.0000` and every preference term
is `0` for everyone, so the held-out set is simply dense enough that nobody satisfies every clause of a
query. Do not hunt a second defect. **(3) `55 %` of the weight therefore pays nobody**, and it unlocks
at a *threshold* (`p ≈ 0.8`), so rank work by whether it can cross that, not by how many clauses it
fixes.

**What `v2` carries, measured.** `v1` predates the whole phrasing-and-precision program (the 2026-08-06
phrasing fix, P15, P20, P22, P23, P24, P17a, P4, P6, P25, P26), and no familiar-100 row could show
that, because familiar-100 is the one register where all of it is structurally inert.
[R32](docs/tpc_phase2_eval.md#r32--what-landed-since-v1-measured-on-free-prose) measures it on free
prose instead — the register whose failure signature matches the held-out one — with R31's translated
oracle lifting the FPR ceiling that used to make such a measurement unreadable: **C-LPR
`75.55 → 88.37`, FPR `10.67 → 44.00`, overall `44.41 → 64.28`**, `191` clauses fail→pass against `29`
lost. Two candidate flags were decided there and in
[R33](docs/tpc_phase2_eval.md#r33--the-v2-whole-run-gate-on-familiar-100).

**Then 2026-08-09 found something bigger, and how it was found is the reusable part.**
[P28](docs/tpc_phase2_roadmap.md#p28--honor-a-stated-room-count): the solver derived the hotel room
count from party size instead of reading the count the traveler stated, and **`28` of 150 `hf_medium`
queries failed *only* that clause**. Every coverage instrument called the family fine, because the probe
classifies it as metadata-guaranteed. What found it was asking *for each query failing exactly one
clause, which clause is it?* — so **run that question after any measured run; a coverage table cannot
answer it.** Both gates GREEN ([R36](docs/tpc_phase2_eval.md#r36--the-stated-room-count-gate-on-both-registers)):
free prose FPR `48.0 → 65.3333` and overall `66.6182 → 76.0996`, familiar-100 whole run
`65.7354 → 66.8128` — the first change to gain on *both* registers. Cumulative `v1 → v2` on free prose:
C-LPR `75.55 → 92.33`, FPR `10.67 → 65.33`, overall `44.41 → 76.10`. Read those sections before
changing a default.

**Read [the eval doc's opening](docs/tpc_phase2_eval.md#the-one-fact-that-reorganizes-this-document)
before trusting any local number**; treat a familiar-100 result as evidence about *one phrasing
register* only; and **never read a free-prose FPR against `100`** — under `--lang en` the raw HF splits
cap at `38.67–46.0`, because their oracle literals are Chinese while their query text is English (use
`scripts/materialize_hf_split.py --translate-oracle-literals`, P23/R31, when a real denominator is
needed).

**`v2` is packaged and verified, but never uploaded by an agent.** The owner submits manually, shortly
before the deadline; agents prepare, measure and test, nothing more. The archive under
`submissions/phase2/` is the tested bytes, so it can be checked without a rebuild. The packaging and
verification path is in the [competition
reference](docs/reference/competition.md#the-v2-archive-as-built-2026-08-09). That 2026-08-04
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
