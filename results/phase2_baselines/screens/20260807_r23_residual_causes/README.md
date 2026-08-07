# R23 — what else separates the held-out set?

**Date** 2026-08-07 · **Branch** `eval/r22-r23-r24` · **git_sha** `dbacc183` · **Contract** screen, not
a `full_runs/`/`runs/` row. Evaluation workstream instrument:
[R23](../../../../docs/tpc_phase2_eval.md#r23--what-else-separates-the-held-out-set-open-static-1-h).
Static only — no query solved, no LLM call, read-only against the released datasets already used by
[`phase2_generalization_probe.py`](../../../../scripts/phase2_generalization_probe.py).

**Question.** Held-out C-LPR (`55.2`) sits below our worst local free-prose measurement. Density or
unseen constraint families were the two leading candidates. This screen quantifies both, plus a third
candidate the exercise turned up along the way.

## Method

[`r23_density_probe.py`](r23_density_probe.py) (committed here, not in `scripts/` — ad hoc, one-off,
same convention as P15's `find_flip2.py`) reuses `phase2_generalization_probe.py`'s and
`parser_vs_oracle.py`'s parse/classify functions read-only. For every released set it computes, per
query, the oracle clause count and which oracle clauses our parser's extracted families could possibly
satisfy (family-presence coverage — an optimistic proxy for C-LPR, since it assumes a covered clause
always passes rather than only *can* pass). Full data: [`density_report.json`](density_report.json).

## 1. Clause-density distributions

| set | n | p50 | p90 | max | ≥10-clause queries |
| --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | 11 | 13 | 13 | 88 (88%) |
| local_released_150 | 150 | 5 | 6 | 6 | 0 (0%) |
| hf_easy | 300 | 5 | 6.9 | 7 | 0 (0%) |
| **hf_medium** | 150 | 8 | 10 | 12 | **27 (18%)** |
| hf_human | 154 | 4 | 6 | 9 | 0 (0%) |
| hf_preference_base50 | 50 | 5 | 6 | 7 | 0 (0%) |

**Finding: the density regime `FPR = 0.0000` implies (`≥ ~10` clauses/query) is almost unobserved
locally.** Outside familiar-100's own numbered-template register, the *only* released queries at that
density are 27 of `hf_medium`'s 150, topping out at 12 clauses. Every other free-prose set never once
reaches double digits. If held-out density exceeds 12 — plausible, since it is unbounded from below
by anything measured here — we have literally zero local examples of it.

## 2. Dense-tail (≥10 clauses) extraction-ceiling proxy — the kill-criterion check

**Read this as a ceiling, never as C-LPR.** It is family-presence coverage on the dense subset, an
optimistic upper bound: a clause counted "covered" only means its family was extracted, not that the
value matched or the plan satisfied it. Real, scored C-LPR is `≤` this number, generally by a
non-trivial margin ([R20](../../../../docs/tpc_phase2_eval.md#r20--does-llm-extraction-convert-recall-into-score-needs-p16)
independently measured that `missing → wrong_value` conversion is real and roughly one-for-one, i.e.
family presence alone regularly fails to convert to a pass).

| set | dense-tail n | clauses | ceiling proxy | ceiling proxy, ASCII-literal only |
| --- | --- | --- | --- | --- |
| familiar_100 (control) | 88 | 1001 | 93.71 | 93.70 |
| **hf_medium** | 27 | 283 | **67.14** | **76.75** |
| all other sets | 0 | — | n/a (no queries this dense) | — |

**Kill criterion does not fire.** The doc's stated test was: if the dense tail of `hf_medium`
approaches `C-LPR ≈ 55`, density alone explains the residual and nothing exotic is needed. Even the
generous *ceiling* sits at `67–77`, well above `55.2` — and the true scored number, being `≤` the
ceiling, would have to fall by `12–22` points from coverage alone to reach the held-out floor. That is
possible (R20's grounding-loss mechanism could plausibly cost that much) but is not established by
this static screen. **Read as: density is a real, quantified contributor — we have almost no local
examples at the density held-out implies — but it is not shown to be sufficient by itself.** A scored
e2e run on `hf_medium`'s 27-query dense tail is the natural next measurement (out of this screen's
static-only scope; flagging it, not running it here).

## 3. Never-produced families — ruled out as a standalone cause

Across all six released sets combined, **every** oracle-required solver-dict family is produced by
our parser on *some* set; **zero** families are unreachable everywhere
(`density_report.json`'s `global.oracle_required_families_never_parsed_anywhere` is `[]` — built from
the real oracle-side family sets via `_families()`, independent of any clause-classification rule, so
this is the load-bearing check). The companion field
`global.known_families_never_parsed_anywhere` is also `[]` but is the weaker of the two: it is scoped
to `CLAUSE_KIND_RULES`'s covering-tuple vocabulary, which is not the full solver-dict family list (see
`r23_density_probe.py`'s comment on `ALL_KNOWN_FAMILIES`) — its emptiness corroborates the finding
without carrying it. "Constraint families we have no local example of" is not supported as a cause —
locally, our extractor's vocabulary is exhaustive relative to every released oracle. (This cannot rule
out the held-out set containing something no released set has either — it only shows the hypothesis
isn't *needed* to explain any local gap.)

## 4. A cleaner finding the exercise turned up: total family blackout on free prose

The per-set (not global) version of the same check found something sharper than "no family is
missing everywhere": **`cuisine_preference`/`restaurant_type` extraction is 100% uncovered on every
HF free-prose set, while ~100% covered on the two locally-phrased sets:**

| set | `restaurant_type`-kind clauses | uncovered | coverage |
| --- | --- | --- | --- |
| familiar_100 (control) | 67 | 0 | 100.0% |
| local_released_150 | 22 | 1 | 95.5% |
| hf_easy | 30 | **30** | **0.0%** |
| hf_medium | 33 | **33** | **0.0%** |
| hf_human | 27 | **27** | **0.0%** |
| hf_preference_base50 | 7 | **7** | **0.0%** |

Not a missing family (§3 already shows `cuisine_preference` is extracted successfully elsewhere) and
not a density effect (fires on sets with as few as 4–5 clauses/query) — this is a phrasing-conditional
**total** precision failure of one specific extractor pattern, complete and consistent across four
independent sets. It is the single most cleanly diagnosed residual-cause candidate this screen found:
`97` clauses uncovered out of `3790` oracle clauses across the four HF sets — a fixed **`2.56` point**
ceiling cost on their combined C-LPR, fully explained rather than attributed to an unmeasured
"something."

## Ranked, quantified candidate list (acceptance criterion)

| rank | cause | status | quantified cost | confidence |
| --- | --- | --- | --- | --- |
| 1 | `cuisine_preference`/`restaurant_type` total blackout on non-templated phrasing | **confirmed, fully explained** | fixed `2.56` C-LPR points on combined HF sets (`97/3790` clauses); query-level FPR cost not computed here (all-or-nothing gating means it is `≥` the clause share) | high — complete, consistent 0% across 4 independent sets |
| 2 | unmeasured density (held-out implied `≥10`, plausibly `>12`) | **plausible, not proven sufficient** | dense-tail ceiling proxy `67–77` vs held-out `55.2` — a `12–22`-point gap the ceiling alone doesn't close | medium — real effect, magnitude needs a scored run |
| 3 | value-grounding loss at the family-presence layer (R20's mechanism) | **independently measured elsewhere, not re-derived here** | consistent with closing rank 2's `12–22`-point gap, not quantified by this static screen | medium — plausible mechanism, no new number here |
| 4 | constraint families with zero local examples | **ruled out** | `0` families unreachable across all 6 sets | high |

**Kill criterion: did not fire.** Action per the doc's own branch: continue — re-tune against dense
queries is not shown to be sufficient alone; a scored confirmation on `hf_medium`'s dense tail plus a
fix for the `cuisine_preference`/`restaurant_type` free-prose blackout (rank 1, cheapest and most
certain) are both better next moves than assuming density closes the gap.

## Files

- `r23_density_probe.py` — the ad hoc script, reproducible: `HF_HUB_OFFLINE=1 .venv/bin/python
  r23_density_probe.py --out density_report.json` (run from this directory; it locates the repo root
  from its own path).
- `density_report.json` — full per-set histograms, dense-tail proxies, and per-set/global family
  lists this README summarizes.
