# Phase 2 improvement plan — the search space, not the schedule

**Written 2026-08-05.** Audience: an implementing agent. Every item below is self-contained —
it names the files, the mechanism, the flag, the tests, and the bar it has to clear. Read
[CLAUDE.md](../CLAUDE.md) first for the non-negotiable invariants; nothing here overrides them.

**The one-paragraph version.** The submission uses only `26%` of its 5-hour envelope, which looks
like wasted headroom. It is not. Fresh measurement (§2b) shows that giving failing queries `2.5×`
the time buys `4.2×` the search and flips **one query in forty-four**, because every knob we have —
more budget, more restarts, more workers, fresh random seeds — is the same intervention: draw more
samples from a parameter space that does not contain the answer. `45 of 61` failing queries fail
on a *single* constraint family the sampler cannot express (§5). **Spend the effort on what the
solver can represent, not on how long it runs.**

What to *measure* after implementing is the [evaluation roadmap](tpc_phase2_eval_roadmap.md)
(R7–R11). What the competition requires is the
[competition reference](reference/competition.md).

---

## The diagnosis

The submission scores `overall 57.99` on `familiar_100` and finishes in `1.31 h` of a `5 h`
envelope (row `results/phase2_baselines/full_runs/20260804T201638Z.json`). Two facts explain
almost everything about where the remaining points are.

### 1. The score is gated by one number

`eval_tpc.py` weights `0.4·FPR + 0.25·C-LPR + 0.1·MicEPR + 0.1·MacEPR + 0.05·(DAV+ATT+DDR)`.
On the reference row:

| | value | weight | contributes |
| --- | --- | --- | --- |
| **FPR** | **33.0** | 0.40 | **13.2** |
| C-LPR | 87.83 | 0.25 | 21.96 |
| MicEPR | 99.48 | 0.10 | 9.95 |
| MacEPR | 97.00 | 0.10 | 9.70 |
| DAV / ATT / DDR | 18.15 / 26.25 / 19.39 | 0.05 ea. | 3.19 |

FPR is the fraction of queries passing *every* constraint, and the three preference terms are
zeroed on any query that fails — so they are bounded above by FPR too. **One FPR point is worth
about `0.85` overall; perfecting all three preference terms at today's FPR is worth `~1.5` in
total.** Preference work is not where the points are.

### 2. The solver is bimodal: it either wins in seconds or burns the whole slice and fails

Per-query search telemetry from a fresh 1 h diagnostic run (`method phase2_diag_1h`, triage pass,
`25 s`/query, `n=42`):

| | accepted (`n=15`) | failed (`n=27`) |
| --- | --- | --- |
| `stop_reason` | `accepted_stop` ×15 | **`budget` ×26**, `accepted_stop` ×1 |
| restarts used | median **0** | median **39** |
| solve seconds | median **3.2** | median **22.7** of a `~23 s` slice |
| best found at restart | median 0 | median 14 |

A query that is going to be solved is solved by the **first constructed plan**, in about three
seconds. A query that is not spends 100% of its slice doing ~39 randomized restarts and finds
nothing acceptable. There is no middle population that "just needed a bit more time."

**This is why more envelope has not bought score.** `1 h / 3 h / 5 h` score `57.35 / 57.86 /
57.99` — flat. The earlier reading, that the `300 s` `max_query_sec` cap made the extra time
*unspendable*, is at best half the story: the failing queries are not waiting on the cap, they are
exhausting a search that has stopped producing improvements (`best_found_at_restart` median 14 of
39 restarts used — the last ~25 restarts found nothing).

### 2b. More search does not help — measured, not assumed

This is the finding that decides the ranking below, and it is the opposite of what "we only use
26% of the envelope" suggests. The same diagnostic run's **repair** pass gave the failing queries
`62 s` each — `2.5×` the triage slice:

| | triage failures (`25 s`, `n=27`) | repair (`62 s`, `n=44`) |
| --- | --- | --- |
| restarts used, median | 39 | **166** |
| `stop_reason` | `budget` ×26 | `budget` ×41, `converged` ×3 — still never the restart cap |
| best found at restart, median | 14 | 47 |
| **queries flipped to passing** | — | **1 of 44** |

`2.5×` the time bought `4.2×` the restarts and flipped **one** query in forty-four. That matches
the 5 h reference run, where the repair pass improved `2 of 66` and polish `11 of 34` (and those
"improvements" are mostly preference-key moves on already-passing plans, not new passes). In every
case the best candidate is found around a third of the way through the restarts and **the whole
back half of the search changes nothing**.

**A sampling note that is itself a finding.** The triage column above comes from a snapshot taken
*during* the triage pass. It has to: `on_result` overwrites `telemetry.json` per query, so once
repair runs, the surviving triage records are only those of queries that never entered repair —
i.e. the ones that passed. Reading triage stats after a completed run silently measures the
winners. That is the bug P2 fixes, and it is why P2 ranks above everything except P1.

**Why more restarts cannot help.** A "restart" resamples one parameter tuple
(`tpc_agent.py:_random_params`): attraction offset, hotel index, attractions per day, visit
minutes, a forced transport mode, optional intercity preferences and a meal offset. That is the
whole search space — a few thousand combinations, sampled independently. Extra budget, a raised
`TPC_MAX_RESTARTS`, more workers, *and a fresh seed salt* are all the same intervention: **draw
more tuples from that space.** The measurement above says the space does not contain a fix for
these queries.

**So the idle 3.4 h is a symptom, not the problem.** The scheduler stops because the search
genuinely has nothing productive left to try, not because it is being timid. Any plan whose
headline is "spend the leftover time" is treating the symptom; the search space itself has to
change, and §5 says where.

### 3. The scheduler has nothing left to schedule, so it stops

`chinatravel/agent/phase2/sweeps.py:_choose_pass` drops a query from a later pass unless its new
budget beats its last by `MIN_BUDGET_GROWTH` (`1.25`). Once repair and polish both clamp to the
effective `max_query_sec` (`300 s` — resolved in `agent_env/scripts/solve_phase2.py:run_split`
from `DEFAULT_BUDGET_SEC`, *not* `sweeps.DEFAULT_MAX_QUERY_SEC`), no query can ever clear that bar
again. The candidate list empties and `run_sweeps` reports *"no pass would do anything new."*

The scheduler is right that re-solving at the same budget reproduces the same plan. A different
seed salt would make it a *different* solve — but §2b measures what a different draw is worth, and
the answer is approximately nothing. Fixing the scheduler without fixing the search space would
convert idle time into idle-time-with-more-restarts.

### 4. The restart RNG is accidentally, uncontrollably random

`chinatravel/agent/tpc_agent/tpc_agent.py:891`:

```python
rng = random.Random(hash((str(query.get("uid", "")), str(self.seed_salt))) & 0xFFFFFFFF)
```

`hash()` over strings is salted per process unless `PYTHONHASHSEED` is pinned, and nothing in this
repository pins it. Verified:

```
$ for i in 1 2 3; do python -c "print(hash(('uid','0')) & 0xFFFFFFFF)"; done
4156652293
674753230
2764167272
```

Three consequences, all of which matter:

- `chinatravel/agent/tpc_agent/readme.md`'s claim that *"fixed query ID plus `TPC_SEED_SALT`
  produces repeatable restart choices"* **is false in practice.** Runs are not reproducible.
- It is the mechanism behind the `sd 0.35` same-config score spread measured across four identical
  2 h runs (see the [eval roadmap](tpc_phase2_eval_roadmap.md#r4--pass-shape-where-should-the-envelope-go)) —
  and therefore the reason single-run A/Bs of `≤ +1` effects keep coming back inconclusive.
- Inverted, it is **free evidence that seed diversity changes outcomes**: same config, same data,
  `constraints_ok` moving `35 ↔ 36` and `overall` by `0.86` across the range.

### 5. One constraint family accounts for almost all of the loss

Solver-only failure attribution (`scripts/phase2_solver_failure_attribution.py`, which feeds the
*oracle* constraints to a bounded solve so parsing is removed from the picture):

```
family                     queries  instances  sole_blocker
timed_visit_named_poi           58         87           45
required_restaurants             5          5            0
required_attractions             4          4            1
required_cuisine_types           2          2            0
```

**`timed_visit_named_poi` is the only failing logical family in 45 of 61 failing queries.** These
are constraints of the shape "be at *this named POI* within *this time window*"
(`activity_position(activity)=="X"` gated by `activity_start_time`/`activity_end_time`).

Put §2b and §5 together and the diagnosis is complete: the random-parameter sampler has no
parameter that *places a specific activity inside a specific time window*. It can shift the day's
starting offset and how many attractions per day, but it cannot pin one activity to a window and
reflow the rest. So no number of draws finds these plans — which is exactly what the flat
budget-sensitivity curve, the 0-improvement repair pass, and the plateaued
`best_found_at_restart` all independently report.

**Corollary for parsing.** Parsing is not the bottleneck either. The last rehearsal has
solver-only FPR `23.75` against end-to-end FPR `25.00` — feeding the solver *perfect* constraints
does not improve it. And on the reference run `constraints_ok` (`35`, the solver's own verdict)
sits within 2 of the official `FPR` (`33`), so the solver is not fooling itself about which
queries it solved. Parser F1 against oracle is `0.9588`. **Parsing works; search is the gap.**

---

## Work items

**Re-ranked 2026-08-05 after §2b.** An earlier draft of this plan led with "spend the idle
envelope on fresh seeds." The repair-pass measurement killed that hypothesis before it was
written up: fresh seeds are the same intervention as more restarts, and more restarts flip zero
queries. It is kept below as P5, cheap and expected-worthless, with a falsifiable prediction —
not as the headline.

| | Item | Effort | Expected | Ships in |
| --- | --- | --- | --- | --- |
| **P1** | **The `timed_visit_named_poi` residual — a window-aware move** | days | **`+2..+5`; the only item that moves FPR** | not v1 |
| P2 | Per-attempt telemetry ledger | 2 h | report figures; measures everything else | v2 |
| P0 | Make the restart seed explicit and reproducible | 30 min | enables trustworthy A/Bs | v1 if time |
| P3 | Emit commonsense-valid plans when nothing is accepted | 2 h | `≤ +0.5` | v2 |
| P7 | Worker count from CPU affinity | 15 min | robustness only | v1 if time |
| P5 | Spend the idle envelope on fresh seeds | half day | **predicted ~0 — read P5 first** | v2 |
| P4 | Derive `max_query_sec` from the envelope | 1 h | ~0 by the same evidence | v2 |
| P6 | LLM-backed repair proposer | 1–2 days | unknown; the one untried *kind* of move | v2 only |

**If you only do one thing, do P1.** Everything else on this list is worth under a point, and
three of the items are worth approximately zero by measurement rather than by guess.

The sections below appear in the table's priority order, not in label order — `P0`…`P7` are stable
identifiers so a later note can refer to "P5" without depending on how the ranking moves.

---

### P1 — the `timed_visit_named_poi` residual: give the search a window-aware move

**This is the item. Everything else on this list is a rounding error next to it.** Diagnosis §5:
this family is the *sole* logical blocker in `45 of 61` failing solver-only queries. Nothing else
on the failure table breaks double digits.

**The shape.** An oracle clause of the form

```python
result = True
for activity in allactivities(plan):
    if activity_position(activity) == "<named POI>":
        result = activity_start_time(activity) >= "HH:MM" and activity_end_time(activity) <= "HH:MM"
```

i.e. *this specific activity must sit inside this specific window*. The random-parameter sampler
(`tpc_agent.py:_random_params`) has no parameter that expresses this — it can move the day's start
offset, attractions per day, and visit minutes, but it cannot pin one activity into a window and
reflow its neighbours. That is why extra restarts, extra budget and extra workers all measure flat.

**Read the prior art before writing anything.** Three mechanisms have already been aimed here:

| Mechanism | Outcome |
| --- | --- |
| `_try_pin_activity` | promoted, real gain |
| `_resequence_day` | promoted with it |
| `_enforce_windows_in_order` / `TPC_CASCADE_TIMED_WINDOWS` | gated at `900 s`, **no measurable effect**, not promoted |

The full brief — including the known-unhandled **backward shift** (a target that must move
*earlier*, pulling its predecessors back, which every landed move ignores) and an explicit
"do not reintroduce" list — is
[W6 in the shortcomings doc](tpc_shortcomings_and_plan.md#w6-attack-the-post-pin-timed_visit_named_poi-residual).
**Start there, not from scratch.** In particular, do not re-emit `arrive_no_later` from
`end_before` to time morning meals: it was tried, it prunes proper transport, and since the
evaluator sync a transport-less plan also scores ATT `0`.

**Step 0, before any code: re-derive the residual on post-sync data.** Every number above comes
from a row with `evaluator_parity: None` — it predates the evaluator sync, so treat it as a
prioritisation signal, not a measurement.

```bash
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode solver-only
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode end-to-end
```

Then **classify the residual by shape** — forward-shift, backward-shift, needs-reordering,
infeasible-as-parsed — and count each. Choose a move only if one shape is a large share. If the
residual has fragmented into shapes with no common move, **write that down and stop**: a
documented dead end is a real deliverable here and is worth more than a fourth mechanism that
gates flat.

**A structurally different option, if the shapes do not converge.** The CP-SAT tier
(`chinatravel/agent/tpc_agent/cp_solver.py`) already exists and already reasons about time. A
timed window is a *native* CP-SAT constraint, unlike a random parameter tuple. Routing queries
whose parsed constraints contain a timed-visit clause into a CP-SAT formulation with the window as
a hard interval constraint attacks the family at the representation level rather than adding a
fourth repair heuristic. Scope this before committing to it — but note it is the only proposal on
this page that changes *what can be expressed*, which §2b says is the actual binding limit.

**Ship bar.** Flag, default off, byte-identical floor, unit tests, and a gate against the
[R7](tpc_phase2_eval_roadmap.md#r7--seed-variance-baseline-the-prerequisite-for-every-ab-below)
variance baseline. With `sd ≈ 0.35`, a `+2` effect is comfortably detectable in a single paired
run; anything smaller needs repeats.

---

### P2 — per-attempt telemetry ledger

**Why.** Two reasons, one of which is a hard requirement. (a) The technical report needs
distributions and timings — min/mean/max with spread, per-pass wall clock, restart histograms —
and today's telemetry cannot supply them. (b) Every other item on this list is measured through it.

**The bug this fixes.** `agent_env/scripts/solve_phase2.py:on_result` writes
`work_root/<uid>/telemetry.json` on **every** attempt, so each pass **overwrites** the previous
pass's record. Attempt history is destroyed as the run proceeds — the §2b table above had to be
reconstructed by reading telemetry mid-run, before later passes clobbered it.

**Change.** Keep `telemetry.json` as the latest (other tooling reads it) and additionally append
one JSON line per attempt to `work_root/<uid>/attempts.jsonl` with at least: `pass_index`,
`pass_kind`, `seed_salt`, `budget_sec`, `wall_sec`, `restarts_used`, `stop_reason`,
`candidates_evaluated`, `best_found_at_restart`, `self_score`, `kept`.

Then aggregate into the committed row in `scripts/phase2_full_run.py`: attempts per query
(min/mean/max), wall per attempt, `stop_reason` histogram, restart-count distribution, and the
first-accept-attempt distribution. **Report figures must be plottable from the committed row
alone**, without the working tree the run happened in — rows are what survive.

**Tests.** Two attempts on one uid append two lines and do not clobber; the row aggregation
matches a hand-computed fixture.

---

### P0 — make the restart seed explicit and reproducible

**Why.** Diagnosis §4. Without this, no A/B on this list can be attributed to the change rather
than to the seed, and the repository's own reproducibility claim is untrue.

**Change.** `chinatravel/agent/tpc_agent/tpc_agent.py:891`. Replace the built-in `hash()` with a
stable digest so the seed depends only on `(uid, seed_salt)`:

```python
import hashlib
seed_bytes = hashlib.blake2b(
    f"{query.get('uid','')}\x00{self.seed_salt}".encode("utf-8"), digest_size=8
).digest()
rng = random.Random(int.from_bytes(seed_bytes, "big") & 0xFFFFFFFF)
```

Do **not** fix this by setting `PYTHONHASHSEED` — it must be set before interpreter start, which
would mean re-exec'ing in the entry point. A stable digest is local and costs nothing.

**Tests.** The same `(uid, salt)` produces the same seed across two separate subprocesses; two
different salts produce different seeds.

**Also fix the doc it falsifies:** `chinatravel/agent/tpc_agent/readme.md` (~line 27) claims fixed
query ID plus `TPC_SEED_SALT` already gives repeatable restarts. It does not, today.

**Bar.** Byte-identical output is *not* expected — the seed changes. What is required is that a
repeated single-query run now produces an identical plan. Verify by diffing two runs of one uid.

---

### P3 — emit commonsense-valid plans when nothing is accepted

**Why.** C-LPR is the *conditional* logical micro: a plan failing commonsense scores `0` on C-LPR
*and* `0` on MacEPR for that query, making a commonsense failure unusually expensive. The
reference row has MacEPR `97`, i.e. **3 queries** in that state.

**What this item is not.** The pre-written fallback (`chinatravel/agent/phase2/fallback.py`,
`minimal_plan`, empty itinerary) is **not** currently costing anything: `empty_plans` is `0/100`
on every real run, because every query gets a real plan long before the envelope ends. A smarter
fallback is insurance against a cut-off run, not points. Do not spend a day on it.

**Change.** The mechanism exists and is off: `TPC_COMMONSENSE_FIRST`
(`chinatravel/agent/tpc_agent/tpc_agent.py:467`) maintains `best_cs`, the best schema- and
commonsense-valid candidate, and prefers it when nothing is fully accepted. Its evidence predates
the evaluator sync. **Re-screen it; do not re-implement it.**

**Bar.** MacEPR and C-LPR up, FPR not down. Ceiling `~+0.5` — one screen, then stop either way.

---

### P7 — worker count from CPU affinity

`sweeps.default_workers()` uses `os.cpu_count() - 1`. Correct on the evaluation host (16 logical
CPUs, all assigned to the harness) and on the 4-core development box (verified: `nproc` `4`,
`os.cpu_count()` `4`, `sched_getaffinity` `4`, workers `3`). It is wrong inside a container with a
restricted CPU set, where `os.cpu_count()` reports the host's CPUs and the scheduler oversubscribes.

```python
try:
    available = len(os.sched_getaffinity(0))
except AttributeError:            # not on Linux
    available = os.cpu_count() or 2
return max(1, available - 1)
```

Strictly safer, no behaviour change on either machine we care about.

---

### P5 — spend the idle envelope on fresh seeds

**Read this before implementing it: the measurement predicts this is worth approximately zero.**
It is listed because the time is otherwise thrown away and the change is cheap — a lottery ticket
bought with free money, not an investment.

**The idea.** Every run ends with `50–74%` of its envelope unused because `_choose_pass`'s
`MIN_BUDGET_GROWTH` filter drops every query already solved at the cap. Giving a failing query a
different `TPC_SEED_SALT` makes it a genuinely new solve, and `on_result` already guarantees
keep-best, so an extra attempt can only improve the split.

**Why it will probably do nothing.** Diagnosis §2b. A fresh salt draws different tuples from the
*same* `_random_params` space; so does simply continuing the existing restart loop. Repair gave
failing queries `3.4×` the restarts and flipped `0`. There is no reason a differently-ordered draw
from a space that does not contain the answer would find it.

**Falsifiable prediction, so this stops being an open question either way:** an explore pass over
the ~65 failing queries at the 5 h envelope flips **fewer than 3** of them. If it flips more, §2b
is wrong and this item is promoted; if it flips none, the "we aren't using the time" question is
closed permanently and nobody needs to raise it again.

**Where.**

- `chinatravel/agent/phase2/sweeps.py`
  - `SweepConfig`: add `explore_passes: bool = False` (env `TPC_P2_EXPLORE`) — **default off**,
    because it is unmeasured.
  - `solve_one(task)`: read `task["seed_salt"]` and set `TPC_SEED_SALT` for the duration of the
    solve, using a context manager modelled exactly on the existing `_fast_accept` (same
    save/restore discipline, same per-task rationale).
  - `_candidate_passes` / `_choose_pass`: add an `explore` kind whose candidates are the still
    failing queries (`repair_order`). **`MIN_BUDGET_GROWTH` must not apply to it** — a new seed is
    new work at any budget. Order it last, so the first three passes behave exactly as today.
  - `_run_pass`: pass a distinct `seed_salt` per explore pass.
- The deadline check in `pass_fits` must still bound it: the run stops before the envelope ends,
  with the best-so-far plan on disk.

**Tests.** Explore is scheduled when repair and polish are empty but budget remains; not scheduled
when the envelope is exhausted; each pass hands out a different salt; `TPC_P2_EXPLORE=0` reproduces
today's pass sequence exactly.

**Depends on P0** — without a stable seed, "a different salt" is not a controlled change, and P2,
without which you cannot count the flips that are the whole point.

**Considered and dropped: warm-starting later passes.** `solve_one` does not receive the incumbent
plan, so repair and polish re-solve from scratch. That is real duplicated work — but duplicated
work only matters if time is scarce, and §2b establishes it is not. Threading plan state through
the worker boundary (and re-grounding it through `ground_and_check` before it may occupy a `best`
slot, or an unverified plan could win — an acceptance-first violation) is real complexity for a
resource we have in surplus. Do not build it.

---

### P4 — derive `max_query_sec` from the envelope instead of `DEFAULT_BUDGET_SEC`

**Demoted deliberately; a previous roadmap made this its top recommendation.** Diagnosis §2b is
why: failing queries exhaust a search that has stopped improving, not a clock. Raising the cap buys
more restarts, and more restarts flip nothing.

Still worth tidying, because the current value arrives by accident rather than by design:
`run_split` resolves `budget_sec = DEFAULT_BUDGET_SEC` (`300`) and passes it as
`SweepConfig(max_query_sec=budget_sec)`, so `sweeps.DEFAULT_MAX_QUERY_SEC` (`900`) is unreachable
dead code on this path. Either make the cap a function of envelope and query count, or delete the
misleading constant. **Do not run this as a scoring A/B** — it has already been answered.

---

### P6 — LLM-backed repair proposer (v2 candidate, default off)

**Not for v1.** Library-default Phase 2 flags must make zero LLM calls
([CLAUDE.md](../CLAUDE.md)), the one screened parse arm came back RED, and the endpoint exists only
on the organizers' host, so nothing here can be verified against the real backend before the
deadline.

**Why it is nonetheless the most interesting item after P1.** §2b says the search space does not
contain fixes for the failing queries, and §5 says what is missing is the ability to place a
specific activity in a specific window. Those are the two things a language model with tool access
can actually contribute — proposing a *plan shape* or a *targeted edit* that the random sampler
cannot express. It is the only proposal here, besides P1's CP-SAT route, that changes what can be
expressed rather than how often it is sampled.

**The only architecture that respects the invariants:**

- The LLM **proposes**; `ground_and_check` **disposes**. A proposal failing the checker is
  discarded. Keep-best means a rejected proposal costs time and nothing else.
- Every value in a committed plan is re-grounded against `WorldEnv`. The model never supplies a
  POI, price, or schedule that is not verified.
- Hard bounds: per-call timeout, max calls per query, max share of the envelope. On timeout or
  error the deterministic path continues unchanged.
- Confirmed endpoint (`docs/reference/competition.md`): `http://127.0.0.1:30000/v1`, model
  `Qwen3.6-27B`, **`--max-running-requests 8`** — a server-side concurrency cap *below* the 15
  workers the scheduler will use. Any LLM stage must throttle to ≤8 in flight or it will queue and
  time out server-side no matter what the client does.

**What "properly, like Claude Code would" means concretely:** multi-turn with tool access to
`WorldEnv` so the model looks up real POIs and schedules instead of inventing them, and a prompt
carrying the *specific failing clauses* rather than the whole query. That is a substantially larger
build than a single-shot call — a day or two, not an afternoon.

**Bar before it could ever be default-on:** a measured configuration beating the deterministic
floor on a full gate, plus a verified bounded fallback. Absent that, it ships off.

---

## What not to spend time on

- **Preference packing (`TPC_PACK_*`).** Bounded by FPR; the entire headroom across DAV, ATT and
  DDR is `~1.5` overall at today's FPR, versus `~0.85` for a single FPR point.
- **More envelope-sensitivity runs.** `1 h / 3 h / 5 h` is flat and §2b explains why. Re-running it
  answers nothing new; the search space, not the schedule, is the binding constraint.
- **Anything justified by "we only use 26% of the budget".** That observation is true and it is a
  dead end — §2b measured it. If a proposal's rationale is "we have time to spare", it needs a
  mechanism that makes the extra time *do something new*, not just more of the same sampling.
- **Single-run A/Bs of small effects.** With `sd ≈ 0.35`, an arm worth `+0.5` needs repeats. Run
  [R7](tpc_phase2_eval_roadmap.md#r7--seed-variance-baseline-the-prerequisite-for-every-ab-below)
  before believing any of them.
- **Improving the empty-itinerary fallback for score.** `empty_plans` is `0` on every real run.
  It is insurance, not points.
