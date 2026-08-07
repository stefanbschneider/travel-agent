# P15 — finish phrasing-robust extraction (restaurant/transport/budget residual)

**Date** 2026-08-07 · **Branch** `p15-phrasing-robust-extraction-tierA` · **Contract** Implementation
screen. Nothing here promotes a change and nothing here is a `full_runs/` row; this is the pre-gate
evidence for the PR that lands it. All work offline on **released** data.

Implements the `local_released_150` residual named in
[the roadmap's P15 entry](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction):
`restaurant_name` (4 clauses), `inner_transport_set` (3), `restaurant_type` (1 of 2), and the
`cost_transport` "in-city" synonym (1) — 9 of the 15 residual parse-gap clauses measured by
[`20260806_generalization_probe_after_fix`](../20260806_generalization_probe_after_fix/README.md).
The other 6 are deferred with reasons below, not silently dropped.

## Verdict up front

| gate | required | measured | |
| --- | --- | --- | --- |
| test suite | all green, no pre-existing test edited | `1132 passed` (`23` integration/llm deselected) | **PASS** |
| familiar-100 parse gaps | exactly `0/1109` | `0/1109` | **PASS** |
| familiar-100 parsed variants | byte-identical | hash-pinned, identical (`tests/phase2/test_parser_phrasing_p15.py`) | **PASS** |
| `local_released_150` parse gaps | targeted 9 clauses close | `15/522 → 6/522` (exactly the 9 targeted) | **PASS** |
| spurious (any of the 6 sets) | must not rise | flat or **down** on every set (table below) | **PASS** |
| precision (any of the 6 sets) | must not fall for a bad reason | flat or **up** on every set except two CJK-only wobbles, both explained | **PASS** (see §3) |

## 1. What changed

`parse_constraints.py` only, four independent additive fixes plus one precision guard found while
measuring them:

- **`_LIST_TERM`** (shared by `_list_after_marker`, so it also reaches attraction/hotel/hotel-type
  list extraction, not just restaurants) now accepts a bare newline as a list terminator. Free-prose
  "Requirements:" blocks put one clause per line with no trailing punctuation, and `.` never matches
  `\n` regardless of what else is in the terminator group — without this, a clause that was not the
  *last* line of the block could not match **at all** (not mis-capture: no terminator was reachable),
  which is exactly the shape of 3 of the 4 `restaurant_name` gaps.
- **`restaurant_name`**: added "avoid the following restaurant: X" and "do not try the following
  restaurant: X" (both drop the "want/wish/hope" step `excluded_restaurants` required before), and
  "would like to try these restaurants: X" (`required_restaurants`). A singular "restaurant:" (not
  "restaurants:") is now read as exactly one name even if it contains a literal " and " inside it
  (`_split_restaurant_names`), fixing an Oxford-comma splitter bug found along the way.
- **`restaurant_type`**: added "restaurants of the cafe type" — the value-before-`type` word order,
  mirroring the already-supported `type`-before-value order (`_looks_like_cuisine_type_chunk`, now
  shared by both `parse_required_restaurants` and `parse_excluded_restaurants` so neither leaks a
  cuisine-type chunk into a restaurant name).
- **`inner_transport_set`**: the multi-mode exclusion regex only accepted "want to use"; "wish to"
  and "travel by" (as in "do not want to travel by walking within the city") are now accepted too.
- **`cost_transport`**: `in-city` added as a budget-scope synonym alongside `intra-city`/`inner-city`.

**The precision guard.** An earlier draft made the `restaurant_name` "want/wish/hope/would like to
try" pattern's restaurant-word anchor *optional* (matching the pre-existing "want/wish/hope"
pattern's own long-standing looseness). On free prose that swallowed the rest of the sentence on any
clause that never says the word "restaurant" — `required_restaurants` spurious count rose on
`hf_easy`/`hf_medium`/`hf_human` with **zero** matching recall gain (§3). Fix: the anchor is
mandatory for "try" (ambiguous between a cuisine/dish and a venue) but stays optional for "dine at"
(unambiguous — released phrasing consistently writes "dine at `<Name>`" with no "restaurant" word at
all, e.g. "would like to dine at Yan Jintang near Longfu Temple"; a first attempt at making *both*
verbs mandatory regressed a real name — `tests/phase2/test_entity_resolution.py`'s
`20250321144415070996`, "want to try one of the following restaurants: OMBRA...").

## 2. Deferred, not fixed (with reasons)

**Tier B — precedence-sensitive, 3 clauses (`attraction_name` ×2, `attraction_type` ×1).** These are
not extraction absences: the parser already fires, into the *wrong* family
("the Hangzhou Suspended Glass Art Museum" → `required_attraction_types: ["Art Museum"]` instead of
`required_attractions`; "Cultural Tourism Areas" → `excluded_attractions` instead of
`excluded_attraction_types`). Fixing the name/type disambiguation necessarily changes which pattern
wins on ambiguous text, which the [P15 write-up](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction)
explicitly distinguishes from an additive fix. It needs its own screen measuring familiar-100 for a
perturbation, which this box cannot turn into e2e evidence — see
[the two-VM rule](../../../../docs/tpc_phase2_eval.md).

**Tier C — infeasibility risk, 2 clauses (`activity_time_window`, "must not leave X before TIME").**
Emitting a pinned late-end-time window from this phrasing is the same class of move as the already-
rejected `arrive_no_later`-from-`end_before` item
([roadmap, "what not to spend time on"](../../../../docs/tpc_phase2_roadmap.md#what-not-to-spend-time-on)):
its ceiling can prune the rest of the day's transport. Max measured gain is 1–2 queries on
`local_released_150` against a real risk of making a previously-solvable query infeasible; not worth
it without a dedicated gate.

**Two probe-classifier artifacts, not parser gaps** (found while triaging the 15, left untouched
here per the instruction not to mix a probe fix into the same commit as the parser fix it would be
measured against):

- `free_attractions_only` already satisfies an oracle's `attraction_cost<=0` OR-arm
  (`parsed_verifier.py:130`), but `scripts/phase2_generalization_probe.py`'s `CLAUSE_KIND_RULES` only
  credits the `cost_attraction` kind to the `budgets` family, so 3 of the original 15 "gaps" were
  already correctly handled by the real checker.
- The same script's `cost_transport` kind marker is `inner_city_transportation_cost`; an oracle
  clause using `inter_city_transportation_cost` (intercity, not inner-city) is invisible to the
  classifier, so the `20250323222907668212` clause tagged `activity_time_window` above may already
  pass via its budget arm — unverified, since `CLAUSE_KIND_RULES` was deliberately not touched in
  this PR.

## 3. Precision, all six sets, before → after

`family_parse.totals` from `probe_before.json` / `probe.json` in this directory (`matched` /
`missing` / `spurious` / `wrong_value`):

| set | matched | missing | spurious | wrong_value | precision | recall |
| --- | --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | `661 → 661` | `0 → 0` | `0 → 0` | `30 → 30` | `0.9552 → 0.9552` | `0.9552 → 0.9552` |
| **local_released_150** (fitted — see §4) | `309 → 318` | `43 → 36` | `42 → 31` | `41 → 39` | `0.8063 → 0.8110` | `0.7852 → 0.8110` |
| hf_easy (unfitted) | `391 → 391` | `132 → 127` | `177 → 177` | `49 → 54` | `0.6961 → 0.6922` | `0.7156 → 0.7156` |
| hf_medium | `391 → 391` | `116 → 116` | `122 → 114` | `38 → 38` | `0.7743 → 0.7878` | `0.7609 → 0.7609` |
| hf_human | `195 → 195` | `97 → 97` | `49 → 44` | `28 → 28` | `0.8001 → 0.8153` | `0.6725 → 0.6725` |
| hf_preference_base50 | `62 → 62` | `20 → 19` | `32 → 32` | `7 → 8` | `0.6617 → 0.6517` | `0.7333 → 0.7333` |

Spurious is flat or down everywhere — the metric this PR is gated on ([CLAUDE.md's precision
trap](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction): a spurious
family can make a query infeasible, costing the whole query, so it is the one number that must never
rise). Two sets show a small **precision** dip (`hf_easy` `-0.0039`, `hf_preference_base50` `-0.01`)
with **flat recall and flat spurious** — verified (`find_flip2.py`, ad hoc) that in every one of
those `missing → wrong_value` flips, the oracle's `required_restaurants` literal is CJK
(e.g. `宴锦堂(隆福寺店)`) while our extraction is the correct English name from the query text itself
(e.g. `"Yan Jintang near Longfu Temple"`). Under `en`-scoring the clause was already failing before
(missing) and is still failing after (present but can never string-match a Chinese literal) — the
same real outcome, reclassified from `missing` to `wrong_value` by the bookkeeping, not a new
failure mode. `local_released_150` — the one set whose restaurant-name literals are genuinely
English — moved in the right direction on **every** column.

One known, accepted residual: the "dine at" pattern's captured value can include a trailing
locative phrase ("the Beautiful Kitchen restaurant **near Palm Springs**" instead of just the venue
name) since it has no anchor word to stop at. Harmless on the CJK-literal sets above (can never
match either way) and not observed on any English-literal set in this run, but flagged here rather
than left as an undocumented latent defect for whoever next touches `restaurant_name`.

## 4. What's fitted vs. what generalized

`local_released_150`'s `15 → 6` is **fitted**: these are the exact 9 queries read and pattern-matched
against. It is evidence the fix works, not evidence it generalizes — the project's whole crisis was
mistaking a fitted number for a generalizing one
([roadmap, "the one-paragraph version"](../../../../docs/tpc_phase2_roadmap.md#the-one-paragraph-version)).
The one number here that *is* unfitted evidence is `hf_easy`'s clause parse-gap count, `132 → 127`:
no `hf_easy` query was read while writing these patterns (`hf_medium`/`hf_human` were, for the CJK
check in §3, but not for pattern-writing), and it improved anyway — the "would like"/"dine at"
verb-vocabulary broadening picked up real restaurant names there by construction, not by fitting.

## Files

- `probe_before.json` / `probe.json` — full `phase2_generalization_probe.py` output, before/after
  this PR's `parse_constraints.py` changes, all 6 sets.
- `summary.md`, `fix_headroom.json`, `residual_gaps_after_fix.json` — the after-state's own rendered
  tables (headroom table's `cost_*`/`room_type` hypothetical is unrelated to this PR — it's the
  probe script's fixed default from the 2026-08-06 fix — and stays flat since none of that family
  set changed here).
- Regenerate with `HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir <dir>`.
