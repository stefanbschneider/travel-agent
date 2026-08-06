# LLM arms — does a language model fix what our regex parser cannot read?

**Date** 2026-08-06 · **Branch** `report-v2` · **Contract** Measurement screen. Nothing here promotes
a change, nothing here is a `full_runs/` or `runs/` row, and no default was changed. Library-default
Phase 2 flags still make zero LLM calls (`tests/phase2/test_normalize_extract_fill.py`
`test_flags_from_env_accepts_extract_fill_and_still_defaults_to_audit`). All work offline on
**released** data; the only held-out fact used is the aggregate `33.2473` the organizers returned for
`v1`.

**Model** `Qwen/Qwen3.6-27B` on DeepInfra (the organizers' evaluation checkpoint), `temperature 0`.
**Total measured spend: `$3.55`** against a `$4.50` cap — itemized in [§0](#0-what-this-cost).

## The question, and the answer up front

The [generalization probe](../20260806_generalization_probe/README.md) measured our deterministic
constraint extraction as phrasing-brittle: zero clause-level gaps on `tpc_phase2_familiar_100`, the
numbered-template split it was built against, and 12–29 % on every differently-phrased released set.
A language model's plausible comparative advantage is exactly that — reading unfamiliar phrasing. So:

| # | experiment | verdict | changes what `v2` contains? |
| --- | --- | --- | --- |
| **1** | LLM as constraint extractor on free prose | **MEASURED. Real recall gain, no realized score gain.** The LLM finds the constraint the regex missed but not the exact environment-vocabulary *value* the verifier requires, so `missing` converts into `wrong_value` almost one-for-one and the only count that can pass a clause — `matched` — does not move. | **No**, not as a family-value source. Yes as a *diagnosis*: the bottleneck is value grounding, not constraint detection. |
| **1b** | the existing `TPC_P2_LLM_PARSE` flag (`audit` mode) re-measured on free prose | **MEASURED. Still not worth it.** Audit mode recovers `6/126` free-prose parse gaps where LLM-first extraction recovers `50/126`, and it damages familiar-100 (family F1 `0.955 → 0.917`). Its old RED screen was *not* only a wrong-dataset artifact. | **No.** |
| **2** | LLM-only planning, no solver (`Act`, autonomous tool use) | **MEASURED, and it is at the floor.** `overall 2.64` on free prose and `1.88` on familiar-100 against our solver's `48.49` / `67.71` on the same 8 queries. `MacEPR 0.0` on both: not one plan passed commonsense. | **No.** It is a report baseline, not a candidate. |
| **3** | upstream baselines (`RuleNeSy`) | **MEASURED, n=4 per register, `$0.069` all-in.** `overall 9.44` on free prose and `9.54` on familiar-100, against our solver's `55.89` / `40.11` on the same prefixes. `MicEPR 94–95` but `MacEPR 0.00`: it grounds in the sandbox correctly and still breaks a commonsense rule in every plan. | **No** — a baseline, not a candidate. Usable as the report's external comparison column. |

Ranking by expected value for `v2` is in [§5](#5-ranked-by-expected-value-for-v2).

The one thing tonight changed about `v2` is *not* on that list: it is
[workstream A](#workstream-a--the-phrasing-fix), the deterministic phrasing fix, which needs no model
and is already committed.

## 0. What this cost

Every figure is measured from `usage.prompt_tokens` / `usage.completion_tokens` on each response, at
DeepInfra's Qwen3 list price (`$0.32` / `$3.20` per 1M in/out — `DEFAULT_PRICE_IN_PER_MTOK`).

| item | live calls | tokens (in / out) | spend |
| --- | --- | --- | --- |
| Exp 1 sizing probe (2 queries, as instructed before sizing anything) | 2 | 2 296 / 74 | `$0.0010` |
| thinking-mode response-shape test (3 raw calls, [§2](#the-harness-bug-thinking-mode-would-have-hidden)) | 3 | ~110 / 659 | `$0.0021` |
| **Exp 1 — `extract` over all 904 released English queries** | 852 | 995 358 / 53 638 | **`$0.4902`** |
| Exp 1 — `extract_fill` over the same 904 | 0 (904 cache hits) | 0 / 0 | **`$0.0000`** |
| Exp 1b — `audit`, first attempt, rate-limited and discarded | 51 | — | `$0.0506` |
| **Exp 1b — `audit` over 400 queries, with retries** | 337 | 454 299 / 68 535 | **`$0.3647`** |
| Exp 2 sizing probe — thinking **on**, 2 queries | 24 | — | `$0.2007` |
| Exp 2 sizing probe — thinking **off**, 2 queries | 76 | — | `$0.2600` |
| **Exp 2 — LLM-only `Act`, 8 free-prose queries** | 277 | 2 338 208 total | **`$0.8527`** |
| **Exp 2 — LLM-only `Act`, 8 familiar-100 queries** | 335 | 3 660 064 total | **`$1.2591`** |
| Exp 3 — `RuleNeSy`, 4 failed/sizing attempts (worker deaths, timeouts) | 6 | — | `$0.0099` |
| **Exp 3 — `RuleNeSy`, 4 free-prose queries** | 8 | 6 389/query | **`$0.0290`** |
| **Exp 3 — `RuleNeSy`, 4 familiar-100 queries** | 8 | ~6 400/query | **`$0.0297`** |
| endpoint health check after the rate limit | 3 | 42 / 6 | `~$0.0000` |
| | | **total** | **`$3.5498`** |

Two things this buys that are worth naming. The response cache
(`CachingLLMClient`, `cache/phase2_llm_parse/`) made the `extract_fill` arm — a *different merge
policy over the identical prompts* — completely free, which is why a second policy could be measured
at all. And the `$0.13`/query cost of the LLM-only arm is 260× the `$0.0005`/query cost of the parse
arm, which is the whole reason the priority order in the task was the right one.

## Workstream A — the phrasing fix

Implemented, verified, and **already committed** as `b9feb250` — concurrently by the other agent on
this branch, which committed the same working tree. Its own screen is
[`../20260806_parser_phrasing_fix/`](../20260806_parser_phrasing_fix/README.md) and it is the
authority on the fix; this section records only that I verified it independently, plus the two
findings my audit added.

Independently reproduced here (`parse_fix/probe.json`, generated by
`scripts/phase2_generalization_probe.py` on this tree):

| set | parse-gap clauses, before → after | C-LPR ceiling | FPR ceiling |
| --- | --- | --- | --- |
| `familiar_100` (control) | `0/1109 → 0/1109` | `100.00 → 100.00` | `100.00 → 100.00` |
| `local_released_150` | `17 → 15` | `96.74 → 97.13` | `88.67 → 90.00` |
| `hf_easy` | `219 → 132` | `86.13 → 91.64` | `33.33 → 56.33` |
| `hf_medium` | `363 → 127` | `71.28 → 89.95` | `0.00 → 52.67` |
| `hf_human` | `146 → 101` | `78.75 → 85.30` | `35.06 → 46.75` |
| `hf_preference_base50` | `32 → 20` | `87.69 → 92.31` | `38.00 → 60.00` |

A per-family differential audit against the pre-fix parser (`HEAD~` at the time,
`_parse_constraints_head_ref`) over all six sets confirms familiar-100 is untouched **by
construction, not by luck**, and quantifies the gain:

| set | `budgets.total` correct, before → after | `room_type` correct, before → after | spurious total | wrong value | any scoped-family change |
| --- | --- | --- | --- | --- | --- |
| `familiar_100` | `16/16 → 16/16` | `9/9 → 9/9` | 0 | 0 | **0** |
| `local_released_150` | `19/19 → 19/19` | `15/18 → 18/18` | 0 | 0 | **0** |
| `hf_easy` | `0/60 → 60/60` | `2/30 → 29/30` | 0 | 0 | **0** |
| `hf_medium` | `2/148 → 134/148` | `4/120 → 106/120` | 0 | 0 | **0** |
| `hf_human` | `2/48 → 46/48` | `1/3 → 3/3` | 6 | 0 | **0** |
| `hf_preference_base50` | `0/11 → 11/11` | `0/1 → 1/1` | 0 | 0 | **0** |

Two findings from that audit that are not in the fix's own screen, both pinned by
`tests/phase2/test_parser_phrasing.py`:

- **A 1000× pre-existing bug, now fixed.** The *old* total-budget route,
  `total\s*budget[^0-9]*?(\d+)`, read `"total budget of 10,000"` as `10.0` (live on `hf_human` uid
  `h20241029143812547929`). Comma-grouped amounts now parse.
- **`hf_medium`'s residual 14 budget + 14 room-type misses are a dataset defect, not a parser
  defect.** In `15/150` `hf_medium` records the English field `nature_language_en` is not a query at
  all — it is a rendered plan title (`"**Travel Plan for a 2-Day Trip from Shenzhen to
  Guangzhou**"`, nothing else). No parser and no model can extract a constraint from it, so ~10 % of
  `hf_medium`'s measured parse gap is unreachable by any method. This also caps what Experiment 1
  could have shown on that set.

## Experiment 1 — LLM as constraint extractor on unfamiliar phrasing

### Command

```bash
# 1. sizing first, 2 queries (the instruction, and it set every later arm's size)
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set hf_medium --limit 2 --mode extract --out-dir /tmp/cost_probe

# 2. LLM-first extraction, every released English query (n=904)
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set familiar_100 --set local_released_150 --set hf_easy --set hf_medium --set hf_human \
    --set hf_preference_base50 --mode extract \
    --out-dir results/phase2_baselines/screens/20260806_llm_arms/exp1_extract

# 3. the same 904 prompts, fill-only merge -- served entirely from cache, $0
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set familiar_100 --set local_released_150 --set hf_easy --set hf_medium --set hf_human \
    --set hf_preference_base50 --mode extract_fill \
    --out-dir results/phase2_baselines/screens/20260806_llm_arms/exp1_extract_fill

# 4. the flag that already exists (audit mode), on the sets that matter
HF_HUB_OFFLINE=1 TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
    --set familiar_100 --set local_released_150 --set hf_medium --mode audit \
    --retries 4 --backoff-sec 4 \
    --out-dir results/phase2_baselines/screens/20260806_llm_arms/exp1_audit
```

Instrument: `scripts/phase2_llm_parse_arms_probe.py` (new). It is the generalization probe's own
clause-coverage layer plus `scripts/parser_vs_oracle.py` unchanged, with one extra arm, so every
number is comparable to the probe's. Deterministic and LLM arms are computed **on the same query, in
the same process, one after the other**, so the pairing is exact. One LLM call per query.

### The model fired

| arm | live calls | cache hits | failures | timeouts | retries | empty responses | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `extract` (n=904) | **852** | 52 | **0** | **0** | 0 | 0 | `MEASURED` |
| `extract_fill` (n=904) | 0 | **904** | 0 | 0 | 0 | 0 | `MEASURED FROM CACHE` |
| `audit` (n=400), 1st attempt | 51 | 12 | **312** | 25 | — | 0 | **`UNMEASURED`** — discarded |
| `audit` (n=400), with retries | **337** | 63 | 0 | 1 | 1 | 0 | `MEASURED` |

The 52 cache hits on `extract` are `hf_preference_base50` uids that also appear in `hf_easy`; they
were served from the earlier set in the same run, not from a stale cache.

**The discarded first `audit` attempt is the methodology requirement doing its job.** It failed 306
calls with `RateLimitError` because it shared an API key with the concurrently running 4-worker
Experiment 2 arm. Because `normalize.parse_to_ir` swallows every LLM exception by contract, each of
those 306 queries silently scored as *the deterministic parse* — the exact mechanism that made an
earlier parse screen read `+1.97` when 10 of 30 audits had timed out. Without wire-level call
counting it would have looked like a clean "audit mode makes no difference" result. The endpoint was
verified healthy afterwards (3/3 calls OK), retries were added to the instrument, and the arm was
re-run. The raw rate-limited run is kept as `exp1_audit_ratelimited/` so the trap is on the record.

### Result: the gap closes, the score does not follow

Family-level precision / recall / F1 and clause-level parse gaps, all 904 queries. `deterministic` is
the post-workstream-A shipped parser.

| set | n | arm | parse P | parse R | parse F1 | parse-gap clauses | C-LPR ceiling | FPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `familiar_100` | 100 | deterministic | **0.955** | **0.955** | **0.955** | **0**/1109 | 100.00 | 100.00 |
| `familiar_100` | 100 | `extract` | 0.710 | 0.811 | 0.757 | 0/1109 | 100.00 | 100.00 |
| `familiar_100` | 100 | `extract_fill` | 0.759 | 0.866 | 0.809 | 0/1109 | 100.00 | 100.00 |
| `local_released_150` | 150 | deterministic | **0.806** | **0.785** | **0.796** | 15/522 | 97.13 | 90.00 |
| `local_released_150` | 150 | `extract` | 0.764 | 0.779 | 0.771 | **5**/522 | **99.04** | **96.67** |
| `local_released_150` | 150 | `extract_fill` | 0.742 | 0.753 | 0.748 | **5**/522 | **99.04** | **96.67** |
| `hf_easy` | 300 | deterministic | **0.696** | 0.716 | **0.706** | 132/1579 | 91.64 | 56.33 |
| `hf_easy` | 300 | `extract` | 0.620 | 0.712 | 0.663 | **62**/1579 | **96.07** | **79.33** |
| `hf_easy` | 300 | `extract_fill` | 0.623 | **0.716** | 0.666 | **62**/1579 | **96.07** | **79.33** |
| `hf_medium` | 150 | deterministic | **0.774** | **0.761** | **0.768** | 126/1264 | 90.03 | 52.67 |
| `hf_medium` | 150 | `extract` | 0.660 | 0.710 | 0.685 | **76**/1264 | **93.99** | **81.33** |
| `hf_medium` | 150 | `extract_fill` | 0.693 | 0.756 | 0.723 | **76**/1264 | **93.99** | **81.33** |
| `hf_human` | 154 | deterministic | **0.800** | **0.673** | **0.731** | 99/687 | 85.59 | 48.05 |
| `hf_human` | 154 | `extract` / `extract_fill` | 0.642 | 0.670 | 0.656 | **42**/687 | **93.89** | **75.97** |
| `hf_preference_base50` | 50 | deterministic | **0.662** | **0.733** | **0.696** | 20/260 | 92.31 | 60.00 |
| `hf_preference_base50` | 50 | `extract` / `extract_fill` | 0.595 | **0.733** | 0.657 | **7**/260 | **97.31** | **86.00** |

Read the two halves against each other, because they disagree:

- **Clause-level, the LLM wins clearly and safely.** Parse gaps fall by **40–65 %** on every
  free-prose set (`hf_medium 126→76`, `hf_easy 132→62`, `hf_human 99→42`, `pref50 20→7`,
  `local150 15→5`), and **`clauses_broken_by_llm` is `0` on every single set** — it never removes a
  family the regex had right. The implied FPR ceiling on `hf_medium` goes `52.67 → 81.33`.
- **Family-level, the LLM loses on every set, including the ones whose gaps it closed.**

The reconciliation is in the raw buckets, and it is the finding:

| set | arm | `matched` | `missing` | `spurious` | `wrong_value` | value acc |
| --- | --- | --- | --- | --- | --- | --- |
| `familiar_100` | deterministic | **661** | 0 | **0** | 30 | **0.955** |
| `familiar_100` | `extract` | 563 | 0 | 103 | 128 | 0.811 |
| `familiar_100` | `extract_fill` | 601 | 0 | 103 | 90 | 0.866 |
| `local_released_150` | deterministic | **309** | 43 | 42 | 41 | **0.882** |
| `local_released_150` | `extract` | 308 | **19** | 40 | 66 | 0.820 |
| `local_released_150` | `extract_fill` | 296 | **19** | 40 | 78 | 0.795 |
| `hf_easy` | deterministic | 391 | 132 | **177** | **49** | **0.923** |
| `hf_easy` | `extract_fill` | 391 | **69** | 193 | 112 | 0.818 |
| `hf_medium` | deterministic | **391** | 116 | **122** | **38** | **0.934** |
| `hf_medium` | `extract_fill` | 388 | **67** | 148 | 90 | 0.851 |
| `hf_human` | deterministic | **195** | 97 | **49** | **28** | **0.910** |
| `hf_human` | `extract_fill` | 193 | **42** | 76 | 85 | 0.763 |
| `hf_preference_base50` | deterministic | 62 | 20 | **32** | **7** | **0.930** |
| `hf_preference_base50` | `extract_fill` | 62 | **8** | 34 | 19 | 0.810 |

**`missing` falls and `wrong_value` rises by almost exactly the same amount, so `matched` does not
move.** `hf_easy`: `missing -63`, `wrong_value +63`, `matched 391 → 391`. `hf_medium`: `-49 / +52`,
`matched 391 → 388`. `hf_human`: `-55 / +57`, `matched 195 → 193`. `pref50`: `-12 / +12`,
`matched 62 → 62`. `local150`: `-24 / +37`, `matched 309 → **296**` — worse.

`matched` is the only bucket that can satisfy a clause. The evaluator checks the *value*
(`restaurant_type_set(plan) ⊆ {…}`, `total_cost <= N`), not the presence of a family. So:

> **The LLM reliably detects *that* a constraint was stated and reliably fails to produce the exact
> environment-vocabulary value the verifier compares against.** The parse-gap ceiling it lifts is a
> necessary condition that its own value accuracy then fails to convert.

The observed mechanism, from the cached responses: on `"I want to eat hotpot"` the model returns
`cuisine_preference: ["hotpot"]`, which `normalize.validate_extract_families` drops because
`hotpot` is not in the closed environment vocabulary read from the restaurant CSVs. The families it
recovers most are exactly the vocabulary-bound ones — `restaurant_type`, `attraction_type`,
`restaurant_name`, `attraction_name`, `accommodation_type` — and on the HF sets a large share of
those oracle literals are **Chinese** (`本帮菜`, `自然风光`) and can never pass under `en` scoring
anyway, a confound the generalization probe already quantified. `local_released_150` is the one set
with English literals throughout, and there `matched` went **down**. That is the cleanest reading
available and it is negative.

**`extract_fill` is strictly better than `extract` and still not better than the regex.** The
fill-only merge (new library mode `TPC_P2_LLM_PARSE_MODE=extract_fill`, `normalize.py`,
`tests/phase2/test_normalize_extract_fill.py`) forbids the LLM from overwriting a family the regex
filled. It recovers the identical clause gaps while repairing much of the precision loss
(`hf_medium` F1 `0.685 → 0.723`, queries with worse recall `27 → 3`; `familiar_100` F1
`0.757 → 0.809`, `72 → 60`). It is the right shape for the idea, and on the numbers above it still
does not reach the deterministic parser on any set. The other agent's independent n=30 screen
([`../20260806_parser_phrasing_fix/llm_extraction/`](../20260806_parser_phrasing_fix/llm_extraction/llm_extraction_summary.md))
reaches the same ordering on the same three sets, from a separately written instrument.

### Verdict — Experiment 1

**No, this does not change what `v2` should contain.** Not as a family-value source, and not behind
a flag we would turn on: on the one released set with English literals throughout it reduces the
count of correctly-matched families, and on familiar-100 it is strictly damaging.

It does change what we *believe*, which is worth more than one flag. The hypothesis under test was
"our extractor cannot read unfamiliar phrasing". The measured answer is narrower: our extractor reads
unfamiliar phrasing well enough to *notice* the constraint (after workstream A) and the residual loss
is **value grounding into a closed vocabulary** — which is a deterministic entity-resolution problem
(`normalize.resolve_entities`, `TPC_P2_ENTITY_RESOLUTION`), not a language problem. An LLM proposing
a free-text value is the wrong tool; an LLM proposing a *candidate to be resolved against the
environment catalogue* is a different and untested one.

**Next measurement:** pair `extract_fill` with the existing deterministic entity-resolution layer
(`TPC_P2_ENTITY_RESOLUTION=1`), so every LLM-proposed name/type value is snapped to the environment
catalogue before it counts, and re-run this exact probe. All 904 responses are already cached, so the
LLM side of that measurement costs **`$0`**. If `matched` rises on `local_released_150`, the idea is
alive; if it does not, it is closed.

### Verdict — Experiment 1b (the flag that already exists)

`TPC_P2_LLM_PARSE` defaults to `audit` mode, and `audit` is what screened RED at `-3.20`. Re-measured
where the deterministic parser actually fails:

| set | arm | parse F1 | parse-gap clauses | clauses recovered | queries recall down |
| --- | --- | --- | --- | --- | --- |
| `familiar_100` | deterministic | **0.955** | 0/1109 | — | — |
| `familiar_100` | `audit` | 0.917 | 0/1109 | 0 | **13** |
| `local_released_150` | deterministic | 0.796 | 15/522 | — | — |
| `local_released_150` | `audit` | **0.817** | **14**/522 | 1 | **0** |
| `hf_medium` | deterministic | **0.768** | 126/1264 | — | — |
| `hf_medium` | `audit` | 0.762 | **120**/1264 | 6 | **0** |

Audit mode is a *conservative patcher*: it recovers `6` of `126` free-prose gaps where LLM-first
extraction recovers `50`, and it still damages familiar-100 (`matched 661 → 637`). So the RED screen
was not merely measured on the wrong dataset — the stage is too weak to have helped on the right one
either. The one positive is `local_released_150` (`F1 +0.021`, `matched 309 → 319`, zero regressions),
which is a template-phrased English set — not the free-prose case it was re-measured for.
**No change to `v2`.**

## Experiment 2 — LLM-only planning, no solver

### Command

```bash
# free-prose subset (materialized from HF medium, deterministic prefix)
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py \
    --hf-split medium --name hf_medium_arms24 --limit 24

TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
    --arm llm-only --agent Act --split hf_medium_arms24 --n 8 --max-steps 45 \
    --max-tokens 4096 --call-timeout-sec 90 --max-calls 60 --budget-sec 900 \
    --workers 4 --method exp2_llmonly_act_hfmedium8

# familiar-100 subset, identical settings
TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
    --arm llm-only --agent Act --split-set familiar_100_val --n 8 --max-steps 45 \
    --max-tokens 4096 --call-timeout-sec 90 --max-calls 60 --budget-sec 900 \
    --workers 4 --method exp2_llmonly_act_familiar8

# paired deterministic control: same uids, same 900 s/query cap, same 4 workers, zero LLM calls
HF_HUB_OFFLINE=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
    --split hf_medium_arms24_n8 --method exp2_ctrl_solver_hfmedium8 --budget-sec 900 --workers 4
HF_HUB_OFFLINE=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
    --split tpc_phase2_familiar_100_val_n8 --method exp2_ctrl_solver_familiar8 --budget-sec 900 --workers 4

# score, same evaluator, same uid list, for all four
HF_HUB_OFFLINE=1 .venv/bin/python eval_tpc.py --splits hf_medium_arms24_n8 \
    --method <method> --lang en
HF_HUB_OFFLINE=1 .venv/bin/python eval_tpc.py --splits tpc_phase2_familiar_100_val_n8 \
    --method <method> --lang en
```

### The model fired

| arm | queries | ok | timed out | plans written | plans non-empty | LLM calls | failures | timeouts | tokens/query | $/query | wall/query | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Act`, free prose (n=8) | 8 | **8** | 0 | 8 | **8** | **277** (34.6/q) | **0** | **0** | 292 276 | `$0.107` | 110.5 s | `MEASURED` |
| `Act`, familiar-100 (n=8) | 8 | **8** | 0 | 8 | 5 | **335** (41.9/q) | **0** | **0** | 457 508 | `$0.157` | 138.3 s | `MEASURED` |

Zero failures, zero timeouts, 34–42 tool-using turns per query, and a non-empty itinerary written for
every query on the free-prose subset. **This arm is measured and the failure below is the model's,
not the harness's.**

### The harness bug thinking mode would have hidden

The owner asked for thinking mode, so it was tried first and it is **not** reportable — for a reason
worth recording, because the naive run would have produced a plausible-looking zero.

Three raw calls against the endpoint (`$0.0021`) established the response contract:

| configuration | `content` | `reasoning_content` | completion tokens |
| --- | --- | --- | --- |
| thinking off, `stop=["\n"]` | `attractions_keys("Beijing")` | absent | 8 |
| **thinking on, `stop=["\n"]`** | **`''`** | present, truncated | 7 |
| thinking on, no `stop` | `attractions_keys("Beijing")` | present, full | **644** |

Upstream's `Act` loop forces one action per turn with `stop=["\n"]`. Under thinking mode the stop
sequence fires on the first newline of the *reasoning*, so `content` returns empty and **every action
is unparseable** — the arm would have scored zero for a harness reason. `make_budgeted_llm` now
suppresses the stop sequence when thinking is enabled and honours `one_line` client-side
(`_first_nonempty_line`), so the loop works either way.

With that fixed, thinking mode was still measured and still rejected, on cost and latency rather than
on quality: **`--enable-thinking --max-steps 40`, 2 queries, `$0.2007`, 24 calls in 1800 s — 75 s per
call, 4 timeouts at a 180 s per-call cap, and the 900 s per-query budget exhausted at step 12 of 40,
with no plan written** (`exp2_costprobe_thinking/summary.json`, correctly `UNMEASURED`). Reasoning
costs ~644 output tokens for a one-line tool call; extrapolated to 40 steps it is `~$1.1`/query, i.e.
the entire remaining budget for three queries. **Thinking mode was therefore dropped and the arm ran
thinking-off at `--max-steps 45`** — 50 % above the recipe's default, 34–42 turns actually used.

### Result

Official evaluator, identical uid list per row, `lang=en`, evaluator parity `c89cfca`.

| subset | arm | MicEPR | MacEPR | C-LPR | FPR | DAV | ATT | DDR | **overall** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| free prose, `hf_medium_arms24_n8` | **LLM-only `Act`** | 26.39 | **0.00** | **0.00** | **0.00** | 0.00 | 0.00 | 0.00 | **2.64** |
| free prose, `hf_medium_arms24_n8` | our solver (control) | 100.0 | 100.0 | 87.50 | 12.50 | 9.38 | 12.50 | 10.42 | **48.49** |
| familiar-100, `tpc_phase2_familiar_100_val_n8` | **LLM-only `Act`** | 18.75 | **0.00** | **0.00** | **0.00** | 0.00 | 0.00 | 0.00 | **1.88** |
| familiar-100, `tpc_phase2_familiar_100_val_n8` | our solver (control) | 100.0 | 100.0 | 89.41 | 50.00 | 31.77 | 42.66 | 32.64 | **67.71** |

`MacEPR 0.00` on both subsets: **not one of the 16 plans passed the commonsense checks.** `MicEPR`
`26.39` / `18.75` says roughly a fifth to a quarter of individual environment checks pass, so the
model produces itineraries with real POIs in roughly the right shape that never satisfy the full
legality contract at once — wrong transport links, meals outside their windows, discontinuous
accommodation. Because `C-LPR` and `FPR` are conditioned on a commonsense-passing plan, every logical
and preference term is zero by construction.

The question the pairing was built to answer — *does the LLM degrade less than our solver when
phrasing changes?* — **cannot be answered from this arm, and saying so is the honest result.** The
LLM-only arm is at the floor on both registers (`2.64` vs `1.88`, and the *free-prose* number is the
higher of the two), so it has nothing to degrade from. Our solver, on the same 16 queries, drops
`67.71 → 48.49`. A floor is not robustness.

### Verdict — Experiment 2

**No.** Nothing here belongs in `v2`. It is a clean, honestly-measured report baseline: a
tool-using LLM with 34–42 autonomous turns and a well-formed English prompt scores `~2` where our
deterministic solver scores `48–68` on the identical queries, and its failure is total at the
commonsense layer, i.e. before any constraint reasoning is even scored.

**Next measurement, if the report wants one:** none on the planning side. The informative variant
would be `ReAct` (one-shot exemplar) to check whether the commonsense collapse is a prompting artifact
rather than a capability limit — but the recipe puts `ReAct` at ~10× this arm's token cost, so it needs
its own budget, and its expected value is a slightly better-explained zero.

## Experiment 3 — upstream `RuleNeSy` (MEASURED, n=4 per register)

### Command

```bash
# n=4 per register, SEQUENTIAL: the multi-worker path dies for this arm (see below)
TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
    --arm upstream --agent RuleNeSy --split hf_medium_arms24 --n 4 \
    --max-tokens 4096 --call-timeout-sec 90 --max-calls 40 --budget-sec 780 \
    --workers 1 --method exp3_upstream_rulenesy_hfmedium4
TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
    --arm upstream --agent RuleNeSy --split-set familiar_100_val --n 4 \
    --max-tokens 4096 --call-timeout-sec 90 --max-calls 40 --budget-sec 780 \
    --workers 1 --method exp3_upstream_rulenesy_familiar4
```

### Two tooling failures found first, and how they were bounded

| attempt | settings | outcome | LLM calls |
| --- | --- | --- | --- |
| 1 | `--n 2 --workers 2 --budget-sec 600` | both queries failed, **no telemetry files written** | 0 |
| 2 | `--n 1 --workers 1 --budget-sec 300` | 2 translation calls, then **exceeded the 300 s budget in DFS** | 2 |
| 3 | `--n 4 --workers 4 --budget-sec 780` | **`BrokenProcessPool` on all four**, workers died before solving | 0 |
| 4 | `--n 2 --workers 1 --budget-sec 780` | **2/2 solved**, 333 s and 312 s | 4 |

`assess_arm` returned `reportable: false` / `UNMEASURED` for attempts 1–3, which is the rule working:
a zero-call arm is not a null result. Two distinct causes, both ours, both recorded because they will
recur:

- **The multi-worker path is broken for this arm.** Every worker died with `BrokenProcessPool`. The
  `llm-only` arm survives 4 workers on the same box, so it is specific to the `NesyAgent`
  construction path (one `WorldEnv` per worker, and that path also reassigns global `sys.stdout` to a
  file logger). Run this arm with `--workers 1`.
- **`RuleNeSy` is DFS-bound, not LLM-bound.** It spends exactly **2** LLM calls per query on the
  nl2sl translation and then up to ~330 s of CPU in search, so a per-query budget sized for our own
  solver starves it. At `--budget-sec 780 --workers 1` it completes.

### The model fired

| arm | queries | ok | timed out | plans non-empty | LLM calls | failures | tokens/query | $/query | wall/query | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `RuleNeSy`, free prose (n=4) | 4 | **4** | 0 | **4** | **8** (2.0/q) | **0** | 6 389 | **`$0.0072`** | 183 s | `MEASURED` |
| `RuleNeSy`, familiar-100 (n=4) | 4 | **4** | 0 | **4** | **8** (2.0/q) | **0** | ~6 400 | **`$0.0074`** | 103 s | `MEASURED` |

At `$0.007`/query this is **18× cheaper than the LLM-only arm** and **14× more expensive than the
parse arm** — the whole cost of the arm was `$0.069` including the four failed attempts.

### Result — three-way, same uids, same evaluator

`n=4` per register. **These `n=4` rows are noisy**: our own solver reads `40.11` on the familiar-100
`n=4` prefix against `67.71` on the `n=8` superset, purely because the 4-query prefix happens to
contain no query it fully satisfies (`FPR 0.0`). Read the *ordering*, not the gaps.

| subset | arm | MicEPR | MacEPR | C-LPR | FPR | **overall** |
| --- | --- | --- | --- | --- | --- | --- |
| free prose, `hf_medium_arms24_n4` | our solver (control) | 100.0 | 100.0 | 90.63 | 25.00 | **55.89** |
| free prose, `hf_medium_arms24_n4` | upstream `RuleNeSy` | 94.44 | **0.00** | 0.00 | 0.00 | **9.44** |
| free prose, `hf_medium_arms24_n4` | LLM-only `Act` | 27.78 | **0.00** | 0.00 | 0.00 | **2.78** |
| familiar-100, `..._val_n4` | our solver (control) | 100.0 | 100.0 | 80.43 | 0.00 | **40.11** |
| familiar-100, `..._val_n4` | upstream `RuleNeSy` | 95.37 | **0.00** | 0.00 | 0.00 | **9.54** |
| familiar-100, `..._val_n4` | LLM-only `Act` | 6.48 | **0.00** | 0.00 | 0.00 | **0.65** |

Two things worth having in the report:

- **`RuleNeSy` sits between the two**, and its failure mode is different from the LLM-only arm's.
  `MicEPR 94–95` means it gets nearly every individual environment check right — it is grounding
  properly in the sandbox — but `MacEPR 0.00` means every plan still breaks at least one commonsense
  rule, which zeroes all logical and preference terms. The LLM-only arm's `MicEPR 6–28` is a
  different, much earlier failure: it is not grounding at all.
- **`RuleNeSy` is register-insensitive (`9.44` free prose vs `9.54` familiar-100)** while our solver
  moves `55.89 → 40.11` across the same two prefixes. That is *not* evidence it is more robust: it is
  flat because both numbers are at the same floor, exactly as with the LLM-only arm. A floor is not
  robustness. No arm in this screen degrades gracefully, because no arm except ours ever climbs.

### Verdict — Experiment 3

**No change to `v2`**, as expected of a baseline. It is a **usable external comparison point for the
technical report**, measured, at `$0.069` all-in: our deterministic solver beats upstream's shipped
neuro-symbolic baseline by ~4–6× overall on both phrasing registers, and beats an autonomous
tool-using LLM by ~6–20×.

**Next measurement:** raise `n` to 8–24 per register (dollars are negligible at `$0.007`/query; the
cost is ~5 min/query of wall clock at `--workers 1`) so the report's baseline column is not resting on
four queries. Fixing the `BrokenProcessPool` in the `NesyAgent` worker path would make that ~4×
cheaper in wall clock and is the only code work involved.


## 4. Comparability — what may be compared with what

- The four Experiment 2 rows compare **only to each other**, pairwise within a subset: same uid list,
  same `900 s`/query cap, same 4 workers, one repeat, `n=8`.
- The six Experiment 3 rows are a separate `n=4` three-way comparison. They compare only to each
  other within a register, and **not** to the `n=8` Experiment 2 rows — the `n=4` list is a prefix of
  the `n=8` list, so the two overlap and differ (our solver: `40.11` at `n=4` vs `67.71` at `n=8` on
  familiar-100). `n=4` is small enough that only the ordering is meaningful.
- Experiment 1's arms compare **only to their own deterministic arm in the same run**, computed on the
  same query in the same process. The six sets are separate signals and are not poolable — `hf_*`
  sets carry Chinese oracle literals that cannot pass under `en` scoring, `local_released_150` does
  not.
- **Nothing here is comparable to a `full_runs/` or `runs/` row.** Those are whole-run 5 h envelope
  and fixed-`900 s`/query contracts respectively; these are reduced subsets at a per-query cap with
  one repeat.
- The `hf_medium_arms24` split is materialized from the Hugging Face `medium` set and is **not**
  distributionally comparable to `tpc_phase2_familiar_100_val`; that difference is the independent
  variable, not a confound to be averaged away.
- Both parse-fix screens on this branch (this one and
  [`../20260806_parser_phrasing_fix/`](../20260806_parser_phrasing_fix/README.md)) measure the same
  committed code (`b9feb250`) with independently written instruments and agree.

## 5. Ranked by expected value for `v2`

1. **Workstream A, the deterministic phrasing fix — already committed, highest value by a wide
   margin.** Zero LLM calls, zero risk to familiar-100 (verified byte-identical on all 16 budget and
   9 room-type queries), and it lifts the `hf_medium` FPR ceiling from structurally `0.00` to
   `52.67`. The remaining decision on it is the other agent's e2e gate, not this screen.
2. **`extract_fill` + deterministic entity resolution — the one live LLM hypothesis, and it costs
   `$0` to test.** Experiment 1 localized the residual loss to value grounding in a closed
   vocabulary; the 904 cached responses make the LLM half of that measurement free. Highest
   value-per-dollar of anything remaining. Kill criterion is sharp: `matched` on
   `local_released_150` must rise.
3. **`RuleNeSy` external comparison — measured, and the cheapest thing here per unit of report
   value.** `$0.007`/query, `2` LLM calls/query, and it already answers the report's baseline
   question: our solver beats it ~4–6× overall on both registers. Irrelevant to what `v2` *contains*;
   raise `n` from 4 to 8–24 before the report quotes it.
4. **LLM-only planning — closed.** Measured at the floor on both phrasing registers with a
   demonstrably working harness (34–42 turns, zero call failures). Report it as a baseline; do not
   spend on it again.
5. **`TPC_P2_LLM_PARSE` (`audit`) — closed.** Re-measured on the data it was never tested against and
   it is still not worth it. Its RED screen was not a dataset artifact.
6. **Thinking mode / higher reasoning effort — closed on cost, not on quality.** `75 s` per one-line
   tool call and `~$1.1`/query extrapolated at 40 steps. If it is ever revisited, the
   `stop=["\n"]` incompatibility is already fixed in `make_budgeted_llm`, so the next attempt starts
   from a working harness.

The single most useful sentence for the report: **the held-out collapse was a constraint-extraction
failure, and it is fixable deterministically — the language model confirms the diagnosis without
being part of the cure.**

## Files

| path | what |
| --- | --- |
| `exp1_extract/report.json`, `summary.md` | Experiment 1, LLM-first extraction, all 904 released English queries, per-query detail |
| `exp1_extract_fill/report.json`, `summary.md` | the same 904 prompts under the fill-only merge (served from cache, `$0`) |
| `exp1_audit/report.json`, `summary.md` | Experiment 1b, `audit` mode (the existing flag) on the three decisive sets, with retries |
| `exp1_audit_ratelimited/report.json` | the discarded first `audit` attempt: 306 `RateLimitError`s, kept as the record of the silent-fallback trap |
| `parse_fix/probe.json`, `summary.md`, `fix_headroom.json` | independent reproduction of workstream A's parse-gap numbers on this tree |
| `../report_ablations/exp2_llmonly_act_hfmedium8/` | Experiment 2 free-prose arm: per-query telemetry + `summary.json` |
| `../report_ablations/exp2_llmonly_act_familiar8/` | Experiment 2 familiar-100 arm |
| `../report_ablations/exp2_costprobe_thinking/summary.json` | the thinking-mode sizing probe (`UNMEASURED`, and why) |
| `../report_ablations/exp2_costprobe_nothink/summary.json` | the thinking-off sizing probe that set the arm's size |
| `../report_ablations/exp3_upstream_rulenesy_hfmedium4/` | Experiment 3 free-prose arm (n=4, `--workers 1`) |
| `../report_ablations/exp3_upstream_rulenesy_familiar4/` | Experiment 3 familiar-100 arm (n=4) |
| `../report_ablations/exp3_costprobe_rulenesy/`, `exp3_upstream_rulenesy_hfmedium2/` | the sizing attempts, incl. the two `UNMEASURED` worker-death runs |
| `scores/` | raw `eval_tpc.py` output for every scored row (n=8 pairs and n=4 three-way) |

## 6. Reproducing this, and what was cleaned up

Every command is in §1–§3 verbatim. The LLM response cache
(`cache/phase2_llm_parse/Qwen/Qwen3.6-27B/`) is **not** committed, so a re-run of Experiment 1 is a
live `$0.49` rather than free.

Cleaned up after scoring, so no stray split or plan directory can ship in a submission archive: the
materialized `hf_medium_arms24` split (`chinatravel/data/en/hf_medium_arms24/`,
`chinatravel/evaluation/default_splits/hf_medium_arms24*.txt`), the `*_suboptimal.txt` files
`eval_tpc.py` writes, the subset split files the ablation runner materializes, every
`results/exp2_*/` and `results/exp3_*/` plan directory, and `agent_env/runs/exp2_*`. The scores
themselves are preserved in `scores/`, and `scripts/materialize_hf_split.py` regenerates the split
deterministically (HF row order, prefix `--limit`).

**Not done here:** no shipped default changed; `docs/` and `report/` untouched (another agent owns
them); no submission archive was built and nothing was uploaded.
