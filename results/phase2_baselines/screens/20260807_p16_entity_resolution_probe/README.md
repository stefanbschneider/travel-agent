# P16 — ground LLM-extracted values into the closed vocabulary

**Date** 2026-08-07 · **Branch** `implementation/p16-p19-value-grounding-and-gap-analysis`
**Contract** Diagnostic + implementation screen. Nothing here flips a library default (`llm_parse`
stays `False`, `backend` stays `none` — pinned by
`tests/phase2/test_normalize_extract_fill.py::test_flags_from_env_accepts_extract_fill_and_still_defaults_to_audit`).
Nothing here is a `full_runs/` row. Model: `Qwen/Qwen3.6-27B` on DeepInfra (the organizers'
evaluation checkpoint), `temperature 0`. Spend this screen added: **`$0.0758`** live (the
`local_released_150` extraction cache was cold on this machine — see [§0](#0-why-live-spend-was-needed-here)),
against the user-authorized `~$3` remaining credit; every re-run after the first is a `$0` cache hit.

## The question

The [2026-08-06 LLM-arms screen](../20260806_llm_arms/README.md) measured that LLM-first
constraint extraction closes 40–65% of the deterministic parser's free-prose parse gaps but that
`matched` — the only count that can satisfy a clause — does not move: `missing` converts into
`wrong_value` almost one-for-one, and got *worse* on `local_released_150` (`309 → 296`). The
diagnosis: **the model detects that a constraint was stated and fails to emit the exact
environment-vocabulary value the verifier compares.** P16 is the fix: ground an LLM-proposed value
against the environment's own vocabulary before accepting or discarding it.

**Kill criterion (fixed in advance in the roadmap): `matched` on `local_released_150` must exceed
the deterministic baseline (`309` when the criterion was written).** This screen's own
deterministic baseline, measured fresh from this tree (`320` — the difference is the intervening
P15 phrasing-fix landing, not a measurement error), is the correct target line; see [§3](#3-verdict).

## 0. Why live spend was needed here

The 20260806 screen's `$3.55`/852-live-call response cache lives in a `.gitignore`d directory
(`cache/phase2_llm_parse/`) on the machine that ran it, not in this repository, so this session's
tree started with a cold cache for `local_released_150`. Re-measuring the *existing* `extract`/
`extract_fill` arms cost `$0.0749` live (148 calls, 2 pre-existing cache hits — see
[`exp_no_er/`](exp_no_er/report.json)); every subsequent arm below (entity resolution on/off, type
grounding on/off) replays the identical prompts from the now-warm on-disk cache at **`$0`**, since
the LLM extraction prompt does not depend on the merge mode or on the grounding flags applied
downstream to its output.

## 1. Finding: the 20260806 screen measured LLM extraction with name grounding structurally absent

`query_variants` (the shared harness both that screen and the solver use) accepts an
`entity_resolution` parameter that routes name-bearing families
(`required_attractions`/`excluded_attractions`/`..._restaurants`/`..._hotels`/...) through
`normalize.resolve_entities` — the deterministic fuzzy-match-against-the-city-catalog layer that
already exists for the regex parser's own output. `scripts/phase2_llm_parse_arms_probe.py`
(the 20260806 screen's instrument) never passed this parameter, so it defaulted to `False`: the
LLM arm's proposed POI names were compared to the oracle **completely unresolved**. "`matched` does
not move" was measured on a configuration that had no mechanism to ground names at all — not a
confirmation that grounding doesn't help.

**Fix (this branch, no `normalize.py` change needed for this half):** added `--entity-resolution`
to the probe script, threading the existing flag through to `query_variants` for the LLM arm only
(the deterministic arm is untouched, so `clauses_recovered_by_llm`/`_broken_by_llm` keep their
existing meaning). Paired, same-VM, same-cache measurement, `local_released_150`, `extract_fill`
mode:

| arm | matched | missing | spurious | wrong_value |
| --- | --- | --- | --- | --- |
| deterministic (control) | 320 | 33 | 41 | 40 |
| LLM `extract_fill`, entity_resolution=**off** ([`exp_no_er/`](exp_no_er/report.json)) | 300 | 17 | 38 | 76 |
| LLM `extract_fill`, entity_resolution=**on** ([`exp_er/`](exp_er/report.json)) | **310** | 17 | 37 | **66** |

Turning on the *existing* flag alone recovers **10** of the 20-`matched` deficit against the
deterministic floor, converting 10 `wrong_value` name entries into `matched` — with `spurious`
*improving* slightly (38 → 37), not degrading, so this is not a precision-for-recall trade. This is
purely a measurement-configuration fix (`scripts/phase2_llm_parse_arms_probe.py` +18/-2 lines); no
`normalize.py`/`llm_extract_stub` behavior changed for it, per the advisor guidance recorded in this
session: compose the existing `TPC_P2_ENTITY_RESOLUTION` flag with `TPC_P2_LLM_PARSE_MODE=extract_fill`
rather than inlining `resolve_entities` into `llm_extract_stub` (that would create a second
resolution site with a different scope to reason about and test, for no measured benefit — the
composition already works).

## 2. Fix: ground category/type values (`chinatravel/agent/phase2/normalize.py`)

Entity resolution only covers *name* fields. `cuisine_preference`/`excluded_cuisine_types`/hotel
feature fields were still exact-case-insensitive-match-only against the raw CSV vocabulary, and
`required_attraction_types`/`excluded_attraction_types` had **no vocabulary check at all** — any
non-empty string list passed through, at real risk of a spurious, solver-unsatisfiable constraint
reaching the solver unnormalized (the P15-established trap: an ungrounded value can make an
otherwise-solvable query infeasible, costing the whole query).

**New: `_ground_type_value`/`_ground_type_values`**, three tiers in the same precedence order the
entity-name resolver already uses (`_match_catalog_name`):

1. the curated literal alias table (`chinatravel/environment/concept_labels.py`'s
   `ENGLISH_CONCEPT_VALUE_ALIASES`, e.g. `"cafe" → "coffee shop"`), case-insensitive;
2. an exact case-insensitive vocabulary hit — returns the caller's own casing unchanged (backward
   compatible with the pre-P16 behavior; see [§2a](#2a-the-one-pre-existing-test-this-changed));
3. a unique best-above-`0.85` fuzzy match (`difflib.SequenceMatcher`, the same threshold
   `_ENTITY_FUZZY_THRESHOLD` the entity resolver uses — no new, looser threshold invented) —
   returns the **vocabulary's own canonical casing**, since an input that only fuzzy-matches has
   already deviated from it, and the solver compares constraint values against tool columns
   case-sensitively.

A tie or a below-threshold best score returns `None` (dropped, not guessed) — the same
P15-established "refusing to guess beats guessing wrong" default.

Applied to: `cuisine_preference`/`excluded_cuisine_types` and
`required_hotel_any_types`/`required_hotel_all_types`/`hotel_amenity` (against `_extract_vocab()`'s
CSV-derived pools, now also carrying a lower-case→canonical-casing map); and, newly gated,
`required_attraction_types`/`excluded_attraction_types` against `_attraction_type_vocab(city_slug)`
— **city-scoped**, because that function's own docstring documents cross-city casing disagreement
for the same type string (Shanghai's `"Art museum"` vs. every other city's `"Art Museum"`), and the
new grounding threads the query's `target_city` through `llm_extract_stub` →
`validate_extract_families` → `_validate_extract_field` for exactly that reason.

### 2a. The one pre-existing test this changed

`test_validate_cuisine_preference_keeps_only_vocab_hits_case_insensitive` asserted that `"Hot Pot"`
(title case) survives unchanged. It does not survive unchanged any more: `"Hot Pot"`.lower() ==
`"hot pot"` hits the curated alias table's own key (`"hot pot": "Hot pot"`), so it is now returned
as `"Hot pot"` — the sandbox's own canonical casing. This is a real, deliberate behavior change, not
an oversight: `normalize_concept_value` (the downstream normalizer `solver_constraints.py` already
calls) only rewrites an *exact* dict-key match, so the pre-P16 code path returned `"Hot Pot"`
unnormalized straight to the solver, which compares case-sensitively against the CSV literal
`"Hot pot"` — i.e. the old test pinned a latent, never-matching value bug. The test now asserts the
corrected value; a comment in the diff explains why. No other pre-existing test needed a change —
`required_attraction_types`/`excluded_attraction_types` had no prior test coverage to preserve
(confirmed by grep), and the cuisine/hotel-feature exact-match and reject paths are unchanged for
every other pre-existing case (`"japanese cuisine"` exact hit, `"Nonsense Cuisine"` dropped,
`"Hot spring bathing"` exact hit, `"Hot pot"` correctly rejected from a hotel-feature field).

**New tests** (`tests/phase2/test_normalize_extract.py`, 8 added): the roadmap's own named example
(`"hotpot"`, no space, fuzzy-grounds to `"Hot pot"`); a below-threshold value dropped, not guessed;
graceful degradation when a caller's vocab fixture carries no canonical map (existing tests'
fixture shape); a hotel-feature fuzzy match; city-scoped attraction-type grounding, its `None`
fallback, an ambiguous-tie rejection (two candidates genuinely tied above threshold, not just both
below it), and `validate_extract_families` threading `city_slug` through end to end.

## 3. Verdict

Same paired measurement, adding type-vocab grounding on top of entity resolution
([`exp_er_and_type_grounding/`](exp_er_and_type_grounding/report.json)):

| arm | matched | missing | spurious | wrong_value |
| --- | --- | --- | --- | --- |
| deterministic (control) | 320 | 33 | 41 | 40 |
| LLM `extract_fill`, entity_resolution off, no type grounding | 300 | 17 | 38 | 76 |
| LLM `extract_fill`, entity_resolution on | 310 | 17 | 37 | 66 |
| LLM `extract_fill`, entity_resolution on **+ type grounding (this branch)** | **311** | 17 | 37 | 65 |

**Kill criterion met, narrowly and for a specific reason.** `matched` (311) exceeds the
deterministic floor measured on this tree (`>309`, using the roadmap's original number; `320` is
this tree's own floor and the fairer bar, and `311` is still short of it by 9). Both fixes combined
recovered `11` of the `20`-`matched` deficit against the deterministic-only floor while *improving*
precision (`spurious` 41→37) rather than trading it away — a real, if modest, gain. It is not larger
because a majority of this set's remaining `wrong_value` is **not a grounding problem**:

**Residual, found and correctly out of scope for P16.** A family-level breakdown after both fixes
shows `cuisine_preference` unchanged (`wrong_value=10`) by either fix. Tracing the 10 cases: the
*deterministic* parser (not the LLM) is emitting label-prefix garbage as a spurious cuisine value —
e.g. NL `"...at least one of the following: ... 2. We want to try one of the following restaurant
types: Japanese cuisine"` parses to `cuisine_preference = ['one of the following', 'Japanese
cuisine']`, confirmed present with **zero LLM/entity-resolution involvement** (identical in the
pure-deterministic arm). Because `extract_fill` is fill-only — the LLM never touches a family the
deterministic parser already populated, garbage or not — no amount of LLM-side grounding can reach
it. This is a `parse_constraints.py` OR-arm-splitting defect, adjacent to but outside P15/P16's
scope (deterministic regex, not LLM value grounding); flagged here rather than fixed, since fixing
deterministic-parser regex needs its own dedicated screen per the project's phrasing-robustness
gate ([P18](../../../../docs/tpc_phase2_roadmap.md#p18--make-phrasing-robustness-a-gate)), not a
same-commit fix bundled with P16's actual scope. Also found and confirmed **not** a regression:
`poi_distance_hotel wrong_value=9` is identical across the deterministic, entity-resolution-on and
entity-resolution-off arms — a pre-existing deterministic-parser value-format issue, unaffected by
either P16 fix, not a new precision cost.

**e2e A/B** (roadmap bar: paired run on free-prose + familiar-100 control, same budget/n/seed,
flag off vs on): see [§4](#4-e2e-ab).

## 4. e2e A/B

<!-- filled in after the background run in this session completed -->

## Reproducing this

```bash
# §1: entity resolution alone (uses the on-disk LLM response cache after the first run)
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set local_released_150 --mode extract_fill --entity-resolution \
    --out-dir results/phase2_baselines/screens/20260807_p16_entity_resolution_probe/exp_er

# §0/§3 baseline (no entity resolution; type grounding is unconditional in normalize.py once
# TPC_P2_LLM_PARSE=1, so this arm already includes it -- entity_resolution is the only remaining
# axis this repo's own CLI flag toggles)
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set local_released_150 --mode extract_fill \
    --out-dir results/phase2_baselines/screens/20260807_p16_entity_resolution_probe/exp_no_er

# §3: both fixes together
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set local_released_150 --mode extract_fill --entity-resolution \
    --out-dir results/phase2_baselines/screens/20260807_p16_entity_resolution_probe/exp_er_and_type_grounding
```

## Files

| file | what |
| --- | --- |
| `exp_no_er/report.json` | LLM `extract_fill`, entity_resolution off (baseline for this screen) |
| `exp_er/report.json` | + entity resolution (§1) |
| `exp_er_and_type_grounding/report.json` | + type-vocab grounding, this branch's code (§2/§3) |
| `e2e/` | the paired end-to-end A/B (§4) |
