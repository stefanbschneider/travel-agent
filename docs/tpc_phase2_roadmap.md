# TPC 2026 Phase 2 Roadmap

This is the active Phase 2 plan.
Historical experiments, superseded plans, and long-form chronology are in the [Phase 2 archive](archive/README.md).
For measurement rules and dataset boundaries, see [Phase 2 evaluation](tpc_phase2_eval.md).

## Upstream evaluator sync (2026-07-30) — read this before any number below

Upstream patched the public evaluator on 2026-07-28 (`LAMDA-NeSy/ChinaTravel` `main` `764614c`,
PRs [#29](https://github.com/LAMDA-NeSy/ChinaTravel/pull/29) / [#30](https://github.com/LAMDA-NeSy/ChinaTravel/pull/30)),
and the organizers confirmed in [issue #28](https://github.com/LAMDA-NeSy/ChinaTravel/issues/28) that
**the updated public evaluator is the canonical Phase 2 evaluator**, with the Phase 1 leaderboard to be
re-scored against it. The change is integrated; the full list is in the
[competition reference](reference/competition.md#evaluator-version).

**Every measurement in this document predates that change and is on the old contract.** Rows and
screens recorded before 2026-07-30 may be read as chronology; none of them may be gated against a
post-sync run.

What the sync actually cost us, measured (screen
[`20260730_upstream_eval_sync`](../results/phase2_baselines/screens/20260730_upstream_eval_sync/README.md),
`familiar_100_val`, `n=20`, `120 s`, LLM off — a sanity screen, not a gate):

| | MicEPR | MacEPR | C-LPR | FPR | DAV | ATT | DDR | overall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| end-to-end | `100.00` | `100.00` | `88.15` | `25.00` | `13.13` | `19.25` | `12.92` | **`54.30`** |
| same plans, old contract | `100.00` | `100.00` | `88.15` | `25.00` | `52.50` | `76.99` | `51.67` | `61.10` |
| solver-only | `99.07` | `75.00` | `63.03` | `15.00` | `6.88` | `10.37` | `10.83` | `40.57` |

Three conclusions:

1. **The two new commonsense rules cost the end-to-end path nothing.** It emits zero commonsense
   failures under the strict checker — the commonsense-first finalization policy and
   `_fast_commonsense_prefilter` already enforced intra-day ordering, and the deterministic builder
   never stacks a meal type. Phase 1's `results/best` is the opposite story (`100.0 -> 61.16`,
   `418/1000` plans rejected; see the [Phase 1 playbook](tpc_phase1_playbook.md#current-status-2026-07-30-after-the-upstream-evaluator-sync)).
2. **The whole `-6.80` is the preference denominator.** DAV/ATT/DDR are now averaged over the entire
   split with a zero per failing query, so the three preference terms are bounded by FPR. Preference
   work is now worth `0.05 · FPR` per term at most. **FPR is the only lever that pays twice.**
3. Solver-only remains behind end-to-end on this data (a known pattern), and is the arm still emitting
   commonsense-invalid plans (1 chronology, 4 transport-grounding).

## Current status snapshot

Current reference row: [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json)
(`familiar_100_val`, `900 s`, `a72357c3`, pin+converge defaults on) — **pre-sync, old contract**.

- A per-query no-oracle orchestrator wraps the deterministic `TPCAgent` and CP-SAT tier.
- Parser output is normalized into branch-local solver variants with optional entity resolution and disjunction handling.
- The harness records stage telemetry, recovers a best available solver plan after errors or timeouts, and has a schema-shaped fallback.
- Rehearsal supports ceiling, solver-only, and end-to-end attribution; parser comparison and regression gates are available.
- **Two eval-only early-stop modes for cheap FPR measurement:** `--fast-fpr` (`TPC_SOLVE_STOP_AT_ACCEPT`, stops at first accept, skips `_pack_plan`) and the newer `--fast-fpr-packed` (`TPC_SOLVE_STOP_AT_ACCEPT_PACKED`, stops at first accept but still runs `_pack_plan` so the pin/transport-repair passes execute). Both default off, never set by the real harness, and are FPR-only/uncalibrated — the packed variant is the one to fast-measure the repair passes' FPR in the `900 s` regime (see [eval doc: Gates](tpc_phase2_eval.md#gates)).
- Baselines can run from a pinned source revision and publish committed rows under `results/phase2_baselines/`.
- The official familiar-100 records are imported byte-for-byte with a pinned archive checksum, per-member manifest, dedicated split, and explicit no-oracle boundary.
- **Parser lifted from `~0.20` to `~0.99` familiar-100 F1** with zero missing families — the last step being the comma-in-name entity-resolution segmentation fix (`62df2a0b`, F1 `0.9316 -> 0.9908`; see [the parser chronology in the archive](archive/README.md)).
- **Timed-window pinning and a within-day resequencer landed opt-in** behind `TPC_PIN_TIMED_WINDOWS` (default off, floor byte-identical), targeting the dominant solver-only failure family. **Gated at `300 s` (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)): quality up, timeouts regress, not promoted. Re-gated clean at `900 s`** (`familiar_100_val`, sha `a72357c3`, rows [floor](../results/phase2_baselines/runs/20260723T200723Z.json)/[pin](../results/phase2_baselines/runs/20260724T071840Z.json)): e2e continuous `43.72 -> 48.04`, FPR `20.0 -> 25.0`, **timeouts `0 -> 0`** — the `300 s` regression was a budget-boundary artifact, not a real cost; `make phase2-gate` **passes**. Paired with `TPC_SOLVE_CONVERGE_PATIENCE=15` ([row](../results/phase2_baselines/runs/20260724T192503Z.json)) quality holds flat while wall-clock drops further (solve `p50` `366s -> 265s`, below even the floor's `337s`). **Promoted (role 3): both are now harness-default-on** via `solve_phase2.apply_deterministic_solver_defaults()` (called at the top of `run_split`, before the agent is built), mirroring the disjunction/entity-resolution promotion pattern — the library default (unset env var) and the byte-identical opt-in unit tests are unchanged, and an explicit operator override (e.g. the eval tooling's flags-off A/B arm) still wins. `TPC_SOLVE_CONVERGE_PATIENCE=15` is defaulted alongside pin both for the wall-clock win and as a hedge: it makes the submission robust to an organizer per-query timeout shorter than the assumed `900 s` (see [Solver-only headroom](#solver-only-headroom)).
- **A commonsense-first finalization policy landed and is promoted (`TPC_COMMONSENSE_FIRST`, harness-default-on).** It relaxes the repair-pass commit rule for unaccepted plans and prefers a schema+commonsense-valid candidate at finalization, because the scored C-LPR is conditional on the commonsense pass. Paired `120 s` e2e screen: `overall_true` `51.34 -> 60.98`, C-LPR `67.35 -> 89.95`, commonsense pass `30/40 -> 40/40`, FPR `32.5 -> 35.0`, `logical_micro` flat (see [Commonsense-first finding](#commonsense-first-finding)).
- **Preference packing landed opt-in behind three flags**: `TPC_PACK_DAV`, `TPC_PACK_DDR`, and `TPC_PACK_HOTEL_BREAKFAST` (all library-default-off, floor byte-identical). The follow-up Task 3 ports the Phase 1 maxpack moves into `_pack_plan` only for already accepted plans, with accepted-key guards and ATT protection via shortest-time rerouting. `TPC_PACK_DAV` screened RED on [`20260726_e2e_n40_b120_pack_dav`](../results/phase2_baselines/screens/20260726_e2e_n40_b120_pack_dav/summary.json): FPR `37.5 -> 32.5`, `overall_true` `61.19 -> 59.32`, timeouts `3 -> 5`. `TPC_PACK_DDR` screened GREEN on [`20260726_e2e_n40_b120_pack_ddr`](../results/phase2_baselines/screens/20260726_e2e_n40_b120_pack_ddr/summary.json): FPR `35.0 -> 37.5`, `overall_true` `60.17 -> 61.36`, timeouts `4 -> 2`; a dedicated full-split `120 s` `eval_tpc.py` comparison was still mixed (official DDR `58.89 -> 65.28`, C-LPR `85.39 -> 86.18`, overall `62.98 -> 63.09`, but FPR `31.25 -> 30.0`), so nothing is promoted from this follow-up. `TPC_PACK_HOTEL_BREAKFAST` is now permanently off: upstream PR #29 (integrated 2026-07-30) made a repeated meal type a commonsense failure, so the DDR loophole it depended on no longer exists and `check` reverts any stacked day. **Both packing screens above predate that evaluator change and are not comparable to anything measured after it.**
- **A commonsense-transport repair pass landed opt-in** behind `TPC_REPAIR_TRANSPORT_GAPS` (default off, floor byte-identical), targeting the "Invalid Transport information across positions" residual (see [Commonsense-transport repair](#commonsense-transport-repair)). Since the commonsense-first promotion it is also enabled implicitly by `TPC_COMMONSENSE_FIRST`.
- **A cascading forward-shift move for the post-pin residual landed opt-in** behind `TPC_CASCADE_TIMED_WINDOWS` (default off, floor byte-identical), targeting the *post-pin* `timed_visit_named_poi` residual — the case where the day is already in the right order but clamping a windowed activity into its window ripples a delay onto the following activities, which `_try_pin_activity` reverts and `_resequence_day` skips. **Gated at `900 s`: no measurable effect, not promoted** (see [Cascading timed-window shift](#cascading-timed-window-shift)).
- **An early-convergence stop for the random-restart search landed opt-in** behind `TPC_SOLVE_CONVERGE_PATIENCE` (**library** default `0`/off so the floor stays byte-identical; **harness**-default `15` since the `900 s` promotion in the pinning bullet above), targeting the budget-bound-solver-with-no-early-convergence shortcoming (see [Solver-only headroom](#solver-only-headroom)).
- **The abbreviation-period truncation residual in the base regex parser is fixed on `main`**, landing directly (unconditional bug fix, not a flag) since it only ever discarded data it should have kept — familiar-100 `wrong_value` `6 -> 3`, F1 `0.9908 -> 0.9949` (see [the parser chronology in the archive](archive/README.md)).
- **The current reference row is already LLM-backed at Stage 1.** [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json) records `llm_config.backend=deepinfra`, `TPC_P2_LLM_PARSE=1`, and `llm_parse_attempted=80`, `llm_parse_failed=0`. The main harness is therefore not LLM-free today; the open decision is whether keeping parse audit on is helping enough to justify the cost/risk.
- **Late-night current-`main` rows did not reveal a new promotion candidate.** On sha `6d354b99`, the single-repeat `900 s` rows [baseline](../results/phase2_baselines/runs/20260725T202012Z.json), [cascade](../results/phase2_baselines/runs/20260725T214823Z.json), [transport](../results/phase2_baselines/runs/20260725T231555Z.json), [intercity](../results/phase2_baselines/runs/20260726T004345Z.json), and [all3](../results/phase2_baselines/runs/20260726T034030Z.json) all kept e2e FPR flat at `21.25`; `all3` nudged `overall_true` to `45.43`, but every arm stayed below the last known good [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json) row's `47.04`. Treat these as cautionary screens, not promotion evidence.
- **A current-head quick screen makes `TPC_P2_LLM_PARSE` the first policy decision for the final evening.** Local `2026-07-26` end-to-end screen on `main` (`n=10`, `60 s`, DeepInfra timeout `6 s`) gave parse off `FPR 30.0`, `overall_true 54.48`, `1` timeout vs. parse audit on `FPR 20.0`, `overall_true 45.54`, `2` timeouts. That is not enough to promote parse-off by itself, but it is strong enough to stop assuming the current auto-enabled audit is helping current head.
- **LLM reachability closed against a real live endpoint (2026-07-31 night).** `TPC_P2_LLM_BACKEND=deepinfra` against the real DeepInfra API (key loaded from `.env` via `load_local_env()`, never read/echoed directly) completes both the happy path (a genuine network call fires and returns a real completion) and the dead-endpoint path (`valid=True fallback=False`, failure recorded only in telemetry, no crash) cleanly. See [Shortcomings and plan W8](tpc_shortcomings_and_plan.md#w8-verify-llm-reachability-and-close-the-parse-policy-decision) for the full record; W8 is now fully closed.
- **W4 step 0's own telemetry had a blind spot for exactly the queries it exists to explain — now fixed.** Reading `search_telemetry` on 8 real queries found 2 of 8 came back `{}` because a `func_timeout` kill lands mid-restart-loop, before `_solve`'s one-shot final telemetry assignment ever ran. Fixed by snapshotting on every leader-improving `consider()` call (tagged `stop_reason="interrupted"`); pure observation, no behavior change, unit-tested and reverified live. The 8-query read itself shows no single "found early" pattern (`0%-100%` of the restart budget across queries), which favors W4 step 2 (parallel restarts) over step 1. A CP-SAT worker screen (step 1, `1 -> 4` workers matched to a 4-core box) came back RED but is not conclusive at that core count. See [Shortcomings and plan W4](tpc_shortcomings_and_plan.md#w4-use-the-16-confirmed-evaluation-cpus).

- End-to-end: FPR `25.0`, `overall_true 47.04`
- Solver-only: FPR `27.5`, `overall_true 49.72`
- Reliability: zero parse failures, zero timeouts, zero fallbacks

Interpretation:

1. **Solver logical search is not the sole binding ceiling — the commonsense gate on the *emitted*
   plan was costing more.** C-LPR is scored conditionally on the commonsense pass, so the 21 of 80
   e2e plans that fail commonsense forfeit logical credit they had already earned (`logical_micro`
   `89.47` vs C-LPR `66.02`). Closing that gate is worth `~+8.6` `overall_true` on this row's own
   numbers, more than any remaining solver-search item. See
   [Commonsense-first finding](#commonsense-first-finding); shipped as `TPC_COMMONSENSE_FIRST`.
2. The earlier `300 s` timeout regressions for pinning were budget-boundary artifacts; the promoted
   `900 s` setting absorbs them.
3. Beyond the commonsense gate, remaining gains are solver/repair/refine improvements, not parser
   recovery.
4. The harness *can* use the LLM for Stage 1 parse audit, but only when a backend is configured, and
   the packaged submission configures none — see
   [LLM packaging](#llm-packaging-the-submission-makes-zero-llm-calls).

## Main insights

- **The commonsense gate on the emitted plan, not solver search, was the largest single leak.** C-LPR
  is the *conditional* logical micro, so a commonsense-invalid plan scores `0` on `0.25` of the
  weighting plus its EPR-macro point regardless of how many clauses it satisfies. Fixed by
  `TPC_COMMONSENSE_FIRST` (harness-default-on): screened `overall_true` `51.34 -> 60.98` with
  `logical_micro` flat. See [Commonsense-first finding](#commonsense-first-finding).
- **Parser is no longer the main bottleneck.** Familiar-100 parser quality is already high (latest headline F1 `0.9949`), and incremental parser fixes now have smaller end-to-end leverage than solver-side work.
- **Promoted deterministic defaults are stable.** `TPC_PIN_TIMED_WINDOWS` plus `TPC_SOLVE_CONVERGE_PATIENCE=15` passed `900 s` gates cleanly and are now harness defaults, joined by `TPC_COMMONSENSE_FIRST` from the `2026-07-26` screen.
- **The deterministic repair flags were mis-diagnosed as low value.** `TPC_REPAIR_TRANSPORT_GAPS` and
  `TPC_REPAIR_INTERCITY` gated flat because their commit rule required full acceptance, which the
  plans they target never reach — not because the repairs do not work. They are now reachable through
  the umbrella flag. `TPC_CASCADE_TIMED_WINDOWS` remains unpromoted on its own `900 s` gate.
- **LLM-assisted paths remain selective, and the packaged submission makes zero LLM calls.** Backend
  defaults to `none` and `agent_env/config.toml` is gitignored, so nothing in the tree reaches the
  organizers' endpoint; `TPC_P2_LLM_PARSE_MODE=extract` is unmeasured and both Stage 3 refine variants
  still show `improve_committed=0`. See [LLM packaging](#llm-packaging-the-submission-makes-zero-llm-calls).

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
- `TPC_REPAIR_DROP_TRAILING_STAY` single-day trailing-accommodation drop is implemented behind a
  flag (see [Known residual](#known-residual-the-intercity-endpoint-cluster-has-a-different-cause)).
- Solver search telemetry (`restarts_used`, `stop_reason`, `candidates_evaluated`,
  `best_found_at_restart`) is recorded on every `TPCAgent._solve` call and surfaced through
  `solve_phase2`'s telemetry as `search_telemetry` — pure observation, no behavior change, added so
  a later parallel-restarts step (roadmap item 0c) can be judged against real data on whether the
  search is budget-bound or plateaus long before `max_restarts`.

Both `make phase2-gate` runs (e2e and solver-only, floor -> pin and floor -> pin+converge) **pass cleanly** — `continuous_score` up, zero new timeouts, zero parse failures on all four. The `300 s` timeout regression was purely a budget-boundary artifact of the extra per-trial deepcopy + full-checker revalidation `_pin_timed_windows`/`_resequence_day` do (PR #34's causal read holds), not a real correctness cost: at `900 s` the restart loop has enough room to absorb it with zero timeouts either way. `TPC_SOLVE_CONVERGE_PATIENCE=15` adds no quality (flat within noise vs pin-alone) but **reclaims the wall-clock pin spends and then some** — pin+converge's `p50`/`p95` beat even the floor's, confirming the roadmap's own hypothesis that converge would absorb the budget pin spends. Both are now harness-default-on (PR [#41](https://github.com/stefanbschneider/china-travel-agent/pull/41)). See [Solver-only headroom](#solver-only-headroom).

**Gated the cascade fallback (`TPC_CASCADE_TIMED_WINDOWS`) at `900 s` — no measurable effect, not promoted.** Matched pair, `TPC_PIN_TIMED_WINDOWS=1` baseline vs `+ TPC_CASCADE_TIMED_WINDOWS=1` candidate, `familiar_100_val`, `900 s`, 2 repeats, `parallel=3`: baseline [`20260725T130809Z`](../results/phase2_baselines/runs/20260725T130809Z.json), candidate [`20260726T004535Z`](../results/phase2_baselines/runs/20260726T004535Z.json). `make phase2-gate` passes both axes, but solver-only — the axis cascade directly acts on — is flat (continuous `+0.004`) within the baseline's own repeat noise, and the fast screen run first overstated the effect and even flipped sign on solver-only. See [Cascading timed-window shift: Gate result](#gate-result-900-s-no-measurable-effect) for the full breakdown.

The familiar release has no organizer best plans, so its ceiling is unavailable rather than zero. Every number here is a repository-local development result, not an estimate of final held-out performance.

## Last-evening outcome (2026-07-26)

The final change window is closed. What shipped is **one mechanism**, promoted from a paired
same-SHA screen: the commonsense-first finalization policy (`TPC_COMMONSENSE_FIRST`, harness-default-on).
Implementation brief: [`docs/agents/final_night_commonsense_first.md`](agents/final_night_commonsense_first.md).
Confirmation commands for a second machine: [`docs/agents/final_night_eval_commands.md`](agents/final_night_eval_commands.md).

| step | result |
| --- | --- |
| Offline sizing (`scripts/phase2_commonsense_headroom.py`) | 21 of 80 e2e plans fail commonsense while passing `8/9`-`11/13` of their logical clauses; projected e2e `overall_true` `47.04 -> 55.69` |
| Relaxed repair commit rule for unaccepted plans (Task 2) | landed, `TPC_COMMONSENSE_FIRST` |
| Commonsense-valid finalization preference (`best_cs`, Task 3) | landed, same flag |
| Per-layer metrics in the quick screen (Task 4) | landed; screens now report EPR micro/macro, C-LPR, logical micro, `all_pass` |
| Paired e2e screen, `n=40`, `120 s`, `parallel=7` | `overall_true` `51.34 -> 60.98`, C-LPR `67.35 -> 89.95`, commonsense pass `30/40 -> 40/40`, FPR `32.5 -> 35.0` |
| Promotion | `TPC_COMMONSENSE_FIRST=1` is a harness default (`apply_deterministic_solver_defaults`) |
| LLM reachability (optional Task 9) | **not attempted**; see [LLM packaging](#llm-packaging-the-submission-makes-zero-llm-calls) |
| Preference packing | skipped that night; implemented later behind `TPC_PACK_DAV` / `TPC_PACK_DDR` / `TPC_PACK_HOTEL_BREAKFAST`, not promoted from current evidence |

What was explicitly *not* done, and stays not done: no new solver move, no new parser family, no
agentic loop, no promotion of `TPC_CASCADE_TIMED_WINDOWS`, and no change to Stage 3 refine (both
`TPC_P2_LLM_REFINE` and `TPC_P2_LLM_AGENTIC_REFINE` remain off with `improve_committed=0`).

The safety net is unchanged: [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json)
remains the last long-budget pinned row, and every new behavior is off when its env var is unset, so
reverting the evening is a single flag.

## Commonsense-first finding

**The scored C-LPR is conditional on the commonsense gate, and that is where the Phase 2 score was
leaking.** `eval_tpc.py` takes C-LPR from
`evaluate_hard_constraints_v2(..., env_pass_id=commonsense_pass_id)`: a query's per-clause logical
credit is counted only if that query's plan also passes the commonsense checker, while the
denominator stays the whole batch's clause count. EPR-macro is all-or-nothing per query. So an
emitted plan that fails commonsense forfeits its logical partial credit (weight `0.25`) *and* its
EPR-macro point (`0.10`), however many clauses it satisfies.

On the promoted row that is not a hypothetical: `logical_micro` is `89.47` while the scored C-LPR is
`66.02`, and the entire difference is the 21 of 80 end-to-end plans that fail commonsense — each of
which passes between `8/9` and `11/13` of its logical clauses. Failure families:
`Invalid Transport information across positions` (13 uids), `Does not follow Chronological Order`
(7), and an intercity-endpoint cluster (3). Reproduce with:

```bash
.venv/bin/python scripts/phase2_commonsense_headroom.py --mode end-to-end
```

Projected ceiling, holding every logical verdict, the FPR, and the preference metrics fixed:
C-LPR `66.02 -> 89.47` (`+5.86` overall), EPR-macro `73.75 -> 100` (`+2.62`), EPR-micro `+0.16` —
e2e `overall_true` `47.04 -> 55.69`. Solver-only projects `+7.83` from 19 failing plans.

### Root cause 1: the repair passes could not commit where the failures live

`TPC_REPAIR_TRANSPORT_GAPS` and `TPC_REPAIR_INTERCITY` both target these exact families, and both
gated flat. The reason was their commit rule, not their repair logic: each ended with
`if not self._accepted(*check(trial)): return`, and `_accepted` requires *all* parsed logical
constraints plus schema plus commonsense. A plan that fails a logical clause is unaccepted by
definition, so a repair that successfully fixed its transport chain was discarded anyway — on
precisely the plans whose commonsense failure was costing the C-LPR and EPR-macro credit.

`_repair_commit_allowed` now splits the two regimes. An accepted input keeps the strict legacy rule
(still accepted, preference key not regressed). An unaccepted input commits when the trial is
schema-valid, flips commonsense from invalid to valid, and loses no parsed-constraint passes.
Preference is deliberately unguarded there: a grounded leg costs more than a broken one by
construction, and the invariant forbids trading a *valid* plan for score, not spending cost to make
an invalid plan valid.

### Root cause 2: finalization ranked unaccepted candidates without a commonsense term

`_make_checker` only adds the schema/commonsense bonus once the parsed base is fully satisfied, so
the search key that ranks unaccepted candidates ignores commonsense entirely, and `_solve` emitted
that leader. Commonsense validity of the emitted plan was therefore incidental — 39 of 60 unaccepted
plans passed by luck.

`_solve` now tracks a third bucket, `best_cs`: the best schema+commonsense-valid candidate whatever
its parsed pass count, emitted when nothing is accepted and the leader is invalid. Timeout recovery
mirrors the same order. Worked example on uid `...00009` at a `150 s` budget: the leader was a
**transport-less plan** — zero inner-city legs anywhere, yet satisfying `13/14` parsed clauses. With
the flag on, the emitted plan is fully commonsense-valid, C-LPR goes `0 -> 91.67` and that query's
`overall_true` goes `9.62 -> 42.92`, at unchanged solve time.

### Cost control: the official evaluator is expensive

A single `evaluate_commonsense_constraints` call costs about `319 ms` (measured), and inside a
wall-clock-bounded solve each call is paid for with a restart that does not happen. The probe is
therefore triple-bounded: `_fast_commonsense_prefilter` rejects hopeless candidates for free (it
mirrors the transport-chain and chronology checks and is no stricter than they are — a transport-less
plan dies without any evaluator call), `TPC_CS_CHECK_BUDGET=60` caps confirmations, and
`TPC_CS_CHECK_TIME_FRAC=0.08` caps their share of the solve budget. Verdicts are memoized per plan
object. Exhausting either bound degrades to the previous selection.

### Screen result and the one caveat

Paired same-SHA end-to-end screen, `familiar_100_val` fold 0, `n=40`, `120 s`, `parallel=7`, LLM
backend `none` (zero LLM calls), artifacts in
[`results/phase2_baselines/screens/20260726_e2e_n40_b120_commonsense_first`](../results/phase2_baselines/screens/20260726_e2e_n40_b120_commonsense_first/summary.json):

| metric | off | on | Δ |
| --- | --- | --- | --- |
| `overall_true` | `51.34` | `60.98` | **`+9.64`** |
| commonsense pass | `30/40` | `40/40` | `+10` |
| EPR-macro | `75.00` | `100.00` | `+25.00` |
| EPR-micro | `99.04` | `100.00` | `+0.96` |
| C-LPR | `67.35` | `89.95` | **`+22.60`** |
| logical micro | `89.95` | `89.95` | `0.00` |
| FPR | `32.50` | `35.00` | `+2.50` |
| `all_pass` | `13` | `14` | `+1` |
| timeouts | `4` | `7` | `+3` |

`logical_micro` being flat is the proof of mechanism: the gain is entirely the commonsense gate
releasing logical credit the solver had already earned, exactly as the offline projection predicted.

**Caveat:** timeouts rose `4 -> 7`, which is the only reason `make phase2-gate` reports FAIL on this
pair. All were recovered (`used_fallback=0`, `parse_failures=0`), and the budget is deliberately
tight — the baseline's own solve `p50` is `108 s` of `120 s`, so any extra per-query work tips
queries over the wall. This is the same budget-boundary shape `TPC_PIN_TIMED_WINDOWS` showed at
`300 s` and cleared at `900 s` (`p50 265 s`, zero timeouts). Treat the `900 s` rows from
[`final_night_eval_commands.md`](agents/final_night_eval_commands.md) as the confirmation.

### Known residual: the intercity-endpoint cluster has a different cause

The 3 uids that fail all four intercity columns (`...00065`, `...00071`, `...00066`) are not fixed by
this work, and the endpoint repair cannot fix them: each is a **1-day trip whose last activity is an
overnight accommodation ending `24:00`**, so `_repair_intercity_endpoints` computes a departure floor
of `24:00` and no return row can be placed after it. The real defect is upstream — a single-day
itinerary should not contain an overnight stay at all.

**Landed (2026-07-31): `TPC_REPAIR_DROP_TRAILING_STAY`** (default off, also reachable via the
`TPC_COMMONSENSE_FIRST` umbrella). Drops a single-day trip's trailing overnight accommodation before
`_repair_intercity_endpoints` computes the return-departure floor, so the floor is derived from the
real last in-city activity instead of `24:00`. Unit-tested in
`tests/phase2/test_repair_intercity_endpoints.py` (flag off byte-identical, the drop+re-placement
commit, a 2-day plan left untouched, and the no-feasible-return-after-drop byte-identical case).
Per-uid verification on the 3 named uids at `900 s`: `...00071` clears all four intercity columns
(`overall_true` `8.52 -> 43.08`); `...00065` and `...00066` are a **distinct, deeper residual the
drop cannot reach** — their day's other activities (correctly built and ordered) run past every
same-day return train/flight regardless of the accommodation (confirmed by querying
`WorldEnv.intercitytransport` directly: the latest same-route departure is earlier than the day's
last real activity ends), so no forward-only repair can place a return leg without also reshaping
the day's earlier schedule, which is out of this mechanism's scope. That is a solver-scheduling
defect (the day was built too dense/late to leave room for the return trip), not a bug in the drop
logic.

**Not promoted.** The required paired screen (`--flag TPC_REPAIR_DROP_TRAILING_STAY --mode end-to-end
--n 40 --budget-sec 120 --parallel 7`) came back **RED**: `overall_true` `52.44 -> 51.07`, FPR
`22.50 -> 20.00`, timeouts `34 -> 37`. The likely cause is that the flag's `_pack_plan` gate
(`self._repair_intercity_enabled() or self._repair_drop_trailing_stay_enabled()`) reaches
`_repair_intercity_endpoints` on its own, which also runs the *general* endpoint re-grounding pass
(normally gated behind `TPC_REPAIR_INTERCITY`) against every query in the screen, not only the rare
single-day-trailing-stay shape this flag targets — at a tight `120 s` budget that pass's own extra
per-query deepcopy + full-checker revalidation cost plausibly explains the regression on unrelated
queries. See
[Shortcomings and plan, W5](tpc_shortcomings_and_plan.md#w5-drop-the-trailing-stay-on-single-day-trips)
for the full result and the open re-screening question. The flag stays implemented, tested, and
default off; `apply_deterministic_solver_defaults()` is untouched.

## LLM packaging: the submission makes zero LLM calls

Recorded because it is a packaging fact, not an opinion, and it survives the deadline:

- `TPC_P2_LLM_BACKEND` defaults to `none`, whose client raises on any call.
- `agent_env/config.toml` is **gitignored** and absent from the repository; only
  `config.toml.example` is tracked. A submission built from git therefore has no `[phase2.llm]`
  backend configured.
- `resolve_llm_client_and_flags` auto-enables `TPC_P2_LLM_PARSE` only when a backend is *already*
  configured, so with backend `none` the parse audit stays off too.
- `TPCAgent`'s `backbone_llm` is `TPCLLM`, whose `_get_response` returns the literal string
  `"Empty LLM response"`.

Consequence: as packaged, the Phase 2 path is fully deterministic and cannot reach the organizers'
Qwen3.6-27B/SGLang endpoint — the reference row's `llm_config.backend=deepinfra` came from local
environment variables, not from anything in the tree. The optional plumbing to auto-detect an
OpenAI-compatible endpoint (`OPENAI_BASE_URL` and friends) with the parse audit still default-off,
originally scoped as Task 9 of the final-night brief, **has since landed** (`_autodetect_openai_cfg` /
`resolve_llm_client_and_flags` in `agent_env/scripts/solve_phase2.py`) and was verified 2026-07-31 night
to work end-to-end against a real live endpoint (both the happy path and the dead-endpoint path — see
[Current status snapshot](#current-status-snapshot)). It only ever activates when an operator points an
env var at a real endpoint, which the packaged submission never does, so this does not change the
packaging fact above. Given that the latest current-head parse screen was RED for audit-on, shipping
deterministic is the defensible position; the reachability gap this paragraph used to describe is closed.

## Shortcomings of the current agent

A review of the Phase 2 path (`chinatravel/agent/phase2/` + the no-oracle `TPCAgent`) against the latest evidence surfaces six shortcomings, roughly in leverage order.

1. **Solver-only ceiling dominated by one family — pinning + resequencer clears the gate at `900 s`.** `26/100` solver-only pass with perfect constraints; `timed_visit_named_poi` is the *sole* logical blocker in `53` of the `74` failures. The landed pinning + resequencer regressed timeouts at the old `300 s` gate (PR [#34](https://github.com/stefanbschneider/china-travel-agent/pull/34)) but **passes cleanly re-gated at `900 s`**: solver-only continuous `46.86 -> 49.38`, FPR `23.75 -> 27.5`, **zero timeouts either way** (`familiar_100_val`, sha `a72357c3`) — the `300 s` regression was a budget-boundary artifact of the per-trial deepcopy + full-checker revalidation, not a real cost. Paired with the now-landed early-convergence stop (shortcoming 2, `TPC_SOLVE_CONVERGE_PATIENCE=15`), quality holds flat and wall-clock drops below even the floor's. Evidence clears the promotion bar; flipping the default is role 3's to do. See [Solver-only headroom](#solver-only-headroom).
2. **Current-head absolute performance is not yet a monotonic signal.** The late single-repeat `900 s` rows on `6d354b99` (`final-baseline-pinconv` and companions) sit materially below the promoted `a72357c3` row, so late decisions must compare against a same-SHA baseline and not assume `main` is automatically better because it is newer. Tonight's risk is regression-by-accumulation, not lack of options.
3. **Stage 3 "improve" is wired, but still acts like a zero-gain feature.** `TPC_P2_LLM_REFINE` is no longer a stub: the orchestrator calls it, `TPCAgent` exposes `ground_and_check` / `apply_refine_edits`, and the failure summary already includes per-clause items, broken-leg diagnostics, and feasible windows. The remaining problem is commit rate: current refine and agentic-refine screens still show `improve_committed=0`, so the gap is now behavioral, not plumbing. See [Stage 3 LLM refine](#stage-3-llm-refine).
4. **Commonsense residual fixes exist and are now reachable — their old commit rule was the blocker.**
   `TPC_REPAIR_TRANSPORT_GAPS` and `TPC_REPAIR_INTERCITY` are implemented and unit-tested, and both
   gated flat because they could only commit on a plan that already reached full acceptance — which the
   plans they target never do. Fixed by `_repair_commit_allowed` and shipped inside
   `TPC_COMMONSENSE_FIRST` (see [Commonsense-first finding](#commonsense-first-finding)). The residual
   that remains is the single-day-trip overnight-accommodation defect, which no repair pass can reach
   today.
5. **Parser value-segmentation residual — largely closed, pending gate.** The comma-/`" and "`-in-name `wrong_value` residual was fixed on `main` (`62df2a0b`) via maximum-munch catalog segmentation plus a restaurant/hotel matching-pool broadening, taking familiar-100 F1 `0.9316 -> 0.9908` (wrong_value `47 -> 6`). It is diagnostic evidence only — not yet through the end-to-end gate. The distinct abbreviation-period truncation bug (`"St. Regis"`, `"No. 3955 …"`) in the base regex parser's `_list_after_marker` is now fixed unconditionally on `main` (F1 `0.9908 -> 0.9949`, wrong_value `6 -> 3`; see [the parser chronology in the archive](archive/README.md)); a `3`-case `excluded_hotels` residual remains from a separate, already-known limit — a comma-heavy full-address value spans more raw tokens than the entity-resolution merge's bounded `_ENTITY_SEGMENT_MAX_SPAN` (`4`), so it stays fragmented rather than re-merging into one catalog name.
6. **The LLM is unreachable in the *packaged* submission by design, and reachability itself is now verified working.**
   Local rows show the harness *can* call DeepInfra/Qwen at Stage 1 (`llm_parse_attempted=80/80` on
   [20260724T192503Z](../results/phase2_baselines/runs/20260724T192503Z.json)), and the 2026-07-31 night
   session confirmed that call path against a real live endpoint end-to-end (happy path and dead-endpoint
   path both clean — see [Current status snapshot](#current-status-snapshot)). In the packaged submission
   it still never fires: backend defaults to `none`, `agent_env/config.toml` is gitignored, and `TPCLLM`
   is an empty stub. The latest paired quick screen was also RED for audit-on vs. parse-off, so shipping
   deterministic is defensible and unchanged. See
   [LLM packaging](#llm-packaging-the-submission-makes-zero-llm-calls).

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Next steps (priority order)

The Phase 2 submission deadline is **not** announced (the organizers listed it as still being
finalized on 2026-07-30), and evaluation runs 2026-08-01 to 08-07, so treat the window as open but
short. Implementation-level detail for the older items lives in
[`next_steps_after_final_night.md`](agents/next_steps_after_final_night.md).

**Self-contained implementation briefs for every open item below — plus the Phase 1 items and a
ranked leverage estimate for each — are in [Shortcomings and plan](tpc_shortcomings_and_plan.md)
(2026-07-31).** That document is the working plan; this section stays the priority record. Two of its
findings change what is written below: the Phase 1 "hard tail" is `22` plan-level commonsense defects
in plans that already satisfy every logical clause (worth `~+2.2` overall, item 0b), and Tasks 1 and 3
of `next_steps_after_final_night.md` have landed while Task 2 (the single-day trailing stay) has not.

0. **Re-establish a post-sync baseline before gating anything.** Every committed row is on the old
   evaluator contract. The first `900 s` `familiar_100_val` run after the sync becomes the new
   reference row; until it exists, `make phase2-gate` has no valid baseline to compare against.

0b. **Re-solve Phase 1 `results/best` (highest expected value of anything on this list, and it is
   Phase 1 work).** The organizers will re-score the Phase 1 leaderboard with the new evaluator, and
   Phase 1 standing decides Phase 2 advancement. `418/1000` of our accepted plans now fail: `344`
   on intra-day chronology, `149` on repeated meal types. The solver's acceptance gate calls the same
   evaluator, so simply re-running the Phase 1 loop over
   `chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` cannot re-create either failure
   family. Two of the failures are also cheap plan-level repairs on already-solved plans (drop the
   duplicate meal; re-space overlapping activities), which is likely faster than a full re-solve.

0c. **Use the 16 confirmed evaluation CPUs.** The organizers confirmed the harness process is assigned
   **16 logical CPUs and 112 GiB host RAM**. Our per-query solve is single-threaded by construction
   (CP-SAT `num_search_workers` 1, sequential restarts), tuned on far smaller dev machines. Parallel
   restarts and/or a multi-worker CP-SAT tier convert idle cores into search inside the same
   per-query budget, with no change to the acceptance contract. Screen it like any other change.
   **Telemetry (2026-07-31 night)**: reading `search_telemetry` on 8 real `familiar_100_val` queries
   found no single "found early" pattern — 3 converge in the first `5%` of their restart budget, but 5
   (including 2 that a `func_timeout` kill had been silently hiding until this session's fix) are still
   improving `47%-100%` of the way to the wall. **A CP-SAT worker screen (`1 -> 4`, matched to this
   machine's 4 cores, `n=20`/`60 s`) came back RED** (`overall_true` `46.78 -> 45.17`), though not
   conclusive since `on=4` exhausts the box's own core count. Net read: **parallel restarts (step 2) is
   the better-motivated remaining lever, not the CP-SAT worker count (step 1)** — see [Shortcomings and
   plan W4](tpc_shortcomings_and_plan.md#w4-use-the-16-confirmed-evaluation-cpus) for the full per-query
   table and the screen row.

1. **Confirm the commonsense-first promotion at `900 s`.** Run the two pinned arms in
   [`final_night_eval_commands.md`](agents/final_night_eval_commands.md). The only open question is
   the screen's `+3` recovered timeouts at a `120 s` budget; everything else was clean.

2. **~~Fix the single-day-trip overnight-accommodation defect.~~ Landed 2026-07-31**
   (`TPC_REPAIR_DROP_TRAILING_STAY`, see [Known residual](#known-residual-the-intercity-endpoint-cluster-has-a-different-cause)):
   1 of the 3 named uids fully clears; the other 2 have a deeper, distinct residual (the day's own
   schedule runs past every same-day return departure regardless of the accommodation) that this
   move cannot reach by design.

3. **~~Close LLM reachability before adding any LLM stage.~~ Landed 2026-07-31 night.** Exercised
   `TPC_P2_LLM_BACKEND=deepinfra` against the real live DeepInfra endpoint (`.env`'s
   `DEEPINFRA_API_KEY`, loaded via `load_local_env()`): a direct client call succeeded, and a full
   `solve_phase2.py` run with `TPC_P2_LLM_PARSE=1` showed the audit genuinely firing over the network.
   The dead-endpoint case is also clean — a closed-port `TPC_P2_LLM_BASE_URL` completes with
   `valid=True fallback=False`, the connection failure recorded only in telemetry, never an unhandled
   crash. This proves the client plumbing itself is correct against a real OpenAI-compatible-wire
   endpoint; the organizers' own SGLang/Qwen3.6-27B endpoint specifically remains untested (not
   reachable from here), but the mechanism it would go through is now verified working, not just
   monkeypatched. The packaged submission still makes zero LLM calls by default (see
   [LLM packaging](#llm-packaging-the-submission-makes-zero-llm-calls)) — this closes the reachability
   *exercise*, not the packaging default. A three-arm parse screen (off / audit / `extract`) against a
   working endpoint is still open and lowest-priority (roadmap [Shortcomings and plan
   W8](tpc_shortcomings_and_plan.md#w8-verify-llm-reachability-and-close-the-parse-policy-decision) item 2
   already recorded the RED audit-on screen as the reason deterministic stays the default).

4. **Do not promote `TPC_CASCADE_TIMED_WINDOWS` from existing evidence**, and keep both Stage 3 refine
   variants off until a screen shows `improve_committed > 0`.

Packing note: the only follow-up packing flag with a green quick screen is `TPC_PACK_DDR`, but the
dedicated full-split `120 s` evaluation remained mixed enough that no packing flag is a harness
default today. Both screens predate the 2026-07-30 evaluator sync and are not comparable to a row
measured after it. `TPC_PACK_HOTEL_BREAKFAST` stays off permanently: the DDR leniency it depended on
is closed upstream, and a stacked day is now reverted by `check` rather than scored.

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

## Current headroom signal (solver side)

Current practical headroom signal remains solver-side:

- On val baseline, solver-only FPR (`27.5`) exceeds end-to-end FPR (`25.0`) by a small but persistent margin.
- Historical failure attribution still points to timed-visit scheduling and transport correctness as top residual families.

Use `scripts/phase2_solver_failure_attribution.py` for offline diagnosis when reprioritizing deterministic fixes.

## References

- [README architecture snapshot](../README.md#architecture-at-a-glance)
- [Phase 2 evaluation](tpc_phase2_eval.md)
- [Agent prompts](agents/README.md)
- [Final-night commonsense-first brief](agents/final_night_commonsense_first.md)
- [Final-night second-machine eval commands](agents/final_night_eval_commands.md)
- [Competition reference](reference/competition.md)
