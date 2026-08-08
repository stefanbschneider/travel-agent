# Phase 2 evaluation roadmap

**One document for both halves of evaluation: what a measurement is allowed to prove, and what to
run next.** Generated rows live in [`results/phase2_baselines/`](../results/phase2_baselines/); this
document defines their interpretation. What to *implement* is the
[implementation roadmap](tpc_phase2_roadmap.md); how the system is built is the
[design doc](tpc_phase2_design.md). Read [CLAUDE.md](../CLAUDE.md) for the invariants.

## The one fact that reorganizes this document

**The organizers returned `v1`'s held-out score on 2026-08-06: `33.2473`, and on 2026-08-07 the
Phase 2 leaderboard published the seven metrics behind it.** The same code scores `64.17` on the
released familiar-100 split ([R17](#the-closed-queue-r1r19)). **Local rows over-predicted held-out
performance by a factor of about two**, and every ranking decision in this project was made on the
local number.

This doc previously predicted `58–68` at `±2σ` for exactly this measurement. That prediction was
wrong, and the [post-mortem](#the-falsified-prediction--a-post-mortem) is the most instructive section
here.

### The measured breakdown

Recorded as [`heldout/20260807_v1_leaderboard.json`](../results/phase2_baselines/heldout/20260807_v1_leaderboard.json);
analysis reproducible with `scripts/analyze_heldout_breakdown.py`.

| metric | weight | held-out `v1` | familiar-100 (R17) | delta |
| --- | --- | --- | --- | --- |
| EPR-micro | 0.10 | `99.4815` | `99.6667` | **`−0.19`** |
| EPR-macro | 0.10 | `95.0000` | `98.0000` | `−3.00` |
| C-LPR | 0.25 | **`55.1966`** | `90.0812` | **`−34.88`** |
| **FPR** | **0.40** | **`0.0000`** | `44.0000` | **`−44.00`** |
| DAV / ATT / DDR | 0.05 ea. | `0` / `0` / `0` | `26.04` / `34.48` / `25.19` | — |
| **overall** | | **`33.2473`** | `64.1725` | `−30.93` |

The breakdown reproduces the aggregate exactly (`delta 0.000000`), so there is nothing to suspect
about the scoring itself. Four readings follow, and they change what is worth building.

**1. Grounding generalized. Constraint satisfaction did not.** EPR-micro is essentially unchanged
(`−0.19`): every fact we emit still resolves in the environment, on queries we have never seen. The
entire collapse is in *knowing what to satisfy*. That is the constraint-extraction diagnosis, now
confirmed on the axis that matters — and it **definitively kills the crashed-run hypothesis**, because
empty or fallback plans cannot score EPR-micro `99.5`.

**2. `FPR = 0.0000` needs no second bug to explain it.** Do not go looking
for a second failure. C-LPR is conditional on commonsense, so the per-clause pass rate on a scored
plan is `55.1966 / 95.0 = 58.1 %`. A query passes only if *every* clause passes, so at familiar-100's
`11.09` clauses per query the model predicts `FPR ≈ 0.25` on the 0–100 scale — a quarter of one query
in a hundred. **An expectation that far below one query makes *observing* exactly zero the single most
likely outcome** (`≈ 78 %` at `n = 100`), and zero becomes more likely than not at any density above
`~9.2` clauses per query. The same model predicts `39.3` on familiar-100 against a measured `44.0`, so
it is calibrated and slightly conservative. Held-out density, query count and within-query correlation
are all unknown and all move this estimate, so read it as an order-of-magnitude consistency check
rather than a prediction.

**Amended 2026-08-07 — a second, simpler mechanism reaches `FPR = 0` without the independence
assumption, and it has a fix.** In `23–50 %` of free-prose queries our own parser emits a
required-POI-name constraint that resolves to nothing in the target city's catalog
(`scripts/phase2_unsatisfiable_names_probe.py`; `42 %` on HF `easy`, `35 %` on `medium`, `23 %` on
`human`, `50 %` on `preference_base50`, against `7 %` on familiar-100). The solver can only place
catalog POIs, so such a query has **no feasible point**: it is pinned at `FPR = 0` and at zero on all
three preference terms at any budget. That is consistent with the whole published breakdown — an
invented *constraint* never becomes an invented *fact*, so `EPR-micro 99.48` is untouched, and the
query still earns its other clauses, so `C-LPR 55.20` is untouched. The two explanations are not
rivals, but they imply different work: the clause-product model says grind up the per-clause rate,
while this one says a third of the split may be recoverable by deleting constraints we should never
have emitted. See [P22](tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints)
and [R30](#r30--does-dropping-unsatisfiable-names-flip-queries).

**3. `55 %` of the total weight currently yields exactly zero.** FPR is `0.40` on its own and gates all
three preference terms (`0.15`), since a failing query scores `0` on each. Everything in our `33.2473`
comes from `0.45` of the weight.

**4. The upside is non-linear, and this is the most decision-relevant fact here.** Because FPR is
multiplicative in the per-clause rate `p`, it stays flat until `p ≈ 0.75` and then climbs steeply:

| `p` | 0.581 (today) | 0.70 | 0.75 | 0.80 | 0.85 | 0.90 |
| --- | --- | --- | --- | --- | --- | --- |
| C-LPR | `55.2` | `66.5` | `71.3` | `76.0` | `80.8` | `85.5` |
| FPR | `0.0` | `2.1` | `4.6` | `9.4` | `18.5` | `34.8` |
| overall | `33.2` | `37.1` | `39.6` | `43.1` | `48.8` | `58.2` |

So **a partial coverage fix earns only its C-LPR share at weight `0.25`; a fix that pushes `p` past
about `0.8` also unlocks the `0.55` of weight that is currently dead.** Aim for the threshold, not for
an increment. Priced against the phrasing fix's measured effect on free prose (it removed `69 %` of
failing English-literal clauses), the same reduction transferring to the held-out set would be worth
roughly `+18`; a third of it, roughly `+5`.

**Treat that projection as a sensitivity tool, not a prediction.** It has one fitted parameter
calibrated at one point, assumes clause independence beyond that, and assumes held-out clause density
equals familiar-100's — unknown, though `FPR = 0.0000` itself implies `≥ ~10` clauses per query.

**5. One cheap, phrasing-independent component.** EPR-macro `95.0` means `5 %` of plans fail
commonsense and therefore also score `0` on C-LPR. Fixing all of them is worth at most `1.23` overall.
Small, but it is the only piece with no phrasing dependency at all.

### What the gap is made of

**[The generalization probe](../results/phase2_baselines/screens/20260806_generalization_probe/README.md)**
found the largest identified cause. Our deterministic constraint extraction has **zero** clause-level
gaps on familiar-100 — the numbered-template split it was built against — and **12–29 %** on every
differently-phrased released set. familiar-100 is the only set it is clean on.

| set | n | oracle clauses/query | numbered "Requirements:" list | parse F1 | parse-gap clauses |
| --- | --- | --- | --- | --- | --- |
| `tpc_phase2_familiar_100` (control) | 100 | 11.09 | **100 %** | **0.955** | **0 / 1109 (0 %)** |
| `tpc_phase2_test` (local released 150) | 150 | 3.48 | 15 % | 0.791 | 17 / 522 (3 %) |
| HF `easy` | 300 | 5.26 | 0 % | 0.625 | 219 / 1579 (14 %) |
| HF `medium` | 150 | 8.43 | 0 % | **0.417** | **363 / 1264 (29 %)** |
| HF `human` | 154 | 4.46 | 0 % | 0.656 | 146 / 687 (21 %) |

Reproduced end-to-end at matched budget, workers and `n`: free-prose queries of comparable constraint
density score `64.57 → 41.62` overall, with `MicEPR`/`MacEPR` staying at `100.0`. The collapse is
entirely in the logical terms — the same signature the leaderboard shows.

**But the held-out set is harder than any register we hold locally.** Its C-LPR (`55.2`) is below even
our *pre-fix* free-prose measurement (`72.5` raw, `78.4` on English-literal clauses). So phrasing
brittleness is a real and measured cause, and it is **not the only one** — something beyond it
separates the held-out set from HF `medium`, most plausibly higher constraint density or families we
have no local example of.

**Note what this says about `tpc_phase2_test`.** The split scoring `90.56` ([R18](#the-closed-queue-r1r19))
shares familiar-100's template *and* carries a third of its constraints. It was never evidence of
generalization, and it should never again be cited as a second confirmation set.

**An amplifier worth understanding, because it changes scheduling too.** The shipped scheduler is
triage → repair *only what fails* → polish, and "fails" is decided by `evaluate_parsed_constraints`
against **our parsed** constraints. A constraint we never extracted cannot fail, so the query is
classified as satisfied and promoted to polish. Observed on the free-prose run: it self-reported
`FPR 86.67` against a real `6.67` and stopped with `1546 s` of `1800 s` **unspent**. Under parse gaps
the envelope is not merely insufficient — it is spent on the wrong queries and then partly not spent.

**How much is accounted for.** Phrasing brittleness is measured and is the largest identified *recall*
cause, but the leaderboard shows it is **not sufficient**: held-out C-LPR (`55.2`) sits below our
*pre-fix* free-prose number, so a second factor of comparable size is still unidentified.
**Update 2026-08-07: a second factor of comparable size is now measured, and it is precision, not
recall.** On free prose we emit a required-POI name that resolves to nothing in `23–50 %` of queries,
and `117` `intercity_mode` clauses against **zero** oracle instances across all four HF sets. The
first class is provably unsatisfiable and pins those queries at `FPR = 0`; the second constrains
arrival and departure times, which is the axis
[R25](#r25--separate-the-cp-restart-and-outer-budget-limits) found binding on failing queries. See
[roadmap §6](tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves).
Remaining unmeasured candidates, in order: higher constraint density per query (which `FPR = 0.0000`
independently implies is `≥ ~10`), and a *partial* infrastructure failure. A total infrastructure
failure is excluded outright by EPR-micro `99.48`; constraint families we have no local example of were
ruled out by [R23](#r23--what-else-separates-the-held-out-set-open-static-1-h). The standing uncertainty
is that the organizers describe the held-out set as same-distribution as familiar-100; the phrasing and
precision evidence says the two do not behave alike, whatever the intent.

### The full field, and what the race is actually about *(2026-08-08)*

**Four more teams appeared on the board on 2026-08-08 and the picture is much more actionable than a
single score was.** Recorded as
[`heldout/20260808_leaderboard_5teams.json`](../results/phase2_baselines/heldout/20260808_leaderboard_5teams.json).

| rank | team | `v1` | `v2` | EPR-mic | EPR-mac | C-LPR | FPR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `fl***ai` | `36.4060` | — | `99.6429` | `95.00` | **`67.7669`** | `0.0000` |
| 2 | `Ha***li` | `35.4768` | — | `99.7778` | `94.00` | `64.3961` | `0.0000` |
| **3** | **`fa***an` (us)** | **`33.2473`** | — | `99.4815` | `95.00` | `55.1966` | `0.0000` |
| 4 | `An***ns` | `32.6028` | — | `99.3571` | `91.00` | `52.6685` | `1.0000` |
| 5 | `LL***PC` | `21.0166` | — | `91.1852` | `43.00` | `28.7921` | `0.0000` |

Three readings, and they sharpen every priority below.

**1. The entire gap to first place is C-LPR.** `67.7669 − 55.1966 = 12.5703` clause points at weight
`0.25` is `3.1426` of the `3.1587` total gap — `99.5 %` of it. Our grounding is within `0.16` of rank 1's
and our commonsense is *tied* with it. There is nothing else to fix at the top of the board:
**+4.0 C-LPR = +1.0 overall**, and `+12.6` C-LPR is first place at today's scores.

**2. `FPR = 0` is the whole field, not our bug.** Four of five teams score exactly `0.0000` and the
fifth scores `1.0000`; every preference term is `0.0000` for all five. This is the strongest available
external confirmation of [reading 2](#the-measured-breakdown) — the held-out set is dense enough that
no entrant reliably satisfies *every* clause of a query. Stop treating our own `FPR = 0` as evidence of
a defect unique to us.

**3. `55 %` of the weight is dead for everyone, which makes the non-linearity a *competitive* lever.**
FPR (`0.40`) plus preferences (`0.15`) currently pay nobody. The first team whose per-clause rate crosses
`~0.8` collects that weight in one step; `FPR 5.0` alone is `+2.0` overall. So an incremental C-LPR gain
is worth its `0.25` share (useful — the board is `3.16` wide), and a threshold-crossing gain is worth
several times more.

And one thing the board does *not* say: every rival still holds an unused `v2` slot, so the bar is not
`36.4060` but `36.4060` plus whatever they gain.

### What has landed since `v1`, measured *(2026-08-08)*

**`v1` predates the entire phrasing-and-precision program**, and until 2026-08-08 no committed
measurement said what that was worth, because every row we hold is on familiar-100 — the one register
where all of it is structurally inert. `v1` was built from `be196d00` (2026-08-05); the phrasing fix
landed 2026-08-06, and P15, P20, P22, P23, P24, P17(a), P4, P6 and P25 after it.

[R32](#r32--what-landed-since-v1-measured-on-free-prose) closes that gap on the free-prose register,
now that [R31](#r31--the-first-real-free-prose-fpr-gate) has removed the oracle-literal FPR ceiling
that made such a measurement unreadable: on `hf_medium` (n=150, paired, same host, translated oracle)
**C-LPR `75.55 → 88.37` and FPR `10.67 → 44.00`, `overall 44.41 → 64.28`** — `191` clauses flip
fail→pass against `29` lost, net `+162` of `1264`. Read against the board above, the failing-clause
mass drops by `52 %` on the register whose failure signature matches the held-out one. That does not
predict a held-out number, and this document will not pretend otherwise; it does mean **`v2` is
carrying a large, measured improvement in exactly the metric the competition is being decided on.**

### Submission policy (owner's instruction, 2026-08-06; re-confirmed 2026-08-08)

**Do not upload `v2`, and never upload automatically.** The owner uploads manually, shortly before the
deadline (2026-08-10, 24:00 Beijing Time), and only with a substantial measured improvement.

The 2026-08-07 leaderboard showed **ours as the only submission**; the
[2026-08-08 read](#the-full-field-and-what-the-race-is-actually-about-2026-08-08) shows five teams and
puts us third, `3.16` behind first. Neither changes this policy. Three facts bear on the decision when
it is made: `v1`'s score stands regardless, since the higher of two successful versions wins — so a
worse `v2` costs only the slot; by [reading 4](#the-measured-breakdown) an *incremental* coverage fix is
worth only its C-LPR share, while one that pushes the per-clause rate past `~0.8` is worth several
times more; and on a board `3.16` wide, an increment is no longer negligible — `+4.0` C-LPR is `+1.0`
overall and the whole gap to first place is `12.6` C-LPR.

## Run this next

Priority order. Every item states its own acceptance criterion so it can be executed without
re-deriving the argument.

**Current state, 2026-08-08 (seventh revision).** `main`'s tip carries P16, **P18**, P19, **P20**,
**P22**, **P23**, **P24**, **P6**, R25, **R26**, **R27**, **R28**, **R29**, **R30** and **R31**. P16 lands useful grounding machinery but
is **not promoted** (same-tree parse arm `matched 311 < 320` deterministic, `hf_medium` e2e flat). P19
closed the residual diagnosis. R24 changed only the outer timeout; **R25 is closed** — both internal
limits were tested directly and neither flips a query, so do not schedule the combined
`CP=300/restarts=4000` 30-uid arm. **R26 is closed GREEN**: P20's parser fix is precision-safe on every
register measured, it also moves one `required_attraction_types` clause locally (a disjunctive branch
P20's own partition script didn't enumerate), and its flat 3-uid e2e arm is a power problem — all 3
queries already passed regardless of the bug — not evidence the fix is inert. P18's tripwire is now an
executable gate inside `pytest tests/phase2`, with two precision conditions still to add (see
[R22](#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)). **R28 is now
closed too**: the current-`main` whole-run row is byte-identical to R19 on all seven metrics and on
all 100 plan files — the drift is closed, and this row is now the baseline for every later gate.
**R29 is closed GREEN**, and its real finding is a doc-framing correction, not a new promotion: the
"default-off" flag it measured was already forced on for every real harness run (including R28 and
`v1`) since `b53a0747` (2026-07-13) — see item 2 below. **R30 is closed with a negative result**: 0/103
target queries flip to fully passing, and 2 regress on `local_released_150` (one a genuine
salvage-before-drop gap, one search perturbation) — see item 4 below.
`TPC_P2_DROP_UNSATISFIABLE_NAMES` stays library-default-off; nothing promotes. **R31 is closed
GREEN**: with the P23 oracle-literal map applied, `hf_medium`'s FPR moves `20.67 → 44.67` and C-LPR
moves `82.44 → 88.29`, `74` clauses flip fail→pass and, checked clause-by-clause across all 150 uids,
**zero flip pass→fail** — see item 6 below. This does not promote a solver default; it recalibrates
the measurement. **R30's own salvage-before-drop follow-up landed and was e2e-reconfirmed 2026-08-08
too**: the genuine loss it found now passes in both arms, the unrelated loss is unchanged, no new loss
appears anywhere — still `0/103` fail→pass so the flag stays off, but the regression risk is now
measured closed, not just claimed closed — see item 4 below.

**R27 is now closed too** (implementation workstream, same PR that landed P6): the roadmap's own
cheap falsification screen (`n=10`, live DeepInfra, `temperature=0`) came back **RED** — `0/10`
accepted flips caused by the repair loop, safety held throughout — see item 7 below.
`TPC_P2_LLM_REPAIR_LOOP` stays library-default-off.

**R31 is closed, R30's follow-up is reconfirmed, R27 is closed RED, and the evaluation queue is now
fully drained: the only open items are R21 (parked) and R20 (HOLD), neither actionable right now.**

1. **A whole-run row now exists on the current `main`.** [R28](#r28--a-whole-run-row-on-the-current-main)
   (`20260807T152009Z`, `git_sha aed4363e`) replaces R19 `ae0bd319` as the baseline every later
   candidate is gated against — same host, same config, byte-identical score. "Promote" is available
   again.
2. **R29 is closed GREEN, and it found something bigger than the question it set out to answer:**
   `TPC_P2_ENTITY_RESOLUTION` is *not* off-by-default on the harness path — `solve_phase2.py`'s
   `resolve_llm_client_and_flags()` has force-defaulted it on since `b53a0747` (2026-07-13), an
   ancestor of both R28 (`aed4363e`) and the `v1` submission build (`be196d00`). **R28's baseline and
   the held-out `v1` score already ran with this flag on** — confirmed directly against R28's own
   on-disk telemetry, not just by reading code. The isolated e2e measurement itself is still real and
   useful: familiar-100 FPR `45.00 → 50.00`, `overall_true` `64.83 → 67.53`, two more queries fully
   pass, zero LLM calls confirmed from telemetry (n=40 screen); free prose (`hf_medium`, n=30) is
   NEUTRAL — all 30 plans byte-identical between arms, matching the static probe's prediction that the
   English-literal-value fix has nothing to convert on a Chinese-oracle-literal register. See
   [R29](#r29--does-deterministic-entity-resolution-convert-end-to-end) for the full result and the
   doc-framing correction it requires.
3. **Every free-prose FPR this document reports was read against the wrong denominator.** The HF
   splits' oracle literals are Chinese while their query text is English, so under `--lang en`
   `59–61 %` of their queries contain a clause no solver can satisfy. Their FPR ceilings are
   `38.67–46.0`. It is also why the *e2e* half of R26's out-of-scope open question cannot be answered
   on an HF split today — the static half is answered in
   [R26's addendum](#r26--gate-p20-on-the-registers-it-targets). See
   [the corrected dataset boundary](#3-hugging-face-chinatravel) and
   [R31](#r31--the-first-real-free-prose-fpr-gate).
4. **R30 is closed with a negative result, not a promotion.** 0/103 targeted queries flip to fully
   passing; `local_released_150` loses 2 (0 gained) with two distinct, now-diagnosed causes — one a
   genuine "the garbage capture contained a real POI name we should have salvaged before dropping"
   gap, the other search perturbation from the freed repair-queue budget landing on a worse plan on an
   unrelated dimension. HF free prose is FPR-flat everywhere (predetermined by the CJK-oracle ceiling
   above, not informative) but gains real ground at the **clause** level on two of four sets
   (`hf_easy 172→174/214`, `hf_medium 82→84/113`). The mechanism P22 targets — solve time — is real and
   large (`5.8–6.1×` faster convergence on three HF sets), but this per-query screen contract cannot
   measure whether the real envelope scheduler converts that into more passes elsewhere; that needs a
   `full_runs/`-shaped measurement. `TPC_P2_DROP_UNSATISFIABLE_NAMES` stays library-default-off. See
   [R30](#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result) and
   the [screen README](../results/phase2_baselines/screens/20260807_r30_unsatisfiable_names_e2e/README.md)
   for the full causal analysis and a concrete follow-up (salvage-before-drop) for the implementation
   workstream. **That follow-up landed 2026-08-08** (static half — `_salvage_catalog_name`, verified
   against the exact loss uid, `25–33 %` recovery rate on every released/HF set; see
   [its screen](../results/phase2_baselines/screens/20260808_p22_salvage_before_drop/README.md)). **Its
   e2e re-confirmation also landed 2026-08-08**: the exact same 103-uid target set and flag pair,
   re-run end to end — `20250324075652034944` (the salvage-fixable loss) now passes in both arms,
   `20250322180344489669` (the search-perturbation loss) is unchanged as predicted, every HF set is
   unchanged from R30, and the solve-time speedup reproduces closely. `local_released_150`'s net
   regression is halved (`2 lost → 1 lost`). Still `0/103` fail→pass, so
   `TPC_P2_DROP_UNSATISFIABLE_NAMES` still does not meet R30's own promotion bar and stays
   library-default-off — but the regression risk R30 identified is now measured closed for the
   parser-side mechanism. See
   [the reconfirmation screen](../results/phase2_baselines/screens/20260808_r30_salvage_reconfirmation/README.md).
   The remaining open question (whether freed solve time converts into more `full_runs/`-level passes)
   is unchanged and still unscheduled.
5. **P23 landed 2026-08-08, static half only.** `scripts/materialize_hf_split.py
   --translate-oracle-literals` now exists and reproduces the cap-pricing table above byte-for-byte,
   plus a full-split dry run of the rewrite itself: `331` free-prose queries across the four sets get
   at least one oracle clause translated, `66` still carry a residual unmapped literal (POI-name
   fragments and generic locations, as predicted — never approximated, only reported). No solve was
   run; that is R31, and nothing code-side blocks it now. See
   [the screen](../results/phase2_baselines/screens/20260808_p23_oracle_literal_translation/README.md).
6. **R31 landed 2026-08-08, closed GREEN.** Full `hf_medium` (n=150), single solve (query text is
   byte-identical between the untranslated and translated splits — the agent never reads
   `hard_logic_py` — so one solve scored twice against each oracle is equivalent to, and cheaper than,
   two solves), scored two ways: aggregate (`FPR 20.67 → 44.67`, `C-LPR 82.44 → 88.29`, `overall 51.06
   → 64.57`) and clause-by-clause across all 150 uids (`74` fail→pass, **`0` pass→fail** — the doc's
   own RED condition, checked directly, not assumed). Recalibrates the measurement; promotes nothing.
   See [R31](#r31--the-first-real-free-prose-fpr-gate) and
   [the screen](../results/phase2_baselines/screens/20260808_r31_oracle_literal_translation/README.md).
7. **R27 landed 2026-08-08, closed RED.** P6's own PR
   (`implementation/p6-validator-in-loop-repair`) ran R27 as its pre-gate screen, per the
   [workstream protocol](../CLAUDE.md#parallel-workstreams): `n=10` deterministic failures (9
   timed_window, 1 name_type, 0 transport_budget — the pool's honestly reported residual), live
   DeepInfra, `temperature=0`, LLM called on 8/10. **`0/10` accepted flips caused by the repair
   loop.** Safety held (0 ungrounded facts, 0 timeouts, real multi-round iteration, the new
   `insert_activity` op fired at least once); a measurement pitfall (crediting 2 deterministic-only
   passes as LLM flips) was caught and fixed before the verdict was drawn. Per the bar this row
   itself states, RED means stop — not scaled to `n=30`. `TPC_P2_LLM_REPAIR_LOOP` stays
   library-default-off. See [R27](#r27--validator-in-loop-qwen-repair-closed-2026-08-08-red) and
   [the screen](../results/phase2_baselines/screens/20260808_r27_llm_repair_loop/README.md).

| Run | Question | Blocked on | Cost |
| --- | --- | --- | --- |
| R20 | should grounded fill-only LLM extraction become a harness default? | no code blocker; precondition re-checked 2026-08-08, still not met (HOLD) | no cold-cache rerun yet |
| R21 | does spending the unspent envelope on all queries buy preference points? | P17(b), parked until FPR is nonzero | ~1.4 h, low priority |

**Parallel execution plan.** **R27, R28, R29, R30 and R31 are all closed**, and the
salvage-before-drop follow-up R30 identified for P22 also landed and was re-confirmed end to end
2026-08-08 (see item 4 above) — **the evaluation queue is now fully drained.** Every remaining item
is blocked or parked: R21 is parked until FPR is nonzero on a register that counts (R31 raised
`hf_medium`'s ceiling but P6/preference work is still the blocker, not the denominator — and P6
itself is now closed RED, so this stays parked), and R20 is HOLD per its own precondition re-check.
The next open (unnumbered) candidate is a `full_runs/`-shaped measurement of whether P22's freed
solve time converts into more passes at the
5 h envelope — plausible from both R30 and its reconfirmation, unmeasured by any per-query screen
contract. Do not run two solver
screens concurrently on one host: wall-clock limits then change the number of restarts each arm gets.
R20 needs no expensive run unless a new parse-level arm first beats the current deterministic floor.
**R9 is closed**, per R25's own gating text: it needed a genuine per-uid flip on the restart axis, and
R25 measured `0/10`.

### R28 — a whole-run row on the current `main` *(closed 2026-08-07)*

**The first slot, and everything else's prerequisite.** Five changes have merged
since R19 measured `ae0bd319`, and the ledger's own comparability rule forbids gating a candidate
against a baseline from a different source revision. Right now every open item's promotion path is
blocked on an absent denominator.

```bash
make phase2-full-run P2_LABEL="current main baseline, post P15/P16/P18/P19/P20"
```

Same host as R19 (4-core Linux, 3 workers) so the row is comparable with it; nothing exported, so
`apply_deterministic_solver_defaults()` alone configures the run — R12 established that the
promotion path and the explicit-environment path are the same configuration, and this row re-checks it.

**Read it two ways.** Against R19 it says whether the parser work since is a no-op, a gain or a
regression **on familiar-100 only** — the register R19 already showed the phrasing fix cannot move, so
byte-identity here is the *expected* result and is not evidence about free prose. Its real job is to
become the baseline every later candidate is gated against. Record it and update the
[promoted-default baselines table](#ledger-comparability).

**If it is not byte-identical to R19, stop and attribute before running anything else.** P20's
free-prose fallbacks are structurally unable to fire on familiar-100 (the template always populates
both families), and P15's fixes touch families familiar-100 does not carry, so a delta means one of
those structural claims is wrong and that matters more than any queued arm.

**Result** ([`20260807T152009Z`](../results/phase2_baselines/full_runs/20260807T152009Z.json),
`git_sha aed4363e`, `1.34 h` of `5 h`): **byte-identical to R19 on all seven official metrics** —
`overall 64.17251838310492`, `MicEPR 99.6667`, `MacEPR 98.0`, `C-LPR 90.08115419296664`, `FPR 44.0`,
`DAV 26.0417`, `ATT 34.4752`, `DDR 25.1944`, `constraints_ok 50/100`, `empty_plans 0/100`. **All
`100/100` plan files are byte-identical to R19's, modulo the timing field** (`elapsed_time(sec)`);
`sweeps.parent_parse_failed_uids` is `[]`; `solver_flags.window_anchor`/`window_push`/`window_insert`
are all `true`, per the ledger comparability requirement. This is the expected outcome the section
above predicted: P15/P16/P18/P19/P20 all touch families or fallback paths that structurally cannot
fire on familiar-100's rigid numbered-requirements template, so a flat row here confirms those
structural claims rather than testing them. **The drift is closed.** This row is now the current
baseline for R29, R30, R31 and any later candidate gate on this host/config; the
[promoted-default baselines table](#ledger-comparability) and [closed queue](#the-closed-queue-r1r19)
are updated below.

### R29 — does deterministic entity resolution convert end-to-end? *(closed 2026-08-07, GREEN)*

**Correction to this section's own former premise, found while running it.** This section used to say
"the flag has been on `main` and default-off since Phase 2 plan 3," citing only
`Flags()`/`Flags.from_env({})`. That is true of the bare library constructor, but the code path every
real run actually takes — `agent_env/scripts/solve_phase2.py:resolve_llm_client_and_flags()`, called
from `run_split`, which both the CLI and the organizer harness entry point dispatch to — has silently
force-defaulted `entity_resolution = True` (unless the operator explicitly sets
`TPC_P2_ENTITY_RESOLUTION`) since `b53a0747` (2026-07-13, the same auto-promotion pattern already used
for `disjunction`/`dynamic_budget`). `b53a0747` is an ancestor of both R28's `aed4363e` and the `v1`
submission's build ancestor `be196d00`. **Confirmed directly against R28's own on-disk telemetry**
(`agent_env/runs/phase2_e2e_tpc_phase2_familiar_100/*/telemetry.json`, mtimes matching R28's run
window): every query's `flags.entity_resolution` is `true`. **R28's baseline and the held-out `v1`
score already ran with this flag on** — the "isolate an off-by-default flag" framing below describes
what R29 measured, not what shipped.

Full result, method and every number:
[`results/phase2_baselines/screens/20260807_r29_entity_resolution/README.md`](../results/phase2_baselines/screens/20260807_r29_entity_resolution/README.md).

**Static probe** (`scripts/phase2_entity_resolution_arms_probe.py`) reproduced byte-identical to the
numbers already recorded in
[P21](tpc_phase2_roadmap.md#p21--promote-deterministic-entity-resolution): parse F1 `0.9552 → 0.9949`
on familiar-100, `0.8222 → 0.8451` on `local_released_150`, `matched` `661 → 688` and `wrong_value`
`30 → 3` on the control, `hf_medium`/`hf_easy` roughly flat with a small `spurious` uptick.

**Familiar-100 e2e A/B** (`--mode end-to-end` — the default `solver-only` never invokes the parser, so
this had to be added explicitly to actually exercise the flag; the literal `make phase2-quick-eval`
command in the doc's prior revision omitted it), n=40, budget=90s: **GREEN**. FPR `45.00 → 50.00`
(`+5.00`), `overall_true` `64.83 → 67.53` (`+2.70`), C-LPR `91.10 → 91.55` (`+0.46`), `all_pass`
`18 → 20`, zero timeouts and zero LLM calls in both arms (`llm_parse_fired: 0`, confirmed from
telemetry), monotonic gate PASS. Two queries flip from failing to fully-passing — the first row that
turns P21's static parse-diff gain into an actual scored flip.

**Free-prose e2e A/B** (`hf_medium`, materialized 30-uid subset, direct sharded `solve_phase2.py`
since `phase2_quick_eval.py` has no `--split` flag for an arbitrary materialized split — deleted after
scoring): **NEUTRAL**, exactly the sanctioned "informative, not a promotion" outcome this section's
acceptance bar named. FPR `16.67` flat, `overall` `49.99` flat, C-LPR `86.25` flat, and **all 30/30
plan files are byte-identical between arms**, not just the aggregate — matching the static probe's
prediction that the English-literal-value repair has nothing to convert on a Chinese-oracle-literal
register. (Remember `hf_medium`'s own FPR ceiling under `--lang en` is `38.67`, not `100` — see
[the corrected dataset boundary](#3-hugging-face-chinatravel).)

No RED condition on either register (no FPR fall, no `spurious` rise on the measured e2e sample).
**Verdict: GREEN**, and per this section's own former bar that authorizes formalizing
`entity_resolution` as a recorded, committed-default configuration — but since it already fires on
every harness run today, that action is documentation and bookkeeping (making an existing default
explicit and durably recorded), not a behavioral change, and does **not** require a new whole-run row
to re-confirm familiar-100 (R28 already is that row, with the flag on). The genuinely new, still-open
question is the mirror image of what this section asked: would explicitly turning the flag *off*
regress a `full_runs/` row — this screen says yes on a 40-query sample, but nobody has run that at
n=100 yet, and it is not currently queued (the flag is not at risk of being turned off, so a
confirmatory row is low priority relative to R30/R31).

### R30 — does dropping unsatisfiable names flip queries? *(closed 2026-08-07, negative result)*

[P22](tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints) **landed
2026-08-07** (`TPC_P2_DROP_UNSATISFIABLE_NAMES`, library default off). **The static part was already
done and GREEN**:
[`results/phase2_baselines/screens/20260807_p22_unsatisfiable_names`](../results/phase2_baselines/screens/20260807_p22_unsatisfiable_names/README.md) —
every set's count was `0` in both the required-name and category-value (`--types`) arms.

**The e2e half is now measured too, and it is a negative result — nothing promotes.** Full write-up:
[`results/phase2_baselines/screens/20260807_r30_unsatisfiable_names_e2e/README.md`](../results/phase2_baselines/screens/20260807_r30_unsatisfiable_names_e2e/README.md).
Paired A/B (`TPC_P2_DROP_UNSATISFIABLE_NAMES=0` vs `=1`), `budget-sec 90`, on the **103** queries the
probe flags across all six released/HF sets (re-run fresh on current `main` — P24, merged after the
last static screen, independently shrinks some of the same over-captured values, so the target set
moved from the stale `24/150` on `local_released_150` to `20/150`; the fresh numbers are what this row
gates against).

Measured against the doc's own bar, clause by clause: **GREEN's condition (≥1 target uid flips to
fully passing) is not met — 0/103.** The literal **RED condition (zero flips *and* no C-LPR movement)
is also not met** — C-LPR moved on three of six sets (two up, one down). So this is neither GREEN nor
literal RED; the honest reading is a **negative result**: no query gained, one register lost two, and
the flag stays library-default-off (no default changes).

**By register:** familiar-100 control (n=7) is byte-identical between arms — the flag provably changes
nothing there. `local_released_150` (n=24) is the only register where a flip was measurable (its
targets were mostly *near*-passing, `22/24` already passing pre-drop): **0 gained, 2 lost**
(`FPR 91.67 → 83.33`), both reproduced deterministically on rerun. One loss
(`20250324075652034944`) is a clean causal case — the garbage capture
`"Xixi Paradise Commercial Street, wish to stay in single-bed rooms"` contains a real attraction name
as its prefix; the solver's own (more lenient) constraint matcher apparently placed the real POI
anyway when the value was kept verbatim, but P22 drops the whole value, so the ON plan never targets
it and the oracle clause requiring it fails — realizing exactly the risk this section's acceptance bar
named. The other (`20250322180344489669`) is a different mechanism: its dropped value had no causal
path to the OFF pass at all (checked directly against the oracle's OR clause), so the flip is search
perturbation from freed repair-queue attention landing on a worse-luck plan, not requirement loss. HF
free prose (n=72 across 4 sets) stayed FPR-flat everywhere — **predetermined, not informative**, since
every target query already carries the `59–61 %`-of-queries CJK-oracle ceiling this document already
flags; the real, positive signal there is at the **clause** level: `hf_easy` and `hf_medium` each gain
2 satisfied clauses with the flag on and lose none (`172→174/214`, `82→84/113`).

**The mechanism P22 actually targets — solve time — is confirmed directly, and it's large:** with the
flag on, free-prose queries converge in `~9–18 s` instead of exhausting the `90 s` per-query cap
(`5.8–6.1×` on three of four HF sets, `stage_sec.solve` telemetry). This fixed-budget screen contract
is structurally blind to what that freed time is worth — a real harness run (`sweeps.py`'s
triage/repair/polish envelope) reallocates it to other queries within the `5 h` budget; a per-query
screen just discards it. **The cost side is measured here and is real; the benefit side is plausible
from this evidence but needs an envelope-shaped (`full_runs/`) measurement, not a per-query one, to
confirm.**

**Follow-up, not yet built:** the clean-causal loss above is a specific, fixable gap — before falling
back to a full drop, try to salvage a real catalog POI name that is a prefix/cleanly-separable
substring of an otherwise-unmatched capture. That would keep P22's demonstrated solve-time win while
closing the loss this row found. Not done here (eval-workstream row; does not edit
`chinatravel/agent/`).

**Follow-up landed 2026-08-08 (static half, implementation machine)** — `_salvage_catalog_name` in
`chinatravel/agent/phase2/normalize.py`, `25–33 %` recovery rate on every released/HF set (see
[the screen](../results/phase2_baselines/screens/20260808_p22_salvage_before_drop/README.md)). **Its
e2e re-confirmation also landed 2026-08-08**, reproducing this row's exact 103-uid target set and flag
pair: `20250324075652034944` (the clean-causal loss above) now passes in both arms, closing that loss;
`20250322180344489669` (the search-perturbation loss) is unchanged, as predicted; `local_released_150`'s
regression is halved (`2 lost → 1 lost`, `0` gained either time); every HF set is unchanged from this
row (byte-identical clause movement); the solve-time speedup reproduces closely
(`local_released_150 60.05 → 26.89 s`, `hf_easy 57.74 → 11.74 s`, etc., matching this row's own numbers
within noise). **Still does not meet this row's own promotion bar** (`0/103` fail→pass) — the flag
stays library-default-off — but the regression risk this row identified is now measured smaller, not
just claimed smaller. See
[the reconfirmation screen](../results/phase2_baselines/screens/20260808_r30_salvage_reconfirmation/README.md).
The remaining open question (whether the freed solve time converts into more `full_runs/`-level passes)
is unchanged and still unscheduled.

### R31 — the first real free-prose FPR gate *(closed 2026-08-08, GREEN)*

**P23 landed 2026-08-08** (static build-and-verify only — see
[the screen](../results/phase2_baselines/screens/20260808_p23_oracle_literal_translation/README.md)).
R31 ran the translation pass end to end on `hf_medium` (n=150, the full split). Cap re-priced first
(seconds, no solve) and reproduced byte-identical to the P23 screen: FPR ceiling `38.67`, C-LPR
ceiling `90.03` — that is the denominator every prior `hf_medium` number in this document should be
read against, unchanged.

**Single solve, scored twice.** Confirmed directly (not assumed) that `--translate-oracle-literals`
touches only `hard_logic_py`; `nature_language` and every other agent-visible field are byte-identical
between the untranslated (`hf_medium_r31`) and translated (`hf_medium_en_oracle`) materializations for
all 150 uids. Since the Phase 2 agent never reads `hard_logic_py`, the solved plan cannot depend on
which split name it ran under — one solve (3-way sharded, `budget-sec=90`, zero LLM calls, `~15 min`
wall clock, well under the doc's `~1 h` estimate) scored against each split's oracle is equivalent to,
and cheaper than, the two-solve reading of "score the same free-prose subset twice."

**Result** ([full screen](../results/phase2_baselines/screens/20260808_r31_oracle_literal_translation/README.md)):

| metric | control (untranslated) | translated | Δ |
| --- | --- | --- | --- |
| FPR | 20.67 (31/150) | 44.67 (67/150) | **+24.00** |
| C-LPR | 82.44 | 88.29 | **+5.85** |
| overall | 51.06 | 64.57 | **+13.51** |
| MicEPR / MacEPR | 100.0 / 100.0 | 100.0 / 100.0 | flat |

**GREEN, checked at the acceptance bar this document actually needs — the clause level, not just the
aggregate.** Two arms can land on the same aggregate C-LPR while satisfying a different clause set, so
a per-uid, per-clause diff (reusing the real checker,
`evaluate_hard_constraints_v2`, not a reimplementation) is what the RED condition requires:
`clause_count_mismatch: 0` across all 150 uids, **`74` clauses flip fail→pass, `0` flip pass→fail**.
Every sampled flip is a bare CJK literal (`'火锅'`, `'历史古迹'`, `'商业街区'`, …) reading as its
English catalog equivalent (`'Hot pot'`, `'historical site'`, `'commercial district'`, …) — never a
value substitution that changes what the clause means. The other `51` of the `125` mappable clauses
stayed failing: translation lifts the structural cap, it does not manufacture a matching plan, and
that split is the expected shape.

**This recalibrates the measurement; it promotes no solver default.** The translated split was deleted
after scoring (confirmed absent from `git status`), matching every prior use of
`--translate-oracle-literals`. Every free-prose FPR/C-LPR number already recorded in this document
stays as written — read against its ceiling, not retroactively rewritten. The open follow-up this
unlocks (re-run R26/R29/R30's pinned free-prose e2e screens under the translated oracle to see whether
their solver-side conclusions look different once the structural cap is lifted) is not yet scheduled
with an R-number.

<a id="r20--does-grounded-fill-only-llm-extraction-convert"></a>
### R32 — what landed since `v1`, measured on free prose *(closed 2026-08-08, GREEN)*

**The measurement the `v2` decision needed, and the one nobody had run.** Every committed row is on
familiar-100, the single register on which the whole 2026-08-06/07 program (phrasing recall, precision,
family fallbacks) is structurally inert — so no row said what `v2` would be *carrying*, only that it
would not regress. R31 removed the last obstacle by lifting the CJK-oracle-literal FPR ceiling off free
prose.

Screen: [`20260808_v2_candidate_freeprose/`](../results/phase2_baselines/screens/20260808_v2_candidate_freeprose/README.md).
Contract: `hf_medium` n=150, per-query mode, `--budget-sec 90`, `--lang en`, four arms launched
**simultaneously** with two shards each on one 10-core host so the arms share their contention;
`v1`'s arm is `be196d00` checked out in a detached `git worktree`, running **its own**
`apply_deterministic_solver_defaults()` so it reproduces the configuration that actually shipped.
Scored against both the untranslated control oracle and R31's translated one.

| arm | C-LPR | FPR | overall | (control-oracle overall) |
| --- | --- | --- | --- | --- |
| `v1` (`be196d00`) | `75.5538` | `10.6667` | `44.4077` | `41.2850` |
| **current `main`** | **`88.3703`** | **`44.0000`** | **`64.2767`** | `51.4844` |
| `main` + `TPC_P2_DROP_UNSATISFIABLE_NAMES` | `88.6867` | `45.3333` | `65.0127` | `51.5239` |
| `main` + drop + `TPC_WINDOW_RELOCATE_DAY` | `88.6867` | `45.3333` | `65.0127` | `51.5239` |

Clause-level, per uid, through `evaluate_hard_constraints_v2` (not a reimplementation): `v1 → main` is
`191` fail→pass against `29` pass→fail, **net `+162` of `1264`** — `52 %` of the failing-clause mass
removed. `main` reproduces R31's independently measured control row (different host, different shard
layout) to within `0.24` C-LPR, which is the cross-check that these absolute numbers are not a
host artifact.

**Both candidate flags, decided here.** `TPC_P2_DROP_UNSATISFIABLE_NAMES` is `+0.74` overall,
`+1.33` FPR (two more queries fully pass), `+4` net clauses (`8` gained, `4` lost) — small, but this is
the **first register on which it could show anything at all**, since [R30](#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
read FPR under a `38.67` ceiling where a flipped query mostly could not become visible. That is not a
reversal of R30's verdict; it is the measurement R30 said it could not make.
`TPC_WINDOW_RELOCATE_DAY` is **provably inert** here: all `150` plan files are identical between the two
candidate arms once `elapsed_time(sec)` is removed, checked per file. Free prose does not contain the
present-but-window-missing `timed_visit_named_poi` shape it targets, so its only positive evidence
remains the familiar-register screen ([P25](../results/phase2_baselines/screens/20260808_p25_window_relocate_day/README.md),
`+2/40`) — no risk and no benefit on free prose.

**Limits, stated because they bound what this licenses.** One register, one budget, one host, no
repeats; the translated oracle is a measurement device, not the organizers'; `90 s`/query is not the
shipped 5 h envelope shape. This ranks configurations and sizes a code delta. It does not predict a
held-out score, and the whole-run confirmation on familiar-100 is
[R33](#r33--the-v2-whole-run-gate-on-familiar-100).

### R33 — the `v2` whole-run gate on familiar-100 *(closed 2026-08-09)*

**The regression half of the `v2` decision.** R32 measures the candidate on the register that resembles
held-out; this row asks the complementary question in the **shipped shape** (the organizers' entry
point, 5 h envelope, triage → repair → polish, keep-best): does the candidate flag pair cost anything
on the register we have always measured? Paired rows on one host, sequential (never concurrent — the
envelope makes concurrent rows non-comparable by construction), `--workers 8`, `--fresh`.

**Result: GREEN.** Rows [`20260808T200402Z_v2gate_base`](../results/phase2_baselines/full_runs/20260808T200402Z_v2gate_base.json)
(`0b4c44a4`, harness defaults) and [`20260808T200402Z_v2gate_cand`](../results/phase2_baselines/full_runs/20260808T200402Z_v2gate_cand.json)
(`104a90d8` + both flags): **overall `64.6878 → 65.7354` (`+1.0476`), FPR `45.0 → 47.0`, C-LPR
`90.1713 → 90.4418`**, EPR-micro and EPR-macro flat, all three preference terms up, `constraints_ok`
`50 → 54`, `empty_plans 0/100` in both, `run_wall 0.63 h` of `5 h` in both. Nothing regresses on any of
the seven metrics. P26 is structurally inert on this register (asserted by a byte-identity test over
all 100 queries), so the movement belongs to the flag pair — principally `TPC_WINDOW_RELOCATE_DAY`,
whose own screen predicted this shape (`+2/40` → `+2/100`). Neither row is comparable to R28: this host
is a 10-core M1 Pro at 4 workers, and the baseline arm scores `64.6878` on code that scored `64.1725`
on the 4-core Linux box, which is exactly why the baseline was re-run rather than reused. See
[the screen](../results/phase2_baselines/screens/20260809_v2_whole_run_gate/README.md).

### R34 — does the intercity recall fix convert? *(closed 2026-08-09)*

**The e2e half of [P26](tpc_phase2_roadmap.md#p26--free-prose-intercity-transport-mode).** Static
recall is not a score: an extracted requirement can still fail to be satisfied, and a *newly
constrained* query can lose ground elsewhere (both endpoint legs are now pinned). Contract: paired
free-prose A/B on `hf_medium` (n=150), per-query mode, `--budget-sec 90`, `--lang en`, both arms
launched simultaneously with two shards each so contention is shared, scored against R31's translated
oracle. Baseline arm is the same tree with the fix reverted at the flag level — here, the pinned
pre-P26 revision (`0b4c44a4`) plus the candidate flag pair, so the *only* difference is the parser.

**Bar, written before the run.** GREEN needs C-LPR up **and** no FPR fall, plus the clause-level
check: `fail→pass` must exceed `pass→fail`. Any C-LPR fall, or a net clause loss, is RED and P26 comes
back out of `v2` — the change is unflagged, so RED means revert, not "leave it off".

**Result: GREEN.** Translated oracle, n=150: **C-LPR `88.6867 → 89.6361` (`+0.9494`), FPR
`45.3333 → 48.0000` (`+2.6667`, four more queries pass every clause), overall `65.0127 → 66.6182`
(`+1.6055`)**; EPR-micro/macro flat at `100.0`; control-oracle arm moves the same way
(`overall 51.5239 → 53.4361`). Clause level: **`14` fail→pass against `2` pass→fail**, net `+12` of
`1264` — the bar was `fail→pass > pass→fail`, met `7×`. The two losses are the expected cost of adding
a constraint (a pinned intercity mode shrinks the feasible set), and the net is what promotes.

**One reproducibility fact from this row is worth carrying forward.** Its baseline arm is the same
configuration R32 measured, re-solved under a *different* concurrency (4 concurrent solver processes
against 8), and it reproduced **every metric to the last decimal**. Per-query solves at this budget are
therefore insensitive to host load here, which is what licenses comparing arms across the two screens.
See [the screen](../results/phase2_baselines/screens/20260809_r34_intercity_e2e/README.md).

### R20 — does grounded fill-only LLM extraction convert? *(HOLD; not promoted)*

P16 fixed two real grounding defects and remains useful infrastructure. It does not yet satisfy the
promotion bar:

- Same tree, same `local_released_150` arm: the current comparison bar is the contemporaneous
  deterministic floor of `matched 320`, not the stale pre-P15 threshold of `309`; grounded
  `extract_fill` reaches only `311`.
- The only post-P16 free-prose e2e arm has a negligible negative delta within the measured noise:
  `hf_medium` overall `49.99 -> 49.88`, FPR unchanged.
- Familiar-100 moved positive on a noisy two-core box, but familiar-only evidence cannot promote the
  parser after v1 exposed the register failure.

**Decision:** keep `TPC_P2_LLM_PARSE=0` by default. Do not spend a cold-cache 904-call rerun merely to
reproduce `311 < 320`. Re-open R20 only when a changed parser/merge policy beats its contemporaneous
deterministic arm on `matched` without increasing `spurious`, then require a positive free-prose e2e
arm before a pinned whole-run row. `extract_fill` is the only allowed merge policy and
`TPC_P2_ENTITY_RESOLUTION=1` is part of the candidate. Audit and overwrite modes remain closed.

Promotion, if R20 reopens, also requires a cold-start harness test with endpoint autodetection and at
most eight concurrent calls. A local env flag is not enough: the organizer invokes exactly the bare
harness command.

**Precondition re-checked 2026-08-08**
([`20260808_r20_precondition_arm`](../results/phase2_baselines/screens/20260808_r20_precondition_arm/README.md),
`git_sha fecdf7ca`): **still not met, R20 stays HOLD.** P20/P22/P24 all landed since the `311 < 320`
comparison, so both arms were re-measured live (`extract_fill`, `--entity-resolution`,
`local_released_150`, `145` live calls + `5` cache hits, `0` failures, `$0.0736`). **The deterministic
floor moved on its own**: `matched 320 → 325`, independent of any LLM arm. The LLM arm also moved
(`311 → 318`) but not enough to catch up (`318 < 325`), and its `spurious` improvement (`38 → 32`) is
offset by `wrong_value` rising sharply (`36 → 59`, `+64 %`). The three counts are a strict partition
of the same `393` oracle-field slots in both arms, which pins the accounting exactly: **at least `7`
of the `59` `wrong_value` families were `matched` (correct) before the LLM arm touched them** —
`extract_fill`'s contract ("only fill families the deterministic parse left empty, never overwrite a
regex value") says this should not be possible at all. The n=5 price probe shows the same signature
in isolation with zero missing families to fill (`matched 10 → 8`, `wrong_value 0 → 2`), so at least
some of this is a genuine overwrite, not an artifact of the larger sample. Whether the cause is
`extract_fill`'s merge path or `--entity-resolution` rewriting a value post-merge is not resolved
here (open question for the implementation workstream) — it does not change this row's verdict, since
`matched 318 < 325` either way. Net: `3` clauses recovered (`attraction_name ×2`, `attraction_type
×1`), `0` broken, but `19` queries improve recall against `28` that regress it. The precondition's
first half (beat the floor on `matched`) is not met, so per R20's own bar the expensive half
(cold-cache harness rerun, free-prose e2e arm) is correctly not spent. Re-open only after a future
parser change re-measures both arms again.

<a id="r25--separate-the-cp-restart-and-outer-budget-limits"></a>
### R25 — separate the CP, restart and outer-budget limits *(closed 2026-08-07)*

R24's `300 s` and `900 s` arms both stopped near `107 s` because they replayed the same deterministic
400 restarts and the same default CP-SAT slice (`min(30, remaining / 2)`). It proved that changing only
the outer timeout is inert. It did not perform 900 seconds of mathematical search.

Use the first ten uids from R24's committed failing set and three same-outer-budget arms. Materialize
the scorer split once; it is evaluation-only and must not ship:

```bash
head -n 10 results/phase2_baselines/screens/20260807_r24_budget_ladder/r24_failing30.txt \
  > chinatravel/evaluation/default_splits/r25_failing10.txt

# Run one uid per process, up to CPU-1 processes. Never add --resume; every method is fresh.
# A: control internal limits
TPC_MAX_RESTARTS=400 TPC_CP_TIME_LIMIT_SEC=30 \
  .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split tpc_phase2_familiar_100 --uids-file chinatravel/evaluation/default_splits/r25_failing10.txt \
  --method phase2_e2e_r25_control --budget-sec 1800 --lang en

# B: isolate mathematical-solver time
TPC_MAX_RESTARTS=400 TPC_CP_TIME_LIMIT_SEC=300 \
  .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split tpc_phase2_familiar_100 --uids-file chinatravel/evaluation/default_splits/r25_failing10.txt \
  --method phase2_e2e_r25_cp300 --budget-sec 1800 --lang en

# C: isolate randomized breadth
TPC_MAX_RESTARTS=4000 TPC_CP_TIME_LIMIT_SEC=30 \
  .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split tpc_phase2_familiar_100 --uids-file chinatravel/evaluation/default_splits/r25_failing10.txt \
  --method phase2_e2e_r25_r4000 --budget-sec 1800 --lang en
```

The commands are shown serially for clarity. On a multi-core host, shard the ten uids across
`cores - 1` subprocesses exactly as R24 did; do not run the three arms concurrently. Score each with
`eval_tpc.py --splits r25_failing10 --method <method> --lang en`, and compare per-uid flips and plan
content, not only the mean.

**Decision table:**

| Result | Interpretation | Next action |
| --- | --- | --- |
| CP arm flips at least one uid | 30 seconds was too short for at least part of the model | instrument CP status/reconstruction, then add a bounded CP-heavy portfolio pass behind a flag |
| restart arm flips at least one uid | the parameter space was not exhausted at 400 draws | implement P4/P5 seed-diverse passes, keep-best, then whole-run gate |
| either single axis flips | useful axis identified | run the combined `CP=300/restarts=4000` arm on all 30 R24 failures |
| no arm changes any plan | both deeper versions reached the same representation limit | close blind compute expansion; prioritize P20/P6/new moves |
| plans change but no uid flips | ambiguous partial movement | inspect failed-clause families before scaling; do not infer headroom from runtime |

Record `TPC_MAX_RESTARTS`, `TPC_CP_TIME_LIMIT_SEC`, solve time, restarts, stop reason and exact method
name in the screen. If CP attribution is ambiguous because status/reconstruction is not exposed, add
telemetry before the 30-query scale-up; do not guess from wall time.

**Result** ([`20260807_r25_cp_restart_separation`](../results/phase2_baselines/screens/20260807_r25_cp_restart_separation/README.md),
`git_sha edb5bb20`): **the CP arm is fully inert, the restart arm changes plans but flips no query, and
the recurring blocker is a clause family neither axis touches.**

Sanity gate first: Arm A (control: `TPC_MAX_RESTARTS=400`, default CP) reproduces R24's committed
`r24_scored_b300.json` byte-for-byte on all 10 uids despite running on a newer SHA (post-P16/P19) — the
deterministic path is unaffected by those changes, and the 10-uid subset still fails exactly as R24 found.

- **Arm B (`TPC_CP_TIME_LIMIT_SEC=300`, 10x the default): `0/10` plans change, at all.** `restarts_used`,
  `stop_reason`, and `overall_true` are identical to control on every uid; plan JSONs are byte-identical
  modulo the timing field. The `stage_sec.solve` rise (`85.5s -> 89.1s` mean) alone sits inside R24's own
  noise band and can't rule out "the CP branch silently no-ops" (it is wrapped in `except Exception:
  pass`), so a fourth throwaway arm fully disabled CP-SAT (`TPC_USE_CP_SOLVER=0`) instead of just
  time-boxing it: byte-identical plans and scores to control on all 10 uids. CP-SAT contributes nothing
  to the accepted plan on these 10 queries at any budget, including zero — a genuine null, not a
  false negative.
- **Arm C (`TPC_MAX_RESTARTS=4000`, 10x the default): `0/10` full flips, but real movement.** Plan content
  differs from control on 6/10 uids (`best_found_at_restart` lands past restart 400 for all 6, out to
  `3769`), proving 400 restarts had not exhausted the reachable set. But `fpr_true` stays `0.0` throughout
  — score moved on exactly one of those six: uid `...00039` gained one clause (a cost-budget clause, via a
  cheaper metro+walk route replacing taxi legs) without flipping the query, because a second, unrelated
  clause on the same query was still unmet.
- **Failed-clause-family inspection** (the doc's own required step for this outcome): across the 6
  differing-plan uids, the clauses that stayed unsatisfied in *both* arms are dominated by one family —
  **timed-window POI placement** ("visit/dine at position X between time A and time B") — 9 of 11
  still-failing clause slots, in 5 of the 6 uids (the exception fails on a transport-cost budget and a
  required-attraction-inclusion clause, neither timed). Ten times the restart budget closed zero
  timed-window clauses; the one clause it did close was a budget clause, a different family entirely.

**Reading, against the doc's own decision table:** this is the "plans change but no uid flips" row —
neither single axis flipped a query, so the combined `CP=300/restarts=4000` 30-uid arm is **not**
authorized by this evidence. The failed-clause inspection the row calls for says more: the binding
constraint on these 10 queries is a move-set gap (hitting a tight arrival/departure window while
satisfying everything else), not an under-sampled search space — 4000 draws of the same random-restart
move never closes it. **This closes blind compute expansion as a lever**: [R9](#r9--the-whole-run-gate-for-seed-diverse-exploration)
required a genuine per-uid flip on the restart axis to become meaningful and R25 measured `0/10`, so R9
stays closed. [P5](tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds) had the weaker gate
"a positive R25 arm before default-on implementation," which is also not met — it stays un-implemented
rather than closed outright, since R25 tested restart volume, not the seed-diversity mechanism P5's own
argument rests on.
[P4](tpc_phase2_roadmap.md#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass)
remains a correctness-only fix, unchanged from R24. Priority moves to
[P20](tpc_phase2_roadmap.md#p20--close-the-two-dominant-family-recall-gaps)/[P6](tpc_phase2_roadmap.md#p6--validator-in-loop-qwen-repair)
or a dedicated timed-window repair move — targeted-edit approaches suited to "find the one placement that
satisfies a tight window," which is what the residual failures on this subset actually are.

<a id="r26--gate-p20-on-the-registers-it-targets"></a>
### R26 — gate P20 on the registers it targets *(closed 2026-08-07, GREEN)*

P20 merged at `f413eb2a` with its R22 screen and a `target_uids.txt` containing only released
English-visible `required_attraction_types`/`cuisine_preference` misses used to develop it. Evaluation
checks out the pre-P20 main SHA and candidate SHA in separate worktrees, runs the same uid file at the
same `90 s`/query budget and worker count with distinct method directories, then scores both. Also run
the unchanged familiar-100 first-30 control.

**GREEN:** familiar-100 parse gaps remain `0/1109`; no free-prose set gains gaps or spurious clauses;
target-family `matched` rises; target-subset C-LPR rises; FPR and EPR-macro do not fall on either
register. **RED:** any precision regression, no target e2e movement, or a familiar-only gain. A GREEN
screen authorizes one current-main whole-run row; it does not estimate held-out score.

**Result** ([`20260807_r26_p20_gate`](../results/phase2_baselines/screens/20260807_r26_p20_gate/README.md),
baseline `git_sha edb5bb20` / candidate `git_sha 0d6f1837`): **GREEN.** A positive control confirmed
worktree isolation first — the pre-P20 tree reproduces the exact buggy `cuisine_preference` values
P20's writeup names, the post-P20 tree emits the clean oracle-matching values.

- **Static probe, all 6 sets:** familiar-100 byte-identical (`0/1109`, structural). Every free-prose
  set's parse-gap count fell (e.g. `hf_medium` `126/1264 -> 78/1264`) and **no set gained a spurious
  clause** — the HF sets' precision figure drops only because `missing` clauses convert to
  `wrong_value` under an unchanged `spurious` count (expected: CJK oracle literals, English fallback
  values), not a new false-positive family detection. `local_released_150` (the one set with an
  English oracle) is the one where the fix's real effect shows on both precision and recall at once.
  Every per-set gap count here is byte-identical to [P18's R22 generalization-tripwire
  screen](#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)
  (`20260807_generalization_post_p20`, merged separately in parallel) — two unrelated comparison
  methods (a pinned pre/post-P20 worktree diff here vs. a floor-file check against an older screen
  there) landing on the same numbers is a useful cross-check that both are measuring something real.
- **Per-family (`tpc_phase2_test`):** `cuisine_preference` `matched 6 -> 12` (reproduces P20's own
  screen). **`required_attraction_types` also moved (`10 -> 11`), contrary to P20's own claim of zero
  locally-measurable misses** — one disjunctive-branch clause its partition script didn't enumerate
  the same way. This is the one piece of e2e-adjacent evidence in this row that speaks to the
  `required_attraction_types` half directly, though it is a single data point, not a volume
  validation.
- **E2E, `r26_p20_target3` (3 uids):** `fpr_true` and `conditional_logical_micro` are identical
  (`100.0`) in both arms on all 3 uids — **no movement, but only because all 3 already passed
  regardless of the parse bug**, so the sample had no failing query to flip. Read this as "no power on
  `n=3`," not "the fix is inert" — the static and per-family evidence above is unambiguous that it
  isn't.
- **E2E, `r26_familiar_first30` (30 uids) control:** byte-identical — `0/30` differ in parsed
  constraints or `overall_true`, `13/30` pass in both arms, confirming the fallback structurally never
  fires on the template register even under an actual solve, not just under static parsing.

No RED condition is met (no precision regression, no familiar-only gain, and the flat e2e result is
explained by ceiling, not inertness). **This authorizes one current-main whole-run row and nothing
more** — it does not estimate held-out score, and an HF-set e2e arm (whether the
`missing -> wrong_value` fallback value can ever locally *hurt* a plan by narrowing the solver to an
ungrounded English type) is explicitly out of this row's scope and remains open for future work.

**R26's open question, answered 2026-08-07 (static, no solve).** R26 left open whether the
`missing → wrong_value` fallback can locally *hurt* a plan by narrowing the solver to an English type
value with zero grounded candidates in the target city. Measured directly, with
`parsed_verifier._match_text` — the matcher the acceptance gate itself uses — against each city's own
`database_en/` vocabulary:

| set | queries with ≥1 ungroundable type value | dominant field |
| --- | --- | --- |
| familiar-100 | `0 / 100` | — |
| `local_released_150` | `5 / 150` (`3 %`) | `cuisine_preference` (3), `required_hotel_*_types` (3) |
| HF `easy` | `7 / 300` (`2 %`) | `required_hotel_all_types` (8) |
| HF `medium` | `8 / 150` (`5 %`) | `required_hotel_all_types` (7), `required_attraction_types` (2) |
| HF `human` | `2 / 154` (`1 %`) | `required_hotel_all_types` (4) |
| HF `preference_base50` | `0 / 50` | — |

**The answer is "yes, but rarely, and mostly not in P20's families."** The risk is real — it is the
same no-feasible-point class as
[roadmap §6](tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves), an
order of magnitude smaller (`1–5 %` of queries against `23–50 %` for names). P20's two target families
contribute `5` instances in total across every set measured, so this does **not** qualify R26's GREEN.
Two things are worth carrying forward instead: the dominant field is `required_hotel_all_types`
(`"King-size bed"`, `"Large bed"`, `"Sea view"`, `"Movie-watching facilities"` — hotel features outside
the closed vocabulary), which is a different family and predates P20; and
`required_attraction_types: "Cultural Landscape"` is ungroundable specifically in **Suzhou and
Hangzhou**, i.e. a canonical value that is absent from *those* cities' catalogs — the city-scoping
hazard `_attraction_type_vocab` already warns about. Both fold into
[P22](tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints), whose drop
rule should cover category-valued families with a **city-scoped** check, not only name-valued ones.

### R27 — validator-in-loop Qwen repair *(closed 2026-08-08, RED)*

Use ten deterministic failures spanning timed-window, name/type and transport/budget blockers. Baseline
and candidate share the deterministic plan; candidate gets at most six Qwen calls/query, thinking off,
`temperature=0`. Verify wire calls and edit counters for every uid.

**GREEN:** at least one previously failing uid becomes accepted, no accepted uid regresses, EPR-macro
does not fall, every emitted fact grounds, and no timeout/fallback count rises. **RED:** zero accepted
flips, even if partial score improves. If GREEN, scale to 30 failures before integrating it as the last
portfolio pass; if RED, close the loop rather than adding prompt turns.

**P6 landed 2026-08-08** (`TPC_P2_LLM_REPAIR_LOOP`, library default off, independent of
`TPC_P2_LLM_REFINE`) with this exact screen run in the same PR (implementation workstream's own
pre-gate triage, per the [workstream protocol](../CLAUDE.md#parallel-workstreams)):
10 deterministic failures (9 timed_window, 1 name_type, 0 transport_budget — the pool's honestly
reported residual, not a forced even split), live DeepInfra backend, `temperature=0`, LLM called on
8/10. **Result: `0/10` accepted flips caused by the repair loop — RED**, per the bar stated above.
Safety held throughout (0 ungrounded facts, 0 timeouts, real multi-round iteration up to all 6
rounds, the new `insert_activity` op fired at least once). A measurement pitfall was caught and fixed
while writing it up: 2 of 10 raw "accepted" outcomes were the deterministic solve alone succeeding at
the repair arm's larger budget, not an LLM-caused flip — the script now reports both the raw and
LLM-attributed counts and the verdict uses only the latter. `TPC_P2_LLM_REPAIR_LOOP` stays library
default off; the `insert_activity` op and the generalized `max_attempts` loop remain in the codebase
(correctness-neutral, tested, off-path). See
[the screen](../results/phase2_baselines/screens/20260808_r27_llm_repair_loop/README.md). Per its
own bar, this is a stop, not scaled to `n=30`.

### Report baselines — no new solver slot

The report already includes the two fair oracle-free comparisons the repository can run: `Act` (`n=8`
per register) and upstream `RuleNeSy` (`n=4` per register), each against TPCAgent on identical uids.
`UrbanTrip` is not a valid Phase 2 arm here: its natural-language translation path is commented out and
its symbolic search expects oracle constraints. Running it with `oracle_translation=True` would be an
oracle-assisted ablation, not a baseline for the held-out contract. Do not spend a slot on it or imply
comparability. Re-run the existing RuleNeSy command with `--workers 1` only if a report artifact is
missing; its multi-worker path is not reliable. ReAct is substantially more expensive and the direct
JSON planning architecture already fails commonsense on `16/16`, so it is lower value than R27.

<a id="r24--does-a-query-above-300-s-ever-flip-the-owners-question-open"></a>
### R24 — does a query above 300 s ever flip? (the owner's question) *(closed 2026-08-07)*

**Registered 2026-08-07 because the owner asked whether more time and fresh seeds could fix failing
constraints, and the honest answer was that we had never tested it.** Across all 25 recorded rows the
per-query cap is `300.0 s` and no pass ever exceeded it — not by choice but because
[P4](tpc_phase2_roadmap.md#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass)
makes a higher budget structurally unreachable. This row measures the untested regime.

**Cheapest form first — a per-query ladder, not a whole run.** `--budget-sec` is already the per-query
cap, so no code change is needed to measure it. Call the per-query runner directly rather than
`phase2_quick_eval.py` — that tool requires `--flag` for its paired A/B design, and an inert flag still
runs two identical arms per budget (double the wall clock for no signal); a single-arm ladder is a
plain sweep over budgets, so call `solve_phase2.py` once per budget with a distinct `--method` per arm
(no `--resume`, so each arm always re-solves fresh rather than risking one budget's plan being reused
by another — see `_run_whole_run`'s docstring on the same collision):

```bash
for B in 300 900 2700; do
  .venv/bin/python agent_env/scripts/solve_phase2.py \
    --split tpc_phase2_familiar_100 --method "phase2_e2e_r24_ladder_b${B}" \
    --uids-file <failing-30-uids.txt> --budget-sec "$B" --lang en
done
```

(Shown as one process for clarity; the closed row below split the 30 uids across `cores − 1` concurrent
`solve_phase2.py` subprocesses per budget arm — one uid per subprocess — since the per-query mode has
no internal parallelism of its own.)

Run it on the **failing** subset, not a random one: take the uids that fail their constraints in
[R19](#the-closed-queue-r1r19)'s plan directory, since a query that already passes at `120 s` tells you
nothing about the ceiling. **Read flips, not the mean**: how many of the failing queries flip to
fully-passing at `900 s` and at `2700 s` that did not at `300 s`.

| Outcome | Read | Action |
| --- | --- | --- |
| flips grow roughly linearly with budget | the search was clock-bound after all, at a scale we never tried | land P4, then re-measure the envelope ladder post-P1, and move P5 up |
| a few flips at `900 s`, none beyond | there is a modest, bounded gain | land P4, then identify which internal mechanism used the time |
| same plans and same solve time | an unchanged internal limit stopped both arms | run R25; do not close P5 from the outer-timeout result |

**Then, only if the ladder is positive**, spend a whole-run slot on the paired form: the same 5 h
envelope with the cap raised, against [R19](#the-closed-queue-r1r19). Note that P4 also changes the
*number* of passes, so that row measures the cap and the growth-rule interaction together — which is the
shipping behaviour, and therefore the right thing to measure.

**One caveat that belongs in the reading, not in the design.** On the held-out distribution a large
share of clause failures are plausibly clauses we never extracted, and search cannot satisfy a clause
that is not in the objective. So a positive ladder result on familiar-100 does **not** imply the same
gain held-out, and a negative one does not close the question for a *correctly extracted* constraint
set. This row measures the solver, not the extractor.

**Result** ([`20260807_r24_budget_ladder`](../results/phase2_baselines/screens/20260807_r24_budget_ladder/README.md),
`git_sha 54be4514`): **`0` flips at `900 s`, and plans are byte-identical to `300 s` modulo the timing
field** — strong evidence that the outer timeout is not the active limit.
`solve_sec` mean `107.8 s` (`300 s` cap) vs `107.4 s` (`900 s` cap), max observed `192 s` either way,
`0/30` timeouts at both budgets, `overall_true` moved by exactly `0.0000` on every one of the 30
previously-failing queries. Code inspection supplies the missing mechanism: both arms retained
`TPC_MAX_RESTARTS=400` and the default CP-SAT cap of `30 s`, so both replayed the same deterministic
work and stopped at the restart boundary. **The `2700 s` arm was correctly not run**: with unchanged
internal limits it would replay the same work again. The original inference "therefore close P5" was
too broad. R24 closes only "raise the outer timeout"; R25 tests whether deeper CP or restart search
can use the envelope.

**Two methodology notes for whoever reruns this.** (1) The failing subset was derived at **zero solve
cost** by re-scoring R19's own already-written plans rather than guessing — this independently
reproduced R19's official `FPR 44.0` exactly (`44/100` passing), which is worth checking first on any
rerun as a sanity gate. (2) This row calls `agent_env/scripts/solve_phase2.py --budget-sec <B>`
directly per arm, **not** the `phase2_quick_eval.py --off 0 --on 0` form sketched above: that form
requires a `--flag`, and an inert flag name still runs two literally-identical arms (baseline and
candidate configured the same way), doubling wall clock for zero signal — and a *real* promoted flag
set to `off 0`/`on 0` would deviate from the shipped default in both arms. Calling the per-query
runner directly, once per budget with a distinct `--method` per arm (avoiding the resume/directory
collision documented in `_run_whole_run`'s docstring), measures the same thing without either problem.

<a id="r23--what-else-separates-the-held-out-set-open-static-1-h"></a>
### R23 — what else separates the held-out set? *(closed 2026-08-07, static, ~1 h)*

The leaderboard closed the "is it phrasing?" question with a qualified yes, and opened a sharper one:
**held-out C-LPR is below our worst local free-prose measurement**, so density or unseen families must
carry a comparable share. This run is cheap because it needs no solve.

Reconstruct, from released data only, what a query set would have to look like to score
`C-LPR 55.2 / FPR 0.0` under our current extractor, and check which released register that resembles:

1. For each released set, compute the *distribution* of clauses per query (not just the mean) and the
   per-family clause mix. `scripts/phase2_generalization_probe.py` already emits the per-family diff;
   add the density histogram.
2. For each set, compute what our own C-LPR would be **restricted to queries with ≥ 10 clauses**, since
   `FPR = 0.0000` implies the held-out set is at least that dense. If our C-LPR on the dense tail of
   HF `medium` approaches `55`, density explains the residual and nothing exotic is needed.
3. List families present in the *oracle* of any released set that our extractor has **never** produced
   on any set. A family we cannot express at all is invisible to every screen we run.

**Acceptance:** a ranked, quantified list of candidate residual causes, and for each an estimate of its
C-LPR cost. **Kill criterion:** if the dense tail of HF `medium` already reproduces `C-LPR ≈ 55`, stop —
density is the answer, and the action is to re-tune against dense queries rather than to hunt families.

**Result** ([`20260807_r23_residual_causes`](../results/phase2_baselines/screens/20260807_r23_residual_causes/README.md),
`git_sha dbacc183`): **kill criterion did not fire.** Ranked findings:

1. **`cuisine_preference`/`restaurant_type` extraction is 100% uncovered on every one of the four HF
   free-prose sets (`0/30`, `0/33`, `0/27`, `0/7`), while ~100% covered on the two locally-phrased sets
   (familiar-100 `67/67`, local_released_150 `21/22`) — a complete, phrasing-conditional precision
   failure of one extractor pattern, not a density effect and not a missing family. Fully explained,
   fixed cost: `2.56` C-LPR points on the combined HF sets (`97/3790` clauses). The single cleanest
   residual-cause candidate found, and the cheapest to act on.
2. **Density is real but not shown sufficient.** The `≥10`-clause regime `FPR = 0.0000` implies is
   almost unobserved locally — only `27/150` `hf_medium` queries ever reach it, capping at `12` clauses,
   and every other free-prose set never reaches double digits. Its dense-tail extraction-*ceiling*
   proxy (family-presence only, an optimistic upper bound on C-LPR) is `67–77`, still `12–22` points
   above the held-out floor (`55.2`) — closing that gap needs a scored run, not just this static check.
3. **Unseen constraint families: ruled out.** Zero families are unreachable by our parser across all
   six released sets combined — the "constraint families we have no local example of" hypothesis is
   not needed to explain any local gap (cannot rule out the held-out set containing something no
   released set has either).

Not run here (out of this screen's static scope, flagged as the natural follow-up): a scored e2e pass
on `hf_medium`'s 27-query dense tail, to replace the ceiling proxy with real C-LPR.

<a id="r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change"></a>
### R22 — the standing phrasing tripwire *(recurring, ~2 min, run with every parser change)*

The process failure behind the held-out gap was that **no gate could see a phrasing dependency**. This
closes it, and it costs seconds:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
  --out-dir results/phase2_baselines/screens/<date>_generalization_<change>
```

Require: familiar-100 parse gaps still `0/1109` **and** no free-prose set's gap count rising. A parser
change that improves familiar-100 while worsening free prose is now a **regression**, whatever its
familiar-100 number says. Commit the screen next to the change.

**[P18](tpc_phase2_roadmap.md#p18--make-phrasing-robustness-a-gate) turned this from a documented
habit into an executable gate.** `results/phase2_baselines/phrasing_generalization_floor.json`
records the floor per set; check it (and fail on any regression, skip cleanly on a dataset-snapshot
mismatch) with either:

```bash
make phase2-generalization-gate
# or directly:
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
  --check-floor results/phase2_baselines/phrasing_generalization_floor.json
```

`tests/phase2/test_phrasing_generalization_gate.py` runs the same check inside the default
`pytest tests/phase2` suite (skips, stating why, when the local HF cache is unavailable), so this is
no longer only a human-read table — a violation now fails CI-equivalent tests too. After a change
that improves a set, ratchet the floor down (never up) with
`... --check-floor <path> --update-floor`, and commit the refreshed screen next to it.

**Last run 2026-08-07, first post-P20** ([`20260807_generalization_post_p20`](../results/phase2_baselines/screens/20260807_generalization_post_p20/README.md),
`git_sha f413eb2a`; this run also seeded the floor file above): **GREEN**. `familiar_100` stays
`0/1109`. Every free-prose set improved over the prior post-P15 run: `local_released_150`
`6/522 → 5/522`, `hf_easy` `127/1579 → 97/1579`, `hf_medium` `126/1264 → 78/1264`, `hf_human`
`99/687 → 81/687`, `hf_preference_base50` `19/260 → 14/260`. No set regressed. The prior screen spans
three landed items (P16, P19, P20), but the screen's README checks attribution rather than assuming
it: only P20 touches code this probe's default (flags-off) path exercises, so this delta is P20's
alone — a second, unfitted confirmation that a fix scoped as family-recall (not phrasing) generalizes
past familiar-100. This is a recurring instrument, not a one-time run — re-run it on the next parser
change, same acceptance criteria.

**Refreshed 2026-08-08, first post-P24**
([`20260808_r22_refresh_post_p24`](../results/phase2_baselines/screens/20260808_r22_refresh_post_p24/README.md),
`git_sha fecdf7ca`): **PASS**, floor unchanged. `make phase2-generalization-gate` and a fresh probe
run both reproduce the floor file exactly (`familiar_100 0/1109`, `local_released_150 5/522`,
`hf_easy 99/1579`, `hf_medium 131/1264`, `hf_human 109/687`, `hf_preference_base50 14/260`) — the
floor file was already ratcheted to these post-P24 values by P24's own second commit (`0f7bfcbb`), so
this run confirms `main` is at the floor rather than drifted past it, not that anything moved.

This refresh also ran the second still-missing condition below for the first time
(`scripts/phase2_unsatisfiable_names_probe.py`, not yet wired into the automated gate), and it
surfaced a large, previously-unmeasured finding: **the free-prose unsatisfiable-required-name share
this document and `CLAUDE.md` cite as `23–50 %` ([roadmap §6](tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves),
measured pre-P24) is now `3–12 %` on the current tree** (`hf_easy 42→11 %`, `hf_medium 35→3 %`,
`hf_human 23→8 %`, `hf_preference_base50 50→12 %`; `local_released_150 16→11 %` with the harness's
real `entity_resolution=True` default) — identical whether `entity_resolution` is on or off, which
rules out entity resolution as the cause (matching R29) but does **not** by itself isolate P24 from
P20/P22, which also landed in this window; one data point argues against a clean "P24 alone" story —
P24's own screens claim `local_released_150` byte-identical in isolation, yet this run's baseline
(no-ER) measures that set at `20/150` against the pre-window `24/150`, so something else in the
window moved it. Read this as attributable to the **post-P20/P22/P24 parse path**, not to entity
resolution; precise per-item attribution needs a pinned-SHA re-run, not done here. P24 was scoped and
gated as a satisfiable-but-unrequested-constraint fix and still has no e2e arm of its own
([roadmap P24](tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints)) —
this is a side effect nobody measured until now, on the *other* half of the precision story
([P22](tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints)'s
infeasibility-by-invention). It does not retire P22 or reopen R30 (R30's own `103`-query target set
was already drawn fresh on this same post-P24 tree, so its negative result already reflects these
smaller numbers) — it does mean the `23–50 %` figure in `CLAUDE.md`'s "Precision, found 2026-08-07"
paragraph and in roadmap §6 is stale and should be corrected by the docs workstream to cite `3–12 %`.
Full tables and per-set breakdown: the screen README linked above.

**Two conditions are still missing, and they are the reason this gate would not have caught the
largest defect we have found** (2026-08-07). The floor compares `n_parse_gap` per set, which is a
recall-only criterion: a change that *invents* constraints rather than missing them passes it
silently. Add both to the floor file and the test as a follow-up to P18 — the instruments exist and
each costs the same two minutes as the check that landed:

- **No set's `spurious` count may rise.** `phase2_generalization_probe.py` already emits it per set and
  per family; it needs one more recorded number per set, next to `n_parse_gap`.
- **No set's unsatisfiable-required-name count may rise:**

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py \
  --out-dir results/phase2_baselines/screens/<date>_unsatisfiable_names_<change>
```

  This is the condition that would have flagged the `23–50 %` of free-prose queries carrying a
  provably unsatisfiable required-POI name
  ([roadmap §6](tpc_phase2_roadmap.md#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves)).

### R21 — spend the unspent envelope *(needs P17)*

Every run ends early, and under parse gaps it ends early *and* mis-ranks its queue (see the amplifier
above). Read this row as **per-pass improvement counts**, not as a total: the question is whether
re-polishing queries the scheduler believes are finished converts idle time into preference points.
Acceptance: `overall` up with `FPR` not down. Expected small — preference terms are capped at `FPR`.

<a id="r9--the-whole-run-gate-for-seed-diverse-exploration"></a>
### R9 — the whole-run gate for seed-diverse exploration *(closed 2026-08-07, per R25)*

```bash
TPC_P2_EXPLORE=1 .venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r9_seeds --label "seed-diversified explore, 5h"
```

**Read flips per pass, not `overall`.** One extra sampling pass is measured at ~1 flip per 68 queries;
the question is whether that accumulates over the ~10 passes the idle envelope affords. Independent
draws give `5–10` flips (`+1.7..+4.2` overall, promoting P5); an exhausted reachable set gives `1–2`
and closes the "we aren't using our time" question for good. Demoted below R20–R22: it re-attacks the
*search*, and the evidence now says the binding limit is *coverage*.

**Closed, not merely deferred.** R24 found zero flips because it replayed the same 400 deterministic
restarts; it did not measure a new seed or a raised restart cap. R9's own precondition was "R25's
restart arm flips at least one uid" — [R25](#r25--separate-the-cp-restart-and-outer-budget-limits)
raised restarts 10x (`400 -> 4000`) directly and measured `0/10` full-query flips (one clause-level
move on one uid, not a flip). The precondition failed, so R9 does not become meaningful; do not run it
on this evidence. Re-open only if a future run establishes a genuine restart-axis flip under a different
configuration (e.g. after a P20/P6 move changes what "failing" means for these queries).

### What not to spend a slot on

- **Any local row read as a held-out estimate.** That is the error this cycle paid for. A local row
  measures a *configuration*, never a *distribution*.
- **Any free-prose FPR read against `100`.** The HF splits cap at `38.67–46.0` under `--lang en`
  ([dataset boundaries](#3-hugging-face-chinatravel)). Quote the ceiling with the number or do not
  quote the number.
- **Any candidate gated against R19.** R19 is `git_sha ae0bd319`, five changes behind `main` now.
  Gate against [R28](#r28--a-whole-run-row-on-the-current-main) (`git_sha aed4363e`) instead — it is
  the current baseline.
- **A repeat of a run you already have.** Post-P0 the solver is bit-for-bit reproducible
  ([R7](#the-closed-queue-r1r19)); the same configuration on the same host returns the same number.
- **Any whole-run row whose configuration you cannot read off its own telemetry.** Check
  `solver_flags` first, score second.
- **`audit`-mode LLM parsing, free-form LLM-only JSON planning, or another one-shot refine prompt.**
  All three measured at or below the deterministic floor. R27 is different: typed edits,
  deterministic grounding and iterative rejection feedback.
- **Another outer-timeout ladder with unchanged internals.** R24 already proves `300/900/2700 s`
  outer caps are equivalent while CP remains `30 s` and restarts remain `400`.
- **A bigger CP-SAT time slice or a further-raised restart cap on this evidence.** R25 tested both
  internal limits directly (`300 s` CP, `4000` restarts — 10x each) and found `0/10` flips on either
  axis; the recurring blocker (timed-window placement) does not respond to more of the same move.
  Scaling either limit further without a new move is the "blind compute expansion" R25 closed.
- **Preference-packing flags (`TPC_PACK_*`).** Every preference term is zeroed on a failing query, so
  each is capped by FPR. Raise FPR first.
- **The old per-query `900 s` pinned gate as a ship signal.** It measures a contract the competition
  does not use. Keep it for solver A/Bs only.

## The falsified prediction — a post-mortem

This section previously estimated `v1`'s held-out score at **`58–68` (`±2σ`), centre `63.6`**. The
answer was **`33.2473`**. Keeping the reasoning visible is worth more than deleting it:

| What the estimate modelled | Size claimed | What actually happened |
| --- | --- | --- |
| Solver nondeterminism | `0` (three bit-identical 5 h repeats) | **Correct and irrelevant.** Reproducibility says nothing about generalization. |
| Query sampling at the same distribution | `±2.6` overall at `1σ` | **The wrong error model.** This is binomial noise on 100 draws from an assumed-matching distribution. The real error was distributional. |
| Designing a mechanism from the `val` residual | "mildly optimistic, not invalidated" | **Understated.** The held-out tripwire (R13) that was supposed to catch this used `familiar_100_test` — a 20-record *subset of the same templated split*, so it could only ever detect fitting `val`'s residual, never fitting familiar-100's phrasing. |
| Evaluation host | neutral | Unknown; a partial failure is still not excluded. |

**Three transferable lessons, and they are already actioned:**

1. **A held-out fold of the same artifact is not a held-out distribution.** Our tripwire was a subset
   of the split we tuned on. It passed. That is now [R22](#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change),
   which tests *phrasing*, not sampling.
2. **A component's measured quality is scoped to the data it was measured on.** Parser F1 `0.9949` was
   true — on templates. It was cited throughout this project as though it were a property of the
   parser.
3. **The confidence interval was the most confident thing in the document and had the least evidence
   behind it.** A stated `±2σ` band invites everything downstream to treat the centre as known. Where
   a distributional assumption is load-bearing, say so instead of quantifying around it.

Record the leaderboard standing next to this when it publishes. It is the only external calibration
this project gets.

**Update, 2026-08-07 — the leaderboard breakdown scored the post-mortem itself.** The bounded inversion
this doc performed on the aggregate alone predicted, for the `FPR = 0` case, `C-LPR ≈ 53.9`. The
published value is `55.20`, and the inversion's structural conclusions all held: environment terms
roughly intact, both logical terms collapsed, total infrastructure failure excluded. So the *inference*
method was sound; what failed earlier was the *assumption* that familiar-100 represented the held-out
distribution. Worth keeping straight, because the two failures have opposite lessons — reason carefully
from partial evidence, and do not assume a distribution you have not sampled.

## The closed queue (R1–R19)

Run 2026-08-04/05/06/07, primarily on a 4-core box (3 workers), plus R3 on a 10-core Mac (8 workers),
`evaluator_parity: c89cfca`, rows under `results/phase2_baselines/full_runs/`. **Nothing here needs
re-running.** Local scores only; see the [held-out fact](#the-one-fact-that-reorganizes-this-document)
for what they do and do not predict. The table also carries
[R28](#r28--a-whole-run-row-on-the-current-main), the current-`main` whole-run row that replaced R19
as the live gate baseline — same numbering range in spirit (a whole-run row measured on this host),
kept out of the header's own `R1–R19` range only because renumbering it would break every existing
link into this section.

| Run | Row | Result |
| --- | --- | --- |
| R1 reference, 5 h | `20260804T201638Z` | `overall 57.99`, FPR `33.0`, `constraints_ok 35/100`, `empty_plans 0/100`; used **`26 %`** of the envelope |
| R2 envelope sensitivity | `20260804T213636Z`, `20260804T221103Z` | `57.35 / 57.86 / 57.99` at `1/3/5 h` — **flat** |
| R3 worker scaling, 5 h | `20260805T215107Z` | 8 workers / 10-core Mac: `overall 64.08`, FPR `44.0`, `constraints_ok 47/100`, `1112 s`. Healthy, non-regressing ≥8-worker deployment; **not** a worker-only causal gain (host differs, both hit the same per-query caps) |
| R4 pass shape | 5 rows `20260804T231910Z`…`20260805T032037Z` | arms A/B were accidental no-ops; arm C (`TPC_P2_FAST_TRIAGE=0`) `58.40` vs `57.81`, inside the then-variance — do not carry forward |
| R5 held-out fold, pre-P1 | `20260805T042106Z` | `overall 62.59`, `constraints_ok 10/20` |
| R6 packaged archive | no row (checks the zip) | unpacked and run with a stripped `PATH`: `valid_output=True` |
| **R7 variance baseline, 5 h ×3** | `…081535Z`, `…094549Z`, `…110654Z` | **bit-for-bit identical across three repeats**: `overall 57.74985419574877`, FPR `32.0`, `constraints_ok 36/100`. **sd = 0, range = 0** post-P0 |
| **R8 window-aware move** (`TPC_WINDOW_ANCHOR=1`) | `20260805T123142Z` | `overall 63.58458530360117` (**`+5.83`** over R7), **FPR `43.0`** (**`+11.0`**), `constraints_ok 46/100` (`+10`). Promoted to harness default; the first arm to move FPR |
| R10 oracle ablation, 1000 queries | `20260805T135254Z` | `tpc_phase1` through the no-oracle path: `overall 85.20` against the oracle-fed pipeline's `98.98` — a **`13.78`-point** removing-the-oracle cost. `git_dirty: true`, structurally (see note below) |
| R12 promotion equality, no env vars | `20260805T170120Z` | **bit-identical to R8** with nothing exported; all four promoted `solver_flags` `true`. The promotion path and the explicit-environment path are the same configuration |
| R13 held-out fold, post-P1 | `20260805T182748Z` | `constraints_ok 13/20` (R5: `10/20`), `overall 70.54`, FPR `55.0`. Read at the time as "the move generalizes"; **see the [post-mortem](#the-falsified-prediction--a-post-mortem)** — this fold is a subset of the same templated split and could not test phrasing |
| R14 P8+P9 gate | `20260806T052925Z` | `overall 64.13167839953107` (`+0.5471`), FPR `44.0` (`+1.0`), **`constraints_ok 46/100` unchanged**. GREEN, but the screen *over*-predicted it and the gain is FPR-plus-preference, not new passing queries |
| R15 held-out fold, post-P8/P9 | `20260806T065521Z` | All seven metrics **bit-identical to R13**; `19/20` plans byte-identical. **The tripwire never armed** — P8/P9 fire rarely on this distribution |
| R16 `v2` candidate | `20260806T082724Z` | `overall 64.14997555172528`, FPR `44.0`, `constraints_ok 51/100`, `git_sha 241c0524`. P10 does not interact destructively with P8/P9 at `n=100`; `constraints_ok +5` is a **self-score** effect, explicitly not a promotion signal |
| **R17 ship candidate** | `20260806T115309Z` | `overall 64.17251838310492`, `FPR 44.0`, C-LPR `90.08`, `constraints_ok 50/100`, `empty_plans 0/100`, `git_sha efbfea96`, `1.38 h` of `5 h`. **The best local row, and the configuration `v1` behaviour is closest to** |
| R18 released-150 regeneration | `20260806T132917Z` | `tpc_phase2_test` (150): `overall 90.5603`, FPR `90.67`, `constraints_ok 125/150`. P12's residual cross-tab is `4/150`. **Do not read `90.56` as generalization** — same template, a third the constraint density |
| **R19 phrasing-fix regression check, 5 h** | `20260807T043142Z` | `git_sha ae0bd319` (`main` tip at launch; also carries **P13** `27d31efe`/`de3c8fcb`, which merged *after* R17's measured `efbfea96` and was flagged in `e7faa9f1` as unmeasured on this tree — so this row confirms P13, not only the phrasing fix). All 7 official metrics **byte-identical** to R17: `overall 64.17251838310492`, FPR `44.0`, C-LPR `90.08115419296664`, `constraints_ok 50/100`, `empty_plans 0/100`, `1.36 h` of `5 h`. All 100 plans byte-identical to `results/phase2_e2e_r17_ship/` modulo per-attempt timing fields (`parent_parse_failed_uids: []`, confirming P13's changed branch never fires here either). **GREEN — expected, and read narrowly**: familiar-100 contains the phrasing the fix targets (bare budgets, plain room-type wording) in `0/100` queries, so this shows the fix and P13 are true no-ops on the one register the parser was already perfect on. It is not evidence the phrasing fix helps — that evidence is the free-prose screen's `41.62 → 49.99`, which this run does not touch |
| **R28 current-`main` baseline, 5 h** | `20260807T152009Z` | `git_sha aed4363e` (`main` tip at launch; carries P15/P16/P18/P19/P20 and R25/R26 on top of R19's `ae0bd319`). All 7 official metrics **byte-identical** to R19 and R17: `overall 64.17251838310492`, FPR `44.0`, C-LPR `90.08115419296664`, `constraints_ok 50/100`, `empty_plans 0/100`, `1.34 h` of `5 h`. All 100 plans byte-identical to R19's modulo the timing field; `parent_parse_failed_uids: []`; `window_anchor`/`window_push`/`window_insert` all `true`. **GREEN — expected, and read narrowly**, same reasoning as R19: every change on this tree since R19 touches families or fallback paths (P20's free-prose fallbacks, P15's phrasing patterns) that familiar-100's rigid template structurally cannot exercise, so flat here is confirmation, not evidence those changes are inert on free prose. **Closes the drift** ([R28's own section](#r28--a-whole-run-row-on-the-current-main)) and becomes the new baseline for R29/R30/R31 |

**Drift note, same shape as `e7faa9f1` — closed by R28.** P15 (`a4d028bb`/`8688439c`),
P16 (`3c1d3e8e`…`d65785c8`, library-default off), P19 (`f9e8233f`, analysis only), P20 (`e6cc0e65`)
and P18 (`dfdace2a`, gate and tooling only) all merged after this run's `ae0bd319`, so R19 stopped
being a valid gate baseline for any new candidate. [R28](#r28--a-whole-run-row-on-the-current-main)
(`20260807T152009Z`, `git_sha aed4363e`) remeasured the current `main` directly rather than reasoning
about it from each change's own screen, and came back byte-identical to R19 on every metric and every
plan — confirming, rather than assuming, that P15/P20's family/fallback scope and P16/P18/P19's
non-behavioral scope really do structurally miss familiar-100. **R28 is now the baseline**; R19 is
retained above as history, not as something to gate against.

**On R10's `git_dirty: true`.** `eval_tpc.py`'s `update_suboptimal_split_file` rewrites
`chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` on every full-split scoring call, so
the dirtiness is **structural**: any rerun from any commit reproduces it. It touches no solver code or
plan output. A clean row would need an Implementation change (stop writing during a read-only scoring
pass), not a rerun.

### What the closed queue established

1. **The run self-terminates at `26 %` of the envelope**, because `_choose_pass` drops a candidate
   whose new budget cannot beat its last by `MIN_BUDGET_GROWTH` and every candidate is already at the
   cap.
2. **Scheduling the unchanged search does not recover the idle time.** `2.5×` the short budget bought
  `4.2×` the restarts and flipped **one query in 68**; R24 then showed an outer `900 s` cap still
  stops at the same 400-restart fixed point. R25 later closed the two remaining internal axes directly
  (`10×` CP time, `10×` restarts): `0/10` flips either way. A configuration-diverse portfolio remains
  unmeasured.
3. **`improved` is not a score signal; `constraints_ok` is** — and `constraints_ok` is a *self*-score,
   which the [generalization probe](#the-one-fact-that-reorganizes-this-document) showed can be
   catastrophically wrong (`86.67` self-reported against `6.67` real) exactly when extraction misses.
4. **Post-P0 the same-config spread is zero**, so a single run resolves any nonzero delta and no arm
   needs repeats.
5. **Representation beat compute, on the in-distribution split.** R8's `+11.0` FPR from one new
   solver move, against `+0.64` overall from five times the budget.
6. **P8/P9 and P10 are real but thin** (R14/R15/R16): `+0.57` overall combined, `constraints_ok` flat,
   firing on `1/20` held-out-fold plans.
7. **Removing the oracle costs `13.78` points** on `tpc_phase1` (R10).
8. **Local rows over-predicted the held-out score by ~2×** — the finding that supersedes how items
   1–7 should be weighted.
9. **The phrasing fix and P13 are confirmed true no-ops on familiar-100** (R19): byte-identical plans
   and metrics to R17, closing the unmeasured-drift flag `e7faa9f1` raised. This says nothing about
   whether either helps elsewhere — the phrasing fix's gain is the free-prose screen's
   `41.62 → 49.99`, not any number in this queue.

### Closed LLM and baseline arms (screens, 2026-08-06)

From [`screens/20260806_llm_arms/`](../results/phase2_baselines/screens/20260806_llm_arms/README.md),
`Qwen/Qwen3.6-27B` on DeepInfra (the organizers' evaluation checkpoint), `temperature 0`, `$3.55`
measured spend, every arm's call count verified at the wire. **Small `n`; these rank approaches, they
do not estimate performance.**

| Arm | Result | Verdict |
| --- | --- | --- |
| LLM as constraint extractor, free prose | parse gaps `−40..65 %`, zero clauses broken, but `matched` flat: `missing → wrong_value` | **Diagnosis, not cure.** The bottleneck is value grounding → [P16](tpc_phase2_roadmap.md#p16--ground-llm-extracted-values-into-the-closed-vocabulary) |
| `TPC_P2_LLM_PARSE` (`audit` mode), free prose | recovers `6/126` gaps vs extraction's `50/126`; damages familiar-100 F1 `0.955 → 0.917` | **Dead.** Its old RED screen was not only a wrong-dataset artifact |
| **LLM-only planning, no solver** (`Act`, 34–42 autonomous tool-using turns, `--max-steps 45`, 612 calls, zero failures) | `overall 2.64` free prose / `1.88` familiar-100 vs our solver's `48.49` / `67.71` on the same 8 queries. **`MacEPR 0.00` on both** — not one of 16 plans passed commonsense | **At the floor.** A report baseline, not a candidate |
| **Upstream `RuleNeSy`** (`n=4` per register, `$0.069`) | `9.44` free prose / `9.54` familiar-100 vs our `55.89` / `40.11`. `MicEPR 94–95` with `MacEPR 0.00` — grounds correctly, breaks one commonsense rule per plan | **External comparison column** for the report |
| Thinking mode | `75 s` per one-line call, 4 timeouts, budget exhausted at step 12 of 40, `~$1.1`/query extrapolated | Rejected on measured cost |

**One methodological catch worth keeping.** The first audit run had **306** calls fail with
`RateLimitError`, and because `parse_to_ir` swallows LLM exceptions by contract those queries silently
scored as the *deterministic* parse — the same mechanism behind an earlier phantom `+1.97`. Wire-level
call counting flagged the arm `UNMEASURED` and it was re-run. **An arm whose call count you did not
check is not a result.** A second catch: under thinking mode the `Act` loop's `stop=["\n"]` truncated
the reasoning and returned empty `content`, which would have scored the arm at zero for a harness
reason; found by inspecting three raw responses, fixed in `make_budgeted_llm`.

## Before the first run

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-submission.txt
nproc                                    # workers default to this minus one
.venv/bin/python -m pytest tests/phase2  # ~1 min, catches a broken checkout
```

Sanity-check on a short envelope first — 12 minutes, not 5 hours:

```bash
.venv/bin/python scripts/phase2_full_run.py \
  --split tpc_phase2_familiar_100_val --total-budget-sec 720 --label "plumbing check"
```

Expect a `[sweep] pass 1 (triage) ...` line and one row under `full_runs/`. A `720 s` envelope fits
only one triage pass, so high `empty_plans` there is expected.

**If a row comes back with anomalously many `empty_plans`, suspect a broken worker pool before the
solver.** A worker dying at start-up takes the whole `ProcessPoolExecutor` with it, and the run still
**exits 0** with a complete set of *pre-written empty fallback* plans. Tells: the per-pass `failed`
count, `empty_plans`, and `Exception in initializer` on stderr. See the
[pre-submission checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).

## Two measurement contracts

| | **Whole-run** (what we ship) | **Per-query** (solver quality) |
| --- | --- | --- |
| Question | what would this score in the real evaluation? | is the solver better on a query at a fixed budget? |
| Time contract | one 5 h wall clock for all 100 queries | fixed `900 s` (or `300 s`) *per query* |
| Scheduling | triage → repair → polish, best-so-far kept | one pass, split order |
| Parallelism | `CPU count − 1` worker processes | one query at a time per chunk |
| Tool | `scripts/phase2_full_run.py` (`make phase2-full-run`) | `make phase2-baseline` / `phase2-rehearse` |
| Rows | `full_runs/` | `runs/` |
| Pre-gate screen | `phase2_quick_eval.py --mode whole-run` | `phase2_quick_eval.py` |

**Rows from the two contracts are never comparable**, whatever else matches. Every whole-run row
records `kind: "full_run"`. The per-query `900 s` budget is purely a development setting — there is no
organizer per-query timeout — chosen so a change is judged with the solver allowed to converge.

### Three attribution axes

| Axis | Input | Meaning |
| --- | --- | --- |
| Ceiling | `results/best`, oracle logic, offline iteration | aspirational bound, not a harness baseline |
| Solver-only | oracle constraints, bounded solve | solver headroom with parsing removed |
| End-to-end | visible text, no oracle | the local approximation to the submitted path |

Ceiling → solver-only is bounded-solver headroom; solver-only → end-to-end is parsing and harness
loss. **The held-out gap lives in a fourth axis this list did not have: end-to-end on *unfamiliar
phrasing*.** `scripts/phase2_generalization_probe.py` is the instrument for it, and a parsing change is
promoted only on an end-to-end measurement.

## Score semantics

$$
0.10\,\mathrm{EPR\!\text{-}micro} + 0.10\,\mathrm{EPR\!\text{-}macro} + 0.25\,\mathrm{C\!\text{-}LPR} + 0.40\,\mathrm{FPR} + 0.05\,(\mathrm{DAV}+\mathrm{ATT}+\mathrm{DDR}).
$$

Three properties decide what is worth measuring:

- **C-LPR is the *conditional* logical micro.** A plan failing commonsense scores `0` on the
  `0.25`-weighted logical term *and* `0` on its EPR-macro point, however many clauses it satisfies.
- **DAV/ATT/DDR are averaged over every query**, with a zero for each non-passing query. Each is
  bounded above by FPR; perfecting one is worth at most `0.05 · FPR`.
- **ATT is `0` for a plan with no inner-city transport**, so a degenerate transport-free plan does not
  score a perfect ATT.

At our operating point one FPR point is worth about `0.85` overall. `eval_tpc.py`'s per-query score
for monotonic merging differs (it assigns both environmental slots from that query's binary
commonsense result); it ranks merge candidates and is not a second official aggregate.

**Evaluator parity moves invalidate comparisons.** Two upstream syncs landed: `764614c` (2026-07-28)
and `c89cfca` (2026-08-04, no scoring change). `EVALUATOR_PARITY_SHA` is `c89cfca`;
`scripts/phase2_gate.py` refuses to gate across the boundary, including one-sided marker presence.

## Dataset boundaries

Every measurement must name its source. **This section was wrong in a way that cost this project a
submission slot's worth of information, and the correction is the point.**

### The correction

This document previously called familiar-100 the "preferred signal" because it is the "same
distribution as final evaluation". **That claim is not supported and the measured evidence now
contradicts its practical use.** familiar-100 is the only released set whose phrasing our extractor
handles cleanly, our second confirmation set shares its template, and the held-out score came in at
about half the familiar-100 number.

familiar-100 remains the best *available* development signal — it is the closest artifact the
organizers released. What changed is what a familiar-100 result licenses: **it measures a
configuration on one phrasing register, and nothing more.** Pair every parser or constraint-layer
change with [R22](#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change).

A second correction: this doc stated the local released sets average "`~16` constraints per record
versus `~38` in familiar-100". Measured through `load_query(..., oracle_translation=True)`, which is
what the evaluator scores, the figures are **`3.48` and `11.09`**.

### 1. Official familiar-100

The organizers' [familiar-100 archive](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip)
(2026-07-15), imported unchanged under `chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/`,
selected by `tpc_phase2_familiar_100`; `_provenance.json` pins the source URL, archive SHA-256 and
every member's checksum. Records carry `hard_logic_py`, retained for scoring only. **Phrasing is a
numbered `Requirements:` list in 100/100 queries** — an enumerated near-DSL restatement of the
constraint set. `11.09` oracle clauses per query.

**Val / test partition.** `scripts/make_familiar_splits.py` splits the 100 records deterministically
(seed `20260723`, stratified by `days`) into `_val` (80) and `_test` (20); `make
phase2-familiar-splits` regenerates them. Every screen and development gate runs on val. **The `_test`
fold is a sampling tripwire only — it is a subset of the same templated artifact and cannot detect a
phrasing dependency**, which is precisely how one shipped.

### 2. Repository-local released data

Released Phase 1 English queries with oracle fields under
`chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/`; `make phase2-splits` partitions them into
`tpc_phase2_val` / `tpc_phase2_test`. Despite the local `test` name these are **not** organizer
held-out data. `3.48` clauses per record and `15 %` template phrasing, so they are both easier and
partly familiar-phrased — which is why `tpc_phase2_test`'s `90.56` is not a generalization signal.

### 3. Hugging Face ChinaTravel

[`LAMDA-NeSy/ChinaTravel`](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel) — `default` config:
`easy` 300, `medium` 150, `human` 154, `preference_base50` 50, all carrying `hard_logic_py` and
`nature_language_en`. **Promoted from "OOD probe, never a tuning target" to the project's only
phrasing-robustness instrument**, because upstream's `easy`/`medium`/`human` splits are not resolvable
locally (the UID lists ship, the query JSONs do not) and these are the same query sets.

`scripts/materialize_hf_split.py` materializes a subset as a local split;
`scripts/phase2_generalization_probe.py` runs the static probe. **Two artifacts to know before
trusting a number from it:** the `hard_logic_py` literals are native **Chinese** (`自然风光`) while
`nature_language_en` is English, so scored in `en` those clauses can never pass regardless of our
parser — correct for it by restricting to ASCII-literal clauses; and `15/150` `medium` English texts
are a rendered plan title rather than a query, so ~10 % of that set's gap is unreachable by any parser.

**The first artifact is now priced, and it is larger than "correct for it" suggested** (2026-08-07,
`scripts/phase2_oracle_literal_translation.py`). It does not merely bias a parse-diff; it caps the
official metrics on any scored run:

| HF split | n | oracle clauses | unsatisfiable under `en` | negated (trivially true) | queries blocked | **FPR ceiling** | C-LPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `easy` | 300 | 1579 | `180` | `0` | `180` (`60 %`) | **`40.00`** | `88.60` |
| `medium` | 150 | 1264 | `126` | `0` | `92` (`61 %`) | **`38.67`** | `90.03` |
| `human` | 154 | 687 | `117` | `0` | `91` (`59 %`) | **`40.91`** | `82.97` |
| `preference_base50` | 50 | 260 | `27` | `0` | `27` (`54 %`) | **`46.00`** | `89.62` |

**So `hf_medium`'s measured `FPR 16.67` is `43 %` of what is achievable there, not `17 %`.** Every
free-prose FPR in this document was reported against `100`. Not one of the blocking clauses is negated,
so the cap only ever suppresses. [P23](tpc_phase2_roadmap.md#p23--make-the-free-prose-register-scoreable)
lifts it: `database/` and `database_en/` are row-parallel, so a **1:1** zh→en literal map (`11957`
entries; the builder raises rather than guessing) is derivable from the shipped data, and `85 %` of the
blocking clauses map as-is. [R31](#r31--the-first-real-free-prose-fpr-gate) is the gate.

It is still not a tuning target and still not the held-out distribution. Delete materialized splits
after scoring so none ships in an archive.

### 4. Organizer final held-out set

Evaluated only through the organizer-run no-oracle harness on `Qwen3.6-27B` via SGLang. **One
observation now exists: `33.2473` for `v1`.** No local split, HF subset or familiar-100 result proved
that number, and the one prediction attempted was off by `~30` points.

## Ledger comparability

Compare rows only when they match on: **measurement contract**; source revision, data source, split,
fold/limit, language; **evaluator contract** (rows straddling `764614c` or `c89cfca` are never
comparable — each row's `evaluator_parity` names its side); budget, repeat count, parallelism and
fresh-output policy; parser/solver/feature flags (read them off the row's per-query `solver_flags`,
never off the label); LLM backend/model and cache policy when an LLM is enabled.

Whole-run rows additionally require the **same machine**. `git_dirty: true` means the row is not
reproducible from a commit — rerun from a clean tree before deciding anything with it.

A row must expose enough telemetry to explain its score: valid-output rate, parse failures, timeout
and recovery counts, fallback use, stage timings, LLM attempts/failures, and the three attribution
axes. Low-`n` rows are smoke checks, not promotion evidence. Field semantics:
[baseline ledger guide](phase2_baselines/README.md).

**Two promoted-default baselines exist; pick the one matching your host, not the highest number.**
The 4-core row moved to [R28](#r28--a-whole-run-row-on-the-current-main), the current-`main` row that
replaced the stale pre-P15/P16/P18/P19/P20 R19 row (byte-identical score, so nothing about the number
changed — only its `git_sha` currency did). The 10-core row is still R3, unrefreshed since no whole-run
row has been produced on that host since `main` `0d6f1837` — a fresh row is owed there too, on the same
gating logic that motivated R28.

| Host | Workers | Baseline row | `overall` / `FPR` / `constraints_ok` |
| --- | --- | --- | --- |
| 4-core Linux | 3 (`CPU−1`) | **R28 `20260807T152009Z`** (byte-identical to R19 `20260807T043142Z` and R17 `20260806T115309Z` — the fix/feature work since neither of them moves familiar-100, all seven metrics and all 100 plans) | `64.17251838310492` / `44.0` / `50/100` |
| 10-core Apple Silicon | 8 | R3 `20260805T215107Z` — **stale**, predates P15/P16/P18/P19/P20; refresh before gating anything on this host | `64.0773462893086` / `44.0` / `47/100` |

On a third machine, produce your own flags-off baseline there first; a cross-host delta is not
evidence. Every row must show `solver_flags.window_anchor`, `window_push` and `window_insert` `true`
unless it is deliberately a flags-off arm.

## Gates

```bash
make phase2-gate BASELINE=results/phase2_baselines/runs/<base>.json \
  CANDIDATE=results/phase2_baselines/runs/<candidate>.json
```

When both inputs supply `continuous_score` it blocks and FPR is advisory; otherwise FPR blocks. More
parse failures or timeouts always block. The no-new-timeouts guard is evaluated **relative to the
budget both rows ran at** — pair rows at the same budget.

Early-stop modes are diagnostic only and never gate-compared against normal rows: `--fast-fpr`
(`TPC_SOLVE_STOP_AT_ACCEPT`) skips `_pack_plan`, so it cannot measure the repair passes;
`--fast-fpr-packed` stops at first accept but still packs. Both force a label prefix and preserve the
binary FPR signal.

## Quick A/B screen

The pinned gate is authoritative but slow. The screen is the pre-filter that decides *within 1–2 h*
whether an off-by-default flag is worth a real run. **It ranks and triages; it never promotes.** Tool:
`scripts/phase2_quick_eval.py` (`make phase2-quick-eval P2_FLAG=<env var>`).

It cuts wall clock on three axes and trusts only the **paired delta**: a deterministic subset (`--n`,
default `40`), a reduced budget (`--budget-sec`, default `60`), and a same-subset/same-seed off-vs-on
pair where only one flag changes. The reduced budget keeps the signal because the deterministic flags
act at the **acceptance boundary** inside `_pack_plan`.

```bash
make phase2-quick-eval P2_FLAG=TPC_PIN_TIMED_WINDOWS P2_N=40 P2_BUDGET=60 P2_PARALLEL=3
# stack on an already-on flag:
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_REPAIR_TRANSPORT_GAPS \
  --extra-env TPC_PIN_TIMED_WINDOWS=1 --n 40 --budget-sec 60 --parallel 3
```

**Reuse one baseline across flags** with `--baseline-json`: the `flag=off` arm is identical for every
deterministic flag. You own the subset/budget/seed match. Cost per arm ≈
`ceil(n / parallel) × (budget_sec + ~3 s)`; keep `--parallel` at `cores − 1`.

**Reading the verdict.** GREEN LIGHT → queue a real run. GREEN with caveat (the only block is more
*recovered* timeouts at the tight budget) → still queue. MIXED → read the blocks. RED → bounce it
back. NEUTRAL → enlarge `--n`/`--budget-sec`, or the subset does not exercise the flag.

### The whole-run screen mode

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_WINDOW_PUSH --mode whole-run \
  --n 40 --budget-sec 90 --total-budget-sec 1800 --workers 6
```

Drives `run_sweeps_split` on a subset under a small envelope, reporting the scheduler's own numbers
(`constraints_ok`, `self_overall_mean`/`self_fpr_mean`, per-pass `improved`/`completed`/`failed`,
`fallbacks_prewritten`, `empty_plans`, the `variants_source` histogram) alongside official metrics. A
scheduler change that moves `constraints_ok` without moving official FPR is the *expected* shape of a
self-scoring fix — and, since the generalization probe, also the shape of a **self-deception** bug, so
read the two together.

Three things before trusting one:

- **Each arm owns its method directory.** `run_sweeps_split` treats any non-empty plan under
  `results/<method>/` as an incumbent to beat *regardless of `resume`*, so two arms sharing a directory
  measure "arm 2 on top of arm 1", biased upward. `_method_for` appends a per-arm suffix. The committed
  [null screen](../results/phase2_baselines/screens/20260806_whole_run_null_n40_tb1800/summary.json)
  (both arms off, every metric and every per-pass triple identical) is the standing proof this holds;
  the tool labels it `NEUTRAL`, which for a deliberately null arm is the pass condition.
- **`--chunk-size`/`--parallel` are ignored**; the sweep scheduler owns its pool. Use `--workers`.
- **The envelope must fit more than one pass** or the mode degenerates into a slow triage-only run.
  `n=40` at `--total-budget-sec 1800 --budget-sec 90 --workers 6` produced three passes in ~9 min per
  arm; that is the calibrated starting point.

**A change with no flag needs the hand-rolled two-revision form** — `--flag` pairs one env var and
cannot pair two trees. Run each arm on its own revision with a distinct `--method`, **sequentially**
(two pools on one box contend for cores). Beyond the aggregates, diff the itineraries: a scheduler
change leaving 39 of 40 plans byte-identical has one real effect, and finding which query moved is
worth more than the delta.

### LLM-backed flags

`--mode end-to-end` plus a configured backend screens the LLM stages. The key is loaded for you —
`build_llm_client` calls `load_local_env()`. **Never source, read or echo `.env`**; export only the
backend selector.

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_LLM_PARSE --mode end-to-end \
  --off 0 --on 1 --extra-env "TPC_P2_LLM_BACKEND=deepinfra,TPC_P2_LLM_TIMEOUT_SEC=6" \
  --n 30 --budget-sec 90 --parallel 3 --out results/phase2_quick_eval/llm_parse
```

- **Lower the LLM timeout below the reduced slice or the flag silently no-ops.** Default `30 s`; at a
  `90 s` screen budget the parse slice is `~22 s`, so `6` is the working value.
- **Verify the arm actually called out**, at the wire, per query. Both historical LLM measurements
  were wrong for this reason, in opposite directions.
- **Responses are cached** (`cache/phase2_llm_parse/`), so re-measuring a different *policy* over the
  same prompts is free. Use this rather than re-spending credit.
- With the backend at `none` (library default) the end-to-end path makes zero LLM calls, so
  deterministic flags can be screened `--mode end-to-end` on a box with no key.

### Limits — read before trusting a screen

- **A screen never promotes.** It authorizes a real run.
- **A per-query screen does not screen the scheduler.** If the change touches
  `chinatravel/agent/phase2/sweeps.py`, `selfscore.py` or `run_sweeps_split`, use `--mode whole-run`.
- **A familiar-100 screen does not screen phrasing robustness.** Pair with [R22](#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change).
- **Absolute numbers are not ledger-comparable.** Do not commit screen outputs into `full_runs/` or
  `runs/`; `screens/` is their home.
- **Timeout counts carry run-to-run noise** — `±1–2` at a tight budget is nondeterminism. FPR and
  `continuous_score` are the correctness signals; `|Δ| ≤ --tol` (default `0.5`) reads as flat.
- **A screen can overstate a rare fallback**, and can mis-predict in either direction: R8's screen
  under-predicted its row, R14's over-predicted on all three axes.
- **Use `n ≥ 30`.** Smaller subsets are noise-dominated smoke checks.

### Cadence for per-query work

On each landing, screen on `familiar_100_val` **and** run the phrasing tripwire; RED bounces back,
GREEN keeps the flag off on `main` but joins tonight's queue. Nightly, run **one batched** end-to-end
with all queued flags stacked against the current promoted baseline. In the morning promote the batch
or, on a regression, promote nothing and run drop-one-out *screens*. Batching is deliberate: two
changes that each screen green can interact.

## Command path

```bash
make phase2-full-run P2_LABEL="reference 5h parallel"                 # whole-run row (decides the ship)
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=900 P2_REPEATS=2 P2_LABEL=<tag>   # per-query row
make phase2-rehearse FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_LIMIT=20     # quick smoke
make phase2-harness P2_SPLIT=tpc_phase2_familiar_100_val              # the organizers' exact command
make phase2-parser-report P2_LIMIT=20
```

Plus the instruments this cycle added — all static, read-only, no solve, no LLM, no network beyond the
local HF cache:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir <screen dir>
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --out-dir <screen dir>
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_entity_resolution_arms_probe.py --out-dir <screen dir>
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_oracle_literal_translation.py --out-dir <screen dir>
.venv/bin/python scripts/phase2_report_ablations.py --arm llm-only --n 2 --llm-backend stub
```

`make phase2-help` has the full catalog. For building and verifying the submission archive see the
[competition reference](reference/competition.md#packaging-this-into-a-submission) — and note that
**uploading is a manual owner action**, never an agent's.

## Measurement rule

Record the source name, split, deterministic selection, budget, flags and model/backend with every
measurement. **Do not infer held-out performance from local rows or from familiar-100** — that
inference has now been falsified once, by `~30` points. A number promotes a change only through the
gate, never by assertion.
