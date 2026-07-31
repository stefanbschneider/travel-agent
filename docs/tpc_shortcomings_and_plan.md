# TPC 2026: Remaining Shortcomings and the Plan to Close Them

**Status:** active work plan, written 2026-07-31 against `main` @ `2645850`.
**Audience:** an implementing agent that has *not* read the rest of `docs/`. Every work item below states
why it matters, the exact file and function to touch, the flag name, the tests to write, the command to
verify, and the bar that decides whether it ships.
**Scope:** both phases. Phase 1 work is offline plan repair on released data; Phase 2 work is no-oracle
solver/harness work. The [phase boundary](../CLAUDE.md#phase-boundary) is non-negotiable in both directions.

Read this document *with* [`docs/tpc_phase2_roadmap.md`](tpc_phase2_roadmap.md) (which records what already
landed and why) and [`docs/tpc_phase2_eval.md`](tpc_phase2_eval.md) (which defines what a measurement is
allowed to prove). This document does not restate their history; it states what is still broken and what to
do about it.

---

## 0. Ground rules (apply to every item)

These are restatements of [`CLAUDE.md`](../CLAUDE.md) invariants, repeated here so this document is
self-contained. Violating any of them invalidates the work regardless of the score it produces.

1. **Python 3.12 through `.venv/bin/python`.** Never invoke bare `python`. If `.venv/` does not exist,
   create it per [README setup](../README.md#setup).
2. **Never read, edit, stage, or overwrite `.env`.** It is local user configuration. When an LLM backend is
   needed, set `TPC_P2_LLM_BACKEND=deepinfra` and let `build_llm_client` → `load_local_env()` load the key
   into the process itself.
3. **Every new Phase 2 behavior goes behind an env flag that is OFF by default in the library.** The
   deterministic floor must stay byte-identical when the flag is unset, and a unit test must assert that.
   Only `agent_env/scripts/solve_phase2.py::apply_deterministic_solver_defaults()` may turn a flag on by
   default, and only after a measured screen or gate.
4. **No oracle in the Phase 2 agent path.** `hard_logic*` is evaluation-only. Phase 1 offline tooling may
   use it; nothing that runs inside `agent_env/` may.
5. **Acceptance first.** A candidate is retained only after its applicable logical, schema, and commonsense
   checks pass. Do not weaken `_make_checker`, `_accepted`, or the `_pack_plan` commit rules.
6. **Ground every fact in `WorldEnv`.** Never fabricate a POI, price, opening window, or transport leg.
7. **Monotonic writes in Phase 1.** `scripts/merge.py` is the only writer of `results/best/`. Never
   hand-edit a result file; never run concurrent merges.
8. **Branch protocol.** Work on `claude/<topic>`, run `.venv/bin/python -m pytest tests -q` before each
   commit, rebase on latest `main` before pushing.
9. **Nothing promotes by assertion.** A Phase 2 default flips only through a committed row under
   `results/phase2_baselines/` that passes `make phase2-gate` against a like-for-like baseline. A screen
   triages; it never promotes.

### The one scoring fact that decides priority

`eval_tpc.py` publishes:

```
0.10·MicEPR + 0.10·MacEPR + 0.25·C-LPR + 0.40·FPR + 0.05·(DAV + ATT + DDR)
```

Since the 2026-07-28 upstream evaluator sync (integrated here 2026-07-30):

- **C-LPR is conditional on the commonsense pass.** A plan that fails commonsense scores `0` on the
  `0.25`-weighted logical term *and* `0` on its EPR-macro point, however many clauses it satisfies.
- **DAV/ATT/DDR are averaged over every query in the split**, with a zero for each non-passing query. So
  each preference term is bounded above by FPR, and perfecting one term is worth at most `0.05 · FPR`.

**Consequence, and the single sentence that orders this whole document: one FPR point is worth roughly
`0.40 + 0.25·(clause share) + 0.10 + 0.15·(preference of the recovered plan)` ≈ `0.8–0.9` overall points,
while one preference point is worth `0.05 · FPR / 100`. At the current Phase 2 FPR of `25`, FPR is about
six times more valuable per point than preference.** Chase acceptance, not polish.

---

## 1. Where we actually are

### Phase 1 (`results/best`, 1000 queries, synced evaluator)

`make p1eval SPLIT=tpc_phase1`, recorded 2026-07-31:

| MicEPR | MacEPR | C-LPR | FPR | DAV | ATT | DDR | **overall** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `99.89` | `97.80` | `96.47` | `97.80` | `90.11` | `94.46` | `84.26` | **`96.45`** |

### Phase 2 (familiar-100 val, no-oracle harness)

There is **no valid post-sync reference row**. The only post-sync measurement is a sanity screen
([`20260730_upstream_eval_sync`](../results/phase2_baselines/screens/20260730_upstream_eval_sync/README.md),
`n=20`, `120 s`, LLM off — not a gate):

| | MicEPR | MacEPR | C-LPR | FPR | DAV | ATT | DDR | overall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| end-to-end | `100.00` | `100.00` | `88.15` | `25.00` | `13.13` | `19.25` | `12.92` | **`54.30`** |
| solver-only | `99.07` | `75.00` | `63.03` | `15.00` | `6.88` | `10.37` | `10.83` | `40.57` |

Every committed row under `results/phase2_baselines/runs/` predates the evaluator change and is **not
comparable** to anything measured now. `make phase2-gate` currently has no legal baseline.

---

## 2. Shortcoming inventory

Leverage is stated in **overall points on that phase's own scale**. Confidence is how sure we are the
estimate survives contact with the implementation.

| # | Shortcoming | Phase | Leverage | Confidence | Item |
| --- | --- | --- | --- | --- | --- |
| S1 | 22 stored plans violate the two new commonsense rules; all 22 satisfy 100% of their logical clauses | 1 | **`+2.2` to `+2.3`** | **high** (arithmetically confirmed, §3.1) | [W1](#w1-repair-the-22-query-phase-1-commonsense-tail) |
| S2 | Addressable preference residual: `68` non-travel-day missing-meal days, `275` plans below 4 attractions/day, `260` plans with mean hop > 15 min | 1 | `+0.3` to `+0.6` | medium | [W2](#w2-close-the-addressable-phase-1-preference-residual) |
| S3 | No post-sync `900 s` reference row — every Phase 2 gate is currently unrunnable | 2 | blocking, `0` on its own | high | [W3](#w3-re-establish-the-post-sync-900-s-reference-row) |
| S4 | The organizer host gives **16 logical CPUs**; our per-query solve uses **one**, sequentially, and records no search telemetry | 2 | `+1` to `+4` (unmeasured) | low-medium | [W4](#w4-use-the-16-confirmed-evaluation-cpus) |
| S5 | Single-day trips ending in an overnight accommodation make the return leg unplaceable — 3 uids fail all four intercity commonsense columns | 2 | `+0.3` (3/80 queries) | high | [W5](#w5-drop-the-trailing-stay-on-single-day-trips) |
| S6 | `timed_visit_named_poi` is still the sole logical blocker in `53` of `74` solver-only failures *after* pinning | 2 | `+2` to `+5` if closed | low | [W6](#w6-attack-the-post-pin-timed_visit_named_poi-residual) |
| S7 | The `900 s` per-query budget is an unconfirmed assumption; a shorter organizer timeout would silently halve our score | 2 | risk, not gain | high | [W7](#w7-de-risk-the-unconfirmed-budget) |
| S8 | LLM endpoint autodetect landed but was never exercised against a real endpoint; Stage 3 refine still commits `0` edits | 2 | `0` today; compliance risk | medium | [W8](#w8-verify-llm-reachability-and-close-the-parse-policy-decision) |
| S9 | Preference packing (`TPC_PACK_DAV` / `TPC_PACK_DDR`) is implemented, unpromoted, and all its evidence predates the sync | 2 | `≤ +1.5` at FPR 25 | medium | [W9](#w9-re-decide-preference-packing-on-post-sync-evidence) |
| S10 | The familiar-100 held-out test split has never been run post-sync; no overfitting tripwire | 2 | risk, not gain | high | [W10](#w10-run-the-test-tripwire-and-verify-the-shipped-package) |

**Priority order: W1 → W3 → W5 → W4 → W7 → W2 → W10 → W6 → W9 → W8.**
W1 is first because Phase 1 standing decides Phase 2 advancement and W1 is the highest-confidence,
lowest-risk gain on this list. W3 is second because nothing else in Phase 2 can be *promoted* until it
exists. W1 and W3 are independent and should run concurrently on different machines.

---

## 3. Phase 1 work items

### W1: repair the 22-query Phase 1 commonsense tail

**Owner:** implementation. **Estimated effort:** one day. **Expected gain: `96.45 → ~98.7`.**

#### 3.1 The diagnosis, and why it is certain

The [Phase 1 playbook](tpc_phase1_playbook.md#current-status-2026-07-31-after-re-solving-the-evaluator-sync-regression)
currently calls the remaining 22 queries "a genuinely hard tail" after three re-solve rounds recovered `0`
of them. That description is right about the *solver* and wrong about the *plans*. A fresh solve cannot
recover them; a **targeted repair of the stored plan** almost certainly can, and that was never attempted.

Three independent facts establish this. All are reproducible offline with no dependencies (§7.1):

1. **A structural scan of all 1000 stored plans flags exactly 22 uids, and only on the two rules the
   2026-07-28 sync added.** No plan violates any other structural family (no missing outbound/return leg,
   no multi-day itinerary without accommodation):

   | family | plans | what it is |
   | --- | --- | --- |
   | inbound transport departs before the previous activity ends | `19` | upstream `Is_time_correct` |
   | intra-day activity overlap / non-chronological activity list | `16` | upstream `Is_time_correct` |
   | repeated meal type in one day | `10` | upstream `Is_restaurants_correct` |
   | **union** | **`22`** | |

2. **Those 22 are exactly the FPR failures.** FPR requires commonsense *and* logical *and* schema, so the
   FPR-passing set is a subset of the commonsense-passing set. Both are `97.80` — i.e. `978` — so the two
   sets coincide. Every plan that passes commonsense also satisfies all of its logical clauses.

3. **Those 22 plans satisfy 100% of their own logical clauses.** They hold `126` of the split's `3568`
   `hard_logic_py` clauses = **`3.53%`**, and the measured C-LPR is **`96.47` = `100 − 3.53`** to the last
   digit. Since C-LPR is the conditional logical micro, that identity is only possible if the *entire*
   logical shortfall is these 22 queries' zeroed credit and every other clause in the split passes.

So each of the 22 is a plan that satisfies every logical constraint and is rejected purely for a
scheduling/meal artifact. Inspecting them confirms the shape — all three are legacy maxpack artifacts
(the hotel-breakfast stacking that predates `TPC_PACK_HOTEL_BREAKFAST` being made permanently off):

```
20250321040138918100, day 1:   06:30 breakfast · 07:30 breakfast · 08:31 breakfast   <- three breakfasts
20250322103116580364, day 0:   11:10 lunch ... 13:30 lunch                            <- duplicate meal
20250322121729768751, day 0:   ... 17:27 dinner, then 08:00 attraction (The Bund)     <- out of time order
```

#### 3.2 What the gain is worth, precisely

Recovering all 22 moves: MacEPR `97.80 → 100` (`+2.20`), C-LPR `96.47 → 100` (`+3.53`), FPR
`97.80 → 100` (`+2.20`), MicEPR `+0.11`. For preference, the offline analysis shows the all-1000-plan
means are DAV `92.31`, ATT `96.66`, DDR `86.46` versus the official `90.11 / 94.46 / 84.26` — a gap of
exactly `2.20` on each, which means these 22 plans currently score a perfect `1.0` on all three preference
terms (unsurprising: they are the over-stacked ones).

```
0.10(0.11) + 0.10(2.20) + 0.25(3.53) + 0.40(2.20) + 0.05(3 × 2.20) = +2.32
```

**`96.45 → 98.77` in the ideal case.** Dropping a duplicate meal lowers that plan's DDR
(`DDR = (meals/days)/3`), so budget `+2.2` as the realistic figure and treat anything above that as upside.

#### 3.3 What to implement

Create **`scripts/repair_commonsense.py`**, modeled on `scripts/densify.py` (read it first — it is the
exact pattern: read `results/best/<uid>.json`, transform, write only accepted improvements to
`results/<method>/<uid>.json`, and let `scripts/merge.py` remain the sole writer of `results/best/`).

CLI:

```
--split <name>          split file of uids to process (default: a new tail split, see below)
--method <name>         output directory under results/ (default: repair_commonsense)
--limit N               process at most N uids
--dry-run               report the repair each plan would receive, write nothing
```

Apply the four repair moves below **in order**, each on a `copy.deepcopy` of the plan, each committed only
if the full checker still accepts the result. Reuse `TPCAgent`'s existing helpers rather than writing new
geometry: `_get_transport` for legs, `_poi_open_bounds` for opening windows, `_activity_end_position` for
the "where are we now" anchor. Instantiate the agent the way `scripts/densify.py` does.

**R1 — drop duplicate meal types (targets the `10`).**
For each day, group activities by `type ∈ {breakfast, lunch, dinner}`. If a type occurs more than once,
keep exactly one and drop the rest. Choose which to keep, in this order:
   1. one whose `position` appears in the query's `hard_logic_py` (Phase 1 may read oracle fields offline —
      do **not** copy this code into `chinatravel/agent/`);
   2. otherwise the one whose removal leaves the day chronologically valid without further edits;
   3. otherwise the first occurrence.
After dropping activity `i`, recompute the inbound transports of activity `i+1` from
`_activity_end_position(activities[i-1])` via `_get_transport`, and clamp `activities[i+1].start_time` to
at or after that leg's end.

**R2 — restore chronological list order (targets part of the `16`).**
Sort each day's activities by `start_time`, holding the day's head and tail fixed if they are intercity
(`airplane` / `train`) activities — those never move. If sorting changes the order, recompute every inbound
leg in the new order sequentially. This alone fixes days where the list order simply disagrees with the
clock.

**R3 — re-space overlapping activities (targets the rest of the `16`).**
Walk the day forward. When `activities[i].start_time < activities[i-1].end_time`, shift activity `i` (and,
by ripple, everything after it) later so it starts at `max(its own start, previous end + leg duration)`,
preserving each activity's own duration. If the ripple pushes an activity past its POI closing time
(`_poi_open_bounds`) or past a fixed intercity tail, **drop that activity instead of shifting it** and
recompute the surrounding legs. Never move an intercity activity.

**R4 — re-ground an early inbound leg (targets the `19`).**
When an activity's first transport leg starts before the previous activity's `end_time`, re-request the leg
from `_get_transport` with `start_time = previous activity end_time` and set the activity's `start_time` to
the returned arrival. If that makes the activity overlap the next one, fall through to R3's ripple.

**Gate every commit.** After the four passes, run the same full checker `scripts/densify.py` uses. Write
the repaired plan to `results/<method>/<uid>.json` **only if** it is accepted. Then:

```bash
make merge SPLIT=tpc_phase1
```

`merge.py` applies its own strictly-greater weighted-score gate, so a repair that somehow scores worse
cannot regress `results/best/`. Two independent monotonic guards; no repair can make the score go down.

#### 3.4 Tests

New `tests/phase1/test_repair_commonsense.py` (create the package if absent), using synthetic plan dicts
and a fake env — do not build a real `WorldEnv`:

- a day with two `lunch` activities → one is dropped, the following activity's leg is re-grounded;
- a day whose activity list is out of time order but has no overlap → sorted, legs recomputed, no activity
  dropped;
- a genuine overlap where shifting fits inside the POI's opening window → shifted, not dropped;
- a genuine overlap where shifting would pass the POI's closing time → the activity is dropped;
- a leg starting before the previous activity ends → re-grounded from the previous end time;
- **a plan that the checker rejects after repair → nothing is written** (the byte-identical-floor case);
- an intercity head/tail activity is never moved, dropped, or re-timed by any of the four passes.

#### 3.5 Verify

```bash
.venv/bin/python -m pytest tests/phase1 -q

# 1. Regenerate the tail work list and confirm it is still these 22 (see §7.1 for the scanner).
.venv/bin/python scripts/scan_commonsense_residual.py --out /tmp/p1_tail.txt

# 2. Dry-run first: every uid must report at least one applicable repair.
.venv/bin/python scripts/repair_commonsense.py --split p1_commonsense_tail --dry-run

# 3. Repair, merge, score.
.venv/bin/python scripts/repair_commonsense.py --split p1_commonsense_tail
make merge SPLIT=tpc_phase1
make p1eval SPLIT=tpc_phase1

# 4. Re-scan: the structural scan must now flag zero plans.
.venv/bin/python scripts/scan_commonsense_residual.py
```

#### 3.6 Ship bar

`make p1eval SPLIT=tpc_phase1` reports **FPR ≥ `99.0`** and **overall ≥ `98.0`**, with no metric lower than
its 2026-07-31 value. Commit the repaired `results/best/` entries and update the
[Phase 1 playbook](tpc_phase1_playbook.md) "Current status" table with the new numbers and the date.

If a uid resists all four repairs, record it by uid and by which check still fails — that residual is real
evidence about the solver, unlike the current "hard tail" framing which this item disproves.

---

### W2: close the addressable Phase 1 preference residual

**Owner:** implementation. **Do W1 first** — preference on a failing plan is worth zero, and W1 changes the
denominator. **Expected gain: `+0.3` to `+0.6`.**

Offline analysis of `results/best` (§7.1, `scripts/analyze_pref.py`, dependency-free) gives the ceiling for
each term if every plan were perfected:

| term | mean over 1000 | perfect plans | ceiling if all → 1 |
| --- | --- | --- | --- |
| DAV | `92.31` | `725/1000` | `+0.384` overall |
| ATT | `96.66` | `740/1000` | `+0.167` overall |
| DDR | `86.46` | `604/1000` | `+0.677` overall |

Most of that is **structural, not addressable**, and the analysis says exactly how much:

- **DDR** — `1107` missing meal-slots total. Of the days missing a meal, `696` are **travel days** (an
  intercity leg eats the meal band; a missing meal there is correct, not a defect) and only `68` are
  non-travel days. **Only those `68` are addressable.** Add the missing meal type at a real restaurant in
  the free gap, via `scripts/densify.py`'s existing `TPC_PACK_DDR` path. Never add a *second* meal of a
  type already present — that is now a commonsense failure and `check` reverts it.
- **DAV** — `275` plans hold fewer than 4 attractions/day, but the distribution has a hard floor: `4` plans
  have literally zero attractions and `19` have one, which are almost certainly single-day trips with no
  room. Target the `attr/day ∈ [3.0, 4.0)` band (`~185` plans) where one insertion completes the day.
- **ATT** — `19729` hops, median `8` min, `p90` `39` min, max `385`. `260` plans have a mean hop above
  15 min. Re-routing each hop to its shortest-time valid mode via `_get_transport` (trying a free walk
  first, so inner-city cost budgets are respected) is the whole move; it is already implemented inside the
  `TPC_PACK_DAV` insertion path and just needs to run standalone over already-accepted plans.

**How.** No new mechanism is needed. Run the existing densify controller on the preference tail:

```bash
TPC_PACK_DAV=1 TPC_PACK_DDR=1 .venv/bin/python scripts/iterate_tail.py \
  --split tpc_phase1 --rank-mode preference --pref-metric overall --runner densify \
  --rounds 4 --top-k 240 --stop-no-improve-rounds 1 \
  --run-id phase1-preference-postW1 --resume
make p1eval SPLIT=tpc_phase1
```

`TPC_PACK_HOTEL_BREAKFAST` stays **off**: it is a structural no-op since the sync, because `check` reverts
any day with a stacked meal type.

**Ship bar.** DAV/ATT/DDR each not lower and at least one materially higher, with FPR and C-LPR unchanged.
The previous densify pass converged after two rounds (`95.70 → 96.45`, then nothing); if this one converges
immediately with no gain, record that and stop — the remaining deficit is then structural and this item is
closed, not failed.

---

## 4. Phase 2 work items

### W3: re-establish the post-sync `900 s` reference row

**Owner:** evaluation. **Blocking for W4, W5, W6, W9.** **Gain: `0` on its own; nothing promotes without it.**

Every row in `results/phase2_baselines/runs/` was produced under the pre-2026-07-28 evaluator contract.
Rows straddling that change are **never** comparable ([eval doc](tpc_phase2_eval.md#ledger-comparability)),
so `make phase2-gate` currently has no legal baseline and no Phase 2 default can be flipped.

Run the current promoted configuration — harness defaults, which means `TPC_PIN_TIMED_WINDOWS=1`,
`TPC_SOLVE_CONVERGE_PATIENCE=15`, `TPC_COMMONSENSE_FIRST=1`, LLM backend `none` — as a pinned row:

```bash
make phase2-baseline-at SHA=$(git rev-parse HEAD) \
  P2_SPLIT_SET=val P2_BUDGET=900 P2_REPEATS=2 P2_PARALLEL=3 \
  P2_LABEL=postsync-ref-900s
```

**Requirements for the row to count:**

- `familiar_100_val` (80 queries), `900 s`, **2 repeats** (variance is the point — the previous reference
  row's own repeat-to-repeat FPR spread was `0.625`, and several past "effects" were smaller than that);
- LLM backend `none`, so the row is the deterministic floor and reproducible on any machine;
- committed under `results/phase2_baselines/runs/` with its `git_sha`, and referenced from the roadmap's
  "Current status snapshot" as the new reference row.

**Also do:** add a one-line "evaluator contract" marker to the row (e.g. `evaluator_parity: 764614c`) so a
future reader cannot accidentally gate a post-sync row against a pre-sync one. `scripts/phase2_gate.py`
should refuse the comparison when the markers differ; add that check and a unit test for it in
`tests/phase2/test_phase2_gate.py`.

**Ship bar.** The row exists, is committed, is referenced from the roadmap, and `make phase2-gate` run
against itself passes trivially. Expect roughly `8` hours at `parallel=3`; this is the long-running,
non-blocking evaluation workstream job — start it first and do other items while it runs.

---

### W5: drop the trailing stay on single-day trips

**Owner:** implementation. **Effort: half a day.** **Expected gain: `~+0.3` on familiar-100-val.**
*(Numbered out of order to keep the deterministic-repair items together; do this before W4.)*

This is the one fully-specified, never-implemented item from
[`next_steps_after_final_night.md`](agents/next_steps_after_final_night.md) — Tasks 1 and 3 of that brief
landed (`llm_backend_source` and the autodetect path exist in `agent_env/scripts/solve_phase2.py`;
`TPC_PACK_DAV` / `TPC_PACK_DDR` exist in `tpc_agent.py`), but **Task 2 was never done** — `grep -r
TPC_REPAIR_DROP_TRAILING_STAY` returns nothing.

**Why.** Three uids in `familiar_100_val` fail all four intercity commonsense columns at once:
`phase2_familiar_e20241028160403455246_00065`, `phase2_familiar_e20241028160409480928_00071`,
`phase2_familiar_e20241028160444030851_00066`. Each is a **1-day trip whose last activity is an overnight
accommodation running to `24:00`**. `_repair_intercity_endpoints` computes the return-leg departure floor
from that activity's end time (`24:00` = 1440 min), so no train or flight can depart after it, the repair
silently declines, and the plan ships without a return leg. An overnight stay in a single-day itinerary is
wrong on its own terms, independent of the return leg.

**Where.** `chinatravel/agent/tpc_agent/tpc_agent.py`, inside `_repair_intercity_endpoints`
(`tpc_agent.py:1989`), in the return-endpoint half that begins at the
`# Return endpoint: last-day final activity.` comment (`tpc_agent.py:2075`).

**What to implement**, behind a new flag `TPC_REPAIR_DROP_TRAILING_STAY` — default off, and also enabled
implicitly by `TPC_COMMONSENSE_FIRST` through the existing `_flag_enabled_with_umbrella` helper
(`tpc_agent.py:464`), exactly the way `TPC_REPAIR_INTERCITY` is wired:

1. Before the `floor_time` / `floor_min` computation, if the trial plan has **exactly one day** and the
   last day's final activity has `type == "accommodation"`, remove that activity from the trial copy.
2. Recompute `last_incity_idx`, `floor_time`, `floor_min`, and `floor_pos` from the new final
   non-intercity activity.
3. Run the existing return-row search unchanged, and commit through the existing `_repair_commit_allowed`
   (`tpc_agent.py:604`). Do **not** add a new commit rule — it already handles the unaccepted case
   (schema-valid, commonsense invalid → valid, parsed passes not lower).
4. **Never touch a multi-day plan.** `Accomondation is necessary for trips longer than one day` is an
   official commonsense column; dropping the stay there converts one failure into another.
5. If no return row can be placed even after the drop, the trial must be discarded whole — never ship a
   plan that lost its accommodation *and* has no return leg.

**Tests.** Extend `tests/phase2/test_repair_intercity_endpoints.py`, reusing its `_FakeEnv` / `ROWS` /
`_base_plan` fixtures:

- flag off → a 1-day plan ending in an accommodation is returned byte-identical;
- flag on → the accommodation is dropped, a grounded return row is placed, the stubbed commonsense verdict
  flips to valid;
- flag on, **2-day** plan ending in an accommodation → untouched;
- flag on, no return row placeable after the drop → plan returned byte-identical;
- `TPC_COMMONSENSE_FIRST=1` with `TPC_REPAIR_DROP_TRAILING_STAY` unset → the pass runs (umbrella);
  with `TPC_REPAIR_DROP_TRAILING_STAY=0` → it does not (explicit override wins).

**Verify.**

```bash
.venv/bin/python -m pytest tests/phase2/test_repair_intercity_endpoints.py -q

for UID in phase2_familiar_e20241028160403455246_00065 \
           phase2_familiar_e20241028160409480928_00071 \
           phase2_familiar_e20241028160444030851_00066; do
  TPC_REPAIR_DROP_TRAILING_STAY=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
    --split tpc_phase2_familiar_100_val --uid $UID --budget-sec 150 --method phase2_stay_check
done

.venv/bin/python -c "
import json,glob
for f in sorted(glob.glob('agent_env/runs/phase2_stay_check/*/evaluation.json')):
    e=json.load(open(f)); r=e['commonsense_details'][0]
    print(e['uid'], [k for k,v in r.items() if k!='data_id' and v==1], 'overall_true', round(e['overall_true'],2))
"
```

**Ship bar.** All three uids lose their intercity commonsense failures, plus a paired screen
(`--flag TPC_REPAIR_DROP_TRAILING_STAY --mode end-to-end --n 40 --budget-sec 120 --parallel 7`) showing
`overall_true` and `commonsense pass` **not worse**. Because only single-day trips are affected, expect a
small clean delta, not a large one. If clean, promote in `apply_deterministic_solver_defaults()` with the
evidence in the docstring, following the `TPC_COMMONSENSE_FIRST` entry as the template. Delete the
throwaway `phase2_stay_check` method directories afterwards.

---

### W4: use the 16 confirmed evaluation CPUs

**Owner:** implementation. **Effort: 2–3 days.** **Expected gain: `+1` to `+4`, unmeasured — the largest
untapped Phase 2 lever and also the least certain.** **Depends on W3** for a baseline.

**Why.** The organizers confirmed on 2026-07-30 that the harness process gets **16 logical CPUs and
112 GiB host RAM** ([competition reference](reference/competition.md#confirmed-evaluation-host-2026-07-30)).
Our per-query solve uses **one core**:

- the random-restart search is a strictly sequential `while restarts < self.max_restarts and not
  out_of_budget()` loop (`tpc_agent.py:1067`), one candidate at a time in one process;
- the CP-SAT tier runs with `num_search_workers = TPC_CP_SEARCH_WORKERS`, **default `1`**
  (`cp_solver.py:243`);
- `agent_env/scripts/solve_phase2.py` has no parallelism of its own — `grep -n "parallel\|Pool" ` finds
  only a docstring.

Fifteen of sixteen cores are idle for the entire per-query budget. Since acceptance is the binding
constraint and the search is random-restart, more restarts inside the same wall clock is close to a free
FPR gain — subject to the measurement caveat below.

**Do it in three steps, cheapest first. Stop at any step that does not pay.**

**Step 0 (free, do this before writing any code): find out what actually binds.**
Nothing in the harness records how many restarts a solve used or why it stopped —
`grep -n "restarts_used\|stop_reason" chinatravel/agent/tpc_agent/tpc_agent.py` returns nothing, and
`orchestrator.py`'s telemetry has no search fields. So we do not currently know whether `900 s` solves are
budget-bound or bound by `TPC_MAX_RESTARTS` (default `400`, `tpc_agent.py:81`). Add to `_solve`, and
surface through `orchestrator.solve_phase2`'s telemetry:

- `restarts_used` (int),
- `stop_reason` (`"budget" | "max_restarts" | "converged" | "accepted_stop"`),
- `candidates_evaluated` (int),
- `best_found_at_restart` (int) — the restart index that produced the emitted plan.

This is pure telemetry: no behavior change, no flag needed, and it makes every later step measurable.
`best_found_at_restart` is the decisive number — if the winning candidate is typically found in the first
20% of restarts, parallel search buys little and the honest answer is to stop here. Write the unit test in
`tests/phase2/test_solve_early_exit.py`, which already exercises the loop.

**Step 1 (one env var, no code): give CP-SAT the cores.**
`TPC_CP_SEARCH_WORKERS` is already plumbed. Screen it:

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_CP_SEARCH_WORKERS --off 1 --on 8 \
  --extra-env TPC_USE_CP_SOLVER=1 --n 40 --budget-sec 120 --parallel 1
```

Note `--parallel 1`: with 8 CP-SAT workers per solve you must **not** also run 7 solves at once, or the
arms are not comparable and both thrash. This is the one experiment in this document where screen
parallelism must be set deliberately rather than to `cores − 1`.

**Step 2 (real work): parallel random restarts.**
New flag `TPC_SOLVE_RESTART_WORKERS`, **default `1`**, which must produce a byte-identical floor.

Design constraints, in order of importance:

1. **Determinism must survive.** Draw a *batch* of `W` parameter sets from the existing `rng` in the same
   sequence the sequential loop would have drawn them, evaluate them concurrently, then fold the results
   back through `consider(...)` **in draw order**. Same seed ⇒ same emitted plan, whatever `W` is and
   whatever order the workers finish in. A unit test must assert this against `W ∈ {1, 4}`.
2. **Processes, not threads.** `_build_plan` and the checker are pure-Python and CPU-bound; the GIL makes
   threads worthless here.
3. **Build `WorldEnv` once per worker, not once per task.** Use
   `concurrent.futures.ProcessPoolExecutor(max_workers=W, initializer=...)` with a module-level lazy
   singleton, and create the pool **once in the harness**, not per solve — per-query pool construction
   would eat the gain in fork/import cost.
4. **The wall-clock bound must still hold.** Check `out_of_budget()` between batches and size the last
   batch to the remaining time. Never let a batch overrun the per-query budget; the timeout-recovery path
   must keep working.
5. **Memory.** 112 GiB across 16 workers is ample for `WorldEnv`, but measure RSS — `solve_phase2.py`
   already records `rss_mb` (`solve_phase2.py:424`). If a worker's RSS × `W` approaches the host limit,
   cap `W`.

**Tests** (new `tests/phase2/test_parallel_restarts.py`): flag unset → the pool is never constructed (spy
on the executor) and the emitted plan is byte-identical to the sequential path on a fixed seed; `W=4` →
same emitted plan as `W=1` on the same seed; a worker raising → the batch degrades to sequential
evaluation for that batch rather than failing the solve; the budget check still fires mid-search.

**Ship bar.** A `900 s` `familiar_100_val` gate against the W3 reference row showing FPR up with no new
timeouts and no new parse failures, **run on a machine with at least `W + 1` cores**. Do not screen this at
`--parallel 7` on a 4-core box; the result would be meaningless. Report the measured wall-clock per query
alongside the score — if parallel restarts raise FPR but also raise `p95` solve time, W7's budget risk gets
worse, and the two must be judged together.

---

### W7: de-risk the unconfirmed budget

**Owner:** implementation + evaluation. **Effort: half a day of compute.** **Gain: risk reduction.**

Every budget number in this repository is a local assumption. The public material specifies neither a
per-query timeout nor a repeat count; `900 s` has been the working expectation only since 2026-07-24. If
the organizer's real timeout is `300 s` or `120 s`, a configuration tuned at `900 s` degrades in a way no
local gate would have caught — and `TPC_PIN_TIMED_WINDOWS` already demonstrated exactly this failure mode
in reverse (it regressed timeouts at `300 s` and cleared cleanly at `900 s`).

**Do:**

1. Run the budget sweep on the promoted configuration: `make phase2-budget-sweep` over
   `30,60,120,300,900` on `familiar_100_val`. Record FPR and `overall_true` per budget as a curve, committed
   next to the W3 reference row.
2. **Read the curve for a cliff, not for a maximum.** A configuration whose FPR collapses below `600 s` is
   `900 s`-fragile and is the wrong thing to ship even if it wins at `900 s`.
3. If a cliff exists, make the solver degrade gracefully rather than re-tuning for a guessed timeout:
   `TPC_SOLVE_CONVERGE_PATIENCE=15` was promoted partly as exactly this hedge, and the timeout-recovery
   snapshot already emits the best plan found so far. Verify the recovery path actually fires under a short
   budget by running `--budget-sec 60` on 20 queries and confirming `used_fallback=0` with
   `solve_recovered_from_timeout=1` where timeouts occur.
4. Re-check after W4 lands: parallel restarts change the shape of the curve, so the sweep must be re-run
   on whatever ships.

**Ship bar.** The curve is committed and the roadmap states, in one sentence, which configuration is
safest across the whole range — not which one wins at `900 s`.

---

### W10: run the test tripwire and verify the shipped package

**Owner:** evaluation. **Effort: 2 hours of compute.** **Gain: risk reduction.** **Depends on W3.**

Two independent checks, both never done post-sync:

1. **Overfitting tripwire.** Every screen and gate since 2026-07-23 has run on `familiar_100_val`. Run the
   promoted configuration once on the held-out `tpc_phase2_familiar_100_test` (20 records) and compare the
   val↔test gap. This is a **coarse, high-variance** signal — 20 records — so treat a gap as a warning to
   investigate, never as a per-change gate, and do not run it more than once per submission.
2. **Package verification.** Confirm the submission as built from git is what we think it is. From a clean
   clone (not the working tree — `agent_env/config.toml` is gitignored and may exist locally):

   ```bash
   git clone . /tmp/pkg_check && cd /tmp/pkg_check
   .venv/bin/python agent_env/scripts/solve_phase2.py \
     --split tpc_phase2_familiar_100_val --limit 3 --budget-sec 120 --method pkg_check
   ```

   Then assert from the telemetry: `llm_backend_source == "none"`, zero LLM calls, `valid_output` true on
   all three, `used_fallback` false. This is the fact the roadmap asserts
   ([LLM packaging](tpc_phase2_roadmap.md#llm-packaging-the-submission-makes-zero-llm-calls)) but which has
   never been verified from a clean clone.

---

### W6: attack the post-pin `timed_visit_named_poi` residual

**Owner:** implementation. **Effort: unbounded — timebox it.** **Expected gain: `+2` to `+5` if closed,
but every previous attempt on this family has under-delivered.** **Depends on W3.**

**Why.** `timed_visit_named_poi` is the sole logical blocker in **53 of 70** failing solver-only queries
*after* `TPC_PIN_TIMED_WINDOWS` — the same `53` it was before pinning, against a slightly smaller failure
set. Pinning fixed the cases it was designed for and the family remained dominant.

**Why it is ranked below everything above it.** Three mechanisms have already been aimed at this family:
`_try_pin_activity` (promoted, real gain), `_resequence_day` (promoted with it), and
`_enforce_windows_in_order` / `TPC_CASCADE_TIMED_WINDOWS` (gated at `900 s`, **no measurable effect**, not
promoted). The residual is not one shape; it is the long tail after the two tractable shapes were taken.

**Before writing any code, re-derive the residual on post-sync data.** Every attribution number above comes
from a pre-sync row:

```bash
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode solver-only
.venv/bin/python scripts/phase2_solver_failure_attribution.py --mode end-to-end
```

Run these against the **W3 reference row**, then classify the `53` by shape before choosing a move. The
known-unhandled shape is the **backward** shift: `_enforce_windows_in_order` ripples a target and its
successors *later* only; a target that must move *earlier*, pulling its predecessors back, is out of scope
of every landed move. That is the first candidate — but only if the re-derived classification says it is a
large share of the residual.

**Explicitly do not reintroduce:** emitting `arrive_no_later` from `end_before` to time morning meals. It
was tried, and its ceiling pruned proper transport, producing transport-less plans that fail
`Invalid Transport information across positions`. Note that this is now *worse* than when it was rejected —
since the sync, a plan with no innercity transport also scores ATT `0`.

**Ship bar.** A flag, default off, byte-identical floor, unit tests, a green screen, and a `900 s` gate
against the W3 row. If the re-derived attribution shows the residual has fragmented into shapes with no
common move, **write that finding down and stop** — a documented dead end is a real deliverable here, and
more valuable than a fourth mechanism that gates flat.

---

### W9: re-decide preference packing on post-sync evidence

**Owner:** implementation. **Effort: one screen.** **Expected gain: `≤ +1.5` at FPR `25`.**
**Depends on W3.**

`TPC_PACK_DAV` and `TPC_PACK_DDR` are implemented, tested, and **not promoted**. All their evidence
predates the evaluator sync and is therefore void:

- `TPC_PACK_DAV` screened RED (FPR `37.5 → 32.5`, `overall_true` `61.19 → 59.32`, timeouts `3 → 5`);
- `TPC_PACK_DDR` screened GREEN on the quick screen but mixed on a dedicated full-split comparison;
- `TPC_PACK_HOTEL_BREAKFAST` is **permanently off** — upstream PR #29 made a repeated meal type a
  commonsense failure, so the DDR loophole it exploited no longer exists and `check` reverts any stacked
  day. Do not re-screen it. Do not "fix" it.

**The ceiling is now small and computable.** At the post-sync screen's numbers (FPR `25.00`, DAV `13.13`,
ATT `19.25`, DDR `12.92`), perfecting a term is worth `0.05 · (FPR − term)`:

```
DAV: 0.05 · (25.00 − 13.13) = 0.59
ATT: 0.05 · (25.00 − 19.25) = 0.29
DDR: 0.05 · (25.00 − 12.92) = 0.60
                              ----
                              1.48 overall, if all three were perfected on every passing plan
```

That is the *entire* preference headroom at the current FPR, against `~0.85` overall for a single FPR
point. **Do not spend time here until FPR work is exhausted.** When you do get to it, re-screen
`TPC_PACK_DDR` alone (the more promising of the two) against the W3 row, and require FPR and C-LPR
unchanged or better — a packing move that costs one accepted plan has already lost more than it can win.

---

### W8: verify LLM reachability and close the parse policy decision

**Owner:** implementation. **Effort: half a day.** **Gain: `0` expected; competition-compliance and
robustness.**

**What already landed.** The endpoint autodetect from Task 1 of `next_steps_after_final_night.md` is
implemented: `agent_env/scripts/solve_phase2.py` resolves a backend source and records
`llm_backend_source` in telemetry (`solve_phase2.py:248`, `:419`, `:525`), the parse audit is suppressed for
an auto-detected backend (`solve_phase2.py:268`), and `tests/phase2/test_llm_endpoint_autodetect.py`
covers it.

**What is still open.**

1. **The autodetect has never been exercised against a real OpenAI-compatible endpoint.** Every test is
   monkeypatched with no network. Stand up a local stub (or a real SGLang instance if available), point
   `OPENAI_BASE_URL` at it, and confirm end-to-end that the backend resolves, the model probe succeeds, and
   the parse audit still stays off. Then confirm the *dead-endpoint* case: a `TPC_P2_LLM_BASE_URL` pointing
   at a closed port must complete with `valid=True fallback=False` and no error in telemetry.
2. **The parse-mode decision is unmade.** The last paired screen on current head was RED for audit-on
   (parse off: FPR `30.0`, `overall_true 54.48`; audit on: FPR `20.0`, `overall_true 45.54`). Shipping
   deterministic is the defensible position, but it is currently a *default*, not a *decision*. Either run
   the three-arm screen (off / audit / `extract`) against a working endpoint and record the verdict, or set
   `TPC_P2_LLM_PARSE=0` explicitly in `resolve_llm_client_and_flags` with the RED screen cited in the
   comment. **Do the latter if there is any doubt** — an explicit off is safer than an auto-enable that
   fires only when an endpoint happens to be reachable, because it makes the organizer run behave the same
   as every local run.
   - If you do screen it: set `TPC_P2_LLM_TIMEOUT_SEC` **below** the parse slice (`6` at a `90 s` budget)
     or the stage silently no-ops, and confirm from the screen's LLM-activity line that the call actually
     fired before believing any arm. A green screen where the LLM never fired is meaningless.
3. **Stage 3 refine stays off.** Both `TPC_P2_LLM_REFINE` and `TPC_P2_LLM_AGENTIC_REFINE` still show
   `improve_committed=0` — called on produced-but-invalid plans, committing nothing, while their reserved
   improve slice costs timeouts. Do not enable, do not extend, and do not build an agentic loop on top.
   Revisit only if a screen ever shows `improve_committed > 0`.

**Ship bar.** The dead-endpoint run is clean, the parse policy is an explicit recorded decision rather than
a default, and `agent_env/config.phase2.example.toml` documents the `[phase2.llm]` block for an SGLang
endpoint (add it if absent, with a pointer from `agent_env/README.md`).

---

## 5. Sequencing

```
machine A (Phase 1, no GPU, low memory)      machine B (Phase 2 evaluation, long-running)
─────────────────────────────────────────    ─────────────────────────────────────────────
W1  repair the 22-query tail        ~1 day   W3  post-sync 900s reference row      ~8 h
    make merge / make p1eval                     (start this FIRST, it blocks others)
W2  preference residual             ~4 h     W7  budget sweep on the same config   ~4 h
                                             W10 test tripwire + package check     ~2 h

machine C (Phase 2 implementation, ≥8 cores)
────────────────────────────────────────────
W5  trailing-stay drop              ~4 h     (independent of W3 for the code; needs W3 to promote)
W4  Step 0 telemetry                ~2 h     (independent, do while W3 runs)
W4  Step 1 CP workers screen        ~2 h     (needs a quiet machine)
W4  Step 2 parallel restarts       ~2 days   (needs W3 to gate)
W6  timed-window residual           timeboxed (needs W3 for re-derived attribution)
W9  packing re-decision             ~2 h      (needs W3; lowest priority)
W8  LLM reachability                ~4 h      (independent of everything)
```

Per [CLAUDE.md's parallel workstreams](../CLAUDE.md#parallel-workstreams): the evaluation workstream writes
only generated rows under `results/phase2_baselines/`; the implementation workstream writes only
`chinatravel/`, `agent_env/`, `tests/`, `scripts/`; docs changes go in a separate PR. Each workstream uses
its own branch and rebases on latest `main` before pushing.

---

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| The organizer's per-query timeout is far below `900 s` | medium | high | W7's sweep; `TPC_SOLVE_CONVERGE_PATIENCE=15` is already a hedge; the timeout-recovery snapshot always emits the best plan so far |
| W1's repairs break a logical clause while fixing commonsense | low | low | Every repair is full-checker gated and `merge.py` applies a strictly-greater score gate on top — the score cannot go down |
| W4's parallel restarts break determinism | medium | high | Fold results in draw order; assert `W=1` and `W=4` produce identical plans on a fixed seed |
| W4 raises `p95` solve time and creates timeouts at the real budget | medium | medium | Judge W4's gate together with W7's curve, never alone |
| Another upstream evaluator change before the deadline | low | high | Re-sync and re-establish the reference row before trusting any number; `chinatravel/evaluation/` must reproduce upstream `main` exactly (parity point `764614c`) |
| Overfitting `familiar_100_val` across ~20 screens | medium | medium | W10's test tripwire; never tune on the test split |
| Time runs out mid-item | high | medium | Every item is independently shippable and every Phase 2 change is off by default — abandoning an item costs nothing |

---

## 7. Appendix: reproduction

### 7.1 The offline scanners (no dependencies, no `WorldEnv`, no solve)

`scripts/analyze_pref.py` already exists and is dependency-free — it replicates `eval_tpc`'s DAV/ATT/DDR
formulas directly from plan JSON:

```bash
.venv/bin/python scripts/analyze_pref.py
```

The structural scanner used for §3.1 does not exist yet. **W1 should commit it as
`scripts/scan_commonsense_residual.py`** so the finding stays reproducible; it is stdlib-only and takes
about a second over 1000 plans. It must flag, per plan:

- any day with more than one activity of the same meal type (`breakfast` / `lunch` / `dinner`);
- any activity whose `start_time` precedes the previous activity's `end_time`;
- any inbound transport leg whose `start_time` precedes the previous activity's `end_time`;
- any single-day itinerary whose final activity is an `accommodation`;
- any itinerary missing an intercity head or tail activity;
- any multi-day itinerary with a non-final day lacking an `accommodation`.

It should print counts per family and support `--out <path>` to write the union of flagged uids as a split
file. Run against `results/best`, on 2026-07-31 it printed:

```
plans: 1000
transport_before_prev_end          19
overlap                            16
repeated_meal                      10
union of flagged uids: 22
```

with the other three families empty.

### 7.2 The 22 Phase 1 tail uids (2026-07-31)

```
20250321040138918100  repeated_meal, transport_before_prev_end
20250322103116580364  repeated_meal
20250322104924634145  repeated_meal
20250322121729768751  overlap, transport_before_prev_end
20250322123503517813  overlap, transport_before_prev_end
20250322124519692875  overlap, transport_before_prev_end
20250322131031099056  transport_before_prev_end
20250322141430543582  overlap, transport_before_prev_end
20250322153759813190  overlap, transport_before_prev_end
20250322200936553702  overlap, repeated_meal, transport_before_prev_end
20250322203811815501  transport_before_prev_end
20250322204641477657  overlap, transport_before_prev_end
20250322232713611229  overlap, repeated_meal, transport_before_prev_end
20250322233035985367  overlap, transport_before_prev_end
20250322235559436781  overlap, repeated_meal, transport_before_prev_end
20250323003106691638  overlap, repeated_meal, transport_before_prev_end
20250323024343468774  overlap, transport_before_prev_end
20250323032331347378  overlap, transport_before_prev_end
20250323135305015682  overlap, transport_before_prev_end
20250324195707870699  overlap, repeated_meal, transport_before_prev_end
20250324200212786306  overlap, repeated_meal, transport_before_prev_end
20250324212220275360  repeated_meal
```

These `22` queries hold `126` of the split's `3568` `hard_logic_py` clauses (`3.53%`), and measured C-LPR is
`96.47 = 100 − 3.53` — the identity that proves all `126` clauses currently pass and are being zeroed
purely by the commonsense gate.

### 7.3 Key source locations referenced above

| What | Where |
| --- | --- |
| Random-restart loop (sequential) | `chinatravel/agent/tpc_agent/tpc_agent.py:1067` |
| `TPC_MAX_RESTARTS` default `400` | `chinatravel/agent/tpc_agent/tpc_agent.py:81` |
| `_repair_intercity_endpoints` | `chinatravel/agent/tpc_agent/tpc_agent.py:1989` |
| Return-endpoint half (W5's edit site) | `chinatravel/agent/tpc_agent/tpc_agent.py:2075` |
| `_repair_commit_allowed` | `chinatravel/agent/tpc_agent/tpc_agent.py:604` |
| `_flag_enabled_with_umbrella` | `chinatravel/agent/tpc_agent/tpc_agent.py:464` |
| `_pin_timed_windows` / `_resequence_day` | `chinatravel/agent/tpc_agent/tpc_agent.py:2147` / `:2325` |
| CP-SAT worker count | `chinatravel/agent/tpc_agent/cp_solver.py:243` |
| `apply_deterministic_solver_defaults` | `agent_env/scripts/solve_phase2.py:281` |
| Phase 2 telemetry assembly | `chinatravel/agent/phase2/orchestrator.py:386`–`:478` |
| Phase 1 densify pattern to copy for W1 | `scripts/densify.py` |
| Phase 1 monotonic writer | `scripts/merge.py` |

### 7.4 What this document deliberately does not propose

- **No new parser family.** Familiar-100 parser F1 is `0.9949` with zero missing families; incremental
  parser work has less end-to-end leverage than any solver item above.
- **No agentic LLM loop.** Stage 3 refine commits `0` edits today; adding a loop on top of a mechanism that
  never commits multiplies cost by zero benefit.
- **No promotion of `TPC_CASCADE_TIMED_WINDOWS`.** Its own `900 s` gate found no measurable effect on the
  axis it acts on.
- **No revival of `TPC_PACK_HOTEL_BREAKFAST`** or of `arrive_no_later`-from-`end_before`. Both are closed
  by the current evaluator, not merely unpromoted.
