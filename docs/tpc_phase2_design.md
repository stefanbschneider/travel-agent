# Phase 2 design

How the submitted Phase 2 system is built: the trust boundary it runs under, the shape of a run, the
per-query pipeline, and where every knob lives. Current priorities are in the [implementation
roadmap](tpc_phase2_roadmap.md); measurement rules are in the [evaluation
roadmap](tpc_phase2_eval.md). Solver internals are documented in [TPCAgent
internals](../chinatravel/agent/tpc_agent/readme.md); [README.md](../README.md) is the
organizer-facing install-and-run entry point.

## No-oracle execution contract

- Input to the planning path is the visible query text plus allowed environment tools only.
- Oracle verifier fields (`hard_logic*`) are evaluation-only and stripped before parsing or solving.
  Local tooling may read them to score or attribute a rehearsal; nothing running inside `agent_env/`
  may.
- LLM steps may propose parse or refine edits, but cannot authorize facts. Every fact is grounded in
  `WorldEnv` and every candidate passes deterministic acceptance checks.
- Library-default flags keep the deterministic path and make zero LLM calls. Any optional feature has
  a bounded fallback, an explicit flag, and telemetry visibility.

## Entry point

Evaluation runs exactly one command, from the package root, with no other flags:

```bash
python agent_env/scripts/solve_script_with_harness.py --method <method> --split <split>
```

Both arguments are the organizers' and neither may be hard-coded (2026-08-06 clarification):
`--split` selects the held-out split, `--method` names the output directory, and plans must land at
`results/<method>/<uid>.json`. The shipped `agent_env/config.toml` therefore pins neither, nor a
`limit`, so no split, query list, query count, or method name is fixed in the package.

Its shipped default is `--harness tpc`, which dispatches **in-process** to
`solve_phase2.run_split` — no subprocess, no network, no LLM. `--harness opencode` / `--harness codex`
remain reachable as explicit opt-ins for baseline comparison but never run by default. Language
defaults to `en` (the competition data), independent of the split's name, and falls back to `zh` if
the split resolves only in that tree — an unresolvable split would otherwise produce no plans at all.
Held-out queries carry no `hard_logic*` (or any other verifier-only) field; every path treats them as
optional, so their absence disables only the local convenience scoring, never the solve. Install for
this path is `requirements-submission.txt`; `scripts/assemble_phase2_submission.py` builds and
verifies the archive, failing the build unless a run with an arbitrary `--method` writes to exactly
`results/<method>/`.

## Run shape

`chinatravel/agent/phase2/sweeps.py` schedules the whole split against the single 5-hour wall clock
rather than giving each query a fixed budget. A one-pass "spend `1/n` of the time on each query in
order" loop would sink a large budget into a structurally unsolvable query while a later query never
gets the 30 seconds that would have solved it, stop with hours left, and spend as much effort on
preference polish as on constraint satisfaction — though the evaluator zeroes every preference term
of a query that fails its constraints.

Instead, passes:

1. **triage** — every query once at a small budget, cheapest wins first. After this pass every query
   has a real plan on disk. `TPC_P2_FAST_TRIAGE=1` (default) stops each query's search at the first
   accepted plan (still finalizing it through `_pack_plan`) rather than spending the rest of the slot
   on preference.
2. **repair** — only queries whose plan does not satisfy its constraints, at a larger budget each
   pass, most-nearly-passing first.
3. **polish** — constraint-satisfying queries with the largest preference headroom, once repair stops
   making progress.

Properties that matter for safety and for reading a row:

- **Parallel across queries.** Each pass runs in `CPU-1` worker processes (`available_cpus()` prefers
  `os.sched_getaffinity(0)`, so a restricted container does not oversubscribe). A pass over `n`
  queries costs `ceil(n / workers)` query-budgets of wall clock instead of `n` — that is what makes a
  large per-query budget affordable inside 5 h at all. A single solve stays single-threaded.
- **Keep-best.** Every result is scored oracle-free (`selfscore`) and written only if it beats what is
  on disk, so no pass can regress a query.
- **Fallback first.** A schema-valid plan for every query is written *before* the first solve
  (`fallback.minimal_plan`), so a run cut off at any instant still submits a complete set.
- **Deadline-aware.** `pass_fits` refuses to start work the envelope cannot finish, and the run stops
  before the deadline rather than being killed at it.
- **Per-query budget is an output, not a setting.** A query may be solved at `40 s` in triage and
  several hundred seconds in a later repair pass.

Budget shape (all overridable by env var, all read in `SweepConfig`):

| Variable | Default | What it changes |
| --- | --- | --- |
| `TPC_P2_TRIAGE_CAP_SEC` | `120` | ceiling on the first, everything-once pass |
| `TPC_P2_TRIAGE_FRACTION` | `0.25` | share of the envelope triage may spend |
| `TPC_P2_PASS_FRACTION` | `0.5` | share of what remains each later pass may spend |
| `TPC_P2_MAX_QUERY_SEC` | `300` effective¹ | ceiling on any single query's solve |
| `TPC_P2_MIN_QUERY_SEC` | `20` | floor below which a query is not worth starting |
| `TPC_P2_MAX_PASSES` | `24` | hard stop on pass count |
| `TPC_P2_FAST_TRIAGE` | `1` | triage stops at first accept instead of polishing preference |
| `TPC_P2_WORKERS` | `CPU - 1` | worker processes |
| `TPC_P2_TOTAL_BUDGET_SEC` | 5 h | the whole-run envelope (`0` disables) |

¹ `sweeps.DEFAULT_MAX_QUERY_SEC` is `900`, but `run_split` resolves `budget_sec` from
`orch.DEFAULT_BUDGET_SEC` (`300`) *before* constructing `SweepConfig(max_query_sec=budget_sec)`, so
`900` is unreachable dead code on this path. See
[P4](tpc_phase2_roadmap.md#p4--derive-max_query_sec-from-the-envelope-instead-of-default_budget_sec).

Two scheduler rules explain why a run self-terminates early: `_choose_pass` drops a query from a
later pass unless its new budget beats its last by `MIN_BUDGET_GROWTH` (`1.25`) — re-solving at the
same budget reproduces the same plan — and `MAX_STALLED_REPAIR_PASSES` (`2`) treats two escalations
that improve nothing as structural rather than starved.

## Per-query pipeline

`chinatravel/agent/phase2/orchestrator.py::solve_phase2` allocates bounded stage budgets and records
`stage_sec` for each:

```text
query text (oracle fields already stripped)
  -> parse    : regex/heuristic constraint extraction, optional LLM audit (off by default)
                -> normalize into branch-local solver variants (disjunctions kept separate,
                   entity resolution, concept-label canonicalization)
  -> solve    : deterministic build, bounded random restarts, optional CP-SAT tier,
                acceptance-gated _pack_plan repairs/densification
  -> improve  : optional bounded LLM refine (off by default; proposals only)
  -> finalize : pick the best candidate under the acceptance ordering, emit plan + telemetry
```

Acceptance ordering inside `_solve`: a fully accepted candidate wins; otherwise, with
`TPC_COMMONSENSE_FIRST` on, the best schema+commonsense-valid candidate (`best_cs`) is preferred over
a higher-scoring but commonsense-invalid leader — because the scored C-LPR is conditional on the
commonsense pass. Timeout recovery mirrors the same order, so a `func_timeout` kill still emits the
best plan found so far instead of falling back.

Branch-local alternatives are preserved end to end: OR-style constraints stay separate variants
through normalization, solving and checking, and are never flattened into one conjunction.

## Ownership map

| Component | Responsibility | Source |
| --- | --- | --- |
| Constraint extraction | query/oracle input → solver-facing, branch-local constraints | `chinatravel/agent/tpc_agent/solver_constraints.py`, `parse_constraints.py` |
| Normalization | branch-local variants, entity resolution, concept-label canonicalization | `chinatravel/agent/phase2/normalize.py` |
| Deterministic planner | build, repair, restart, rank, pack, densify | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| CP-SAT tier | candidate pools and hard residuals | `chinatravel/agent/tpc_agent/cp_candidates.py`, `cp_solver.py` |
| Acceptance path | parsed/oracle constraints, then schema and commonsense checks | `chinatravel/agent/tpc_agent/parsed_verifier.py`, `tpc_agent.py` |
| Per-query orchestration | stage budgets, TPCAgent call, finalize | `chinatravel/agent/phase2/orchestrator.py` |
| Whole-run scheduling | passes, parallelism, keep-best, deadline | `chinatravel/agent/phase2/sweeps.py`, `selfscore.py`, `fallback.py` |
| Harness boundary | hide oracle fields, expose tools, official output layout | `agent_env/scripts/solve_script_with_harness.py`, `solve_phase2.py`, `agent_env/` |
| World facts | POIs, schedules, prices, restaurants, hotels, transport | `chinatravel/environment/`, `WorldEnv` |

## Flag policy

Three tiers, and the distinction is load-bearing:

- **Library default (env var unset)** — the deterministic floor. Every optional behavior is off and a
  unit test asserts the floor stays byte-identical when its flag is unset.
- **Harness default** — `solve_phase2.apply_deterministic_solver_defaults()` sets
  `TPC_PIN_TIMED_WINDOWS=1`, `TPC_WINDOW_ANCHOR=1`, `TPC_SOLVE_CONVERGE_PATIENCE=15` and
  `TPC_COMMONSENSE_FIRST=1` before the
  agent is built, *unless the operator overrode them*. This is the only sanctioned place a flag
  becomes on-by-default, and only on measured evidence
  ([landed](tpc_phase2_roadmap.md#harness-defaults-promoted-through-a-measured-gate-or-screen)).
  Each is recorded per query under `solver_flags`, so a row states which of them actually ran.
- **Eval-only** — `TPC_SOLVE_STOP_AT_ACCEPT` / `TPC_SOLVE_STOP_AT_ACCEPT_PACKED` (early-stop FPR
  measurement) and `TPC_USE_ORACLE` (solver-only attribution). Never set by the real harness;
  `sweeps` does set the packed variant per-task for fast triage, via a save/restore context manager.

`TPC_COMMONSENSE_FIRST` additionally acts as an umbrella (`_flag_enabled_with_umbrella`): it enables
`TPC_REPAIR_TRANSPORT_GAPS`, `TPC_REPAIR_INTERCITY` and `TPC_REPAIR_DROP_TRAILING_STAY` implicitly,
while an explicit `=0` on any of them still wins.

LLM configuration is separate and defaults to nothing: `TPC_P2_LLM_BACKEND=none`,
`agent_env/config.toml` gitignored, `TPC_P2_LLM_PARSE` explicitly off. See [LLM
packaging](tpc_phase2_roadmap.md#llm-packaging-the-submission-makes-zero-llm-calls).

## Outputs and telemetry

- Plans go to `results/<method>/<uid>.json` — the organizers' required location, with `<method>`
  taken verbatim from `--method`. When `--method` is omitted it defaults to `phase2_e2e_<split>`, so
  the harness entry point and `solve_phase2.py` share a directory and resume each other.
- Per-query telemetry (`work_root/<uid>/telemetry.json`) carries `stage_sec`, parse/LLM counters,
  `used_fallback`, `solve_recovered_from_timeout`, `rss_mb`, `search_telemetry` (`restarts_used`,
  `stop_reason`, `candidates_evaluated`, `best_found_at_restart`) and `solver_flags` (the promoted
  deterministic passes as the agent read them). It is overwritten per attempt —
  [P2](tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger) adds the append-only attempt ledger.
- Committed measurement rows: `results/phase2_baselines/full_runs/` (whole-run) and
  `results/phase2_baselines/runs/` (per-query). Field semantics: [baseline ledger
  guide](phase2_baselines/README.md).

**Resource shape:** cores, not memory, are the limit. Each solve is single-threaded (CP-SAT defaults
to one search worker), and the measured per-process RSS floor is `~250 MB`, so `N` concurrent solves
cost roughly `N` cores and `N × 250 MB` — trivial against the evaluation host's 112 GiB. Size
parallelism to `cores − 1` and read `rss_mb` from telemetry if a solve ever looks memory-bound.

## Cold start is the only start that counts

The submitted archive runs in a tree that has never been run in, with `CPU-1` workers. A development
tree is always warm, so warm-tree evidence proves nothing about it. A worker that dies during
start-up takes the whole `ProcessPoolExecutor` down, and the run still **exits 0** while shipping the
pre-written empty fallbacks — so check plan contents, never exit status. Guarded by
`tests/phase2/test_cold_start.py` and `scripts/assemble_phase2_submission.py --verify-budget-sec`;
see the [pre-submission
checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).
