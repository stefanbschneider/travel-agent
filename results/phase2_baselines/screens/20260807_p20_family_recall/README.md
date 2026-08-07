# P20 — close the two dominant family-recall gaps

**Date** 2026-08-07 · **Branch** `implementation/p20-family-recall-cuisine-attraction-type`
**Contract** Static parser screen (R22, the standing phrasing tripwire) plus two focused
`parse_constraints.py` bug fixes. No solve, no LLM call, no WorldEnv, no held-out artifact used.
Read-only over released and HF-local data.

P19 ([closed screen](../20260807_p19_unidentified_gap/README.md)) ranked
`required_attraction_types` (160 instances, 63.75% miss) and `cuisine_preference` (127 instances,
78.74% miss) as the two largest family-recall residuals by `instances x miss_rate`, well ahead of
the next family. This item implements the parser-side slice the roadmap scoped for them.

## The measurable universe is much smaller than the miss counts suggest — read this first

Before writing any pattern, every miss in both families across all six released/HF sets was
partitioned by whether its **oracle value** is an English literal or a CJK literal
(`scripts/phase2_family_recall_gap_partition.py`, output below, pre-fix code):

| set | family | instances | oracle literal |
| --- | --- | --- | --- |
| local_released_150 | cuisine_preference | 3 | **English** |
| hf_easy | cuisine_preference | 30 | CJK |
| hf_easy | required_attraction_types | 21 | CJK |
| hf_medium | cuisine_preference | 33 | CJK |
| hf_medium | required_attraction_types | 28 | CJK |
| hf_human | cuisine_preference | 27 | CJK |
| hf_human | required_attraction_types | 50 | CJK |
| hf_preference_base50 | cuisine_preference | 7 | CJK |
| hf_preference_base50 | required_attraction_types | 3 | CJK |
| local_released_150 | required_attraction_types | 0 | — (no misses at all) |

**Only 3 clauses, all `cuisine_preference`, all on `local_released_150`, are measurable as
`matched` locally.** `diff_constraints` requires `_canon(parsed) == _canon(oracle)`; emitting an
English value against a CJK oracle literal moves a clause from `missing` to `wrong_value`, never to
`matched` — the same wall [P16's screen](../20260807_p16_entity_resolution_probe/README.md) already
measured ("`missing` converts into `wrong_value` almost one-for-one"). This is **not a loader
artifact**: checked directly against `chinatravel/data/load_datasets.py` and
`parser_vs_oracle.load_hf_queries`. `tpc_phase2_test`/`tpc_phase2_familiar_100` load from a
physically separate, pre-translated English tree (`chinatravel/data/en/`, confirmed by reading a raw
`hard_logic_py` off disk — English literals like `"Sichuan cuisine"`, `"historical site"`). The four
HF sets' `hard_logic_py` is never translated regardless of the query's English
`nature_language_en`, because HF's own generation pipeline never produced an English version of it.
`required_attraction_types` has **zero** English-literal misses anywhere in released data, so **that
family's `matched` count cannot be moved by any local measurement** — ship-and-defer-to-R26 is the
honest position for it, not a green.

`target_uids.txt` in this directory is the 3-row output of that partition (pre-fix), i.e. the
exact target list this change was developed against, per the roadmap's requirement.

## What landed

### 1. Two bugs in `parse_cuisine_preference`, fixed and attributable to `local_released_150`

Both close all 3 of the English-literal-measurable misses above.

- **List lead-in leak.** `["one of the following", "Japanese cuisine"]` is the roadmap's own cited
  example. The "want to try X restaurant" pattern is a non-greedy scan for the first `" restaurant"`
  it can reach; on "want to try one of the following restaurant types: X" that first occurrence
  sits inside the lead-in phrase itself. Fixed with a closed set of lead-in fillers added to the
  pattern's existing stop-set (not a stoplist over cuisine values — the sibling list pattern still
  extracts the real value from the same sentence). Also extended one sibling pattern's word order
  ("types of restaurants" vs. "restaurant types") to accept the same "one of " lead-in, since it
  was missing there entirely (`20250322130847337844`, "types of restaurants" order).
- **Numbered-OR-arm boundary swallow.** The released generator does not always end an OR arm with
  a period before the next arm's digit ("... restaurant types: Cantonese cuisine 2. The total
  budget ..."); a bare `.+?` scanning for the next period over-captured into the next arm's leading
  number, returning `"Cantonese cuisine 2"`. Fixed with a lookahead terminator local to these four
  cuisine list-patterns (deliberately not added to the shared `_LIST_TERM`, per the roadmap's own
  note on why digit-adjacency there was previously rejected).

Local effect: `local_released_150` `cuisine_preference` `matched` `7 -> 14` (the 3 target clauses
plus 4 more the same fixes happened to also unblock), `spurious` `4 -> 1`, `missing` `3 -> 0`.

### 2. Free-prose fallback patterns for both families

Every anchored pattern in both `parse_required_attraction_types` and `parse_cuisine_preference`
requires an explicit `"restaurant(s)"`/`"attraction type(s)"`-shaped noun phrase — the templated
register these files were built against always uses one. Free prose (the register held-out most
resembles) usually states the same requirement as a bare verb + value instead: `"want to eat
hotpot"`, `"try Sichuan cuisine"`, `"We like Hunan cuisine"`, `"are interested in cultural
attractions"`, `"visit garden attractions like the Humble Administrator's Garden"` — no
"restaurant"/"attraction type" word anywhere in the sentence.

**Gated as a last-resort fallback**: both fallbacks (`_free_prose_type_mentions` in
`parse_constraints.py`) run only when every anchored pattern above found nothing. Consequence
proved structurally, not just tested: familiar-100 always populates both families through the
`"Include the following attraction/restaurant types: X"` template, so the fallback never executes
there, and the fallback can only turn a `missing` family into `matched`/`wrong_value` — it can never
override a value an anchored pattern already found. Values are the canonical English strings
`chinatravel/symbol_verification/concept_func.py`/`concept_labels.py` actually return, not the
casing free text uses.

**Safety mechanisms, iterated in this screen after two measured false positives**:

- Negation is checked at both the trigger *and* the matched value's own position — a single check
  at the trigger missed a case where a non-negated trigger's 80-char window ran into a *later*,
  separately-negated clause (`"visit X and do not want to visit any Museum..."`; found via the
  existing regression test `test_negated_attraction_types_do_not_leak_into_required`).
- A proper-noun guard skips matches immediately preceded by a capitalized word, extended to look
  past punctuation/dash/paren separators to the nearest real word — a POI name routinely appends a
  type word after `" - "` (familiar-100: `"Sichuan University (Wangjiang Campus) - Museum"`, whose
  literal preceding token is just `"-"`; found via the familiar-100 byte-identity floor test, which
  is exactly what it exists to catch).
- A bare `universit(y|ies)` alternative was tried and dropped: measured spurious on `hf_human`
  (`"We are both university students"`, and `"tour universities like [3 named universities]"`,
  where the oracle records only `required_attractions`). Kept only the anchored `"university
  campus(es)"` phrase, at the cost of one recoverable `hf_easy` instance (`"visit some
  universities"`).
- Two or more distinct values found with a bare `" or "` between their span are dropped entirely
  rather than flattened into a simultaneous AND requirement (P20: "never flatten 'A or B' into two
  simultaneous requirements") — pinned by
  `tests/phase2/test_parser_phrasing_p20.py::test_cuisine_preference_or_arms_stay_branch_local`.
- A closed set of plausible-looking values is deliberately **not** included: `"local
  specialties"`/`"local cuisine"`/`"local specialty dishes"` name no cuisine in the sentence (the
  oracle value is city-derived, which this file has no access to); `"such as X"` introduces an
  example, not a requirement; a single `"Huaiyang cuisine"` -> `Huizhou cuisine` instance looks like
  a released-data translation quirk, not a general synonym; `"sweet foods and bread"` and `"go
  drinking"`/`"drinking"` are too ambiguous to anchor safely (the latter easily confused with
  unrelated "drinks"/"drinking water" mentions).

## R22 — the standing phrasing tripwire

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
    --out-dir results/phase2_baselines/screens/20260807_p20_family_recall
```

**GREEN.** `familiar_100` stays `0/1109` (also independently pinned by the pre-existing
`tests/phase2/test_parser_phrasing_p15.py::test_familiar_100_parsed_variants_are_byte_identical`
hash test — passes unmodified). No free-prose set's parse-gap count rose:

| set | parse-gap clauses, before -> after | C-LPR ceiling | FPR ceiling |
| --- | --- | --- | --- |
| familiar_100 (control) | 0/1109 -> 0/1109 | 100.0 -> 100.0 | 100.0 -> 100.0 |
| local_released_150 | 6/522 -> 5/522 | 98.85 -> 99.04 | 96.0 -> 96.67 |
| hf_easy | 127/1579 -> 97/1579 | 91.96 -> 93.86 | 58.0 -> 68.0 |
| hf_medium | 126/1264 -> 78/1264 | 90.03 -> 93.83 | 52.67 -> 80.67 |
| hf_human | 99/687 -> 81/687 | 85.59 -> 88.21 | 48.05 -> 55.19 |
| hf_preference_base50 | 19/260 -> 14/260 | 92.69 -> 94.62 | 62.0 -> 72.0 |

("before" is [`20260807_generalization_post_p15`](../20260807_generalization_post_p15/README.md),
the last R22 run prior to this change, same git lineage.)

**Spurious counts (the real regression risk — a wrong extracted family, not merely a
mismatched-value one) are flat or down on every set**, checked at both the whole-parse total and
the two target families specifically:

| set | total spurious, before -> after | cuisine_preference spurious | required_attraction_types spurious |
| --- | --- | --- | --- |
| familiar_100 | 0 -> 0 | — | — |
| local_released_150 | 41 -> 40 | 4 -> 1 | 3 -> 3 |
| hf_easy | 177 -> 177 | 0 -> 0 | 9 -> 9 |
| hf_medium | 114 -> 114 | 0 -> 0 | 1 -> 1 |
| hf_human | 44 -> 44 | 0 -> 0 | 2 -> 2 |
| hf_preference_base50 | 32 -> 32 | 0 -> 0 | 1 -> 1 |

`wrong_value` counts rose substantially on the CJK-oracle sets (e.g. `hf_medium`
`cuisine_preference` `0 -> 32`). This is the expected, already-anticipated `missing -> wrong_value`
conversion described above, not a new defect — the family is now populated with a plausible English
value that simply cannot equal a Chinese oracle literal, on data this project cannot measure
`matched` against locally regardless of extraction quality.

## Honest scoring against P20's stated acceptance bar

The roadmap requires: familiar-100 `0/1109` (met — structurally, not just by measurement); no
free-prose set's gaps/spurious rising (met, both counts, table above); **"each target family's
`matched` count must rise on at least one English-literal set."**

- **`cuisine_preference`: met.** `local_released_150` `matched` `7 -> 14`.
- **`required_attraction_types`: cannot be met with local data, and this is not a gap in the
  implementation — it is a gap in what released/HF data can measure.** Zero English-literal misses
  exist for this family anywhere locally (table above), so no code change to it can move `matched`
  on any local set no matter how correct the change is. The fallback patterns for this family are
  shipped anyway on the same bounded-risk argument P16 used for its own unmeasurable-locally
  extension: familiar-100 cannot regress (structural gate), spurious is flat everywhere it was
  measured, and the coverage-ceiling proxy — which tracked realized e2e C-LPR closely on the
  2026-08-06 phrasing-fix screen — moved up on every free-prose set. Whether it earns real
  `matched` credit is a question only the held-out-shaped register (or R26's e2e gate) can answer.

**R26 is the deciding measurement and is explicitly not run here.** CLAUDE.md's two-VM rule and
[P15's Tier B precedent](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction)
("its safety can only be shown by an e2e run this box must not start") both bind: this is the
coding VM. [R26](../../../../docs/tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets) is
recorded as pending for the Evaluation workstream, using this directory's `target_uids.txt`.

## Bar

`pytest tests/phase2` green, no pre-existing test edited or its assertion weakened; new tests in
`tests/phase2/test_parser_phrasing_p20.py` cover both bugs (positive, negation, numbered-boundary
edge cases including a decimal non-match, and an explicit OR-arm isolation case) plus the two
measured-and-fixed false positives (negation-through-a-later-clause, dash-adjacent proper noun,
bare-word university ambiguity) as regressions in the existing accuracy/generalization suites this
change touches. Regenerate this screen with:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_family_recall_gap_partition.py \
    --out results/phase2_baselines/screens/<date>_<name>/target_uids.txt
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
    --out-dir results/phase2_baselines/screens/<date>_<name>
```
