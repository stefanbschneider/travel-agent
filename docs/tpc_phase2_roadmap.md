# TPC 2026 Phase 2 Roadmap

This is the only active Phase 2 plan. It also absorbs the former solver-headroom note.
Historical step plans, chronology, and superseded priorities are preserved in the [Phase 2 archive](archive/README.md).
For measurement discipline and dataset boundaries, see [Phase 2 evaluation](tpc_phase2_eval.md).

## Completed capabilities

- A per-query no-oracle orchestrator wraps the deterministic `TPCAgent` and CP-SAT tier.
- Parser output is normalized into branch-local solver variants with optional entity resolution and disjunction handling.
- The harness records stage telemetry, recovers a best available solver plan after errors or timeouts, and has a schema-shaped fallback.
- Rehearsal supports ceiling, solver-only, and end-to-end attribution; parser comparison and regression gates are available.
- **Two eval-only early-stop modes for cheap FPR measurement:** `--fast-fpr` (`TPC_SOLVE_STOP_AT_ACCEPT`, stops at first accept, skips `_pack_plan`) and the newer `--fast-fpr-packed` (`TPC_SOLVE_STOP_AT_ACCEPT_PACKED`, stops at first accept but still runs `_pack_plan` so the pin/transport-repair passes execute). Both default off, never set by the real harness, and are FPR-only/uncalibrated — the packed variant is the one to fast-measure the repair passes' FPR in the `900 s` regime (see [eval doc: Gates](tpc_phase2_eval.md#gates)).
- Baselines can run from a pinned source revision and publish committed rows under `results/phase2_baselines/`.
- The official familiar-100 records are imported byte-for-byte with a pinned archive checksum, per-member manifest, dedicated split, and explicit no-oracle boundary.
- **Parser lifted from `~0.20` to `~0.99` familiar-100 F1** with zero missing families — the last step being the comma-in-name entity-resolution segmentation fix (`62df2a0b`, F1 `0.9316 -> 0.9908`; see [Completed parser work](#completed-parser-work)).
- **Timed-window pinning and a within-day resequencer landed opt-in** behind `TPC_PIN_TIMED_WINDOWS` (default off, floor byte-identical), targeting the dominant solver-only failure family. **Gated at `300 s` (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)): quality up, timeouts regress, not promoted. Re-gated clean at `900 s`** (`familiar_100_val`, sha `a72357c3`, rows [floor](../results/phase2_baselines/runs/20260723T200723Z.json)/[pin](../results/phase2_baselines/runs/20260724T071840Z.json)): e2e continuous `43.72 -> 48.04`, FPR `20.0 -> 25.0`, **timeouts `0 -> 0`** — the `300 s` regression was a budget-boundary artifact, not a real cost; `make phase2-gate` **passes**. Paired with `TPC_SOLVE_CONVERGE_PATIENCE=15` ([row](../results/phase2_baselines/runs/20260724T192503Z.json)) quality holds flat while wall-clock drops further (solve `p50` `366s -> 265s`, below even the floor's `337s`). **Promoted (role 3): both are now harness-default-on** via `solve_phase2.apply_deterministic_solver_defaults()` (called at the top of `run_split`, before the agent is built), mirroring the disjunction/entity-resolution promotion pattern — the library default (unset env var) and the byte-identical opt-in unit tests are unchanged, and an explicit operator override (e.g. the eval tooling's flags-off A/B arm) still wins. `TPC_SOLVE_CONVERGE_PATIENCE=15` is defaulted alongside pin both for the wall-clock win and as a hedge: it makes the submission robust to an organizer per-query timeout shorter than the assumed `900 s` (see [Solver-only headroom](#solver-only-headroom)).
- **A commonsense-transport repair pass landed opt-in** behind `TPC_REPAIR_TRANSPORT_GAPS` (default off, floor byte-identical), targeting the "Invalid Transport information across positions" residual (see [Commonsense-transport repair](#commonsense-transport-repair)).
- **An early-convergence stop for the random-restart search landed opt-in** behind `TPC_SOLVE_CONVERGE_PATIENCE` (**library** default `0`/off so the floor stays byte-identical; **harness**-default `15` since the `900 s` promotion in the pinning bullet above), targeting the budget-bound-solver-with-no-early-convergence shortcoming (see [Solver budget and early convergence](#solver-budget-and-early-convergence)).
- **The abbreviation-period truncation residual in the base regex parser is fixed on `main`**, landing directly (unconditional bug fix, not a flag) since it only ever discarded data it should have kept — familiar-100 `wrong_value` `6 -> 3`, F1 `0.9908 -> 0.9949` (see [Completed parser work](#completed-parser-work)).

These capabilities are not evidence of final-evaluation performance.

## Current evidence

The current local reference for the flags-on harness path is [familiar-100 run `20260721T174336Z`](../results/phase2_baselines/runs/20260721T174336Z.json) (`familiar100-negconstraint-llmon`, sha `1de62e99`, two fresh repeats, harness-default flags with `llm_parse` audit on, `300 s` budget). It carries the parser template fixes through `1de62e99` but **predates** the entity-resolution segmentation fix (`62df2a0b`, F1 `0.9316 -> 0.9908`): parser precision/recall/F1 are each `0.9510` with zero missing, mean end-to-end FPR `21.5%`, mean end-to-end `overall_true` `45.06`, solver-only FPR `25.5%`. All `100/100` outputs are valid; zero parse failures, zero fallbacks, zero budget overruns.

Two facts from this row set the roadmap:

1. **Solver-only FPR (`~26`) is now the binding ceiling.** With oracle-perfect constraints the solver still passes only `26/100`, stable across every committed familiar row and repeat. The parser is no longer the bottleneck on familiar-100; the solver is.
2. **The median query runs to the budget wall.** Solve `p50 = 270 s` at a `300 s` budget, and `38/100` end-to-end queries time out (all recovered into valid plans). The restart loop consumes the whole budget rather than converging, so wall-clock is a live constraint and the recovery path is load-bearing.

The earlier promoted anchor was [`20260718T155006Z`](../results/phase2_baselines/runs/20260718T155006Z.json) (`ae6337f0`); it and `20260716T090638Z` predate flag recording and were mislabeled "library-default" — their telemetry (`llm_parse_attempted: 100`) shows they ran the Qwen audit path. Baseline rows now record resolved flags under `flags`.

The `TPC_PIN_TIMED_WINDOWS` gate (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34), sha `110eefae`, paired familiar-100 rows [`20260722T092330Z`](../results/phase2_baselines/runs/20260722T092330Z.json) off / [`20260722T195341Z`](../results/phase2_baselines/runs/20260722T195341Z.json) on) shows fact 1's `~26` ceiling is not fixed but is budget-bound: enabling the flag lifts solver-only continuous `46.99 -> 50.42` and FPR `25.5 -> 30.5`, cleanly separated across both repeats with no overlap (off `[46.40, 47.58]` vs on `[49.48, 51.36]`). But end-to-end timeouts jump `38 -> 57` (+50%) and solver-only timeouts `23 -> 27` — `make phase2-gate` fails on the no-new-timeouts guard at that `300 s` budget, so it is **not promoted** on that pair.

**Re-gated at `900 s` and the guard relaxes cleanly** (`familiar_100_val` 80-query split, one pinned sha `a72357c315bd1fdb7acc43ce9da1a6594fc7356e`, `900 s` budget, 2 repeats, `parallel=3`, harness-default flags otherwise identical across all three rows): [floor](../results/phase2_baselines/runs/20260723T200723Z.json) (no pin/converge), [pin](../results/phase2_baselines/runs/20260724T071840Z.json) (`TPC_PIN_TIMED_WINDOWS=1`), [pin+converge](../results/phase2_baselines/runs/20260724T192503Z.json) (`+ TPC_SOLVE_CONVERGE_PATIENCE=15`).

| | e2e continuous | e2e FPR | solver-only continuous | solver-only FPR | timeouts (e2e / solver-only) | solve `p50` / `p95` |
| --- | --- | --- | --- | --- | --- | --- |
| floor | `43.72 ± 0.22` | `20.0` | `46.86 ± 0.40` | `23.75` | `0 / 0` | `337s / 571s` |
| pin | `48.04 ± 0.64` | `25.0` | `49.38 ± 0.00` | `27.5` | `0 / 0` | `366s / 631s` |
| pin+converge | `47.98 ± 0.94` | `25.6` | `49.54 ± 0.17` | `27.5` | `0 / 0` | **`265s / 499s`** |

Both `make phase2-gate` runs (e2e and solver-only, floor -> pin and floor -> pin+converge) **pass cleanly** — `continuous_score` up, zero new timeouts, zero parse failures on all four. The `300 s` timeout regression was purely a budget-boundary artifact of the extra per-trial deepcopy + full-checker revalidation `_pin_timed_windows`/`_resequence_day` do (PR #34's causal read holds), not a real correctness cost: at `900 s` the restart loop has enough room to absorb it with zero timeouts either way. `TPC_SOLVE_CONVERGE_PATIENCE=15` adds no quality (flat within noise vs pin-alone) but **reclaims the wall-clock pin spends and then some** — pin+converge's `p50`/`p95` beat even the floor's, confirming the roadmap's own hypothesis that converge would absorb the budget pin spends. See [Solver-only headroom](#solver-only-headroom).

The familiar release has no organizer best plans, so its ceiling is unavailable rather than zero. Every number here is a repository-local development result, not an estimate of final held-out performance.

## Shortcomings of the current agent

A review of the Phase 2 path (`chinatravel/agent/phase2/` + the no-oracle `TPCAgent`) against the latest evidence surfaces six shortcomings, roughly in leverage order.

1. **Solver-only ceiling dominated by one family — pinning + resequencer clears the gate at `900 s`.** `26/100` solver-only pass with perfect constraints; `timed_visit_named_poi` is the *sole* logical blocker in `53` of the `74` failures. The landed pinning + resequencer regressed timeouts at the old `300 s` gate (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)) but **passes cleanly re-gated at `900 s`**: solver-only continuous `46.86 -> 49.38`, FPR `23.75 -> 27.5`, **zero timeouts either way** (`familiar_100_val`, sha `a72357c3`) — the `300 s` regression was a budget-boundary artifact of the per-trial deepcopy + full-checker revalidation, not a real cost. Paired with the now-landed early-convergence stop (shortcoming 2, `TPC_SOLVE_CONVERGE_PATIENCE=15`), quality holds flat and wall-clock drops below even the floor's. Evidence clears the promotion bar; flipping the default is role 3's to do. See [Solver-only headroom](#solver-only-headroom).
2. **Budget-bound solver with no early convergence — early-convergence stop landed opt-in, pending gate.** Solve `p50` sits at the budget wall; `38%` of queries time out and survive only through timeout recovery. The seeded-restart loop had no "good enough, stop" signal short of the wall, so extra budget bought little and the recovery plan carried a large share of outputs. `TPC_SOLVE_CONVERGE_PATIENCE` (opt-in, default `0`/off) now stops the random-restart loop once the best accepted plan's preference key has stalled for that many consecutive restarts, distinct from the evaluation-only `TPC_SOLVE_STOP_AT_ACCEPT` (which stops at the *first* accept regardless of score); see [Solver budget and early convergence](#solver-budget-and-early-convergence). Not yet measured through the pinned end-to-end gate, and the restart-count-vs-score curve quantification (which would inform a default patience value) remains open.
3. **Stage 3 "improve" is a no-op — the active implementation target.** `orchestrator.llm_refine_stub` returns the plan unchanged and never calls the LLM (`improve` stage `p50 ≈ 1 µs`). The reserved improve slice is either wasted or, with `dynamic_budget`, reallocated to solve. There is no bounded, acceptance-gated refinement — a designed extension point that is still empty, and now the only "Next steps" item that is a new implementation rather than a gate (Next step 7). See [Stage 3 LLM refine](#stage-3-llm-refine).
4. **Commonsense residual — transport-repair pass landed opt-in, pending gate.** Even at solver-only, `~24/100` fail commonsense, dominated by "Invalid Transport information across positions" (`18`) and intercity-event grounding (`6`). These are produced-but-invalid plans, so the feasible fallback does not help them. Root-caused (PR [#29](https://github.com/stefanbschneider/china-travel-agent/pull/29)) to two `_build_plan`/`_get_transport` bugs: several call sites fall back to an empty `transports` leg while still moving position when a leg lookup fails, and `_get_transport` aborts its whole mode fallback chain on the first candidate mode's exception instead of trying the rest. `_repair_transport_gaps` (opt-in behind `TPC_REPAIR_TRANSPORT_GAPS`, default off) grounds every broken leg in one batched, acceptance-gated trial; see [Commonsense-transport repair](#commonsense-transport-repair) for the mechanism and known limits. Not yet measured through the pinned end-to-end gate.
5. **Parser value-segmentation residual — largely closed, pending gate.** The comma-/`" and "`-in-name `wrong_value` residual was fixed on `main` (`62df2a0b`) via maximum-munch catalog segmentation plus a restaurant/hotel matching-pool broadening, taking familiar-100 F1 `0.9316 -> 0.9908` (wrong_value `47 -> 6`). It is diagnostic evidence only — not yet through the end-to-end gate. The distinct abbreviation-period truncation bug (`"St. Regis"`, `"No. 3955 …"`) in the base regex parser's `_list_after_marker` is now fixed unconditionally on `main` (F1 `0.9908 -> 0.9949`, wrong_value `6 -> 3`; see [Completed parser work](#completed-parser-work)); a `3`-case `excluded_hotels` residual remains from a separate, already-known limit — a comma-heavy full-address value spans more raw tokens than the entity-resolution merge's bounded `_ENTITY_SEGMENT_MAX_SPAN` (`4`), so it stays fragmented rather than re-merging into one catalog name.
6. **LLM-parse decision is not yet cleanly gated end-to-end.** Parser-level evidence says audit mode is neutral-to-negative, yet the harness auto-enables it whenever a backend is configured, and the two end-to-end points that bracket it are at different shas (`nollm` at `7d5e1910`, `llmon` at `1de62e99`) so they conflate parser code with the flag. A paired on/off gate at one sha is now runnable and should settle the auto-enable.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Next steps (priority order)

Execution is split across [parallel agent roles](../CLAUDE.md#parallel-agent-roles): the gate items below are run by the evaluation agent (role 2), the code items by the implementation agent (role 3); this document (role 1) owns their order.

**Pre-gate screen triage (2026-07-22), and how it held up against the gate.** A fast reduced-budget A/B [quick screen](tpc_phase2_eval.md#quick-ab-screen-pre-gate-triage) (solver-only, familiar-100, `n=30`, `60 s`) was run on the three ungated solver flags to rank them for the slow gate: `TPC_PIN_TIMED_WINDOWS` (FPR `20.0 → 26.67`, overall_true `+6.0`) and `TPC_REPAIR_TRANSPORT_GAPS` (FPR `20.0 → 23.33`, overall_true `+2.72`) both lift solver-only quality with a few *recovered* extra timeouts; `TPC_SOLVE_CONVERGE_PATIENCE=15` holds FPR and shaves a timeout. **The pin screen's "green-with-timeout-caveat" verdict was then confirmed by the full pinned gate** (Next step 1, PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)): the gate found the same quality lift *and* the same timeout regression — now large enough at full budget (`38 → 57` end-to-end) to block promotion. The screen called both the benefit and the disqualifying risk in ~20 min, which is exactly its job. The lesson it points to — **pair pin with the early-convergence stop so converge reclaims the budget pin spends** — is the concrete case for [batched, not isolated, e2e](tpc_phase2_eval.md#recommended-cadence-daily-screen-nightly-batched-e2e): screen `pin + converge` together, then gate the batch.

The two LLM flags were screened end-to-end the same day (familiar-100, `n=30`, `90 s`, DeepInfra `Qwen/Qwen3.6-27B`, shared all-LLM-off baseline `overall_true 47.38`) and both come back **do-not-default**, so they do *not* join the batch: `TPC_P2_LLM_PARSE` regresses `overall_true 47.38 → 44.18` once the audit fires on all `30/30` queries (an end-to-end confirmation of the parser-level neutral-to-negative finding — Next step 3 settled toward off), and `TPC_P2_LLM_REFINE` (Stage 3 v1) is called on `18` invalid plans but commits `0` repairs (`8` ungroundable edits, `5` checker-rejected, `5` LLM-errored) while costing `+8` timeouts — flat quality, no benefit yet, so Next step 7's v1 needs groundable, checker-satisfying edits before it earns a gate. (An early `timeout=6` parse screen looked positive only because `10/30` audits timed out into the deterministic fallback; the corrected `timeout=15` run is the real signal — always confirm the LLM fired.)

Going forward, screens and development gates run on the **`tpc_phase2_familiar_100_val`** 80-query split (see [dataset boundaries](tpc_phase2_eval.md#1-official-familiar-100-development-set-preferred-signal)); the held-out **`tpc_phase2_familiar_100_test`** 20 queries are an overfitting tripwire, not a per-change signal.

1. **Gate the solver-headroom step — DONE, clean pass at `900 s`.** At the old `300 s` budget (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34), sha `110eefae`) `TPC_PIN_TIMED_WINDOWS` lifted solver-only continuous `46.99 -> 50.42` and FPR `25.5 -> 30.5` but failed the gate on timeouts (`23 -> 27` solver-only, `38 -> 57` end-to-end). **Re-gated at `900 s`** (`familiar_100_val`, one pinned sha `a72357c315bd1fdb7acc43ce9da1a6594fc7356e`, `900 s` budget, 2 repeats, `parallel=3`): matched triple [floor](../results/phase2_baselines/runs/20260723T200723Z.json) / [pin](../results/phase2_baselines/runs/20260724T071840Z.json) / [pin+converge](../results/phase2_baselines/runs/20260724T192503Z.json). Floor -> pin: e2e continuous `43.72 -> 48.04`, FPR `20.0 -> 25.0`, solver-only continuous `46.86 -> 49.38`, FPR `23.75 -> 27.5`, **timeouts `0 -> 0` on both axes** — the `300 s` regression confirmed as a pure budget-boundary artifact, not a real correctness cost. `make phase2-gate` **passes** on all four checks (e2e + solver-only, both against floor). Floor -> pin+converge also passes cleanly, with quality flat vs pin-alone but solve `p50`/`p95` (`265s`/`499s`) **below even the floor's** (`337s`/`571s`) — `TPC_SOLVE_CONVERGE_PATIENCE=15` reclaims the wall-clock pin spends and then some, confirming the hypothesis from Next step 5. See [Solver-only headroom](#solver-only-headroom) for the full table. **Evidence clears the promotion bar for both `TPC_PIN_TIMED_WINDOWS` and the paired `TPC_PIN_TIMED_WINDOWS` + `TPC_SOLVE_CONVERGE_PATIENCE=15` batch; flipping either default is role 3's to do** (role 2 does not edit code defaults). Standalone `TPC_SOLVE_CONVERGE_PATIENCE` (no pin) remains ungated on its own — Next step 5.
2. **Gate the landed parser fixes together.** The negative-constraint, required-constraint, deterministic-budget, and `required_attraction_types` time-window fixes still need one pinned end-to-end gate against the last promoted familiar row before promotion. The current best flags-on row (`20260721T174336Z`) already carries them but has no matched flags-off counterpart at the same sha.
3. **Settle the LLM-parse auto-enable.** Run paired `llm_parse` on/off rows at one sha (`make phase2-baseline-at SHA=<ref>` with and without `TPC_P2_LLM_PARSE`, now that `phase2_eval_at.py` shares `agent_env/config.toml` into the worktree) and gate on `continuous_score`. If audit adds spurious constraints with no end-to-end benefit, stop the harness auto-enabling it when a backend is configured (`agent_env/scripts/solve_phase2.py::resolve_llm_client_and_flags`).
4. **Gate the commonsense-transport repair pass.** `TPC_REPAIR_TRANSPORT_GAPS` landed opt-in (PR [#29](https://github.com/stefanbschneider/china-travel-agent/pull/29); see [Commonsense-transport repair](#commonsense-transport-repair)), targeting "Invalid Transport information across positions" (`18` solver-only) via a batched, acceptance-gated leg-recomputation pass. Record a clean flags-off baseline, then run the flag on through `make phase2-gate` against a matched baseline; promote only if the commonsense FPR component improves with no new parse failures or timeouts. A residual is already known and out of this pass's bounded scope: legs that need a real cascading time shift (not just a leg fix) to fit — a future resequencing move, not a gate blocker.
5. **Gate the solver early-convergence stop — paired gate DONE (clean), standalone gate still open.** `TPC_SOLVE_CONVERGE_PATIENCE` landed opt-in (default `0`/off; see [Solver budget and early convergence](#solver-budget-and-early-convergence)), stopping the random-restart loop once the accepted plan's preference key stalls for `N` consecutive restarts instead of running to `max_restarts`/the wall-clock budget. **Paired with `TPC_PIN_TIMED_WINDOWS` at `900 s`, `patience=15` confirmed the Next-step-1 hypothesis**: floor -> pin+converge passes `make phase2-gate` clean, quality flat vs pin-alone, solve `p50`/`p95` (`265s`/`499s`) below even the floor's — converge reclaims the wall-clock pin spends and then some (see [Solver-only headroom](#solver-only-headroom)). Still open: a **standalone** flags-off-vs-converge-only `900 s` gate (no pin) and a sweep of patience values beyond the single `N=15` measured — promote a specific value only after that sweep shows wall-clock/timeout rate improves with no drop in solver-only FPR or `continuous_score`. The restart-count-vs-score curve quantification (to pick a sensible default patience) remains open and is a good companion diagnostic, not a gate blocker.
6. **Gate the landed entity-resolution segmentation fix** (`62df2a0b`, comma-in-name residual) and the abbreviation-period truncation fix (unconditional, on `main`; F1 `0.9908 -> 0.9949`, wrong_value `6 -> 3`; see [Completed parser work](#completed-parser-work)) together in one pinned end-to-end row. A `3`-case `excluded_hotels` residual remains out of scope for both fixes — a comma-heavy full-address value exceeds the entity-resolution merge's bounded token span (`_ENTITY_SEGMENT_MAX_SPAN = 4`); widening that span is a separate, not-yet-scoped change (raising it risks over-merging unrelated multi-entity lists elsewhere, so needs its own measurement, not a drive-by bump here).
7. **Implement Stage 3 refine — the active implementation target.** This is now the **only** "Next steps" item that is a new implementation rather than a gate (steps 1–6 are all landed-and-awaiting-role-2 or landed on `main`), so it is the current top implementation item. A bounded, acceptance-gated LLM refinement pass over the solver's chosen plan: the LLM proposes a small set of typed edits, every edited POI/window/price/leg is re-grounded from `WorldEnv`, and the result is committed only if the deterministic checker accepts and the preference key does not regress. Today `orchestrator.llm_refine_stub` is an intentional no-op that never calls the LLM. See [Stage 3 LLM refine](#stage-3-llm-refine) for the design and the dedicated implementation brief [`agents/stage3_llm_refine.md`](agents/stage3_llm_refine.md).
8. **Package and smoke-test the official harness interface**, including oracle hiding, output layout, and tool access (`agent_env/scripts/solve_phase2.py`, `solve_script_with_harness.py`; entry-point smoke tests exist).

The public material still does not specify a runtime contract, so every budget stays an assumption. Since 2026-07-24 the **working expectation is a `~900 s` official per-query timeout**, and development gates run at `900 s` (see [eval doc: Baselines and repetitions](tpc_phase2_eval.md#baselines-and-repetitions)); `300 s` is retained as a faster sensitivity setting and the `30,60,120,300,900` budget sweep guards against a `900 s`-fragile promotion. The original `300 s` gate budget was chosen to make e2e eval fast, not because the organizer confirmed it — so the shift removes a self-imposed constraint, and several landed solver features blocked only by the `300 s` no-new-timeouts guard should be re-gated at `900 s` (Next step 1). Do not overfit any single unconfirmed budget number.

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

Verified by unit tests (`tests/phase2/test_pin_timed_windows.py`, `tests/phase2/test_resequence_day.py`) and, on failing uid `...00062`, the `required_hotels` projection moving the required breakfast onto the named inn.

**Measured through the pinned gate at `300 s` (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34), sha `110eefae`)**: paired familiar-100 rows, off [`20260722T092330Z`](../results/phase2_baselines/runs/20260722T092330Z.json) / on [`20260722T195341Z`](../results/phase2_baselines/runs/20260722T195341Z.json), fold 0/1 (n=100), `300 s` budget, 2 repeats, `parallel=3`, identical flags/backend otherwise. Solver-only continuous `46.99 -> 50.42` (+3.43) and FPR `25.5 -> 30.5` (+5.0), cleanly separated across both repeats with no overlap (off `[46.40, 47.58]` vs on `[49.48, 51.36]`, far beyond the ~`0.5` run-to-run std either row shows alone — proof the flag genuinely fired, since the row itself does not record `TPC_PIN_TIMED_WINDOWS`). But solver-only timeouts rose `23 -> 27` and end-to-end timeouts rose `38 -> 57` (+50%); `make phase2-gate` failed on the no-new-timeouts guard at that budget. Not promoted on that pair.

**Re-gated clean at `900 s`** (`familiar_100_val` 80-query split, one pinned sha `a72357c315bd1fdb7acc43ce9da1a6594fc7356e`, `900 s` budget, 2 repeats, `parallel=3`): matched triple [floor](../results/phase2_baselines/runs/20260723T200723Z.json) / [pin](../results/phase2_baselines/runs/20260724T071840Z.json) / [pin+converge](../results/phase2_baselines/runs/20260724T192503Z.json), harness-default flags otherwise identical across all three.

| | e2e continuous | e2e FPR | solver-only continuous | solver-only FPR | timeouts (e2e / solver-only) | solve `p50` / `p95` |
| --- | --- | --- | --- | --- | --- | --- |
| floor | `43.72 ± 0.22` | `20.0` | `46.86 ± 0.40` | `23.75` | `0 / 0` | `337s / 571s` |
| pin | `48.04 ± 0.64` | `25.0` | `49.38 ± 0.00` | `27.5` | `0 / 0` | `366s / 631s` |
| pin+converge | `47.98 ± 0.94` | `25.6` | `49.54 ± 0.17` | `27.5` | `0 / 0` | **`265s / 499s`** |

`make phase2-gate` **passes** floor -> pin and floor -> pin+converge on both axes (e2e and solver-only) — `continuous_score` up, zero new timeouts (both `0`), zero new parse failures. The `300 s` timeout regression is confirmed a pure budget-boundary artifact of the extra per-trial deepcopy + full-checker revalidation, not a real correctness cost: at `900 s` the restart loop absorbs it with zero timeouts either way. `TPC_SOLVE_CONVERGE_PATIENCE=15` adds no measurable quality on top of pin-alone (flat within noise) but reclaims the wall-clock pin spends and then some — pin+converge's `p50`/`p95` beat even the floor's. **Evidence clears the promotion bar for both configurations; flipping the default(s) is role 3's to do** — see Known limits below.

### Known limits / what the gate must check

- **A rejected idea — do not reintroduce.** Emitting `arrive_no_later` from `end_before` (to time morning meals) **regressed commonsense** on the floor: its ceiling pruned proper transport, producing transport-less plans that fail "Invalid Transport information across positions." It was dropped; do not revive it without gating.
- **Gated at `300 s`, not promoted on that pair (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)); re-gated clean at `900 s` (evidence above).** All 900s rows are also harness-default with `llm_parse` on, not a true flags-off floor (none exists in the ledger yet) — immaterial to the gate, since solver-only bypasses the parser entirely and each pair differs only in the flag(s) under test, so the comparison is materially equivalent to the intended flags-off comparison. At `300 s`: solver-only FPR/continuous improved cleanly but timeouts regressed (no parallelism confound — both `parallel=3`), a genuine, causally-attributed cost from `_pin_timed_windows`/`_resequence_day` trialing every retiming/resequencing candidate via a deepcopy + full-checker revalidation before committing, pushing more queries to the `300 s` wall. At `900 s` that same mechanism costs zero timeouts — the restart loop has enough room to absorb the extra per-candidate work — so the earlier `300 s` gate failure does not indicate a real defect, only a tight-budget artifact. The combined gate pairing this flag with `TPC_SOLVE_CONVERGE_PATIENCE=15` also passes clean at `900 s` and additionally reclaims wall-clock beyond even the floor.
- **Out of scope.** The constraint-light feasible fallback (G7, `fallback.py`'s empty itinerary) does not move solver-only FPR — those failures are produced-but-invalid plans, not solver failures/timeouts.

## Commonsense-transport repair

Diagnostic root-cause of the "Invalid Transport information across positions" commonsense residual (`18/100` familiar-100 solver-only, roadmap shortcoming 4) and the landed opt-in fix (PR [#29](https://github.com/stefanbschneider/china-travel-agent/pull/29)). Development signal only; not yet through the gate (Next step 4).

### The failure mechanism

Reproduced directly against real familiar-100 solver-only runs (e.g. `phase2_familiar_20250321044802265544_00014`, `phase2_familiar_m20241028164821619599_00023` — the latter passes all `11/11` oracle logic clauses and fails *only* commonsense, isolating the bug from the timed-visit family). Two distinct bugs compound:

1. **Silent empty-leg fallback.** Several `_build_plan` call sites follow `if transports is not None: ... else: transports = []`, then still advance `current_pos` to the new activity's position regardless. When `_get_transport` fails, the greedy build keeps the activity rather than abandoning the candidate, producing an activity whose position differs from the previous one with an empty `transports` list — exactly what `Is_space_correct` flags.
2. **`_get_transport` aborts on the first mode's exception.** Its mode-order loop (`metro`, `walk`, `taxi`) is wrapped in one `try/except`; a mode that raises (observed: `env.transportation.goto(..., "metro", ...)` raising `TypeError: string indices must be integers, not 'str'` on some POI pairs) aborts the whole lookup even when a later mode would have succeeded.

### Landed: opt-in transport-gap repair pass (`TPC_REPAIR_TRANSPORT_GAPS`, default off)

Implemented in `chinatravel/agent/tpc_agent/tpc_agent.py`, gated behind `TPC_REPAIR_TRANSPORT_GAPS` (default **off**, so the deterministic floor is byte-identical; asserted by unit tests). When on, `_repair_transport_gaps` runs in `_pack_plan` (before the acceptance gate, before window pinning so an unrelated grounding gap doesn't block that pass):

- Walks the plan in checker order (continuous across day boundaries, matching `Is_space_correct`'s `position_list`), comparing positions via `normalize_poi_name` (not raw strings, so alias-equivalent names are never treated as a gap — fixed after GitHub Copilot review flagged the raw-string comparison on the first version of the PR).
- For every activity whose inbound leg does not already connect to the previous activity's position, recomputes it via `_get_transport_resilient` — a new lookup (used only by this pass) that tries each allowed mode independently so one mode's exception no longer blocks the rest.
- All fixes land in **one** deepcopy trial and commit together only if the full checker then accepts — a single remaining broken leg would still fail the whole-plan checker, so a per-leg commit-on-accept (like `_try_pin_activity`) would never land when several legs are broken at once (the common case observed).
- **Bounded, no cascading shifts:** a fix is skipped if the recomputed arrival would land after the activity's own `start_time` — this pass only grounds/corrects legs, it never re-times the plan.
- The "preference must not regress" guard only applies when the plan was already accepted (a grounded leg has real, nonzero cost where the broken original had none, so comparing unconditionally would always reject the very fix that flips an invalid plan valid).

Verified by unit tests (`tests/phase2/test_repair_transport_gaps.py`, 15 cases covering the flag, single/batched leg repair, the no-cascading-shift bound, the alias-normalization fix, and `_get_transport_resilient`'s per-mode fallback).

### Known limits / what the gate must check

- **Cascading time shifts are out of scope.** Reproduced on `phase2_familiar_m20241028164821619599_00023`: the missing leg needs real travel time (~49 min) the original zero-travel-time schedule left no room for, so the bounded, no-shift repair correctly declines rather than cascading a reorder into downstream activities. A future resequencing move (distinct from this pass) would be needed to close this case.
- **No promotion without the gate.** Record a clean flags-off solver-only familiar-100 baseline, then run flag-on through `make phase2-gate` against a matched baseline; promote only if the commonsense FPR component improves with no new parse failures or timeouts. Restart-search timing is not run-to-run reproducible (wall-clock-bounded restarts pick different random params each run), so a clean paired before/after count needs the pinned gate, not an ad hoc rerun.

## Solver budget and early convergence

Landed opt-in mechanism for roadmap shortcoming 2 (budget-bound solver with no early convergence). Development signal only; not yet through the gate (Next step 5).

### The problem

`_solve`'s multi-start search (`chinatravel/agent/tpc_agent/tpc_agent.py`) runs a base build, a small deterministic repair-params pass, then a random-restart loop that keeps rebuilding candidate plans until either `max_restarts` (`TPC_MAX_RESTARTS`, default `400`) or the wall-clock budget (`TPC_SOLVE_BUDGET_SEC`) is exhausted. Per the current evidence, solve `p50` sits at the budget wall and `38%` of end-to-end familiar-100 queries time out (all recovered into valid plans via the timeout-recovery snapshot, so none of this is a correctness risk today — it is pure wasted wall-clock). Once an accepted plan already exists, the loop has no "the search has plateaued, stop" signal short of the wall: it keeps spending restarts on marginal or zero preference-score improvement instead of returning early.

This is distinct from the existing `TPC_SOLVE_STOP_AT_ACCEPT` (evaluation-tooling only): that flag stops at the very *first* accepted plan regardless of preference score, trading a fast-but-uncalibrated FPR signal for speed. An early-convergence stop instead keeps polishing preference score exactly like the default path, and only stops once further restarts are no longer paying off.

### Landed: opt-in early-convergence stop (`TPC_SOLVE_CONVERGE_PATIENCE`, default off)

Implemented in `_solve`'s random-restart loop (`chinatravel/agent/tpc_agent/tpc_agent.py`), gated behind `TPC_SOLVE_CONVERGE_PATIENCE` (an integer restart count; default `"0"`, which disables the mechanism so the loop's behavior is byte-identical to before — asserted by unit tests). When set to a positive `N`:

- Once an accepted plan exists (`best_accepted["plan"] is not None`), the loop tracks consecutive restarts whose `_accepted_eval_key` fails to improve on the previous best.
- After `N` consecutive non-improving restarts, the loop breaks early — before `max_restarts` or the wall-clock budget — and falls through to the existing `_pack_plan`/finalization path exactly as if the budget or restart cap had been hit.
- The stall counter resets per constraint variant (disjunction branches start a fresh scoring landscape) and never engages before any plan is accepted, so a query that is still searching for *any* accepted plan always runs its full restart/budget allowance, same as today.
- No change to the base build, the deterministic repair-params pass, or the CP-SAT branch — only the random-restart loop's stopping condition changes, and only when the flag is set.

Verified by unit tests (`tests/phase2/test_solve_converge_patience.py`, 4 cases: the flag-off byte-identical floor, early stop once the preference key plateaus, full-budget exploration when the key never plateaus, and full-budget exploration when nothing is ever accepted).

### Known limits / what the gate must check

- **No default patience value yet.** The roadmap's restart-count-vs-score curve quantification (informing a sensible default `N`) is still open; this lands the mechanism, not a chosen default. `N=15` is only what has been measured so far (screens and the `900 s` batched gate), not a validated optimum.
- **Gated paired with `TPC_PIN_TIMED_WINDOWS`, not standalone.** The `900 s` batched gate (see [Solver-only headroom](#solver-only-headroom)) measured `patience=15` stacked on top of pin — floor -> pin+converge passes clean, quality flat vs pin-alone, wall-clock reclaimed below even the floor. That is strong evidence converge does its job when paired, but a standalone flags-off-vs-converge-alone `900 s` gate (no pin) has not been run — the sweep-multiple-patience-values, converge-only gate this item originally asked for remains open.

## Stage 3 LLM refine

Design for roadmap shortcoming 3 / Next step 7 — the active implementation target and the only remaining "Next steps"
item that is a new implementation rather than a gate. Not yet implemented; this section is the plan. The dedicated
implementation brief is [`agents/stage3_llm_refine.md`](agents/stage3_llm_refine.md).

### The problem

`orchestrator.llm_refine_stub` (`chinatravel/agent/phase2/orchestrator.py`) returns the plan unchanged and never calls
the LLM, so the `improve` stage is a no-op (`improve` `p50 ≈ 1 µs`). The stage is otherwise fully wired — a
`func_timeout`-bounded slice (`b.improve_sec`), revert-to-last-valid on timeout/exception/invalid-shape, telemetry, and a
`dynamic_budget` reserve (`dynamic_solve_sec(..., improve_reserved=flags.llm_refine)`) — so the reserved slice is simply
wasted (or, with `dynamic_budget`, handed to solve). There is no bounded, acceptance-gated refinement of the solver's
plan: a designed extension point that is still empty.

### Why it is well-placed

The orchestrator's Stage 4 gate is **shape-only**: `_valid_plan_shape` checks that `itinerary` is a list, not that the
plan passes the semantic checker. A produced-but-invalid plan is therefore emitted verbatim (it is not replaced by the
constraint-light fallback, which only fires when the candidate is not even plan-shaped). Solver-only FPR (`~26/100`) is
the binding ceiling, and those failures are produced-but-invalid plans — so **Stage 3 is the only stage left that can
flip such a plan to accepted end-to-end.** It complements the landed deterministic repair passes
(`_pin_timed_windows`, `_repair_transport_gaps`) by covering exactly the cases they decline — e.g. a leg or window that
needs a real cascading time shift / resequencing rather than a local leg fix.

### Planned mechanism (v1: repair, not polish)

Gated behind the existing `TPC_P2_LLM_REFINE` / `Flags.llm_refine` (default **off**, floor byte-identical, zero LLM calls
on the deterministic path):

- **Repair-only in v1.** If the input plan already passes acceptance, no-op and return it — the solver's restart loop
  already spends its whole budget polishing DAV/ATT/DDR (shortcoming 2), so preference-lift on an already-valid plan is
  low-value/high-risk and is deferred to a documented stretch behind its own sub-flag.
- **LLM proposes, deterministic path disposes.** Build a repair prompt from the visible query fields only (mirroring
  `build_llm_parse_prompt`'s allowlist), the current plan, and the no-oracle checker's failure summary; ask for strict
  JSON with a small, bounded list of typed edits (reorder/shift/swap/drop) — no free-form rewrites. Every edited
  POI/window/price/leg is re-grounded from `WorldEnv`; a reference the environment cannot ground is dropped, never
  fabricated.
- **Acceptance-gated, deepcopy-trialed.** Apply edits to a deepcopy and commit only if the full deterministic checker
  accepts and `_accepted_eval_key` does not regress vs. the input — the same commit rule as `_pin_timed_windows` /
  `_resequence_day`. On LLM error, timeout, invalid JSON, or no accepted improvement, return the input plan unchanged.
- **Wiring.** Keep Stage 3 in the orchestrator (its separate `improve_sec` slice and revert-to-last-valid safety are
  deliberate); expose a `ground_and_check` hook off the TPCAgent-backed `solve_fn` the way `make_tpcagent_solve_fn`
  already exposes `get_timeout_recovery_plan`, so the refine can ground + check + read failures without moving into
  `TPCAgent.run()` (which would spend the solve budget). When the hook is absent (unit tests inject a bare `solve_fn`),
  refine no-ops.

### Known limits / what the gate must check

- **No oracle, no fabrication.** The checker used is the no-oracle one (`_make_checker`, `use_oracle=False`), which scores
  against parsed `constraints`, not `hard_logic_py`; the prompt must carry no oracle field. The gate must confirm the
  floor stays byte-identical with the flag off.
- **Repair is strictly non-regressing by construction** (commit only on accept + no eval-key regression), so the risk is
  wasted budget, not a worse plan. The gate should measure whether it flips any produced-but-invalid plan to accepted
  end-to-end (FPR / `continuous_score`) with no new parse failures or timeouts, and watch the `improve` slice's wall-clock
  cost (one bounded LLM call must fit the `~30 s` improve slice at a `300 s` budget).
- **No promotion without the gate.** Role 2 runs a paired `TPC_P2_LLM_REFINE` on/off gate at one SHA (backend reachable
  for the on run); role 1 records the outcome. As with every landed feature, an ad hoc rerun does not promote it.

## Completed parser work

The parser rose from `~0.20` to `~0.99` familiar-100 F1 (solver-free `scripts/parser_vs_oracle.py --split tpc_phase2_familiar_100`; the template fixes run flags-off, the final segmentation row with entity resolution on) through a sequence of structural fixes. Full per-family tables and the chronological narrative are preserved in the [archive](archive/README.md); the headline sequence and the durable lessons:

| Stage (sha) | precision | recall | F1 |
| --- | --- | --- | --- |
| Baseline | 0.4445 | 0.1281 | 0.1988 |
| Activity-window fix (`ae6337f0`) | 0.8180 | 0.3518 | 0.4920 |
| Deterministic-budget templates (`c428dd6c`) | 0.8502 | 0.4561 | 0.5937 |
| Negative-constraint fix | 0.8620 | 0.8036 | 0.8317 |
| Required-constraint fix | 0.9402 | 0.9487 | 0.9444 |
| `required_attraction_types` time-window guard | 0.9510 | 0.9510 | 0.9510 |
| Entity-resolution catalog segmentation (`62df2a0b`) | — | — | 0.9908 |
| Abbreviation-period truncation fix | 0.9949 | 0.9949 | 0.9949 |

(The entity-resolution row is measured with entity resolution on, `--disjunction --entity-resolution --branch-aware`; it drops familiar-100 `wrong_value` `47 -> 6` and moves val F1 `0.7869 -> 0.7949`. The reference run `20260721T174336Z` predates it, so its `0.9510` does not yet reflect this fix. The abbreviation-period row is measured the same way, on top of it: `wrong_value` `6 -> 3` (`totals.matched 685 -> 688`); it is an unconditional base-parser fix, not gated by a flag, so it also applies flags-off.)

Why familiar-100 needed this while val did not: familiar records average `~38` `hard_logic_py` constraints each vs. `~16` in the released Phase 1 source `tpc_phase2_val` is partitioned from. The dominant gap was five negative families the parser extracted **zero** of (`excluded_cuisine_types`, `excluded_hotels`, `excluded_attractions`, `excluded_restaurants`, `excluded_attraction_types`) — `266` of `359` missing constraints — encoded in the oracle as `result=not({<names>} & <set>)` and surfaced in one uniform `Do not include any of these <category>: A, B and C.` template. All five now have zero missing.

Durable parser lessons (each landed with a val-inert guard, so the phase-1 partition stayed byte-identical):

- **Anchor the category at the `:` list marker** so a name category (`hotels`) never fires on a sibling type category (`hotel feature types`).
- **Use verbatim values for type families** — the NL uses the oracle's own vocabulary/casing; routing through the lower-casing alias table drops unaliased types.
- **Protect compound vocabulary** read from committed `database_en` CSVs (cuisine values like `Fast food and casual dining` legitimately contain `" and "`).
- **Handle Oxford commas** so `A, B, and C` leaves no `and C` fragment.
- **Never scan a POI name for a naive type substring** — strip `Visit X between A and B` window lines before the known-types substring check (the fix that removed the last `required_attraction_types` spurious entries).
- **Segment entity lists by maximum-munch against the catalog, with a strict exact match** — a catalog name can itself contain an internal `,`/`" and "` (`Honey Lake 1979 Cultural and Creative Park`), so `_segment_entity_list`/`_merge_fragmented_list_entries` prefer the longest span that resolves exactly; reusing the lenient ≥60%-containment match let a longer candidate silently absorb the next distinct entry. A restaurant-family clause can also legitimately name a hotel (a free hotel breakfast positioned at the hotel's own name), so broaden that family's pool to `{restaurant, hotel}` rather than rerouting the match away.

### Abbreviation-period truncation fix

The `6`-case `wrong_value` residual left after the segmentation fix (`excluded_hotels`/`excluded_restaurants`, `3` each) was a distinct upstream bug from the comma-in-name segmentation entity resolution handles: `_list_after_marker` (`parse_constraints.py`, shared by `_do_not_include_items`/`_the_following_items` across required/excluded attractions, attraction types, hotels, restaurants, and cuisine types) captured its name-list chunk with `(.+?)(?:\.|;|$)`. The terminator alternative `\.` matches a literal period unconditionally, with no way to distinguish a real sentence-ending period from one embedded inside an entity name — so the *first* literal period anywhere in the chunk ended the capture (`"St. Regis"`, `"No. 3955 Baishi Road ..."`), silently discarding the rest of the list rather than just mis-splitting it.

Fixed unconditionally on `main` (not gated by a flag — a base-parser correctness fix that only ever discarded data it should have kept, so there is no deterministic-floor tradeoff to preserve): a period is no longer treated as the list terminator when it directly follows one of a short closed set of address/title abbreviations (`St`, `No`, `Mt`, `Dr`, `Mr`, `Mrs`, `Ms`, `Rd`, `Co`, `Jr`, `Sr`, `Ft`, `Ave`, `Inc`, `Ltd`, `Blvd`), each checked as a whole word via a fixed-width lookbehind (grouped by width, since Python's `re` requires each lookbehind assertion to be fixed-width). Deliberately **not** also gated on "not followed by a digit": familiar-100's requirements are numbered lists (`"... 9. Do not include any of these attractions: X.\n10. Dine at ..."`), so a genuine end-of-item period is routinely followed by whitespace + the next item's digit — a digit-lookahead guard was tried first and immediately regressed nearly every list family (familiar-100 F1 `0.9908 -> 0.724`) by swallowing every subsequent numbered requirement into the capture; it was dropped in favor of the abbreviation-lookbehind-only signal, which is both correct on the target cases and neutral everywhere else.

Verified by unit tests (`tests/phase2/test_parser_abbreviation_period.py`, 6 cases covering both real familiar-100 examples, the sentence-boundary floor, and a regression guard for the rejected digit-lookahead approach).

Familiar-100 `wrong_value` `6 -> 3`, F1 `0.9908 -> 0.9949` (diagnostic, `scripts/parser_vs_oracle.py --split tpc_phase2_familiar_100 --disjunction --entity-resolution --branch-aware`). A `3`-case `excluded_hotels` residual remains, out of this fix's scope: the two named accommodations in the affected records are full multi-comma addresses (e.g. `"Mangonet Building, No. 3955 Baishi Road, Nanshan District, Shenzhen, Guangdong, China"`, `6` comma-separated tokens) that the base parser now captures completely but the entity-resolution merge (`_merge_fragmented_list_entries`) cannot re-join, because its token span is bounded (`_ENTITY_SEGMENT_MAX_SPAN = 4`) to avoid over-merging unrelated multi-entity lists elsewhere. Widening that span is a separate, not-yet-scoped change (Next step 6).

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
