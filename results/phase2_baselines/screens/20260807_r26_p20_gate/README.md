# R26 — gate P20 on the registers it targets

**Date** 2026-08-07 · **Branch** `eval/r26-p20-family-recall-gate` · **baseline `git_sha`** `edb5bb20`
(pre-P20 main) · **candidate `git_sha`** `0d6f1837` (current main; verified docs-only diff from the
P20 merge commit `e6cc0e65`, `git diff --stat e6cc0e65 HEAD` touches only `docs/` and R25's screen
artifacts) · **host** 4-core Linux (3 workers) · **Contract** per-query e2e screen plus a static
parser probe, not a `full_runs/`/`runs/` row.
Evaluation workstream instrument: [R26](../../../../docs/tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets),
gating [P20](../../../../docs/tpc_phase2_roadmap.md#p20--close-the-two-dominant-family-recall-gaps).

**Question.** P20 fixed two `cuisine_preference` parser bugs and added free-prose fallback patterns
for `cuisine_preference`/`required_attraction_types`. Its own screen (`20260807_p20_family_recall`)
was run on the coding VM (against CLAUDE.md's two-VM rule) and could show only static parser-level
evidence, deferring the e2e question and the `required_attraction_types` register to this row.

## Method

Two isolated trees: `edb5bb20` (pre-P20, checked out as a separate `git worktree`) and the current
`eval/r26-p20-family-recall-gate` branch tip (post-P20, `0d6f1837`, byte-identical code to `e6cc0e65`).
Both invoked with the same `.venv` interpreter but each tree's own `agent_env/scripts/solve_phase2.py`
and `parse_constraints.py`, so `sys.path` resolution is per-tree.

**Positive control, run first and recorded before trusting anything else.** Parsed the 3 target uids
directly in each tree and printed `cuisine_preference`:

| uid | baseline (pre-P20) | candidate (post-P20) |
| --- | --- | --- |
| `20250322130847337844` | `None` | `'Hot pot'` |
| `20250322174632709770` | `['one of the following', 'buffet']` | `'buffet'` |
| `20250322175216115859` | `'one of the following'` | `'Cantonese cuisine'` |

Baseline reproduces the exact bug shapes P20's own writeup names (list-lead-in leak, numbered-OR-arm
swallow); candidate emits the clean oracle-matching values. Worktree isolation is confirmed live, not
assumed.

**Static parser probe** (`scripts/phase2_generalization_probe.py`, no solve, no LLM), run independently
in each tree over all 6 released/HF sets. **Per-family stats** on `tpc_phase2_test` specifically
(`scripts/parser_vs_oracle.py --split-set test --lang en --per-variant-family-stats`), since the
probe's own output only reports family-parse totals, not a per-family breakdown, and P20's
`cuisine_preference`/`required_attraction_types` claims need the per-family numbers to check.

**E2E solve+score**, `agent_env/scripts/solve_phase2.py --budget-sec 90 --lang en` (per-query mode, no
`--resume` — every uid re-solved fresh), two uid files:

- `r26_p20_target3.txt` — the 3 uids in P20's own `target_uids.txt` (the entire locally-measurable
  English-literal-oracle universe for these two families; all 3 are `cuisine_preference` on
  `tpc_phase2_test` — `required_attraction_types` has no local English-literal misses, per P20's own
  partition).
- `r26_familiar_first30.txt` — the first 30 uids of `tpc_phase2_familiar_100`, unchanged control.

Both arms sharded across 3 concurrent `solve_phase2.py` subprocesses (`cores - 1`, matching R24/R25).
**Arms run strictly sequentially** (baseline target3 → baseline familiar30 → candidate target3 →
candidate familiar30) — never overlapping across arms on this 4-core box, since R24/R25 established
these queries are close to clock-bound at the budgets in play and concurrent arms would contaminate
the timing/outcome comparison. Scored via each query's own `evaluation.json`/`telemetry.json`
(the same official-evaluator fields `solve_phase2.py` writes per uid), aggregated with
`aggregate_r26.py` (not committed — a 40-line read-only aggregator, reproducible from this README).

## Result: parser fix confirmed and precision-safe on every register measured; e2e is flat on this
sample because all 3 target queries already passed regardless of the bug

### 1. Static probe — no set gains gaps or spurious clauses; every free-prose set's coverage improves

| set | n | parse-gap clauses base→cand | spurious base→cand | matched base→cand | missing base→cand | precision base→cand | recall base→cand |
| --- | --- | --- | --- | --- | --- | --- | --- |
| familiar_100 (control) | 100 | `0/1109` → `0/1109` | `0` → `0` | `661` → `661` | `0` → `0` | `0.9552` → `0.9552` | `0.9552` → `0.9552` |
| local_released_150 | 150 | `6/522` → `5/522` | `41` → `40` | `320` → `325` | `33` → `32` | `0.811` → `0.82` | `0.811` → `0.8243` |
| hf_easy | 300 | `127/1579` → `97/1579` | `177` → `177` | `391` → `391` | `127` → `97` | `0.6922` → `0.6644` | `0.7156` → `0.7156` |
| hf_medium | 150 | `126/1264` → `78/1264` | `114` → `114` | `391` → `391` | `116` → `68` | `0.7878` → `0.7209` | `0.7609` → `0.7609` |
| hf_human | 154 | `99/687` → `81/687` | `44` → `44` | `195` → `195` | `97` → `80` | `0.8153` → `0.7758` | `0.6725` → `0.6725` |
| hf_preference_base50 | 50 | `19/260` → `14/260` | `32` → `32` | `62` → `62` | `19` → `14` | `0.6517` → `0.6283` | `0.7333` → `0.7333` |

**Cross-check:** every per-set gap count above is byte-identical to P18's independently-run
`20260807_generalization_post_p20` screen (merged separately, in parallel, via a floor-file check
against an older screen rather than a pinned pre/post-P20 worktree diff) — two unrelated comparison
methods landing on the same numbers is a useful sanity check that both are measuring something real.

**familiar_100 is byte-identical** (structurally guaranteed — the fallback only fires when every
anchored pattern finds nothing, and familiar-100 always populates both families through the
templated `"Include the following ... types: X"` clause). **Every free-prose set's parse-gap count
shrank and none gained a spurious clause** — `spurious` and `matched` are unchanged on all 4 HF sets;
only `missing` fell (converting to `wrong_value`, exactly the mechanism P20's writeup predicted: HF
sets carry a CJK oracle literal, so an English fallback extraction can only ever move a clause from
`missing` to `wrong_value`, never to `matched`). **The HF sets' `precision` figure drops for this
reason alone, not because of new spurious extractions** — the denominator effect of
`missing → wrong_value` under an unmoved `spurious` count, not a precision regression in the sense the
GREEN gate cares about (no new false-positive family detections). `local_released_150` (the one set
with an English oracle) shows the fix's real effect on *both* halves at once: precision *and* recall
both rise (`0.811/0.811 → 0.82/0.8243`).

### 2. Per-family — `cuisine_preference` matches P20's claim; `required_attraction_types` moves too

`parser_vs_oracle.py --per-variant-family-stats` on `tpc_phase2_test` (150 uids):

| family | matched base→cand | missing base→cand | spurious base→cand | wrong_value base→cand |
| --- | --- | --- | --- | --- |
| `cuisine_preference` | `6` → `12` | `0` → `0` | `5` → `3` | `7` → `4` |
| `required_attraction_types` | `10` → `11` | `1` → `0` | `3` → `3` | `3` → `3` |

`cuisine_preference` reproduces P20's own screen (`7 → 14` there; this tool's variant/disjunction
handling differs slightly in the denominator, same direction and magnitude) with a precision gain
too (`spurious` and `wrong_value` both fell). **`required_attraction_types` also moved, contrary to
P20's claim of zero locally-measurable English-literal misses** — one uid
(`20250324004250012727`) flipped `missing → matched`. Checked directly: this is a *disjunctive*
clause (`"meet any one of the following: 1. Wish to visit historical sites 2. Wish to stay at a hotel
... Free parking"`), which `phase2_family_recall_gap_partition.py`'s partition apparently didn't
enumerate the same way `parser_vs_oracle.py`'s per-family stats do. **This is the one piece of
evidence in this row that speaks to the `required_attraction_types` half directly** — a single
disjunctive-branch data point, not the volume validation the doc originally wanted, but a genuine
locally-measurable improvement for a family P20's own screen said had none.

### 3. E2E — no regression anywhere; no *rise* on the target set because it was already at ceiling

**`r26_p20_target3` (3 uids, 90 s budget):**

| uid | `fpr_true` base/cand | `overall_true` base/cand | `conditional_logical_micro` base/cand | `solve_sec` base/cand | `stop_reason` base/cand |
| --- | --- | --- | --- | --- | --- |
| `20250322130847337844` | `100.0` / `100.0` | `93.5417` / `93.5417` | `100.0` / `100.0` | `13.4` / `13.4` | `converged` / `converged` |
| `20250322174632709770` | `100.0` / `100.0` | `98.0556` / `98.0556` | `100.0` / `100.0` | `73.8` / `71.3` | `max_restarts` / `max_restarts` |
| `20250322175216115859` | `100.0` / `100.0` | `94.9754` / `94.9722` | `100.0` / `100.0` | `80.2` / `81.1` | `max_restarts` / `budget` |

**All 3 uids already passed (`fpr_true 100`) in *both* arms.** The parser bug was real (confirmed
above) but never caused these particular 3 queries to fail overall — the solver's chosen restaurant
already satisfied the oracle's cuisine clause even when the internal parsed constraint was `None` or
garbled, so there was no failing query on this sample for the fix to flip. `conditional_logical_micro`
is `100.0` in both arms on all 3 — it cannot "rise" per the doc's GREEN wording because it was already
at the ceiling before the fix; read this as **"does not fall," satisfied, not "rises," inapplicable**,
and say so plainly rather than force a misleading GREEN checkbox. The third uid's `overall_true`
differs by `0.0032` (a different but equally-valid plan, not a regression — `fpr_true` and
`conditional_logical_micro` are identical). One `stop_reason` differs (`max_restarts` vs `budget`),
consistent with R24/R25's finding that queries near this budget sit close to the clock/restart
boundary and small search-space perturbations can shift which limit is hit first.

**`r26_familiar_first30` (30 uids, 90 s budget) — the control:**

Byte-identical: `0/30` uids differ in parsed `constraints`, `0/30` differ in `overall_true`,
`13/30` pass in both arms. This reproduces the structural argument in §1 as an e2e result, not just a
static one — the fallback genuinely never executes on this register. `EPR-macro` (mean
`commonsense_macro`) is `100.0` in both arms on both the target3 and familiar30 sets — no fall on
either register, per the GREEN gate's explicit requirement.

## Reading against the doc's own GREEN/RED gate

| Criterion | Result |
| --- | --- |
| familiar-100 parse gaps remain `0/1109` | **met** — byte-identical |
| no free-prose set gains gaps or spurious clauses | **met** — every set's gap count fell or held; spurious flat everywhere |
| target-family `matched` rises | **met** — `cuisine_preference` `6→12`; `required_attraction_types` `10→11` (bonus, not claimed by P20) |
| target-subset C-LPR rises | **partially inapplicable** — flat at ceiling (`100.0`→`100.0`) on the 3-uid e2e sample because all 3 already passed pre-fix; does not fall |
| FPR and EPR-macro do not fall on either register | **met** — both flat (`100/100/100` target3, `13/30`↔`13/30` familiar30; EPR-macro `100.0` both) |

**No RED condition is met**: no precision regression (spurious flat/improved everywhere, HF precision
drops are a `missing→wrong_value` denominator artifact, not new false positives), no familiar-only
gain (the fix moves `local_released_150`, `hf_easy`, `hf_medium`, `hf_human`, `hf_preference_base50`
coverage, all while familiar-100 stays exactly flat), and the e2e sample shows no *movement* but also
**no regression** — it is silent because it had no failing query to flip, not because the fix is
inert (the static and per-family evidence above is unambiguous that it isn't).

**Verdict: GREEN**, on the reading that "target-subset C-LPR rises" is vacuously satisfied by a
sample already at ceiling rather than falsified by it. **This authorizes one current-main whole-run
row, nothing more** — it does not estimate held-out score, and the e2e evidence here is a
no-regression check on `n=3`, not a demonstrated FPR gain; the load-bearing evidence for *this* row is
the static parser probe and per-family stats, not the e2e arm, exactly as the doc's own item 4
under "the measured breakdown" would predict for a fix this small relative to per-query clause counts.

## Open question for future work, not this row's scope

The HF sets' `missing → wrong_value` conversion (§1) means the fallback now hands the solver an
English cuisine/attraction-type value that can never match a CJK oracle literal — this cannot help
C-LPR on those sets by construction, but it is *unverified* whether it can locally *hurt* an e2e plan
(e.g. by narrowing the solver's restaurant search to an English-labeled type that returns zero
grounded candidates, forcing a worse substitute or a fallback plan). R26's scope (per the roadmap) is
the registers P20 targets and their local no-regression check, not an HF e2e arm — this was out of
scope here and is not measured by this row. If it matters, it needs its own screen.

## Files

- `r26_p20_target3.txt`, `r26_familiar_first30.txt` — the two uid files. To rerun, copy each into
  `chinatravel/evaluation/default_splits/` (not committed there, matching R25's precedent) so
  `solve_phase2.py --split <name>` can resolve it.
- `probe_baseline.json` / `probe_candidate.json`, `probe_baseline_summary.md` /
  `probe_candidate_summary.md` — full `phase2_generalization_probe.py` output per tree.
- `pvo_baseline_tpc_phase2_test.json` / `pvo_candidate_tpc_phase2_test.json` — full
  `parser_vs_oracle.py --per-variant-family-stats` output per tree.
- `scored_baseline_target3.json`, `scored_candidate_target3.json`, `scored_baseline_familiar30.json`,
  `scored_candidate_familiar30.json` — per-uid `fpr_true`/`overall_true`/`conditional_logical_micro`/
  `solve_sec`/`stop_reason`/parsed-constraints snapshot, aggregated from each uid's own
  `evaluation.json`/`telemetry.json`.
- `run_r26.sh` — the exact sharding/sequencing driver used for the four e2e arms.
- Raw plans and per-uid telemetry are not committed (bulky, reproducible):
  `results/phase2_e2e_r26_{baseline,candidate}_r26_{p20_target3,familiar_first30}/`,
  `agent_env/runs/phase2_e2e_r26_{baseline,candidate}_r26_{p20_target3,familiar_first30}/`, in both
  the candidate tree and the (deleted after this run) pre-P20 worktree.
