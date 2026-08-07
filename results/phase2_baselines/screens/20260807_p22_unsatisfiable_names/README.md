# P22 — drop provably unsatisfiable required-name constraints

**Date** 2026-08-07 · **Branch** `claude/p22-implementation-6kcpfs` · **git_sha** `aed4363` (pre-change
base; this screen was run against the branch's working tree with P22's code applied)
**Contract** Static parser screen (definitional check + R22's standing phrasing tripwire). No solve,
no LLM call, no WorldEnv, no held-out artifact used. Read-only over released and HF-local data
(the HF sets are skipped here — no local HF cache in this environment — the two local sets are the
ones the roadmap's bar requires to reach `0`).

## What this is

[§6](../../../../docs/tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves)
found that `_resolve_one_required_name`'s terminal branch keeps an unresolvable required-POI-name
value verbatim as a hard constraint — a query carrying one is pinned at `FPR = 0` at any budget,
because no plan can ever satisfy a constraint with no feasible point. P22 adds a `TPC_P2_DROP_UNSATISFIABLE_NAMES`
flag (library default off) that drops the value instead, for both halves R26 identified:
required-POI names (`required_attractions` / `required_restaurants` / `required_hotels` /
`position_presence`) and category values (`required_attraction_types` / `cuisine_preference` /
`required_hotel_all_types` / `required_hotel_any_types`), the latter checked against each target
city's **own** vocabulary (a canonical value can still be absent from one city's catalog — e.g.
`"Cultural Landscape"` in Suzhou/Hangzhou).

The flag is reachable standalone: `ir_to_solver_variants` now runs the entity-resolution catalog
lookup whenever `entity_resolution` **or** `drop_unsatisfiable_names` is on, so this does not
require P21's promotion to be reachable (composes with it when it lands, per the roadmap's
preferred design).

## Commands run

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py \
  --sets "familiar_100 (control),local_released_150" \
  --out-dir results/phase2_baselines/screens/20260807_p22_unsatisfiable_names
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --entity-resolution \
  --sets "familiar_100 (control),local_released_150" \
  --out-dir results/phase2_baselines/screens/20260807_p22_unsatisfiable_names
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --drop-unsatisfiable-names \
  --sets "familiar_100 (control),local_released_150" \
  --out-dir results/phase2_baselines/screens/20260807_p22_unsatisfiable_names
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --types \
  --sets "familiar_100 (control),local_released_150" \
  --out-dir results/phase2_baselines/screens/20260807_p22_unsatisfiable_names
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --types --drop-unsatisfiable-names \
  --sets "familiar_100 (control),local_released_150" \
  --out-dir results/phase2_baselines/screens/20260807_p22_unsatisfiable_names
```

`--drop-unsatisfiable-names` was added to the probe/`query_variants` in this change; the other
arms (baseline, `--entity-resolution`, `--types`) already existed and are re-run here only to
confirm the baseline numbers the roadmap cites still hold on this tree.

## Results

| arm | familiar_100 (control) | local_released_150 |
| --- | --- | --- |
| baseline (both flags off) — required names | `7 %` (7/100) | `16 %` (24/150) |
| `--entity-resolution` — required names | `0 %` | `14 %` (21/150) |
| **`--drop-unsatisfiable-names` — required names** | **`0 %`** | **`0 %`** |
| baseline — category values (`--types`) | `0 %` | `3 %` (5/150) |
| **`--drop-unsatisfiable-names --types`** | **`0 %`** | **`0 %`** |

The baseline and `--entity-resolution` rows reproduce the roadmap's
[§6 table](../../../../docs/tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves)
exactly (unchanged on this tree). The drop-flag rows are the bar requirement: **the per-set count
falls to `0` on every set in both arms.**

## A residual the first implementation missed, and the fix

The first pass at `--drop-unsatisfiable-names` left `local_released_150` at `1/150`
(`position_presence: 1`), not `0`. Cause: `resolve_entities` has two separate resolution code
paths — `_resolve_one_required_name` (required_attractions/restaurants/hotels, and the values
rerouted *into* `position_presence` from a category-misroute) and `_resolve_generic_location`
(anything the parser put into `position_presence` **directly**, plus `hotel_nearby`/
`poi_distance_hotel`/`stay_duration`/`activity_time_windows`). Only the first had a drop branch.
`_resolve_generic_location` gained its own `drop_unresolved` parameter (returns `None`, which the
`position_presence` list-handling caller treats as "omit this entry"); the four dict-valued callers
never pass it, since dropping a nested location there would mean removing a whole constraint
object, not just a value — out of P22's scope (the roadmap's `NAME_FIELDS` is exactly
`required_attractions` / `required_restaurants` / `required_hotels` / `position_presence`). After
the fix, both local sets are `0/0` in every arm above. Regression test:
`tests/phase2/test_entity_resolution.py::test_directly_parsed_position_presence_dropped_when_unresolvable`.

## What this does not establish

This is a static, no-solve, no-LLM parse-time measurement — it is the **definitional** check (the
probe uses the same matchers the drop rule and the acceptance gate itself use), not an end-to-end
result. Promotion needs
[R30](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries), a
paired e2e A/B on both registers, which is Evaluation-workstream work on the eval machine. The
roadmap's own expectation: the local free-prose e2e gain is capped, since `59–61 %` of HF queries
also carry a structurally unpassable CJK oracle clause (P23) independent of this fix.

## Test coverage

`tests/phase2/test_entity_resolution.py` — new "P22" sections: default-off byte-identical, the
resolvable-name-never-dropped bar requirement, required-name drop (single/partial-list), type-vocab
reroute and category-misroute reroute still firing with the flag on, the standalone-reachability
test (`drop_unsatisfiable_names=True` with `entity_resolution` left at its default `False`), the
four category-valued families (scalar and list shapes, city-scoped `"Cultural Landscape"`
Beijing-vs-Suzhou case), and the `position_presence` residual above. `Flags.from_env({})` byte-
identical floor test included. Full `pytest tests` green (`aed4363` base + this change).
