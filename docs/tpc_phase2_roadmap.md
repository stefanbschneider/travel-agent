# TPC 2026 Phase 2 Roadmap

This is the active Phase 2 plan.
Historical experiments, superseded plans, and long-form chronology are in the [Phase 2 archive](archive/README.md).
For measurement rules and dataset boundaries, see [Phase 2 evaluation](tpc_phase2_eval.md).

## Current status snapshot

Current reference row: [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json)
(`familiar_100_val`, `900 s`, `a72357c3`, pin+converge defaults on).

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
- **A cascading forward-shift move for the post-pin residual landed opt-in** behind `TPC_CASCADE_TIMED_WINDOWS` (default off, floor byte-identical), targeting the *post-pin* `timed_visit_named_poi` residual — the case where the day is already in the right order but clamping a windowed activity into its window ripples a delay onto the following activities, which `_try_pin_activity` reverts and `_resequence_day` skips. **Gated at `900 s`: no measurable effect, not promoted** (see [Cascading timed-window shift](#cascading-timed-window-shift)).
- **An early-convergence stop for the random-restart search landed opt-in** behind `TPC_SOLVE_CONVERGE_PATIENCE` (**library** default `0`/off so the floor stays byte-identical; **harness**-default `15` since the `900 s` promotion in the pinning bullet above), targeting the budget-bound-solver-with-no-early-convergence shortcoming (see [Solver budget and early convergence](#solver-budget-and-early-convergence)).
- **The abbreviation-period truncation residual in the base regex parser is fixed on `main`**, landing directly (unconditional bug fix, not a flag) since it only ever discarded data it should have kept — familiar-100 `wrong_value` `6 -> 3`, F1 `0.9908 -> 0.9949` (see [Completed parser work](#completed-parser-work)).
- **The current reference row is already LLM-backed at Stage 1.** [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json) records `llm_config.backend=deepinfra`, `TPC_P2_LLM_PARSE=1`, and `llm_parse_attempted=80`, `llm_parse_failed=0`. The main harness is therefore not LLM-free today; the open decision is whether keeping parse audit on is helping enough to justify the cost/risk.
- **Late-night current-`main` rows did not reveal a new promotion candidate.** On sha `6d354b99`, the single-repeat `900 s` rows [baseline](../results/phase2_baselines/runs/20260725T202012Z.json), [cascade](../results/phase2_baselines/runs/20260725T214823Z.json), [transport](../results/phase2_baselines/runs/20260725T231555Z.json), [intercity](../results/phase2_baselines/runs/20260726T004345Z.json), and [all3](../results/phase2_baselines/runs/20260726T034030Z.json) all kept e2e FPR flat at `21.25`; `all3` nudged `overall_true` to `45.43`, but every arm stayed below the last known good [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json) row's `47.04`. Treat these as cautionary screens, not promotion evidence.
- **A current-head quick screen makes `TPC_P2_LLM_PARSE` the first policy decision for the final evening.** Local `2026-07-26` end-to-end screen on `main` (`n=10`, `60 s`, DeepInfra timeout `6 s`) gave parse off `FPR 30.0`, `overall_true 54.48`, `1` timeout vs. parse audit on `FPR 20.0`, `overall_true 45.54`, `2` timeouts. That is not enough to promote parse-off by itself, but it is strong enough to stop assuming the current auto-enabled audit is helping current head.

- End-to-end: FPR `25.0`, `overall_true 47.04`
- Solver-only: FPR `27.5`, `overall_true 49.72`
- Reliability: zero parse failures, zero timeouts, zero fallbacks

Interpretation:

1. Solver-side quality remains the binding ceiling.
2. The earlier `300 s` timeout regressions for pinning were budget-boundary artifacts; the promoted `900 s` setting absorbs them.
3. Remaining gains are mostly from solver/repair/refine improvements, not parser recovery.
4. The harness does use the LLM today, but only for Stage 1 parse audit; the highest-leverage late decision is whether to keep that call at all.

## Main insights

- **Parser is no longer the main bottleneck.** Familiar-100 parser quality is already high (latest headline F1 `0.9949`), and incremental parser fixes now have smaller end-to-end leverage than solver-side work.
- **Promoted deterministic defaults are stable.** `TPC_PIN_TIMED_WINDOWS` plus `TPC_SOLVE_CONVERGE_PATIENCE=15` passed `900 s` gates cleanly and are now harness defaults.
- **Most additional deterministic repair flags are now de-prioritized by evidence, not by missing implementation.** `TPC_REPAIR_TRANSPORT_GAPS`, `TPC_REPAIR_INTERCITY`, and `TPC_CASCADE_TIMED_WINDOWS` all exist and are tested; the latest current-`main` rows do not justify a last-minute default flip.
- **LLM-assisted paths remain selective.** The harness already calls DeepInfra/Qwen in Stage 1 when a backend is configured, but current-head evidence now points toward *less* LLM by default, not more: audit parse regressed on the latest quick screen, `TPC_P2_LLM_PARSE_MODE=extract` exists but is unmeasured, and both Stage 3 refine variants still have near-zero accepted commit rate.

## Phase 2 guardrails

- Organizer execution is per-query and no-oracle: visible query text in, no `hard_logic*` fields in the planning path.
- Stable stage flow is: parse/normalize -> branch-local solve -> acceptance-gated pack/refine -> finalize + telemetry.
- LLM steps are proposals only; grounded facts and acceptance decisions remain deterministic.
- Any optional feature must preserve a deterministic fallback and explicit run-time flag/telemetry visibility.

## Completed capabilities (condensed)

- No-oracle per-query orchestrator is in place with deterministic fallback and telemetry.
- Rehearsal and baseline ledger tooling are operational with pinned-sha comparability.
- Familiar-100 import/provenance and val/test split boundaries are established.
- Major parser recovery is complete (`~0.20 -> ~0.99+` familiar-100 F1).
- Pinning + resequencing + converge pairing is promoted at `900 s`.
- `TPC_REPAIR_TRANSPORT_GAPS` and Stage 3 refine v1 are implemented behind flags.
- `TPC_REPAIR_INTERCITY` endpoint grounding repair is implemented behind a flag.

Both `make phase2-gate` runs (e2e and solver-only, floor -> pin and floor -> pin+converge) **pass cleanly** — `continuous_score` up, zero new timeouts, zero parse failures on all four. The `300 s` timeout regression was purely a budget-boundary artifact of the extra per-trial deepcopy + full-checker revalidation `_pin_timed_windows`/`_resequence_day` do (PR #34's causal read holds), not a real correctness cost: at `900 s` the restart loop has enough room to absorb it with zero timeouts either way. `TPC_SOLVE_CONVERGE_PATIENCE=15` adds no quality (flat within noise vs pin-alone) but **reclaims the wall-clock pin spends and then some** — pin+converge's `p50`/`p95` beat even the floor's, confirming the roadmap's own hypothesis that converge would absorb the budget pin spends. Both are now harness-default-on (PR [#41](https://github.com/stefanbschneider/china-travel-agent/pull/41)). See [Solver-only headroom](#solver-only-headroom).

**Gated the cascade fallback (`TPC_CASCADE_TIMED_WINDOWS`) at `900 s` — no measurable effect, not promoted.** Matched pair, `TPC_PIN_TIMED_WINDOWS=1` baseline vs `+ TPC_CASCADE_TIMED_WINDOWS=1` candidate, `familiar_100_val`, `900 s`, 2 repeats, `parallel=3`: baseline [`20260725T130809Z`](../results/phase2_baselines/runs/20260725T130809Z.json), candidate [`20260726T004535Z`](../results/phase2_baselines/runs/20260726T004535Z.json). `make phase2-gate` passes both axes, but solver-only — the axis cascade directly acts on — is flat (continuous `+0.004`) within the baseline's own repeat noise, and the fast screen run first overstated the effect and even flipped sign on solver-only. See [Cascading timed-window shift: Gate result](#gate-result-900-s-no-measurable-effect) for the full breakdown.

The familiar release has no organizer best plans, so its ceiling is unavailable rather than zero. Every number here is a repository-local development result, not an estimate of final held-out performance.

## Last-evening plan (2026-07-26)

This is the final realistic plan before the submission window closes. It assumes **no new long end-to-end gates tonight**: only focused unit tests, quick paired screens, and explicit flag choices are still worth the time.

1. **Protect the last known good floor first.** Treat [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json) (`a72357c3`, pin+converge on) as the submission safety net. Do not enable `TPC_CASCADE_TIMED_WINDOWS`, `TPC_REPAIR_TRANSPORT_GAPS`, `TPC_REPAIR_INTERCITY`, `TPC_P2_LLM_REFINE`, or `TPC_P2_LLM_AGENTIC_REFINE` by default unless a same-SHA quick screen turns clearly green tonight.
2. **Settle the `TPC_P2_LLM_PARSE` policy before anything else.** The current-head screen is RED for audit-on vs. parse-off, so stop assuming backend auto-enable is helping. If there is time for exactly one more parser experiment, make it a three-arm quick screen on the same subset/budget: parse off vs. audit on vs. extract on (`TPC_P2_LLM_PARSE_MODE=extract`). The bar for shipping any LLM parse mode tonight is simple: beat parse-off on both FPR and `overall_true`, with no new parse failures. If no arm clears that bar, force `TPC_P2_LLM_PARSE=0` for the submission harness instead of relying on backend auto-enable.
3. **Do not spend more long-eval budget on the landed deterministic repair flags.** The late `6d354b99` rows are flat on FPR and mostly worse or noisy on `overall_true` versus the same-SHA pin+converge baseline. `TPC_CASCADE_TIMED_WINDOWS` is already a no-go from the 2-repeat gate, and `TPC_REPAIR_TRANSPORT_GAPS` / `TPC_REPAIR_INTERCITY` are implemented-and-tested but not currently earning promotion. If one cheap interaction check is still desired, use **one stacked quick screen** (`all3-on` vs. current baseline) only; do not launch separate long gates.
4. **Treat Stage 3 refine as a stretch only if it starts committing immediately.** `TPC_P2_LLM_REFINE` v1 is real code, not a stub: hooks, prompt, failure summary, feasible-window context, and acceptance gate all exist, and the targeted unit tests pass. The only acceptable tonight investment is one focused prompt/hook tweak followed by a short end-to-end screen that shows `improve_committed > 0`. If commits remain `0`, keep both `TPC_P2_LLM_REFINE` and `TPC_P2_LLM_AGENTIC_REFINE` off and stop.
5. **Do not start new mechanisms tonight.** No new solver move, no new agentic tool loop, no new parser family. The only realistic late win is a better flag/configuration choice on top of the code already in `main`.
6. **Freeze early and ship the cleanest evidence-backed configuration.** Best-case late improvement: pin+converge plus a clearly better parser policy. Otherwise, ship the last known good deterministic floor rather than stacking more experimental flags.

## Shortcomings of the current agent

A review of the Phase 2 path (`chinatravel/agent/phase2/` + the no-oracle `TPCAgent`) against the latest evidence surfaces six shortcomings, roughly in leverage order.

1. **Solver-only ceiling dominated by one family — pinning + resequencer clears the gate at `900 s`.** `26/100` solver-only pass with perfect constraints; `timed_visit_named_poi` is the *sole* logical blocker in `53` of the `74` failures. The landed pinning + resequencer regressed timeouts at the old `300 s` gate (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)) but **passes cleanly re-gated at `900 s`**: solver-only continuous `46.86 -> 49.38`, FPR `23.75 -> 27.5`, **zero timeouts either way** (`familiar_100_val`, sha `a72357c3`) — the `300 s` regression was a budget-boundary artifact of the per-trial deepcopy + full-checker revalidation, not a real cost. Paired with the now-landed early-convergence stop (shortcoming 2, `TPC_SOLVE_CONVERGE_PATIENCE=15`), quality holds flat and wall-clock drops below even the floor's. Evidence clears the promotion bar; flipping the default is role 3's to do. See [Solver-only headroom](#solver-only-headroom).
2. **Current-head absolute performance is not yet a monotonic signal.** The late single-repeat `900 s` rows on `6d354b99` (`final-baseline-pinconv` and companions) sit materially below the promoted `a72357c3` row, so late decisions must compare against a same-SHA baseline and not assume `main` is automatically better because it is newer. Tonight's risk is regression-by-accumulation, not lack of options.
3. **Stage 3 "improve" is wired, but still acts like a zero-gain feature.** `TPC_P2_LLM_REFINE` is no longer a stub: the orchestrator calls it, `TPCAgent` exposes `ground_and_check` / `apply_refine_edits`, and the failure summary already includes per-clause items, broken-leg diagnostics, and feasible windows. The remaining problem is commit rate: current refine and agentic-refine screens still show `improve_committed=0`, so the gap is now behavioral, not plumbing. See [Stage 3 LLM refine](#stage-3-llm-refine).
4. **Commonsense residual fixes exist, but current evidence does not justify flipping them on.** `TPC_REPAIR_TRANSPORT_GAPS` and `TPC_REPAIR_INTERCITY` are both implemented and unit-tested; the latest single-repeat `900 s` rows on `6d354b99` are flat on FPR and not convincingly positive on `overall_true` vs. the same-SHA baseline. That makes them poor final-evening promotion candidates even though they remain valid future work.
5. **Parser value-segmentation residual — largely closed, pending gate.** The comma-/`" and "`-in-name `wrong_value` residual was fixed on `main` (`62df2a0b`) via maximum-munch catalog segmentation plus a restaurant/hotel matching-pool broadening, taking familiar-100 F1 `0.9316 -> 0.9908` (wrong_value `47 -> 6`). It is diagnostic evidence only — not yet through the end-to-end gate. The distinct abbreviation-period truncation bug (`"St. Regis"`, `"No. 3955 …"`) in the base regex parser's `_list_after_marker` is now fixed unconditionally on `main` (F1 `0.9908 -> 0.9949`, wrong_value `6 -> 3`; see [Completed parser work](#completed-parser-work)); a `3`-case `excluded_hotels` residual remains from a separate, already-known limit — a comma-heavy full-address value spans more raw tokens than the entity-resolution merge's bounded `_ENTITY_SEGMENT_MAX_SPAN` (`4`), so it stays fragmented rather than re-merging into one catalog name.
6. **The LLM-parse policy is unresolved and is the only LLM-side switch likely to matter tonight.** The main harness does call DeepInfra/Qwen today (for example, `llm_parse_attempted=80/80` on [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json)), but the latest paired quick screen on `main` is RED for audit-on vs. parse-off. `TPC_P2_LLM_PARSE_MODE=extract` exists and is unit-tested, but has no screening evidence yet, so the remaining work is a fast policy choice, not more parser plumbing.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Next steps (priority order)

1. **Freeze the submission floor around the last known good measured config.** Keep [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json) behavior (pin+converge on, everything else off) as the safety net, and compare any late change only against a same-SHA baseline.

2. **Settle `TPC_P2_LLM_PARSE` with quick screens, not intuition.** Screen parse off vs. audit on, and only add `TPC_P2_LLM_PARSE_MODE=extract` if there is time for one extra three-arm comparison. If no LLM parse mode clearly beats parse off on FPR and `overall_true`, ship with `TPC_P2_LLM_PARSE=0` explicitly.

3. **Do not promote transport/intercity/cascade from the current evidence.** `TPC_CASCADE_TIMED_WINDOWS` is already a no-go from the 2-repeat gate, and the late single-repeat `TPC_REPAIR_TRANSPORT_GAPS` / `TPC_REPAIR_INTERCITY` rows do not justify more long eval tonight. At most, run one stacked quick screen if an interaction check is still desired.

4. **If touching Stage 3 refine at all, require an immediate commit-rate signal.** One focused tweak plus one short screen is acceptable; more than that is not. The success bar is `improve_committed > 0` with no quality regression. If that bar is missed, keep both refine variants off.

5. **Start no new mechanisms.** No new solver move, no new parser family, no new agentic loop. The final-evening upside is configuration choice, not fresh architecture.

**Status note, not a priority item: the cascade fallback for the residual pin leaves behind (`TPC_CASCADE_TIMED_WINDOWS`) gated at `900 s` with no measurable effect** — flat on solver-only (its own target axis), and the apparent end-to-end lift does not clear its own repeat-to-repeat noise; see [Cascading timed-window shift](#cascading-timed-window-shift) for the full breakdown. Not promoted.

The public material still does not specify a runtime contract, so every budget stays an assumption. Since 2026-07-24 the **working expectation is a `~900 s` official per-query timeout**, and development gates run at `900 s` (see [eval doc: Baselines and repetitions](tpc_phase2_eval.md#baselines-and-repetitions)); `300 s` is retained as a faster sensitivity setting and the `30,60,120,300,900` budget sweep guards against a `900 s`-fragile promotion. The original `300 s` gate budget was chosen to make e2e eval fast, not because the organizer confirmed it — so the shift removed a self-imposed constraint, and the remaining final-evening question is no longer "should these landed flags be re-gated at `900 s`?" but "which already-measured configuration is safest to ship?" Do not overfit any single unconfirmed budget number.

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

## Cascading timed-window shift

Opt-in mechanism (`TPC_CASCADE_TIMED_WINDOWS`, default off, floor byte-identical) for the **post-pin** `timed_visit_named_poi` residual — still the dominant solver-only failure family *after* `TPC_PIN_TIMED_WINDOWS`. **Gated at `900 s`: no measurable effect, not promoted** (see [Gate result](#gate-result-900-s-no-measurable-effect) below).

### The residual pin leaves

Solver-only failure attribution on the committed pin-on row ([`20260722T195341Z`](../results/phase2_baselines/runs/20260722T195341Z.json), `scripts/phase2_solver_failure_attribution.py`) shows `timed_visit_named_poi` is *still* the sole logical blocker in **53 of 70 failing queries** with pin on. Reproducing failing plans isolates one mechanism pin does not cover: the day is already in the **correct order**, but a windowed activity is slotted just before its `[earliest, end_before]` window, and clamping it into the window would push the *following* activity later. Neither landed move handles this:

- `_try_pin_activity` recomputes the next activity's inbound leg and **reverts** whenever the retimed target pushes that next activity past its start ("no cascading reorder", `tpc_agent.py`).
- `_resequence_day` returns early when the window-sorted order **equals the current order** — so a day that only needs a forward *time* shift, not a reorder, is skipped.

### Landed: opt-in cascading forward-shift (`TPC_CASCADE_TIMED_WINDOWS`, default off)

`_enforce_windows_in_order` (`tpc_agent.py`) runs as a **third fallback inside `_pin_timed_windows`**, only after both `_try_pin_activity` and `_resequence_day` fail for a window, and only when the flag is set (so the pin flow — and the deterministic floor — is byte-identical when off; asserted by unit tests). It re-lays the day's contiguous movable (meal/attraction) block in its **current order** with the clause windows honored, reusing the already-tested `_relayout_movable_block`: each windowed slot is clamped to `max(arrival, earliest)` and the resulting delay ripples through every following inbound leg. Bounds are inherited from `_relayout_movable_block`:

- Intercity legs and the day's fixed head/tail are never moved; if the ripple makes a downstream fixed activity (e.g. an evening train) unreachable, the relayout fails and nothing is committed.
- Deepcopy-trialed and committed only if the full checker still accepts and the preference key does not regress — the same commit rule as `_try_pin_activity` / `_resequence_day`.
- **Forward ripple only.** This move shifts the target and its *successors* later; a target that needs to move *earlier* (pulling its predecessors back) is out of scope and left to `_resequence_day` / future work.
- **Only meaningful with `TPC_PIN_TIMED_WINDOWS`**, since it is a fallback inside `_pin_timed_windows`.

Verified by unit tests (`tests/phase2/test_cascade_timed_windows.py`, 5 cases: the flag-off byte-identical floor via a fallback-not-invoked spy, a committed cascading shift, the tail-unreachable revert, the no-windows no-op, and the flag-on end-to-end pin-flow fix).

### Gate result (`900 s`): no measurable effect

**Gated at `900 s`** against a matched pin-on baseline (`familiar_100_val`, 2 repeats, `parallel=3`): baseline [`20260725T130809Z`](../results/phase2_baselines/runs/20260725T130809Z.json) (`TPC_PIN_TIMED_WINDOWS=1`) vs candidate [`20260726T004535Z`](../results/phase2_baselines/runs/20260726T004535Z.json) (`+ TPC_CASCADE_TIMED_WINDOWS=1`).

| | e2e continuous | e2e FPR | solver-only continuous | solver-only FPR | timeouts (e2e / solver-only) |
| --- | --- | --- | --- | --- |--- |
| pin-only (baseline) | `47.66 ± 0.18` | `25.0` | `50.13 ± 0.73` | `28.125` | `0 / 0` |
| pin + cascade | `48.14 ± 0.44` | `26.25` | `50.13 ± 0.42` | `28.75` | `0 / 0` |

`make phase2-gate` passes both axes (no regression, zero new timeouts/parse failures), but **the effect is not distinguishable from noise**:

- **Solver-only — the axis cascade directly acts on — is flat.** Continuous `50.126 -> 50.131` (+0.004); FPR `+0.625` (half a query on `n=80`) against a baseline whose own two repeats already span `27.5`-`28.75`, a `1.25`-point spread twice the observed delta.
- **End-to-end shows a larger apparent lift but the per-repeat ranges overlap** (`[47.48, 47.84]` baseline vs `[47.69, 48.58]` candidate) — contrast the pin-vs-floor gate above, where the ranges were cleanly separated with no overlap. A purely solver-side mechanism moving the noisier, parser-laden e2e axis more than its own clean solver-only axis is the wrong causal direction for a real effect.
- **The `--fast-fpr-packed` screen run first (same sha, single pass, full `n=80`) overstated the effect and even flipped sign on solver-only**: FPR `27.5 -> 31.25` (+3.75, six times the full gate's `+0.625`) and continuous `50.87 -> 50.53` (**-0.35**, vs the full gate's flat `+0.004`). Stopping at first-accept-then-pack under-uses the restart budget that, at the full `900 s`, already resolves most of what the residual pin leaves behind — so the packed screen hands a rarely-firing fallback disproportionate credit. This is the mechanism, not a fluke: screening triages candidates cheaply, it does not substitute for the full gate (see [eval doc: Limits — read before trusting a screen](tpc_phase2_eval.md#limits--read-before-trusting-a-screen)).

**Not promoted.** The flag is floor byte-identical off by construction and this gate found no regression on either axis — a "costless insurance, might help a different query mix" case for still flipping the default is available, but that is a role-1 judgment call about risk tolerance, not something this gate demonstrates as a quality win. One open item independent of the promotion decision: the gated sha predated this PR's own rebase onto `main`, so neither arm included `TPC_SOLVE_CONVERGE_PATIENCE` — this measures cascade's marginal value over pin-alone, not over the pin+converge harness default promoted in PR [#41](https://github.com/stefanbschneider/china-travel-agent/pull/41). PR [#42](https://github.com/stefanbschneider/china-travel-agent/pull/42) (landed concurrently with this gate) explicitly designed the parallel transport-repair gate to share "the current promoted default" (pin+converge) as its baseline; a future re-run against that actual current default — not a re-run of this same comparison at larger `n` — is the more defensible next measurement if cascade is reconsidered.

## Commonsense-transport repair

`TPC_REPAIR_TRANSPORT_GAPS` is landed, opt-in, and acceptance-gated in `_pack_plan`.
It repairs broken intra-itinerary transport legs with deterministic re-grounding and commits only when checker acceptance is preserved.

Known limit to preserve: it does not perform cascading day-wide re-timing; when a broken leg requires schedule reshaping, this pass intentionally declines.

## Stage 3 LLM refine

Stage 3 refine is implemented behind `TPC_P2_LLM_REFINE` and bounded by the improve-stage time slice.
It is currently safe-by-construction but quality-neutral in screened runs because accepted edit commits are sparse.

Roadmap source of truth for remaining Stage 3 work is the Next steps item above; use this section as the gating summary:

- Keep repair-only scope for v2 (no preference-polish mode by default).
- Preserve hard invariants: no oracle leakage, deterministic re-grounding, commit only on checker acceptance and non-regression.
- Gate with paired on/off runs at one SHA; do not promote from ad hoc reruns.

## Solver-only headroom

Current practical headroom signal remains solver-side:

- On val baseline, solver-only FPR (`27.5`) exceeds end-to-end FPR (`25.0`) by a small but persistent margin.
- Historical failure attribution still points to timed-visit scheduling and transport correctness as top residual families.

Use `scripts/phase2_solver_failure_attribution.py` for offline diagnosis when reprioritizing deterministic fixes.

## References

- [README architecture snapshot](../README.md#architecture-at-a-glance)
- [Phase 2 evaluation](tpc_phase2_eval.md)
- [Agent prompts](agents/README.md)
- [Competition reference](reference/competition.md)
