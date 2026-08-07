# Parser phrasing fix — closing the budget / room-type extraction gap

**Date** 2026-08-06 · **Branch** `report-v2` · **Contract** Implementation screen. Nothing here
promotes a change and nothing here is a `full_runs/` row. All work offline on **released** data; the
only held-out fact used is the single aggregate `33.2473` the organizers returned for `v1`.

Implements the one fix specified in
[`../20260806_generalization_probe/README.md`](../20260806_generalization_probe/README.md) §6, plus
two precision guards found while measuring it. Verification ladder run in full; every number below
is measured on this tree unless the row says *inferred* or cites the earlier screen.

## Verdict up front

| gate | required | measured | |
| --- | --- | --- | --- |
| test suite unchanged | all green, familiar-100 parse untouched | `1091` phase2 + `14` phase1 + `27` upstream, all exit `0` | **PASS** |
| familiar_100 parse gaps | exactly `0/1109` | `0/1109` | **PASS** |
| hf_medium parse gaps | `363 → ≤ 89` | `363 → 126` | **MISS** — see [why 89 was unreachable](#why-89-was-unreachable) |
| hf_medium first-30 e2e | `41.62 → > 50` | `41.62 → 49.99` | **MISS by 0.009** (< ⅕ of one query) |
| familiar_100 first-30 e2e | `64.57 ± 1` | `64.56528973412726` → `64.56528973412726` | **PASS, exactly** |

The direction and the mechanism are confirmed: the two named families went from ~100 % missing to
~0 % missing on every differently-phrased set, and on the English-literal clauses that an English
held-out set consists of, `hf_medium`'s logical terms rose `27.60 → 44.64` points. Both numeric
gates land just short, and both shortfalls have a measured cause that is *not* the parser.

## 1. What changed

`parse_constraints.py` only. `chinatravel/agent/tpc_agent/solver_constraints.py` was **checked and
deliberately not touched**: it parses the oracle `hard_logic_py` DSL, not natural language, so it is
the *reference* side of the parser-vs-oracle diff, not a mirror of the NL extractor. There is exactly
one NL extraction path (`parse_constraints.parse_query_no_oracle`, used by `TPCAgent` via
`chinatravel/agent/phase2/normalize.py`), so consistency is structural.

**a. Bare total budget** (`_bare_total_budget`, consulted only when the existing total routes miss):
`budget of N`, `budget of N RMB/yuan/元`, `travel budget of N`, `budget is/was/:/= N`,
`budget under/within/no more than N`, bare `budget N`, and `within/under/spend no more than N
<currency>` → `budgets["total"]`.

Guarded three ways so a scoped budget can never become the total:
- **before**: a scope word immediately preceding `budget` (accommodation / hotel / dining / food /
  sightseeing / attraction / transport / metro / taxi / intercity / intra-city / per-day …),
  optionally separated by a generic filler, rejects the candidate — so `intra-city travel budget of
  50.0` stays `inner_transport`. `travel` / `trip` alone are *not* scope words, so `a travel budget
  of 4000` is still a total.
- **after**: `... N for/on accommodation` and per-unit rates `... N per person / per meal / per
  night / a day` reject the candidate.
- **currency required** for the `within N` alternative, because familiar-100's scoped template is
  `Keep the accommodation cost within 342.` with no currency word.

**b. Room type** (`_ROOM_TYPE_PATTERNS`, un-anchored; the old version needed a trigger verb):
`twin` / `twin-bed` / `two beds` / `two twin rooms` / `double room` → `twin`;
`single room` / `single-bed` / `big bed` / `large bed` / `king|queen bed` / `double bed` → `single`.
Earliest match wins.

Two semantics were read off the verifier and the data rather than guessed. `room_type` is the *bed
count* per room, so a **`double bed` room is one bed → `single`** (the pre-fix code returned
`"double"`, which `parsed_verifier._room_type_to_numbed` maps to `2` — the opposite of the oracle),
while a **`double room` is a two-person room → `twin`** (measured: HF medium
`e20241028161347428726`, 2 travelers, oracle `room_type == 2`).

**c. Two precision guards found while measuring** (not in §6's spec; both are mis-scopes the bare
alternatives would otherwise introduce, and both are strictly harmful, not merely imprecise):
- `spend no more than 70 RMB per meal` was being read as `budgets["total"] = 70` (real query: HF
  medium `e20241028161351544529`). A 70-yuan plan total is unsatisfiable, so this would have
  *destroyed* queries the pre-fix parser merely under-constrained.
- `a budget of 500 yuan per day` likewise became a plan-wide `500`.

**d. Not done, on measured evidence.** A `people_number == 1 → room_type single` metadata default
looked free (38/40 released solo queries carry oracle code 1) and was **rejected**: familiar-100 has
two solo queries with code `2`, so the default would change familiar-100 behaviour — precisely the
guard this task forbids breaking. `family room` was also rejected: its two released instances
disagree (`easy m20241028164807696509` → 2, `medium e20241028161318465643` → 1).

**Tests** `tests/phase2/test_parser_phrasing_generalization.py` (50 tests): bare `budget of 1500
RMB` → `budgets.total == 1500` (helper *and* full solver-dict path); every scoped phrasing keeps its
own key with no `total`; per-unit rates and `budget`-as-adjective produce nothing; the plain room
wordings above; and a **floor test that pins familiar-100 byte-identically** — verbatim copies of the
pre-fix extractors are kept inside the test file and asserted equal to the current ones over all 100
familiar-100 queries, so "familiar-100 is unchanged" is a test rather than a claim. A tripwire test
also asserts familiar-100 still contains the word `budget` in 0/100 queries and no
`within <N> <currency>`, i.e. that the by-construction argument still holds.

## 2. Ladder step 1 — tests

`.venv/bin/python -m pytest` per directory, on the committed tree state:

| suite | tests | exit |
| --- | --- | --- |
| `tests/phase2` | 1091 (1041 pre-existing + 50 new) | `0` |
| `tests/phase1` | 14 | `0` |
| `tests/upstream` | 27 | `0` |

No pre-existing test was edited. `test_parser_accuracy.py` / `test_parser_coverage.py` (the
familiar-100 parse wall) and `test_budget.py` pass untouched.

## 3. Ladder step 2 — static probe, every set

`HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir
results/phase2_baselines/screens/20260806_generalization_probe_after_fix`. Before-columns are the
committed [generalization probe](../20260806_generalization_probe/probe.json); after-columns are
[this run](../20260806_generalization_probe_after_fix/probe.json). Identical instrument, identical
sets, same `scripts/parser_vs_oracle.py` semantics (the concurrent `llm_parse_mode` kwarg in that
file is additive and unused here).

| set | n | parse F1 before → after | parse-gap clauses before → after | C-LPR ceiling | FPR ceiling |
| --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 0.9552 → **0.9552** | **0/1109 → 0/1109** | 100.00 → 100.00 | 100.00 → 100.00 |
| local_released_150 | 150 | 0.7956 → 0.7956 | 17/522 → **15/522** | 96.74 → 97.13 | 88.67 → **90.00** |
| hf_easy | 300 | 0.625 → **0.7057** | 219/1579 → **132/1579** | 86.13 → 91.64 | 33.33 → **56.33** |
| hf_medium | 150 | 0.417 → **0.7676** | 363/1264 → **126/1264** | 71.28 → 90.03 | 0.00 → **52.67** |
| hf_human | 154 | 0.656 → **0.7308** | 146/687 → **99/687** | 78.75 → 85.59 | 35.06 → **48.05** |
| hf_preference_base50 | 50 | 0.631 → **0.6957** | 32/260 → **20/260** | 87.69 → 92.31 | 38.00 → **60.00** |

The two targeted families, before → after (clause-level parse gaps by kind):

| set | `cost_total` | `room_type` |
| --- | --- | --- |
| hf_easy | 60 → **0** | 28 → **1** |
| hf_medium | 145 → **14** | 116 → **14** |
| hf_human | 44 → **2** | 2 → **0** |
| hf_preference_base50 | 11 → **0** | 1 → **0** |
| local_released_150 | 0 → 0 (`cost_attraction` 3 → 3) | 2 → **0** |
| familiar_100 | 0 → 0 | 0 → 0 |

`hf_medium`'s **queries** with any parse gap fell `150 → 71` and its FPR ceiling rose `0.00 →
52.67` — both *exactly* the values §6 predicted (`71`, `52.67`). Value fidelity was checked
separately: over the `hf_medium` first-30 subset, extracted `budgets.total` and `room_type` match the
oracle in **30/30** queries — 0 value mismatches.

### Why 89 was unreachable

§6's `363 → 89` came from `fix_headroom`, which credits the fix with every clause whose only
uncovered kinds are `cost_*`/`room_type` — including clauses in queries whose English text contains
no constraints at all. Decomposing the measured residual of 126 (127 before the `double room` and
per-unit guards landed):

| residual kind | clauses | of which in a **markdown-title-only** query |
| --- | --- | --- |
| `restaurant_type` | 33 | 1 |
| `attraction_type` | 28 | 12 |
| `attraction_name` | 17 | 5 |
| `cost_total` | 14 | **14 (all)** |
| `room_type` | 14 | 11 |
| `accommodation_type` | 11 | 9 |
| `cost_restaurant` | 10 | **10 (all)** |
| total | 127 | 62 |

15 of `hf_medium`'s 150 queries have a `nature_language_en` that is **only** a markdown title —
`'**Travel Plan for a 2-Day Trip from Shenzhen to Guangzhou**'` is the entire visible text, while the
oracle still asserts a total cost and a room type. Every one of the 14 residual `cost_total` and 10
residual `cost_restaurant` clauses lives in those queries, as do 11 of the 14 residual `room_type`
clauses. `24 + 11 = 35` of the 38-clause shortfall (`127 − 89`) is therefore **not extractable from
the visible text at any parser quality** — it is a defect in that split's English field, present in
`medium` only (`0` such queries in `easy`, `human`, `familiar_100`, `local_released_150`).

The genuinely addressable remainder was ~3 clauses; `double room` closed 1 of them (`127 → 126`).
The rest are the solo-traveler inference rejected in §1d.

## 4. Ladder step 3 — paired end-to-end

Same shape as the probe's §4: whole-run scheduler, `--total-budget-sec 1800`, `--workers 3`, `n=30`,
`lang=en`, per-query cap `300 s`, zero LLM calls, evaluator parity `c89cfca`, fresh output
directories. Driver: [`run_paired_e2e.sh`](run_paired_e2e.sh); logs and scheduler summaries in
[`e2e/`](e2e/). Arms ran **sequentially**, never overlapping.

| run | C-LPR | FPR | MicEPR | MacEPR | **overall** | self-reported FPR | unspent budget |
| --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 first-30, before (probe) | 91.69 | 43.33 | 100.0 | 100.0 | 64.56528973412726 | 50.00 | 989.2 s |
| familiar_100 first-30, **after** | 91.69 | 43.33 | 100.0 | 100.0 | **64.56528973412726** | 50.00 | 995.9 s |
| hf_medium first-30, before (probe) | 72.50 | 6.67 | 100.0 | 100.0 | 41.619841269841274 | 86.67 | 1545.6 s |
| hf_medium first-30, **after** | **86.25** | **16.67** | 100.0 | 100.0 | **49.99093915343915** | 86.67 | 1542.0 s |

- The control is not merely within `±1`; it is **identical to every decimal**. The fix is inert on
  familiar-100 end-to-end, as the by-construction argument requires.
- `hf_medium` gained `+8.371`: C-LPR `+13.75`, FPR `+10.00`, commonsense untouched at `100.0`.
- It lands `0.00906` below the `> 50` gate. One query is worth `3.33` FPR points ≈ `1.33` overall on
  an `n=30` subset, so the shortfall is under a fifth of a single query — real, but not a signal
  distinguishable from subset noise. Reported as a miss regardless.

### Corrected for the CJK-literal artifact (the number that speaks to the held-out set)

The HF sets' oracle literals are native Chinese while the text is English, so those clauses cannot
pass under `en` scoring whatever the parser does (probe §3). Splitting per clause by literal
language, with `scripts/phase2_clause_language_split.py` (new; it reproduces the official `C-LPR
86.25` / `FPR 16.67` exactly, which is how I know it computes the same quantity):

| hf_medium first-30 | C-LPR raw | C-LPR ASCII-only | FPR raw | FPR ASCII-only | logical terms (`0.25·C-LPR + 0.40·FPR`) |
| --- | --- | --- | --- | --- | --- |
| before (probe §3) | 72.50 | 78.38 | 6.67 | 20.00 | 27.60 |
| **after** | 86.25 | **93.24** | 16.67 | **53.33** | **44.64** |

On English-literal clauses — the only kind an English held-out set can contain — per-clause quality
now **exceeds** familiar-100's own `91.69`, and FPR exceeds familiar-100's `43.33`. The logical
portion of the score rose **`+17.04` points** on this subset. Against the probe's estimate that
phrasing cost `-12.65` corrected logical points, this recovers it and then some *on this measure*;
I am **not** claiming `+17` overall on the held-out set, because 11 of the 30 queries still fail only
on unpassable CJK clauses and the preference terms are not included here.

## 5. Workstream B — does an LLM recover what the regex misses?

`scripts/phase2_llm_extraction_probe.py` (new), DeepInfra `Qwen/Qwen3.6-27B`, temperature 0, one call
per query, `n=30` per set, 120 calls, **0 errors**, responses cached.
Raw: [`llm_extraction/llm_extraction.json`](llm_extraction/llm_extraction.json). Three arms, same
instrument as §3: the shipped regex parse; LLM-first extraction with the **shipped** merge policy
(`normalize.llm_extract_stub`, where a validated LLM value *overwrites* the regex value); and a
counterfactual **fill-only** merge (the LLM may only populate families the regex left absent).

| set | arm | parse-gap clauses | FPR ceiling | family F1 | value accuracy |
| --- | --- | --- | --- | --- | --- |
| familiar_100 | regex | **0** | 100.00 | **0.9582** | **0.9582** |
| familiar_100 | LLM extract (shipped merge) | 0 | 100.00 | 0.7747 | 0.8311 |
| familiar_100 | regex + LLM fill-only | 0 | 100.00 | 0.8939 | **0.9582** |
| hf_medium | regex | 17 | 43.33 | 0.8829 | 0.9917 |
| hf_medium | LLM extract (shipped merge) | **1** | **96.67** | 0.7985 | 0.8389 |
| hf_medium | regex + LLM fill-only | **1** | **96.67** | 0.8082 | 0.8500 |
| hf_human | regex | 20 | 43.33 | 0.7688 | 0.9611 |
| hf_human | LLM extract | **10** | **70.00** | 0.7000 | 0.8167 |
| hf_human | regex + LLM fill-only | **10** | **70.00** | 0.7000 | 0.8167 |
| hf_easy | all three arms | 0 | 100.00 | 0.9474 | 1.0000 |

Three findings, in order of importance:

1. **Yes — an LLM recovers the residual coverage gap, and it is the *only* thing measured that
   does.** On `hf_medium` it closes `17 → 1` clause gaps (16 of 30 queries improved, **0**
   regressed) and lifts the FPR ceiling `43.33 → 96.67`; on `hf_human` `20 → 10` and `43.33 →
   70.00`. That residual is exactly the open-vocabulary name/type families more regex will not
   reach.
2. **The shipped merge policy would wreck familiar-100.** Letting a validated LLM value overwrite the
   deterministic one corrupts `budgets` in **15/30** familiar-100 queries and
   `excluded_inner_transport` in **14/30**, dropping family F1 `0.958 → 0.775` and value accuracy
   `0.958 → 0.831` — while recovering nothing there (it has nothing to recover). Any future
   `TPC_P2_LLM_PARSE=1` configuration must change that merge first.
3. **Fill-only is safe on the control and keeps the whole gain.** It breaks **nothing** on
   familiar-100 (value accuracy back to the regex's `0.9582`, `{}` families broken) and keeps
   `hf_medium`'s `17 → 1`. It still costs family *precision* (`0.958 → 0.894` on familiar-100,
   `0.883 → 0.808` on medium): the LLM adds families the oracle does not have. That is a real risk
   the ceilings do not price — a spurious constraint over-constrains the solver and can make a query
   infeasible, which is how an extraction "improvement" turns into a lower score.

**Therefore: not promotable tonight, and no flag was changed.** The next step is a paired e2e A/B of
fill-only LLM extraction on this same 30-query pair, which is the only thing that can convert those
ceilings into a score. Library-default flags remain off and the shipped path still makes zero LLM
calls.

## 6. Residual gaps I did **not** close

| residual | evidence | why not |
| --- | --- | --- |
| 15 `hf_medium` queries whose English text is a markdown title only (`62` of the `126` residual clauses) | §3 table | Not extractable from visible text. Dataset defect in that split's English field. |
| Open-vocabulary name/type families (`restaurant_type` 33, `attraction_type` 28, `attraction_name` 17, `accommodation_type` 11 on medium) | §3 | Out of this fix's scope; §5 shows an LLM closes them, unmeasured e2e. |
| Spelled-out amounts (`with a budget of over four thousand`, `human h20241029143846901147`) | grep of the residual set | 1 clause; a number-word parser is more surface area than it earns. |
| Per-person totals (`Our budget is 6000 RMB per person`, 4 `human` queries) | §1c | Deliberately **dropped**, not multiplied by party size: those queries carry no oracle `total_cost` at all, so inventing `6000 × people` would add a constraint the oracle never asserts. |
| Per-meal dining caps (`spend no more than 70 RMB per meal`) | oracle clause is `food_cost/food_count/people_count <= 70` | Our `budgets["dining"]` is a plan-wide cap; there is no per-meal-per-person family to hold this. Blocked from becoming a wrong `total` (§1c) rather than mapped. |
| The self-deception gap | `hf_medium` after-fix run still reports self-FPR `86.67` against a real `16.67`, and still leaves `1542 s` of `1800 s` unspent | The probe's "second fix". Unextracted clauses cannot fail the parsed check, so those queries are never queued for repair. Untouched here. |
| The `> 50` gate itself | §4 | Missed by `0.009`. Not chased: no in-scope phrasing change was left, and tuning to cross a threshold on a 30-query subset would be overfitting to it. |

## 7. Measured vs inferred

**Measured on this tree:** every number in §2, §3, §4, §5; the value-fidelity check (30/30); the
title-only decomposition; the familiar-100 byte-identity of budget and room-type parses (as a test
over all 100 queries).
**Taken from the committed earlier screen, not re-measured:** the before-columns of §3, and the
`before` rows of §4 including the ASCII-only `78.38` / `20.00` (those plan directories were deleted
after scoring, per that screen's cleanup note).
**Inferred, not measured:** that this improves the organizers' held-out score. The held-out set's
phrasing register is unknown; if it is familiar-100's numbered template, this fix is inert there —
that remains the single biggest uncertainty, exactly as the probe stated. Also inferred: that
fill-only LLM extraction would help end-to-end (§5 measures ceilings and precision cost, not score).

## 8. Reproducing

```bash
.venv/bin/python -m pytest tests/phase2 tests/phase1 tests/upstream -q

HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
    --out-dir results/phase2_baselines/screens/20260806_generalization_probe_after_fix

bash results/phase2_baselines/screens/20260806_parser_phrasing_fix/run_paired_e2e.sh
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_clause_language_split.py \
    --split hf_medium_probe30 --method probe2_hfmedium30

TPC_P2_LLM_BACKEND=deepinfra HF_HUB_OFFLINE=1 .venv/bin/python \
    scripts/phase2_llm_extraction_probe.py --sets familiar_100 hf_medium hf_human hf_easy \
    --limit 30 --workers 4 --out-dir <screen>/llm_extraction
```

The materialized `hf_medium_probe30` / `probe2_fam30` splits, their plan directories and
`agent_env/runs/` working dirs were **deleted after scoring** so no stray split ships in a submission
archive; the driver script regenerates them deterministically.

## Files

| file | what |
| --- | --- |
| [`e2e/eval_hfmedium30.log`](e2e/eval_hfmedium30.log), [`e2e/eval_fam30.log`](e2e/eval_fam30.log) | official `eval_tpc.py` output for both arms |
| [`e2e/solve_*.log`](e2e/), [`e2e/probe2_*/`](e2e/) | solver logs and scheduler summaries (budget spent/unspent) |
| [`e2e/cjk_split_after_fix.json`](e2e/cjk_split_after_fix.json) | per-clause pass split by oracle-literal language, after the fix |
| [`llm_extraction/llm_extraction.json`](llm_extraction/llm_extraction.json) | workstream B: three arms, per query, per family |
| [`run_paired_e2e.sh`](run_paired_e2e.sh) | the exact paired-arm driver |
| [`../20260806_generalization_probe_after_fix/`](../20260806_generalization_probe_after_fix/) | full static probe output on the fixed tree |
