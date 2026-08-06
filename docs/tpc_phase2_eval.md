# Phase 2 evaluation roadmap

**One document for both halves of evaluation: what a measurement is allowed to prove, and what to
run next.** Merged 2026-08-05 from the former `tpc_phase2_eval.md` (definitions) and
`tpc_phase2_eval_roadmap.md` (run queue); both are preserved verbatim in the
[archive](archive/README.md). What to *implement* is the [implementation roadmap](tpc_phase2_roadmap.md);
how the system is built is the [design doc](tpc_phase2_design.md).

Generated rows live in [`results/phase2_baselines/`](../results/phase2_baselines/); this document
defines their interpretation.

## Run this next

**Where this stands as of 2026-08-06.** `v1` was **uploaded to the portal on 2026-08-05** (the
committed `submissions/phase2/fabiundstefan_v1.zip`, built from `be196d00`, tagged `phase2-v1` — see
[the archive record](reference/competition.md#the-v1-archive-as-built-2026-08-05)). The organizers
aim to return a score within 3 days of a valid submission, so feedback is expected around
2026-08-08, and **one submission slot remains** (`v2`, due with the technical report on 2026-08-10,
24:00 Beijing Time = 18:00 CEST). **[R17](#r17--does-the-tree-we-would-actually-ship-still-score-what-r16-measured-closed-2026-08-06-green)
closed GREEN on 2026-08-06: the tree `main` would actually ship (`git_sha efbfea96`, post-P11/P12)
scores `overall 64.17251838310492` — `+0.02254283` over R16's `64.14997555172528`, `FPR 44.0`
unchanged, `empty_plans 0/100`, zero failed jobs.** P12's tightened accept gate fired on exactly `1`
of the 100 plans versus R16's tree (byte-diffed against `results/phase2_e2e_r16_v2cand/` still on
disk), replacing a nonsensical overnight itinerary with a different, coherent one and moving no
aggregate metric outside noise. **`v2` should now be built from `efbfea96bea19610f9d725ebec2fd6f5d6b5cceb`**,
not from R16's `241c0524` — see [R17's own section](#r17--does-the-tree-we-would-actually-ship-still-score-what-r16-measured-closed-2026-08-06-green)
for the full reading. Packaging/upload remains a separate, outward-facing step this row does not
perform.

**Found while pushing this row: `main` has drifted again, past R17's sha too.**
[P13](tpc_phase2_roadmap.md#p13--an-empty-parent-parse-must-mean-the-same-thing-on-both-sides) merged
to `main` (`de3c8fcb`) *after* R17 measured `efbfea96` — its own roadmap-doc text says "PR open, held
per the sequencing note — do not merge to `main` until `v2` is packaged," but it was merged anyway,
so `main`'s tip now carries an unflagged production-path change (`agent_env/scripts/solve_phase2.py`,
`chinatravel/agent/phase2/orchestrator.py`, `chinatravel/agent/phase2/sweeps.py`) that no committed
row measures at `n=100`. This is the same drift pattern R16 and R17 each closed one PR earlier,
recurring a third time. **It does not change R17's own reading — `efbfea96` is still the correct sha
to build `v2` from** — but it means `main`'s current tip is *not* that sha, and a future row (or the
archive build itself) must not silently substitute one for the other. R16 confirmed P13's trigger
fires on `0/100` familiar-100 queries, so the expected blast radius is the same "small but not zero"
shape as P12's, not yet confirmed on the post-P13 tree specifically.

Every evaluation slot before R17 existed to answer one question:
**is there a configuration worth spending the second slot on?** [R14](#r14--the-p8p9-gate-the-one-run-that-decides-whether-v2-exists-closed-2026-08-06-green)
was that measurement, and it came back **GREEN** on 2026-08-06 (`overall 64.13`, `+0.5471` over the
R8/R12 baseline; `FPR 44.0`, `+1.0`; `constraints_ok` unchanged at `46/100` — see the row's own
section for the two caveats that temper it). [R15](#r15--held-out-tripwire-for-p8p9-closed-2026-08-06),
run the same day, found `constraints_ok 13/20` — tied with R13, but the plans on disk show P8/P9
changed only 1 of the 20 held-out queries and that edit moved no metric, so the tripwire never
actually armed; read together with R14 the two rows say **P8/P9 fire rarely** on this distribution,
which tempers rather than overturns the GREEN.

**[R16](#r16--measure-the-v2-candidate-the-last-run-before-a-rebuild-closed-2026-08-06-green) closed the last open
question, GREEN, on 2026-08-06.** [P10](tpc_phase2_roadmap.md#infrastructure-landed) merged to
`main` (`21ab422`) **not behind a flag** and changes `run_sweeps_split` — the whole-run scheduler,
the path every `full_runs/` row measures and the only path the submission uses. Checking the git_sha
of each row settles how that interacts with them:

| Row | `git_sha` | P10 in the tree? | What it therefore measures |
| --- | --- | --- | --- |
| R8/R12 baseline | `2298b4ba` | no | promoted defaults, pre-P10 |
| **R14** | `b54c58ef` | **no** | **P8+P9 alone — a clean two-way delta, exactly as registered** |
| **R15** | `1ac96bbd` | **yes** | P10 **+** P8+P9 against R13's pre-both baseline (20 held-out records) |
| **R16** | `241c0524` | **yes** | post-P10 `main` at `n=100`, P8/P9 on, nothing exported — **the shipping configuration *as of that commit*** |
| **R17** | `efbfea96` | **yes** | post-P11/P12 `main` at `n=100` — **confirms P12 does not cost score on the shipped path; this is the sha `v2` ships from** |

So R14's GREEN was *not* confounded — it happened to run one commit before P10 landed — but it also
meant `+0.5471` was measured with P10 absent, and P10 changes which candidate the scheduler keeps
while P8/P9 change what the candidates are, so the two interact by construction. R16 ran the actual
shipping configuration at full size and came back **GREEN against R14** (`overall 64.14997555172528`,
`+0.0183` over R14's `64.13167839953107`; `FPR 44.0`, unchanged; `empty_plans 0/100`; zero failed
jobs) and further ahead of the `v1`-matching R8/R12 baseline (`+0.5654` overall, `+1.0` FPR) — see the
[row's own section](#r16--measure-the-v2-candidate-the-last-run-before-a-rebuild-closed-2026-08-06-green) for the full
reading, including the self-score jump on `constraints_ok` (`46 → 51/100`) that P10 causes on its own
and that the doc's decision rule explicitly excludes from the promotion call. R9 and R11 stay blocked
on unimplemented work items — see the table below.

**`main` had moved past the tree R16 measured, and the difference was in the shipped solve path — so
[R17](#r17--does-the-tree-we-would-actually-ship-still-score-what-r16-measured-closed-2026-08-06-green)
was the run that decided what `v2` contains, and it closed GREEN.** R16's row pins `git_sha:
241c0524`. Between R16 and R17, two PRs
landed: [P11](tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen-landed-2026-08-06)
(tooling only — `scripts/`, `tests/`, nothing the solver imports) and
[P12](tpc_phase2_roadmap.md#p12--close-p10s-false-positive-half-omitted-parser-semantics), which is
**production code, unflagged**: `chinatravel/agent/tpc_agent/parsed_verifier.py`,
`solver_constraints.py` and `parse_constraints.py`.

P12's own screen argued this was safe on the grounds that `evaluate_parsed_constraints` "is consulted
only by the final self-score, never by the CP-SAT solve/accept loop". **That claim is false, and it is
the reason R17 existed.** Phase 2 runs with `TPC_USE_ORACLE=0`
(`chinatravel/agent/phase2/orchestrator.py:283`), and in that mode `TPCAgent._make_checker`'s
`base_check` *is* `evaluate_parsed_constraints` (`chinatravel/agent/tpc_agent/tpc_agent.py:174`) — the
same `check(plan)` that drives `_accepted`, every `_pack_plan` commit rule and the restart loop's
`consider()`. Probing the accept gate directly with the adversarial plan from P12's own test (an
`accommodation` activity sitting inside a meal-only window at the right POI) returns `check → (3, 3)
accepted` under pre-P12 semantics and `(0, 3) rejected` under post-P12 semantics. So P12 changes
**what the shipped solver accepts**, not merely what it reports about itself.

That does not make P12 wrong — it tightens a check that was vacuously true, which is the direction
[P12](tpc_phase2_roadmap.md#p12--close-p10s-false-positive-half-omitted-parser-semantics) was written
to fix. It makes it **unmeasured on the path that ships**, and unmeasured in a direction that can cost
score: a tightened gate rejects plans the solver used to accept, so it keeps searching and may finish
on a different incumbent or on `best_cs`. Our checker's opinion changed; the official evaluator's did
not. Where the old opinion was wrong-positive that is a gain; where the new one is over-strict
relative to the oracle it discards plans the official evaluator would have passed. P12's screen was
`n=10` in per-query mode with a zero-diff result it mis-attributed to structure, so it does not bound
this. **Expected effect on familiar-100 was small** — `required_order` matched `0/80` val queries and
the type fix did not fire on the 10 uids most likely to exercise it — and R17 confirmed it: P12 fired
on exactly `1` of the 100 plans versus R16's tree, and the aggregate score moved `+0.02`, inside
noise. This was exactly the "the measured tree is not the shipped tree" gap R16 existed to close for
P10, recurring one PR later for P12 — and R17 closed it the same way.

R1–R17 are closed (see [what the closed queue established](#what-the-closed-queue-r1r17-established)).
R7 (2026-08-05, post-P0) found the same-config spread is now **zero**: three independent 5 h
repeats scored bit-for-bit identical (`overall 57.74985419574877`, `FPR 32.0`, `constraints_ok
36/100`, all three times) — every remaining arm below is judged against that near-zero floor rather
than the pre-fix `sd 0.35`, so an effect well under `1` point is resolvable in a single run and
**no arm on this list needs repeats** unless a future result actually shows spread. R8
(2026-08-05) gated the window-aware move **GREEN and full-sized**: `overall 63.58` (`+5.83` over
R7), `FPR 43.0` (`+11.0`), `constraints_ok 46/100` (`+10`) — close to the paired screen's predicted
`FPR 32.5 → 42.5`. **`TPC_WINDOW_ANCHOR=1` was promoted to a harness default the same day**
(`apply_deterministic_solver_defaults()`), so **R8 is the new baseline: a later arm is compared to
`63.58` / `FPR 43.0`, never to R1's `57.99` or R7's `57.75`.** R10 (2026-08-05, diagnostic
only) put `tpc_phase1` through the same no-oracle path: `overall 85.20` against the oracle-fed
Phase 1 pipeline's `98.98` — a `13.78`-point removing-the-oracle cost, the report figure this run
exists to produce. **R12 (2026-08-05) closed the promotion equality check: the bare organizer
command with no environment set reproduced R8 bit-for-bit** (`overall 63.58458530360117`, `FPR
43.0`, `constraints_ok 46/100`, all four `solver_flags` including `window_anchor` read `true`) — the
promotion path and the explicit-environment path are confirmed to agree, so R8/R12 are one number
going forward. **R13 (2026-08-05) closed the held-out tripwire: `constraints_ok` moved `10/20 →
13/20`** against R5's pre-P1 number on the same `familiar_100_test` split (`FPR 40.0 → 55.0`,
`overall 62.59 → 70.54`) — inside the `13–15/20` "the move generalizes" band the doc set out in
advance, so the window-aware gain is not an artifact of fitting `val`'s residual. **R3 (2026-08-05)
closed the ≥8-core deployment check on a 10-core Mac with 8 workers**: `overall 64.08`, `FPR 44.0`,
`constraints_ok 47/100`, `empty_plans 0/100`, and `1112 s` wall time. Against R8/R12's 3-worker
4-core Linux baseline this is `+0.49` overall and one additional passing query, but both runs hit
the same `120/300 s` per-query caps and the hosts differ, so the defensible conclusion is that the
8-worker path is healthy and non-regressing, not that worker count alone caused the flip.

**Pick the baseline that matches your host, not the highest number in the ledger.** Whole-run rows
are only comparable on the same machine and worker count ([ledger comparability](#ledger-comparability)),
and two promoted-default baselines now exist:

| Host you are running on | Workers | Baseline row | `overall` / `FPR` / `constraints_ok` |
| --- | --- | --- | --- |
| 4-core Linux box | 3 (`CPU-1`) | R8 `20260805T123142Z` = R12 `20260805T170120Z` | `63.58458530360117` / `43.0` / `46/100` |
| 10-core Apple Silicon Mac | 8 | R3 `20260805T215107Z` | `64.0773462893086` / `44.0` / `47/100` |

If you are on a third machine, produce your own flags-off baseline row there first; a cross-host
delta is not evidence.

**Every row from here on must show `solver_flags.window_anchor: true` in its per-query telemetry**
unless it is deliberately the flags-off arm. That snapshot landed with the promotion precisely so a
row states its own configuration; a run that reports `false` is measuring the pre-R8 system whatever
its label says. Since 2026-08-06 the same snapshot also carries `window_push` and `window_insert`
(promoted alongside `window_anchor` as of R14's GREEN action, `241c0524`) plus the one remaining
**screened-but-unpromoted** candidate, `window_push_max_min`, from
`orchestrator.CANDIDATE_SOLVER_FLAGS`, so a row states which repairs actually ran instead of relying
on its `--label`.

| Run | What it answers | Blocked on | Cost |
| --- | --- | --- | --- |
| ~~R17~~ | ~~does the tree we would actually ship still score what R16 measured?~~ (post-P11/P12 `main`) | closed 2026-08-06, GREEN vs R16 — `v2` ships from `efbfea96` | done |
| ~~R16~~ | ~~what does the configuration a `v2` would ship actually score?~~ | closed 2026-08-06, GREEN vs R14 — but measured `241c0524`, superseded as the ship sha by R17 | done |
| ~~R14~~ | ~~do P8+P9 hold up on a whole run? → does `v2` exist?~~ | closed 2026-08-06, GREEN (pre-P10 tree) | done |
| ~~R15~~ | ~~did the P8/P9 gain generalize past the `val` residual?~~ | closed 2026-08-06, tripwire never armed (see result) | done |
| R18 | which held-out plans are `official=fail, parsed=pass`? (P12's residual false-positive half) | nothing, but **lower priority than R17** — it informs the *next* cycle, not `v2` | ~1.5 h |
| R9 | does re-attacking failures with fresh seeds accumulate flips? | [P5](tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds) + [P2](tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger) | ~5 h |
| R11 | LLM-backed repair | [P6](tpc_phase2_roadmap.md#p6--llm-backed-repair-proposer-v2-candidate-default-off), which is not implemented and cannot be verified against the organizers' endpoint from here | out of reach before 2026-08-10 |

**R9 and R11 remain blocked on unimplemented work items** that belong to the Implementation
workstream, not Evaluation — see the [parallel workstreams](../CLAUDE.md#parallel-workstreams)
split. R11's old "not before the `v1` upload" gate has now been *superseded rather than satisfied*:
`v1` is uploaded, but with `P6` unwritten and the endpoint unreachable locally, there is no arm to
run before the deadline.

### R17 — does the tree we would actually ship still score what R16 measured? *(closed 2026-08-06, GREEN)*

**Status: closed.** This was the only thing standing between a GREEN R16 and a `v2` upload, and it
closed GREEN the same day it was queued.

**Why it existed.** R16 measured `git_sha 241c0524`. `main` had moved to `154ee9e6` (and, by the time
this row ran, `efbfea96`), and the delta contains
P12 — unflagged production code that changes `TPCAgent`'s **acceptance gate**, not just the
scheduler's self-score. The reasoning, the source lines and the direct accept-gate probe are in
[Run this next](#run-this-next) above. Short version: a `v2` built from `main` today ships a
configuration no committed row covers.

**Pin the revision.** Record the sha you actually run and do not rebase mid-run; Implementation is
working in parallel on [P13](tpc_phase2_roadmap.md#p13--an-empty-parent-parse-must-mean-the-same-thing-on-both-sides)
and [P2](tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger), and whichever sha this row reports
is the sha the archive must be built from.

```bash
git rev-parse --short HEAD    # record this; the v2 archive is built from it
.venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r17_ship --label "R17 ship candidate: post-P11/P12 main, 5h, vs R16"
```

Export nothing. The promoted defaults come from `apply_deterministic_solver_defaults()`, and the
point of the row is that the bare organizer command is what gets measured.

**Verify the arm before reading the score**, exactly as R16 did — `window_anchor`, `window_push`,
`window_insert` all `true` with nothing exported; `variants_source` reading `parent` everywhere;
`variants_count == 0` on zero queries (a nonzero count is
[P13](tpc_phase2_roadmap.md#p13--an-empty-parent-parse-must-mean-the-same-thing-on-both-sides)'s
failure mode and worth reporting with uids). Reuse
[R16's verification snippet](#r16--measure-the-v2-candidate-the-last-run-before-a-rebuild-closed-2026-08-06-green)
with the method name changed.

**Baseline: R16 `20260806T082724Z`** on the same host (4-core Linux / 3 workers), `overall
64.14997555172528`, `FPR 44.0`, `constraints_ok 51/100`. On a different host produce your own baseline
first — a cross-host delta is not evidence.

**Decision rule, fixed in advance:**

| Outcome vs R16 | Read | Action |
| --- | --- | --- |
| `overall` ≥ R16 − `0.5`, `FPR` not down, `empty_plans 0/100`, no failed jobs | GREEN | **Build `v2` from this row's sha.** Packaging path in the [competition reference](reference/competition.md#packaging-this-into-a-submission), then the [cold-start checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05), then upload as `{team}_v2.zip`. |
| `overall` down by more than `0.5`, or `FPR` down | RED — **P12 costs score on the shipped path** | Do not ship `main`. **Build `v2` from `241c0524`** — the exact tree R16 measured, a known-GREEN configuration that is still `+0.5654` over `v1`. P12 then ships in the next cycle at no cost to this submission, which is cheap: it matched `0/80` val queries. Hand the row to Implementation with the uids whose plans changed. |
| `empty_plans > 0` or any failed job | RED — infrastructure | Suspect the **worker pool** before the solver ([cold-start note](#before-the-first-run)); fix and re-run. Do not read the score. |

Expected: **within noise of R16's `64.15`**, because both P12 fixes are rare on this distribution.
`constraints_ok` may fall while `overall` holds — that is the tightened gate no longer counting a
vacuous pass, and it is [P12's own predicted signature](tpc_phase2_roadmap.md#p12--close-p10s-false-positive-half-omitted-parser-semantics).
**`constraints_ok` is not a promotion metric here**; `overall` and `FPR` are.

**Result** (row `20260806T115309Z`, 4-core Linux, 3 workers, `git_sha:
efbfea96bea19610f9d725ebec2fd6f5d6b5cceb`, `git_dirty: false`, `evaluator_parity: c89cfca`, `split:
tpc_phase2_familiar_100` — matches R16's row by construction, confirmed rather than assumed —
compared against **R16** `20260806T082724Z`):

Telemetry confirmed before the score was read: all 100 per-query `telemetry.json` files showed
`variants_source: parent`, zero queries with `variants_count == 0` (matching R16's expectation
exactly), and `window_anchor`/`window_push`/`window_insert` all `true` with nothing exported;
`window_push_max_min` read `false` (unpromoted candidate, at its code default). All three passes
(triage/repair/polish) reported `failed: 0`.

`overall 64.17251838310492` (**`+0.02254283`** over R16's `64.14997555172528` — inside noise), MicEPR
`99.67`, MacEPR `98.00`, C-LPR `90.08`, **`FPR 44.0`** (unchanged from R16), DAV `26.04`, ATT `34.48`,
DDR `25.19`; `empty_plans 0/100`, zero failed jobs across all three passes. Ran `100/50/50` queries
through triage/repair/polish with `100/1/14` improved, in `1.38 h` of the `5.00 h` envelope (`27.55%`).
The scheduler's own self-score, `constraints_ok`, read **`50/100`** — **`-1`** versus R16's `51/100`,
consistent with P12's predicted signature (the tightened gate no longer counts a vacuous pass) and,
per the pre-registered rule, not itself a promotion signal.

By the pre-registered rule this is **GREEN**: `overall` is within `0.5` of R16 (in fact fractionally
above it), `FPR` is not down, `empty_plans 0/100`, and no failed job on any pass. **Action per the
rule: build `v2` from this row's sha, `efbfea96bea19610f9d725ebec2fd6f5d6b5cceb`** — not from R16's
`241c0524`. Packaging/upload remains a separate, outward-facing action not performed by this row.

**Cheaper alternative if the eval machine is busy** (not exercised — the full row above already
exists), now that
[P11](tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen-landed-2026-08-06) exists: a
paired `--mode whole-run` screen at `n=40` over the two revisions (`241c0524` vs `main`) bounds P12's
whole-run effect in `~50 min`. That is a screen — it triages, it never promotes.

**The plan-directory diff, done.** Compared this row's plan directory
(`results/phase2_e2e_r17_ship/`) against R16's (`results/phase2_e2e_r16_v2cand/`, still on disk) the
way R15 was read: **99 of 100 plans are byte-identical** apart from `elapsed_time(sec)`. The 100th,
`phase2_familiar_20250322120414354584_00052`, has a real P12-caused change: the R16-tree plan departed
its outbound flight at `02:56` and landed at `04:27` (an implausible overnight schedule the old accept
gate let through), and P12's tightened gate rejected it, sending the solver to a different incumbent —
a `07:28`–`08:59` flight followed by a coherent lunch/attraction/dinner sequence through the day. This
answers "did the fix fire at all on the shipped path": **yes, on `1/100` queries**, matching the
"rare but real" prediction (`required_order` matched `0/80` val queries) and moving no aggregate
metric outside noise.

Committed the row under `results/phase2_baselines/full_runs/` and added its line to
[the closed-queue table](#what-the-closed-queue-r1r17-established).

### R18 — regenerate the held-out plans P12's residual needs *(open, lower priority than R17)*

[P12](tpc_phase2_roadmap.md#p12--close-p10s-false-positive-half-omitted-parser-semantics) closed two
of five omitted semantics and explicitly could not close the other three, because the evidence — the
`official=fail, parsed=pass` plans from the packaged-`v1` `tpc_phase2_test` run — is **not in this
checkout**. The roadmap item's own "where the evidence lives" note asks Evaluation for it rather than
having Implementation guess. This is that request.

```bash
.venv/bin/python scripts/phase2_full_run.py --split tpc_phase2_test \
  --total-budget-sec 5400 --method phase2_e2e_r18_test150 --label "R18 regenerate tpc_phase2_test plans for the P12 cross-tab"
```

Then score every plan twice — officially with `eval_tpc.py`, and with `selfscore.score_plan` — and
report the four-cell cross-tab plus **the uids in the `official=no, parsed=yes` cell**. Those uids are
the deliverable; the aggregate score is not the point and this row does not promote anything.

**This informs the next cycle, not `v2`.** Run it only after R17, and only if a slot is free before
2026-08-10.

### R16 — measure the `v2` candidate (the last run before a rebuild) *(closed 2026-08-06, GREEN)*

**Status: closed.** The flag promotion (R14's GREEN action) had already landed on `main`
(`0c80ab6b`/`241c0524`) before this row ran, so the command below needed no exported environment —
the arm *is* the shipped default.

**What it answered.** Before this row, no committed row measured the configuration a `v2` would
ship. Reading R14/R15's `git_sha` fields (table in [Run this next](#run-this-next)) shows why:

- **R14 ran on `b54c58ef`, one commit before P10 merged.** Good news for R14 itself — its `+0.5471`
  is a clean two-way P8+P9 delta, exactly as registered, with no P10 confound.
- **But that means `+0.5471` was measured with P10 absent**, while `main` has had P10 default-on
  since `21ab422`. P10 changes which candidate `run_sweeps_split` keeps; P8/P9 change what the
  candidates are. They interact by construction, so the sum is not guaranteed to be the parts.
- **R15 is the only post-P10 whole-run row that predates this one**, and it is 20 held-out records
  on which nothing fired (19 of 20 plans byte-identical to R13). It bounded P10's effect at "not
  large on that fold" and nothing more.

So before R16, the shipping configuration had never been run at `n=100` — a gap worth `~1.3 h`
against the 2026-08-10 deadline, closed by the row below.

**Command actually run** (the promotion had already landed, so nothing needed exporting — the arm
*is* the shipped default; retained here for reproducibility):

```bash
.venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r16_v2cand --label "R16 v2 candidate: post-P10 main, P8/P9 promoted, 5h"
```

(If run before the promotion lands, set the two flags explicitly instead
— `TPC_WINDOW_PUSH=1 TPC_WINDOW_INSERT=1 …` — the measurement is identical, but then the row does
not also prove the promotion took effect, which is half its value.)

**Verify the arm before reading the score**, from per-query telemetry under
`agent_env/runs/phase2_e2e_r16_v2cand/`:

```bash
.venv/bin/python - <<'PY'
import collections, json, pathlib
root = pathlib.Path("agent_env/runs/phase2_e2e_r16_v2cand")
sources, flags, empty = collections.Counter(), collections.Counter(), []
for path in sorted(root.rglob("telemetry.json")):
    t = json.loads(path.read_text())
    sources[t.get("variants_source")] += 1
    if not t.get("variants_count"):
        empty.append(path.parent.name)
    for k, v in (t.get("solver_flags") or {}).items():
        flags[(k, bool(v))] += 1
print("variants_source:", dict(sources))
print("queries solved with zero variants:", len(empty), empty[:5])
print("solver_flags:", {f"{k}={v}": n for (k, v), n in sorted(flags.items())})
PY
```

- `window_anchor`, `window_push`, `window_insert` all **`true`** on every query — with nothing
  exported, that is what proves the promotion is real rather than a code comment.
- `variants_source` must read **`parent`** everywhere: that is the P10 path, and a row reading
  `worker` is measuring pre-P10 behaviour whatever its label says.
- **`variants_count == 0` is the check that actually matters**, and it is *not* the same as
  `variants_source == "worker"`. `orchestrator.solve_phase2` branches on `variants is not None`
  (`chinatravel/agent/phase2/orchestrator.py:471`), so a query whose *parent* parse raised gets
  `variants=[]`, still reports `source="parent"`, and **skips its own parse entirely** — it is solved
  against no constraints at all. Expect `0`. A nonzero count is a finding, not noise: report it with
  the uids and see [P13](tpc_phase2_roadmap.md#p13--an-empty-parent-parse-must-mean-the-same-thing-on-both-sides).

**Two comparisons, both from this one row** (4-core Linux / 3 workers; on another host produce your
own flags-off baseline first — a cross-host delta is not evidence):

| Against | Isolates | Baseline |
| --- | --- | --- |
| **R14** `20260806T052925Z` | **P10 alone** — same flags, only P10 differs | `overall 64.13167839953107`, `FPR 44.0`, `constraints_ok 46/100` |
| R8/R12 `20260805T123142Z` | the whole `v1 → v2` delta | `overall 63.58458530360117`, `FPR 43.0`, `constraints_ok 46/100` |

**Decision rule, fixed in advance:**

| Outcome vs **R14** | Read | Action |
| --- | --- | --- |
| `overall` ≥ R14 − `0.5`, `FPR` not down, `empty_plans 0/100`, no failed jobs | GREEN | Ship it. The `v2` candidate is at least as good as the configuration R14 gated, and better than `v1` by the R8/R12 comparison. Rebuild the archive from `main` per the [packaging path](reference/competition.md#packaging-this-into-a-submission), run the [cold-start checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05), upload as `{team}_v2.zip`. |
| `overall` down by more than `0.5` vs R14, or `FPR` down | RED — **P10 costs more than P8/P9 gain** | Do not ship `main` as-is. Two options, in order: (1) build `v2` from `b54c58ef` + the flag promotion — the exact tree R14 measured, which is a known-GREEN configuration; or (2) hand the row to Implementation to find the P10 interaction. Option 1 is the safe one with the deadline this close. |
| `empty_plans > 0` or any failed job | RED — infrastructure | Suspect the **worker pool** before the solver ([cold-start note](#before-the-first-run)), fix, re-run. Do not read the score. |

Expected: **within noise of R14's `64.13`**, since P10 was ~flat on its own `n=40` screen and
inert on R15's 20 records. `constraints_ok` may rise while `overall` does not — P10's whole purpose
is that the scheduler stops under-counting its own successes, and that is a self-score effect, not a
scoring one. **`constraints_ok` is not a promotion metric here.**

**Result** (row `20260806T082724Z`, 4-core Linux, 3 workers, `git_sha: 241c0524`, `git_dirty: false`,
`evaluator_parity: c89cfca`, compared against **R14** `20260806T052925Z` and, for the whole `v1 → v2`
delta, R8/R12 `20260805T123142Z`):

Telemetry confirmed before the score was read: `variants_source` read **`parent`** on all 100
queries (the P10 path); zero queries had `variants_count == 0`, matching the expectation exactly;
`window_anchor`, `window_push`, `window_insert` all **`true`** on every query with nothing exported,
confirming the promotion is live rather than a code comment; `window_push_max_min` read `false`
(unpromoted candidate, at its code default). All three passes (triage/repair/polish) reported
`failed: 0`.

`overall 64.14997555172528` (**`+0.0183`** over R14's `64.13167839953107`; **`+0.5654`** over
R8/R12's `63.58458530360117`), MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.99`, **`FPR 44.0`**
(unchanged from R14, **`+1.0`** over R8/R12), DAV `26.04`, ATT `34.48`, DDR `25.19`; `empty_plans
0/100`, zero failed jobs across all three passes. Ran `100/49/51` queries through triage/repair/polish
with `100/1/14` improved, in `1.31 h` of the `5.00 h` envelope (`26%`). The scheduler's own self-score,
`constraints_ok`, read **`51/100`** — **`+5`** over R14's `46/100` — with `overall` essentially flat;
exactly the pattern the doc predicted for P10's self-scoring fix and, per the pre-registered rule,
not itself a promotion signal.

By the pre-registered rule this is **GREEN**: `overall` is within `0.5` of R14 (in fact fractionally
above it), `FPR` is not down, `empty_plans 0/100`, and no failed job on any pass. Read against
R8/R12 this is also the full, undiluted `v1 → v2` delta: `+0.5654` overall and `+1.0` FPR, with P10
contributing essentially nothing on top of P8/P9's R14 gain and taking nothing away from it either
— the two do not interact destructively at `n=100`, resolving the confound this row existed to
close. **Action per the rule: ship the measured tree as `v2`.** Rebuild the archive per the
[packaging path](reference/competition.md#packaging-this-into-a-submission), run the [cold-start
checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05),
and upload as `{team}_v2.zip` — that packaging/upload step is a separate, outward-facing action and
is not performed by this row.

> **Addendum 2026-08-06: "the measured tree" was `241c0524`, and `main` had moved past it.** P12
> landed after this row and changes `TPCAgent`'s acceptance gate without a flag, so `main` shipped a
> configuration this row did not measure.
> [R17](#r17--does-the-tree-we-would-actually-ship-still-score-what-r16-measured-closed-2026-08-06-green)
> resolved it: **GREEN**, `overall +0.02` over this row, `FPR` unchanged — `v2` ships from R17's
> `efbfea96`, not from this row's `241c0524`.


**On whether `v2` is worth spending at all.** The organizers evaluate at most two versions and **the
higher score wins if both succeed** ([competition reference](reference/competition.md#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply)),
so a `v2` that scores *worse* than `v1` costs nothing but the slot — `v1`'s score stands. The
asymmetry says: with a GREEN R16 in hand, ship it. The only real risk is a `v2` that fails to *run*,
which is what the cold-start checklist exists to prevent, so budget the time for that check rather
than for more score-chasing.

Commit the row under `results/phase2_baselines/full_runs/` and add its line to
[the closed-queue table](#what-the-closed-queue-r1r17-established) with host, worker count and both
baselines above.

### R14 — the P8/P9 gate: the one run that decides whether `v2` exists *(closed 2026-08-06, GREEN)*

**Status: closed.** P8 (`TPC_WINDOW_PUSH`) and P9
(`TPC_WINDOW_INSERT`) landed on `main` in `0c2cc395`, both **library- and harness-default-off**, each
screened GREEN individually and stacked ([roadmap P8](tpc_phase2_roadmap.md#p8--bounded-local-window-push-the-rest-of-the-timed-visit-residual),
[P9](tpc_phase2_roadmap.md#p9--place-an-absent-timed-visit-poi)). A screen never promotes, so
without this row the two passes cannot ship and `v2` has nothing new in it.

Gate the **stack**, not each flag alone: both screens are already paired against the same P1-on
candidate artifact, the stacked end-to-end screen showed no destructive interaction
(`FPR 42.5 → 45.0`, `overall_true 63.130 → 64.422`, `all_pass 34 → 36`), and the
[cadence rule](#cadence-for-per-query-work-daily-screen-nightly-batched-run) is explicit that a
batch measures the net effect that would actually ship. One run, one decision.

```bash
# 1. baseline: R16's row on this host. Do not re-run it, and do not substitute a pre-P10 row.
# 2. candidate: promoted defaults plus the two window repairs.
TPC_WINDOW_PUSH=1 TPC_WINDOW_INSERT=1 .venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r14_pushinsert --label "R14 P8+P9 stacked, 5h, vs R16"
```

Export nothing else. `apply_deterministic_solver_defaults()` supplies the promoted flags and respects
the two you set, so the candidate arm differs from **R16's** baseline in exactly those two — which is
the whole reason R16 has to exist. Comparing this arm to R8/R12 instead folds P10 into the delta and
makes the decision rule below meaningless.

**Use a distinct `--method` per arm, as above.** `phase2_full_run.py`'s `--fresh` is the default
(confirmed against the script's `argparse` defaults and this run's own row: `"fresh": true`,
`"incumbents_scored": 0`), so each named method starts from a clean directory; `--resume` is the
opt-in flag that would instead treat a filled directory as an incumbent to beat. A distinct
`--method` per arm is still the right habit — it keeps arms separable on disk and in the ledger —
but the resume-by-default risk this paragraph used to describe does not apply to the current script.

**Before reading the score, verify the arm actually ran what it claims** — one per-query
`telemetry.json` under `agent_env/runs/phase2_e2e_r14_pushinsert/` must show `window_push: true`,
`window_insert: true` *and* `window_anchor: true`. A row whose `window_push` reads `false` is a
repeat of the baseline, whatever its label says:

```bash
.venv/bin/python - <<'PY'
import json, pathlib
root = pathlib.Path("agent_env/runs/phase2_e2e_r14_pushinsert")
for path in sorted(root.rglob("telemetry.json"))[:3]:
    print(path, json.loads(path.read_text())["solver_flags"])
PY
```

**Expected, from the stacked `n=80` / `90 s` end-to-end screen** (`+1.29` `overall_true`, `+2.5`
FPR): `overall` and `FPR` roughly `+1.3` and `+2.5` **on top of R16's numbers**, whatever those turn
out to be. The absolute targets this section used to quote (`overall ≈ 64.5–65.5`, `FPR 45–46`) were
computed off the pre-P10 `63.58` and are only still right if R16 lands flat; take the deltas, not the
absolutes. R8's screen slightly *under*-predicted its full
run (`+10.0` predicted, `+11.0` measured), so treat the screen as a floor rather than a ceiling — but
also note the screen ran at `90 s`/query while the whole run spends `120/300 s`, so the two passes
have more competing search to displace here than they did there.

**Decision rule, fixed in advance so the result cannot be read after the fact:**

| Outcome | Read | Action |
| --- | --- | --- |
| `overall` up **and** `FPR` not down **and** `empty_plans 0/100` **and** no failed jobs | GREEN | Promote both flags: move them from `CANDIDATE_SOLVER_FLAGS` into `PROMOTED_SOLVER_FLAGS` and set them in `apply_deterministic_solver_defaults()` with this row cited (Implementation task), then run [R15](#r15--held-out-tripwire-for-p8p9-closed-2026-08-06), then rebuild and upload `v2`. |
| `abs(Δ overall) ≤ 0.5` with `FPR` unchanged | FLAT | Do not promote. `v1`'s configuration stays the submission. Record the row and stop — do **not** spend a second 5 h run hoping for a different number; the solver is deterministic. |
| `FPR` down, `empty_plans > 0`, or any failed job | RED | Do not promote. Commit the row, then hand it to Implementation with the failing uids; run **drop-one-out screens** (`--flag TPC_WINDOW_PUSH` alone, then `--flag TPC_WINDOW_INSERT` alone) rather than more full runs. |

`empty_plans > 0` or a nonzero per-pass `failed` count means suspect the **worker pool** before the
solver — see the [cold-start note](#before-the-first-run) above.

Commit the row under `results/phase2_baselines/full_runs/` and add its line to
[the closed-queue table](#what-the-closed-queue-r1r17-established) with the host, worker count and
the baseline it is compared against.

**Result** (row `20260806T052925Z`, 4-core Linux, 3 workers, `git_dirty: false`, `evaluator_parity:
c89cfca`, compared against the same-host R8 `20260805T123142Z` = R12 `20260805T170120Z` baseline):
all 100 per-query `telemetry.json` files confirmed `window_push: true`, `window_insert: true` *and*
`window_anchor: true` before the score was read. `overall 64.13167839953107` (**`+0.5471`** over
`63.58458530360117`), MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.99` (`+0.09`), **`FPR 44.0`**
(**`+1.0`** over `43.0`), DAV `25.54` (`+0.83`), ATT `34.53` (`+0.88`), DDR `25.28` (`+0.78`);
`empty_plans 0/100`, zero failed jobs across all three passes, **`constraints_ok 46/100` — unchanged
from baseline**. Ran `100/54/46` queries through triage/repair/polish with `100/1/13` improved, in
`1.32 h` of the `5.00 h` envelope (`26%`, matching the R8/R12/R3 shape).

By the pre-registered rule this is **GREEN**: `overall` up, `FPR` not down, `empty_plans 0/100`, no
failed job. The FLAT row does not apply even though `Δoverall` (`0.5471`) sits just above its `0.5`
threshold, because that row's condition is `FPR unchanged` and FPR moved (`+1.0`); the rule was fixed
in advance specifically so a borderline delta cannot be re-read as FLAT after the fact, and R7's
`sd = 0` means this is a real deterministic effect, not noise around a threshold.

**Two things temper how much this GREEN buys, worth reading before spending `v2` on it:**

1. **The screen over-predicted, in the opposite direction from R8's screen.** The paired `n=80`/`90 s`
   screen predicted `overall 64.5–65.5`, `FPR 45–46`, `constraints_ok 48–49/100`; the full run landed
   at `64.13` / `44.0` / `46` — below the low end on all three, not above it. R8's screen had
   *under*-predicted its full run, which is why this doc told readers to treat a screen as "a floor
   rather than a ceiling"; R14 is the counter-example, so that heuristic no longer holds in general
   and a screen's full-run outcome should be read as uncertain in either direction, not just upward.
2. **`constraints_ok` did not move at all** (`46/100`, identical to baseline). The `+0.5471` overall
   gain is entirely from one FPR point plus the three preference terms (DAV/ATT/DDR), not from any
   query flipping from failing to passing its constraints — the same distinction this doc's [closed-queue
   finding #4](#what-the-closed-queue-r1r17-established) already draws between `improved` and
   `constraints_ok`. The gain is real (GREEN stands) but thinner than the headline `overall` delta
   reads on its own.

Per the GREEN action: promoting the flags into `PROMOTED_SOLVER_FLAGS` /
`apply_deterministic_solver_defaults()` is an Implementation-workstream change (CLAUDE.md's
[parallel workstreams](../CLAUDE.md#parallel-workstreams) bar Evaluation from solver code) and is not
done in this row's branch. [R15](#r15--held-out-tripwire-for-p8p9-closed-2026-08-06) does not depend on that promotion
— its command sets both flags via environment variable — so it can and does run next.

### R15 — held-out tripwire for P8/P9 *(closed 2026-08-06)*

**Only after R14 comes back GREEN.** [R13](#r13--the-held-out-tripwire-on-the-new-default-closed-2026-08-05)
closed the same question for P1 and said so explicitly: P8/P9 were designed from the *same* `val`
shape classification, so they get their own held-out check rather than inheriting P1's.

```bash
TPC_WINDOW_PUSH=1 TPC_WINDOW_INSERT=1 .venv/bin/python scripts/phase2_full_run.py \
  --split tpc_phase2_familiar_100_test --total-budget-sec 3600 \
  --method phase2_e2e_r15_test --label "held-out tripwire, post-P8/P9"
```

**Read `constraints_ok` out of 20, not `overall`**, against R13's `13/20` on the identical 20
records (`overall 70.54`, `FPR 55.0`). `14–15/20` says the residual moves on unseen records too;
`13/20` is a tie and is *not* a reason to withhold promotion by itself — one query is `5` percentage
points on this instrument, and R14 on 100 records is the gate. `≤ 12/20` is a real warning: promote
nothing without re-reading it, because a held-out regression next to a `val` gain is what
overfitting looks like. Never compare this row to R14's `overall`: `familiar_100_test` is a *subset*
of `familiar_100` and an easier one.

**Result** (row `20260806T065521Z`, 4-core Linux, 3 workers, `git_dirty: false`, `evaluator_parity:
c89cfca`, `git_sha: 1ac96bbd` — this row sits on top of the [R14](#r14--the-p8p9-gate-the-one-run-that-decides-whether-v2-exists-closed-2026-08-06-green)
commit, one revision after R14's own `b54c58ef`; the intervening commit is
[P10](tpc_phase2_roadmap.md#infrastructure-landed), which does not touch flag semantics but **is
not unrelated** — it rewrites how `run_sweeps_split` self-scores and therefore which candidate each
pass keeps, so this row is a P10 **+** P8/P9 delta against R13's pre-both baseline, while R14 is
P8/P9 alone. That makes R15 the only post-P10 whole-run row in the ledger, and the fact that it
reproduces R13 to 15 significant digits bounds P10's effect on *these 20 records* at zero. It says
nothing about P10 at `n=100`, which is
[R16](#r16--measure-the-v2-candidate-the-last-run-before-a-rebuild-closed-2026-08-06-green)): all 20 per-query
`telemetry.json` files confirmed `window_push: true`, `window_insert: true` and `window_anchor:
true`. `overall 70.53975966861671`, MicEPR `100.0`, MacEPR `100.0`, C-LPR `93.36`, FPR `55.0`, DAV
`32.60`, ATT `42.90`, DDR `28.47`; `empty_plans 0/20`; **`constraints_ok 13/20`** — identical to
R13's `13/20` on the same 20 records. `0.26 h` of the `1.00 h` envelope.

**This is not an ordinary tie: all seven official metrics matched R13 to 15 significant digits**, so
before reading `13/20` as "one query flipped each way and cancelled," the two runs' plan directories
were diffed directly (`results/phase2_e2e_r13_test/` vs `results/phase2_e2e_r15_test/`, both still on
disk). **19 of the 20 plans are byte-identical apart from the recorded `elapsed_time(sec)`.** The
20th (`phase2_familiar_20250323024847827162_00069`) has a real, P8/P9-caused edit — every timed
visit's start/end time is shifted by `14–15` minutes throughout the day — so the flags did fire on
this split, at least once. That edit left every official aggregate metric unchanged, which is only
possible if this query's pass/fail status did not change (a query's preference terms are zeroed
whenever it fails, per this doc's [closed-queue finding #4](#what-the-closed-queue-r1r17-established));
the row's telemetry has no per-query pass/fail counter to confirm this beyond the aggregate
arithmetic, so that is as far as this row can pin it down.

**Reading**: R15 does not answer the question it was registered to answer. "Did the P8/P9 gain
generalize past the `val` residual" presumes the flags produce a *different* plan whose pass/fail
status can then be compared; here they changed one plan out of twenty and left the aggregate
completely unmoved, so this row is neither evidence that the residual generalizes nor evidence that
it doesn't — the tripwire never armed. Read together with R14 (`+1.0` FPR on `100` records with
`constraints_ok` flat, i.e. the gain there was also FPR-plus-preference rather than new passing
queries), the consistent picture across both rows is that **P8/P9 fire rarely** on this data
distribution. That does not overturn R14's GREEN — the decision rule was pre-registered and R7's
`sd = 0` makes the `+0.5471` a real effect, not noise — but it is material to whether the last `v2`
slot is worth spending on these two flags specifically, which is the question this section of the doc
exists to answer. That call is left to the human, not resolved here.

### What the submitted `v1` is expected to score — an expectation, not a measurement

**`v1` was uploaded 2026-08-05** and carries R8's configuration (`TPC_WINDOW_ANCHOR` on, P8/P9 off),
so the honest point estimate is **R8's number: `overall 63.58`, `FPR 43.0`** on data drawn like
familiar-100. Everything below is uncertainty around that, and the
[measurement rule](#measurement-rule) still stands: no local row proves held-out performance. When
the organizers' score arrives (expected ~2026-08-08), record it next to this estimate — it is the
only external calibration this project will get, and the gap between it and `63.58` is the single
most informative number for deciding what `v2` should be.

| Source of error | Size | Direction |
| --- | --- | --- |
| Solver nondeterminism | **`0`** — R7's three 5 h repeats are bit-for-bit identical | none |
| Query sampling (100 fresh queries, same distribution) | FPR is binomial: at `p = 0.43`, `n = 100`, `SE = 4.95` FPR points. Empirically `1` FPR point is worth `0.53` overall on this system (`+11.0 FPR → +5.83` from R7 to R8, above the `0.40` weight because C-LPR and the preference terms move with FPR), so **`≈ ±2.6` overall at `1σ`** | symmetric |
| P1 was designed from the **`val` residual** | **resolved by [R13](#r13--the-held-out-tripwire-on-the-new-default-closed-2026-08-05)**: `constraints_ok 10/20 → 13/20` on the untouched `familiar_100_test` split — inside the pre-registered `13–15/20` "generalizes" band, not the `10/20` "fit val" band. R8's 100 queries include the 80 `val` records, so its `+11.0` FPR is still partly in-sample, but the held-out subset moved in the same direction | **mildly optimistic, not invalidated** |
| Evaluation host | unknown core count; the split costs `≤ ~14200` worker-seconds, so even one worker fits the 5 h envelope. [R3](#r3--worker-scaling-closed-2026-08-05) confirmed the 8-worker path is healthy (`64.08`, no empty plans), but because both measured worker counts hit the same per-query caps it did not establish a worker-only score gain | neutral |

So: **low-to-mid 60s, centre `~63.6`, roughly `58–68` as a `±2σ` band**. R13 closed the residual
val-design risk without erasing it: the held-out subset improved (`10/20 → 13/20`), landing at the
low end of the pre-registered generalization band rather than at its high end or at the "fit val"
floor, so the centre estimate stands but is not read as conservative. For context on the held-out
subset, R5 measured `FPR 40.0` / `overall 62.59` there on the **pre-P1** configuration; R13 measured
`FPR 55.0` / `overall 70.54` on the same 20 records post-P1 — that subset is easier than the full 100
(`constraints_ok` runs several points above the full-100 rate on both configurations), which is why
R13 is read as `constraints_ok/20` against R5's `10/20` rather than as a score comparison.

### R12 — the promoted default, from a clean tree *(closed 2026-08-05)*

R8 turned the flag on **explicitly, from the environment**. The submission turns it on **implicitly,
inside `apply_deterministic_solver_defaults()`**. Those are different code paths to the same
configuration, and only the second one ships, so exactly one thing is being asked here: does the bare
organizer command reproduce `63.58` with no environment set at all?

```bash
.venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r12_default --label "promoted default, 5h"
```

Do not export any `TPC_*` variable. **Read `solver_flags` in a per-query `telemetry.json` first** —
all four promoted flags must read on — then the score. Expect `overall 63.58` and `FPR 43.0`: post-P0
the solver is bit-for-bit reproducible, so this is a genuine equality check rather than an
"approximately". Any gap means the promotion path and the environment path disagree, which is a bug in
the promotion, not a new measurement.

**Result** (row `20260805T170120Z`, `git_dirty: false`, `evaluator_parity: c89cfca`): confirmed with
no `TPC_*` variable exported, all four `solver_flags` read `true` (`pin_timed_windows`,
`window_anchor`, `commonsense_first`, `solve_converge_patience`) in every checked per-query
`telemetry.json`, and the score matched R8 **bit-for-bit**: `overall 63.58458530360117`, MicEPR
`99.67`, MacEPR `98.0`, C-LPR `89.90081154192967`, `FPR 43.0`, DAV `24.70833333333333`, ATT
`33.645981695708585`, DDR `24.499999999999996`, `empty_plans 0/100`, `constraints_ok 46/100`. The
run self-terminated at `1.32 h` of the `5.00 h` envelope (`26%`, matching R8's usage), same
triage→repair→polish shape (`100/54/46` queries, `100/1/13` improved). **The promotion path and the
explicit-environment path agree exactly** — no bug, no new number; R8 and R12 are the same
measurement from two entry points.

Pair it with the archive check R6 performed on the old configuration: build with
`scripts/assemble_phase2_submission.py`, unpack **into a directory that has never been run in**, and
confirm the plans are real rather than the pre-written empty fallbacks. A worker dying at start-up
still exits `0`; see the [cold-start rule](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).

**Archive check**: see the R12 row in [what the closed queue established](#what-the-closed-queue-r1r17-established)
— packaged and verified with `scripts/assemble_phase2_submission.py`'s built-in unpack-and-run check.

### R13 — the held-out tripwire on the new default *(closed 2026-08-05)*

P1 was designed from a *measured shape classification of the `val` residual*, which is exactly the
procedure that can overfit `val`. R5 established the `familiar_100_test` number for the old
configuration (`62.59`, `constraints_ok 10/20`); re-run it now:

```bash
.venv/bin/python scripts/phase2_full_run.py --split tpc_phase2_familiar_100_test \
  --total-budget-sec 3600 --method phase2_e2e_r13_test --label "held-out tripwire, post-P1"
```

**Read `constraints_ok` out of 20, not `overall`.** The whole question is whether the FPR gain
carried: `10/20 → 13–15/20` says the move generalizes; `10/20 → 10/20` says it fit `val`'s residual
and P8/P9 (designed the same way, from the same classification) need a different validation plan.
Twenty records is a coarse instrument — it is a tripwire, not a second gate — and `familiar_100_test`
is a *subset* of `familiar_100`, so this is never compared against R8's `63.58` as a val↔test gap.

**Result** (row `20260805T182748Z`, `git_dirty: false`, `evaluator_parity: c89cfca`): `constraints_ok
13/20`, up from R5's `10/20` on the identical 20-record split — inside the pre-registered `13–15/20`
"generalizes" band, at its low end rather than its middle or high end. Full decomposition: `overall
70.53975966861671`, MicEPR `100.0`, MacEPR `100.0`, C-LPR `93.36283185840708`, `FPR
55.00000000000001` (R5's pre-P1 number on this split was `40.0`), DAV `32.604166666666664`, ATT
`42.90464519140989`, DDR `28.47222222222222`; `empty_plans 0/20`; all four `solver_flags` including
`window_anchor` confirmed `true` in per-query telemetry. Ran in `0.26 h` of the `1.00 h` envelope
(same self-terminating shape as R1/R8/R12). **Reading**: the window-aware move generalizes past the
80 `val` records it was designed against — it is not an artifact of fitting `val`'s residual — though
`13/20` sits at the low end of the predicted band rather than the middle, so P8/P9 (designed the same
way) still deserve their own held-out check rather than an assumption that everything from the same
classification generalizes equally well. Twenty records stays a coarse instrument: one query flipping
either way moves this ratio by `5` percentage points.

### R9 — the falsification run for "spend the idle envelope" *(needs P5, readable only with P2)*

```bash
TPC_P2_EXPLORE=1 .venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r9_seeds --label "seed-diversified explore, 5h"
```

**Do not read `overall` first — read flips per pass.** One extra sampling pass is measured at ~1
flip per 68 queries; the open question is whether that rate *accumulates* over the ~10 explore
passes the idle envelope affords. Independent draws would give `5–10` flips (`+1.7..+4.2` overall,
promoting P5); an exhausted reachable set gives `1–2` and closes the "we aren't using our time"
question for good. A flat flips-per-pass curve and a dying one are the two outcomes to distinguish;
the score total cannot separate them even at R7's now-zero noise floor — the two curves differ in
*shape* over passes, not in a single aggregate number.

### R11 — LLM-backed repair arm *(needs P6; not reachable before 2026-08-10)*

Off by default, and it stayed off for the uploaded `v1`. The confirmed endpoint (`Qwen3.6-27B` via
SGLang, `--max-running-requests 8`) exists only on the organizers' host, so any local number is a
proxy against a different backend. [P6](tpc_phase2_roadmap.md#p6--llm-backed-repair-proposer-v2-candidate-default-off)
is also unwritten, and it is a 1–2 day build that would then need its own gate. With `v2` due
2026-08-10 and one slot left, this arm is out of scope for this competition round; it stays recorded
as the one untried *kind* of move, not as a queued run.

### R3 — worker scaling *(closed 2026-08-05)*

```bash
.venv/bin/python scripts/phase2_full_run.py --workers 8 \
  --method phase2_e2e_r3_workers8 --label "R3 worker scaling, 8 workers, 5h"
```

R3 was registered to test the ≥8-worker deployment directly: whether parallel passes remain healthy
under the shared envelope and whether the extra throughput converts into score. Compare against the
current promoted R8/R12 baseline. The completed run shows that both worker counts already reach the
same per-query caps, so under the current scheduler this is primarily a throughput and operational
safety check rather than a test of deeper per-query search.

**Result** (row `20260805T215107Z`, `git_dirty: false`, `evaluator_parity: c89cfca`): run on a
10-core Apple Silicon Mac with exactly 8 workers and no `TPC_*` environment variables. All 100
telemetry snapshots reported the promoted defaults (`pin_timed_windows`, `window_anchor`,
`commonsense_first`, `solve_converge_patience`); P8/P9 remained default-off. Official score:
`overall 64.0773462893086`, MicEPR `99.67`, MacEPR `98.0`, C-LPR `89.90`, `FPR 44.0`, DAV `25.02`,
ATT `34.63`, DDR `25.06`; `constraints_ok 47/100`; `empty_plans 0/100`. The run completed in
`1112 s` (`18.5 min`, `6.18%` of the envelope) with triage→repair→polish at `120/300/300 s`,
`100/53/47` queries, zero failed jobs, and `100/0/13` improvements.

Against the promoted R8/R12 score baseline (`63.58458530360117`, `FPR 43.0`, `constraints_ok
46/100`) and R12's matching bare-default wall time (`4769 s` on 3 workers / 4-core Linux), the
8-worker row is `+0.4928` overall and one passing query higher while taking `4.29×` less cross-host
wall time. **Reading:** the ≥8-worker scheduler is
operationally safe and does not trade score for throughput. It does *not* prove that worker count
caused the one-query gain: the host changed, and both configurations already reached the same
per-query caps, so extra workers bought completion speed rather than deeper per-query search. R3 is
closed; a worker-only causal estimate would require paired worker counts on the same host, which is
not needed for the submission decision because the requested 8-worker deployment passed directly.

### What not to spend a slot on

- **A repeat of a run you already have.** Post-P0 the solver is bit-for-bit reproducible ([R7](#what-the-closed-queue-r1r17-established)),
  so a rerun of the same configuration on the same host returns the same number. [R14](#r14--the-p8p9-gate-the-one-run-that-decides-whether-v2-exists-closed-2026-08-06-green)
  already closed GREEN off a single run; do not repeat it hoping for a different number.
- **Any whole-run row whose configuration you cannot read off its own telemetry.** Check
  `solver_flags` first, score second. A mislabelled arm costs a full envelope and proves nothing.
- **The old per-query `900 s` pinned gate as a ship signal.** It measures a contract the competition
  does not use. Keep it for solver-change A/Bs only.
- **More envelope-sensitivity runs.** `1 h / 3 h / 5 h` is flat and the
  [diagnosis](tpc_phase2_roadmap.md#the-diagnosis) explains why.
- **Preference-packing flags (`TPC_PACK_*`).** Every preference term is zeroed for a query that fails
  its constraints, so each is capped at FPR: at R8's `FPR 43.0` the whole remaining headroom across
  DAV/ATT/DDR is `2.3` overall (`0.05 × [(43−24.71)+(43−33.65)+(43−24.50)]`), and that number only
  grows by raising FPR first. It was `~1.5` at R1's `FPR 33.0` — the ceiling moves with FPR, which is
  the argument for spending the slot on FPR either way.
- **Anything LLM-backed.** The shipped path makes zero LLM calls, the one screened parse arm came
  back RED, and no endpoint is reachable from the evaluation machine.
- ~~Single-run A/Bs of small effects. Run R7 first.~~ R7 is closed (sd `0`); a single run is now
  sufficient evidence for any nonzero delta.

## Before the first run

On the evaluation machine:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-submission.txt   # or: uv pip install -r ...
nproc                                    # workers default to this minus one
.venv/bin/python -m pytest tests/phase2  # ~1 min, catches an obviously broken checkout
```

Sanity-check the machinery on a short envelope first — 12 minutes, not 5 hours:

```bash
.venv/bin/python scripts/phase2_full_run.py \
  --split tpc_phase2_familiar_100_val --total-budget-sec 720 --label "plumbing check"
```

Expect a `[sweep] pass 1 (triage) ...` line, one row under `results/phase2_baselines/full_runs/`,
and `empty_plans` well below the query count. If the run ends far short of its envelope, the last
`[sweep]` line says why. A `720 s` envelope legitimately fits only one triage pass, and high
`empty_plans` at that compressed budget is expected.

**If a row comes back with anomalously many `empty_plans`, suspect a broken worker pool before
suspecting the solver.** A worker that dies during start-up takes the whole `ProcessPoolExecutor`
with it, and the run still **exits 0** and writes a complete set of plan files — they are just the
pre-written empty fallbacks. The tells are the row's per-pass `failed` count, `empty_plans`, and
`Exception in initializer` on stderr. One instance (a cold-tree race on `cache/phase2_solve`) was
fixed 2026-08-05, but the failure *shape* outlives that cause — see the [pre-submission
checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).
Every row committed before that date was produced in a warm tree and is unaffected.

## Two measurement contracts

Since the organizers confirmed the real execution contract (2026-08-04) there are two different
questions and two run shapes. Mixing their rows is the easiest way to reach a wrong conclusion.

| | **Whole-run** (what we ship) | **Per-query** (solver quality) |
| --- | --- | --- |
| Question | what would this score in the real evaluation? | is the solver better on a query at a fixed budget? |
| Time contract | one 5 h wall clock for all 100 queries | fixed `900 s` (or `300 s`) *per query* |
| Scheduling | triage → repair → polish, best-so-far kept | one pass, split order |
| Parallelism | `CPU count - 1` worker processes | one query at a time per chunk |
| Tool | `scripts/phase2_full_run.py` (`make phase2-full-run`) | `make phase2-baseline` / `phase2-rehearse` |
| Rows | `results/phase2_baselines/full_runs/` | `results/phase2_baselines/runs/` |
| Promotes | the submission configuration | a solver change, via the [gate](#gates) |
| Pre-gate screen | `scripts/phase2_quick_eval.py --mode whole-run` (since [P11](tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen-landed-2026-08-06)) | `scripts/phase2_quick_eval.py` |

**That last row closed on 2026-08-06.** Until P11 landed, a whole-run change either shipped unscreened
or spent 5 h to find out it was flat; both contracts now have a 1–2 h pre-gate screen. A screen still
never promotes — see [the whole-run screen mode](#the-whole-run-screen-mode).


**Rows from the two contracts are never comparable**, whatever else matches: different budget
contract, scheduler and parallelism. Every whole-run row records `kind: "full_run"`. The per-query
rehearsal is not retired — it still answers "is the solver better on this query at a fixed budget",
which is the right question for a solver change. It is no longer the signal that decides what ships.

**Per-query gate budget: `900 s`.** There is no organizer per-query timeout, so this is purely a
development setting: a change is judged with the solver allowed to converge, which is what
`TPC_PIN_TIMED_WINDOWS` and `TPC_REPAIR_TRANSPORT_GAPS` needed (both trade wall-clock for FPR and
were blocked only by a `300 s` no-new-timeouts guard). `300 s` is a faster sensitivity setting, the
quick screen runs at `60 s`, and `make phase2-budget-sweep` (`30,60,120,300,900`) checks that a
promotion is not fragile at a shorter budget.

### Three attribution axes

| Axis | Input and purpose | Meaning |
| --- | --- | --- |
| Ceiling | `results/best` with released oracle logic and offline iteration | aspirational upper bound, not a harness baseline |
| Solver-only | oracle constraints, bounded autonomous solve | solver headroom after parsing is removed |
| End-to-end | visible text, no oracle, bounded harness | the local approximation to the submitted path |

Ceiling → solver-only is bounded-solver headroom; solver-only → end-to-end is parsing and harness
loss. `scripts/parser_vs_oracle.py` diagnoses constraint-family differences, but a parsing change is
promoted only on an end-to-end measurement.

## Score semantics, and the evaluator contract

`eval_tpc.py` publishes one aggregate:

$$
0.10\,\mathrm{EPR\!\text{-}micro} + 0.10\,\mathrm{EPR\!\text{-}macro} + 0.25\,\mathrm{C\!\text{-}LPR} + 0.40\,\mathrm{FPR} + 0.05\,(\mathrm{DAV}+\mathrm{ATT}+\mathrm{DDR}).
$$

Its per-query score for monotonic merging is different — it assigns both 10% environmental slots
from that query's binary commonsense result. That helps rank merge candidates; it is not a second
official aggregate.

Three properties decide what is worth measuring:

- **C-LPR is the *conditional* logical micro.** A plan failing commonsense scores `0` on the
  `0.25`-weighted logical term *and* `0` on its EPR-macro point, however many clauses it satisfies.
- **DAV/ATT/DDR are averaged over every query in the split**, with a zero for each non-passing query
  (changed 2026-07-28). Each preference term is therefore bounded above by FPR, and perfecting one is
  worth at most `0.05 · FPR`.
- **ATT is `0` for a plan with no innercity transport** (it used to be a clamped `1.0`), so a
  degenerate transport-free plan no longer scores a perfect ATT.

**Evaluator parity moves invalidate comparisons.** Two upstream syncs landed: 2026-07-28 `764614c`
(the two changes above, plus intra-day chronology and one-meal-type-per-day enforced in the official
checker, and the local `patched_*` keys removed) and 2026-08-04 `c89cfca` (no scoring change;
canonical concept labels and mode-reading `innercity_transport_*` helpers, which move end-to-end
rows because the solver now canonicalizes its own constraint literals). `EVALUATOR_PARITY_SHA` is
`c89cfca`; `scripts/phase2_gate.py` refuses to gate across the boundary, including one-sided marker
presence. Full detail: [competition reference](reference/competition.md#evaluator-version).

## What the closed queue (R1–R17) established

Run 2026-08-04/05/06 primarily on a 4-core box (3 workers), plus R3 on a 10-core Mac (8 workers),
`evaluator_parity: c89cfca`, rows under `results/phase2_baselines/full_runs/`. **Nothing on this
list needs re-running.**

| Run | Row | Result |
| --- | --- | --- |
| R1 reference, 5 h | `20260804T201638Z` | `overall 57.99`; MicEPR `99.48`, MacEPR `97.00`, C-LPR `87.83`, **FPR `33.00`**, DAV `18.15`, ATT `26.25`, DDR `19.39`; `empty_plans 0/100`, `constraints_ok 35/100`; **used `26%` of the envelope** (`4723 s` of `18000 s`) |
| R2 envelope sensitivity | `20260804T213636Z` (1 h), `20260804T221103Z` (3 h) | `57.35 / 57.86 / 57.99` at 1/3/5 h — **flat** |
| **R3 worker scaling, 5 h** | `20260805T215107Z` | 8 workers on a 10-core Mac: `overall 64.08`, FPR `44.0`, `constraints_ok 47/100`, `empty_plans 0/100`; `1112 s` (`6.18%` of envelope), zero failed jobs. Versus the R8/R12 score baseline and R12's bare-default wall time: `+0.49` overall, `+1` FPR, `+1` passing query, and `4.29×` lower cross-host wall time. Same per-query caps on different hosts mean **healthy/non-regressing 8-worker deployment**, not a clean worker-only causal score gain |
| R4 pass shape | `20260804T231910Z` control, `20260805T001808Z` A, `20260805T011733Z` B, `20260805T021805Z` C, `20260805T032037Z` control repeat | arms A/B were accidental no-ops (their caps never bound); arm C (`TPC_P2_FAST_TRIAGE=0`) `58.40` vs `57.81` |
| R5 held-out tripwire | `20260805T042106Z` | `overall 62.59` on the 20-record test split, `constraints_ok 10/20` |
| R6 packaged archive | no row (checks the zip, not a split) | `fabiundstefan_v1.zip`, `1676` entries, `4.0 MB`, from commit `b44bb73c096b`; unpacked and run with a stripped `PATH`: `valid_output=True` |
| **R7 seed-variance baseline, 5 h ×3** | `20260805T081535Z`, `20260805T094549Z`, `20260805T110654Z` | **bit-for-bit identical across all three repeats**: `overall 57.74985419574877`, MicEPR `99.67`, MacEPR `98.00`, C-LPR `88.82`, FPR `32.0`, DAV `16.625`, ATT `24.53`, DDR `18.42`; `constraints_ok 36/100`; per-pass telemetry (`improved`/`elapsed_sec`) matches to within noise across the three runs too |
| **R8 window-aware move, 5 h** (`TPC_WINDOW_ANCHOR=1`) | `20260805T123142Z` | `overall 63.58` (**`+5.83`** over R7); MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.90`, **FPR `43.0`** (**`+11.0`**), DAV `24.71`, ATT `33.65`, DDR `24.50`; `empty_plans 0/100`, `constraints_ok 46/100` (**`+10`**); matches the paired `n=80`/`90 s` screens (predicted FPR `32.5 → 42.5`) closely; used `26%` of the envelope (`4733 s`). **Promoted to a harness default 2026-08-05 — this row is the new baseline** |
| **R10 phase1-under-phase2, 5 h** (diagnostic, 1000 queries) | `20260805T135254Z` | `overall 85.20`; MicEPR `100.0`, MacEPR `100.0`, C-LPR `95.57`, FPR `85.4`, DAV `29.86`, ATT `59.52`, DDR `53.53`; `empty_plans 0/1000`, `constraints_ok 715/1000`; `1.60 h` of the envelope. `git_dirty: true` (see caveat below) |
| **R12 promotion equality check, 5 h, no env vars** | `20260805T170120Z` | **bit-for-bit identical to R8**: `overall 63.58458530360117`, MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.90`, FPR `43.0`, DAV `24.71`, ATT `33.65`, DDR `24.50`; `empty_plans 0/100`, `constraints_ok 46/100`; `git_dirty: false`; all four `solver_flags` (`pin_timed_windows`, `window_anchor`, `commonsense_first`, `solve_converge_patience`) confirmed `true`/set in per-query telemetry with nothing exported. Paired archive check (no row; checks the zip, not a split; re-run after a rebase moved packaging into `submissions/phase2/` in the same window): `submissions/phase2/fabiundstefan_v1.zip`, `1683` entries, `4.3 MB`, from commit `aba52e7a02c9`; unpacked into a directory that had never been run in and run there with the harness's own worker default (no `--workers` override, so more than one worker starts — see the [cold-start rule](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05)) via `--split tpc_phase2_familiar_100_val --limit 6 --budget-sec 90`: `6/6` plans with a non-empty itinerary, no worker start-up failure, `llm_backend=none`, `valid_output=True` |
| **R13 held-out tripwire, 1 h** (`familiar_100_test`, post-P1) | `20260805T182748Z` | `overall 70.53975966861671`; MicEPR `100.0`, MacEPR `100.0`, C-LPR `93.36`, FPR `55.0` (R5 pre-P1: `40.0`), DAV `32.60`, ATT `42.90`, DDR `28.47`; `empty_plans 0/20`, **`constraints_ok 13/20`** (R5 pre-P1: `10/20`) — inside the pre-registered `13–15/20` "generalizes" band; `git_dirty: false`; all four `solver_flags` confirmed `true`; `0.26 h` of the `1.00 h` envelope |
| **R14 P8+P9 gate, 5 h** (`TPC_WINDOW_PUSH=1 TPC_WINDOW_INSERT=1`), 4-core Linux, 3 workers, vs R8/R12 baseline | `20260806T052925Z` | `overall 64.13167839953107` (**`+0.5471`** over R8/R12's `63.58458530360117`); MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.99`, **FPR `44.0`** (**`+1.0`**), DAV `25.54`, ATT `34.53`, DDR `25.28`; `empty_plans 0/100`, **`constraints_ok 46/100` (unchanged)**; `git_dirty: false`; all 100 per-query `telemetry.json` confirmed `window_push`/`window_insert`/`window_anchor` all `true`; `1.32 h` of the `5.00 h` envelope, zero failed jobs across triage/repair/polish (`100/54/46` queries, `100/1/13` improved). **GREEN by the pre-registered rule** (overall up, FPR not down, no empty plans, no failed jobs), but the paired screen over-predicted this row on all three axes (predicted `64.5–65.5`/`45–46`/`48–49`, measured `64.13`/`44.0`/`46`) and `constraints_ok` did not move at all — the gain is one FPR point plus preference terms, not new passing queries. Flag promotion into `PROMOTED_SOLVER_FLAGS` is an Implementation-workstream follow-up, not done in this row |
| **R15 held-out tripwire, 1 h** (`familiar_100_test`, post-P8/P9), 4-core Linux, 3 workers, vs R13 on the identical 20 records | `20260806T065521Z` | All seven official metrics **bit-for-bit identical to R13**: `overall 70.53975966861671`, MicEPR `100.0`, MacEPR `100.0`, C-LPR `93.36`, FPR `55.0`, DAV `32.60`, ATT `42.90`, DDR `28.47`; `empty_plans 0/20`, **`constraints_ok 13/20`** (tied with R13); `git_dirty: false`; all 20 `solver_flags` confirmed `window_push`/`window_insert`/`window_anchor` `true`; `0.26 h` of the `1.00 h` envelope. Diffing the plan directories on disk (`results/phase2_e2e_r13_test/` vs `results/phase2_e2e_r15_test/`) found **19/20 plans byte-identical** apart from `elapsed_time(sec)`; the 20th query got a real P8/P9 edit (every timed visit shifted `14–15` min) that moved no official metric — consistent with that query's pass/fail status being unchanged either side, though the row's telemetry has no per-query pass/fail counter to confirm that beyond the aggregate arithmetic. **The tripwire never armed**: with the flags changing only 1/20 plans and moving nothing, this row is neither evidence the residual generalizes nor evidence it doesn't |
| **R16 `v2` candidate gate, 5 h**, post-P10 `main`, P8/P9 promoted, nothing exported, 4-core Linux, 3 workers, vs R14 and R8/R12 | `20260806T082724Z` | `overall 64.14997555172528` (**`+0.0183`** over R14's `64.13167839953107`; **`+0.5654`** over R8/R12's `63.58458530360117`); MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.99`, **FPR `44.0`** (unchanged from R14, **`+1.0`** over R8/R12), DAV `26.04`, ATT `34.48`, DDR `25.19`; `empty_plans 0/100`, zero failed jobs across triage/repair/polish (`100/49/51` queries, `100/1/14` improved); `git_sha: 241c0524`, `git_dirty: false`; all 100 per-query `telemetry.json` confirmed `variants_source=parent`, zero queries with `variants_count == 0`, and `window_push`/`window_insert`/`window_anchor` all `true` with nothing exported; `1.31 h` of the `5.00 h` envelope. **GREEN by the pre-registered rule** (overall within `0.5` of R14, FPR not down, no empty plans, no failed jobs), and this row is also the clean, undiluted `v1 → v2` delta since it is the only row with both P10 and P8/P9 in the tree at `n=100`. `constraints_ok` (the scheduler's own self-score) read `51/100`, **`+5`** over R14 — the self-scoring effect P10 was built to fix, explicitly not a promotion signal by the doc's own rule |
| **R17 ship candidate, 5 h**, post-P11/P12 `main`, nothing exported, 4-core Linux, 3 workers, vs R16 | `20260806T115309Z` | `overall 64.17251838310492` (**`+0.02254283`** over R16's `64.14997555172528` — inside noise); MicEPR `99.67`, MacEPR `98.00`, C-LPR `90.08`, **FPR `44.0`** (unchanged from R16), DAV `26.04`, ATT `34.48`, DDR `25.19`; `empty_plans 0/100`, zero failed jobs across triage/repair/polish (`100/50/50` queries, `100/1/14` improved); `git_sha: efbfea96bea19610f9d725ebec2fd6f5d6b5cceb`, `git_dirty: false`; all 100 per-query `telemetry.json` confirmed `variants_source=parent`, zero queries with `variants_count == 0`, and `window_push`/`window_insert`/`window_anchor` all `true` with nothing exported; `1.38 h` of the `5.00 h` envelope. **GREEN by the pre-registered rule** (overall within `0.5` of R16, FPR not down, no empty plans, no failed jobs). `constraints_ok` read `50/100`, **`-1`** versus R16 — P12's predicted signature (the tightened gate no longer counts a vacuous pass), not itself a promotion signal. Byte-diffing the plan directory against R16's (`results/phase2_e2e_r16_v2cand/`) found **99/100 plans identical**; the one changed query (`phase2_familiar_20250322120414354584_00052`) had its implausible overnight-flight plan rejected by P12's tightened gate and replaced with a coherent full-day itinerary, moving no aggregate metric outside noise. **Action: `v2` ships from this row's sha, `efbfea96`, not from R16's `241c0524`** |

**On R10's `git_dirty: true`.** By the letter of the [ledger rule](#ledger-comparability) this row
is not proven reproducible from its commit alone, and that should not be waved away. What actually
happened: `git status --porcelain` at record time showed exactly one changed path,
`chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` (`1` file, `593` insertions,
reverted — not committed), because `eval_tpc.py`'s `update_suboptimal_split_file` unconditionally
rewrites that split's suboptimal-ID file on every full-split scoring call. The file is tracked from
earlier history but is now `.gitignore`d going forward ("regenerated by every scoring run"). This
makes the dirtiness **structural, not a one-off**: scoring the full `tpc_phase1` split through
`eval_tpc.py` will reproduce the identical `git_dirty: true` on *any* rerun from *any* commit,
including a from-scratch rerun of this exact row — there is no clean-tree rerun that fixes it under
the current tooling. It does not touch solver code or plan outputs, so the `overall`/`FPR`/
`constraints_ok` figures above are unaffected by it, but achieving a `git_dirty: false` R10 row
would need an Implementation-workstream change (stop `eval_tpc.py` writing the file during a
read-only scoring pass, or fully untrack it) — not a rerun.

R7's finding: **sd = 0, range = 0** on this box post-P0 — the pinned restart seed
([P0](tpc_phase2_roadmap.md#landed-and-promoted), landed 2026-08-05) removed the salted-`hash()`
source of cross-process variance that produced the pre-fix spreads below (`sd 0.35` at 2 h, `Δ 1.04`
at 1 h). **Every later arm on this list is now judged against a near-zero floor, not `sd 0.35`** —
a single run resolves an effect well under `1` point, and no arm needs repeats unless a future
result actually shows spread. (Pre-fix spreads, kept for context: 2 h `n=4`
(`57.34 / 57.81 / 57.82 / 58.20`), sd `0.35`, range `0.86`; 1 h `n=2` (`57.35` R2, `56.31`
diagnostic), Δ `1.04` overall, Δ `2.0` FPR — a single pre-fix run could not resolve anything under
about `2` points.)

Five findings, and two corrections that matter more than the scores:

1. **The run self-terminates at `26%` of the envelope.** Repair and polish both clamp to the
   effective `max_query_sec` (`300 s`), and `_choose_pass` drops a candidate unless its new budget
   beats its last by `MIN_BUDGET_GROWTH` — so a query already solved at the cap can never re-enter a
   pass, the candidate list empties, and the sweep reports *"no pass would do anything new."*
2. **The idle `3.4 h` is not recoverable by scheduling.** This queue originally blamed the `300 s`
   cap and made raising it the top follow-up. Per-query search telemetry retired that: failing
   queries exhaust a *search*, not a clock — `2.5×` the budget buys `4.2×` the restarts and flips
   **one query in sixty-eight**. Extra envelope, a higher cap, more workers and fresh seeds are one
   intervention wearing four hats. See the [diagnosis](tpc_phase2_roadmap.md#the-diagnosis).
3. **Arm C's `+0.59` does not survive this queue's own variance estimate.** The *mechanism* finding
   stands and is clean: with fast triage off, polish improved `0/34` versus `10/33`, `14/33`, `14/34`,
   `13/34` in the four other 2 h runs, because triage now performs the preference search polish
   exists to do. **The work moved; it did not grow** — which predicts a near-tie. Against the four
   same-config samples (mean `57.79`, sd `0.35`), `+0.59` is `1.7 sd` and only `0.20` above a plain
   control rerun. Do not carry it forward.
4. **`improved` is not a score signal; `constraints_ok` is.** The 1 h diagnostic row
   (`20260805T061217Z`) has repair `improved 11` with `constraints_ok +1`: ten of the eleven were
   preference-key moves on queries that still fail, and preference is zeroed on a failing query.
5. **Post-P0, the same-config spread is zero.** R7's three 5 h repeats are bit-for-bit identical.
   The pre-fix variance (`sd 0.35` at 2 h) was entirely the salted-`hash()` restart-seed artifact P0
   removed, not genuine solver or scheduler nondeterminism.
6. **R8 is the first arm that actually moved FPR** — `+11.0` against a `sd 0` baseline, so the
   effect is unambiguous, not noise. This is the confirmation of the roadmap's diagnosis: the
   solver's failure mode was a missing window-aware move, not insufficient search time, and fixing
   the move (not spending more budget on the old sampler) converts directly into FPR.
7. **Removing the oracle costs `13.78` points on `tpc_phase1`** (R10): `85.20` end-to-end against
   `98.98` oracle-fed. Not comparable to any `familiar_100` row — `tpc_phase1` is 1000 queries at a
   tenth the per-query pressure — but it is the clean oracle-ablation figure the technical report
   wants.
8. **The promotion is confirmed, not just applied** (R12): the bare organizer command, with no
   `TPC_*` variable exported, reproduces R8 bit-for-bit — same `overall`, same `FPR`, same
   `constraints_ok`, same pass shape, all four promoted `solver_flags` on. `apply_deterministic_solver_defaults()`
   and the explicit `TPC_WINDOW_ANCHOR=1` environment path are the same configuration in practice, not
   just in intent.
9. **The window-aware move generalizes past `val`** (R13): `constraints_ok` on the untouched
   `familiar_100_test` split moved `10/20 → 13/20` between the pre-P1 (R5) and post-P1 (R13)
   configurations — inside the pre-registered `13–15/20` band that was defined, before this run, to
   mean "the move generalizes" rather than "P1 fit `val`'s residual" (which would have held at
   `10/20`). It lands at the low end of that band, so the finding is "generalizes, with headroom
   uncertain" rather than "generalizes as strongly as `val` suggested."
10. **P8/P9 gate GREEN, but on a thinner margin than `overall` alone suggests** (R14): `+0.5471`
    overall and `+1.0` FPR against the R8/R12 baseline, with `constraints_ok` flat at `46/100` — the
    gain is FPR plus preference terms, not new passing queries, and it landed below every axis of the
    paired screen's prediction rather than above. The rule still says GREEN (overall up, FPR not
    down, no empty plans, no failed jobs), so the flags queue for promotion, but the margin is the
    thinnest of any GREEN gate run so far.
11. **P8/P9's held-out tripwire never armed** (R15): all seven official metrics matched R13
    bit-for-bit, and diffing the plan directories showed why — the flags changed 1 of 20 held-out
    plans (a real timing shift) and left every metric unmoved, rather than flipping any query's
    pass/fail status. `13/20` is therefore not the ordinary "one query moved each way" tie the doc's
    pre-registered band anticipated; it is closer to "the flags mostly didn't fire here." Combined
    with R14's flat `constraints_ok`, the pattern across both P8/P9 rows is that the two passes fire
    rarely on this distribution — real when they do (R14's `+1.0` FPR, this row's one shifted plan),
    but thin. This does not overturn R14's GREEN, but it is the fact most relevant to whether the
    `v2` slot is worth spending on these two flags.
12. **P10 does not interact destructively with P8/P9 at `n=100`** (R16): the shipping configuration
    (post-P10 `main`, P8/P9 promoted, nothing exported) scored `64.14997555172528`, `+0.0183` over
    R14's P10-absent `64.13167839953107` and `+0.5654` over the R8/R12 baseline, with `FPR` flat
    against R14 and `+1.0` against R8/R12 — GREEN by the pre-registered rule, and the full,
    undiluted `v1 → v2` delta since this is the only row with both changes in the tree at full size.
    `constraints_ok` moved `46 → 51/100` on the self-score alone, confirming P10's intended effect
    (the scheduler stops under-counting its own successes) without moving `overall` — exactly the
    "self-score effect, not a scoring one" the row was registered to check for, and, per the doc's
    own rule, not itself a reason to read the gate any differently.
13. **P12 does not cost score on the shipped path, and it fires rarely** (R17): the tree `main`
    would actually ship (`efbfea96`, post-P11/P12) scored `64.17251838310492`, `+0.02254283` over
    R16's `64.14997555172528` — inside noise — with `FPR` unchanged, `empty_plans 0/100`, and no
    failed job on any pass. GREEN by the pre-registered rule. `constraints_ok` fell one point
    (`51 → 50/100`), the tightened gate's predicted self-score signature, not a promotion signal.
    Byte-diffing the plan directory against R16's found P12 fired on exactly `1/100` queries,
    replacing an implausible overnight-flight itinerary with a coherent one — confirming both that
    the fix reaches the shipped path (P12's own screen never established this) and that its blast
    radius is as small as predicted. `v2` ships from this row's sha, not R16's.

R5 and R13 are recorded standalone: `familiar_100_test` is a *subset* of `familiar_100` (R1's split),
so no val↔test gap is computed against R1/R8/R12's `overall`. R13's `70.54` above R8's `63.58` is
consistent with a smaller, easier split scoring higher on the same code, not a generalization signal
by itself — the generalization claim rests on the `constraints_ok` movement relative to R5, not on
the `overall` gap. R6 checks packaging only, never score.

**What the queue does not answer:** whether 100 queries converge this fast on the organizers'
held-out set (only their harness run will tell). R7 closes the "is any arm worth more than noise"
question — the floor is now ~0, so smaller effects are measurable, not that they exist.

## Dataset boundaries

Every measurement must name its source. These four have different trust and generalization
properties; none substitutes for the organizer's final held-out set, and rows are never compared
across them as if the distribution or oracle exposure matched.

### 1. Official familiar-100 (preferred signal)

The organizers released the [familiar-100
archive](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip)
on 2026-07-15. The 100 records are imported unchanged under
`chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/` and selected by
`tpc_phase2_familiar_100`; `_provenance.json` pins the source URL, dates, archive SHA-256 and every
member's size/CRC32/SHA-256. Records carry `hard_logic_py`; loaders retain it for scoring only,
while the adapter and both harnesses expose just `uid`, trip metadata and `nature_language` to the
agent path. Same distribution as final evaluation, so it is the preferred development signal — but a
familiar-100 result must name this artifact and its run configuration and is never a
final-evaluation estimate.

**Val / held-out-test partition (since 2026-07-23).** `scripts/make_familiar_splits.py` splits the
100 records once, deterministically (seed `20260723`), into `tpc_phase2_familiar_100_val` (80) and
`tpc_phase2_familiar_100_test` (20); `make phase2-familiar-splits` regenerates or inspects them
(frozen unless `--force`). The split is **stratified by trip length (`days`)** — the strongest
available difficulty signal, since `days` spans 1–5 with real spread and drives solve difficulty,
whereas the `hard_logic_py` clause count is a narrow 9–13 — so val and test carry the same day-count
mix and a val gain is likelier to carry. **Every screen and development gate runs on val; test is an
occasional overfitting tripwire, never a per-change signal.** Two caveats stand: 20 records is a
coarse, high-variance tripwire, and neither split is the organizer final set.

### 2. Repository-local released data

Released Phase 1 English queries with oracle fields under
`chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/`; `make phase2-splits` partitions them into
`tpc_phase2_val` / `tpc_phase2_test`. Despite the local `test` name these are **not** organizer
held-out data, and they average `~16` `hard_logic_py` constraints per record versus `~38` in
familiar-100, so they under-represent the final distribution's constraint density. Usable only when
the agent path hides oracle fields.

### 3. Hugging Face ChinaTravel

[`LAMDA-NeSy/ChinaTravel`](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel) is an
out-of-distribution phrasing-generalization probe, never a tuning target. It is natively Chinese;
`load_hf_queries` uses `nature_language_en`, so the "OOD" gap versus familiar-100 is a
phrasing-register difference within English (free prose vs. rigid templates), not a cross-language
one. Keep configuration and split names with every result:

```bash
.venv/bin/python scripts/compare_hf_dataset.py --hf-config default
```

### 4. Organizer final held-out set

Separate, unavailable locally, evaluated only through the organizer-run no-oracle harness on
Qwen3.6-27B via SGLang. No local split, HF subset or familiar-100 result proves performance on it.

## Ledger comparability

Compare rows only when they match on:

- **measurement contract** — a whole-run row is never comparable to a per-query row;
- source revision, data source, split, deterministic fold/limit, and language;
- **evaluator contract** — rows straddling either sync (`764614c`, `c89cfca`) are never comparable;
  each row's `evaluator_parity` names its side;
- budget, repeat count, parallelism and fresh-output policy — for a whole-run row that means
  `total_budget_sec`, `workers`, and any `TPC_P2_*` pass-shape override (note it in `--label`);
- parser, solver and feature flags — the promoted deterministic ones are recorded per query under
  `solver_flags`, so read them off the row instead of assuming the label is right;
- LLM backend/model and cache policy when an LLM is enabled.

Whole-run rows additionally require the **same machine**: worker count, core count and memory
pressure move the result directly, so a row from a 4-core laptop says nothing about a 16-core
evaluation host. `git_dirty: true` means the row is not reproducible from a commit — rerun it from a
clean tree before deciding anything with it.

A row must expose enough telemetry to explain its score: valid-output rate, parse failures, timeout
and recovery counts, fallback use, stage timings, LLM attempts/failures, and the three attribution
axes. Low-`n` rows are smoke checks, not promotion evidence. Long per-query runs use
`make phase2-baseline-at SHA=<ref> ...` so the recorded revision is the code that executed.
Familiar-100 rows carry the manifest-derived data-source ID and stay separate from the local
partitions. Ledger field semantics are in the [baseline ledger guide](phase2_baselines/README.md).

## Gates

```bash
make phase2-gate BASELINE=results/phase2_baselines/runs/<base>.json \
  CANDIDATE=results/phase2_baselines/runs/<candidate>.json
```

When both inputs supply `continuous_score` it is the blocking score and FPR is advisory; otherwise
FPR blocks. In every case more parse failures or timeouts block promotion. The no-new-timeouts guard
is evaluated **relative to the budget both rows ran at** — pair rows at the same budget. A timeout
regression measured at `300 s` does not block a change whose intended budget is `900 s`; re-gate the
pair before concluding.

Early-stop modes are diagnostic only, never set by the real harness, and never gate-compared against
normal rows:

- `--fast-fpr` (`TPC_SOLVE_STOP_AT_ACCEPT`) stops at the first accepted plan and **skips
  `_pack_plan`**, so it cannot measure the repair passes (`_pin_timed_windows`,
  `_repair_transport_gaps`). Rows are forced to a `fastfpr-` label prefix.
- `--fast-fpr-packed` (`TPC_SOLVE_STOP_AT_ACCEPT_PACKED`) stops at the first accept but still runs
  `_pack_plan`, so use this one to fast-measure those passes. Its continuous score is uncalibrated;
  rows carry a `fastfprpacked-` prefix.

Both preserve the binary FPR signal (a pre-pack accept stays accepted; `_pack_plan` only commits
changes that keep the checker accepting and do not regress the preference key).

## Quick A/B screen

The pinned gate is authoritative but slow. Gating every landed change behind its own isolated
end-to-end run costs `O(changes × 8 h)` and falls behind the rate of new work, so the screen is the
pre-filter that decides *within 1–2 h* whether an off-by-default flag is worth a real run. **It ranks
and triages; it never promotes.** Tool: `scripts/phase2_quick_eval.py`
(`make phase2-quick-eval P2_FLAG=<env var>`).

It cuts wall-clock on three axes and trusts only the **paired delta**, never the absolute numbers: a
deterministic subset (`--n`, default `40`), a reduced budget (`--budget-sec`, default `60`), and a
same-subset/same-seed off-vs-on pair where only one flag changes. The reduced budget keeps the signal
because the deterministic flags act at the **acceptance boundary** inside `_pack_plan`, before the
acceptance gate, so their FPR effect shows even when the restart loop is cut short.

Default mode is `solver-only` (oracle constraints, no LLM). Per arm it reports `FPR`,
`overall_true`, `timeouts`, `solve p50`, `used_fallback`, `parse_failures`, and the per-layer
metrics (EPR micro/macro, C-LPR, logical micro, `all_pass`), then runs the monotonic gate on
gate-shaped keys and prints a reconciled verdict.

```bash
make phase2-quick-eval P2_FLAG=TPC_PIN_TIMED_WINDOWS P2_N=40 P2_BUDGET=60 P2_PARALLEL=3
# stack on an already-on flag:
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_REPAIR_TRANSPORT_GAPS \
  --extra-env TPC_PIN_TIMED_WINDOWS=1 --n 40 --budget-sec 60 --parallel 3
```

**Reuse one baseline across flags**: the `flag=off` arm is identical for every deterministic flag, so
run it once and pass `--baseline-json results/<out>/baseline.json`. You own the
subset/budget/seed match; the tool trusts the reused baseline. Cost per arm ≈
`ceil(n / parallel) × (budget_sec + ~3 s)`; keep `--parallel` at `cores − 1` (each CP-SAT solve is
single-threaded).

**Reading the verdict.** GREEN LIGHT (target improves, gate passes) → queue for a real run. GREEN
with caveat (the only block is more *recovered* timeouts at the tight budget) → expected when a flag
does more work per solve; still queue. MIXED (non-timeout gate block) → read the blocks. RED (FPR,
`overall_true` or `parse_failures` regress) → bounce it back. NEUTRAL → enlarge `--n`/`--budget-sec`
or pick a subset that exercises the flag.

### LLM-backed flags

`--mode end-to-end` plus a configured backend screens `TPC_P2_LLM_PARSE` / `TPC_P2_LLM_REFINE`. The
key is loaded for you — `build_llm_client` calls `load_local_env()`, which reads the repo-root `.env`
into the process when the backend is `openai`/`deepinfra`. Never source, read or echo `.env`
yourself; export only the backend selector.

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_LLM_PARSE --mode end-to-end \
    --off 0 --on 1 --extra-env "TPC_P2_LLM_BACKEND=deepinfra,TPC_P2_LLM_TIMEOUT_SEC=6" \
    --n 30 --budget-sec 90 --parallel 3 --out results/phase2_quick_eval/llm_parse
```

- **Lower the LLM timeout below the reduced slice or the flag silently no-ops.** Both stages skip the
  LLM when their slice is smaller than the client timeout. Default is `30 s`; at a `90 s` screen
  budget the parse slice is `~22 s` and the improve slice `~9 s`, so `6` is the working value.
- **Verify the arm actually called out** (`llm_parse` fired, no `llm_parse_skipped_deadline`, or
  `improve_llm_called: true`). A green screen where the LLM never fired is meaningless — a first
  `TPC_P2_LLM_PARSE` pass looked `+1.97` only because `10/30` audits timed out and fell back to the
  deterministic parse; with all `30` firing the verdict flipped to RED (`−3.20`).
- Pin the *other* LLM flag across both arms, and screen each with explicit `--off 0 --on 1`.
- With the backend at `none` (library default) the end-to-end path makes zero LLM calls, so
  deterministic flags can also be screened `--mode end-to-end` on a box with no key.

### The whole-run screen mode

**`--mode whole-run` landed 2026-08-06** ([P11](tpc_phase2_roadmap.md#p11--a-whole-run-mode-for-the-pre-gate-screen-landed-2026-08-06)).
Before it, **both** screen modes took the per-query path: `--mode end-to-end` calls
`rehearse._run_end_to_end`, which invokes `run_split` **without** `total_budget_sec`, and `run_split`
only dispatches to `run_sweeps_split` when an envelope is set. So triage/repair/polish pass selection,
incumbent keep-best, deadline-aware budgeting and `selfscore` — everything the shipped run actually
does — were structurally unreachable from `phase2_quick_eval.py`, and a green screen said nothing about
a change living there. That was found while screening
[P10](tpc_phase2_roadmap.md#infrastructure-landed), whose entire effect is in that path.

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_WINDOW_PUSH --mode whole-run \
    --n 40 --budget-sec 90 --total-budget-sec 1800 --workers 6
```

It drives `run_sweeps_split` on a subset under a small envelope and pairs off-vs-on like any other
arm, reporting the scheduler's own numbers (`constraints_ok`, `self_overall_mean`/`self_fpr_mean`,
per-pass `improved`/`completed`/`failed`, `fallbacks_prewritten`, `empty_plans`, the
`variants_source` histogram) alongside the official metrics — a scheduler change that moves
`constraints_ok` without moving official FPR is the *expected* shape of a self-scoring fix.

Three things to know before trusting one:

- **Each arm owns its method directory.** `run_sweeps_split` treats any non-empty plan under
  `results/<method>/` as an incumbent to beat *regardless of `resume`*, so two arms sharing a directory
  measure "arm 2 on top of arm 1", biased upward. `_method_for` appends a per-arm suffix and `--fresh`
  clears each; the committed **null** screen (both arms off) is the standing proof this holds — `fpr`,
  `continuous_score`, `constraints_ok` and every per-pass `improved`/`completed`/`failed` triple
  identical across arms
  ([`screens/20260806_whole_run_null_n40_tb1800`](../results/phase2_baselines/screens/20260806_whole_run_null_n40_tb1800/summary.json)).
  The tool labels that `NEUTRAL: no measurable delta`, which for a deliberately null arm is the pass
  condition — it has no notion of an intentionally identical pair.
- **`--chunk-size`/`--parallel` are ignored**; the sweep scheduler owns its own pool. Use `--workers`,
  and keep it at `cores − 1`.
- **The envelope must fit more than one pass** or the mode degenerates into a slow triage-only run.
  `n=40` at `--total-budget-sec 1800 --budget-sec 90 --workers 6` produced three passes in ~9 min per
  arm (`546–558 s`, with `~1160 s` of the envelope left unspent); that is the calibrated starting point.
  The **live** calibration screen at those settings (`TPC_WINDOW_PUSH` off vs on) read `fpr 47.5 →
  50.0`, `continuous_score 66.324 → 67.698`, `constraints_ok 20 → 21`, zero timeouts and zero parse
  failures, `GREEN LIGHT`
  ([`screens/20260806_whole_run_live_n40_tb1800_window_push`](../results/phase2_baselines/screens/20260806_whole_run_live_n40_tb1800_window_push/summary.json)),
  reproducing the direction of P8's per-query screen at a different magnitude — as expected, since the
  two contracts are not comparable.

**A change with no flag still needs the hand-rolled two-revision form**, because `--flag` pairs one
env var and cannot pair two trees. Run each arm on its own revision with a distinct `--method`,
**sequentially** (two 6-worker pools on one box contend for cores, and the timing difference alone
changes which passes fit):

```bash
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --harness tpc \
  --split tpc_phase2_familiar_100_val --limit 40 \
  --total-budget-sec 1800 --budget-sec 90 --workers 6 \
  --method screen_whole_run_<arm>
.venv/bin/python eval_tpc.py --splits tpc_phase2_familiar_100_val --method screen_whole_run_<arm>
```

Beyond the official numbers, diff the itineraries: a scheduler change that leaves 39 of 40 plans
byte-identical except for `elapsed_time(sec)` has one real effect, and finding which query moved is
worth more than the aggregate delta.

### Limits — read before trusting a screen

- **A screen never promotes.** It authorizes a real run; only a committed row through the
  [gate](#gates) promotes a default.
- **A per-query screen does not screen the scheduler** — see the section directly above. If the
  change touches `chinatravel/agent/phase2/sweeps.py`, `selfscore.py`, or `run_sweeps_split`, the
  default modes measure the wrong path entirely.
- **Absolute numbers are not ledger-comparable** (reduced budget/subset). Do not commit screen
  outputs into `results/phase2_baselines/`.
- **Timeout counts carry run-to-run noise** — a `±1–2` swing at a tight budget is nondeterminism.
  FPR and `continuous_score` are the correctness signals; `|Δ| ≤ --tol` (default `0.5`) reads as flat.
- **A screen can overstate a rare fallback.** `TPC_CASCADE_TIMED_WINDOWS`'s `--fast-fpr-packed`
  screen reported `+3.75` FPR where the full `900 s` gate found `+0.625` and flipped sign on
  `continuous_score`: stopping at first-accept-then-pack under-uses the restart budget that, at full
  budget, already resolves most of what the fallback would have caught.
- **Use `n ≥ 30`.** Smaller subsets are noise-dominated smoke checks.
- Familiar-100 inherits every [dataset-boundary caveat](#dataset-boundaries); a screen never
  estimates final performance.

### Cadence for per-query work: daily screen, nightly batched run

On each landing, screen (`familiar_100_val`); RED bounces back, GREEN keeps the flag **off on
`main`** but joins tonight's queue. Nightly, run **one batched** end-to-end with all queued flags
stacked on against the current promoted baseline — one run per night regardless of how many changes
landed, which is what makes the cadence keep up. In the morning promote the whole batch or, on a
regression, promote nothing and run drop-one-out *screens* to find the offender. Batching rather than
isolating is deliberate: two changes that each screen green can interact (`TPC_PIN_TIMED_WINDOWS` and
`TPC_REPAIR_TRANSPORT_GAPS` both retime the same plan), and the batch measures the net effect that
would actually ship. Run the test tripwire only occasionally, e.g. before a submission.

### Setup on a fresh box (no GPU needed)

The screen never loads a local model, so the GPU stack is unnecessary —
`requirements-submission.txt` is enough. The environment database
(`chinatravel/environment/database_en/`) and the imported familiar-100 split are both committed.

## Command path

Use Make targets rather than duplicating script arguments; `make phase2-help` has the full catalog.

```bash
make phase2-full-run P2_LABEL="reference 5h parallel"                 # whole-run row (decides the ship)
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=900 P2_REPEATS=2 P2_LABEL=<tag>   # per-query row
make phase2-rehearse FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_LIMIT=20     # quick smoke
make phase2-solve P2_SPLIT_SET=val P2_BUDGET=300 P2_LIMIT=1           # one query through the no-oracle path
make phase2-harness P2_SPLIT=tpc_phase2_familiar_100_val              # rehearse the organizers' exact command
make phase2-parser-report P2_LIMIT=20
make phase2-timing P2_METHOD=<method> P2_BUDGET=900
```

`P2_BUDGET` is a local per-query development setting; there is no organizer per-query timeout. For
building and verifying the submission archive, see the [competition
reference](reference/competition.md#packaging-this-into-a-submission).

## Measurement rule

Record the source name, split, deterministic selection, budget, flags and model/backend with every
measurement. Do not infer final-evaluation performance from local rows or from familiar-100. A
number promotes a change only through the gate, never by assertion.
