# P19 — the unidentified half of the held-out gap

**Date** 2026-08-07 · **Branch** `implementation/p16-p19-value-grounding-and-gap-analysis`
**Contract** Diagnostic screen. Nothing here promotes a change and nothing here is a `full_runs/`
row. Static analysis only — no solve, no LLM call, no WorldEnv. Read-only over released data; the
only held-out fact used is the single published `C-LPR 55.20`
([artifact](../../heldout/20260807_v1_leaderboard.json)).

Instrument: `scripts/phase2_density_family_gap_analysis.py`. Raw output:
[`p19_report.json`](p19_report.json), [`p19_summary.md`](p19_summary.md).

## The question

Held-out `C-LPR` is `55.20` — **below our worst local free-prose measurement** (`72.5` raw /
`78.4` English-literal, realized end-to-end, *before* the P15 phrasing fix landed). The phrasing
diagnosis explains a large part of the held-out gap but not all of it
([roadmap §1](../../../../docs/tpc_phase2_roadmap.md#1-coverage-not-search-what-the-held-out-gap-is-made-of)).
This screen prices three candidate causes of the residual, from released data only, per the
roadmap's pre-registered plan and kill criterion.

**Kill criterion (fixed in advance): if the dense tail of a free-prose set reproduces `C-LPR ≈ 55`,
stop and do not pursue causes 2/3.** It does not reproduce it (below) — the dense tail comes closer
than the overall average, but a real gap is left, so causes 2 and 3 are both reported.

**Method note on "C-LPR" here.** No solve is needed for this screen, so "C-LPR" throughout is the
existing no-solve **coverage ceiling** (`clpr_ceiling_parse_gap_only`, the same quantity
`scripts/phase2_generalization_probe.py` already reports): the share of oracle clauses whose family
we extract at all, assuming every extracted clause then passes. It is an upper bound, not a solved
plan's realized rate — but it has tracked realized e2e C-LPR closely on this project's own past
measurements (the 2026-08-06 phrasing-fix screen: ceiling `71.28 → 89.95` on `hf_medium` against a
realized e2e `72.5 → 86.25` on the same set), so it is a reasonable low-cost proxy, not a novel one.

## 1. Density (candidate 1)

| set | n | clauses mean | p50 | p75 | p90 | max | % dense (≥10) | overall ceiling | dense-tail ceiling | sparse-rest ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 11.09 | 11 | 12 | 13 | 13 | 88.0% | 100.00 | 100.00 (n=88) | 100.00 |
| local_released_150 | 150 | 3.48 | 5 | 6 | 6 | 6 | 0.0% | 98.85 | — (n=0) | 98.85 |
| hf_easy | 300 | 5.26 | 5 | 5 | 6 | 7 | 0.0% | 91.96 | — (n=0) | 91.96 |
| **hf_medium** | 150 | 8.43 | 8 | 9 | 10 | 12 | **18.0%** | 90.03 | **74.91 (n=27)** | 94.39 |
| hf_human | 154 | 4.46 | 4 | 5 | 6 | 9 | 0.0% | 85.59 | — (n=0) | 85.59 |
| hf_preference_base50 | 50 | 5.2 | 5 | 5 | 6 | 7 | 0.0% | 92.69 | — (n=0) | 92.69 |

**Density is real but does not by itself reach `55.20`.** `hf_medium` is the *only* free-prose set
with any queries at or above the `≥10`-clause threshold `FPR = 0` independently implies (roadmap
[reading 2](../../../../docs/tpc_phase2_roadmap.md#where-we-are)), and its 27-query dense tail's
ceiling (`74.91`) drops **15 points below its own overall average** (`90.03`) and **20 points below
the sparse rest of the same set** (`94.39`) — clean, monotonic evidence that density hurts coverage
in exactly the direction predicted. But `74.91` is still `~20` points above the held-out `55.20`, so
density alone does not close the gap, and every *other* local free-prose set has **zero** queries
this dense at all — meaning the local data cannot fully exercise this hypothesis, only support it
directionally. Read the `n=27` dense-tail figure with that sample size in mind.

**Reading**: density is a contributor, not the answer. The kill criterion is not met — continue to
causes 2 and 3.

## 2. Families we cannot express at all (candidate 2)

**None.** Every family present in any released set's oracle solver-dict is produced (`matched` or
`wrong_value`) on at least one of the six sets. There is no family invisible to every screen the
way `budgets`/`room_type` were before the P15 phrasing fix — that specific failure mode is closed
for now. This rules out "a whole constraint kind we cannot express" as an explanation of the
residual; the remaining candidates are about *how well*, not *whether*, we express a family.

## 3. Families we express but get wrong at scale (candidate 3)

Ranked by `oracle_instances × miss_rate` across all six sets combined (top 10 of 20 shown; full
list in [`p19_report.json`](p19_report.json)):

| family | oracle instances | missing | miss_rate | score |
| --- | --- | --- | --- | --- |
| **`required_attraction_types`** | 160 | 102 | **63.75%** | **102.0** |
| **`cuisine_preference`** | 127 | 100 | **78.74%** | **100.0** |
| `required_attractions` | 133 | 46 | 34.59% | 46.0 |
| `required_hotel_all_types` | 82 | 38 | 46.34% | 38.0 |
| `required_restaurants` | 63 | 32 | 50.79% | 32.0 |
| `budgets` | 421 | 21 | 4.99% | 21.0 |
| `required_hotels` | 63 | 19 | 30.16% | 19.0 |
| `room_type` | 184 | 15 | 8.15% | 15.0 |
| `position_presence` | 105 | 4 | 3.81% | 4.0 |
| `required_hotel_any_types` | 5 | 4 | 80.00% | 4.0 |

**The top two are exactly [P16](../../../../docs/tpc_phase2_roadmap.md#p16--ground-llm-extracted-values-into-the-closed-vocabulary)'s
targets, independently confirmed.** `required_attraction_types` and `cuisine_preference` are the
two highest-scoring families by a wide margin over the rest of the ranking (the #3 entry,
`required_attractions`, scores under half as much), and both are exactly the closed-vocabulary
category fields P16's grounding fix (this same branch,
[`20260807_p16_entity_resolution_probe/`](../20260807_p16_entity_resolution_probe/README.md))
targets. This is `missing` (never extracted, not merely wrong-valued), which is upstream of and
additive to the `wrong_value` problem P16 addresses — the two screens describe two different stages
of the same two families' failure. It is corroborating rather than contradicting evidence: whatever
raises `matched` on these two families (P16's grounding, or a deterministic-parser recall
improvement in this space) is aimed at the largest measured piece of candidate 3.

## Deliverable and next step

Ranked causes, by estimated C-LPR cost:

1. **Density** (candidate 1) — real, measured, directionally consistent, but a `~15-20`-point
   effect on the one set that has any dense queries, not `~30+`. Action: none new — this is already
   why [P4](../../../../docs/tpc_phase2_roadmap.md#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass)/[P5](../../../../docs/tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds)
   are ranked where they are; no dense-query-specific tuning is proposed here since the local data
   cannot calibrate one (`n=27` from a single set).
2. **Family recall on `required_attraction_types` / `cuisine_preference`** (candidate 3) — the
   largest concrete, actionable residual found. Both are worked by P16 this same branch; a
   deterministic-parser recall pass on these two families (in the `parse_constraints.py` style of
   [P15](../../../../docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction)) is the
   next candidate if P16's LLM-side fix does not fully close them, since `missing` (never
   attempted) is a different failure than `wrong_value` (attempted, ungrounded) and needs the
   deterministic extractor's own attention, not just a downstream grounding layer.
3. **No family is completely unexpressed** (candidate 2) — closed, do not pursue further without
   new evidence.

**Residual not addressed here**: this screen's coverage-ceiling proxy cannot separate "genuinely
denser held-out queries" from "a partial infrastructure difference on the organizers' host" (the
roadmap's other named candidate for the unexplained residual) — that would need a held-out-side
signal this project does not have access to beyond the seven published metrics.

## Reproducing this

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_density_family_gap_analysis.py \
    --out-dir results/phase2_baselines/screens/20260807_p19_unidentified_gap
```

Runtime: a few minutes, all six sets, no network beyond the local HF dataset cache.
