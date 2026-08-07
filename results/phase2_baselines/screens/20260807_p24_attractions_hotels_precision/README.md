# P24 screen: `required_attractions` / `required_hotels` precision

Static, definitional screen for the second of two P24 commits
([docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints](../../../../docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints)).
Coding-VM, no eval-machine slot used. Base: the P24 intercity commit
([screen](../20260807_p24_intercity_oracle_fix/README.md), `git_sha a6c80e05`).

Unlike `intercity_mode` (the other P24 commit), these two families are **real** over-extraction,
confirmed by direct sampling: `has_marker_clause = 0` for every sampled `required_attractions`/
`required_hotels`-spurious query on `hf_easy`/`hf_medium`/`hf_human` (no `attraction_name_set` /
`accommodation_name_set` clause anywhere in `hard_logic_py`) — the doc's original diagnosis for
these two families holds.

## Root causes, found by sampling the spurious captures directly

**`required_attractions`.** `parse_required_attractions`'s `(?:want|wish|hope)\s+to\s+visit\s+(.+?)`
pattern has no delimiter between "visit `<city>`" and a trailing budget/day-count clause when no
comma precedes it, so the dominant free-prose shape —
`"I want to visit Nanjing for a day by myself with a budget of 1800 RMB."` — is captured whole as
one "attraction name". A second, smaller shape: the same greedy capture spanning
`"visit <city> for N days and would like to {eat at/dine at/try} <restaurant/cuisine>"` invents a
`required_attractions` entry for a requirement that is really `required_restaurants`/
`cuisine_preference` (their own anchored patterns already capture it correctly).

**`required_hotels`.** The `stay at/in X` pattern's existing room-type guard only matched chunks
*starting* with `a single/double/twin`, missing the quantified/descriptive phrasings that are
actually dominant in free prose: `"stay in two twin rooms"`, `"stay in two rooms"`, `"stay in a
room with a double bed"`, `"stay in a big bed room"`.

## The fix, and why it runs per split-part, not on the whole chunk

Both patterns split a captured chunk on `" and "` into candidate names. The first version of this
fix filtered the **whole chunk** before splitting — simpler, and it drove `required_attractions`
spurious to `0` everywhere, but a review pass (advisor) caught a regression it introduced: for
queries with a *real* attraction reference following the trip-framing text (e.g. `"visit Chongqing
for 2 days and would like to go to the Great Hall of the People"`), filtering the whole chunk threw
away the genuine second half along with the invented first half, converting `wrong_value` (some
attempt, oracle has a real clause) into `missing` (no attempt at all) on ~19 hf_easy queries alone.
Moving the guards inside the per-part loop fixes this: `"Chongqing for 2 days"` is dropped, `"would
like to go to the Great Hall of the People"` survives (imperfect — it still carries a junk verb
prefix, pre-existing noise this fix does not address — but strictly better than silence). The
whole-chunk version was caught and corrected before it was ever committed (never landed on this
branch); the measurements below are all from the per-part version. No `wrong_value → missing`
regression on any set with it.

Guards in `required_attractions`:

1. On the whole chunk, before splitting: reject if an eat/dine/try cue appears anywhere (the
   restaurant/cuisine leak). Checked on the whole chunk, not per part, because a food list like
   "try Jiangsu and Zhejiang cuisine" splits on " and " into two cuisine names, not one cuisine
   name plus an unrelated attraction — a per-part version of this guard was tried first and missed
   exactly that case (`"Zhejiang cuisine"` still leaking into `required_attractions`); moving it to
   the whole chunk closed it (`hf_easy` spurious `11 → 10`).
2. Per part (after splitting on " and "): reject a part containing budget/currency/day-count/
   solo-travel markers (`budget`, `RMB`, `¥`, `yuan`, `alone`, `by myself`, `for (up to two filler
   words) day(s)`).
3. Per part: reject a part with no capitalized token (filters plain-sentiment captures with no
   name in them at all: "some cool places", "places with beautiful scenery", "the university town
   there").

And for `required_hotels`: reject a part matching `(quantifier) (descriptor words) room(s)` or
`a/an room ...` (covers "two twin rooms", "two rooms", "a room with a double bed", "a big bed
room").

## Measurement

`scripts/parser_vs_oracle.py` family stats, before (base commit, unaffected by this one) vs. after:

**`required_attractions`**

| set | matched | missing (before→after) | spurious (before→after) | wrong_value (before→after) |
| --- | --- | --- | --- | --- |
| hf_easy | 0 → 0 | 11 → 11 | 105 → 10 | 19 → 19 |
| hf_medium | 0 → 0 | 17 → 37 | 25 → 0 | 24 → 4 |
| hf_human | 0 → 0 | 15 → 16 | 25 → 3 | 8 → 7 |
| hf_preference_base50 | 0 → 0 | 5 → 6 | 155 → 12 | 25 → 24 |
| familiar_100 (control) | 19 → 19 | 0 → 0 | 0 → 0 | 4 → 4 |
| local_released_150 | 5 → 5 | 2 → 2 | 6 → 5 | 4 → 4 |

**`required_hotels`**

| set | matched | missing | spurious (before→after) | wrong_value |
| --- | --- | --- | --- | --- |
| hf_easy | 0 → 0 | 18 → 18 | 14 → 0 | 12 → 12 |
| hf_medium | 0 → 0 | 0 → 0 | 35 → 1 | 0 → 0 |
| hf_human | 0 → 0 | 0 → 0 | 6 → 5 | 0 → 0 |
| hf_preference_base50 | 0 → 0 | 0 → 0 | 0 → 0 | 6 → 6 |
| familiar_100 (control) | 16 → 16 | 0 → 0 | 0 → 0 | 0 → 0 |
| local_released_150 | 2 → 2 | 0 → 0 | 7 → 6 | 6 → 6 |

Totals across the four free-prose sets: `required_attractions` spurious `310 → 25` (92% reduction),
`required_hotels` spurious `55 → 6` (89% reduction). `matched` unchanged on every set (`0` on
free prose both sides — neither family was ever producing a *correct* value there, only
over-extracting on queries with no such requirement; `familiar_100`/`local_released_150` byte-
identical control). Bar from the roadmap item met and exceeded on both families: spurious falls on
every free-prose set it was nonzero on, matched falls on none.

The `missing`/`wrong_value` shifts (e.g. medium `required_attractions` missing `17 → 37`) are the
honest re-labeling this fix causes, not a regression: `clause_is_covered()` checks family
*presence*, so a query whose garbage capture used to count as "some attempt" now correctly shows
"no attempt" once the garbage is gone — the same mechanism documented in the intercity commit's
screen. `parse_gap` clauses rose accordingly on `medium` (`111 → 131`) and `human` (`108 → 109`);
`easy` and `preference_base50` are unchanged by this commit (`99`, `14`). The overall parse
**precision** metric — the number this item exists to move — rose on every free-prose set:
`easy 0.7433 → 0.8528`, `medium 0.7929 → 0.8924`, `human 0.786 → 0.8363`,
`preference_base50 0.735 → 0.865` (see `probe.json`).

## Residual, not this commit

`required_attractions` spurious residual (`hf_easy 10`, `hf_human 3`, `hf_preference_base50 12`,
`hf_medium 0`): mostly capture fragments that fuzzy-match a real POI closely enough to pass the
capitalization guard while still being wrong (`docs/tpc_phase2_roadmap.md`'s "Art Museum 2"-shaped
case) or a proper-noun location mentioned in a generic-category sentence ("the gardens in Suzhou").
Per the roadmap's own diagnosis, closing this needs catalog fuzzy-matching (the entity-resolution
layer, flag-gated), not another lexical rule — out of scope here.
`required_hotels` `wrong_value` (unchanged: `hf_easy 12`, `hf_preference_base50 6`) is a different,
untouched defect.

**`required_restaurants` recall gap, found while checking the food-clause guard above.** The guard
correctly keeps restaurant/cuisine references out of `required_attractions`, but a sampled check of
15 `hf_easy` queries with an "eat/dine/try" clause found `required_restaurants`/`cuisine_preference`
actually captures only ~40% of them — cuisine-type phrasing ("try Hubei cuisine") is caught
reliably, specific-restaurant phrasing ("would like to eat at Siji Minfu near Qianmen") is caught
only sometimes. The other ~60% are dropped by both families, not misrouted into this one. That is a
real `required_restaurants` recall residual (a P15/P20-shaped item), not something this commit's
guard can or should fix — recording it here would only move the wrong-family invention P24 exists
to remove.

## Reproduce

```
.venv/bin/python -m pytest tests/phase2/test_parser_accuracy.py -k "attraction or hotel"
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
    --out-dir results/phase2_baselines/screens/20260807_p24_attractions_hotels_precision
```
