# Generalization probe — why is the held-out score half the local one?

**Date** 2026-08-06 · **Branch** `report-v2` · **Source revision** `966a9f956de5137487d6d541f3110ddcb273660b` (clean tree)
**Contract** Diagnostic screen. Nothing here promotes a change and nothing here is a `full_runs/` row.
All work is offline on **released** data; the only held-out fact used is the single aggregate
`33.2473` the organizers returned for `v1`.

## The question

| measurement | overall | C-LPR | FPR |
| --- | --- | --- | --- |
| organizer held-out, `v1` | **33.2473** | unknown | unknown |
| `tpc_phase2_familiar_100`, [`20260806T115309Z`](../../full_runs/20260806T115309Z.json) (R17) | 64.1725 | 90.08 | 44.0 |
| `tpc_phase2_test` 150, [`20260806T132917Z`](../../full_runs/20260806T132917Z.json) (R18) | 90.5603 | 96.93 | 90.67 |

## Answer

**Yes — constraint extraction is the largest identified cause, and it is now measured rather than
suspected.** Two specific, named phrasing bugs (total budget, room type) account for most of it. But
the measured phrasing effect explains roughly **half to three quarters** of the 31-point gap, not all
of it, so at least one further factor remains unidentified.

The load-bearing numbers:

- Our parser has **zero** clause-level extraction gaps on familiar-100 and **12–29 %** on every
  differently-phrased released set. familiar-100 is the *only* set with a clean sheet.
- End-to-end at matched budget/workers/`n`, free-prose phrasing of comparable constraint density
  drops overall from **64.57 → 41.62** (`-22.95`), with commonsense (`MicEPR`/`MacEPR`) staying at
  `100.0`. The collapse is entirely in the logical terms, which is the shape the held-out inversion
  predicted.
- The agent **does not know it is failing**: on that same run its own self-score reported
  `FPR 86.67` while the official evaluator said `6.67`. An unextracted clause is invisible to the
  acceptance gate, so the query is never queued for repair — the run ended with `1545.6 s` of its
  `1800 s` unspent.

## 1. Inventory: what differently-phrased released data exists locally

Upstream's `easy` / `medium` / `human` splits are **not resolvable locally** — the `.txt` UID lists
ship but the query JSONs do not (`load_query` raises `Unable to resolve local split 'human':
missing=[...154 uids]`). The same query sets *are* available through the Hugging Face
`LAMDA-NeSy/ChinaTravel` cache (`default` config: `easy` 300, `medium` 150, `human` 154,
`preference_base50` 50), all carrying `hard_logic_py` and `nature_language_en`. That is the route
used here, offline (`HF_HUB_OFFLINE=1`).

Phrasing register is the discriminator, and it is stark:

| set | n | NL chars | oracle clauses/query | has numbered "Requirements:" list |
| --- | --- | --- | --- | --- |
| `tpc_phase2_familiar_100` (control) | 100 | 883.9 | 11.09 | **100.0 %** |
| `tpc_phase2_test` (local released 150) | 150 | 211.0 | 3.48 | 15.3 % |
| HF `easy` | 300 | 153.2 | 5.26 | 0.0 % |
| HF `medium` | 150 | 205.1 | 8.43 | 0.0 % |
| HF `human` | 154 | 282.7 | 4.46 | 0.0 % |
| HF `preference_base50` | 50 | 162.3 | 5.20 | 0.0 % |

Real examples, one per register:

- **familiar-100** — an enumerated near-DSL restatement of the constraint list:
  > We are 2 people traveling from Nanjing to Guangzhou for 2 days. Requirements: 1. The trip must
  > last 2 days. 2. The plan must be for 2 travelers. 3. Tickets for attractions, intercity
  > transport, and metro rides must match 2 travelers. 4. Do not include any of these attraction
  > types: Red tourism sites. 5. Keep the accommodation cost within 342. …
- **HF `medium`** — the same *kinds* of constraint in ordinary prose:
  > Current location: Shanghai. My friend and I are planning to visit Beijing for three days with a
  > budget of 6000 RMB. We will primarily use the subway for transportation within the city and plan
  > to book a single-bed room. Could you provide me with a travel itinerary?
- **HF `human`** — human-written, bracketed metadata header, intent stated obliquely:
  > [Current location: Shanghai, Destination: Suzhou, Number of travelers: 2, Number of travel days:
  > 3] I want to take my eldest son from Shanghai to Suzhou for a three-day trip. We want a light and
  > free travel experience, not a rigorous one. Please help me plan it.

Note also that `tpc_phase2_test` — the split scoring `90.56` — shares familiar-100's template *and*
carries a third of its constraints (3.48 vs 11.09 clauses/query). It is both easier and phrased the
way our parser expects, so its `90.56` was never evidence of generalization.

> One correction to the record: `docs/tpc_phase2_eval.md` states these sets average "`~16`
> `hard_logic_py` constraints per record versus `~38` in familiar-100". Measured through
> `load_query(..., oracle_translation=True)` the figures are **3.48** and **11.09**. Whatever the
> `~16`/`~38` counted, it is not `len(hard_logic_py)`, which is what the evaluator scores
> (`evaluate_hard_constraints_v2` emits one boolean per entry). Doc-owning agent's call; flagged, not
> edited.

## 2. Parser vs oracle, per set

Instrument: `scripts/phase2_generalization_probe.py` (new), which reuses
`scripts/parser_vs_oracle.py` unchanged for the family-level diff (`--disjunction --branch-aware`
equivalent) and adds a clause-level coverage layer. Raw output: [`probe.json`](probe.json),
[`summary.md`](summary.md).

| set | n | parse P | parse R | parse **F1** | parse-gap clauses | C-LPR ceiling | queries w/ parse gap | FPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0.955 | 0.955 | **0.955** | **0/1109 (0.0 %)** | 100.00 | **0.0 %** | 100.00 |
| local_released_150 | 150 | 0.805 | 0.777 | 0.791 | 17/522 (3.3 %) | 96.74 | 11.3 % | 88.67 |
| hf_easy | 300 | 0.671 | 0.586 | 0.625 | 219/1579 (13.9 %) | 86.13 | 66.7 % | 33.33 |
| hf_medium | 150 | 0.652 | **0.307** | **0.417** | **363/1264 (28.7 %)** | **71.28** | **100.0 %** | **0.00** |
| hf_human | 154 | 0.784 | 0.565 | 0.656 | 146/687 (21.2 %) | 78.75 | 64.9 % | 35.06 |
| hf_preference_base50 | 50 | 0.645 | 0.617 | 0.631 | 32/260 (12.3 %) | 87.69 | 62.0 % | 38.00 |

Definitions, because the two "gap" ideas are easy to conflate:

- A **parse gap** is an oracle clause whose covering solver-dict family is present in the *oracle*
  parse and absent from our *no-oracle* parse. Only these are phrasing evidence.
- A **schema gap** is an oracle clause no solver-dict family can express at all (e.g. an *excluded*
  accommodation type). The oracle side drops it too, so it is a vocabulary limit identical on every
  set and carries no phrasing signal. familiar-100 has 67 of these — which is why its clause
  coverage reads `0.9396` while its parse-gap count is exactly zero.
- **C-LPR ceiling** = the per-clause pass rate we could reach if every parse-gap clause failed and
  every other clause passed. **FPR ceiling** = share of queries with no parse gap at all, since FPR
  is all-or-nothing per query.

### The families that are missing, per set

`budgets` and `room_type` dominate, and both are *value-clean* (a number, and the English words
`single`/`twin`) — no cross-language excuse applies to either:

| family | oracle has it | our parse misses it |
| --- | --- | --- |
| `budgets` — HF `easy` | 60 | **60 (100.0 %)** |
| `budgets` — HF `medium` | 148 | **145 (98.0 %)** |
| `budgets` — HF `human` | 48 | **44 (91.7 %)** |
| `room_type` — HF `easy` | 30 | 28 (93.3 %) |
| `room_type` — HF `medium` | 120 | **116 (96.7 %)** |
| `cuisine_preference` — `easy`/`medium`/`human` | 30 / 33 / 27 | 30 / 33 / 27 (**100 %** each) |
| `required_attraction_types` — `easy`/`medium`/`human` | 30 / 31 / 60 | 21 / 28 / 50 (70–90 %) |

**Root cause of the budget miss, read off the code.** `parse_constraints.parse_budget` recognises a
total budget through exactly two routes: the familiar-100 template line
`Keep the total activity and in-city transportation cost within N`, and the regex
`total\s*(?:travel\s*|trip\s*)?budget[^0-9]*?(\d+)` — which **requires the literal word "total"**.
Ordinary phrasing does not use it:

```
"I want to travel to Hangzhou alone for a day with a budget of 1500 RMB."
   parsed : {"taxi_cars_equals": 1}
   oracle : {"budgets": {"total": 1500.0}, "taxi_cars_equals": 1}
```

Same shape for room type: `"…and stay in two twin rooms."` → oracle `room_type = "twin"`, parsed
nothing.

## 3. What it costs — and the confound that halves the naive answer

**Confound found and quantified.** The HF sets' `hard_logic_py` literals are native **Chinese**
(`自然风光`, `本帮菜`) while `nature_language_en` is English. Scored in `en`, the verifier's
`attraction_type()` / `restaurant_type()` return English labels, so those clauses can **never** pass
regardless of our parser. Measured per clause on the e2e runs
([`e2e/cjk_artifact_correction.json`](e2e/cjk_artifact_correction.json)):

| set | clauses | CJK-literal clauses | CJK-literal pass rate | ASCII-literal pass rate |
| --- | --- | --- | --- | --- |
| familiar_100 first-30 | 325 | **0** | — | 91.69 |
| hf_human first-30 | 124 | 23 (18.5 %) | **0.00** | 92.08 |
| hf_medium first-30 | 240 | 18 (7.5 %) | **0.00** | 78.38 |

Correcting for it:

| set (n=30) | C-LPR raw | C-LPR ASCII-only | FPR raw | FPR ASCII-only |
| --- | --- | --- | --- | --- |
| familiar_100 first-30 | 91.69 | 91.69 | 43.33 | 43.33 |
| hf_human first-30 | 75.00 | **92.08** | 33.33 | **73.33** |
| hf_medium first-30 | 72.50 | **78.38** | 6.67 | **20.00** |

Two things follow, and they pull in opposite directions:

- On `human`, once the artifact is removed our per-clause satisfaction is **as good as on
  familiar-100** (92.08 vs 91.69) and FPR is *better* (73.33 vs 43.33) — but `human` averages 4.1
  clauses/query against familiar-100's 10.8, so that is a difficulty effect, not a robustness one.
- On `medium` — the closest density analogue at 8.0 clauses/query — the degradation survives the
  correction: C-LPR `91.69 → 78.38`, FPR `43.33 → 20.00`. The logical portion of the score
  (`0.25·C-LPR + 0.40·FPR`) falls from `40.25` to `27.60`, i.e. **-12.65 overall points from
  phrasing alone**, before the preference terms that are gated on constraint pass.

And a limit on this evidence worth stating plainly: **after** the budget and room-type gaps are
excluded, *every* residual parse gap on all three HF sets sits in a CJK-literal clause
([`residual_gaps_after_fix.json`](residual_gaps_after_fix.json) — `residual_ascii_literal_only` is
empty for `easy`, `medium` and `human`). So this data **cannot** tell us whether the name/type
families (`cuisine_preference`, `required_attraction_types`, `required_attractions`) are also
phrasing-brittle in a way that would cost real points on an English held-out set. Their 70–100 %
family-level miss rate is real extraction failure, but its *score* impact is unmeasurable here.

The one set that does speak to it is `tpc_phase2_test`, whose literals are English: there, 15 of 522
clauses remain parse gaps after the budget/room-type fix, spread over `restaurant_name` (4),
`inner_transport_set` (3), `attraction_name` (2), `restaurant_type` (2), `activity_time_window` (2),
`attraction_type` (1) and `accommodation_type` (1). So the name/type families *do* leak on English
data — but at 2.9 % of clauses on a template-phrased set, not at the 70–100 % rate the HF family
counts suggest. Treat the HF name/type miss rates as an upper bound of unknown tightness.

## 4. End-to-end confirmation

Paired diagnostic runs, identical shape — whole-run scheduler, `--total-budget-sec 1800`,
`--workers 3`, `n=30`, `lang=en`, zero LLM calls, evaluator parity `c89cfca`. Metadata and scores:
[`e2e/official_scores.json`](e2e/official_scores.json); predicted-vs-realized:
[`e2e/predicted_vs_realized.json`](e2e/predicted_vs_realized.json).

| run | clauses/q | parse R | C-LPR predicted ≤ | C-LPR real | FPR predicted ≤ | FPR real | MicEPR | MacEPR | **overall** | self-reported FPR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 first-30 | 10.83 | 0.958 | 100.00 | 91.69 | 100.00 | 43.33 | 100.0 | 100.0 | **64.57** | 50.00 |
| hf_human first-30 | 4.13 | 0.628 | 79.03 | 75.00 | 36.67 | 33.33 | 100.0 | 100.0 | **55.88** | 76.67 |
| hf_medium first-30 | 8.00 | 0.300 | 69.17 | 72.50 | **0.00** | **6.67** | 100.0 | 100.0 | **41.62** | **86.67** |

Three things this establishes:

1. **The reduced-budget control is faithful.** familiar-100 first-30 scores `64.57 / 91.69 / 43.33`
   against the full R17 row's `64.17 / 90.08 / 44.0`, so the `n=30`, `1800 s` shape is not what moves
   the other two rows.
2. **The static instrument predicts the dynamic outcome.** Every predicted ceiling lands within
   `~4` points of the realized value, on both metrics, on all three sets. The parse-gap count is
   therefore a usable cheap proxy for e2e damage.
3. **Commonsense is phrasing-independent.** `MicEPR`/`MacEPR` are `100.0` everywhere. The
   deterministic packer does not care how the query is worded; only the constraint layer does. So the
   held-out collapse cannot be a commonsense collapse *if* the environment terms held, and the
   inversion says they did.

### The amplifier: the agent cannot see its own failure

The self-score gap widens exactly with the parse gap — `+6.7` points on familiar-100, `+43.3` on
`human`, `+80.0` on `medium`. This is not cosmetic. The shipped scheduler is
triage → **repair only what fails** → polish, and "fails" is decided by
`evaluate_parsed_constraints` against the *parsed* constraints. A constraint we never extracted
cannot fail, so the query is classified as satisfied and promoted to polish. Consequence, observed:
the `hf_medium` run stopped with **`1545.6 s` of `1800 s` unspent** (familiar-100: `989.2 s`). Under
parse gaps the 5-hour envelope is not merely insufficient — it is spent on the wrong queries and then
partly not spent at all.

## 5. Ranked hypotheses

**1. Parse / coverage failure on non-template phrasing — best fit, measured.**
Zero parse gaps on familiar-100 versus 12–29 % everywhere else; the only set our extractor is clean
on is the one it was built against. Reproduced end-to-end: `-22.95` overall raw, `-12.65` on the
logical terms after correcting the CJK artifact, with commonsense untouched — the same
"C-LPR *and* FPR fell, environment terms did not" signature the held-out inversion produces. Two
named code-level causes with concrete repros. *Its one weakness:* the organizers describe the
held-out set as same-distribution as familiar-100, and if the held-out phrasing genuinely is that
numbered template, this hypothesis does not apply at all. We cannot check that, and it is the single
biggest uncertainty in this write-up.

**2. Overfitting to familiar-100 as a process failure — same evidence, different level, strong fit.**
Not an independent mechanism; it is *why* (1) went unnoticed. Parser F1 was only ever measured on
familiar-100 (`0.9949` recorded in the roadmap, `0.9552` here under the branch-aware diff), every
screen and development gate ran on familiar-100 val, and the second confirmation set
(`tpc_phase2_test`) turns out to share the same template. Nothing in the gate could have detected a
phrasing dependency. Directly supported by the F1 spread in §2 (`0.955` → `0.417`).

**3. Genuinely harder / denser held-out queries — plausible, partly measurable, cannot be isolated.**
The `human` result shows difficulty and phrasing are entangled: it is *worse* phrased than
familiar-100 yet scores *better* per clause once the artifact is removed, purely because it carries
4.1 clauses instead of 10.8. Conversely, per-query FPR decays multiplicatively in clause count, so a
held-out set even slightly denser than familiar-100 would score below it with an unchanged solver.
Consistent with the evidence; contributes an unknown amount; not separable from (1) without held-out
phrasing.

**4. Infrastructure failure on the organizers' host — poorly supported, near-excluded in its strong
form.** A cold-start or worker-pool failure ships schema-valid empty fallback plans, which would
drive `MicEPR`, `MacEPR`, `C-LPR`, `FPR` and all three preference terms toward zero and the overall
toward `~0`, not `33.2473`. Arithmetically, `FPR ≤ MacEPR`, so `MacEPR = 0` forces
`0.25·C-LPR ≈ 33.2`, i.e. `C-LPR > 100` — impossible. A *total* infrastructure failure is therefore
ruled out by the number itself. A *partial* one (a subset of workers dying, a subset of queries
timing out) remains possible and is not testable from here.

**5. Evaluator or harness contract mismatch — not investigated, no evidence either way.** Listed only
so it is not silently dropped. Our scoring path reproduces upstream `c89cfca` and the organizers'
command is the one we ship, so there is no positive reason to suspect it.

### How much of the gap is accounted for

| component | overall points |
| --- | --- |
| familiar-100 R17 baseline | 64.17 |
| measured phrasing effect, raw (`hf_medium` first-30 vs control) | **-22.95** |
| measured phrasing effect, CJK-corrected logical terms only | **-12.65** |
| … plus preference terms, which are gated on constraint pass (*estimated*, not measured) | ~-2 to -4 |
| organizer held-out `v1` | 33.25 |
| **unexplained residual** | **~8 to ~16** |

The raw figure over-attributes (it includes the CJK artifact); the corrected figure under-attributes
(it excludes name/type families whose impact this data cannot measure). The honest statement is that
phrasing brittleness explains **roughly half to three quarters** of the 31-point gap and a second
factor — most likely (3), possibly the partial form of (4) — carries the rest.

## 6. The one fix to make tomorrow

**Make `parse_budget` recognise a bare total budget, and `room_type` recognise plain room wording.**

Concretely: accept `(a|the)? budget of N`, `budget of N RMB/yuan/元`, `travel budget of N`,
`budget is N`, `within N RMB` as `budgets["total"]` when no scoped qualifier
(accommodation / dining / sightseeing / transport) precedes it; and map `single-bed / big bed / double
bed room` → `single`, `twin / twin-bed / two beds` → `twin`. Both are additive regex alternatives in
`parse_constraints.py` guarded by the existing scoped patterns, so familiar-100 behaviour is
unchanged **by construction**: familiar-100 contains the word "budget" in **0/100** queries (it says
`Keep the … cost within N`) and phrases room type as `Each accommodation stay must use twin-bed
rooms.`, which the current patterns already match. There is no familiar-100 text for either new
alternative to fire on.

**Expected effect**, measured statically over the full HF sets
([`fix_headroom.json`](fix_headroom.json)) — the two families are worth this much on their own:

| set | parse-gap clauses | queries with a gap | C-LPR ceiling | FPR ceiling |
| --- | --- | --- | --- | --- |
| HF `medium` | 363 → **89** | 150 → **71** | 71.28 → **92.96** | 0.00 → **52.67** |
| HF `easy` | 219 → **131** | 200 → **131** | 86.13 → **91.70** | 33.33 → **56.33** |
| HF `human` | 146 → **97** | 100 → **79** | 78.75 → **85.88** | 35.06 → **48.70** |
| HF `preference_base50` | 32 → **20** | 31 → **20** | 87.69 → **92.31** | 38.00 → **60.00** |
| `tpc_phase2_test` (English literals) | 17 → **15** | 17 → **15** | 96.74 → **97.13** | 88.67 → **90.00** |
| familiar_100 (control) | 0 → **0** | 0 → **0** | 100.00 → **100.00** | 100.00 → **100.00** |

On `medium` that restores the C-LPR ceiling to familiar-100's own level and lifts the FPR ceiling
from *structurally zero* to `52.67`. Given §4's finding that realized values track these ceilings
within `~4` points, the expected e2e effect on the `hf_medium` first-30 pair is roughly
`41.62 → 55–60` overall, at zero risk to familiar-100.

**How to measure it, in order:**

1. `.venv/bin/python -m pytest tests/phase2/test_budget.py tests/phase2/test_parser_accuracy.py
   tests/phase2/test_parser_coverage.py tests/phase2` — the regression wall (`test_budget.py` and
   `test_parser_accuracy.py` are the ones that pin familiar-100 parse behaviour). Any familiar-100
   parse change here means the guard failed.
2. `HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir <new screen>` —
   seconds. Requires: familiar-100 parse-gap count still `0/1109`, `hf_medium` parse gaps
   `363 → ≤89`. If this does not move, stop; nothing downstream will.
3. Re-run the exact §4 pair (`scripts/materialize_hf_split.py --hf-split medium --name
   hf_medium_probe30 --limit 30`, then `solve_phase2.py --total-budget-sec 1800 --workers 3`, then
   `eval_tpc.py`) and require `hf_medium` overall `41.62 → >50` **with** familiar-100 first-30 held at
   `64.57 ± 1`. Same command, same subset, same budget, so it is a paired delta.
4. Only then spend an eval-machine slot on a `full_runs/` row against
   [`20260806T115309Z`](../../full_runs/20260806T115309Z.json).

**Second fix, if there is time before `v2`:** close the self-deception gap rather than any individual
family. The scheduler currently treats "my parsed constraints are satisfied" as "done", which under
any parse gap both mis-ranks the repair queue and leaves budget unspent (§4). A cheap version — spend
residual envelope re-polishing *all* queries rather than idling once every parsed check passes — turns
unspent time into preference points and needs no parser change. Measure it by the same
`scheduler_budget_unspent_sec` figure recorded in [`e2e/official_scores.json`](e2e/official_scores.json).

## 7. Reproducing this

```bash
# §1-§3 static probe (seconds; needs the local HF dataset cache). Regenerates all four static
# evidence files: probe.json, summary.md, fix_headroom.json, residual_gaps_after_fix.json.
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
    --out-dir results/phase2_baselines/screens/20260806_generalization_probe

# §4 end-to-end pair (~15 min each on 3 workers)
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py \
    --hf-split medium --name hf_medium_probe30 --limit 30
HF_HUB_OFFLINE=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
    --split hf_medium_probe30 --method probe_hfmedium30 --total-budget-sec 1800 --workers 3
HF_HUB_OFFLINE=1 .venv/bin/python eval_tpc.py --splits hf_medium_probe30 --method probe_hfmedium30
```

The materialized splits, plan directories and `agent_env/runs/` working dirs were **deleted after
scoring** so no stray split ships in a submission archive; `scripts/materialize_hf_split.py`
regenerates them deterministically (HF row order, prefix `--limit`).

## Files

| file | what |
| --- | --- |
| [`probe.json`](probe.json) | full per-set report: inventory, family diff, clause coverage, gap decomposition, examples |
| [`summary.md`](summary.md) | the §2 table as generated |
| [`fix_headroom.json`](fix_headroom.json) | ceilings before/after the budget + room-type fix |
| [`residual_gaps_after_fix.json`](residual_gaps_after_fix.json) | what is left after that fix, split by literal language |
| [`e2e/official_scores.json`](e2e/official_scores.json) | the three paired runs: metadata, official scores, self-scores, unspent budget |
| [`e2e/predicted_vs_realized.json`](e2e/predicted_vs_realized.json) | static ceilings vs realized C-LPR/FPR per subset |
| [`e2e/cjk_artifact_correction.json`](e2e/cjk_artifact_correction.json) | CJK-literal clause pass rates and corrected C-LPR/FPR |
| `e2e/solve_*.log`, `e2e/probe_*/*_summary.json` | raw solver logs and scheduler summaries |

**Not done here:** no solver, parser, default, `agent_env/`, `chinatravel/agent/phase2/` or
`chinatravel/agent/tpc_agent/` file was changed; the two budget/room-type bugs are written up, not
fixed. `docs/` and `report/` were not touched.
