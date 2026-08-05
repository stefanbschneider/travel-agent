# Phase 2 implementation roadmap

**The active Phase 2 work plan: where the points are, what to build next, and what is already
settled.** Merged 2026-08-05 from the former `tpc_phase2_roadmap.md` (landed record) and
`tpc_phase2_improvement_plan.md` (diagnosis and work items), absorbing the open Phase 2 items of
`tpc_shortcomings_and_plan.md`; all three are preserved verbatim in the
[archive](archive/README.md). Phase 1's record lives in the [Phase 1
playbook](tpc_phase1_playbook.md).

How the system is built: [design doc](tpc_phase2_design.md). What to *measure* after implementing:
[evaluation roadmap](tpc_phase2_eval.md). What the competition requires: [competition
reference](reference/competition.md). Read [CLAUDE.md](../CLAUDE.md) first for the non-negotiable
invariants; nothing here overrides them.

**The one-paragraph version.** The submission scores `overall 57.99` on `familiar_100` and uses only
`26%` of its 5-hour envelope, which looks like wasted headroom. It is not. Giving failing queries
`2.5×` the time buys `4.2×` the search and flips **one query in sixty-eight**, because every knob we
have — more budget, more restarts, more workers, fresh seeds — is the same intervention: draw more
samples from a parameter space that does not contain the answer. `45 of 61` failing queries fail on a
*single* constraint family the sampler cannot express. **Spend the effort on what the solver can
represent, not on how long it runs.**

## Where we are

Reference row `results/phase2_baselines/full_runs/20260804T201638Z.json` (`familiar_100`, 5 h
envelope, 3 workers, `evaluator_parity: c89cfca`, zero LLM calls), finishing in `1.31 h`:

| | value | weight | contributes |
| --- | --- | --- | --- |
| **FPR** | **33.0** | 0.40 | **13.2** |
| C-LPR | 87.83 | 0.25 | 21.96 |
| MicEPR | 99.48 | 0.10 | 9.95 |
| MacEPR | 97.00 | 0.10 | 9.70 |
| DAV / ATT / DDR | 18.15 / 26.25 / 19.39 | 0.05 ea. | 3.19 |

`empty_plans 0/100`, `constraints_ok 35/100`. The submission path itself is settled: the organizers'
bare command runs this repository's deterministic solver in-process, schedules the split against the
5 h envelope across `CPU-1` workers, pre-writes a fallback for every query, and makes zero LLM calls
(see [design](tpc_phase2_design.md) and [landed](#landed-and-promoted)).

## The diagnosis

### 1. The score is gated by one number

FPR is the fraction of queries passing *every* constraint, and the three preference terms are zeroed
on any query that fails — so they are bounded above by FPR too. **One FPR point is worth about
`0.85` overall; perfecting all three preference terms at today's FPR is worth `~1.5` in total.**
Preference work is not where the points are.

### 2. The solver is bimodal: it either wins in seconds or burns the whole slice and fails

Per-query search telemetry from a 1 h diagnostic run (`phase2_diag_1h`, triage pass, `25 s`/query,
`n=42`):

| | accepted (`n=15`) | failed (`n=27`) |
| --- | --- | --- |
| `stop_reason` | `accepted_stop` ×15 | **`budget` ×26**, `accepted_stop` ×1 |
| restarts used | median **0** | median **39** |
| solve seconds | median **3.2** | median **22.7** of a `~23 s` slice |
| best found at restart | median 0 | median 14 |

A query that is going to be solved is solved by the **first constructed plan**, in about three
seconds. A query that is not spends 100% of its slice on ~39 randomized restarts and finds nothing
acceptable. **There is no middle population that "just needed a bit more time."**

### 3. More search does not help — measured, not assumed

The same run's **repair** pass gave the failing queries `62 s` each, `2.5×` the triage slice:

| | triage failures (`25 s`) | repair (`62 s`) |
| --- | --- | --- |
| restarts used, median | 39 | **166** |
| `stop_reason` | `budget` ×26 of 27 | `budget` ×41, `converged` ×3 — never the restart cap |
| best found at restart, median | 14 | 47 |
| **queries newly satisfying their constraints** | — | **1 of 68** |

The last row is the scheduler's own accounting over the complete pass, not a sample. The 5 h
reference run says the same at a larger budget: repair improved `2 of 66`, polish `11 of 34`. In
every case the best candidate arrives about a third of the way through the restarts and **the whole
back half of the search changes nothing** — which is also why `1 h / 3 h / 5 h` score
`57.35 / 57.86 / 57.99`.

**Why more restarts cannot help.** A restart resamples one parameter tuple
(`tpc_agent.py:_random_params`): attraction offset, hotel index, attractions per day, visit minutes,
a forced transport mode, optional intercity preferences, a meal offset. That is the whole search
space — a few thousand combinations, sampled independently. Extra budget, a raised
`TPC_MAX_RESTARTS`, more workers, within-query parallel restarts, *and* a fresh seed salt are all the
same intervention: **draw more tuples from that space.** The measurement says the space does not
contain a fix for these queries.

**So the idle `3.4 h` is a symptom, not the problem.** The scheduler stops because the search
genuinely has nothing productive left to try (`_choose_pass` drops a query whose new budget cannot
beat its last by `MIN_BUDGET_GROWTH`, and every candidate is already at the `300 s` cap). Any plan
whose headline is "spend the leftover time" is treating the symptom.

**A sampling note that is itself a finding.** The triage column above was taken *during* the triage
pass. It has to be: `on_result` overwrites `telemetry.json` per query, so after repair runs the
surviving triage records are only those of queries that never entered repair — i.e. the ones that
passed. Reading triage stats after a completed run silently measures the winners. That is what
[P2](#p2--per-attempt-telemetry-ledger) fixes.

### 4. One constraint family accounts for almost all of the loss

Solver-only failure attribution (`scripts/phase2_solver_failure_attribution.py`, oracle constraints
fed to a bounded solve so parsing is removed):

```
family                     queries  instances  sole_blocker
timed_visit_named_poi           58         87           45
required_restaurants             5          5            0
required_attractions             4          4            1
required_cuisine_types           2          2            0
```

**`timed_visit_named_poi` is the only failing logical family in 45 of 61 failing queries** —
constraints of the shape "be at *this named POI* within *this time window*". Put that together with
§3: the random-parameter sampler has no parameter that *places a specific activity inside a specific
time window*. It can shift the day's start offset and attractions per day; it cannot pin one
activity to a window and reflow the rest. So no number of draws finds these plans — exactly what the
flat budget curve, the ~zero-flip repair pass, and the plateaued `best_found_at_restart` all
independently report.

### 5. Parsing is not the bottleneck either

Solver-only FPR (`23.75`) sits *below* end-to-end FPR (`25.00`) on the last rehearsal — feeding the
solver perfect constraints does not improve it. On the reference run `constraints_ok` (`35`, the
solver's own oracle-free verdict) is within 2 of the official `FPR` (`33`), so the solver is not
fooling itself about which queries it solved. Parser F1 against oracle is `0.9588`–`0.9949`
depending on the measurement, with zero missing families. **Parsing works; search is the gap.**

## Work items

| | Item | Effort | Expected | Ships in |
| --- | --- | --- | --- | --- |
| **P1** | **`timed_visit_named_poi`: a window-aware move** | days | **`+2..+5`; the only item that moves FPR** | not v1 |
| P2 | Per-attempt telemetry ledger | 2 h | report figures; measures everything else | v2 |
| P3 | Re-screen commonsense-valid emission when nothing is accepted | 2 h | `≤ +0.5` | v2 |
| P5 | Spend the idle envelope on fresh seeds | half day | **`~0` or `+1.7..+4.2` — genuinely open** | v2 |
| P4 | Derive `max_query_sec` from the envelope | 1 h | ~0 by the same evidence | v2 |
| P6 | LLM-backed repair proposer | 1–2 days | unknown; the one untried *kind* of move | v2 only |
| ~~P0~~ | ~~Explicit, reproducible restart seed~~ | — | **landed 2026-08-05** | v1 |
| ~~P7~~ | ~~Worker count from CPU affinity~~ | — | **landed 2026-08-05** | v1 |

`P0`…`P7` are stable identifiers, so a later note can refer to "P5" without depending on the
ranking. Sections below are in priority order. Everything still open is safe to implement in
parallel with the eval queue — none of it touches the shipping default.

**If you only do one thing, do P1.** Everything else is worth under a point, and three items are
worth approximately zero by measurement rather than by guess.

### P1 — the `timed_visit_named_poi` residual: give the search a window-aware move

**This is the item.** Diagnosis §4: the *sole* logical blocker in `45 of 61` failing solver-only
queries; nothing else on the failure table breaks double digits.

**The shape.** An oracle clause of the form

```python
result = True
for activity in allactivities(plan):
    if activity_position(activity) == "<named POI>":
        result = activity_start_time(activity) >= "HH:MM" and activity_end_time(activity) <= "HH:MM"
```

i.e. *this specific activity must sit inside this specific window*.

**Read the prior art before writing anything.** Three mechanisms have already been aimed here, all
inside `_pack_plan` and all deepcopy-trialed and committed only if the full checker still accepts:

| Mechanism | What it does | Outcome |
| --- | --- | --- |
| `_apply_search_constraints` → `required_hotels` projection | routes a window/position name into the hotel pool, so "meal at *Nanyang Inn*" can pin hotel selection | promoted with pinning |
| `_try_pin_activity` | shifts a present-but-mistimed activity into its window, recomputing its own and the next activity's legs; **reverts on any cascade** | promoted, real gain |
| `_resequence_day` | reorders the day's meal/attraction activities by target window; **returns early when the window-sorted order equals the current order** | promoted with it |
| `_enforce_windows_in_order` (`TPC_CASCADE_TIMED_WINDOWS`) | forward-only ripple: re-lays the day's movable block in current order with windows honored | gated at `900 s`, **no measurable effect**, not promoted |

The residual is therefore not one shape; it is the tail after the two tractable shapes were taken.
**The known-unhandled shape is the backward shift** — a target that must move *earlier*, pulling its
predecessors back. Every landed move ignores it.

**Step 0, before any code: re-derive the residual on post-sync data**, then **classify it by shape**
(forward-shift, backward-shift, needs-reordering, infeasible-as-parsed) and count each:

```bash
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode solver-only
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode end-to-end
```

Choose a move only if one shape is a large share. **If the shapes do not converge, write that down
and stop** — a documented dead end is a real deliverable here and worth more than a fourth mechanism
that gates flat.

**The structurally different option.** The CP-SAT tier (`chinatravel/agent/tpc_agent/cp_solver.py`)
already exists and already reasons about time, and a timed window is a *native* CP-SAT constraint
unlike a random parameter tuple. Routing queries whose parsed constraints contain a timed-visit
clause into a CP-SAT formulation with the window as a hard interval attacks the family at the
representation level. Scope it before committing, but note it is the only proposal here (besides P6)
that changes *what can be expressed*, which is the actual binding limit.

**Do not reintroduce: emitting `arrive_no_later` from `end_before`** to time morning meals. It was
tried; its ceiling prunes proper transport, producing transport-less plans that fail *Invalid
Transport information across positions* — and since the evaluator sync a transport-less plan also
scores ATT `0`, so it is worse than when it was rejected.

**Ship bar.** Flag, default off, byte-identical floor, unit tests, and
[R8](tpc_phase2_eval.md#r8--the-gate-for-a-window-aware-move-needs-p1) against the R7 variance
baseline. At `sd ≈ 0.35` a `+2` effect is detectable in a single paired run; anything smaller needs
repeats.

### P2 — per-attempt telemetry ledger

**Why.** Two reasons, one a hard requirement. (a) The technical report needs distributions and
timings — min/mean/max with spread, per-pass wall clock, restart histograms — which today's
telemetry cannot supply. (b) Every other item is measured through it.

**The bug this fixes.** `agent_env/scripts/solve_phase2.py:on_result` writes
`work_root/<uid>/telemetry.json` on **every** attempt, so each pass overwrites the previous pass's
record and attempt history is destroyed as the run proceeds (diagnosis §3's sampling note).

**Change.** Keep `telemetry.json` as the latest (other tooling reads it) and additionally append one
JSON line per attempt to `work_root/<uid>/attempts.jsonl` with at least `pass_index`, `pass_kind`,
`seed_salt`, `budget_sec`, `wall_sec`, `restarts_used`, `stop_reason`, `candidates_evaluated`,
`best_found_at_restart`, `self_score`, `kept`. Then aggregate into the committed row in
`scripts/phase2_full_run.py`: attempts per query (min/mean/max), wall per attempt, `stop_reason`
histogram, restart-count distribution, first-accept-attempt distribution. **Report figures must be
plottable from the committed row alone** — rows are what survive.

**Tests.** Two attempts on one uid append two lines and do not clobber; row aggregation matches a
hand-computed fixture.

### P3 — emit commonsense-valid plans when nothing is accepted

**Why.** C-LPR is the conditional logical micro, so a plan failing commonsense scores `0` on C-LPR
*and* `0` on MacEPR for that query. The reference row's MacEPR `97` means **3 queries** in that state.

**The mechanism exists — re-screen it, do not re-implement it.** `TPC_COMMONSENSE_FIRST`
(harness-default-on) already maintains `best_cs`, the best schema- and commonsense-valid candidate,
and prefers it when nothing is fully accepted; its evidence predates the evaluator sync.

**What this item is not.** The pre-written fallback (`chinatravel/agent/phase2/fallback.py`,
`minimal_plan`) is not costing anything: `empty_plans` is `0/100` on every real run. A smarter
fallback is insurance against a cut-off run, not points. Do not spend a day on it.

**Bar.** MacEPR and C-LPR up, FPR not down. Ceiling `~+0.5` — one screen, then stop either way.

### P5 — spend the idle envelope on fresh seeds

**Cheap, and genuinely uncertain.** §3 shows one extra sampling pass is worth ~1 query in 68; whether
ten passes are worth ten times that is the open question, and the answer spans "not worth the code"
to "second-best item on this list."

**The idea.** Every run ends with `50–74%` of its envelope unused because `MIN_BUDGET_GROWTH` drops
every query already solved at the cap. A different `TPC_SEED_SALT` makes a failing query a genuinely
new solve, and `on_result` already guarantees keep-best, so an extra attempt can only improve the
split. On the evaluation host an explore pass over ~65 failing queries costs ~25 min
(`ceil(65/15)` rounds × `300 s`), so the idle `4.7 h` fits roughly ten.

**Why it will probably do nothing:** a fresh salt draws different tuples from the *same*
`_random_params` space, exactly as continuing the restart loop does.

**Predict the shape, not the total.** The two readings separate cleanly, which is the whole reason to
spend a slot:

| Reading | Flips in pass 1 | Flips across ~10 passes |
| --- | --- | --- |
| independent draws | ~1 | **5–10** (`+1.7..+4.2` overall) |
| reachable set exhausted (§3's reading) | ~1 | **1–2** |

**Record flips per pass** and check whether pass `k` still flips at pass 1's rate. A flat curve
promotes this item; a curve that dies after pass 2 closes the "we aren't using our time" question
permanently.

**Where.** `chinatravel/agent/phase2/sweeps.py`: add `SweepConfig.explore_passes` (env
`TPC_P2_EXPLORE`, **default off**); have `solve_one(task)` read `task["seed_salt"]` and set
`TPC_SEED_SALT` for the duration of the solve with the same save/restore discipline as the existing
`_fast_accept` context manager; add an `explore` pass kind in `_candidate_passes` / `_choose_pass`
whose candidates are the still-failing queries, ordered **last** so the first three passes behave
exactly as today, and to which **`MIN_BUDGET_GROWTH` must not apply** (a new seed is new work at any
budget); hand out a distinct salt per explore pass in `_run_pass`. `pass_fits` must still bound it
against the deadline.

**Tests.** Explore is scheduled when repair and polish are empty but budget remains; not scheduled
when the envelope is exhausted; each pass hands out a different salt; `TPC_P2_EXPLORE=0` reproduces
today's pass sequence exactly.

**Depends on** P0 (landed — without a stable seed "a different salt" is not a controlled change) and
P2 (without which the flips cannot be counted).

**Considered and dropped: warm-starting later passes.** `solve_one` does not receive the incumbent
plan, so repair and polish re-solve from scratch. That is real duplicated work, but duplicated work
only matters if time is scarce and §3 establishes it is not. Threading plan state through the worker
boundary — and re-grounding it through `ground_and_check` before it may occupy a `best` slot, or an
unverified plan could win, an acceptance-first violation — is real complexity for a resource we have
in surplus.

### P4 — derive `max_query_sec` from the envelope instead of `DEFAULT_BUDGET_SEC`

**Demoted deliberately; a previous roadmap made this its top recommendation.** Diagnosis §3 is why:
failing queries exhaust a search, not a clock, so raising the cap buys more restarts and more
restarts flip nothing.

Still worth tidying, because the current value arrives by accident: `run_split` resolves
`budget_sec = DEFAULT_BUDGET_SEC` (`300`) and passes it as `SweepConfig(max_query_sec=budget_sec)`,
so `sweeps.DEFAULT_MAX_QUERY_SEC` (`900`) is unreachable dead code on this path. Either make the cap
a function of envelope and query count, or delete the misleading constant. **Do not run this as a
scoring A/B** — it has already been answered.

### P6 — LLM-backed repair proposer (v2 candidate, default off)

**Not for v1.** Library-default Phase 2 flags must make zero LLM calls, the one screened parse arm
came back RED, and the endpoint exists only on the organizers' host, so nothing here can be verified
against the real backend before the deadline.

**Why it is nonetheless the most interesting item after P1.** §3 says the search space does not
contain fixes for the failing queries and §4 says what is missing is the ability to place a specific
activity in a specific window. Those are the two things a language model with tool access can
actually contribute — proposing a plan *shape* or a *targeted edit* the sampler cannot express. It is
the only proposal here besides P1's CP-SAT route that changes what can be expressed.

**The only architecture that respects the invariants:**

- The LLM **proposes**; `ground_and_check` **disposes**. A proposal failing the checker is discarded;
  keep-best means a rejected proposal costs time and nothing else.
- Every value in a committed plan is re-grounded against `WorldEnv`.
- Hard bounds: per-call timeout, max calls per query, max share of the envelope. On timeout or error
  the deterministic path continues unchanged.
- The confirmed endpoint runs `--max-running-requests 8`, a **server-side concurrency cap below the
  15 workers** the scheduler uses. Any LLM stage must throttle to ≤8 in flight or it will queue and
  time out server-side whatever the client does.
- Multi-turn with tool access to `WorldEnv`, and a prompt carrying the *specific failing clauses*
  rather than the whole query. That is a day or two, not an afternoon.

**Bar before it could ever be default-on:** a measured configuration beating the deterministic floor
on a full gate, plus a verified bounded fallback. Absent that, it ships off.

## What not to spend time on

- **Within-query parallelism** (parallel restarts, multi-worker CP-SAT). It is more draws from the
  space §3 measured as exhausted, and since the whole-run scheduler already spends all cores *across*
  queries it now competes for the same cores rather than filling idle ones — so it has to beat the
  alternative use of that core, not merely beat zero. The one screen run
  (`TPC_CP_SEARCH_WORKERS` `1 → 4`, solver-only, `n=20`, `60 s`,
  [row](../results/phase2_baselines/screens/20260731_solver_only_n20_b60_cp_search_workers/summary.json))
  came back RED (`overall_true 46.78 → 45.17`), though inconclusive because `on=4` exhausted the
  box's cores.
- **Preference packing (`TPC_PACK_*`).** Bounded by FPR: `0.05 · (FPR − term)` per term is
  `0.59 + 0.29 + 0.60 = ~1.5` overall *if all three were perfected on every passing plan*, against
  `~0.85` for a single FPR point. If it is ever revisited, re-screen `TPC_PACK_DDR` or `TPC_PACK_ATT`
  alone and require FPR and C-LPR unchanged or better — a packing move that costs one accepted plan
  has already lost more than it can win.
- **More envelope-sensitivity runs.** `1 h / 3 h / 5 h` is flat and §3 explains why.
- **Anything justified by "we only use 26% of the budget".** True, and a dead end. A proposal needs a
  mechanism that makes the extra time *do something new*.
- **Improving the empty-itinerary fallback for score.** `empty_plans` is `0` on every real run.
- **A new parser family.** Zero missing families; less end-to-end leverage than any solver item.
- **An agentic loop on Stage 3 refine.** Both `TPC_P2_LLM_REFINE` and `TPC_P2_LLM_AGENTIC_REFINE`
  show `improve_committed=0` — a loop on top of a mechanism that commits nothing multiplies cost by
  zero benefit. Revisit only if a screen ever shows `improve_committed > 0`.

## Landed and promoted

### Harness defaults (promoted through a measured gate or screen)

Set by `solve_phase2.apply_deterministic_solver_defaults()` before the agent is built. The **library**
default (unset env var) is unchanged, and an explicit operator override still wins — so the
byte-identical opt-in unit tests and the eval tooling's flags-off arm both keep working.

| Flag | Evidence |
| --- | --- |
| `TPC_PIN_TIMED_WINDOWS=1` | timed-window pinning + within-day resequencer, targeting the dominant solver-only failure family. Failed the `300 s` gate on timeouts, **re-gated clean at `900 s`** (`familiar_100_val`, sha `a72357c3`): e2e continuous `43.72 → 48.04`, FPR `20.0 → 25.0`, timeouts `0 → 0`. The `300 s` regression was a budget-boundary artifact of the per-trial deepcopy + full-checker revalidation. |
| `TPC_SOLVE_CONVERGE_PATIENCE=15` | early-convergence stop for the restart search. Quality flat vs pin alone, but solve `p50` `366 s → 265 s` — below even the floor's `337 s`. |
| `TPC_COMMONSENSE_FIRST=1` | commonsense-first finalization: relaxes the repair commit rule for *unaccepted* plans and prefers a schema+commonsense-valid candidate (`best_cs`) at finalization. Paired `120 s` e2e screen: `overall_true 51.34 → 60.98`, C-LPR `67.35 → 89.95`, commonsense pass `30/40 → 40/40`, FPR `32.5 → 35.0`, **`logical_micro` flat** — the proof of mechanism: the gain is the commonsense gate releasing logical credit the solver had already earned. Probe cost is triple-bounded (`_fast_commonsense_prefilter`, `TPC_CS_CHECK_BUDGET=60`, `TPC_CS_CHECK_TIME_FRAC=0.08`), because one official `evaluate_commonsense_constraints` call costs ~`319 ms`. |

The commonsense-first work also fixed the reason two repair passes had gated flat:
`TPC_REPAIR_TRANSPORT_GAPS` and `TPC_REPAIR_INTERCITY` ended with `if not self._accepted(...):
return`, so a repair that successfully fixed a plan's transport chain was discarded whenever the plan
still failed a logical clause — which is every plan they target. `_repair_commit_allowed` now splits
the regimes: an accepted input keeps the strict legacy rule; an unaccepted input commits when the
trial is schema-valid, flips commonsense invalid → valid, and loses no parsed-constraint passes. Both
passes are reachable through the `TPC_COMMONSENSE_FIRST` umbrella.

### Infrastructure landed

- **The confirmed entry point runs the real solver** (2026-08-04). `solve_script_with_harness.py`
  ships `--harness tpc`, dispatching in-process to `solve_phase2.run_split` — zero LLM calls, zero
  network, no subprocess. `opencode`/`codex` are explicit opt-ins. Previously the bare command ran an
  external-CLI LLM demo, which would have failed outright on the organizers' host. Pinned by
  `tests/phase2/test_harness_entry_point.py`.
- **The whole-run envelope and scheduler** (2026-08-04). `chinatravel/agent/phase2/sweeps.py`:
  triage → repair → polish across `CPU-1` workers, oracle-free self-scoring, keep-best, fallback
  written before the first solve. See the [design doc](tpc_phase2_design.md#run-shape).
- **Minimal packaging.** `requirements-submission.txt` (eight PyPI packages, no GPU stack, mirrored by
  `pyproject.toml`'s core dependencies) and `scripts/assemble_phase2_submission.py`, which builds the
  archive and verifies it by unpacking and running it with a stripped `PATH`. It uploads nothing.
- **P0: the restart seed is explicit and reproducible** (2026-08-05). `restart_seed()` replaces a
  `hash((uid, salt))` seed — `hash()` over strings is salted per process unless `PYTHONHASHSEED` is
  pinned, so runs were not reproducible and every worker drew a different restart sequence. That is
  the known mechanism behind the `sd 0.35` same-config score spread. Now a BLAKE2b digest;
  `tests/phase2/test_restart_seed.py` pins cross-process stability, salt sensitivity and range.
- **P7: worker count from CPU affinity** (2026-08-05). `sweeps.available_cpus()` prefers
  `os.sched_getaffinity(0)`, falling back to `os.cpu_count()` off Linux, so a restricted container no
  longer oversubscribes. Five tests in `tests/phase2/test_sweeps.py::TestWorkerConfiguration`.
- **A cold-start race that could empty the whole submitted split** (2026-08-05). A worker dying in
  the pool initializer takes the `ProcessPoolExecutor` down while the run still **exits 0** and ships
  pre-written empty fallbacks. Fixed for the `cache/phase2_solve` case and guarded by
  `tests/phase2/test_cold_start.py`; the failure *shape* is now a standing check in the
  [pre-submission checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).
- **Solver search telemetry** — `restarts_used`, `stop_reason`, `candidates_evaluated`,
  `best_found_at_restart` on every `_solve`, surfaced as `search_telemetry`. A `func_timeout` kill
  used to discard it (assignment happened once, at the end of `_solve`), silently losing data for
  exactly the budget-bound queries it exists to explain; every leader-improving `consider()` now
  snapshots it, tagged `stop_reason="interrupted"`. This telemetry is what diagnosis §2/§3 is built on.
- **Parser recovery** — familiar-100 F1 `~0.20 → 0.9949` with zero missing families, the last steps
  being comma-in-name entity-resolution segmentation and the abbreviation-period truncation fix.
- **Familiar-100 import** with pinned archive checksum, per-member manifest, dedicated split, and the
  val/test partition.
- **Evaluator-parity marker** — every recorded row carries `evaluator_parity`, and
  `scripts/phase2_gate.py` refuses a cross-boundary comparison including one-sided marker presence.

### Landed, implemented, not promoted (all library-default-off)

| Flag | Status |
| --- | --- |
| `TPC_CASCADE_TIMED_WINDOWS` | forward-only cascading shift for the post-pin residual. Gated at `900 s`: solver-only — its own target axis — flat (`+0.004` continuous), e2e ranges overlap. Not promoted; see P1's prior-art table. |
| `TPC_REPAIR_DROP_TRAILING_STAY` | drops a single-day trip's trailing overnight accommodation so `_repair_intercity_endpoints` derives the return floor from the real last activity instead of `24:00`. 1 of 3 target uids fully clears (`overall_true 8.52 → 43.08`); the other 2 have a deeper defect — their day's activities run past every same-day return departure regardless of the accommodation, which no forward-only repair can reach. Its screen was RED, probably because the flag's `_pack_plan` gate also activates the *general* endpoint re-grounding pass on every query. |
| `TPC_PACK_DAV` / `TPC_PACK_DDR` / `TPC_PACK_ATT` / `TPC_DENSIFY_COMPRESS_BEFORE` | preference packing. `TPC_PACK_DAV` screened RED, `TPC_PACK_DDR` green on a quick screen but mixed on a full-split comparison, and all of that evidence predates the 2026-07-30 evaluator sync. `TPC_PACK_ATT` is the most plausible Phase 2 candidate — count-preserving, so it cannot cost FPR or C-LPR — but see [what not to spend time on](#what-not-to-spend-time-on). |
| `TPC_P2_LLM_PARSE` / `TPC_P2_LLM_REFINE` / `TPC_P2_LLM_AGENTIC_REFINE` | LLM stages. Parse audit screened RED once it genuinely fired on every query (`−3.20` `overall_true`); both refine variants commit `improve_committed=0` while their reserved improve slice costs timeouts. |

### Closed — do not reopen without new evidence

- **`TPC_PACK_HOTEL_BREAKFAST` is permanently off.** Upstream PR #29 made a repeated meal type a
  commonsense failure, so the DDR loophole it depended on no longer exists and `check` reverts any
  stacked day.
- **`arrive_no_later` emitted from `end_before`** — see P1's do-not-reintroduce note.
- **LLM reachability** is verified, not assumed: a real DeepInfra endpoint completes the happy path,
  and a closed-port endpoint completes with `valid=True fallback=False`, the failure recorded only in
  telemetry, never an unhandled crash. The organizers' own SGLang/Qwen3.6-27B endpoint remains
  unreachable from here by construction.
- **Slow queries starving the split** — structurally handled by the triage-first, deadline-aware
  scheduler rather than by tuning a per-query budget, and measured: the reference run finishes at
  `26%` of the envelope with `empty_plans 0/100`.
- **Phase 1's commonsense and preference residuals** — 21 of 22 tail plans repaired, preference paths
  wired, `overall 98.98`. Record: [Phase 1 playbook](tpc_phase1_playbook.md).

## LLM packaging: the submission makes zero LLM calls

A packaging fact, not an opinion:

- `TPC_P2_LLM_BACKEND` defaults to `none`, whose client raises on any call.
- `agent_env/config.toml` is **gitignored** and absent from the repository; only
  `config.toml.example` and `config.phase2.example.toml` are tracked. An archive built from git has
  no `[phase2.llm]` backend configured.
- `TPC_P2_LLM_PARSE` is an explicit off-by-default decision in `resolve_llm_client_and_flags`, citing
  the RED screen — not an auto-enable keyed off backend configuration. So the organizer run behaves
  the same as every local run.
- `TPCAgent`'s `backbone_llm` is `TPCLLM`, whose `_get_response` returns the literal string
  `"Empty LLM response"`.

The optional autodetect (`_autodetect_openai_cfg`) only activates when an operator points an env var
at a real endpoint, which the packaged submission never does. The organizers' endpoint is confirmed
(SGLang, `Qwen3.6-27B`, `http://127.0.0.1:30000/v1`, `--reasoning-parser qwen3`,
`--max-running-requests 8`) and `agent_env/config.phase2.example.toml` carries those exact values,
with the Qwen3 thinking-mode-off default now covering the `openai` backend as well — our 30 s
per-call timeout assumes thinking is off. None of that changes the default: shipping deterministic
is the measured position.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never
   feed parsing, solving or finalization.
2. **Flags off is the floor.** Library-default Phase 2 flags preserve the deterministic path and make
   zero LLM calls. A new behavior goes behind an env flag that is off by default, with a unit test
   asserting the floor stays byte-identical. Only `apply_deterministic_solver_defaults()` may turn a
   flag on by default, and only on measured evidence.
3. **Ground before acceptance.** `WorldEnv` and the deterministic validators decide facts and
   acceptance; LLM output is only a proposal.
4. **Acceptance first.** Retain a candidate only after its applicable logical, schema and commonsense
   checks pass. Do not weaken `_make_checker`, `_accepted`, or the `_pack_plan` commit rules.
5. **Nothing promotes by assertion.** A default flips only through a committed row that passes
   `make phase2-gate` against a like-for-like baseline. A screen triages; it never promotes.
6. **Preserve development signals.** Local partitions, HF data, familiar-100 val, familiar-100 test
   and the organizer final set are distinct sources; do not tune repeatedly on any one of them.

## Key source locations

| What | Where |
| --- | --- |
| Random-restart loop, `restart_seed`, `TPC_MAX_RESTARTS` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| `_pin_timed_windows` / `_resequence_day` / `_enforce_windows_in_order` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| `_repair_intercity_endpoints`, `_repair_commit_allowed`, `_flag_enabled_with_umbrella` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| CP-SAT tier and worker count | `chinatravel/agent/tpc_agent/cp_solver.py` |
| Whole-run scheduler (`_choose_pass`, `solve_one`, `default_workers`) | `chinatravel/agent/phase2/sweeps.py` |
| Per-query orchestration and telemetry | `chinatravel/agent/phase2/orchestrator.py` |
| `apply_deterministic_solver_defaults`, `on_result`, `run_split` | `agent_env/scripts/solve_phase2.py` |
| Confirmed entry point | `agent_env/scripts/solve_script_with_harness.py` |
| Whole-run measurement | `scripts/phase2_full_run.py` |
| Failure attribution / commonsense headroom | `scripts/phase2_solver_failure_attribution.py`, `scripts/phase2_commonsense_headroom.py` |
