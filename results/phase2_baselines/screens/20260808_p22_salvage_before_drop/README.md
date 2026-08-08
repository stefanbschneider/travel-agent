# P22 — salvage-before-drop follow-up (closes R30's clean-causal loss)

**What this is.** [R30](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
found `TPC_P2_DROP_UNSATISFIABLE_NAMES` caused one genuine loss: `local_released_150` uid
`20250324075652034944` went from passing (flag off) to failing (flag on) because the dropped
`required_attractions` value —
`"Xixi Paradise Commercial Street, wish to stay in single-bed rooms"` — was a real, oracle-required
attraction (`"Xixi Paradise Commercial Street"`) with an unrelated trailing clause tail-swallowed
onto it by the parser. Dropping the whole value threw the real requirement away with the garbage.
R30's own writeup and `docs/tpc_phase2_roadmap.md`'s P22 section both named the fix: "before falling
back to a full drop, try to salvage a real catalog POI name that is a prefix/cleanly-separable
substring of an otherwise-unmatched capture, using the same catalog matcher the solver's own
constraint-application step already relies on more leniently than
`_exact_catalog_match`/`_match_catalog_name`." This screen builds and measures exactly that.

**What this is not.** Static only — no solve, no e2e re-run of R30's own gate (that is an
Evaluation-workstream job on the eval machine, per the two-VM rule; this box only builds and
unit-tests the fix and measures its static effect on the released/HF sets).

## Why the drop rule missed this in the first place

`_resolve_one_required_name` already tries, in order: `_exact_catalog_match` (normalized exact),
`_segment_entity_list` (multi-entity split), and `_match_catalog_name` (exact, then containment —
but only when the catalog name covers **≥60 %** of the candidate text, a floor deliberately set so a
short catalog name can't hijack a genuine multi-entity string ahead of segmentation getting a turn —
see that function's own docstring). The R30 loss falls *below* that floor: the real name
(`"xixi paradise commercial street"`, 31 normalized chars) covers `48 %` of the full garbage capture
(`"xixi paradise commercial street wish to stay in single bed rooms"`, 65 chars) — close, but under
the 60 % bar `_match_catalog_name` uses to protect segmentation. By the time the terminal
keep/drop branch is reached, segmentation has already had its turn and failed (this isn't a genuine
multi-entity list, just one name plus an unrelated tail), so that protection is no longer needed —
which is exactly why the fix adds a *new*, more lenient step at the terminal branch specifically,
rather than lowering `_match_catalog_name`'s own threshold (which would reopen the segmentation risk
that threshold exists to prevent).

## The fix: `_salvage_catalog_name` (`chinatravel/agent/phase2/normalize.py`)

Uses the solver's own even-more-lenient matcher — `TPCAgent._match_constraint_text` /
`parsed_verifier._match_text`: normalized `c == q or q in c or c in q`, no coverage floor at all —
the exact function that decides, at solve time, whether a plan satisfies a *kept* required-name
value. A name this finds is therefore provably one the solver would already have credited as
satisfying the constraint had the whole garbage value been kept verbatim, which is exactly R30's own
diagnosis of why the OFF (flag-off) arm passed `20250324075652034944` in the first place. Two guards
keep this from over-firing:

- **Minimum length (`_SALVAGE_MIN_NORM_LEN = 10` normalized characters).** The catalog holds entries
  as short as 2–5 characters (`"HY"`, `"China"`, `"Atour"`); with no coverage floor, a short common
  word could accidentally match inside unrelated prose. 10 characters excludes those while still
  covering every real multi-word POI name salvaged below.
- **Refuse an ambiguous tie.** If more than one catalog name of the same maximal normalized length
  matches, salvage returns `None` and the value falls through to drop — never guessed, matching
  every other resolution step in this module (`_match_catalog_name`'s own containment step has the
  identical "tie → don't guess" posture).

Wired into `_resolve_one_required_name`'s terminal branch only (`required_attractions` /
`required_restaurants` / `required_hotels`): a salvage hit returns `{"kind": "name", "value": ...}`
instead of `{"kind": "drop"}`. `_resolve_generic_location` (`position_presence`) is untouched — no
evidence yet that it has the same failure mode, and R30's finding was specifically a
`required_attractions` case; out of scope here.

## Verified against the exact R30 case

```python
>>> catalog = load_city_entity_catalog("Hangzhou")
>>> text = "Xixi Paradise Commercial Street, wish to stay in single-bed rooms"
>>> _resolve_one_required_name(text, "required_attractions", catalog, "hangzhou", drop_unresolved=True)
{'kind': 'name', 'value': 'Xixi Paradise Commercial Street'}
```

Pre-fix this returned `{'kind': 'drop'}` — the exact loss R30 measured. Regression test:
`test_salvage_recovers_tail_swallowed_poi_before_dropping` in `tests/phase2/test_entity_resolution.py`.

**R30's other target case (`20250322180344489669`, the Sauna-hotel-type garbage capture) still
drops, correctly** — no real hotel name is embedded in `"a hotel of the following type: Sauna"`, so
nothing to salvage. R30's own causal analysis already established this loss was search perturbation
unrelated to the dropped value's content, not a salvage-fixable gap, and this screen's static check
confirms the fix does not (and should not) touch it.

## Salvage rate across all released/HF sets

Instrument: `scripts/phase2_salvage_before_drop_rate.py` (reuses
`phase2_unsatisfiable_names_probe.py`'s own `measure_set` to find "unsatisfiable" — the same
definition the drop rule and its probe already use — then checks each flagged value against
`_salvage_catalog_name`).

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_salvage_before_drop_rate.py \
  --out-dir results/phase2_baselines/screens/20260808_p22_salvage_before_drop
```

| set | n | unsatisfiable values (pre-fix) | salvaged | still dropped | salvage rate |
| --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 11 | 11 | 0 | **100 %** |
| local_released_150 | 150 | 24 | 6 | 18 | 25 % |
| hf_easy | 300 | 47 | 15 | 32 | 32 % |
| hf_medium | 150 | 4 | 1 | 3 | 25 % |
| hf_human | 154 | 17 | 5 | 12 | 29 % |
| hf_preference_base50 | 50 | 9 | 3 | 6 | 33 % |

Full examples (10 per set) in `report.json`. familiar-100's `11/11` salvages are all genuine
multi-entity segmentation misses already tracked elsewhere (e.g. `"Honey Lake 1979 Cultural"` +
`"Creative Park"`, both salvaging to the one real catalog entry — segmentation didn't fully resolve
this list, but each half independently identifies the same real POI). The free-prose sets salvage
`25–33 %` of what would otherwise be a full drop — real POI names recovered from phrasing like
`"would like to see Peking University"` → `"Peking University"`, `"see ... Tiananmen Square"` →
`"Tiananmen Square"`, `"the Jintai Hotel near Huazhong University of Science"` → `"Jintai Hotel"`.

**One salvage worth double-checking explicitly, because it looks wrong at first glance and isn't:**
`hf_human` uid `h20241029143646523600`, `"Disneyland"` → `"Dream World (Shanghai Disneyland Store)"`.
Verified against the catalog directly: `chinatravel/environment/database_en/attractions/shanghai/attractions.csv`
row 267 is exactly `"Dream World (Shanghai Disneyland Store)"`, type `Amusement Park/Sports
Entertainment` — the **only** `attraction`-category entry containing "Disneyland" in Shanghai's
catalog (the other three "Disneyland" hits in the database are a restaurant and two hotels, outside
`required_attractions`' category pool, `("attraction",)` only — `_ENTITY_CATEGORY_POOL` in
`normalize.py`). This dataset's own attraction-category name for Shanghai Disneyland is this string,
not `"Shanghai Disneyland"` verbatim, so the salvage is correct, not a false positive from the
missing coverage floor.

## Bar

- [x] Unit test per shape: recovers the real R30 loss
  (`test_salvage_recovers_tail_swallowed_poi_before_dropping`); does not fire on a genuinely
  unsatisfiable capture (`test_salvage_does_not_fire_on_genuinely_unsatisfiable_capture`,
  `test_salvage_does_not_fire_on_category_value_mistaken_for_a_name`); refuses a short accidental
  match (`test_salvage_catalog_name_refuses_short_accidental_match`); refuses an ambiguous tie
  (`test_salvage_catalog_name_refuses_ambiguous_tie`); picks the unambiguous longest match
  (`test_salvage_catalog_name_picks_unambiguous_longest_match`) — all in
  `tests/phase2/test_entity_resolution.py`, alongside the existing P22 test suite (54 tests total in
  that file now, all green, no pre-existing test edited).
- [x] `scripts/phase2_unsatisfiable_names_probe.py --drop-unsatisfiable-names` re-run: every set
  still at `0` unsatisfiable-constraint queries in both arms (required-name and category-value),
  matching P22's original GREEN bar exactly — see `post_salvage_drop/summary.md` in this directory
  (`pre_drop_baseline/summary.md` is the same probe without the drop flag, the pre-fix-equivalent
  baseline the salvage-rate table above is measured against).
- [x] `pytest tests` green.
- [x] No behavior change when the flag is off: salvage only runs inside the `drop_unresolved=True`
  branch, so `Flags.from_env({})`'s byte-identical-library-floor test is untouched.

## What this authorizes

**Nothing promotes.** `TPC_P2_DROP_UNSATISFIABLE_NAMES` stays library-default-off — this is a
correctness improvement to the flag's *own* logic, not new evidence for turning it on by default.
The next step is re-running R30's exact e2e A/B (same target uids, same paired-solve contract) on the
eval machine to confirm `20250324075652034944` now passes and no new loss appears — not done here
(this box must not run e2e/solve screens; see the two-VM rule in `docs/tpc_phase2_eval.md`).
`20250322180344489669`'s search-perturbation loss remains unaddressed by design (R30 diagnosed it as
unrelated to the dropped value's content).
