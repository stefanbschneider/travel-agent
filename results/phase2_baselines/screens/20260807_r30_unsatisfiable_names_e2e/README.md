# R30 — does dropping unsatisfiable names flip queries?

**Date** 2026-08-07 · **Branch** `eval/r30-drop-unsatisfiable-names-e2e` · **`git_sha`** `51878929`
(current `main` tip; includes P22 `TPC_P2_DROP_UNSATISFIABLE_NAMES` and P24's constraint-invention
fixes) · **host** 4-core Linux (3-way sharded per split) · **Contract**: paired e2e A/B, per-query
mode (`agent_env/scripts/solve_phase2.py`, no `--total-budget-sec`), `budget-sec=90`, `--lang en`, no
`--resume`, distinct method directories per arm. Not a `full_runs/`/`runs/` row.
Evaluation workstream instrument:
[R30](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries),
gating [P22](../../../../docs/tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints).

## Headline: 0/103 flips to passing, 2/103 flips to failing, and both mechanisms are now understood

Measured against the doc's own bar, clause by clause: **GREEN's first condition (at least one target
uid flips to fully passing) is not met — 0/103.** The **literal RED condition (zero flips *and* no
C-LPR movement) is also not met** — C-LPR moved on three of six sets, up on two, down on one. So this
is neither the doc's GREEN nor its literal RED; the honest reading is **a negative result**: no query
gained, one register lost two, and the flag correctly stays library-default-off (no default changes as
a result of this row).

## Baseline drift, found before running anything

The last committed static screen
([`20260807_p22_unsatisfiable_names`](../20260807_p22_unsatisfiable_names/README.md)) recorded
`local_released_150` at `24/150` unsatisfiable-name queries. Re-running the same probe on current
`main` (`51878929`) gives `20/150` — **P24** ("stop inventing satisfiable but unrequested
constraints", merged after that screen) independently reduces some of the same over-captured
`required_attractions`/`required_hotels` values the probe counts, since both P22 and P24 fix
different halves of the same root-cause capture bug. This is expected, not a regression in either
change; **the fresh numbers below are what this row gates against**, not the stale `24/150`. Full
probe outputs (all 6 sets, both `--types` arms, baseline and `--drop-unsatisfiable-names`):
`report*.json` / `summary*.md` in this directory.

## Target set

Per the doc ("run it on the queries it targets, not a random subset"): the union of each set's
unsatisfiable-required-name and unsatisfiable-category-value uids from the fresh probe run
(`target_uids.json`; per-split uid lists in `uids/`). **103 queries total**, all six released/HF sets:

| set | split | target uids |
| --- | --- | --- |
| familiar_100 (control) | `tpc_phase2_familiar_100` | 7 |
| local_released_150 | `tpc_phase2_test` | 24 |
| hf_easy | HF `easy` | 40 |
| hf_medium | HF `medium` | 12 |
| hf_human | HF `human` | 14 |
| hf_preference_base50 | HF `preference_base50` | 6 |

## Method

Each split's target uids materialized as a **uid-only local split** (`chinatravel/data/en/hf_*_r30/`
for the four HF sets — full split materialized via `scripts/materialize_hf_split.py`, then its
`default_splits/*.txt` overwritten to just the target uids so `eval_tpc.py` scores exactly the target
subset, not the padding entries; the two local sets used a **new** split name
(`tpc_phase2_familiar_100_r30targets` / `tpc_phase2_test_r30targets`) pointing at the existing
`tpc_phase2_familiar_100`/`tpc_phase2_test` data directories via `load_datasets.py`'s directory-search
fallback, so the canonical 100/150-query split files were never touched). Each split's target uids
3-way sharded (`shards/`), shards run as parallel `solve_phase2.py --uids-file <shard>` subprocesses,
one `--method` per split per arm, **arms run strictly sequentially** (OFF arm first, then ON), same
discipline as R29/R25/R24:

```bash
TPC_P2_DROP_UNSATISFIABLE_NAMES=0 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split <split> --uids-file <shard> --method phase2_e2e_r30_<set>_off \
  --budget-sec 90 --lang en
TPC_P2_DROP_UNSATISFIABLE_NAMES=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split <split> --uids-file <shard> --method phase2_e2e_r30_<set>_on \
  --budget-sec 90 --lang en
```

`TPC_P2_ENTITY_RESOLUTION` was left unset on both arms (its harness force-default of `True`, per
[R29](../../../../docs/tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end),
applies identically to both — `TPC_P2_DROP_UNSATISFIABLE_NAMES` is the only isolated variable), so
this row also re-confirms it reads the same value both arms would see in a real harness run. Scored
with `eval_tpc.py --splits <split> --method <method> --lang en` (logs in `eval/`). All materialized
HF split data/dirs and the four temporary `default_splits/*.txt` files were **deleted after scoring**
— confirmed absent from `git status`. `agent_env/runs/`, `results/phase2_e2e_r30_*/`, `eval_res/`,
`your_tpc_scores.json` and `*_suboptimal.txt` are already `.gitignore`d and were not committed; two
uids' plan/telemetry pairs are kept under `evidence/` as the causal record for the two regressions
(below). Telemetry confirms zero LLM calls and zero timeouts in all 12 method arms
(`llm_parse_attempts_sum: 0`, `timeouts: 0`), and `flags.drop_unsatisfiable_names` toggled correctly
per arm. `results/best/` and `results/constraints_solved/` untouched (`--update_best` never passed; no
`constraints_solved: N saved` line in any `eval/*.log`).

## Result, by register

### familiar-100 control (n=7): byte-identical — the flag changed nothing

Every one of the 7 target uids' plan files are byte-identical between arms (modulo
`elapsed_time(sec)`) — not just the aggregate (`overall 64.809309...` to 12 significant figures, both
arms). This is stronger than "overall did not fall": the drop rule provably never fires a change on
this register at the plan level. Consistent with the static screen's own history (familiar-100 has
always been the cleanest register for this fix).

### local_released_150 (n=24): the only register where a flip was measurable — 0 gained, 2 lost

| metric | off | on | Δ |
| --- | --- | --- | --- |
| FPR (pass %) | 91.67 (22/24) | 83.33 (20/24) | **−8.33 (−2 uids)** |
| C-LPR | 97.75 | 95.51 | **−2.25** |
| overall | 91.60 | 86.85 | **−4.75** |
| MicEPR / MacEPR | 100.0 / 100.0 | 100.0 / 100.0 | flat (no fact fails to ground) |

**Flips: 0 fail→pass, 2 pass→fail** (`20250322180344489669`, `20250324075652034944`). Both
re-solved a second time under the same OFF configuration and are **byte-identical to the first OFF
run** (`evidence/*.rerun.plan.json`) — deterministic, not solver search noise.

**Two different causal mechanisms, not one:**

- **`20250324075652034944` (Hangzhou, 4 days) — a clean, direct loss.** The parser's
  `required_attractions` capture for this query is
  `"Xixi Paradise Commercial Street, wish to stay in single-bed rooms"` — the classic tail-swallow bug
  (real POI name + an unrelated trailing clause captured as one string), which the probe correctly
  flags as no catalog match. **The OFF plan includes "Xixi Paradise Commercial Street"; the ON plan
  does not** (`evidence/20250324075652034944.{off,on}.plan.json` — diff the `position` fields
  directly). The oracle's real hard-logic clause requires this attraction; OFF apparently satisfies it
  because the solver-side constraint matcher used when *applying* the (kept-verbatim, per
  entity_resolution's terminal branch) constraint is more lenient than the probe's own
  `_exact_catalog_match`/`_match_catalog_name` — lenient enough to place the real POI despite the
  garbage tail. P22's drop rule removes the entire value, including the real POI name embedded as its
  prefix, so ON never targets it and the plan (a different, otherwise-reasonable Hangzhou itinerary)
  never includes it. **This is exactly the risk the doc's own acceptance bar named** ("an over-eager
  drop must not turn into an unconstrained plan that loses [ground truth]") — realized, not
  hypothetical.
- **`20250322180344489669` (Beijing, 2 days) — search perturbation, not requirement loss.** The oracle
  clause is `restaurant_cost <= 1700 OR "Sauna" in accommodation_type_set` (an OR the query's own text
  states as "meet any one of..."). Checked directly: the **OFF plan satisfies the budget branch**
  (`restaurant_cost = 1685 <= 1700`; its hotel, "Atour Hotel Youanmenqiao Beijing South Railway
  Station", is not Sauna-type), so the dropped garbage value ("a hotel of the following type: Sauna",
  captured as a `required_hotels` name) **had no causal path to the OFF pass** — it was never
  satisfiable in either arm. The ON plan's actual restaurant cost is `7355`, and its hotel is not
  Sauna-type either, so it fails both branches. Removing the constraint changed what the deterministic
  solver's `90 s` search explored (see the solve-time mechanism below) and *this instance* happened to
  land on a worse-luck itinerary on a dimension unrelated to the dropped value's content. Confirmed
  deterministic on rerun, but **not attributable to "the drop removed a real requirement"** — a
  different failure mode from the other uid, and one that could as easily land on a better-luck plan
  on a different query.

### HF free prose (n=72 across 4 sets): inconclusive on FPR by construction, real gain at clause level

FPR stayed flat everywhere (`0.0/0.0` on `hf_easy`/`hf_medium`/`hf_preference_base50`, `7.14/7.14` on
`hf_human` — same single uid passing both arms, confirmed by uid set, not just count). This is
**predetermined, not a result**: every target uid here already carries an unsatisfiable name by
construction, and R30's own text flagged this ceiling in advance — `59–61 %` of HF queries under
`--lang en` also carry a structurally unpassable CJK oracle clause
([the corrected dataset boundary](../../../../docs/tpc_phase2_eval.md#3-hugging-face-chinatravel)), so
a query-level flip needs every other clause to already pass too, which a targeted (by definition,
currently-failing) subset is unlikely to do. [R31](../../../../docs/tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate)
is what removes this ceiling.

The real, genuine result on this register is at the **clause** level, where the ceiling doesn't apply:

| set | C-LPR off → on | conditional clauses passing (off → on) |
| --- | --- | --- |
| hf_easy | 80.37 → 81.31 | 172 → **174** / 214 |
| hf_medium | 72.57 → 74.34 | 82 → **84** / 113 |
| hf_human | 67.07 → 67.07 | 55 → 55 / 82 (flat) |
| hf_preference_base50 | 80.0 → 80.0 | 24 → 24 / 30 (flat) |

`hf_easy` and `hf_medium` each gain 2 satisfied clauses with the flag on and lose none — real,
positive, reproducible movement, just not enough density on any one target query to flip a whole-query
pass on a subset that was hand-picked for having at least one guaranteed-failing clause.

**Read together with `local_released_150`, one line explains both:** `local_released_150`'s targets
were *near*-passing (`22/24` already passed before the drop), so a loss shows up at the query level;
HF's targets are *far* from passing (structurally at most one clause away from a ceiling that is
itself capped below 100), so a gain shows up only at the clause level. Same mechanism
(dropping a value the solver could never satisfy anyway, changing what the remaining search budget
gets spent on), two different clause densities producing two different visible shapes.

## The mechanism P22 actually targets: solve time, not correctness — measured directly

The roadmap's own framing for why an unsatisfiable name is harmful: it "stays in the scheduler's
repair queue burning envelope on an objective that cannot be met." This row measures that directly
from `stage_sec.solve` telemetry (`solve_time_table.json`):

| set | off mean solve (s) | on mean solve (s) | speedup |
| --- | --- | --- | --- |
| familiar_100 | 57.28 | 57.28 | 1.0× (no unsatisfiable-name pressure here) |
| local_released_150 | 61.00 | 26.92 | 2.3× |
| hf_easy | 57.83 | 9.43 | **6.1×** |
| hf_medium | 59.06 | 9.95 | **5.9×** |
| hf_human | 63.65 | 17.74 | 3.6× |
| hf_preference_base50 | 53.20 | 9.11 | **5.8×** |

With the flag on, the free-prose registers converge in ~9–18 s instead of exhausting the `90 s` cap —
a real, large, and structural effect. **This fixed-`90 s`-per-query screen contract is blind to the
benefit this produces**: a fixed per-query budget simply discards the freed time, it does not
reallocate it. The real harness path (`chinatravel/agent/phase2/sweeps.py`'s triage → repair → polish
envelope) *does* reallocate freed time to other queries in the same 5 h budget — this row cannot
measure that reallocation (it would need a `full_runs/`-shaped envelope run, not a per-query screen),
so **the cost side of P22 is measured here and it is real; the benefit side (more envelope for other
queries) is plausible from this evidence but unmeasured by this row's contract.**

## What this authorizes

**Nothing promotes.** `TPC_P2_DROP_UNSATISFIABLE_NAMES` stays library-default-off, which it already
was — this row does not change any default. Per the invariants, a measurement gates a change; this one
gates it closed for now.

**A concrete follow-up for the implementation workstream** (not done here — this is an eval-workstream
row, and does not edit `chinatravel/agent/`): `20250324075652034944`'s failure mode is a specific,
fixable gap, not a fundamental flaw in dropping unsatisfiable names — before falling back to a full
drop, try to salvage a real catalog POI name that is a *prefix* (or otherwise cleanly separable
substring) of an otherwise-unmatched capture, using the same catalog matcher the solver's own
constraint-application step already relies on more leniently than
`_exact_catalog_match`/`_match_catalog_name`. That would keep P22's demonstrated solve-time win while
closing exactly the loss this row found. `20250322180344489669`'s mechanism (search perturbation from
freeing repair-queue attention) is not a parser bug and has no obvious fix at the parser level; it is
a property of the deterministic solver's budget allocation and would need to be re-measured at the
envelope level (`full_runs/`), not chased at the per-query level.

## Reproduce

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --out-dir <dir>
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --types --out-dir <dir>
# build target uid files per set from report.json/report_types.json "uids", then:
TPC_P2_DROP_UNSATISFIABLE_NAMES=0|1 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split <split> --uids-file <target_uids.txt> --method <method> --budget-sec 90 --lang en
.venv/bin/python eval_tpc.py --splits <split> --method <method> --lang en
```
