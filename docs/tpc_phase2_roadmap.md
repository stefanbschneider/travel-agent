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

**The one-paragraph version.** The submission scores `overall 63.58` on `familiar_100` and uses only
`26%` of its 5-hour envelope, which looks like wasted headroom. It is not. Giving failing queries
`2.5×` the time buys `4.2×` the search and flips **one query in sixty-eight**, because every knob we
have — more budget, more restarts, more workers, fresh seeds — is the same intervention: draw more
samples from a parameter space that does not contain the answer. What moved the score instead was
adding **one move the space could not express**: `+5.83` overall and `+11.0` FPR at identical budget,
restarts and seed. **Spend the effort on what the solver can represent, not on how long it runs.**

**That thesis has now been tested at full scale, and it held.** [P1](#p1--the-timed_visit_named_poi-residual-give-the-search-a-window-aware-move)
gave the solver the move the dominant failure family needs;
[R8](tpc_phase2_eval.md#what-the-closed-queue-r1r13-established) measured `FPR 32.0 → 43.0` over a
baseline whose three repeats were bit-for-bit identical, and it is **on by default since
2026-08-05**. `33 of 80` val queries are still blocked by nothing but that same family, which is what
[P8](#p8--bounded-local-window-push-the-rest-of-the-timed-visit-residual) and
[P9](#p9--place-an-absent-timed-visit-poi) are for.

## Where we are

Current best known configuration and the row the next arm is measured against:
`results/phase2_baselines/full_runs/20260805T123142Z.json` — **R8**, `familiar_100`, 5 h envelope,
3 workers, `evaluator_parity: c89cfca`, zero LLM calls, finishing in `1.31 h`. Its configuration is
now the default (`TPC_WINDOW_ANCHOR=1`), so this is what the bare organizer command produces:

| | value | weight | contributes |
| --- | --- | --- | --- |
| **FPR** | **43.0** | 0.40 | **17.20** |
| C-LPR | 89.90 | 0.25 | 22.48 |
| MicEPR | 99.67 | 0.10 | 9.97 |
| MacEPR | 98.00 | 0.10 | 9.80 |
| DAV / ATT / DDR | 24.71 / 33.65 / 24.50 | 0.05 ea. | 4.14 |

`empty_plans 0/100`, `constraints_ok 46/100`. **FPR is `63%` of the remaining `36.42` points**: at
weight `0.40` the `57` failing queries hold `22.8`, and because a failing query is also scored `0` on
every preference term, they hold most of the `10.86` still missing across DAV/ATT/DDR as well. C-LPR
(`2.53`) and the two EPR terms (`0.23`) are the rest.

The predecessor row `20260804T201638Z` (`overall 57.99`, FPR `33.0`, `constraints_ok 35/100`) and the
three bit-identical R7 repeats (`57.74985419574877`, FPR `32.0`) are the pre-P1 floor. They stay in
the ledger as the baseline R8's `+5.83` is measured against, not as a description of the current
system.

The submission path itself is settled: the organizers'
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
fed to a bounded solve so parsing is removed). **Pre-sync vintage, kept for the argument below**; the
current post-sync counts and — more usefully — the *shape* breakdown that says which move fixes them
are in [P1's Step 0 result](#step-0-result-2026-08-05):

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

**Confirmed by construction, 2026-08-05.** P1 added the missing move and nothing else — same budget,
same restart count, same seed — and `all_pass` went `26 → 34` on `n=80`. The gap was representation,
not search time.

### 5. Parsing is not the bottleneck either

Solver-only FPR (`23.75`) sits *below* end-to-end FPR (`25.00`) on the last rehearsal — feeding the
solver perfect constraints does not improve it. On the reference run `constraints_ok` (`35`, the
solver's own oracle-free verdict) is within 2 of the official `FPR` (`33`), so the solver is not
fooling itself about which queries it solved. Parser F1 against oracle is `0.9588`–`0.9949`
depending on the measurement, with zero missing families. **Parsing works; search is the gap.**

## Work items

| | Item | Effort | Expected | Ships in |
| --- | --- | --- | --- | --- |
| **P8** | **Bounded local window push — the shift/shorten half of the timed-visit residual** (`TPC_WINDOW_PUSH`) | 1 day | **`12 of 80` val sole-blocker queries need only a forward-shift or shorten (`32` clause instances, `11` off by `5–19 min`)** | pending |
| **P9** | **Place an absent timed-visit POI** | half day | **`6` val queries blocked by nothing but this shape** (`15` instances) | pending |
| P2 | Per-attempt telemetry ledger | 2 h | report figures; measures everything else | v2 |
| P3 | Re-screen commonsense-valid emission when nothing is accepted | 2 h | `≤ +0.5` | v2 |
| P5 | Spend the idle envelope on fresh seeds | half day | **`~0` or `+1.7..+4.2` — genuinely open** | v2 |
| P4 | Derive `max_query_sec` from the envelope | 1 h | ~0 by the same evidence | v2 |
| P6 | LLM-backed repair proposer | 1–2 days | unknown; the one untried *kind* of move | v2 only |
| ~~P1~~ | ~~`timed_visit_named_poi`: a window-aware move~~ (`TPC_WINDOW_ANCHOR`) | — | **promoted 2026-08-05: [R8](tpc_phase2_eval.md#what-the-closed-queue-r1r13-established) GREEN, `overall +5.83`, `FPR +11.0`; on by default** | v1 |
| ~~P0~~ | ~~Explicit, reproducible restart seed~~ | — | **landed 2026-08-05** | v1 |
| ~~P7~~ | ~~Worker count from CPU affinity~~ | — | **landed 2026-08-05** | v1 |

`P0`…`P9` are stable identifiers, so a later note can refer to "P5" without depending on the
ranking. Sections below are in priority order. Everything still open is safe to implement in
parallel with the eval queue — none of it touches the shipping default.

**If you only do one thing, do [P8](#p8--bounded-local-window-push-the-rest-of-the-timed-visit-residual).**
P1 confirmed the family is where the points are and took `8` queries out of it; `33` remain, still
blocked by nothing else — `12` of them needing only a forward-shift or shorten (P8), `6` only an
insertion (P9), and `8` a cross-day relocation nobody has scoped yet. Every other item on this list
is worth under a point, and three are worth approximately zero by measurement rather than by guess.
**P8 carries an implementation addendum written against the source; read it before writing code** —
it fixes the flag name, hook point and ordering, states the push as arithmetic, and retracts one
paragraph of P8's prose that describes a mechanism the environment does not have.

### P8 — bounded local window push: the rest of the timed-visit residual

**Read [P1](#p1--the-timed_visit_named_poi-residual-give-the-search-a-window-aware-move) first**,
especially its [Step 0 shape classification](#step-0-result-2026-08-05) and the failure mode below.
P8 is the direct continuation, not a new direction, and the diagnosis is already done.

**Where the residual stands after P1.** Same instrument, same split, on the flag-*on* plans
(`familiar_100_val`, `n=80`, solver-only, harness defaults + `TPC_WINDOW_ANCHOR=1`, `all_pass 34`):

```bash
.venv/bin/python scripts/phase2_timed_window_shapes.py \
  --plans results/phase2_solver_only_tpc_phase2_familiar_100_val \
  --split tpc_phase2_familiar_100_val --detail
```

`43 of 80` queries still fail a timed-visit clause, **`33` with nothing else failing**, `57` failing
clauses:

| shape | instances | sole-blocker queries needing *only* this shape |
| --- | --- | --- |
| forward-shift | 21 | 8 |
| absent POI | 15 | 6 |
| shorten | 11 | 4 |
| backward-shift | 10 | 8 |

(plus `7` sole-blocker queries needing a combination). So the family is still the whole story, and it
is still one clause short on a third of the split.

**Why P1's relayout left them — the *effect* is measured, the *cause below is a hypothesis*.**
`_relayout_movable_block` re-derives *every* leg in the day through `_get_transport` at its new
departure time and places each activity at earliest arrival. The sentence that followed — "because
each re-derived leg lands a little later than the plan's original leg and the error accumulates" —
**cannot be the mechanism**: a leg's duration does not depend on its departure time, so re-deriving
at a later clock cannot lengthen it. See [addendum item 3](#p8-implementation-addendum-2026-08-05)
for the likelier cause (a mode change) and treat neither account as established until the uid is
replayed. The before/after below is a real replay and the cascade is real; only its explanation is
open. That the whole-day relayout is the wrong granularity for a 5-minute fix does not depend on
which explanation holds. Replaying it on `phase2_familiar_20250321155107635610_00035` day 1 — a
breakfast needing `+15 min` —

```
before: brea 07:30-08:30  attr 09:04  attr 10:37  lunc 12:05  attr 13:58  attr 15:19  dinn 17:25  acco 18:54
after : brea 07:45-08:40  attr 09:30  attr 11:33  lunc 13:35  attr 16:22  attr 18:56  dinn 21:53  acco 23:38
```

The window is satisfied and the checker still rejects (`11/12`): a 15-minute nudge became a
**4½-hour** cascade. That is why `11` instances remain that are off by only `5–19 minutes`.

**The move.** Shift the target into its window (shortening its dwell to fit, which `_try_pin_activity`
already computes), then **translate** the following activities by exactly the deficit — preserving each
one's dwell and re-deriving only the legs that must change — stopping as soon as the day absorbs it.
Arithmetic over the 32 remaining forward/shorten instances says how far that has to reach:

| after the target is clamped | instances |
| --- | --- |
| absorbed by existing inter-activity slack — nothing else moves | 2 |
| needs the successors pushed (near-misses: **`5–19 min`**) | 28 |
| target is the day's last movable activity | 2 |

So a push bounded at, say, `30 minutes` covers most of the near-miss set, and the bound is what keeps
it from degenerating into P1's cascade. Start there and read the near-miss list from `--detail`.

**~~The trap to check first.~~ Retracted — it describes a mechanism that does not exist.** The
paragraph read: *"Translating a leg's `start_time`/`end_time` without re-deriving it can claim a
metro departure at a time no service runs, which the commonsense checker catches as Invalid
Transport information across positions. Decide per leg: re-derive through `_get_transport` when the
mode is scheduled, translate when it is not."* There is no timetable, no service window and no
waiting anywhere in inner-city transport, and the column named is not the one that would catch it.
**Do not implement that rule** — the verified constraint, and the simpler move it licenses, are in
[§ Implementation addendum, item 2](#p8-implementation-addendum-2026-08-05).
Kept visible for the same reason P1 keeps its wrong paragraph: it is why the move was scoped as the
harder of the two options.

**`absent POI` is no longer in scope here** — it moved to [P9](#p9--place-an-absent-timed-visit-poi),
because it is insertion rather than retiming and needs its own POI resolution and slot choice. P8 is
purely the shift/shorten residual.

**Out of scope, and say so if you skip it.** `backward-shift` where the window has already passed on
that day (8 sole-blocker queries) needs **cross-day relocation**, a structurally different move. A
coarse check says `22 of 25` absent/backward instances have some day whose free span contains the
window, so the headroom is real — but a duplicate visit to a POI already in the plan trips the
repeated-attraction commonsense rule, so relocation means move-then-delete, not insert.

**Ship bar.** Same as P1: flag, default off, byte-identical floor, unit tests, a paired screen on
**both** axes (`scripts/phase2_quick_eval.py --flag TPC_WINDOW_PUSH --extra-env
"TPC_PIN_TIMED_WINDOWS=1,TPC_COMMONSENSE_FIRST=1,TPC_SOLVE_CONVERGE_PATIENCE=15,TPC_WINDOW_ANCHOR=1"`
— all four are harness defaults since R8, but the screen sets them explicitly because
`phase2_quick_eval.py` builds its own arm environments; the point is that both arms carry P1, so the
screen measures P8's *marginal* effect), and a re-run of `phase2_timed_window_shapes.py` showing the
residual shrinking on the shapes claimed and nowhere else. **The baseline to beat is now R8's
`overall 63.58` / `FPR 43.0`, not R1's `57.99`.**

#### P8 implementation addendum (2026-08-05)

**Read this before writing code.** Added after a source review of every mechanism P8 names. Items 1,
4 and 5 are decisions that were missing; item 2 corrects a factual error in the section above; item 3
flags an unverified claim. **Where this addendum and the prose above disagree, this addendum wins.**

**1. Flag, hook point, ordering.** Name the flag `TPC_WINDOW_PUSH`. Add `_window_push_enabled()`
beside `_window_anchor_enabled()` (`tpc_agent.py:520`), copying its form exactly
(`os.environ.get("TPC_WINDOW_PUSH", "0") not in ("", "0", "false", "False")`). Call the new pass from
`_pack_plan` **immediately after** the `if self._window_anchor_enabled():` block
(`tpc_agent.py:1308-1310`) and still **before** the `if not self._accepted(*check(plan)): return
plan` gate, with the same `self._set_transport_context(constraints or {})` prelude. The order is not
cosmetic: P8 is defined and screened as the *marginal* effect on top of P1, whose screen env sets
`TPC_WINDOW_ANCHOR=1`, so running the push before the anchor would measure a different thing than the
ship bar claims. Floor test: with `TPC_WINDOW_PUSH` unset, `_pack_plan` must not reach the pass at
all (mirror `tests/phase2/test_window_anchor.py`'s floor test).

**2. The verified transport rule — translate, never re-derive.** Three facts from source, replacing
the retracted trap paragraph:

- `InnerCityTransport.goto` (`chinatravel/environment/tools/transportation/apis.py:190-346`) is pure
  distance/speed arithmetic for all three modes — walk `5 km/h`, taxi `40 km/h`, metro
  walk-to-station + `30 km/h` + walk-from-station. **No timetable, no service hours, no waiting.**
  `add_time` (`apis.py:50-71`) adds `int(hours * 60)` whole minutes, a duration that does not depend
  on the clock it is added to.
- What the evaluator actually enforces is stricter than P8 assumed and lives elsewhere:
  `Is_transport_correct` (`chinatravel/symbol_verification/commonsense_constraint.py:840-1077`)
  re-calls `goto(city, transports[0]["start"], transports[-1]["end"], transports[0]["start_time"],
  mode)` for **every** leg — the 3-segment metro shape and the 1-segment walk/taxi shape alike — and
  requires **exact string equality** of every segment's `start_time` and `end_time` (plus `price` and
  `distance` within `0.1`). It reports under the column spelled, upstream typo included,
  `'Incorrect Information of Inner-City Transporton on price, distance, and duration'` — grep for
  `Transporton` to find every write site. The column P8 named, `'Invalid Transport information across
  positions'`, belongs to `Is_space_correct` (`commonsense_constraint.py:1169-1273`), which only
  checks endpoint names and non-empty `transports` and **never looks at a time**.
- Therefore **shifting every segment of a leg by the same whole-minute delta reproduces exactly what
  `goto` returns at the shifted departure time, for every mode including metro.** Translation is not
  the risky option; it is the provably exact one.

**Both halves of that were checked against the environment, not only read.** Calling `goto` for the
same POI pair at `08:30`, `08:45` and `19:05` returns identical per-segment durations, distances and
costs for walk, taxi *and* a 3-segment metro route. And applying the move itself to real data — take
each of the `71` commonsense-passing `familiar_100_val` solver-only plans, shift day 1's last movable
activity by `+15 min` together with every segment of its own `transports`, and retime the overnight
stay — leaves **`70` still commonsense-valid**. The single failure is not a transport error at all:
it pushed `Yonghe Temple` past its `17:00` closing time (*The attraction is closed now*), which is
guard (c) in item 5.

So the move is a pure translation, and that buys two things beyond simplicity: it preserves `mode`,
`price`, `cost`, `distance` and `tickets`/`cars` verbatim (`_format_transport_segments`,
`tpc_agent.py:5555-5579`), so a pushed suffix **cannot** move the preference key by re-routing — the
ATT-fraction friction that forced P1's two-regime commit rule does not arise — and it removes any
need to reason about mode selection (item 3). Use `_repair_commit_allowed`'s two-regime rule anyway,
for the same reason `_anchor_timed_windows` does: the input plan is unaccepted by construction.

**3. Unverified: why P1's relayout cascaded.** The cascade itself is a real replay; its published
cause was re-derivation drift ("each re-derived leg lands a little later than the plan's original leg
and the error accumulates"), now marked as a hypothesis in the section above.
That cannot be the mechanism as stated, because item 2 establishes a leg's duration is independent of
its departure time. In the replayed day the same hotel→attraction leg takes `34 min` before and
`50 min` after, which is a **mode change**, not drift: `_get_transport`
(`tpc_agent.py:5446-5512`) returns the *first* mode from `mode_order` that grounds, and that order is
rewritten by `_forced_inner_mode` (a restart parameter), `_budget_limits["inner_transport"]`,
`conditional_transport` and `excluded_inner_transport` — the relayout runs under whatever
`_set_transport_context(constraints)` last installed, not under the params the plan was built with.
Translating sidesteps this completely. **You do not need to resolve this to implement P8**; if you
ever do call `_get_transport` on an existing leg, pin `_forced_inner_mode` to that leg's own `mode`
first, and do not repeat either explanation as fact without replaying the uid.

**4. The push, as arithmetic.** Target activity at day `d`, slot `i`, deficit `delta > 0` minutes
(from `phase2_timed_window_shapes.py --detail`'s `off=<N>m`). On a `deepcopy` trial:

1. Clamp the target into its window with the dwell arithmetic `_try_pin_activity`
   (`tpc_agent.py:2386`) already computes — `start = max(arrival, lo)`, `dwell = min(dwell, hi -
   start)` — and re-derive **only the target's own inbound leg**, since its departure time genuinely
   changed.
2. Walk slots `i+1 …` forward while `delta > 0`. For each, the free gap to its predecessor is
   `start_time − (predecessor end_time + its own leg duration)`. Absorb `min(delta, gap)` there; the
   remaining `delta` is what this activity must move by. Shift that activity's `start_time`,
   `end_time` and **every segment of its own `transports`** by exactly that remainder (dwell
   preserved, per item 2 — no `_get_transport` call). Stop as soon as `delta` reaches `0`; that is
   the "absorbed by the day" case (`2` of the `32` instances). A shift that would run an activity
   past its POI's closing time bounds the push here (guard (c) in item 5).
3. If the movable block ends with `delta` still positive, the push has to be taken up by the day's
   fixed tail. Reuse P1's `retime_stay_tail` rule verbatim: an `accommodation` tail may move later,
   an intercity departure may not, and nothing may pass `24:00`. Otherwise fail the trial.
4. Bound the whole thing at `TPC_WINDOW_PUSH_MAX_MIN`, default `30` (the near-miss set is
   `5–19 min`, so `30` covers it with headroom while keeping this from degenerating into P1's
   whole-day relayout). A required push above the bound fails the trial rather than truncating.
5. Commit per day, deepcopy-trialed, through `_repair_commit_allowed`, exactly as
   `_anchor_timed_windows` does (`tpc_agent.py:2800-2866`).

**5. Guards that will bite.** Three, in the order they will hurt:

(a) `minutes_to_time` clamps at `23:59` (`tpc_agent.py:58`) while the
evaluator's `add_time` has no wrap and will happily emit `24:05`, so a translated time at or past
`24:00` silently becomes a bogus `23:59` and hands a wrong departure to the next leg — reject the
push instead, as the anchored path already does.

(b) Chronological order (`Is_time_correct`,
`commonsense_constraint.py:1079-1166`) needs `transports[0].start_time >= previous activity's
end_time` and `activity.start_time >= transports[-1].end_time`; a uniform shift of a contiguous
suffix preserves both internally, so the only place it can break is the boundary between the last
shifted activity and the first unshifted one — check that leg explicitly. Keep the contiguity
precondition every existing mover enforces (`movable_slots[-1] - movable_slots[0] + 1 ==
len(movable_slots)`).

(c) **POI opening hours — the one that actually broke in the experiment above.** A pushed activity
must still end before its POI closes (`Is_attractions_correct`, `commonsense_constraint.py:461`;
`Is_restaurants_correct`, `:680`). Check every shifted activity against
`_lookup_poi_open_bounds`/`_poi_open_bounds` (`tpc_agent.py:1350`, `1368`) *before* handing the trial
to the checker, so a push that would close a POI is bounded rather than merely rejected — otherwise
one late-closing attraction discards the whole day's push. The acceptance gate would catch it either
way; catching it in the arithmetic is what makes the pass useful.

**6. Unit tests to write** (bare-agent harness, zero-travel `_get_transport` stub, as in
`tests/phase2/test_window_anchor.py`): slack absorption moves nothing downstream; a `15 min` push
shifts the suffix by exactly `15 min` with every dwell and every leg segment offset unchanged; a push
needing more than the bound is rejected; a push that would run an activity past its POI's closing
time is bounded or rejected; an `accommodation` tail absorbs a push and an intercity tail does not;
and the flag-off floor.

**7. How to reproduce items 2 and 5(c)** — both were established with two throwaway scripts, not
committed, and each is a few lines: (i) call
`Transportation(lang="en").goto(city, a, b, dep, mode)` for one POI pair at three departure times and
compare per-segment `end_time − start_time`, `distance` and `cost`; (ii) over
`results/phase2_solver_only_tpc_phase2_familiar_100_val/*.json`, keep the plans
`func_commonsense_constraints` already accepts, apply the shift by hand, and re-check. Re-run them if
you doubt any claim in item 2 — that is cheaper than debugging the pass.

### P9 — place an absent timed-visit POI

Split out of [P8](#p8--bounded-local-window-push-the-rest-of-the-timed-visit-residual) on
2026-08-05, because it is insertion rather than retiming and needs machinery P8 does not touch. `15`
failing clause instances, `6` sole-blocker queries needing only this shape.

`_insert_activity` / `_insert_activity_before_first` / `_insert_activity_after_last` already take a
`window` tuple and honour it, and their commit rule is the over-strict one P1 had to fix — they
require `_accepted(*check(plan))` *and* `_activity_counts(plan) > before` *and*
`_accepted_eval_key(plan) >= before_key` (`tpc_agent.py:1626`, `1719`, `1783`), so on an unaccepted
input the last clause rejects an insertion that flips the plan to accepted because a leg cost a
fraction of an ATT point. Use `_repair_commit_allowed`'s two-regime rule instead.

**What makes this a separate item, not a cheap rider on P8.** All three helpers take a resolved POI
**dict** (name plus open/close bounds), not a name, and their only callers today are the densify and
meal-top-up paths (`tpc_agent.py:1617-1622`, `3376`, `3421`, `3559-3612`). Using them for a *named*
timed-visit POI needs new wiring the paragraph in P8 glossed: resolve the clause's POI name against
`WorldEnv` into that dict, choose the day, and choose the `prev_idx` slot — plus the
repeated-attraction commonsense rule if the POI is already in the plan on another day. Same ship bar
as P8.

### P1 — the `timed_visit_named_poi` residual: give the search a window-aware move

**Landed and promoted 2026-08-05 — [R8](tpc_phase2_eval.md#what-the-closed-queue-r1r13-established)
gated it GREEN (`overall 57.75 → 63.58`, `FPR 32.0 → 43.0`, `constraints_ok 36 → 46`) and
`TPC_WINDOW_ANCHOR=1` is now a [harness default](#harness-defaults-promoted-through-a-measured-gate-or-screen).
This was the item, and it delivered.** Diagnosis §4: the *sole* logical blocker in `45 of 61`
failing solver-only queries; nothing else on the failure table breaks double digits. Kept in full
because it is the worked example for the family — the shape classification, the three defects it
found in the landed machinery, and the measured before/after. The continuation is
[P8](#p8--bounded-local-window-push-the-rest-of-the-timed-visit-residual).

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
| `_anchor_timed_windows` (`TPC_WINDOW_ANCHOR`) | the same clamp-and-ripple, with type-aware intersected windows, a re-timable overnight-stay tail, and the two-regime commit rule | added 2026-08-05, [screened GREEN](#step-0-result-2026-08-05) (FPR `+10` on both axes), **R8 GREEN (`FPR +11.0`), promoted the same day** |

**This paragraph was wrong, and the measurement that replaced it is below.** It read: *"the residual
is not one shape; it is the tail after the two tractable shapes were taken, and the known-unhandled
shape is the backward shift — a target that must move earlier, pulling its predecessors back."* The
[Step 0 classification](#step-0-result-2026-08-05) says backward-shift is the *smallest* of the four
shapes (`10 of 65` instances), and that the residual is dominated by shapes the landed moves already
claim to handle and fail to. Kept here deliberately: the wrong guess is why three mechanisms were
built before anyone counted.

**Step 0, before any code: re-derive the residual on post-sync data**, then **classify it by shape**
(forward-shift, backward-shift, needs-reordering, infeasible-as-parsed) and count each. **Done
2026-08-05 — the result is the next section; do not re-derive it, extend it.** The instrument is
`scripts/phase2_timed_window_shapes.py`; the family-level view remains

```bash
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode solver-only
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode end-to-end
```

Choose a move only if one shape is a large share. **If the shapes do not converge, write that down
and stop** — a documented dead end is a real deliverable here and worth more than a fourth mechanism
that gates flat.

#### Step 0 result (2026-08-05)

Family-level attribution cannot answer "which move", so
[`scripts/phase2_timed_window_shapes.py`](../scripts/phase2_timed_window_shapes.py) was added: it
re-evaluates each produced plan's oracle clauses with the official `evaluate_constraints_py`, parses
every failing timed-visit clause back into `(activity types, POI, earliest, end_before)` — the
familiar-100 template is exact, `149/149` clauses match — locates the target activity, and reports
the *move* that would satisfy it. Post-sync input: a fresh `familiar_100_val` solver-only run
(`n=80`, `90 s`/query, harness defaults, `FPR 32.5`).

`51 of 80` queries carry ≥1 failing timed-visit clause (`41` sole logical blocker), `65` failing
clauses:

| shape | instances | queries | sole-blocker instances |
| --- | --- | --- | --- |
| forward-shift (starts too early) | 24 | 22 | 19 |
| shorten (dwell exceeds the whole window) | 16 | 15 | 14 |
| absent POI (target not in the plan at all) | 15 | 13 | 11 |
| backward-shift (ends too late) | 10 | 9 | 10 |

**The shapes do converge, but not on the axis the prior art assumed.** Forward-shift, shorten and
backward-shift are one move — *clamp the activity into its window and let the day absorb it* —
covering `50 of 65` instances (`77%`) and `32 of 41` sole-blocker queries. They differ only in which
direction the consequence ripples. So the deliverable is not a fourth mechanism aimed at a new
shape; it is fixing why the existing clamp-and-ripple mechanism does nothing.

**Why `_enforce_windows_in_order` gated flat — measured, not guessed.** Replaying it over the
produced plans fixes `4 of 65` clauses. Its rejections attribute cleanly:

| Rejection | Count | Why it is wrong |
| --- | --- | --- |
| the day's fixed tail is unreachable at its recorded `start_time` | 29 | **25 are the overnight `accommodation` stay**, whose start time records when the traveller got back to the hotel, not a departure that can be missed. Correct for a train, wrong for a hotel. |
| the window is unreachable in the current order | 16 | includes every backward-shift case whose target's window has already passed by the time the forward pass reaches it |

On top of that, `_window_for_position` resolves a window by **position name only**. `11 of 80` val
queries carry *two* timed windows on the same POI name differing only in activity type — a hotel's
`Dine at … between 07:45 and 08:40` and its `Stay at … between 20:10 and 24:00` — so the day's
breakfast gets clamped to the 20:10 stay window and the relayout dies. One query carries two *meal*
windows on one hotel (`07:45–08:40` and `07:50–08:35`) that only their intersection satisfies.

The `shorten` bucket is the sharpest illustration: `10 of 16` instances are the hard-coded `07:30–08:30`
hotel breakfast against a `45–55` minute window — off by **5 to 15 minutes**.

#### What was implemented: `TPC_WINDOW_ANCHOR`

A window-anchored day relayout (`_anchor_timed_windows`, `_resolve_slot_windows`), default off, run
from `_pack_plan` after `_pin_timed_windows`, reusing `_relayout_movable_block` through two new
opt-in parameters so every existing caller stays byte-identical. Three deltas, each traceable to a
row above:

1. **Type-aware, intersected window resolution.** A window applies only to an activity whose type it
   names, and all windows naming one activity are intersected (`max(earliest)`/`min(end_before)`).
   Both constraint sources now record the types: `parse_constraints` from the sentence's verb
   (`Visit`/`Dine at`/`Stay at`), `solver_constraints` from the oracle clause's `activity_type` test.
   The key is additive — nothing reads `activity_types` unless the flag is on.
2. **A re-timable overnight-stay tail** (`retime_stay_tail`): a ripple may push the `accommodation`
   tail's `start_time` later, never an intercity departure, and never past `24:00`.
3. **The two-regime commit rule** already used by `_repair_commit_allowed`: the trial must be fully
   accepted either way, and must additionally not lower the preference key only when the *input* was
   already accepted. Requiring a non-regressing key against an unaccepted input rejected layouts
   that flipped the plan to accepted because a rerouted leg cost a fraction of an ATT point.

Measured on the same produced plans, against the landed forward-only cascade as the control:
clauses fixed `6 → 9`, queries flipped to full logical pass `5 → 8`. Capability (1) is worth `+1`
clause, (2) `+2` clauses and `+2` queries.

**Screen result (paired, same subset/budget/seed, only the flag changes).** The post-hoc probe above
understates it, because in a real solve the pass runs on every candidate inside the restart loop
rather than once on the finished plan.

| | solver-only | end-to-end |
| --- | --- | --- |
| row | [`screens/20260805_solver_only_n80_b90_window_anchor`](../results/phase2_baselines/screens/20260805_solver_only_n80_b90_window_anchor/summary.json) | [`screens/20260805_e2e_n80_b90_window_anchor`](../results/phase2_baselines/screens/20260805_e2e_n80_b90_window_anchor/summary.json) |
| FPR | `32.50 → 42.50` (**+10.00**) | `32.50 → 42.50` (**+10.00**) |
| `all_pass` (n=80) | `26 → 34` | `26 → 34` |
| `overall_true` | `56.95 → 62.27` | `57.81 → 63.13` |
| C-LPR / logical micro | `86.41 → 87.43` / `90.94 → 91.96` | `88.00 → 89.01` / `90.15 → 91.17` |
| commonsense pass / EPR-macro | `76 → 76` / `95 → 95` (flat) | `78 → 78` / `97.5 → 97.5` (flat) |
| timeouts, `used_fallback`, `parse_failures` | `0 → 0` on all three | `0 → 0` on all three |
| solve `p50` | `53.52 s → 53.58 s` | `50.60 s → 53.13 s` |
| monotonic gate | PASS — **GREEN LIGHT** | PASS — **GREEN LIGHT** |

`familiar_100_val`, `n=80`, `90 s`/query, `parallel=7`, harness defaults stacked on both arms
(`TPC_PIN_TIMED_WINDOWS=1,TPC_COMMONSENSE_FIRST=1,TPC_SOLVE_CONVERGE_PATIENCE=15`). The two axes
agreeing to the query matters: the end-to-end arm reads `activity_types` from the *sentence's verb*,
the solver-only arm from the *oracle clause's type test*, so both extraction paths are exercised and
the effect is not an artifact of oracle constraints. Commonsense and EPR being exactly flat while
`all_pass` moves `+8` is the proof of mechanism: the gain is windows being satisfied, not a side
effect on another layer. A screen triages and never promotes — this one buys
[R8](tpc_phase2_eval.md#r8--the-gate-for-a-window-aware-move) on the eval machine.

**The floor is intact on real data, not only in unit tests.** The flag-off arm reproduces the
pre-change run exactly: `FPR 32.5`, `all_pass 26`, `commonsense_pass 76`, `logical_micro 90.94`.

**Independent mechanism check.** Re-running the shape diagnostic on the flag-*on* plans shows the
residual shrinking on precisely the targeted shapes and nowhere else:

| shape | flag off | flag on |
| --- | --- | --- |
| shorten | 16 | **11** |
| forward-shift | 24 | **21** |
| absent POI | 15 | 15 (untargeted) |
| backward-shift | 10 | 10 (untargeted) |

`8` clause instances fixed, `8` queries flipped — the same `8`, and none of them from a shape this
move does not claim to handle.

**Two shapes remain open, and the shift family is only partly taken.** `absent POI` (insertion, not
retiming) and already-passed-window `backward-shift` (cross-day relocation) were never in this move's
scope, and `32 of the 50` shiftable instances also survived it — `11` of them off by only `5–19`
minutes, because a whole-day relayout is the wrong granularity for a five-minute fix. The shift
residual is scoped, sized and instrumented in
**[P8](#p8--bounded-local-window-push-the-rest-of-the-timed-visit-residual)**, the top work item, and
`absent POI` in **[P9](#p9--place-an-absent-timed-visit-poi)**; already-passed-window
`backward-shift` (`8` sole-blocker queries) remains unscoped.

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

**Ship bar — cleared.** Flag, byte-identical library-default floor, unit tests, and a whole-run row
against the R7 variance baseline. R8 delivered `+5.83` overall / `+11.0` FPR against a baseline whose
three repeats were *bit-for-bit identical*, so the effect needed no repeats: the screen predicted
`FPR 32.5 → 42.5` and the full run measured `32.0 → 43.0`. It also cost nothing to ship — wall clock
`4786 s → 4733 s`, `empty_plans 0/100` both sides. `apply_deterministic_solver_defaults()` sets it on
next to the pin it depends on; the library default stays off so the floor tests keep describing the
shipped floor, and `TPC_WINDOW_ANCHOR=0` still reproduces the R7 arm.

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
| `TPC_WINDOW_ANCHOR=1` (2026-08-05) | [P1](#p1--the-timed_visit_named_poi-residual-give-the-search-a-window-aware-move)'s window-anchored day relayout. The only flag promoted on a **whole-run** row rather than a per-query gate, and the only one whose effect is unambiguous by construction: R8 (`full_runs/20260805T123142Z`) scored `overall 63.58` / `FPR 43.0` / `constraints_ok 46` against R7's `57.75` / `32.0` / `36` — and R7 is **three bit-identical 5 h repeats**, so `+5.83` cannot be seed noise. Same box, envelope, worker count and `evaluator_parity` on both sides; wall clock `4786 s → 4733 s`, `empty_plans 0/100`. Matches the paired `n=80`/`90 s` screens that queued it (predicted `FPR 32.5 → 42.5`). Set next to `TPC_PIN_TIMED_WINDOWS`, which is what puts the named POI in the plan for it to anchor — R8 measured the pair, so the pair ships. |

Every recorded row now carries a `solver_flags` snapshot of exactly these four (per-query
`telemetry.json`, `chinatravel/agent/phase2/orchestrator.py`). They are environment reads inside
`TPCAgent` rather than fields on `Flags`, so before that a row could not state which of them ran —
and after R8 that is the only way to distinguish an archive running the promoted configuration from
one silently running the pre-R8 one.

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
- **`solver_flags` in per-query telemetry** (2026-08-05). The promoted deterministic passes are
  environment reads inside `TPCAgent`, not fields on `Flags`, so a row used to be silent about the
  configuration that produced it — the one thing the ledger's comparability rule demands. Now every
  `telemetry.json` snapshots all four (`PROMOTED_SOLVER_FLAGS`,
  `chinatravel/agent/phase2/orchestrator.py`), using the agent's own off-set so the record cannot
  disagree with the behaviour, and a drift test fails if a flag is promoted without being recorded.

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
| `_anchor_timed_windows` / `_resolve_slot_windows` / `_relayout_movable_block` (P1) | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| Timed-window `activity_types` extraction | `parse_constraints.py` (`_window_activity_types`), `chinatravel/agent/tpc_agent/solver_constraints.py` (same name) |
| `_repair_intercity_endpoints`, `_repair_commit_allowed`, `_flag_enabled_with_umbrella` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| CP-SAT tier and worker count | `chinatravel/agent/tpc_agent/cp_solver.py` |
| Whole-run scheduler (`_choose_pass`, `solve_one`, `default_workers`) | `chinatravel/agent/phase2/sweeps.py` |
| Per-query orchestration and telemetry | `chinatravel/agent/phase2/orchestrator.py` |
| `apply_deterministic_solver_defaults`, `on_result`, `run_split` | `agent_env/scripts/solve_phase2.py` |
| Confirmed entry point | `agent_env/scripts/solve_script_with_harness.py` |
| Whole-run measurement | `scripts/phase2_full_run.py` |
| Failure attribution / commonsense headroom | `scripts/phase2_solver_failure_attribution.py`, `scripts/phase2_commonsense_headroom.py` |
| Timed-window residual **by shape** (which move would fix it) | `scripts/phase2_timed_window_shapes.py` |
| Inner-city transport arithmetic — distance/speed only, **no timetable** | `chinatravel/environment/tools/transportation/apis.py` (`goto`, `add_time`) |
| The evaluator's exact-equality leg check (what makes a translated leg legal) | `chinatravel/symbol_verification/commonsense_constraint.py` (`Is_transport_correct`, `Is_time_correct`, `Is_space_correct`) |
