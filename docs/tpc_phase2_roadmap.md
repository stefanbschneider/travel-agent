# TPC 2026 Phase 2 Roadmap

This is the only active Phase 2 plan. It also absorbs the former solver-headroom note.
Historical step plans, chronology, and superseded priorities are preserved in the [Phase 2 archive](archive/README.md).
For measurement discipline and dataset boundaries, see [Phase 2 evaluation](tpc_phase2_eval.md).

## Completed capabilities

- A per-query no-oracle orchestrator wraps the deterministic `TPCAgent` and CP-SAT tier.
- Parser output is normalized into branch-local solver variants with optional entity resolution and disjunction handling.
- The harness records stage telemetry, recovers a best available solver plan after errors or timeouts, and has a schema-shaped fallback.
- Rehearsal supports ceiling, solver-only, and end-to-end attribution; parser comparison and regression gates are available.
- Baselines can run from a pinned source revision and publish committed rows under `results/phase2_baselines/`.
- The official familiar-100 records are imported byte-for-byte with a pinned archive checksum, per-member manifest, dedicated split, and explicit no-oracle boundary.
- **Parser lifted from `~0.20` to `~0.99` familiar-100 F1** with zero missing families — the last step being the comma-in-name entity-resolution segmentation fix (`62df2a0b`, F1 `0.9316 -> 0.9908`; see [Completed parser work](#completed-parser-work)).
- **Timed-window pinning and a within-day resequencer landed opt-in** behind `TPC_PIN_TIMED_WINDOWS` (default off, floor byte-identical), targeting the dominant solver-only failure family (see [Solver-only headroom](#solver-only-headroom)).

These capabilities are not evidence of final-evaluation performance.

## Current evidence

The current local reference for the flags-on harness path is [familiar-100 run `20260721T174336Z`](../results/phase2_baselines/runs/20260721T174336Z.json) (`familiar100-negconstraint-llmon`, sha `1de62e99`, two fresh repeats, harness-default flags with `llm_parse` audit on, `300 s` budget). It carries all the landed parser fixes: parser precision/recall/F1 are each `0.9510` with zero missing, mean end-to-end FPR `21.5%`, mean end-to-end `overall_true` `45.06`, solver-only FPR `25.5%`. All `100/100` outputs are valid; zero parse failures, zero fallbacks, zero budget overruns.

Two facts from this row set the roadmap:

1. **Solver-only FPR (`~26`) is now the binding ceiling.** With oracle-perfect constraints the solver still passes only `26/100`, stable across every committed familiar row and repeat. The parser is no longer the bottleneck on familiar-100; the solver is.
2. **The median query runs to the budget wall.** Solve `p50 = 270 s` at a `300 s` budget, and `38/100` end-to-end queries time out (all recovered into valid plans). The restart loop consumes the whole budget rather than converging, so wall-clock is a live constraint and the recovery path is load-bearing.

The earlier promoted anchor was [`20260718T155006Z`](../results/phase2_baselines/runs/20260718T155006Z.json) (`ae6337f0`); it and `20260716T090638Z` predate flag recording and were mislabeled "library-default" — their telemetry (`llm_parse_attempted: 100`) shows they ran the Qwen audit path. Baseline rows now record resolved flags under `flags`.

The familiar release has no organizer best plans, so its ceiling is unavailable rather than zero. Every number here is a repository-local development result, not an estimate of final held-out performance.

## Shortcomings of the current agent

A review of the Phase 2 path (`chinatravel/agent/phase2/` + the no-oracle `TPCAgent`) against the latest evidence surfaces six shortcomings, roughly in leverage order.

1. **Solver-only ceiling dominated by one family.** `26/100` solver-only pass with perfect constraints; `timed_visit_named_poi` is the *sole* logical blocker in `53` of the `74` failures. The landed pinning + resequencer (opt-in, ungated) target exactly this but have not been measured through the gate. This is the single highest-leverage gap. See [Solver-only headroom](#solver-only-headroom).
2. **Budget-bound solver with no early convergence.** Solve `p50` sits at the budget wall; `38%` of queries time out and survive only through timeout recovery. The seeded-restart loop has no "good enough, stop" signal short of the wall, so extra budget buys little and the recovery plan carries a large share of outputs. A convergence/early-accept heuristic (distinct from the evaluation-only `TPC_SOLVE_STOP_AT_ACCEPT`) and a restart-budget study are open.
3. **Stage 3 "improve" is a no-op.** `orchestrator.llm_refine_stub` returns the plan unchanged and never calls the LLM (`improve` stage `p50 ≈ 1 µs`). The reserved improve slice is either wasted or, with `dynamic_budget`, reallocated to solve. There is no bounded, acceptance-gated refinement of an already-valid plan — a designed extension point that is still empty.
4. **Commonsense residual is unaddressed.** Even at solver-only, `~24/100` fail commonsense, dominated by "Invalid Transport information across positions" (`18`) and intercity-event grounding (`6`). These are produced-but-invalid plans, so the feasible fallback does not help them; they need a transport-grounding repair, not more search.
5. **Parser value-segmentation residual — largely closed, pending gate.** The comma-/`" and "`-in-name `wrong_value` residual was fixed on `main` (`62df2a0b`) via maximum-munch catalog segmentation plus a restaurant/hotel matching-pool broadening, taking familiar-100 F1 `0.9316 -> 0.9908` (wrong_value `47 -> 6`). It is diagnostic evidence only — not yet through the end-to-end gate — and a `6`-case residual remains from a *different* upstream bug: abbreviation-period truncation (`"St. Regis"`, `"No. 3955 …"`) in the base regex parser.
6. **LLM-parse decision is not yet cleanly gated end-to-end.** Parser-level evidence says audit mode is neutral-to-negative, yet the harness auto-enables it whenever a backend is configured, and the two end-to-end points that bracket it are at different shas (`nollm` at `7d5e1910`, `llmon` at `1de62e99`) so they conflate parser code with the flag. A paired on/off gate at one sha is now runnable and should settle the auto-enable.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Next steps (priority order)

1. **Gate the solver-headroom step.** Record a clean flags-off solver-only familiar-100 baseline (no committed row is truly flags-off), then run `TPC_PIN_TIMED_WINDOWS` on through the pinned no-oracle gate (`make phase2-gate`) against a matched baseline; promote only if solver-only FPR improves with no new parse failures or timeouts. This is the highest-leverage open item — see [Solver-only headroom](#solver-only-headroom).
2. **Gate the landed parser fixes together.** The negative-constraint, required-constraint, deterministic-budget, and `required_attraction_types` time-window fixes still need one pinned end-to-end gate against the last promoted familiar row before promotion. The current best flags-on row (`20260721T174336Z`) already carries them but has no matched flags-off counterpart at the same sha.
3. **Settle the LLM-parse auto-enable.** Run paired `llm_parse` on/off rows at one sha (`make phase2-baseline-at SHA=<ref>` with and without `TPC_P2_LLM_PARSE`, now that `phase2_eval_at.py` shares `agent_env/config.toml` into the worktree) and gate on `continuous_score`. If audit adds spurious constraints with no end-to-end benefit, stop the harness auto-enabling it when a backend is configured (`agent_env/scripts/solve_phase2.py::resolve_llm_client_and_flags`).
4. **Attack the commonsense-transport residual.** Root-cause "Invalid Transport information across positions" (`18` solver-only) and intercity-event grounding (`6`); prefer a grounded transport-repair pass over more search. This is the second solver surface after the timed-visit family.
5. **Study the solver budget/convergence.** Because solve `p50` is at the wall with `38%` timeouts, quantify the restart-count vs. score curve and add an early-convergence stop distinct from the evaluation-only `TPC_SOLVE_STOP_AT_ACCEPT`. Run a longer local-budget sensitivity only if a future solver-only failure set becomes timeout-confounded — the current one is not (all `22`–`23` solver-only timeouts recover into pass cases; none of the failures timed out).
6. **Gate the landed entity-resolution segmentation fix** (`62df2a0b`, comma-in-name residual) and, separately, address the `6`-case abbreviation-period truncation residual (`"St. Regis"`, `"No. 3955 …"`) in the base regex parser — a distinct upstream bug, not a segmentation gap.
7. **Consider implementing Stage 3 refine.** Only after the above: a bounded, acceptance-gated refinement of an already-valid plan, keeping the change only if acceptance still passes. Today it is an intentional no-op placeholder.
8. **Package and smoke-test the official harness interface**, including oracle hiding, output layout, and tool access (`agent_env/scripts/solve_phase2.py`, `solve_script_with_harness.py`; entry-point smoke tests exist).

The public material still does not specify a runtime contract. Until it does, `300 s` and `900 s` are local assumptions for sensitivity analysis, not organizer-confirmed limits.

## Solver-only headroom

Diagnostic analysis of the **solver-only** failure surface (oracle constraints fed to a bounded solve, parser removed) on familiar-100, plus the landed opt-in step to close it. Development signal only; the relevant invariant is G8 in the [archived gap map](archive/phase2/tpc_phase2_plan3.md).

Reproduce offline (reads the committed baseline's per-clause verdicts and the split's oracle `hard_logic_py`; no LLM calls, no re-solve):

```
python3 scripts/phase2_solver_failure_attribution.py            # latest familiar row, solver-only
python3 scripts/phase2_solver_failure_attribution.py --mode end-to-end
```

Against `results/phase2_baselines/runs/20260718T155006Z.json`:

| Layer | pass (macro) | micro |
| --- | --- | --- |
| Schema | 100/100 | — |
| Commonsense (EPR) | 76/100 | 98.19 |
| Logical (C-LPR) | 28/100 | 88.91 |
| **All (FPR)** | **26/100** | — |

Logical satisfaction is the binding surface, and one family dominates it:

| logical family | failing queries | failed instances | sole blocker |
| --- | --- | --- | --- |
| **timed_visit_named_poi** | **70** | **104** | **53** |
| required_attractions | 6 | 6 | 1 |
| required_restaurants | 6 | 6 | 0 |
| room_count | 2 | 2 | 0 |
| required_cuisine_types | 2 | 2 | 0 |
| (others) | ≤1 each | | |

`sole_blocker` = queries where the family is the only failing logical family. **timed_visit_named_poi is the sole blocker in 53 of the 74 failures** — the highest-leverage target by a wide margin, quantitatively confirming G8.

### The failure mechanism

The clause requires *an activity of a given type, at a named position, within `[earliest, end_before]`*. The `104` failing instances split by the named position's database: **44 meals at a named accommodation** (hotel breakfast), **39 attraction visits at a named attraction**, **21 meals at a named restaurant**. Two concrete gaps, confirmed by reproducing failing plans:

1. **Pool routing.** `_apply_search_constraints` projected window/position names only into `required_attractions`/`required_restaurants`. An accommodation name resolves in neither, so "meal at *Nanyang Inn*" never pinned hotel selection to that inn — the plan stayed elsewhere and the named meal was absent.
2. **Timing.** The greedy slotter schedules included POIs by visit order, not by clause window, so a present named POI lands at the wrong time (a required 07:50–08:40 hotel breakfast placed 07:30–08:30; a required evening attraction placed in the morning).

### Landed: opt-in timed-window pinning + resequencer (`TPC_PIN_TIMED_WINDOWS`, default off)

Implemented in `chinatravel/agent/tpc_agent/tpc_agent.py`, gated behind `TPC_PIN_TIMED_WINDOWS` (default **off**, so the deterministic floor is byte-identical; asserted by unit tests). When on:

- **Pool routing** — `_apply_search_constraints` also projects window/position names into `required_hotels` (the per-DB resolver keeps a name only in the pool it matches), so a named accommodation pins hotel selection there and its hotel breakfast can satisfy the clause.
- **Retiming** — `_pin_timed_windows` (run in `_pack_plan` *before* the acceptance gate) shifts a present-but-mistimed matching activity into `[earliest, end_before]`, recomputing its own and the following activity's inbound legs. Every shift is trialed on a deepcopy and committed only if the full checker then accepts and the preference key does not regress.
- **Resequencing** — `_resequence_day`, tried from `_pin_timed_windows` only when the local same-slot retime fails to commit (a fixed neighbour blocks it for lack of slack). It orders the day's meal/attraction activities by target window, recomputes each inbound leg sequentially via `_get_transport`, and commits on a deepcopy only if the full checker still accepts and the preference key does not regress. Intercity legs and the overnight accommodation activity are never moved.

Verified by unit tests (`tests/phase2/test_pin_timed_windows.py`, `tests/phase2/test_resequence_day.py`) and, on failing uid `...00062`, the `required_hotels` projection moving the required breakfast onto the named inn. **Not yet measured through the pinned end-to-end gate** — that is Next step 1.

### Known limits / what the gate must check

- **A rejected idea — do not reintroduce.** Emitting `arrive_no_later` from `end_before` (to time morning meals) **regressed commonsense** on the floor: its ceiling pruned proper transport, producing transport-less plans that fail "Invalid Transport information across positions." It was dropped; do not revive it without gating.
- **No promotion without the gate.** No committed familiar row is truly flags-off (all ran a Qwen backend that auto-enables `llm_parse`). Before promoting pinning + resequencing: record a clean flags-off solver-only familiar-100 baseline, then run flag-on through `make phase2-gate` against a matched baseline; promote only if solver-only FPR improves with no new parse failures or timeouts.
- **Out of scope.** The constraint-light feasible fallback (G7, `fallback.py`'s empty itinerary) does not move solver-only FPR — those failures are produced-but-invalid plans, not solver failures/timeouts.

## Completed parser work

The parser rose from `~0.20` to `~0.95` familiar-100 F1 (solver-free `scripts/parser_vs_oracle.py --split tpc_phase2_familiar_100`, flags-off deterministic path) through a sequence of structural template fixes. Full per-family tables and the chronological narrative are preserved in the [archive](archive/README.md); the headline sequence and the durable lessons:

| Stage (sha) | precision | recall | F1 |
| --- | --- | --- | --- |
| Baseline | 0.4445 | 0.1281 | 0.1988 |
| Activity-window fix (`ae6337f0`) | 0.8180 | 0.3518 | 0.4920 |
| Deterministic-budget templates (`c428dd6c`) | 0.8502 | 0.4561 | 0.5937 |
| Negative-constraint fix | 0.8620 | 0.8036 | 0.8317 |
| Required-constraint fix | 0.9402 | 0.9487 | 0.9444 |
| `required_attraction_types` time-window guard | 0.9510 | 0.9510 | 0.9510 |
| Entity-resolution catalog segmentation (`62df2a0b`) | — | — | 0.9908 |

(The last row is measured with entity resolution on, `--disjunction --entity-resolution --branch-aware`; it drops familiar-100 `wrong_value` `47 -> 6` and moves val F1 `0.7869 -> 0.7949`. The reference run `20260721T174336Z` predates it, so its `0.9510` does not yet reflect this fix.)

Why familiar-100 needed this while val did not: familiar records average `~38` `hard_logic_py` constraints each vs. `~16` in the released Phase 1 source `tpc_phase2_val` is partitioned from. The dominant gap was five negative families the parser extracted **zero** of (`excluded_cuisine_types`, `excluded_hotels`, `excluded_attractions`, `excluded_restaurants`, `excluded_attraction_types`) — `266` of `359` missing constraints — encoded in the oracle as `result=not({<names>} & <set>)` and surfaced in one uniform `Do not include any of these <category>: A, B and C.` template. All five now have zero missing.

Durable parser lessons (each landed with a val-inert guard, so the phase-1 partition stayed byte-identical):

- **Anchor the category at the `:` list marker** so a name category (`hotels`) never fires on a sibling type category (`hotel feature types`).
- **Use verbatim values for type families** — the NL uses the oracle's own vocabulary/casing; routing through the lower-casing alias table drops unaliased types.
- **Protect compound vocabulary** read from committed `database_en` CSVs (cuisine values like `Fast food and casual dining` legitimately contain `" and "`).
- **Handle Oxford commas** so `A, B, and C` leaves no `and C` fragment.
- **Never scan a POI name for a naive type substring** — strip `Visit X between A and B` window lines before the known-types substring check (the fix that removed the last `required_attraction_types` spurious entries).
- **Segment entity lists by maximum-munch against the catalog, with a strict exact match** — a catalog name can itself contain an internal `,`/`" and "` (`Honey Lake 1979 Cultural and Creative Park`), so `_segment_entity_list`/`_merge_fragmented_list_entries` prefer the longest span that resolves exactly; reusing the lenient ≥60%-containment match let a longer candidate silently absorb the next distinct entry. A restaurant-family clause can also legitimately name a hotel (a free hotel breakfast positioned at the hotel's own name), so broaden that family's pool to `{restaurant, hotel}` rather than rerouting the match away.

Remaining parser defect after the segmentation fix: a `6`-case `wrong_value` residual on familiar-100 (`excluded_hotels`/`excluded_restaurants`, `3` each) from abbreviation-period truncation (`"St. Regis"`, `"No. 3955 …"`) in the base regex parser — a distinct upstream bug from the comma-in-name segmentation now handled by entity resolution (Next step 6).

### LLM parsing vs deterministic

Question settled at the parser level: routing the parse through the DeepInfra `Qwen/Qwen3.6-27B` LLM does **not** beat the deterministic parser on the final distribution, so **`TPC_P2_LLM_PARSE` is not defaulted on** (the library default `Flags()` already keeps it off). Measured with `scripts/parser_vs_oracle.py`, temperature 0, cached, on English text.

- **Audit mode never recovers recall on any set.** `matched` is flat on HF (`52→52`, `51→51`) and falls on familiar-100 (`644→633`, corrupting matched families into spurious/wrong-value), because `normalize.llm_parse_stub` re-parses every LLM proposal through the regex — a constraint the regex cannot extract from the original NL it also cannot extract from the paraphrase. Net F1 ≤ deterministic on all three sets; audit-by-default is pure downside at the parser level.
- **Extract mode recovers OOD recall** (HF `medium` F1 `0.447→0.793`) but at a value-accuracy cost that is neutral-to-negative on human-written NL (HF `human` `0.699→0.681`) and strongly negative on familiar-100's already-solved templates (`0.935→0.758` on the 25-uid subset). Its only decisive win is machine-templated OOD phrasing, which is not the final distribution.

The end-to-end gate (Next step 3) is the arbiter and should also re-examine the harness auto-enable of audit mode when a backend is configured. The first end-to-end point (`20260721T054820Z`, `llm_parse` off, `41.83` overall_true / `12.5%` FPR) is directionally consistent but not a clean gate; the current `llmon` best (`20260721T174336Z`, `45.06` / `21.5%`) is at a different sha, so the pair still conflates parser code with the flag.

## References

- [Stable design](tpc_phase2_design.md)
- [Evaluation and dataset boundaries](tpc_phase2_eval.md)
- [Competition reference](reference/competition.md)
- [Baseline ledger guide](phase2_baselines/README.md)
