# Phase 2 evaluation roadmap — 5-hour envelope, parallel

**Written 2026-08-04, after the whole-run-envelope rewrite.** This is the run order for the
evaluation workstream. It replaces the per-query-budget run plan in
[`docs/agents/`](agents/README.md), which measured a contract the competition does not use.

For metric definitions, dataset boundaries and the gate mechanics, see
[Phase 2 evaluation](tpc_phase2_eval.md). For what to *implement* next, see the
[roadmap](tpc_phase2_roadmap.md).

## Status: full queue run 2026-08-04/05, this machine (4 cores)

Pre-flight, R1, R2, R4 (control + arms A/B/C + a confirmation repeat), R5, and R6 all completed;
R3 was skipped (needs ≥8 cores, this machine has 4). **Every row that solves and scores a split
(pre-flight through R5, 10 rows total) is under `results/phase2_baselines/full_runs/`,
`evaluator_parity: c89cfca`, same machine, and `git_dirty: false` except the pre-flight *plumbing
check* row (`git_dirty: true`, labelled and excluded from any comparison).** R6 is different in
kind — it verifies the *packaged submission archive*, not a split, so it writes no row under
`full_runs/`; its result is the `--dry-run`/`--verify-budget-sec` console output recorded inline
below. Full detail with each run's row path is inline below; the headline findings:

1. **R1 reference: `overall 57.99`, `FPR 33.0`, `empty_plans 0/100`.** The scheduler
   self-terminates at **`26%`** of the 5 h envelope (`1.31 h`) — the last two passes both clamp to
   exactly `300s`/query (the effective `max_query_sec` ceiling, see point 4 below), so once a query
   has been solved at the cap no later pass can offer it a meaningfully larger budget, the candidate
   list empties, and the sweep stops. **This is a capped-search stop, not a proven convergence** —
   see the correction to point 2.
2. **R2 envelope sensitivity: flat, but confounded by the `300s` cap.** `1 h / 3 h / 5 h` score
   `57.35 / 57.86 / 57.99`. The supported claim is narrower than "more budget never helps": **extra
   envelope buys nothing *given the `300s` per-query ceiling*, because the scheduler has no
   mechanism to spend it** — every later pass is filtered to candidates whose new budget would beat
   their last one by `MIN_BUDGET_GROWTH`, and a query stuck at the `300s` cap never clears that bar.
   Whether raising the cap lets extra envelope convert into score is **untested and is now this
   queue's top follow-up recommendation** (see point 4).
3. **R3 worker scaling: not run**, this box is below the roadmap's own 8-core floor for that
   comparison.
4. **R4 pass shape: two accidental no-ops surfaced a real ceiling bug, plus one behavioral finding.**
   - Arms A (`TPC_P2_TRIAGE_CAP_SEC=60`) and B (`TPC_P2_MAX_QUERY_SEC=300`) both landed as
     same-config reruns of the control — their target caps never bound at a 2 h envelope. Arm B's
     no-op surfaced a **doc correction that turned out to matter for R1/R2 too**: this roadmap's own
     table said `TPC_P2_MAX_QUERY_SEC` defaults to `900`, but `phase2_full_run.py` never reaches
     that default — the effective default on this path is `300` (confirmed against R1's own
     telemetry, which clamps to exactly `300s`). **Top recommendation: rerun with
     `TPC_P2_MAX_QUERY_SEC=600` or `900` at the 5 h envelope**, where R1 shows the cap demonstrably
     binds — this could turn `3.4 h` of currently-unspendable envelope into score, and ranks above
     the arm C gate below because it is untested rather than merely unconfirmed.
   - Arm C (`TPC_P2_FAST_TRIAGE=0`) scored `+0.59` over a 2 h control. The strongest evidence here is
     **categorical, not statistical**: polish improved `0/34` in arm C, versus `10/34`, `14/34`,
     `13/34`, `14/33` in the other four 2 h runs (control, control repeat, arm A, arm B) — with fast
     triage off, triage's own full-slice preference polishing already does the later polish pass's
     job. A same-config control repeat landed `Δ 0.01` from the first control, which is **weak
     evidence** (n=2, and the two runs' internal trajectories — `constraints_ok 36` vs `35`, repair
     improved `4` vs `5` — genuinely differ) **that same-config score variance is small relative to
     arm C's `+0.59`, not proof of a `~60×` noise-floor margin.** The behavioral signature is the
     part to trust. **Recommended next step: queue `TPC_P2_FAST_TRIAGE=0` for a pinned E2E gate**,
     which settles the magnitude regardless.
5. **R5 held-out tripwire: `overall 62.59`** on the 20-record test split, recorded standalone. No
   val↔test gap is computed — `familiar_100_test` is a subset of `familiar_100` (R1's split), and no
   comparable `familiar_100_val` row at a matching envelope exists in this queue.
6. **R6 packaged archive: verified end to end**, `valid_output=True`, from commit `b44bb73c096b`.
   Checks packaging only, not score; upload/report/tag remain manual follow-ups.

**What this queue does *not* answer:** whether raising `TPC_P2_MAX_QUERY_SEC` converts the unused
`3.4 h` into score (point 4's top recommendation, untested), whether arm C's gain survives a full
E2E gate at the real submission split/budget, and whether `100` queries always converge this fast on
the organizer's actual held-out set (only their harness run will tell).

---

## What changed, and why old rows cannot be reused

The organizers confirmed (2026-08-04) that there is **no per-query timeout**: the whole 100-query
run shares a single **5-hour wall clock**, and every query is weighted equally. The submission
path was rewritten to match — it now schedules the split in passes (triage → repair → polish)
across worker processes, keeps whatever is best so far on disk, and stops before the deadline
rather than being cut off.

Consequences for measurement:

| | Old contract (every committed row) | New contract |
| --- | --- | --- |
| Time | fixed per-query budget (`300 s` / `900 s`) | 5 h shared by the whole split |
| Order | one pass, split order | triage all, then repair failures, then polish |
| Cores | 1 | `CPU count - 1` workers |
| Per-query time | fixed | grows each pass, ends when the envelope does |
| Result file | written once | written before solving, then only improved |

**No row in `results/phase2_baselines/runs/` is comparable to a run under the new contract.** They
are a different budget contract, a different scheduler and a different parallelism. Whole-run rows
live in a separate directory, `results/phase2_baselines/full_runs/`, written by
`scripts/phase2_full_run.py`. Never gate one against the other.

The per-query rehearsal (`make phase2-rehearse`, `make phase2-baseline`) is **not** retired: it
still answers "is the solver better on this query at a fixed budget", which is the right question
for a solver change. It is no longer the signal that decides what we ship.

---

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

Expect: a `[sweep] pass 1 (triage) ...` line, one row under
`results/phase2_baselines/full_runs/`, and `empty_plans` well below the query count. If the run
ends far short of its envelope, read the last `[sweep]` line — it says why it stopped.

**Run 2026-08-04, this machine (`cpu_count: 4`).** `pytest tests/phase2` passed (804 passed, 1
skipped). Plumbing row `results/phase2_baselines/full_runs/20260804T200536Z.json`: one triage pass
(80 queries × 20 s, 3 workers), `empty_plans: 48/80`, `constraints_ok: 24/80`, `overall: 25.97`,
stopped at `383 s` of `720 s` (`53%`) — the last `[sweep]` line explains why: "no pass would do
anything new (every candidate would repeat a solve it already had)". That is a **legitimate stop**,
not a bug: a `720 s` envelope only fits one triage pass at this per-query cadence, so a second pass
would rerun the same solves with the same budget and the scheduler correctly declines. High
`empty_plans` at this compressed budget is expected (only `20 s`/query, no repair pass reached) and
is not informative about R1. Machinery confirmed working; proceeding to R1.

Two gitignore gaps found and fixed before any row could be trusted: `.claude/` (local tool state)
and `chinatravel/evaluation/default_splits/*_suboptimal.txt` (an `eval_tpc.py` scoring byproduct
regenerated every run) were both untracked and would have stamped every subsequent row
`git_dirty: true`. Each run in this queue now uses a distinct `--method` per the roadmap's default
(`phase2_e2e_<split>`) only where it doesn't collide with a same-split prior run in this queue — see
each run's row for its actual `method`.

---

## Run order

Each run records its own row. Run them in this order; **R1 is the prerequisite for every other
row on this list.**

### R1 — the reference whole-run row (do this first)

The number that describes what we would score today.

```bash
.venv/bin/python scripts/phase2_full_run.py --label "reference 5h parallel"
```

Defaults to `tpc_phase2_familiar_100`, 5 h, `CPU count - 1` workers. **Duration: ~5 h plus ~10 min
scoring.** This is the overnight run.

Read from the row: `overall`, `official_scores` (the full decomposition), `run_wall_frac_of_budget`
(how much of the envelope was actually used), `empty_plans` (must be `0`), and the per-pass table
(how many passes ran, and where the improvements came from).

**Run 2026-08-04, this machine (4 cores, 3 workers).**
`results/phase2_baselines/full_runs/20260804T201638Z.json`, `--method phase2_e2e_r1_ref`
(distinct method dir so R2/R4 don't overwrite this row's per-query outputs — every later run in
this queue does the same).

| | |
| --- | --- |
| `overall` | `57.99` |
| `official_scores` | MicEPR `99.48`, MacEPR `97.00`, C-LPR `87.83`, **FPR `33.00`**, DAV `18.15`, ATT `26.25`, DDR `19.39` |
| `empty_plans` | `0 / 100` |
| `constraints_ok` | `35 / 100` |
| `run_wall_frac_of_budget` | **`0.26`** (`4723 s` of `18000 s`) |
| passes | 1 triage (`100×120s`, improved 100, 37.3 min) → 2 repair (`66×300s`, improved 2, 37.3 min) → 3 polish (`34×300s`, improved 11, 4.1 min) → stopped: "no pass would do anything new" |

**The headline finding: R1 self-terminates at 26% of the envelope, not 100%** — `3.4 h` of the `5 h`
went unused. **Read the mechanism before assuming "converged":** repair and polish both clamp to
exactly `300s`/query (see the R4 arm B correction below: the effective `max_query_sec` default on
this path is `300`, not sweeps.py's internal `900`). The growth filter in `_choose_pass` drops a
candidate from a later pass unless its new budget would beat its last one by `MIN_BUDGET_GROWTH`; a
query already solved at the `300s` cap can never clear that bar again, so the candidate list empties
and the sweep reports "no pass would do anything new." **This is a capped-search stop, not
necessarily a quality plateau** — whether a higher cap would let the unused `3.4 h` convert into
score is untested (see the R4 top recommendation). FPR (`33.0`) sits well below `constraints_ok/100`
(`35`) only because FPR is stricter than the self-scored oracle-free `constraints_ok` proxy —
expected, not a discrepancy to chase.

**Three things this row settles that nothing else can:** whether the split fits the envelope at
all, how much of the 5 h the scheduler actually spends, and how many queries reach
`constraints_ok` — the state that carries `0.65` of the score.

### R2 — envelope sensitivity: is the 5th hour worth anything?

```bash
.venv/bin/python scripts/phase2_full_run.py --total-budget-sec 3600  --label "1h envelope"
.venv/bin/python scripts/phase2_full_run.py --total-budget-sec 10800 --label "3h envelope"
```

Two runs, 4 h total. If `overall` is flat from 1 h to 5 h, extra time is not the constraint and
every "give it more budget" idea on the implementation roadmap is dead — which is a valuable
negative result. If it climbs to the end, the scheduler is time-starved and the pass shape (R4) is
where the leverage is.

**1h arm, run 2026-08-04:** `results/phase2_baselines/full_runs/20260804T213636Z.json`,
`--method phase2_e2e_r2_1h`. `overall 57.35` (vs R1 `57.99`, **`Δ -0.64`**), `FPR 31.0` (vs `33.0`),
`constraints_ok 35/100` — same as R1. `run_wall_frac_of_budget 0.56` (`2015 s` of `3600 s`), all
three passes completed (triage → repair → polish) before self-terminating for the same reason as
R1. The predicted "1 h might cut off polish" did not happen — 1 h was still enough headroom. Nearly
flat vs R1, within likely run-to-run noise for a single-seed comparison.

**3h arm, run 2026-08-04:** `results/phase2_baselines/full_runs/20260804T221103Z.json`,
`--method phase2_e2e_r2_3h`. `overall 57.86` (vs R1 `57.99`, **`Δ -0.13`**), `FPR` unrecorded here
but `constraints_ok 36/100` (vs R1's `35`, +1). `run_wall_frac_of_budget 0.37` (`4015 s` of
`10800 s`), same three-pass shape, same self-termination reason.

**R2 verdict: flat, but confounded by the `300s` per-query cap — corrected 2026-08-05 after
tracing R4 arm B.** `overall` across 1 h / 3 h / 5 h is `57.35 / 57.86 / 57.99`, `constraints_ok`
moving by only `±1` query. The supported claim is narrower than "extra envelope buys nothing":
**extra envelope buys nothing *given the effective `300s` `max_query_sec` ceiling*, because a query
already solved at that cap is filtered out of every later pass by the growth check** (`_choose_pass`
requires a new budget to beat the last one by `MIN_BUDGET_GROWTH`, which a capped query can never
do) — so R1 itself never gets the chance to spend hours 2 through 5 on a query stuck at the ceiling.
Whether raising `TPC_P2_MAX_QUERY_SEC` past `300` lets that unused time convert into score is
**untested and is this queue's top follow-up recommendation** — it is a materially different
question from "does the scheduler already extract everything available," which this queue has not
answered either way.

### R3 — worker scaling: does parallelism convert into score?

```bash
TPC_P2_WORKERS=1 .venv/bin/python scripts/phase2_full_run.py --workers 1 --label "1 worker, 5h"
```

Compare against R1 at the same envelope. This is the direct test of the claim behind the rewrite:
with `W` workers a pass costs `ceil(n/W)` query-budgets of wall clock instead of `n`, so each query
can afford a much larger budget. A 1-worker run at 5 h gives every query ~162 s once; R1 gives them
a small triage budget and then several hundred seconds each in repair. If R1 does not beat this
clearly, the pass structure — not the parallelism — is what needs work.

Skip on a machine with fewer than 8 cores: the comparison says more about the box than the code.

**Skipped 2026-08-04, this machine.** `nproc` reports `4` cores — below the roadmap's own `8`-core
floor for this comparison, so a 1-worker-vs-3-worker (default `CPU-1`) run here would say more about
this box than about the scheduler. Not run; needs a ≥8-core machine.

### R4 — pass shape: where should the envelope go?

Every knob is an environment variable, so these need no code change:

| Variable | Default | What it changes |
| --- | --- | --- |
| `TPC_P2_TRIAGE_CAP_SEC` | `120` | ceiling on the first, everything-once pass |
| `TPC_P2_TRIAGE_FRACTION` | `0.25` | share of the envelope triage may spend |
| `TPC_P2_PASS_FRACTION` | `0.5` | share of what remains each later pass may spend |
| `TPC_P2_MAX_QUERY_SEC` | `900`¹ | ceiling on any single query's solve |
| `TPC_P2_MIN_QUERY_SEC` | `20` | floor below which a query is not worth starting |
| `TPC_P2_MAX_PASSES` | `24` | hard stop on pass count |
| `TPC_P2_FAST_TRIAGE` | `1` | triage stops each query at its first accepted plan instead of polishing preference |
| `TPC_P2_WORKERS` | `CPU - 1` | worker processes |

¹ **Doc correction (2026-08-04), found while running arm B:** `900` is `sweeps.py`'s
`DEFAULT_MAX_QUERY_SEC`, but `phase2_full_run.py` never reaches it. `solve_phase2.py`'s
`run_split` resolves `budget_sec = budget_sec if budget_sec is not None else DEFAULT_BUDGET_SEC`
(`300`, from `orch.DEFAULT_BUDGET_SEC`) *before* calling `run_sweeps_split`, which constructs
`SweepConfig(max_query_sec=budget_sec)` from that already-resolved value — and `phase2_full_run.py`
never passes `--budget-sec`. **The effective default for every row in this queue (R1, R2, R4
control) is `max_query_sec: 300`, not `900`** — confirmed against R1's own telemetry, where
repair/polish clamped to exactly `300s` per query. Arm B's `TPC_P2_MAX_QUERY_SEC=300` therefore
restates the existing default rather than raising it.

Two arms worth running once R1 exists, at a **reduced 2 h envelope** so each is ~2 h:

```bash
# A: cheap triage, more repair passes
TPC_P2_TRIAGE_CAP_SEC=60 .venv/bin/python scripts/phase2_full_run.py \
  --total-budget-sec 7200 --label "triage cap 60"
# B: fewer, longer solves
TPC_P2_MAX_QUERY_SEC=300 .venv/bin/python scripts/phase2_full_run.py \
  --total-budget-sec 7200 --label "per-query cap 300"
```

**Arm A, run 2026-08-04:** `results/phase2_baselines/full_runs/20260805T001808Z.json`,
`--method phase2_e2e_r4_arm_a`. `overall 57.34` (vs 2h control `57.81`, `Δ -0.47`),
`constraints_ok 35/100` (vs `36`). **The cap never bound**: triage still ran at `50s`/query,
identical to the control's triage budget — `TPC_P2_TRIAGE_FRACTION`'s default (`0.25`) already
computes a smaller-than-`60s` triage slice at this envelope/worker count/query count, so
`TPC_P2_TRIAGE_CAP_SEC=60` was never the binding constraint and this run is a same-config rerun of
the control, not a real test of the hypothesis. The `-0.47` delta is noise, not a finding.
**To actually test "cheap triage, more repair," `TPC_P2_TRIAGE_CAP_SEC` needs to be set below the
default fraction-derived triage slice** (well under `50s` at this envelope), or `TPC_P2_TRIAGE_FRACTION`
lowered directly — worth a follow-up run, noted rather than re-run now to keep the queue moving.

**Arm B, run 2026-08-04:** `results/phase2_baselines/full_runs/20260805T011733Z.json`,
`--method phase2_e2e_r4_arm_b`. `overall 58.20` (vs 2h control `57.81`, `Δ +0.39`),
`constraints_ok 36/100` — same as control. **Also a same-config rerun, for a different reason than
arm A:** per the ¹ correction above, `300` is already the effective default `max_query_sec` on this
path, so `TPC_P2_MAX_QUERY_SEC=300` changed nothing. The `+0.39` delta is noise. Separately, at this
2 h envelope the repair/polish passes' fraction-derived share (`131s`/`151s`, from the control row)
never even reached `300` — so a `300` cap would not have bound here regardless of the default-value
confusion. **R1's own telemetry shows the cap does bind at 5 h** (repair and polish both clamped to
exactly `300s`), so a real test of raising this ceiling needs the larger envelope, not `2 h`, and a
value above `300` (e.g. `TPC_P2_MAX_QUERY_SEC=600`) — noted as a follow-up rather than re-run now.

**Arms A and B both landed as accidental no-ops, for related reasons: the 2 h envelope used for
this section's "reduced" arms doesn't generate a large enough per-round share for either cap to
bind.** Arm C is the only one of the three that changes pass *behavior* rather than a ceiling that
may or may not be reached, so it is the one likeliest to show a real effect — matching the roadmap's
own text calling it "the one with the clearest hypothesis."

A third arm worth the same 2 h, and the one with the clearest hypothesis:

```bash
# C: triage spends its whole slot polishing instead of stopping at the first accept
TPC_P2_FAST_TRIAGE=0 .venv/bin/python scripts/phase2_full_run.py \
  --total-budget-sec 7200 --label "no fast triage"
```

Fast triage is on by default on the argument that an accepted plan for another query is worth more
than a better preference key for this one (constraints carry `0.65` of a query's score; preference
terms are zeroed until it passes) and that an early accept hands its remaining slot back to the
pass. That is reasoning, not a measurement. If arm C wins, the reasoning is wrong somewhere —
most likely because the polish pass rarely runs, so first-accept preference is what actually ships.

**Arm C, run 2026-08-04:** `results/phase2_baselines/full_runs/20260805T021805Z.json`,
`--method phase2_e2e_r4_arm_c`. `overall 58.40` (vs 2h control `57.81`, **`Δ +0.59`, the largest of
the three arms**), `constraints_ok 36/100` — same as control. Unlike arms A/B, this run's config
change actually took effect — and it comes with a clean behavioral signature, not just a score
wobble: **polish improved `0/34`** (vs control's `10/34`, arm A's `14/34`, arm B's `13/34`). With
`TPC_P2_FAST_TRIAGE=0`, triage itself already spends its full slice polishing preference, so by the
time the later polish pass runs there is nothing left for it to find — it becomes dead weight. This
is exactly the mechanism the roadmap predicted for a arm-C win ("the polish pass rarely runs, so
first-accept preference is what actually ships") except inverted: here polish *does* run (on all 34
candidates) but finds nothing, because triage already did polish's job.

**The behavioral signature is the part to trust; the score delta is weaker evidence than I first
claimed.** A same-config repeat of the 2 h control (below) lands at `Δ 0.01` from the first control
run — but that is `n=2`, not a variance estimate, and the two control runs' own trajectories differ
(`constraints_ok 36` vs `35`, repair improved `4` vs `5`, polish improved `10` vs `14`): the process
is visibly stochastic and these are two nearby samples, not proof the spread is `0.01`. So arm C's
`+0.59` is **weak evidence of a real effect relative to that one repeat, not a confirmed `~60×`
noise-floor margin.** What *does* hold up without needing a variance estimate: polish improved
`0/34` in arm C against `10/34`, `14/34`, `13/34`, and `14/33` in the four other 2 h runs (control,
control repeat, arm A, arm B) — a categorical difference, not a score wobble, with a clean causal
story (triage's full-slice polishing subsumes the later polish pass, which becomes dead weight).
This is screen-level evidence, not a promotion — per CLAUDE.md a default only flips through a full
E2E gate — but it is strong enough on the behavioral axis to prioritize for one. **Recommended next
step:** queue `TPC_P2_FAST_TRIAGE=0` for a pinned E2E gate run (`make phase2-baseline` /
`phase2_gate.py`), which settles the score magnitude regardless.

All three must be compared against a **2 h control** (`--total-budget-sec 7200`, no overrides), not
against R1.

**2h control, run 2026-08-04:** `results/phase2_baselines/full_runs/20260804T231910Z.json`,
`--method phase2_e2e_r4_control`. `overall 57.81`, `constraints_ok 36/100`,
`run_wall_frac_of_budget 0.49` (`3490 s` of `7200 s`), same three-pass shape and self-termination
as R1/R2 — consistent with the pattern seen at every envelope tried so far (see the R2 correction
above: the stop is cap-driven, not necessarily a quality plateau). Arms A/B/C below compare against
this row, not R1.

**Control repeat, run 2026-08-05:** `results/phase2_baselines/full_runs/20260805T032037Z.json`,
`--method phase2_e2e_r4_control_rep2`, identical config/envelope, rerun to get a second sample on
arm C's delta before trusting it. `overall 57.82` — `Δ 0.01` vs the first control run. **This is
one paired difference, not a variance estimate (`n=2`)** — and the two runs' own trajectories
differ (`constraints_ok 36` vs `35`, repair improved `4` vs `5`, polish improved `10` vs `14`),
which argues the process is stochastic and these are two nearby samples rather than proof the
spread is tightly `0.01`. Treat this as **weak evidence that same-config variance is smaller than
arm C's `+0.59`**, not confirmation of a precise noise floor — see arm C's write-up for the stronger
(categorical) evidence that carries the actual recommendation.

### R5 — the held-out tripwire (once, and only after R1 is settled)

```bash
.venv/bin/python scripts/phase2_full_run.py \
  --split tpc_phase2_familiar_100_test --total-budget-sec 3600 --label "test tripwire"
```

20 records, so **coarse and high-variance**: a gap versus val is a prompt to investigate, never a
per-change signal. Run it at most once per submission. Note the envelope must scale with the split
— 20 queries in 5 h is not the same pressure as 100 in 5 h, so use 1 h.

**Run 2026-08-05:** `results/phase2_baselines/full_runs/20260805T042106Z.json`,
`--method phase2_e2e_r5_test`. `overall 62.59`, `empty_plans 0/20`, `constraints_ok 10/20` (`50%`),
`run_wall_frac_of_budget 0.25` (`882 s` of `3600 s`), same three-pass self-terminating shape.

**Recorded standalone — no val↔test gap is computed against R1.** `tpc_phase2_familiar_100_test`'s
20 records are a *subset* of `tpc_phase2_familiar_100`, the split R1 ran on; comparing R5 to R1
would be comparing 20 records against a superset that contains them, not against an independent val
partition. This queue produced no `tpc_phase2_familiar_100_val` row at a comparable (non-plumbing)
envelope, so a genuine val↔test gap check needs a follow-up val run at `1 h`/`3 workers` before it
can be trusted. At face value `62.59` (test) sits well above R1's `57.99` (full 100, includes these
20) and R4 control's `57.81`/`57.82` — consistent with a smaller, possibly easier split rather than
a generalization signal; do not read a "test beats val" story into this without the missing val row.

### R6 — the packaged archive, end to end

The submission is a zip, not a working tree. Once R1 looks right:

```bash
.venv/bin/python scripts/assemble_phase2_submission.py --dry-run
.venv/bin/python scripts/assemble_phase2_submission.py --verify-budget-sec 120
```

The builder unpacks the archive into a temporary directory and runs the organizers' exact command
inside it with a stripped `PATH`. That checks the package, not the score.

**Run 2026-08-04/05, this machine.** `--dry-run`: `fabiundstefan_v1`, `1674` files, `16.3 MB`
unpacked. `--verify-budget-sec 120`: wrote `submissions/fabiundstefan_v1.zip` (`1676` entries,
`4.0 MB` compressed) from commit `b44bb73c096b`, unpacked it to a scratch dir, and ran the
organizers' exact entry point inside it with a stripped `PATH`: `valid_output=True` on a 1-query,
`120 s` smoke slice. **Package verified end to end; this checks packaging only, not the score.**
Per CLAUDE.md's resubmission note, every pre-2026-08-04 upload is disregarded — this verified
archive is a candidate for the `{TeamName}_v1.zip` re-upload, not yet uploaded (upload, report PDF,
and `git tag phase2-v1` remain manual follow-ups outside this eval queue).

---

## What to record, and what makes two rows comparable

`scripts/phase2_full_run.py` writes the row for you. Two rows may be compared only when **all** of
these match: `split`, `total_budget_sec`, `workers`, `evaluator_parity`, and any `TPC_P2_*`
override in play (note them in `--label`). `git_dirty: true` means the row is not reproducible
from a commit — rerun it from a clean tree before using it to decide anything.

Run comparisons on the same machine. Worker count, core count and memory pressure all move the
result, and a row from a 4-core laptop says nothing about a 16-core evaluation host.

---

## What not to spend an overnight slot on

- **The old per-query `900 s` pinned gate as a ship signal.** It measures a contract the
  competition does not use. Keep it for solver-change A/Bs only.
- **Preference-packing flags (`TPC_PACK_*`) before R1.** Since the evaluator sync, every
  preference term is zeroed for a query that fails its constraints, so preference work is bounded
  by FPR. R1 tells you what FPR is under the real contract; without it you cannot size the gain.
- **Anything LLM-backed.** The shipped path makes zero LLM calls, the one screened parse arm came
  back RED, and no endpoint is reachable from the evaluation machine.
