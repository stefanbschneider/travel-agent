# TPC 2026 Phase 2 Roadmap

This is the only active Phase 2 plan.
Historical step plans, chronology, and superseded priorities are preserved in the [Phase 2 archive](archive/README.md).

## Completed capabilities

- A per-query no-oracle orchestrator wraps the deterministic `TPCAgent` and CP-SAT tier.
- Parser output is normalized into branch-local solver variants with optional entity resolution and disjunction handling.
- The harness records stage telemetry, recovers a best available solver plan after errors or timeouts, and has a schema-shaped fallback.
- Rehearsal supports ceiling, solver-only, and end-to-end attribution; parser comparison and regression gates are available.
- Baselines can run from a pinned source revision and publish committed rows under `results/phase2_baselines/`.
- The official familiar-100 records are imported byte-for-byte with a pinned archive checksum, per-member manifest, dedicated split, and explicit no-oracle boundary.

These capabilities are not evidence of final-evaluation performance.

## Current evidence

The current local reference is the promoted no-oracle Qwen [familiar-100 run `20260718T155006Z`](../results/phase2_baselines/runs/20260718T155006Z.json), measured at parser-fix commit `ae6337f0`. It is like-for-like with [anchor `20260716T090638Z`](../results/phase2_baselines/runs/20260716T090638Z.json): official familiar archive, DeepInfra `Qwen/Qwen3.6-27B`, two fresh repeats, library-default Phase 2 flags, and the local `300 s` budget assumption.
The continuous-score gate passes without reasons or advisories. Mean end-to-end FPR moves `2.0% -> 7.5%`, mean end-to-end `overall_true` moves `36.0610 -> 39.1265`, and solver-only FPR stays `26.0%`. The mean continuous parser gap closes from `12.2369` to `7.9591`. Full-split parser precision/recall/F1 move `0.4445 / 0.1281 / 0.1988 -> 0.8180 / 0.3518 / 0.4920`.
All `100/100` candidate outputs are valid, with zero parse failures, fallbacks, or budget overruns. End-to-end bounded-solver timeouts move `35 -> 34`; solver-only timeouts remain `23`, all recovered into solver-pass cases.
The familiar release has no organizer best plans, so its ceiling is unavailable rather than zero. This repository-local development result is not an estimate of final held-out performance.

> **Note — flag description to reconcile.** The two rows above are described as using *both* DeepInfra `Qwen/Qwen3.6-27B` *and* "library-default Phase 2 flags." These cannot both hold: library-default `Flags()` keeps `llm_parse` off and makes zero LLM calls, so a real Qwen parse run is not library-default. The harness path (`resolve_llm_client_and_flags`) actually defaults `disjunction`, `dynamic_budget`, `entity_resolution`, and — once a backend is configured — `llm_parse` on. Those two rows predate flag recording, so their true configuration is not captured. Baseline rows now record the resolved flags under `flags` (see the [ledger guide](phase2_baselines/README.md)); re-derive the intended description from a newly recorded row before treating either as the pinned reference.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed parsing, solving, or finalization.
2. **Flags off first.** Library-default Phase 2 flags preserve the deterministic path. Any enabled feature must have an explicit configuration, deterministic fallback, and measured effect.
3. **Ground before acceptance.** Environment data and deterministic validators decide facts and acceptance; LLM output is only a proposal.
4. **Pin and compare.** Promotable long runs use `make phase2-baseline-at SHA=<ref> ...`. Compare only matching data provenance, fold/limit, budget, repeats, flags, model/backend, and fresh-output policy.
5. **Gate end-to-end behavior.** Parser statistics guide diagnosis but do not promote a change alone. Gate a like-for-like end-to-end row; use `continuous_score` when available and reject increased parse failures or timeouts.
6. **Preserve development signals.** Do not tune repeatedly on the organizer final set. Treat local partitions, HF data, familiar-100, and final evaluation as distinct sources.

## Highest priority

1. The focused deterministic budget parser change is committed at `c428dd6c`; it maps the five familiar line-scoped cap templates into the existing solver buckets. Its solver-free familiar report (regenerated at that revision) reproduces `0.8502 / 0.4561 / 0.5937` precision/recall/F1, up from `0.8180 / 0.3518 / 0.4920`. This is diagnostic evidence, not promotion.
2. Measure the budget change through the normal pinned no-oracle gate before touching another family. The latest promoted familiar row (`20260718T155006Z`, `ae6337f0`) predates the budget commit, so the two are not yet like-for-like.
3. The negative/excluded-constraint families and the positive `required_*` families are now both covered by deterministic templates (see "Negative-constraint parser fix" and "Required-constraint parser fix" below), taking familiar-100 parser F1 from `~0.49` to `~0.94` with zero missing. These, plus the budget change, all still need the pinned end-to-end gate before promotion.
Familiar-100 is a development-only set drawn from the final distribution; its result must not be reported as a final-evaluation estimate.

## Parser recall attribution (familiar-100, solver-free)

Solver-free `scripts/parser_vs_oracle.py --split tpc_phase2_familiar_100` at `c428dd6c` (deterministic parser, no LLM audit) explains why familiar-100 end-to-end FPR (`7.0`) is far below repository-local val (`85.9`): the parser drops most of the constraints these denser queries carry. Familiar records average `~38` `hard_logic_py` constraints each versus `~16` in the released Phase 1 source that `tpc_phase2_val` is partitioned from, so this is out-of-distribution constraint density, not a val regression.

Of `359` missing constraints across the split, `266` (`74%`) come from five negative families the deterministic parser extracts **zero** of:

| Family | matched | missing | spurious | wrong_value |
| --- | --- | --- | --- | --- |
| `excluded_cuisine_types` | 0 | 55 | 0 | 0 |
| `excluded_hotels` | 0 | 55 | 0 | 0 |
| `excluded_attractions` | 0 | 54 | 0 | 0 |
| `excluded_restaurants` | 0 | 53 | 0 | 0 |
| `excluded_attraction_types` | 0 | 49 | 0 | 0 |
| `required_attractions` | 0 | 23 | 0 | 0 |
| `required_restaurants` | 0 | 18 | 0 | 0 |
| `required_hotel_all_types` | 0 | 16 | 0 | 0 |
| `required_attraction_types` | 0 | 15 | 12 | 5 |
| `cuisine_preference` | 0 | 12 | 0 | 0 |
| `room_type` | 0 | 9 | 0 | 0 |
| `required_hotels` | 0 | 0 | 31 | 16 |

The oracle encodes negatives as `result=not({<names>} & <set>)` (e.g. `result=not({"Red tourism sites"}&attraction_type_set)`). All `100/100` queries carry at least one such constraint, so a dropped negative lets the solver include a forbidden item on essentially every query and fail that query's all-constraints FPR — the direct mechanism behind the val-to-familiar FPR collapse. This was a structural coverage gap (no template mapped the negative shape), not a value error: extracted-side precision was healthy (`0.8502`) and value-accuracy `0.9485`. `required_hotels` is the one notable precision leak (`31` spurious, `16` wrong_value) and stays a second-order concern behind the negatives.

## Negative-constraint parser fix

The five negative families all surface in the NL through one uniform familiar-100 template — `Do not include any of these <category>: A, B and C.` — that none of the older `do not want to visit/stay/try …` patterns matched. `parse_constraints._do_not_include_items` now parses it and feeds the five `parse_excluded_*` extractors, with:

- **category anchoring at the `:` list marker**, so a name category (`hotels`) never fires on a sibling type category (`hotel feature types`), and `attractions`/`restaurants` never fire on `attraction types`/`restaurant types`;
- **verbatim values for the type families** (`excluded_attraction_types`, `excluded_cuisine_types`) — the NL uses the oracle's own vocabulary/casing, so routing through the lower-casing alias table would drop unaliased types like `Library/Memorial Hall`;
- **compound-vocabulary protection** for cuisine values that legitimately contain `" and "` (`Fast food and casual dining`, `Bakery and Desserts`), read once from the committed `database_en` restaurant CSVs (deterministic environment data, not oracle); and
- **Oxford-comma handling** so `A, B, and C` does not leave a leading `and C` fragment.

Solver-free `parser_vs_oracle.py --split tpc_phase2_familiar_100` moves as follows (flags-off deterministic path, the headline signal):

| Metric | Before (`c428dd6c`) | After | After + entity-resolution (harness default) |
| --- | --- | --- | --- |
| precision | 0.8502 | 0.8620 | 0.8747 |
| recall | 0.4561 | 0.8036 | 0.8148 |
| F1 | 0.5937 | 0.8317 | 0.8437 |
| value-accuracy | 0.9485 | 0.9224 | 0.9354 |

All five negative families now have **zero missing** (full recall); `excluded_cuisine_types` and `excluded_attraction_types` match exactly (`55/55`, `49/49`, zero wrong-value). The residual `wrong_value` (`~16` hotels, `~8` restaurants, `~2` attractions) are proper names that contain internal commas/`" and "` and can only be segmented against the city catalog — a pre-existing entity-resolution limitation, not specific to this template. This is diagnostic evidence: it must clear the pinned no-oracle gate against the last promoted row before promotion, and it is not a final-evaluation estimate.

## Required-constraint parser fix

The positive requirements use the mirror-image template — `<Visit|Dine at|Stay at|Include> the following <category>: A, B and C.` — parsed by `parse_constraints._the_following_items` (which shares its splitting core, `_list_after_marker`, with the negative helper). It feeds the `required_*` extractors with the same category anchoring, verbatim type values, compound-cuisine protection, and Oxford-comma handling, plus a negated-lead-in guard so it never fires on a `do not …` clause. Two precision guards accompany it:

- **junk-label guard**: the older `^visit …` / broad `stay at …` patterns captured the `the following attractions:` / `hotels:` label as part of the first name (e.g. `hotels: Golden Eagle Summit Hotel`) — those template lines are now skipped so the clean template owns them;
- **time-window guard**: `Stay at X between 21:39 and 24:00` is an activity-time-window/position constraint, not a required hotel; the broad `stay at` pattern no longer emits a (junk-valued) `required_hotels` entry for it.

`room_type` also gained the familiar `Each accommodation stay must use <single|twin>-bed rooms.` phrasing.

Solver-free `parser_vs_oracle.py --split tpc_phase2_familiar_100`, measured from the post-negatives-merge baseline (`7d5e1910`):

| Metric | Before | After | After + entity-resolution (harness default) |
| --- | --- | --- | --- |
| precision | 0.8620 | 0.9402 | 0.9193 |
| recall | 0.8036 | 0.9487 | 0.9284 |
| F1 | 0.8317 | 0.9444 | 0.9239 |

Every family now has **zero missing** (full-split recall). `required_hotel_all_types`, `cuisine_preference`, `required_hotels`, and `room_type` match exactly with zero wrong-value; `required_hotels` in particular went from `0` matched / `31` spurious / `16` wrong-value to `16 / 0 / 0` once the two guards landed. Remaining defects: `required_attraction_types` keeps `7` spurious (pre-existing substring false positives like `park` inside `Free parking`, down from `12`; tightening them risks a val regression), and the comma-in-name `wrong_value` residual (`~4` attractions, `~3` restaurants) is the same catalog-segmentation limit as the negatives. Val is unchanged (`f1 0.7268 -> 0.7272`): the `the following` template is inert on the phase-1 partition. Diagnostic evidence pending the pinned end-to-end gate; not a final-evaluation estimate.

## `required_attraction_types` time-window guard

Root-caused the `7` remaining familiar-100 `required_attraction_types` spurious entries flagged above: the actual mechanism is not `park` inside a hotel-feature phrase like `Free parking` (a different family) but a POI **name** that happens to contain a known type word, picked up by `parse_required_attraction_types`'s unanchored `[Vv]isit\s+(.+?)...` fallback when it scans a numbered-line `Visit X between A and B` sentence — territory `parse_activity_time_windows` (`_CONTAINED_BETWEEN_WINDOW_RE`) already owns. E.g. `Visit Golden Eagle Art Museum between 14:44 and 16:34.` matched the `Art Museum` known-type substring; `Visit Baihua Tan Park between 09:31 and 11:16.` matched `park`. The fix strips `_CONTAINED_BETWEEN_WINDOW_RE` lines out of the text the fallback scans, before the known-types substring check runs — the same "don't scan a POI name for a naive type substring" lesson `parse_excluded_attraction_types` already applies (see its `piece`-exact-match comment).

Solver-free `parser_vs_oracle.py --split tpc_phase2_familiar_100`, measured from the required-constraint-fix baseline above:

| Metric | Before | After |
| --- | --- | --- |
| precision | 0.9402 | 0.9510 |
| recall | 0.9487 | 0.9510 |
| F1 | 0.9444 | 0.9510 |

`required_attraction_types` moves `18` matched / `7` spurious / `2` wrong-value → `20` matched / `0` spurious / `0` wrong-value (the two prior wrong-value cases resolved once their time-window line stopped contributing a rival entry). Val is byte-identical (`f1 0.7282` before and after): `_CONTAINED_BETWEEN_WINDOW_RE` targets the familiar-100 line-scoped `Visit/Dine at/Stay at X between A and B` template only (an optional leading `N.` numbering is not required), so this is inert on the phase-1 partition, same as the required-constraint fix above. Diagnostic evidence pending the pinned end-to-end gate; not a final-evaluation estimate.

## LLM parsing vs deterministic (familiar-100 + HF OOD)

Question: does routing the parse through the DeepInfra `Qwen/Qwen3.6-27B` LLM beat the deterministic parser, and should `TPC_P2_LLM_PARSE` be defaulted on? Measured with `scripts/parser_vs_oracle.py` (parse vs oracle, shared solver-dict schema), keeping the harness-default flags `--disjunction --entity-resolution --branch-aware` on both sides and toggling only `--llm-parse` (and, for `extract`, `Flags.llm_parse_mode`). Temperature 0, responses cached, backend `deepinfra`. Two LLM strategies exist: `audit` (the harness default — corrective audit that re-parses every LLM proposal through the regex) and `extract` (LLM-first structured extraction validated against closed vocabularies, independent of the regex).

All rows are measured on **English** query text: familiar-100 and the local `tpc_phase2_val`/`test` partitions are natively English, and the HF `LAMDA-NeSy/ChinaTravel` set is natively Chinese (`nature_language`) but `load_hf_queries` uses its English translation field (`nature_language_en`), which is what the agent path would receive. So the "OOD" gap below is a phrasing-register difference *within English* (familiar-100's rigid `Requirements: 1. … 2. …` templates vs. HF's free-prose translations), not a cross-language difference.

Familiar-100 (full 100, the final-distribution proxy):

| Config | precision | recall | F1 | matched | missing | spurious | wrong_value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 0.9311 | 0.9321 | 0.9316 | 644 | 0 | 1 | 47 |
| LLM audit | 0.9057 | 0.9154 | 0.9106 | 633 | 0 | 10 | 58 |
| LLM extract (25-uid subset) | — | — | 0.758 | 135 | 0 | 23 | 32 |

(The `extract` row is a 25-uid subset; its like-for-like deterministic baseline on the *same* 25 uids is F1 `0.935` — so extract loses ~0.18 F1 there. Audit on that same subset was byte-identical to deterministic, `0.935`.)

HF `LAMDA-NeSy/ChinaTravel` config `default`, first 50 uids per split (out-of-distribution phrasing generalization probe — a measurement set only, never tuned against; see [dataset boundaries](tpc_phase2_hf_dataset.md)):

| Split | Config | precision | recall | F1 | matched | missing | spurious | wrong_value |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| medium | deterministic | 0.8367 | 0.3050 | 0.4470 | 52 | 121 | 14 | 3 |
| medium | LLM audit | 0.5667 | 0.3050 | 0.3966 | 52 | 118 | 40 | 6 |
| medium | LLM extract | 0.7643 | 0.8233 | 0.7927 | 143 | 3 | 19 | 30 |
| human | deterministic | 0.8567 | 0.5900 | 0.6988 | 51 | 47 | 12 | 4 |
| human | LLM audit | 0.8267 | 0.5900 | 0.6886 | 51 | 46 | 14 | 5 |
| human | LLM extract | 0.7067 | 0.6567 | 0.6807 | 60 | 21 | 19 | 21 |

Two findings:

1. **Audit mode never recovers recall on any set.** `matched` never rises deterministic→audit: it is flat on HF (medium `52→52`, human `51→51`) and actually falls on familiar-100 (`644→633`, i.e. audit corrupted 11 previously-matched families into `spurious`/`wrong_value`); `missing` barely moves. This is structural: `normalize.llm_parse_stub` re-parses every LLM proposal through `parse_constraints.parse_single_constraint_text`, so a constraint the regex could not extract from the original NL it also cannot extract from the LLM's paraphrase. Audit can only re-route an already-parseable span (polarity/value), never recover a regex-unparseable constraint — and it adds spurious noise on every set (familiar `1→10`, medium `14→40`). Net F1 ≤ deterministic on all three. **Audit-by-default is pure downside at the parser level.** (Audit's *theoretical* niche is non-empty — it helps when the deterministic miss is a trigger/phrasing gap on a value the regex *can* express, e.g. "check out the Forbidden City" that the LLM rewrites into the canonical `Visit …` template the regex then extracts, or a polarity mislabel on an already-located span. On these sets that niche is near-empty: the misses are dominated by value-segmentation failures the regex cannot express either way, so the paraphrase round-trip has nothing to recover.)

2. **Extract mode recovers OOD recall, but at a value-accuracy cost that only pays off on machine-templated OOD phrasing.** On HF `medium` it is a large win (`missing 121→3`, F1 `0.447→0.793`). On HF `human` the recall gain is offset by `wrong_value`/`spurious` (F1 `0.699→0.681`, net slightly negative). On the familiar-100 25-uid subset it is strongly negative (deterministic `0.935` → extract `0.758` on that same subset): the deterministic templates already reach zero missing there, so the LLM only re-derives values it gets slightly wrong against the oracle's exact strings.

**Decision: do not default `TPC_P2_LLM_PARSE` on.** The final held-out set is drawn from the familiar-100 distribution, and on that distribution (and on human-written NL) both LLM modes are neutral-to-negative; extract's only decisive win is on machine-templated OOD phrasing that is not the final distribution. Consistent with the operating rule that parser statistics diagnose but do not promote, this is parser-level evidence only — the end-to-end gate the operator runs separately is the arbiter, and it should also re-examine the harness's existing auto-enable of audit mode when a backend is configured (`agent_env/scripts/solve_phase2.py::resolve_llm_client_and_flags`), which this evidence shows adds spurious constraints with no recall benefit. The library default (`Flags()`) already keeps `llm_parse` off; no default is changed by this investigation. Regenerate with `TPC_P2_LLM_BACKEND=deepinfra scripts/parser_vs_oracle.py --split tpc_phase2_familiar_100 --disjunction --entity-resolution --branch-aware [--llm-parse]`.

## Follow-on order

1. Gate the negative-constraint fix, the required-constraint fix, the budget change, and the `required_attraction_types` time-window guard together through the pinned no-oracle path against the last promoted familiar row (`20260718T155006Z`), then promote if the end-to-end gate passes with no new parse failures or timeouts.
2. The parser is now at `~0.95` familiar-100 F1 with zero missing and zero spurious/wrong-value on `required_attraction_types`. The remaining parser defect is the comma-in-name `wrong_value` residual (`~4` attractions, `~3` restaurants); prefer the catalog-segmentation path (entity resolution) over more regex for it.
3. Run a longer local-budget sensitivity only if a future solver-only failure set becomes timeout-confounded. The promoted row does not justify it: all `23` solver-only timeouts recovered into pass cases, while none of the `74` solver-only failures timed out.
4. Re-examine the harness auto-enable of audit-mode `llm_parse` when a backend is configured (see "LLM parsing vs deterministic" above): the parser-level evidence shows it adds spurious constraints with no recall benefit on familiar-100 or HF, so an end-to-end gate should confirm whether keeping it on is justified before the next promoted row.
5. Package and smoke-test the official harness interface, including oracle hiding, output layout, and tool access.
6. **Solver-only headroom (timed-visit-at-named-POI, G8).** Now that the parser is at `~0.95` F1, the `26.0` solver-only FPR is the binding ceiling on familiar-100 end-to-end. The dominant gap is the timed-visit-at-named-POI family: sole logical blocker in `53` of the `74` failures, split by named-position DB into `44` accommodation meals, `39` attraction-window visits, `21` restaurant meals. See [solver headroom analysis](tpc_phase2_solver_headroom.md). Staged plan:
   1. **Landed (opt-in, `TPC_PIN_TIMED_WINDOWS`, default off, floor byte-identical):** project window/position names into `required_hotels` (pins hotel selection to a named-accommodation meal) and `_pin_timed_windows`, an acceptance-gated *local* retime (`max(earliest, arrival)`, dwell clamped to `end_before`) run before the `_pack_plan` acceptance gate. Handles the meal cases that only need retiming within a day.
   2. **Gate it:** record a clean flags-off solver-only familiar-100 baseline (no committed familiar row records flags; both ran a Qwen backend that auto-enables `llm_parse`, so neither is flags-off), then run flag-on through the pinned no-oracle gate (`make phase2-gate`) against `20260718T155006Z`; promote only if solver-only FPR improves with no new parse failures or timeouts.
   3. **Next increment — day resequencer:** the local retime cannot move a POI across the day's activity order, so the `39` attraction cases whose required window sits in a different part of the day than the greedy placed them (e.g. a required evening visit built into the morning) stay unfixable. Add a within-day resequencing move under the same flag: order a day's non-intercity activities by their target window (windowed POIs at their `[earliest, end_before]`, others by current time), recompute the full day's inbound legs sequentially via `_get_transport`, and commit on a deepcopy only if the full checker accepts and the preference key does not regress. Keep it strictly local to one day (intercity anchors fixed) and acceptance-gated, so the floor stays byte-identical when off. Do **not** revive the `arrive_no_later`-from-`end_before` hint (it regressed commonsense by pruning transport — see the analysis).

The public material still does not specify a runtime contract.
Until it does, `300 s` and `900 s` are local assumptions for sensitivity analysis, not organizer-confirmed limits.

## References

- [Stable design](tpc_phase2_design.md)
- [Evaluation methodology](tpc_phase2_eval.md)
- [Dataset boundaries](tpc_phase2_hf_dataset.md)
- [Competition reference](reference/competition.md)
- [Baseline ledger guide](phase2_baselines/README.md)
