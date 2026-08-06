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
24:00 Beijing Time = 18:00 CEST). Every evaluation slot from here exists to answer one question:
**is there a configuration worth spending the second slot on?** [R14](#r14--the-p8p9-gate-the-one-run-that-decides-whether-v2-exists-closed-2026-08-06-green)
was that measurement, and it came back **GREEN** on 2026-08-06 (`overall 64.13`, `+0.5471` over the
R8/R12 baseline; `FPR 44.0`, `+1.0`; `constraints_ok` unchanged at `46/100` — see the row's own
section for the two caveats that temper it). [R15](#r15--held-out-tripwire-for-p8p9) is next.

R1–R14 are closed (see [what the closed queue established](#what-the-closed-queue-r1r14-established)).
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
its label says. Since 2026-08-06 the same snapshot also carries the **screened-but-unpromoted**
window repairs (`window_push`, `window_insert`, `window_push_max_min`, from
`orchestrator.CANDIDATE_SOLVER_FLAGS`), so an R14 arm states which repairs actually ran instead of
relying on its `--label`.

| Run | What it answers | Blocked on | Cost |
| --- | --- | --- | --- |
| ~~R14~~ | ~~do P8+P9 hold up on a whole run? → does `v2` exist?~~ | closed 2026-08-06, GREEN | done |
| **[R15](#r15--held-out-tripwire-for-p8p9)** | did the P8/P9 gain generalize past the `val` residual it was designed from? | nothing — R14 came back GREEN | `~0.3 h` (1 h envelope, 20 records) |
| R9 | does re-attacking failures with fresh seeds accumulate flips? | [P5](tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds) + [P2](tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger) | ~5 h |
| R11 | LLM-backed repair | [P6](tpc_phase2_roadmap.md#p6--llm-backed-repair-proposer-v2-candidate-default-off), which is not implemented and cannot be verified against the organizers' endpoint from here | out of reach before 2026-08-10 |

**R9 and R11 remain blocked on unimplemented work items** that belong to the Implementation
workstream, not Evaluation — see the [parallel workstreams](../CLAUDE.md#parallel-workstreams)
split. R11's old "not before the `v1` upload" gate has now been *superseded rather than satisfied*:
`v1` is uploaded, but with `P6` unwritten and the endpoint unreachable locally, there is no arm to
run before the deadline.

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
# 1. baseline: only needed if your host has no promoted-default row yet (see the host table above).
.venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r14_base --label "R14 baseline, promoted defaults, 5h"

# 2. candidate: promoted defaults plus the two window repairs.
TPC_WINDOW_PUSH=1 TPC_WINDOW_INSERT=1 .venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r14_pushinsert --label "R14 P8+P9 stacked, 5h"
```

Export nothing else. `apply_deterministic_solver_defaults()` supplies the four promoted flags and
respects the two you set, so the candidate arm differs from the baseline in exactly those two.

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
FPR): `overall ≈ 64.5–65.5`, `FPR 45–46`, `constraints_ok ≈ 48–49/100` against the 4-core baseline,
or the same deltas on top of R3's `64.08` on the Mac. R8's screen slightly *under*-predicted its full
run (`+10.0` predicted, `+11.0` measured), so treat the screen as a floor rather than a ceiling — but
also note the screen ran at `90 s`/query while the whole run spends `120/300 s`, so the two passes
have more competing search to displace here than they did there.

**Decision rule, fixed in advance so the result cannot be read after the fact:**

| Outcome | Read | Action |
| --- | --- | --- |
| `overall` up **and** `FPR` not down **and** `empty_plans 0/100` **and** no failed jobs | GREEN | Promote both flags: move them from `CANDIDATE_SOLVER_FLAGS` into `PROMOTED_SOLVER_FLAGS` and set them in `apply_deterministic_solver_defaults()` with this row cited (Implementation task), then run [R15](#r15--held-out-tripwire-for-p8p9), then rebuild and upload `v2`. |
| `abs(Δ overall) ≤ 0.5` with `FPR` unchanged | FLAT | Do not promote. `v1`'s configuration stays the submission. Record the row and stop — do **not** spend a second 5 h run hoping for a different number; the solver is deterministic. |
| `FPR` down, `empty_plans > 0`, or any failed job | RED | Do not promote. Commit the row, then hand it to Implementation with the failing uids; run **drop-one-out screens** (`--flag TPC_WINDOW_PUSH` alone, then `--flag TPC_WINDOW_INSERT` alone) rather than more full runs. |

`empty_plans > 0` or a nonzero per-pass `failed` count means suspect the **worker pool** before the
solver — see the [cold-start note](#before-the-first-run) above.

Commit the row under `results/phase2_baselines/full_runs/` and add its line to
[the closed-queue table](#what-the-closed-queue-r1r14-established) with the host, worker count and
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
   finding #4](#what-the-closed-queue-r1r14-established) already draws between `improved` and
   `constraints_ok`. The gain is real (GREEN stands) but thinner than the headline `overall` delta
   reads on its own.

Per the GREEN action: promoting the flags into `PROMOTED_SOLVER_FLAGS` /
`apply_deterministic_solver_defaults()` is an Implementation-workstream change (CLAUDE.md's
[parallel workstreams](../CLAUDE.md#parallel-workstreams) bar Evaluation from solver code) and is not
done in this row's branch. [R15](#r15--held-out-tripwire-for-p8p9) does not depend on that promotion
— its command sets both flags via environment variable — so it can and does run next.

### R15 — held-out tripwire for P8/P9

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

**Archive check**: see the R12 row in [what the closed queue established](#what-the-closed-queue-r1r14-established)
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

- **A repeat of a run you already have.** Post-P0 the solver is bit-for-bit reproducible ([R7](#what-the-closed-queue-r1r14-established)),
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

## What the closed queue (R1–R14) established

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

### Limits — read before trusting a screen

- **A screen never promotes.** It authorizes a real run; only a committed row through the
  [gate](#gates) promotes a default.
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
