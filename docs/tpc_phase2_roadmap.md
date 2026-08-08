# Phase 2 implementation roadmap

**The active Phase 2 work plan: where the points are, what to build next, and what is already
settled.** How the system is built: [design doc](tpc_phase2_design.md). What to *measure*:
[evaluation roadmap](tpc_phase2_eval.md). What the competition requires:
[competition reference](reference/competition.md). Read [CLAUDE.md](../CLAUDE.md) first for the
non-negotiable invariants; nothing here overrides them. Phase 1's record is in the
[Phase 1 playbook](tpc_phase1_playbook.md); superseded plans are in the [archive](archive/README.md).

## The one-paragraph version

**Our held-out score is `33.2473`, first place is `36.4060`, and `99.5 %` of that gap is C-LPR.** The
2026-08-08 board ([five teams](tpc_phase2_eval.md#the-full-field-and-what-the-race-is-actually-about-2026-08-08))
also says `FPR = 0` is the whole field, not our bug: four of five teams score exactly `0.0000` and
every preference term is `0` for everyone. So `55 %` of the weight pays nobody, and the ranking is
decided inside the per-clause rate at weight `0.25` — `+4.0` C-LPR is `+1.0` overall.

**What we did about it is measured, and it is large.** `v1` was built from `be196d00` and predates the
entire phrasing-and-precision program; on free prose (the register that behaves like held-out)
[R32](tpc_phase2_eval.md#r32--what-landed-since-v1-measured-on-free-prose) puts the delta at C-LPR
`75.55 → 88.37` and FPR `10.67 → 44.00`, with `191` clauses flipping fail→pass against `29` lost.

**The two causes, for the record, because the fixes follow their shape. (1) Recall.** Our constraint
extraction had **zero** clause-level gaps on the familiar-100 split it was built against and
**12–29 %** on every differently-phrased released set. We optimized, screened and gated against the
one register we were already perfect on, and our held-out tripwire was a 20-record subset of that same
templated artifact, so nothing in the process could have caught it. **(2) Precision.** On free prose
our parser invented a required-POI-name constraint that **no POI in the city can satisfy** in
`23–50 %` of queries — capturing a whole sentence (`"Nanjing for a day by myself with a budget of 1800
RMB"`) as an attraction name. Such a query is *provably* unacceptable at any budget, so it is pinned at
`FPR = 0` and at zero on all three preference terms, and the scheduler keeps paying for it. That is
[§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves) and
[P22](#p22--drop-provably-unsatisfiable-required-name-constraints), and it reproduces the held-out
signature (`EPR-micro 99.48`, `C-LPR 55.20`, `FPR 0.0000`) without needing the clause-independence
argument reading 2 relies on. The earlier diagnosis — that the score was *representation*-bound rather
than compute-bound — was correct and still holds, but it was a diagnosis of one distribution.

## Where we are

| Measurement | Score | What it licenses |
| --- | --- | --- |
| **Organizer held-out, `v1`** | **`33.2473`** | the only external calibration, and since 2026-08-07 **broken out per metric** — see below |
| familiar-100, [R28](tpc_phase2_eval.md#r28--a-whole-run-row-on-the-current-main) `20260807T152009Z` | `64.17251838310492`, FPR `44.0` | current-`main` baseline row (byte-identical to R19 `20260807T043142Z` and R17 `20260806T115309Z`); a configuration on one phrasing register |
| local released 150, R18 | `90.5603` | **nothing about generalization** — same template, a third the constraint density |
| free prose (HF `medium`), matched-budget screen | `41.62 → 49.99` after the phrasing fix | the register the held-out set most resembles, though it is *easier* than held-out — and read its FPR against a **ceiling of `38.67`**, not `100` (see below) |

**Two corrections to how the rows above must be read, both new on 2026-08-07.**

1. **Was:** no row existed on the current `main`. **Now closed:**
   [R28](tpc_phase2_eval.md#r28--a-whole-run-row-on-the-current-main) (`20260807T152009Z`,
   `git_sha aed4363e`) remeasured the current tip and came back byte-identical to R19 on all seven
   metrics and all 100 plans — the row above is already R28, not R19. "Promote" is an available verb
   again; gate any new candidate against R28, not R19.
2. **Every free-prose FPR we have ever measured was scored against a cap we did not know about.**
   The four HF splits' `hard_logic_py` literals are native Chinese while their query text is English,
   so under `--lang en` a clause like `'博物馆' in attraction_type(x)` can never be true — the plan's
   own facts come from `database_en/`. Measured with `scripts/phase2_oracle_literal_translation.py`:
   `59–61 %` of HF queries contain at least one such clause and **none of them is negated**, so the
   highest FPR *any* solver can score there is `38.67` (`medium`), `40.0` (`easy`), `40.91` (`human`),
   `46.0` (`preference_base50`). C-LPR caps at `82.97–90.03`. `hf_medium`'s measured `FPR 16.67` is
   therefore `43 %` of its ceiling, not `17 %` of it. [P23](#p23--make-the-free-prose-register-scoreable)
   lifts the cap.

**The held-out breakdown, published 2026-08-07** ([artifact](../results/phase2_baselines/heldout/20260807_v1_leaderboard.json),
analysis `scripts/analyze_heldout_breakdown.py`):

| | EPR-micro | EPR-macro | C-LPR | **FPR** | DAV/ATT/DDR |
| --- | --- | --- | --- | --- | --- |
| held-out | `99.48` | `95.00` | **`55.20`** | **`0.00`** | `0` / `0` / `0` |
| familiar-100 | `99.67` | `98.00` | `90.08` | `44.00` | `26.04` / `34.48` / `25.19` |

**Read this before picking up any work item.** Three consequences, in order of how much they should
change your plans:

1. **Grounding generalized; only constraint satisfaction failed.** EPR-micro moved `−0.19`. Every fact
   we emit still resolves in the environment on unseen queries. So none of the solver's grounding,
   packing or repair machinery is implicated, and a crashed-run explanation is excluded outright —
   empty plans cannot score EPR-micro `99.5`.
2. **`FPR = 0.0000` needs no second bug to explain it.** Per-clause pass rate on a scored plan is
   `55.20/95.0 = 58.1 %`; a query needs *all* ~11 clauses, so the model predicts `FPR ≈ 0.25` on the
   0–100 scale — a quarter of one query in a hundred. An expectation that far below one query makes
   *observing* exactly zero the likeliest single outcome (`≈ 78 %` at `n = 100`). The same model
   predicts `39.3` against familiar-100's measured `44.0`, so it is calibrated. **Do not spend time
   looking for a systematic single-query failure**; density, query count and clause correlation are
   unknown, so this is a consistency check rather than a prediction.
   **Amended 2026-08-07:** there is now a *simpler* mechanism that reaches the same place without
   assuming clause independence — in `23–50 %` of free-prose queries we emit a required-POI-name
   constraint that no POI can satisfy, which pins those queries at `FPR = 0` outright
   ([§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves)). The two explanations are
   not rivals; the point that changes is that a *third* of the split may be failing for a reason
   with a known, deterministic fix rather than for a diffuse statistical one.
3. **`55 %` of the total weight yields exactly zero, and it unlocks at a threshold.** FPR is `0.40`
   alone and gates the `0.15` of preference terms. Because FPR is multiplicative in the per-clause
   rate, it is flat below `p ≈ 0.75` and steep above it: `p = 0.70 → overall 37`, `p = 0.80 → 43`,
   `p = 0.85 → 49`, `p = 0.90 → 58`. **Rank work by whether it can move `p` past the threshold, not by
   how many clauses it fixes.** An incremental coverage win earns only its C-LPR share at weight
   `0.25`.

Current shipped configuration: `TPC_WINDOW_ANCHOR` + `TPC_PIN_TIMED_WINDOWS` + `TPC_COMMONSENSE_FIRST`
+ `TPC_SOLVE_CONVERGE_PATIENCE` + `TPC_WINDOW_PUSH` + `TPC_WINDOW_INSERT`, all set by
`apply_deterministic_solver_defaults()`, zero LLM calls, `1.38 h` of the `5 h` envelope.

**`v2` is not packaged and must not be uploaded by an agent.** The owner uploads manually, shortly
before the deadline and only with a substantial measured improvement. The leaderboard's rank `1` is
rank 1 of 1 and means nothing. See the
[submission policy](tpc_phase2_eval.md#submission-policy-owners-instruction-2026-08-06).

## The diagnosis

### 1. Coverage, not search: what the held-out gap is made of

Evidence: [generalization probe](../results/phase2_baselines/screens/20260806_generalization_probe/README.md).

An unextracted constraint is not a hard clause — it is a clause we **never try to satisfy**, and one
the acceptance gate cannot see. Two named code-level causes were found and fixed (see
[landed](#the-phrasing-fix-landed-2026-08-06)); both were value-clean, so no cross-language excuse
applied:

- `parse_budget` recognised a total budget only via the familiar-100 template line or a regex
  **requiring the literal word "total"**. Ordinary phrasing ("a budget of 1500 RMB") extracted nothing
  — missed on `92–100 %` of budget clauses on every other set.
- room-type parsing missed plain wording ("two twin rooms").

**The self-deception amplifier.** The scheduler repairs only what *our parsed constraints* say fails.
A constraint we never extracted cannot fail, so the query is marked satisfied and promoted to polish.
Measured on free prose: self-reported `FPR 86.67` against a real `6.67`, with `1546 s` of `1800 s`
**unspent**. The envelope is not just insufficient — it is spent on the wrong queries and then idled.
That is [P17](#p17--stop-trusting-our-own-satisfied-verdict).

**What remains unexplained.** Phrasing explains roughly half to three quarters of the 31-point gap;
`~8–16` points do not. Most plausible residuals: genuinely denser held-out queries, or a *partial*
infrastructure failure on their host. A *total* infrastructure failure is arithmetically excluded.

### 2. The score is gated by one number

FPR is the fraction of queries passing *every* constraint, and the three preference terms are zeroed on
any query that fails. **One FPR point is worth about `0.85` overall; perfecting all three preference
terms at today's FPR is worth `~1.5` in total.** Preference work is not where the points are.

### 3. The current fixed search saturates; deeper search is not yet tested

Per-query telemetry from a 1 h diagnostic (`n=42`, triage, `25 s`/query):

| | accepted (`n=15`) | failed (`n=27`) |
| --- | --- | --- |
| `stop_reason` | `accepted_stop` ×15 | **`budget` ×26** |
| restarts used, median | **0** | **39** |
| solve seconds, median | **3.2** | **22.7** of `~23 s` |

A query that gets solved in this short regime is solved by the **first constructed plan**. A query that
does not spends its whole slice on ~39 randomized restarts. There is no measured middle population that
"just needed a little more time" in this regime.
Giving the failures `2.5×` the budget raised restarts to a median of 166 and flipped **one query in
68**; the 5 h reference run agrees (repair improved `2 of 66`, polish `11 of 34`), which is why
`1/3/5 h` score `57.35 / 57.86 / 57.99`.

**What that does and does not establish.** A restart resamples one parameter tuple (`_random_params`):
attraction offset, hotel index, attractions per day, visit minutes, a forced transport mode, optional
intercity preferences, a meal offset. Extra budget, a raised `TPC_MAX_RESTARTS`, more workers,
within-query parallelism and a fresh seed salt all draw more tuples from that same small representation.
That explains why a new move beat more draws. It does **not** prove mathematical infeasibility.

**R24's sharper scope correction (2026-08-07).** Raising the outer per-query budget from `300 s` to
`900 s` produced byte-identical plans because both arms stopped naturally near `107 s`. The reason is
visible in code: `TPC_MAX_RESTARTS` stays fixed at `400`, so both arms replay the same deterministic
400-restart sequence, while CP-SAT still gets at most `30 s` by default (`min(30, remaining / 2)`).
An unchanged one-hour run would therefore also stop early; it would not perform one hour of search.
R24 rejects "raise only the outer timeout." It does **not** test `4000` restarts, a longer CP-SAT
slice, fresh configurations, or a validator-guided portfolio. CP-SAT also selects sets of POIs,
hotels and transport rather than the exact timed itinerary; greedy reconstruction can reject a
feasible assignment, so a timeout or `INFEASIBLE` status there is not a proof about the full problem.

The discriminating measurement was
[R25](tpc_phase2_eval.md#r25--separate-the-cp-restart-and-outer-budget-limits): vary the CP limit and
restart cap independently on R24's failing subset. **Closed 2026-08-07**: neither `TPC_CP_TIME_LIMIT_SEC=300`
nor `TPC_MAX_RESTARTS=4000` (both 10x default) flips a query; the honest statement is now "the fixed
30-second-CP/400-restart configuration saturates the reachable improvements for the clause families these
queries fail on, dominated by timed-window placement, and 10x deeper or more diverse search of the same
move does not reach further."

**So the idle time is usable capacity, not evidence of score headroom by itself.** Part of it is the
scheduler idling on queries it wrongly believes are done (§1), part is the P4 cap defect, and part is
the internal 400-restart/30-second-CP boundary R24 never changed. Phase 1 used comparable capacity by
trying different seeds, configurations, targeted repairs and densification behind monotonic merge;
the Phase 2 analogue is a keep-best portfolio, not one unchanged hour-long call.

### 4. One constraint family accounted for almost all of the in-distribution loss

`timed_visit_named_poi` — "be at *this named POI* within *this time window*" — was the *sole* logical
blocker in `45 of 61` failing solver-only queries. The sampler had no parameter that pins one activity
inside a window and reflows the rest of the day. Adding exactly that move at identical budget, restart
count and seed moved FPR `32.5 → 42.5`; the full run measured `+11.0`. **The gap was representation,
not search time** — the worked example for the whole family, and the reason §3's flat budget curve is
not a dead end but a signpost.

Residual after the three window moves landed (`familiar_100_val`, `n=80`): `43 of 80` queries still
fail a timed-visit clause, `33` with nothing else failing. By shape: forward-shift `21`, absent POI
`15`, shorten `11`, backward-shift `10`. Already-passed-window backward-shift (`8` sole-blocker
queries) needs **cross-day relocation** and remains unscoped; a coarse check says `22 of 25`
absent/backward instances have some day whose free span contains the window, so the headroom is real,
but a duplicate visit trips the repeated-attraction rule, so relocation means move-then-delete.
Instrument: `scripts/phase2_timed_window_shapes.py`.

### 5. Parsing was not the bottleneck — on familiar-100

Solver-only FPR (`23.75`) sits *below* end-to-end FPR (`25.00`) on the last rehearsal: feeding the
solver perfect constraints did not improve it. Parser F1 against oracle was `0.955`–`0.995` with zero
missing families. **Both statements are true and both are scoped to familiar-100.** On free prose
recall falls to `0.30`. This is the single clearest case in the project of a component's measured
quality being mistaken for a property of the component.

### 6. We make a third of free-prose queries infeasible ourselves

**New 2026-08-07, and it is the largest single mechanically-certain finding in this document.**
Instrument: `scripts/phase2_unsatisfiable_names_probe.py` (static, no solve, no LLM).

The solver can only place POIs that exist in the target city's catalog. So a `required_attractions` /
`required_restaurants` / `required_hotels` / `position_presence` value that resolves to **nothing** in
that catalog is not a constraint we might fail — it is a constraint with **no feasible point**. Every
query carrying one can never be accepted, at any budget, under any search; it scores `FPR = 0` and
zero on all three preference terms by construction, and the scheduler leaves it in the repair queue
paying for it.

| set | n | queries with ≥1 unsatisfiable required name | with `TPC_P2_ENTITY_RESOLUTION=1` |
| --- | --- | --- | --- |
| familiar-100 (control) | 100 | `7` (`7 %`) | **`0`** |
| `local_released_150` | 150 | `24` (`16 %`) | `21` (`14 %`) |
| HF `easy` | 300 | **`127` (`42 %`)** | `127` — unchanged |
| HF `medium` | 150 | **`53` (`35 %`)** | `53` — unchanged |
| HF `human` | 154 | **`36` (`23 %`)** | `36` — unchanged |
| HF `preference_base50` | 50 | **`25` (`50 %`)** | `25` — unchanged |

The values are not near-misses. `parse_required_attractions` matches
`(?:want|wish|hope)\s+to\s+visit\s+(.+?)` and filters the capture through a **stoplist of type
words** only, so on free prose it returns whole sentences: `"Nanjing for a day by myself with a
budget of 1800 RMB"`, `"book two twin rooms"`, `"relax"`, `"Guangzhou for a few days to see the
rivers"`. `chinatravel/agent/phase2/normalize.py`'s `_resolve_one_required_name` ends in
`{"kind": "keep", "value": cleaned}` — an unresolvable name is **kept verbatim as a hard
constraint** — and entity resolution is off on the shipped path anyway, so nothing filters it.

**Why this fits the held-out breakdown better than any other single cause.** `EPR-micro 99.48`: an
invented *constraint* never becomes an invented *fact*, so grounding is untouched — exactly what the
leaderboard shows. `C-LPR 55.20`: the query still emits a plan and still earns its other clauses.
`FPR 0.0000`: a third of the split is structurally excluded from passing. No assumption about clause
density or independence is needed.

**And the fix has an unusually clean dominance argument.** Dropping an unsatisfiable required name is
never worse than keeping it. If the oracle never had that family (the majority — `spurious` on
`required_attractions` is `105` on `hf_easy` alone), dropping it is a pure gain: the query becomes
acceptable and its FPR and preference terms unlock. If the oracle *did* have it and our value is
garbage, we were failing that clause either way, so dropping costs nothing and frees the search to
satisfy the rest. It cannot lower C-LPR. See [P22](#p22--drop-provably-unsatisfiable-required-name-constraints).

**A smaller sibling, in the category-valued families** (measured 2026-08-07 with the same probe's
`--types` arm, prompted by [R26](tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets)'s open
question). A `required_attraction_types` / `cuisine_preference` / `required_hotel_*_types` value that
matches no row of the target city's vocabulary is unsatisfiable for the same reason: `0 %` of
familiar-100, `3 %` of `local_released_150`, `2 / 5 / 1 / 0 %` of the four HF sets. An order of
magnitude smaller than the name half, dominated by `required_hotel_all_types` (`"King-size bed"`,
`"Sea view"` — hotel features outside the closed vocabulary), and notable for one case that is *not* a
parsing error at all: `required_attraction_types: "Cultural Landscape"` is canonical but absent from
**Suzhou's and Hangzhou's** catalogs, so the check has to be city-scoped. Folded into P22's scope.

**Related but separate: constraints we invent that *are* satisfiable.** Over-extraction is not
limited to unresolvable values. From the committed
[post-P15 probe](../results/phase2_baselines/screens/20260807_generalization_post_p15/probe.json),
free-prose `spurious` counts: `required_attractions` `105/25/25/20` across
`easy/medium/human/preference_base50`, `intercity_mode` `49/52/5/11` against **zero** oracle
instances on all four sets, `required_hotels` `14/35/6/0`. The `intercity_mode` cause is one line — a
bare `(?:take|by|use)\s+(?:a\s+|the\s+)?(train|airplane|plane|flight)` fallback that pins **both**
legs whenever free prose mentions a mode in passing. A wrongly pinned intercity mode fixes arrival
and departure times, which is the same axis
[R25](tpc_phase2_eval.md#r25--separate-the-cp-restart-and-outer-budget-limits) found to be the
recurring blocker on failing queries, so this is a plausible mechanism for *creating* timed-window
infeasibility. That is [P24](#p24--stop-inventing-satisfiable-but-unrequested-constraints).

## Work items

Ranked. `P0`…`P25` are stable identifiers. Nothing below is on a critical path to an upload, because
[there is no scheduled upload](tpc_phase2_eval.md#submission-policy-owners-instruction-2026-08-06);
they are ranked by expected effect on the held-out score.

**The ranking changed again on 2026-08-07 (second revision), when the unsatisfiable-name measurement
landed.** The 2026-08-07 leaderboard breakdown had already established that the score is gated by a
*threshold* in the per-clause pass rate rather than by a linear clause count (see
[where we are](#where-we-are), reading 3). Three implications now, in order:

- **Removing a self-inflicted blocker outranks adding coverage.** A query with an unsatisfiable
  parsed constraint contributes exactly zero to `0.55` of the total weight and cannot be rescued by
  any amount of extraction or search. `23–50 %` of free-prose queries are in that state
  ([§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves)). P22 and P24 are these.
- **Coverage items compound**, because they raise C-LPR at weight `0.25` *and*, past `p ≈ 0.8`, unlock
  the `0.55` of weight that is currently dead. P15, P16 and P20 are coverage items.
- **Anything that cannot plausibly move `p` by a lot is worth close to nothing right now.** That
  demotes P17(b): it buys preference points, and every preference term is `0` while FPR is `0`.
  **This bullet previously demoted P5 and P4 for the same reason, which was wrong** — both target
  failing queries and therefore FPR, not preferences. See [P4](#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass)
  for the corrected reasoning; [P5](#p5--spend-the-idle-envelope-on-fresh-seeds) has since been closed
  by [R25](tpc_phase2_eval.md#r25--separate-the-cp-restart-and-outer-budget-limits), which tested the
  ordering argument directly rather than by inference.

**And one process fact, now resolved.** A whole-run row on the current `main` was missing (R19
predated P15, P16, P19, P20 and P18); [R28](tpc_phase2_eval.md#r28--a-whole-run-row-on-the-current-main)
closed that gap 2026-08-07 (`20260807T152009Z`, `git_sha aed4363e`, byte-identical to R19). "Promote"
is available again — gate any candidate against R28.

| | Item | Effort | Expected | Status |
| --- | --- | --- | --- | --- |
| **P26** | [Free-prose intercity transport mode](#p26--free-prose-intercity-transport-mode) | 2 h | the largest single remaining ASCII-literal recall gap: `33/85` intercity clauses missed on `hf_medium`, `27/32` on `hf_human`, `0` on familiar-100 | **landed 2026-08-08, unflagged (additive alternatives, floor-gated); static GREEN — `hf_medium` gaps `131 → 111`, `hf_human` `109 → 85`, `hf_easy` `99 → 97`, precision flat or up, familiar-100 and `local_released_150` byte-identical; e2e gate is [R34](tpc_phase2_eval.md#r34--does-the-intercity-recall-fix-convert)** |
| **P22** | [Drop provably unsatisfiable required-name constraints](#p22--drop-provably-unsatisfiable-required-name-constraints) | half day | un-pins the `23–50 %` of free-prose queries that currently cannot pass at any budget; the only item with a dominance argument rather than an estimate | **landed 2026-08-07, library default off; [R30](tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result) closed 2026-08-07 with a negative e2e result (0/103 flip to passing, 2 regress) — stays default-off. Salvage-before-drop follow-up landed 2026-08-08 (`_salvage_catalog_name`, static only): recovers `25–33 %` of what would otherwise be a full drop on every released/HF set (`100 %` on familiar-100), verified against R30's exact loss; e2e re-confirmation is an Evaluation-workstream job, not yet run** |
| **P21** | [Promote deterministic entity resolution](#p21--promote-deterministic-entity-resolution) | doc/bookkeeping only, no behavioral code change needed | already-landed flag, never measured alone: familiar-100 parse F1 `0.9552 → 0.9949`, `local_released_150` `0.8222 → 0.8451`, zero LLM calls; also takes familiar-100's unsatisfiable-name count `7 → 0` | **[R29 closed GREEN 2026-08-07](tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end); found the flag was already harness-default-on since `b53a0747` (predates R28/`v1`) — remaining work is documenting that explicitly, not flipping a switch** |
| **P24** | [Stop inventing satisfiable but unrequested constraints](#p24--stop-inventing-satisfiable-but-unrequested-constraints) | half day | Diagnosis revised 2026-08-07: the `intercity_mode` half was a measurement bug, not invention (fixed, spurious `172→0`); `required_attractions`/`required_hotels` were real (fixed, spurious `310→25` / `55→6`, 92%/89%, matched unchanged) | **landed 2026-08-07 (code + tests + two static screens GREEN, `pytest tests` green); e2e effect needs its own R-numbered arm, not yet run** |
| **P23** | [Make the free-prose register scoreable](#p23--make-the-free-prose-register-scoreable) | half day | lifts a `38.67–46.0` FPR ceiling off every free-prose measurement we make, and makes P20's `required_attraction_types` half gateable at volume (R26 found exactly `1` locally-measurable clause; translation unlocks `~380`) | **landed 2026-08-08 (static build-and-verify only — `scripts/materialize_hf_split.py --translate-oracle-literals`, `pytest tests` green, 14 new tests); no solve run yet, that is [R31](tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate), now unblocked** |
| **P25** | [Cross-day timed-window relocation](#p25--cross-day-timed-window-relocation) | 1–2 days | the one solver move R25 identified as the binding blocker on failing queries, and the only unbuilt member of the family that produced our single largest gain (`+11.0` FPR) | **landed 2026-08-08, library default off; quick A/B screen GREEN LIGHT (familiar_100_val n=40: FPR `40.0 → 45.0`, `+2/40` flips, `0` regressions) — pinned end-to-end gate is the next, Evaluation-workstream step** |
| **P18** | [Make phrasing robustness a gate](#p18--make-phrasing-robustness-a-gate) | landed | prevents the recurrence of the failure that cost this cycle | **landed 2026-08-07 (`dfdace2a`); gates parse gaps only — two precision conditions still open, see below** |
| **P6** | [Validator-in-loop Qwen repair](#p6--validator-in-loop-qwen-repair) | 1 day spike | tests the successful Kiro/Claude interaction shape without allowing generated facts or unchecked plans | **closed 2026-08-08 — built and screened, R27 RED (0/10 accepted flips caused by the loop); stays library default off, per the roadmap's own falsification bar** |
| **P20** | [Close the two dominant family-recall gaps](#p20--close-the-two-dominant-family-recall-gaps) | landed | P19 attributed `202` released clause misses to `required_attraction_types` and `cuisine_preference`, over 2x the next family | **landed 2026-08-07 (`f413eb2a`); R22 GREEN; [R26 GREEN](tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets) 2026-08-07, and the whole-run row it authorized is done — [R28](tpc_phase2_eval.md#r28--a-whole-run-row-on-the-current-main), byte-identical to R19** |
| **P16** | [Ground LLM-extracted values into the closed vocabulary](#p16--ground-llm-extracted-values-into-the-closed-vocabulary) | landed | detects unfamiliar requirements, but current-tree `matched 311 < 320` deterministic and `hf_medium` e2e is flat | **landed, library default off; not promoted** |
| **P15** | [Finish phrasing-robust extraction](#p15--finish-phrasing-robust-extraction) | half day | the measured residual beyond budget/room-type; compounds through the FPR threshold | **landed (partial) 2026-08-07; residual re-scoped, see below** |
| P4 | [Fix the 300 s per-query cap](#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass) | half day | correctness fix (currently disables the intended `900 s` cap); R25 found it will not itself buy flips | **landed 2026-08-08, correctness-only, no score effect claimed (R24 already measured 0 flips at 900s outer cap); no `full_runs/` row yet — Evaluation-workstream job** |
| P5 | [Spend the idle envelope on fresh seeds](#p5--spend-the-idle-envelope-on-fresh-seeds) | half day | R25's own gate ("a positive R25 arm before default-on implementation") was not met — `0/10` flips at 10x restarts; the recurring blocker (timed-window placement) does not respond to search volume | **not implemented; R25 removed the case for default-on** |
| P17 | [Stop trusting our own "satisfied" verdict](#p17--stop-trusting-our-own-satisfied-verdict) | half day (a), 2 h (b) | (a) re-aims the repair queue, worth more under large parse gaps; (b) idle envelope, worth ~0 until FPR > 0 | **(a) landed 2026-08-08, library default off; whole-run screen NEUTRAL by construction (0 fires on the only registers `--mode whole-run` can reach) -- benefit-on-a-firing-register is a residual. (b) still parked** |
| **P19** | [Find the unidentified half of the gap](#p19--find-the-unidentified-half-of-the-gap) | 1 h | produced the density and family ranking that defines P20 | **closed 2026-08-07** |
| ~~P1~~ | ~~`timed_visit_named_poi` window-aware move~~ (`TPC_WINDOW_ANCHOR`) | — | **promoted 2026-08-05**: `overall +5.83`, `FPR +11.0` | landed |
| ~~P8/P9~~ | ~~Window push / absent-POI insert~~ | — | **promoted 2026-08-06** (R14 GREEN, `+0.5471`); fire rarely | landed |
| ~~P10~~ | ~~Scheduler self-scoring uses the solver's exact variants~~ | — | **landed 2026-08-06**, default-on; R16 GREEN | landed |
| ~~P12~~ | ~~Close P10's false-positive half~~ | — | **landed 2026-08-06**; R17 GREEN on the shipped path | landed |
| ~~P13~~ | ~~Empty parent parse means the same on both sides~~ | — | **landed 2026-08-06**; trigger fires on `0/100`, independently confirmed on a full run in [R19](tpc_phase2_eval.md#the-closed-queue-r1r19) | landed |
| ~~P2~~ | ~~Per-attempt telemetry ledger~~ | — | **landed 2026-08-06**; `attempts.jsonl`, aggregated into the row | landed |
| ~~P3~~ | ~~Commonsense-valid emission~~ | — | **closed 2026-08-06**, re-screened, no code change needed | closed |
| ~~P11~~ | ~~Whole-run mode for the pre-gate screen~~ | — | **landed 2026-08-06**, tooling only | landed |
| ~~P14~~ | ~~Promote P8/P9 to harness defaults~~ | — | **landed 2026-08-06** | landed |
| ~~P0/P7~~ | ~~Reproducible restart seed; worker count from affinity~~ | — | **landed 2026-08-05** | landed |

### P27 — the remaining attraction-type residual is interpretive, not lexical *(investigated and closed 2026-08-09)*

**Read this before adding another attraction-type pattern.** After P26, the largest remaining
parse-gap family on free prose is `attraction_type` — `37` clauses on `hf_human`, `12` on `hf_medium`.
It looks like the same shape P20 and P26 fixed. It is not, and the difference is worth recording so the
next agent does not spend a night on it.

**What the residual actually consists of** (read off the uncovered queries, not guessed): *"experience
some of the historical areas"*, *"explore the local history and culture"*, *"they are more interested in
history and culture"*, *"attractions suitable for children"*, *"see the rivers and relax… focusing
mainly on wellness"*, *"Going on a date, please recommend an itinerary"*, *"experience the atmosphere of
prestigious universities"*. These are not lexical variants of a category name; they are inferences from
an interest to a category.

**And the oracle's own labeling of those phrasings is inconsistent**, which caps what any deterministic
mapping can score. Measured across all five sets by scanning oracle `attraction_type_set` literals for
each phrase (`/tmp` probe, reproducible from the description here — the phrase list is in this entry):

| phrase in the query text | oracle's required type(s), by frequency |
| --- | --- |
| `historical and cultural` / `cultural and historical` | `人文景观` ×5, `{博物馆/纪念馆, 历史古迹}` ×3, `历史古迹` ×2, `{大学校园, 文化旅游区}` ×1 |
| `history and culture` (any order) | `人文景观` ×5, `历史古迹` ×5, `{博物馆/纪念馆, 历史古迹}` ×3, `{大学校园, 文化旅游区}` ×1 |
| `I/we like|love|prefer|enjoy …` | **no attraction-type clause at all ×15**, then `人文景观` ×2, `自然风光` ×2, three others ×1 |
| `universit(y\|ies)` | no clause ×23, `大学校园` ×10 (P20 already measured and rejected the bare form) |
| `historical area`, `suitable for children`, `going on a date`, `food court` | one instance each |

So the modal answer for the biggest phrase class is a coin flip between two canonical values, and the
most inviting new trigger (`I like X`) has **no** type clause in two thirds of its occurrences. P20's
own rule — *drop rather than guess, because a dropped extraction stays `missing` (no regression) while a
wrong value risks making a satisfiable query infeasible* — decides this: do not add these mappings.

**One addition survived the measurement, and it is the only thing P27 landed.** Adding
`like|love|prefer|keen on|focus on|experience` to the free-prose *trigger* set — no new value
mappings, so it can only fire the existing table — moves `hf_human` parse gaps `85 → 81` and costs
`0.008` of parse precision there. Because the static columns of the other four sets did not move, the
full parsed **solver dicts** were diffed query by query rather than trusted:
**`4` of `854` queries change, all on `hf_human`**; familiar-100, `local_released_150`, `hf_medium` and
`hf_easy` are byte-identical. End-to-end on translated `hf_human`
([R35](tpc_phase2_eval.md#r35--the-preference-verb-trigger-arm), n=154): FPR `51.9481 → 53.2468`
(two more queries fully pass), C-LPR `84.8617 → 85.0073`, overall `67.8013 → 68.5027`, `2` clauses
fail→pass against `1` pass→fail. GREEN, and small — kept, with the caveat recorded in the screen that
one of the four is a shared-noun OR (`"cultural or natural attractions"`) whose second arm P20's OR
guard cannot see.

**What this implies for the system, and it is in the report.** This residual is the boundary where a
deterministic extractor stops being the right tool: recognizing that *"going on a date"* implies
`约会圣地` is exactly the inference an LLM does well, provided its output is then resolved against the
closed category vocabulary rather than trusted as text. That is [P16](#p16--ground-llm-extracted-values-into-the-closed-vocabulary)'s
grounded fill-only path, still library-default-off because it has never beaten the deterministic floor
on a measured register — and this entry is the sharpest available argument for why that path is worth
finishing rather than dropping.

### P26 — free-prose intercity transport mode

**Landed 2026-08-08.** The generalization probe's own residual table named this: after the
2026-08-06 phrasing fix and P20, the largest remaining *ASCII-literal* (i.e. actually fixable under
`--lang en`) parse gap on free prose was `intercity_transport` — `33` of `85` oracle clauses missed on
`hf_medium`, `27` of `32` on `hf_human`, `2` on `hf_easy`, **`0` on familiar-100**. The 2026-08-08
board makes this the highest-value shape available: it is pure C-LPR, which is where `99.5 %` of the
gap to first place lives.

**Mechanism.** `parse_intercity_mode` recognized the family only through the familiar template's
literal word `destination`, or through `take|by|use` immediately followed by a *bare* mode noun. Free
prose states the same requirement as a verb (`"we have chosen to fly"`, `"we will be flying"`,
`"planning to fly from Guangzhou to Beijing"`) or with a qualifier between the preposition and the
noun (`"traveling by high-speed train (G)"`, `"round trip by high-speed train"`), and neither reaches
those patterns.

**What landed.** Two additions, both after every existing pattern so nothing already working can
change:

1. an **undirected free-prose fallback** that fires only when no directional pattern matched, and sets
   *both* legs — matching the oracle clause shape for this register, which constrains the whole
   `intercity_transport_set` rather than a single endpoint;
2. the missing **affirmative `fly to the destination`** mirror of the long-standing negated pattern,
   so a genuinely mixed request (`"fly to the destination and take the train back"`) records both legs
   instead of only the return one.

**Three precision guards, because a spurious intercity mode is not free** — it pins both endpoint legs
and can invalidate an otherwise-passing plan, which is [P24](#p24--stop-inventing-satisfiable-but-unrequested-constraints)'s
lesson: station/airport *place* nouns are stripped before matching (`"near the train station"` is not a
mode statement); every alternative requires an intent context (a planning verb, a preposition of
travel, or an explicit round-trip phrase); and a loose mention of the *other* mode vetoes the match, so
`"still deciding whether to fly or take the high-speed train"` yields nothing rather than a guess.

**Static result** (`scripts/phase2_generalization_probe.py`, same command the P18 gate runs):

| set | parse-gap clauses | parse precision | parse recall |
| --- | --- | --- | --- |
| familiar_100 (control) | `0 → 0` | `0.9552 → 0.9552` | `0.9552 → 0.9552` |
| `local_released_150` | `5 → 5` | `0.8222 → 0.8222` | `0.8243 → 0.8243` |
| `hf_easy` | `99 → 97` | `0.8528 → 0.8528` | `0.7122 → 0.7156` |
| `hf_medium` | `131 → 111` | `0.8924 → **0.8939**` | `0.7418 → 0.7717` |
| `hf_human` | `109 → 85` | `0.8363 → 0.8358` | `0.6364 → 0.6868` |

Recall up on all three free-prose sets, precision flat or *up*, and the two template registers
byte-identical. The [P18 phrasing gate](#p18--make-phrasing-robustness-a-gate) passes and its floor is
ratcheted down to the new counts. Tests: `tests/phase2/test_parser_phrasing_generalization.py` §5 — 14
extraction cases, 6 no-spurious cases, the contradiction veto, the directional-wins and
negation-wins orderings, a solver-dict end-to-end case, and a familiar-100 byte-identity floor against
a verbatim copy of the pre-fix extractor.

**Not claimed here:** an end-to-end score. That is [R34](tpc_phase2_eval.md#r34--does-the-intercity-recall-fix-convert).

### P22 — drop provably unsatisfiable required-name constraints

**Landed 2026-08-07.** Diagnosis and measurement:
[§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves). This was the only open item
whose value rested on a dominance argument rather than an estimate.

**What landed.** `TPC_P2_DROP_UNSATISFIABLE_NAMES` (`Flags.drop_unsatisfiable_names`, library
default off) on both halves in one commit, screened separately as the roadmap asked:
`_resolve_one_required_name`'s terminal branch now returns `{"kind": "drop"}` when the flag is on
(required-POI names), and `resolve_entities` filters the four category-valued families
(`required_attraction_types` / `cuisine_preference` / `required_hotel_all_types` /
`required_hotel_any_types`) against each target city's own vocabulary. The flag forces
`ir_to_solver_variants` to run the entity-resolution catalog lookup even when
`TPC_P2_ENTITY_RESOLUTION` is off (composes with [P21](#p21--promote-deterministic-entity-resolution)
when it promotes, per the design point below, but does not require it). A second code path,
`_resolve_generic_location` (directly-parsed `position_presence` entries, as opposed to ones
entity resolution reroutes there from a category misroute), needed its own drop branch too — the
static screen caught this residual before the fix; see the screen README for the failure and fix.
Static screen (definitional; the probe uses the same matchers the drop rule and acceptance gate
themselves use):
[`results/phase2_baselines/screens/20260807_p22_unsatisfiable_names`](../results/phase2_baselines/screens/20260807_p22_unsatisfiable_names/README.md)
— **GREEN**: both `familiar_100 (control)` and `local_released_150` reach `0` unsatisfiable-constraint
queries in both arms (required-name and category-value), `Flags.from_env({})` stays byte-identical,
and `pytest tests` is green with no pre-existing test edited. This static check only proved the *drop*
removes what the probe measures, not that it flips any query to passing end-to-end.

**R30 (closed 2026-08-07) answered the e2e question, and it is a negative result: the flag stays
default-off.** Paired A/B on the 103 queries the probe flags (fresh re-run on current `main`, which
also carries [P24](#p24--stop-inventing-satisfiable-but-unrequested-constraints) and therefore a
smaller target set than the static screen above recorded): **0/103 flip to fully passing, and
`local_released_150` loses 2 (0 gained)**. One loss is a genuine gap in the drop rule itself — the
garbage capture contained a real, salvageable POI name as its prefix, and dropping the whole value
threw that away; the other is search perturbation (removing the constraint changed what the
solver's fixed budget explored, unrelated to the dropped value's content). HF free prose stayed
FPR-flat (predetermined by the CJK-oracle ceiling, not informative) but gained 2 satisfied clauses
each on `hf_easy`/`hf_medium` with none lost. The flag's real, measured effect is solve time
(`5.8–6.1×` faster convergence on three HF sets when the flag drops what the solver could never
satisfy anyway) — real and large, but this per-query-budget screen can't show whether the real
envelope scheduler (`sweeps.py`) turns that into more passes elsewhere; that needs a `full_runs/`
row, not a screen. Full causal analysis:
[screen README](../results/phase2_baselines/screens/20260807_r30_unsatisfiable_names_e2e/README.md).
**Follow-up landed 2026-08-08 (static half):** before falling back to a full drop, try to salvage a
real catalog POI name that is a prefix/cleanly-separable substring of an otherwise-unmatched capture,
using the same matcher the solver's own constraint-application step already relies on more leniently
than `_exact_catalog_match`/`_match_catalog_name`. `_salvage_catalog_name`
(`chinatravel/agent/phase2/normalize.py`) does exactly this: it reuses
`TPCAgent._match_constraint_text`'s own logic (normalized `c == q or q in c or c in q`, no coverage
floor), guarded by a minimum length and an ambiguous-tie refusal. Verified against the exact R30 loss
(`20250324075652034944`: `{"kind": "drop"}` → `{"kind": "name", "value": "Xixi Paradise Commercial
Street"}`), and measured across every released/HF set: recovers `25–33 %` of what would otherwise be
a full drop (`100 %`, `11/11`, on familiar-100), never on the genuinely-unsatisfiable cases P22
targets. 5 new unit tests, `pytest tests` green (54/54 in `test_entity_resolution.py`), the original
P22 static screen's bar re-confirmed unchanged (every set still `0` in both arms). Full account,
salvage-rate table, and one salvage case checked explicitly against the catalog because it looked
wrong at first glance ("Disneyland" → "Dream World (Shanghai Disneyland Store)", confirmed correct):
[screen README](../results/phase2_baselines/screens/20260808_p22_salvage_before_drop/README.md).
**Not done here:** re-running R30's own e2e A/B to confirm the target uid now passes end-to-end with
no new loss — an Evaluation-workstream job (this box must not run it; see the two-VM rule).

**Two design points that decided the shape of the fix.**

- **The drop rule had to run on the deterministic path, not only when `TPC_P2_ENTITY_RESOLUTION` is
  on** — resolution was skipped entirely on the shipped path, which is why nothing filtered these
  values before. Resolved by composing: `ir_to_solver_variants` now runs the entity-resolution
  catalog lookup whenever `entity_resolution` **or** `drop_unsatisfiable_names` is true, so the
  new flag is reachable standalone and, once [P21](#p21--promote-deterministic-entity-resolution)
  promotes, the two share one code path and can gate as one candidate configuration.
- **Drop the *value*, not the *query*.** A query whose only requirement was unresolvable becomes an
  unconstrained query — correct, since we could not represent what it asked for, and an
  unconstrained plan still earns EPR and any clause it satisfies incidentally. Confirmed **not**
  routed to the empty-plan fallback: the fallback only triggers when the *variants list* is empty,
  never when one variant dict has an empty/missing field, and dropping only ever removes a field
  from within a variant, never the variant itself.

**Downgrade vs. drop, decided:** drop, not downgrade. An unresolvable `required_attractions` value
that contains a type word already reroutes to `required_attraction_types` via the pre-existing
`_match_type_vocab` step (a `{"kind": "type"}` outcome, unaffected by this flag); by the time the
terminal branch is reached the value is genuinely name-shaped garbage (a whole sentence, "book two
twin rooms", etc.), so downgrading it would re-introduce P15's spurious-constraint trap.

**Category-valued families, city-scoped** (from
[R26](tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets)'s open question): the same
no-feasible-point class applies to `required_attraction_types` / `cuisine_preference` /
`required_hotel_all_types` / `required_hotel_any_types` when the value matches no row of the target
city's own vocabulary — an order of magnitude smaller than the name half (`0 %` familiar-100, `3 %`
`local_released_150` pre-fix), dominated by `required_hotel_all_types` (`"King-size bed"`, absent
from every city's `featurehoteltype` column). `required_attraction_types: "Cultural Landscape"` is
the interesting case: canonical and present in Beijing/Shanghai/five other cities, absent from
Suzhou's and Hangzhou's own catalogs specifically — confirmed against the committed CSVs, which is
why the check (`_type_field_vocab` in `normalize.py`) is scoped per city, never pooled globally.
Screened and reported separately from the name half throughout (`--types` on the probe), landed in
the same commit as the roadmap allowed.

**A residual the first pass missed.** The static screen's first `--drop-unsatisfiable-names` run
left `local_released_150` at `1/150`, not `0`: `_resolve_generic_location` — the code path for a
`position_presence` entry the parser extracted *directly*, as opposed to one entity resolution
reroutes there from a category misroute — had no drop branch at all. Fixed by giving it its own
`drop_unresolved` parameter; the four dict-valued callers that share the same function
(`hotel_nearby`, `poi_distance_hotel`, `stay_duration`, `activity_time_windows`) never pass it,
since dropping a nested location there would mean removing a whole constraint object, out of this
item's scope (`NAME_FIELDS` is exactly `required_attractions` / `required_restaurants` /
`required_hotels` / `position_presence`). See the screen README for the full account.

**Bar, met:** `pytest tests` green with no pre-existing test edited; `Flags.from_env({})` byte-
identical (unit test); a resolvable name is never dropped (unit test); every set at `0` in both
arms (required-name and category-value) on the static screen; familiar-100 parse gaps still
`0/1109` (R22, unaffected — the flag is off on the default path the tripwire measures). Screen:
[`results/phase2_baselines/screens/20260807_p22_unsatisfiable_names`](../results/phase2_baselines/screens/20260807_p22_unsatisfiable_names/README.md).
Promotion needs [R30](tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries), a
paired e2e A/B on both registers. **Expect the local free-prose e2e gain to be capped**: `59–61 %`
of HF queries also carry a structurally unpassable CJK oracle clause
([P23](#p23--make-the-free-prose-register-scoreable)), so a query this fix un-pins may still be
unable to pass for an unrelated reason. Read per-query flips and the target subset, not the split
mean.

### P21 — promote deterministic entity resolution *(closed 2026-08-07 — R29 GREEN, doc-framing corrected)*

**Correction found while closing this item.** The paragraph below originally said
`TPC_P2_ENTITY_RESOLUTION` "has been landed and default-off since Phase 2 plan 3" — true only of
`Flags()`/`Flags.from_env({})`, the bare library constructor. The code path every real run takes,
`agent_env/scripts/solve_phase2.py:resolve_llm_client_and_flags()` (called from `run_split`, which
both the CLI and the organizer harness entry point dispatch to), has force-defaulted
`entity_resolution = True` since `b53a0747` (2026-07-13) unless the operator explicitly sets the env
var — the same auto-promotion pattern already used for `disjunction`/`dynamic_budget`. `b53a0747`
predates both R28's `aed4363e` and the `v1` submission build ancestor `be196d00`; R28's own on-disk
telemetry confirms `flags.entity_resolution: true` throughout. **R28's baseline and `v1`'s held-out
score already ran with this flag on.** So "promote" below does not change harness behavior — it
formalizes a default that already silently applies. See
[R29's full writeup](tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end)
and its [screen README](../results/phase2_baselines/screens/20260807_r29_entity_resolution/README.md).

`TPC_P2_ENTITY_RESOLUTION` has been landed and harness-default-on (not library-default-on) since
`b53a0747`, 2026-07-13. **Every measurement
of it ever taken ran it composed with `TPC_P2_LLM_PARSE_MODE=extract_fill` against a live DeepInfra
backend** — all three arms of the
[P16 screen](../results/phase2_baselines/screens/20260807_p16_entity_resolution_probe/) are
`mode: extract_fill`. So its value on the **shipped deterministic path**, which makes zero LLM calls,
had never been read. Isolated with `scripts/phase2_entity_resolution_arms_probe.py` (both arms
deterministic, one flag differing):

| set | n | parse F1 off → on | `matched` | `wrong_value` | `spurious` |
| --- | --- | --- | --- | --- | --- |
| familiar-100 (control) | 100 | `0.9552` → **`0.9949`** | `661 → 688` | `30 → 3` | `0 → 0` |
| `local_released_150` | 150 | `0.8222` → **`0.8451`** | `325 → 335` | `36 → 26` | `40 → 39` |
| HF `easy` | 300 | `0.6891` → `0.6886` | flat | flat | `177 → 179` |
| HF `medium` | 150 | `0.7404` → `0.7384` | flat | flat | `114 → 119` |
| HF `human` / `preference_base50` | 154 / 50 | exactly flat | flat | flat | flat |

It also takes familiar-100's unsatisfiable-name count from `7` to **`0`**
([§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves)), by repairing fragmented real
names (`"Honey Lake 1979 Cultural"` + `"Creative Park"` → one POI).

**Read the two arms honestly.** The gain is concentrated where values are English literals, which is
where value equality is measurable at all; the HF sets are flat because their oracle literals are
Chinese, not because the flag does nothing there ([P23](#p23--make-the-free-prose-register-scoreable)).
The `−0.002` F1 wobble on `hf_easy`/`hf_medium` is `+2`/`+5` `position_presence` clauses from the
category-misrouting reroute firing where the oracle has no such family — the one residual risk, and
small. **This is a static parse-diff and cannot promote anything by itself**: the corrected values
must convert into satisfied clauses end-to-end.

**Bar, met.** [R29](tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end)
ran the paired e2e A/B on familiar-100 *and* free prose: **GREEN** — familiar-100 FPR `45.00 → 50.00`,
`overall_true` `64.83 → 67.53`, two more queries fully pass, zero LLM calls confirmed from telemetry;
`hf_medium` free prose is NEUTRAL (byte-identical plans on all 30 uids, matching this section's own
"HF sets are flat" prediction). But R29 also found the flag was already forced on for every harness
run since `b53a0747` — see the correction at the top of this item. So the action this GREEN actually
licenses is: record `entity_resolution` as an explicit, documented harness default (it already
composes with [P22](#p22--drop-provably-unsatisfiable-required-name-constraints)'s catalog lookup
today, since P22 forces that lookup whenever either flag is true) rather than adding it to
`PROMOTED_SOLVER_FLAGS`/`apply_deterministic_solver_defaults()` as if it were currently off — those
mechanisms don't govern this flag, `resolve_llm_client_and_flags()` does, and it already fires. No new
`full_runs/` row is needed to re-confirm familiar-100 with the flag on (R28 already is that row).

### P24 — stop inventing satisfiable but unrequested constraints

**The other half of the precision story, and unlike P22 these constraints *are* satisfiable — which
is why they are harder to spot and possibly more harmful.** A satisfiable invented constraint does not
make the query infeasible; it makes the solver optimize the wrong problem, and it consumes the
degrees of freedom a real clause needed.

Measured on free prose from the committed
[post-P15 probe](../results/phase2_baselines/screens/20260807_generalization_post_p15/probe.json)
(`spurious`, i.e. we emit the family and the oracle has none for that query):

| family | `easy` | `medium` | `human` | `preference_base50` | oracle instances on those sets |
| --- | --- | --- | --- | --- | --- |
| `intercity_mode` | `49` | `52` | `5` | `11` | **`0` / `0` / `0` / `0`** |
| `required_attractions` | `105` | `25` | `25` | `20` | `30` / `41` / `23` / `5` |
| `required_hotels` | `14` | `35` | `6` | `0` | `30` / `0` / `0` / `1` |

Read the last column carefully, because it separates two different defects — **but read the
correction below before trusting the `intercity_mode` row**, because that "`0` oracle instances"
figure is itself wrong.

**Correction, 2026-08-07: `intercity_mode` was misdiagnosed. It was never invention — it was a
measurement bug in our own oracle-side extractor, and it is landed.** The "`0` oracle instances"
count above was produced by `parser_vs_oracle.py`'s oracle-side reconstruction, which calls
`solver_constraint_variants(..., use_oracle=True)`. That function treats `intercity_mode` as
branch-local and rehydrates it from `hard_logic_py` via `_parse_intercity`
(`chinatravel/agent/tpc_agent/solver_constraints.py`), which recognized only the go/back accessor
shape (`intercity_transport_go`/`intercity_transport_back` — the templated register's shape) and
the `allactivities(plan)[0]['type']` shape. It did **not** recognize the shape the HF free-prose
generator actually uses for this requirement: `intercity_transport_set=set(); ...;
result=({'train'}==intercity_transport_set)`. Measured directly: **100% of a sampled
`intercity_mode`-spurious set on every one of `hf_easy`/`hf_medium`/`hf_human`/
`hf_preference_base50` had exactly this oracle clause** — `genuinely_no_oracle_clause = 0`
everywhere. There was no invented constraint; a correct NL extraction was being scored `spurious`
because the oracle side of the comparison was blind to its own ground truth. The "pinned mode
manufactures timed-window infeasibility" harm story does not apply to this family: the value the
NL fallback produces matches the real oracle requirement in every sampled case, so requiring a
direction/destination cue (the fix this section used to prescribe) would have been a pure recall
loss for no precision gain — confirmed directly: `local_released_150`, the templated register this
change was meant to protect, has `0` queries where `intercity_mode` fires without a direction cue,
so the fallback earns nothing there either. **Fixed** by teaching `_parse_intercity` the
set-equality shape (`setdefault`, so a more specific go/back value already found is never
clobbered): `intercity_mode` spurious `172 → 0` and matched `0 → 172` across the four free-prose
sets, `familiar_100`/`local_released_150` byte-identical. This is not diagnostic-only —
`solver_constraint_variants(..., use_oracle=True)` also backs Phase 1's oracle-guided CP solve
(`tpc_agent.py:360`), so Phase 1 was silently dropping this constraint on the same query shape.
Full writeup, before/after family-stats table, and the P18 floor-file consequence (below):
[screen README](../results/phase2_baselines/screens/20260807_p24_intercity_oracle_fix/README.md).
**Follow-up, not yet built:** fixing the oracle side also revealed a real, previously-invisible
recall gap — phrasing like "we have chosen to fly" / "traveling by high-speed train (G)" that
`parse_intercity_mode` does not catch (`easy +2`, `medium +33`, `human +27` newly-visible parse
gaps). Needs its own item; not folded into this one.

**`required_attractions` and `required_hotels` are real, and both are landed too.** Unlike
`intercity_mode`, both families do exist in the free-prose oracles (see the table's last column),
and their `spurious` counts are genuine over-extraction on the *wrong queries*, confirmed the same
way: `has_marker_clause = 0` on every sampled spurious instance (no
`attraction_name_set`/`accommodation_name_set` clause at all). `required_attractions`, same root
cause as [§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves): a
`(?:want|wish|hope)\s+to\s+visit\s+(.+?)` capture with no delimiter before a trailing
budget/day-count clause swallows the whole tail as one "attraction name" (`"I want to visit
Nanjing for a day by myself with a budget of 1800 RMB"` → captured as an attraction), plus a
smaller shape where the same greedy split lands a restaurant/cuisine clause in
`required_attractions` instead of `required_restaurants`/`cuisine_preference`.
`required_hotels`'s dominant shape is a sibling bug in the `stay at/in X` pattern: `"stay in two
twin rooms"` / `"stay in a room with a double bed"` is a room-type/room-count requirement, not a
hotel name — the existing type-word guard only matched chunks *starting* with `a single/double/
twin`, missing every quantified phrasing. **Fixed** with guards applied per `" and "`-split part
(not the whole captured chunk — an earlier version filtered the whole chunk and was caught in
review before landing: it also discarded genuine trailing attraction references like `"... and
would like to go to the Great Hall of the People"`, turning a `wrong_value` into a `missing`).
Result: `required_attractions` spurious `310 → 25` across the four free-prose sets (92%), `required_
hotels` spurious `55 → 6` (89%), `matched` unchanged (`0` both sides — neither family ever produced
a *correct* value on free prose, only invented on queries with no such requirement) and
familiar-100/local_released_150 control byte-identical. Overall parse precision rose on every
free-prose set (`easy 0.7433 → 0.8528`, `medium 0.7929 → 0.8924`, `human 0.786 → 0.8363`,
`preference_base50 0.735 → 0.865`). Full before/after tables:
[screen README](../results/phase2_baselines/screens/20260807_p24_attractions_hotels_precision/README.md).
**Residual, not this item:** capture fragments that fuzzy-match a real POI closely enough to pass
the capitalization guard while still being wrong (the `"Art Museum 2"` case) need catalog
fuzzy-matching (the entity-resolution layer) to close, not another lexical rule.

**Bar.** One family per commit — landed as two: intercity oracle-side fix, then the attractions/
hotels precision guards. Target family's `spurious` falling on at least two free-prose sets with
`matched` not falling on any set, familiar-100 control byte-identical — met by all three families.
**The R22 "no free-prose set's gaps rising" clause is retracted as stated** — the `intercity_mode`
fix proves it was unmeetable by construction whenever a fix corrects the *oracle* side, and the
attractions/hotels fix shows the same holds for a pure NL-side precision fix: `clause_is_covered()`
tests family presence, not value correctness, so a query whose garbage capture used to count as
"covered" correctly loses that credit once the garbage is gone. State the `spurious`/`missing`/
`wrong_value` deltas per set explicitly instead, and treat any resulting P18 floor rise as
information to justify in the floor file's `_meta`, not an automatic blocker — both screen READMEs
above show how that was handled (`easy 97→99`, `medium 78→131`, `human 81→109`, unchanged
elsewhere). Then
[R30](tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries) or its own e2e arm; a
precision fix whose e2e effect is unmeasured stays default-off — **both P24 commits are library
default already** (`parse_constraints.py`/`solver_constraints.py` have no flag gate; they are the
one deterministic path), so "default-off" here means the roadmap does not yet claim an e2e score
change from them, not that a flag needs flipping.

### P23 — make the free-prose register scoreable

**Landed 2026-08-08 — the static half.** The zh→en map (`build_map`) already existed in
`scripts/phase2_oracle_literal_translation.py`; what landed now is the rewrite it enables:
`translate_clause` / `translate_hard_logic` in that same module, wired into
`scripts/materialize_hf_split.py` as `--translate-oracle-literals`. Full-split dry run: `331` of
`654` free-prose queries across the four HF sets get at least one `hard_logic_py` clause translated
(`388` clauses total), `66` still carry a residual unmapped literal (reported per-uid, never
approximated) — dominated by restaurant/hotel branch-name fragments (`前门店`, "...branch") and
generic-location words with no catalog row (`河边`, "riverside"), exactly the two shapes this section
predicted below. The map reproduces the roadmap's own cited `11957` entries byte-for-byte. Output is
evaluation-only and structurally cannot ship: `--translate-oracle-literals` requires the `_en_oracle`
name suffix (raises otherwise) and that suffix is gitignored. Full account, per-split tables, and the
"read the two measurement methods together" caveat:
[screen README](../results/phase2_baselines/screens/20260808_p23_oracle_literal_translation/README.md).
**Not done here, and it is the next step**: no solve was run, so there is still no free-prose FPR/C-LPR
number scored against the lifted cap — that is
[R31](tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate), unblocked now, an
Evaluation-workstream job (this box must not run it — see the two-VM rule).

**A measurement fix, and it is the reason several of the items above cannot currently be gated.**
Instrument: `scripts/phase2_oracle_literal_translation.py`.

The four HF splits are our only free-prose register — the one the held-out set most resembles. Their
`nature_language_en` is English; their `hard_logic_py` literals are **native Chinese**, and upstream
never translated them. Scored under `--lang en` the plan's own facts come from
`chinatravel/environment/database_en/`, so a clause like `'博物馆' in attraction_type(x)` is
**structurally unsatisfiable whatever we do**. Measured:

| HF split | n | oracle clauses | unsatisfiable under `en` | of those, mappable | queries blocked | **FPR ceiling** | C-LPR ceiling |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `easy` | 300 | 1579 | `180` | `135` | `180` | **`40.00`** | `88.60` |
| `medium` | 150 | 1264 | `126` | `125` | `92` | **`38.67`** | `90.03` |
| `human` | 154 | 687 | `117` | `105` | `91` | **`40.91`** | `82.97` |
| `preference_base50` | 50 | 260 | `27` | `19` | `27` | **`46.00`** | `89.62` |

**None of those clauses is negated**, so none is trivially true; the cap is real in one direction
only. Every free-prose FPR in this repository was read against `100` and should have been read against
`~39`.

**The fix is derivable from the shipped data, not translated by a model.** `database/` and
`database_en/` are **row-parallel** — identical row counts, same order, verified per file — so a
zh→en value map falls straight out of them. After `normalize_concept_value` canonicalizes the English
casing variants the map is **1:1** with zero ambiguity: 14 attraction types, 43 cuisines, 74 hotel
features, 11,810 POI names, `11957` entries total. The builder raises rather than guessing if that
ever stops holding.

**What to build.** Extend `scripts/materialize_hf_split.py` with an opt-in
`--translate-oracle-literals` pass that rewrites the materialized split's `hard_logic_py` literals
through the verified map, emitting a report of what it changed and what it could not. `85 %` of the
blocking clauses map as-is; the residual is POI-name *fragments* (branch suffixes like `前门店`,
"Qianmen branch") and generic locations (`河边`, riverside), which need substring matching rather than
token lookup — leave them, and have the pass report them, rather than approximating.

**Three hard constraints on this item.**

1. **Evaluation-only, and it must never ship.** Same rule as the existing materializer: delete the
   split after scoring. Add it to the archive-verification denylist if one exists.
2. **It does not touch `chinatravel/evaluation/` or `chinatravel/symbol_verification/`.** It rewrites
   *query files in a materialized local split*, so [upstream evaluator parity](../CLAUDE.md#non-negotiable-invariants)
   is untouched. Say so in the screen; a reviewer will ask.
3. **A translated-oracle row is a new register.** It is never comparable with an untranslated HF row.
   Label it distinctly (`hf_medium_en_oracle`) and record the map's entry count in the row.

**Why it is worth half a day.** It is the difference between "P20's `required_attraction_types` half
can only be judged by the held-out set" and "it can be judged this afternoon". It gives us the first
free-prose **FPR** gate the project has ever had — the `0.40`-weight metric — and FPR is what the
whole ranking above is trying to move.

**One qualification, from [R26](tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets).** P20's
own screen reported *zero* locally-measurable English-literal `required_attraction_types` misses; R26
found one (`10 → 11 matched` on `tpc_phase2_test`), a **disjunctive-branch** clause that
`scripts/phase2_family_recall_gap_partition.py` does not enumerate the way
`scripts/parser_vs_oracle.py --per-variant-family-stats` does. So the local measurable universe for
that family is `1`, not `0` — which does not change this item's case (`1` against the `~380` clauses
the translation unlocks) but does mean two of our own instruments disagree about what is measurable.
**Fix the partition script's disjunction handling while you are here**, or at minimum note in the
screen which of the two tools a "zero measurable misses" claim came from; an item scoped by a tool with
a blind spot is how P20 came to ship a fallback it believed it could not measure at all.

### P25 — cross-day timed-window relocation

**Landed 2026-08-08, library default off.** `TPC_WINDOW_RELOCATE_DAY`
(`TPCAgent._relocate_timed_windows_across_days`, wired into `_pack_plan` after
`TPC_WINDOW_INSERT`): finds a `timed_visit_named_poi` activity that is present in the plan for its
required type but does not satisfy its window on the day it currently sits on, and — reusing the
P9 insert helpers (`_insert_activity_before_first`/`_insert_activity`/`_insert_activity_after_last`)
plus a new `_remove_movable_activity` (deletes one movable activity and re-legs its neighbours,
including a legitimate pull-earlier of an overnight accommodation tail) — tries a different day's
slots in one atomic delete+insert trial. Skips any target day that already carries the POI (the
duplicate-avoidance trap below), and gates the combined trial against the plan as it stood at
function entry via the shared `_repair_commit_allowed` two-regime rule. Bounded to one relocation
per call. 11 unit tests (`tests/phase2/test_window_relocate_day.py`) cover the three named shapes
(window already passed with a day that has a free span; no day has a free span; relocation would
duplicate the POI) plus atomicity, absence (P9's job, not this one's), single-day itineraries, and
`_remove_movable_activity`'s neighbour re-legging. `pytest tests` green (full suite).
`CANDIDATE_SOLVER_FLAGS` gains the flag; not in `PROMOTED_SOLVER_FLAGS`.

**Quick A/B screen (`familiar_100_val`, `n=40`, `budget=60s`, stacked on the harness-default window
moves): GREEN LIGHT.** FPR `40.0 → 45.0` (+2/40 queries), `overall_true 62.581 → 65.140`, 0
regressions, 0 new timeouts, gate PASS. Corroborated beyond the aggregate mean, since **all 40
plans differ between arms** (a known search-perturbation confound — the extra per-restart
grounding work shifts which random-restart draws complete within the fixed 60s budget even on
queries where the move never fires, the same effect [R30](tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries-closed-2026-08-07-negative-result)
found for P22): re-evaluating all 40 uids' oracle clauses directly against both arms confirms
exactly 2 fail→pass flips and 0 regressions; `scripts/phase2_timed_window_shapes.py` before/after
shows `forward_shift` instances and queries both drop by exactly 2, matching the flips; and both
flipped plans were spot-checked directly, each showing a genuine cross-day move (an attraction
deleted from one day and inserted into another, inside its window). Full account:
[screen README](../results/phase2_baselines/screens/20260808_p25_window_relocate_day/README.md).
**Not exercised at `n=40`:** the `backward_shift` shape the diagnosis below named as primary was
unchanged (`7/7` both arms) — the two flips came from a `forward_shift` residual the move also
reaches, not the "already passed" sub-case specifically; a `backward_shift`-driven flip is plausible
but wasn't sampled in this half of the val split. Solver-only mode also supplies oracle-derived,
reliably-populated `activity_time_windows` — the shipped parsed path may fire less often, since
parse-side window extraction is imperfect ([P15](#p15--finish-phrasing-robust-extraction)).

**Next step:** a pinned end-to-end gate on the eval machine (Evaluation-workstream job, not run
here — see the two-VM rule) to confirm the gain survives a full budget/restart count before this
flag is a `PROMOTED_SOLVER_FLAGS` candidate.

**Original diagnosis and scoping (2026-08-07), retained below.**

**The one solver move R25 pointed at, and the only member of its family still unbuilt.** Newly given
an identifier on 2026-08-07; the residual itself was measured on 2026-08-06 and has been sitting in
[§4](#4-one-constraint-family-accounted-for-almost-all-of-the-in-distribution-loss) without an item.

`timed_visit_named_poi` is the family that produced this project's single largest gain — one new move
(`TPC_WINDOW_ANCHOR`) moved FPR `32.5 → 42.5` on a screen and `+11.0` on a full run, at identical
budget and restart count. Three moves have landed (anchor, push, insert). The residual on
`familiar_100_val` (`n=80`) is `43` queries still failing a timed-visit clause, `33` with nothing else
failing; by shape, forward-shift `21`, absent POI `15`, shorten `11`, backward-shift `10`.

**What is missing is one shape: a window that has already passed on the day the POI is scheduled.**
`8` sole-blocker queries need the activity moved to a **different day**, which no landed move can do —
all three operate within a day. A coarse check found `22 of 25` absent/backward instances have some day
whose free span contains the window, so the headroom is real. Instrument:
`scripts/phase2_timed_window_shapes.py`.

**Why it is ranked below the precision items despite that.** R25 established that this family does not
respond to more search of the same move (`0/10` flips at 10x restarts and 10x CP time) — which is an
argument *for* a new move, exactly as §4 was. But it is scoped to familiar-100, where extraction is
clean; on the held-out register a third of queries may be failing for the reason in
[§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves), and a solver move cannot help a
query with no feasible point. Do the precision items first, then this.

**The known trap, already paid for once.** Relocation means **move-then-delete**, not copy: a
duplicate visit trips the repeated-attraction commonsense rule, and since the evaluator sync a
commonsense failure zeroes C-LPR *and* the EPR-macro point for that query. So the move must be atomic
across two days and re-grounded through `ground_and_check` before it may occupy a `best` slot.

**Where.** `chinatravel/agent/tpc_agent/tpc_agent.py`, alongside `_anchor_timed_windows` /
`_relayout_movable_block`. Behind `TPC_WINDOW_RELOCATE_DAY`, library default off, bounded (one
relocation per attempt, a fixed candidate-day order — the search space here is small and does not need
randomizing).

**Bar.** A unit test per shape (window already passed; no day has a free span; relocation would
duplicate a POI). Then the [quick A/B screen](tpc_phase2_eval.md#quick-ab-screen) on
`familiar_100_val` at `n=40`, reading the timed-window shape counts from
`scripts/phase2_timed_window_shapes.py` before and after, not only FPR — a move that fires on `1/40`
plans is measurable by shape and invisible in the mean, which is what happened to P8/P9.

### P15 — finish phrasing-robust extraction


**The budget/room-type half is [landed](#the-phrasing-fix-landed-2026-08-06). This entry covers the
residual: 9 of its 15 `local_released_150` clauses landed 2026-08-07
([screen](../results/phase2_baselines/screens/20260807_p15_phrasing_robust_extraction/README.md));
6 are re-scoped below, not silently dropped.**

**What is left, measured (the unextractable part, unchanged).** After the landed fix, `hf_medium`
parse gaps are `363 → 126`. Of the 38-clause shortfall against the predicted `≤89`, **35 are
unextractable from visible text at any parser quality**: `15 of 150` `medium` queries have an English
`nature_language` that is only a rendered markdown title (`'**Travel Plan for a 2-Day
Trip...**'`), and `14/14` residual `cost_total`, `10/10` residual `cost_restaurant` and `11/14`
residual `room_type` clauses live in those queries. Do not chase them.

**Landed 2026-08-07 (`parse_constraints.py`).** Of the `15 of 522` `tpc_phase2_test` parse-gap
clauses this entry named, 9 are fixed: `restaurant_name` (4, all 4 — a shared-helper newline fix plus
"avoid"/"do not try X" verb phrasings), `inner_transport_set` (3, all 3 — "wish to" and "travel by"
verb phrasings), `restaurant_type` (1 of 2 — "restaurants of the cafe type" value-before-`type` word
order), `cost_transport` (1 of 1 — "in-city" budget-scope synonym). A precision guard was needed
alongside: an unanchored "would like to try X" pattern swallowed whole free-prose sentences that never
say "restaurant" at all (measured: `required_restaurants` spurious rose on `hf_easy`/`medium`/`human`
with zero recall gain) — the anchor is mandatory for "try" but stays optional for "dine at", which the
released set always uses to name a specific venue. Full before/after (all 6 sets, precision **and**
spurious) in the screen above.

**What is genuinely still open** is 6 clauses, re-scoped into two tiers by risk rather than left as
one flat list:

- **Tier B — precedence-sensitive mis-classification, 3 clauses** (`attraction_name` ×2,
  `attraction_type` ×1). Not an absence: the parser already fires, into the *wrong* family (e.g. "the
  Hangzhou Suspended Glass Art Museum" → `required_attraction_types: ["Art Museum"]` instead of
  `required_attractions`). Fixing the disambiguation changes which pattern wins on ambiguous text —
  not an additive change, and its safety can only be shown by an e2e run this box (the coding VM)
  must not start; see [the two-VM rule](tpc_phase2_eval.md).
- **Tier C — infeasibility risk, 2 clauses** (`activity_time_window`, "must not leave X before
  TIME"). Same class of move as the already-rejected `arrive_no_later`-from-`end_before` item below —
  a pinned late-end-time window can prune the rest of the day's transport. Max measured gain is 1–2
  queries against a real risk of making a solvable query infeasible.

On the HF sets the name/type families miss at `70–100 %` (`cuisine_preference` `100 %`,
`required_attraction_types` `70–90 %`) — but **every** residual gap there sits in a CJK-literal
clause, so that data cannot tell you their score impact.
**Treat the HF name/type miss rates as an upper bound of unknown tightness, and work the
`tpc_phase2_test` list, which is real English evidence.**

Two probe-classifier artifacts were also found and left untouched (measurement fix, not parser fix,
not to be mixed into the same commit as the change it would be measured against — see the screen's
§2): `free_attractions_only` already satisfies a `cost_attraction<=0` OR-arm but
`CLAUSE_KIND_RULES` doesn't credit it; and the same table's `cost_transport` marker matches
`inner_city_transportation_cost` only, so an `inter_city` (intercity) clause is invisible to it.

**How to do it (Tier B/C).** Work one family at a time in `parse_constraints.py`. For each: find the
released queries whose oracle carries the family and our parse does not
(`scripts/phase2_generalization_probe.py` emits them per family), read the actual phrasing, add an
additive alternative guarded so no existing pattern's precedence changes — Tier B specifically is
**not** additive, so it needs a dedicated screen showing zero familiar-100 perturbation before it can
land. **Two precision traps already paid for:** `spend no more than 70 RMB per meal` and `a budget of
500 yuan per day` both became plan-wide `budgets["total"]` in a first cut. An unsatisfiable 70-yuan
total budget is strictly worse than no extraction — a spurious constraint makes a query infeasible,
which costs the whole query. A third, found 2026-08-07: an unanchored restaurant-name verb pattern
can swallow a whole free-prose sentence that never names a restaurant at all (above) — the fix is a
mandatory lexical anchor, not a stoplist, since a stoplist can never enumerate every non-name phrase.

**Bar.** `pytest tests` green with **no pre-existing test edited**; the familiar-100 byte-identity
floor test in `tests/phase2/test_parser_phrasing_generalization.py` still passes (it keeps verbatim
copies of the pre-fix budget/room-type extractors and asserts equality over all 100 queries) —
**and**, since this entry's fixes touch families that test's verbatim copies do not cover,
`tests/phase2/test_parser_phrasing_p15.py`'s hash-pinned `query_variants()` floor over all 100
familiar-100 queries also passes; and
[R22](tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)
shows familiar-100 gaps still `0/1109` with the targeted family's gap count down and no other set's
up — measured here as spurious flat-or-down on all 6 sets, precision flat-or-up on all but two
CJK-literal-only wobbles (screen §3).

### P16 — ground LLM-extracted values into the closed vocabulary

**Landed 2026-08-07** (`chinatravel/agent/phase2/normalize.py`;
[screen](../results/phase2_baselines/screens/20260807_p16_entity_resolution_probe/README.md)). Two
independent fixes, both needed:

1. **The 2026-08-06 LLM-arms screen measured with name grounding structurally absent.**
   `scripts/phase2_llm_parse_arms_probe.py` never threaded `entity_resolution` through to
   `query_variants`, so the LLM arm's proposed POI names were compared to the oracle completely
   unresolved — not a confirmation that grounding fails, an explanation of why the screen couldn't
   show it. Composing the *existing* `TPC_P2_ENTITY_RESOLUTION` flag with
   `TPC_P2_LLM_PARSE_MODE=extract_fill` (no new code) recovers `10` of the `20`-`matched` deficit on
   `local_released_150` alone.
2. **New: `_ground_type_value`/`_ground_type_values`** ground category/type values (cuisine, hotel
   feature, attraction type) against the environment's closed vocabulary — alias table → exact
   case-insensitive hit → unique best-above-`0.85` fuzzy match, dropping a tie or a below-threshold
   value rather than guessing. Attraction-type grounding is new entirely (previously no vocab check
   at all) and city-scoped (`_attraction_type_vocab`'s own casing-disagreement note).

Both fixes together: `matched` on `local_released_150` `300 → 311` (`extract_fill`,
`entity_resolution` on), `spurious` improving `38 → 37` rather than trading away. It clears the
roadmap's stale pre-P15 threshold of `309`, but **does not clear the contemporaneous deterministic
floor of `320` measured in the same run**. Promotion decisions compare same-tree arms, so the honest
gate result is not yet GREEN. e2e A/B: familiar-100 **GREEN** (`FPR 26.67→40.0`, `overall
55.72→62.88`, though this box's
own baseline showed `~7`-point run-to-run noise, so read the sign not the magnitude); `hf_medium`
has a **negligible negative delta within that noise** (`overall 49.99→49.88`, `FPR` unchanged), so
this branch's headline gain did not reproduce on this particular 30-query free-prose subset. Two measurement bugs were found and
fixed while running the e2e screen (an LLM-timeout-vs-parse-deadline trap matching CLAUDE.md's own
documented warning, and a stale-result-reuse bug from killing a run mid-flight) — both are recorded
in the screen so they don't recur. **Library default unchanged**: `Flags.from_env({})` still gives
`llm_parse=False, backend=none`; this is not a default flip, and R20 requires a new parse-level arm
to beat the contemporaneous deterministic floor before spending a pinned `full_runs/` slot.

The section below is preserved as the original diagnosis and is still accurate; only the "open" framing
is stale.

**The highest-value open experiment, and the cheapest to resolve: every prompt response is cached, so
re-measuring a policy costs `$0`.**

**What is measured** ([LLM arms screen](../results/phase2_baselines/screens/20260806_llm_arms/README.md),
`$3.55`, 852 live calls, zero failures). LLM-first extraction over all 904 released English queries
cuts free-prose parse gaps `40–65 %` and breaks **zero** clauses; `hf_medium`'s FPR ceiling rises
`52.67 → 81.33`. **But `matched` — the only count that can satisfy a clause — does not move.**
`missing` converts into `wrong_value` almost one-for-one, and on `local_released_150` (English literals
throughout) it gets *worse*: `309 → 296`. The model detects *that* a constraint was stated and fails to
emit the exact environment-vocabulary value the verifier compares; `"hotpot"` is dropped by
`validate_extract_families`.

**So the bottleneck is value grounding, not language.** The fix is to resolve an LLM-proposed value
against the environment's own vocabulary before accepting or discarding it, instead of exact-matching a
whitelist: canonical concept labels (`chinatravel/environment/concept_labels.py`) and the existing
entity-resolution path for names.

**Settled, do not re-litigate.** The merge policy is **fill-only** —
`TPC_P2_LLM_PARSE_MODE=extract_fill`, landed as a library mode: the LLM may populate an *absent*
family, never overwrite a regex one. The overwrite policy corrupts `budgets` in `15/30` and
`excluded_inner_transport` in `14/30` familiar-100 queries. And **`audit` mode is dead**: it recovers
`6/126` free-prose gaps against extraction's `50/126` and damages familiar-100 family F1
`0.955 → 0.917`.

**Kill criterion, corrected for intervening parser changes:** `matched` on `local_released_150` must
exceed the deterministic arm measured on the same tree and same query set. A historical absolute
number cannot remain the floor after P15 moves that arm. P16 currently reads `311 < 320`; it remains
available for [R20](tpc_phase2_eval.md#r20--does-grounded-fill-only-llm-extraction-convert), but it is
not promotable from the merged screen.

**Residual risk to watch.** Family *precision* falls with LLM extraction (`0.958 → 0.894` familiar,
`0.883 → 0.808` medium) because the model adds families the oracle lacks. Per P15's trap, a spurious
constraint can make a query infeasible, so precision is not a cosmetic metric here.

**Bar.** Flag, default off, byte-identical library floor (`Flags.from_env({})` must keep
`llm_parse=False, backend=none`), the contemporaneous `matched` criterion above, then a paired e2e A/B
on free prose enriched for P19's two dominant families **and** the familiar-100 control, then a
`full_runs/` row before any default flips. The free-prose arm must improve; familiar-only evidence
cannot promote a parser after v1. Note the deployment constraint: the organizers' endpoint caps
concurrency at `--max-running-requests 8`, below our worker count, so any LLM stage must throttle to
at most 8 in flight.

### P19 — find the unidentified half of the gap

**Closed 2026-08-07** ([screen](../results/phase2_baselines/screens/20260807_p19_unidentified_gap/README.md),
`scripts/phase2_density_family_gap_analysis.py`). Kill criterion not met: `hf_medium`'s dense tail
(`≥10` clauses, the only free-prose set with any queries this dense, `n=27`) has a coverage ceiling
of `74.91` — `15` points below its own overall average, real and directional, but `~20` points short
of held-out's `55.20`, so density alone does not explain the residual. No family is completely
unproduced on every set. The families-ranked-by-`instances × miss_rate` list is dominated by
`required_attraction_types` (`160` instances, `63.75%` miss) and `cuisine_preference` (`127`
instances, `78.74%` miss) by a wide margin over the rest of the ranking — **independent confirmation
that [P16](#p16--ground-llm-extracted-values-into-the-closed-vocabulary)'s targets are the largest
concrete residual**, found from a completely separate analysis. Deliverable (the ranked list with
estimated C-LPR cost) is in the screen; no further P19 work is open without new held-out evidence.

The section below is preserved as the original brief.

**Cheap, static, and it decides where the *next* half-day goes.** Opened by the 2026-08-07 leaderboard
breakdown, which qualified the phrasing diagnosis rather than confirming it outright: held-out C-LPR is
`55.20`, **below our worst local free-prose measurement** (`72.5` raw / `78.4` English-literal, *before*
the phrasing fix). Phrasing brittleness is real and measured, but something of comparable size is
unaccounted for.

**Three candidate causes, and how to price each from released data only.** No solve is needed, so this
is an afternoon at most.

1. **Higher constraint density.** `FPR = 0.0000` independently implies `≥ ~10` clauses per query. For
   each released set, compute the clause-count *distribution* (not the mean) and then our own C-LPR
   **restricted to queries with `≥ 10` clauses**. If the dense tail of HF `medium` already reproduces
   `C-LPR ≈ 55`, density is the answer and the action is to tune against dense queries.
2. **Families we cannot express at all.** List families appearing in any released set's *oracle* that
   our extractor has **never** produced on any set. A family with no representation is invisible to
   every screen we run, which is exactly how the phrasing gap survived.
3. **Families we express but get wrong at scale.** From the per-family diff
   (`scripts/phase2_generalization_probe.py` already emits it), rank families by
   `instances × miss_rate` across all released sets rather than by miss rate alone — a family missed
   `30 %` of the time on 400 instances outranks one missed `100 %` of the time on 20.

**Deliverable:** a ranked list of residual causes with an estimated C-LPR cost each, committed as a
screen. **Kill criterion:** if (1) reproduces `C-LPR ≈ 55` on a dense tail, stop and do not pursue (2)
or (3) — density would then explain the residual, and the useful response is re-tuning rather than
family hunting.

**Do not use any held-out artifact.** The only held-out facts available are the seven published
metrics, already recorded in
[`heldout/20260807_v1_leaderboard.json`](../results/phase2_baselines/heldout/20260807_v1_leaderboard.json).

### P20 — close the two dominant family-recall gaps

**Landed 2026-08-07** (`parse_constraints.py`;
[screen](../results/phase2_baselines/screens/20260807_p20_family_recall/README.md)). P19 ranked
`required_attraction_types` (`102` misses) and `cuisine_preference` (`100` misses) more than twice
above the next family. P16 can ground values only after a family exists; it cannot repair the
`missing` bucket, and `extract_fill` deliberately cannot overwrite a deterministic family already
populated with garbage. The merged P16 screen gave the concrete example:
`cuisine_preference = ["one of the following", "Japanese cuisine"]`.

**The measurable universe turned out much smaller than the miss counts suggest, and this reshapes
the whole item.** Before writing any pattern, every miss in both families across all six
released/HF sets was partitioned by whether its *oracle value* is an English or a CJK literal
(`scripts/phase2_family_recall_gap_partition.py`). `diff_constraints` requires exact value equality,
so an English extraction against a CJK oracle literal can only ever land as `wrong_value`, never
`matched` — the same wall [P16's screen](#p16--ground-llm-extracted-values-into-the-closed-vocabulary)
already measured ("`missing` converts into `wrong_value` almost one-for-one"), now confirmed as the
*general* shape of this problem rather than an LLM-arm-specific quirk. Not a loader artifact:
`tpc_phase2_test`/`tpc_phase2_familiar_100` load from a physically separate, pre-translated English
tree (`chinatravel/data/en/`); the four HF sets never translate `hard_logic_py` regardless of the
query's English text. Result: **only 3 clauses, all `cuisine_preference`, all on
`local_released_150`, are locally measurable as `matched` at all** — zero for
`required_attraction_types` anywhere in released data.

**What landed, in two parts:**

1. **Two bugs in `parse_cuisine_preference`**, closing all 3 of the measurable misses (plus 4 more
  the same fixes happened to also unblock): a list-lead-in leak (the roadmap's own cited example —
  a non-greedy "want to try X restaurant" scan stopping at the lead-in words instead of the value)
  and a numbered-OR-arm boundary swallow (the released generator doesn't always end an arm with a
  period before the next arm's digit, so a bare `.+?` over-captured into it). `local_released_150`
  `cuisine_preference`: `matched 7 -> 14`, `spurious 4 -> 1`.
2. **Free-prose fallback patterns for both families** (`_free_prose_type_mentions`), gated to run
  only when every anchored pattern above found nothing — structurally unable to touch
  familiar-100 (always populated through the template) or override a value an anchored pattern
  already found. Three false positives were found and fixed while developing this, each now a
  regression test: negation checked only at the trigger (missed a later, separately-negated
  clause); a proper-noun guard that didn't skip past a POI name's " - " separator
  (`"Sichuan University (Wangjiang Campus) - Museum"`); a bare `universit(y|ies)` alternative that
  matched `"university students"`.

**Acceptance, honestly scored against the criterion as originally written.** R22 is GREEN:
familiar-100 stays `0/1109` (also structurally guaranteed, not just tested); no free-prose set's
parse gaps or spurious count rose (checked at both the whole-parse total and the two target
families specifically). "Each target family's `matched` count must rise on at least one
English-literal set" — **met for `cuisine_preference`** (`local_released_150` `7 -> 14`); **cannot
be met for `required_attraction_types` with any local data**, since zero English-literal misses
exist for it anywhere released, a fact discovered during this item rather than assumed going in.
The fallback for that family is shipped anyway on the same bounded-risk argument P16 used for its
own unmeasurable-locally extension (familiar-100 cannot regress, spurious flat everywhere
measured, coverage ceiling up on every free-prose set) — its real value was a question only
[R26](tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets) or the held-out register could
answer. **R26 has since run on the Evaluation machine and closed GREEN** (2026-08-07, using this
screen's `target_uids.txt`): no set gained gaps or spurious clauses, and — beyond what this screen
found — one locally-measurable `required_attraction_types` gain turned up too (a disjunctive-branch
clause this item's own partition script didn't enumerate). See
[R26's result](tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets) for the full readout.

**Did not bundle:** distance-value formatting, activity end-window semantics, P17 scheduler
coverage, or LLM merge policy — different failure and precision risks.

### P17 — stop trusting our own "satisfied" verdict

Two halves. **(a) is the real fix, landed 2026-08-08, library default off. (b) was the safe one,
and the 2026-08-07 breakdown demoted it to approximately worthless: idle-envelope work buys
preference points, and every preference term is `0` on the held-out set because FPR is `0`. (b)
stays parked until FPR is above zero.**

**(a) landed as `TPC_P2_COVERAGE_UNKNOWN`.** `chinatravel/agent/phase2/coverage_signal.py` ships
two closed, checkable categories -- a currency amount and a room-type noun -- each measured
`0/100` on familiar-100 and `0/150` on `local_released_150` before landing (the P13 trigger-rate
precedent this section's own bar requires). A third category, cuisine, was built and **rejected on
measurement**: a closed-vocabulary substring match against the environment's own cuisine values
triggered on `58/100` familiar-100 queries, almost all false positives from a cuisine word
appearing inside a restaurant *name* a query correctly handled through an entirely different
family (e.g. `excluded_restaurants`) -- exactly the P12 failure mode restated for a word list
instead of a phrase. Named-POI mention is deferred for the same reason (needs catalog grounding, not
a word list); both are residuals, not built here. `sweeps.repair_order`/`polish_order` gained an
opt-in `coverage_unknown` eligibility filter (never touching `PlanScore.constraints_ok` itself,
which keep-best and the incumbent comparison depend on) so a flagged query keeps its repair-queue
slot instead of being silently promoted to polish; `run_sweeps_split` computes the signal once per
query in the parent (oracle-free: visible text + already-parsed variants only) and threads it
through. 25 new unit tests across `tests/phase2/test_coverage_signal.py`,
`tests/phase2/test_sweeps.py`, and `tests/phase2/test_coverage_unknown_wiring.py`; `pytest tests`
green (full suite, `-m integration` included).

**Whole-run screen (`familiar_100_val`, `n=14`, `--mode whole-run` -- required, since this item
changes pass *selection*, machinery a `solver-only`/`end-to-end` screen never reaches): NEUTRAL by
construction, not a caution sign.** FPR/`overall_true` flat (as pre-registered: the only two
split-sets `--mode whole-run` supports are ones the static probe had already measured at `0`
trigger rate), and both arms' raw run summaries record `coverage_unknown_uids: []` even with the
flag on -- proof the observed pass-composition/`+2`-timeout deltas are solve-to-solve noise on a
shared 2-core box, not an effect of this item's code (the eligibility filter is a no-op on every
uid when nothing is flagged, by construction). Full account:
[screen README](../results/phase2_baselines/screens/20260808_p17a_coverage_unknown/README.md).
**Residual, explicitly not built here:** `--mode whole-run`'s split-set choices exclude every
register where the signal fires at nonzero volume (`hf_human` 4/154; `local_released_150` before
cuisine was dropped, 6/150) -- proving the mechanism *helps* (not just "is safe and correctly
wired") needs a whole-run-equivalent screen on one of those, which needs a tooling extension or a
bespoke driver. Evaluation-workstream job either way.

**(b) Spend the residual envelope, ~2 h, no correctness risk.** Every run ends early, and under parse
gaps it ends early *and* idles on queries it wrongly believes are done (`1546 s` of `1800 s` unspent on
the free-prose run). Once repair and polish are empty but budget remains, re-polish *all* queries
rather than idling. `on_result` already guarantees keep-best, so an extra attempt cannot regress the
split. Where: `chinatravel/agent/phase2/sweeps.py`, `_candidate_passes` / `_choose_pass`; `pass_fits`
must still bound it against the deadline. Measure by `overall` up with `FPR` not down, and by the
`scheduler_budget_unspent_sec` figure the probe records
([R21](tpc_phase2_eval.md#r21--spend-the-unspent-envelope-needs-p17)). Expected small — preference
terms are capped by FPR — but it is free.

**(a) Make an unrepresented requirement visible to the scheduler.** The scheduler asks
`evaluate_parsed_constraints`, so a clause we never extracted reads as satisfied. The honest answer is
`unknown`: a query whose parse could not represent something it can see stated should keep its place in
the repair queue rather than being promoted to polish.

**Why this needs care, and what was already rejected.** [P12](#landed-and-promoted) considered exactly
this ("mark it unknown") and rejected it, on the grounds that a signal-phrase heuristic imprecise
enough to fire on already-correctly-parsed queries manufactures the false negatives P10 existed to
remove. That reasoning stands **for a phrase heuristic**. What has changed is the evidence about
direction: on unfamiliar phrasing we are systematically *over*-confident, and a false negative costs
budget while a false positive costs the query. So implement it as a **coverage** signal, not a phrase
signal — e.g. a sentence that mentions a currency amount, a room noun, a cuisine or a named POI while
the parse produced no family covering it. Keep the trigger rate measurable, and require the familiar-100
trigger rate to stay at or near zero (as P13's did) before it may ship.

**Bar for (a).** A screen must show the familiar-100 trigger rate and the free-prose trigger rate
separately, plus `overall`/`FPR` on both registers. If it fires on familiar-100 at all, show that
`overall` there does not fall.

### P4 — the per-query cap is 300 s by accident, and it structurally forbids a second repair pass

**Landed 2026-08-08.** `run_split` (`agent_env/scripts/solve_phase2.py`) no longer resolves
`budget_sec` to `DEFAULT_BUDGET_SEC` (`300`) before deciding whether to hand off to the sweep
scheduler — it now forwards the raw, possibly-`None` value through to `run_sweeps_split`, which
only sets `SweepConfig.max_query_sec` from it when an operator explicitly passed `--budget-sec`;
otherwise `SweepConfig`'s own default, `sweeps.DEFAULT_MAX_QUERY_SEC` (`900`), applies — the
smaller-diff shape this section named ("stop passing `budget_sec` as `max_query_sec`"), chosen
over deriving the cap from envelope÷query-count. The organizers' exact entry point takes no other
flags, so **every real run now uses the `900 s` cap by default**, not `300`. The plain per-query
*development*-gate loop (no `--total-budget-sec`) is untouched — an omitted `--budget-sec` still
resolves to `300` there, and `scripts/phase2_quick_eval.py --mode whole-run`'s explicit
`--budget-sec` still overrides the sweep scheduler's cap exactly as before, so that screen's
calibrated per-pass timing is unaffected. The whole-run summary's `budget_sec` field now records
the cap actually in force (`900` by default, or the explicit override) rather than blindly echoing
the raw operator input, with a new `budget_sec_explicit` field alongside it for the raw value — a
recorded row has to state its own configuration. 6 new unit tests
(`tests/phase2/test_sweep_budget_cap.py`), `pytest tests` green (full suite, `-m integration`
included).

**No `full_runs/` row on this fix exists yet** — R28 predates it, and this is exactly the "no
query has ever been solved above `300 s`" regime the section below says was untested rather than
tested-and-flat. R24 already measured `0` flips at a `900 s` *outer* cap with the internal
`400`-restart/`30 s` CP-SAT limits unchanged, so **no score effect is claimed here**; this is a
correctness fix that makes the intended `900 s` per-query cap reachable for the first time, nothing
more. A `full_runs/` row against the current tree is an Evaluation-workstream job, not run here (see
the two-VM rule) — no screen was run for this item either, since its own bar (R24) already exists
and is negative on score, and a screen would only re-measure that.

**Re-opened 2026-08-07; R25 closed 2026-08-07 as a correctness-only fix (below).**
Previously filed as a score-neutral tidy-up. It is not a tidy-up: it is why every run stops at roughly
a quarter of its envelope, and it silently disabled a mechanism the design intended to have.

**The mechanism, verified in code and against every recorded row.**

- `run_split` resolves `budget_sec = DEFAULT_BUDGET_SEC` (`300`, `agent_env/scripts/solve_phase2.py`)
  and passes it as `SweepConfig(max_query_sec=budget_sec)`. So the cap that applies is `300 s`, while
  `sweeps.DEFAULT_MAX_QUERY_SEC = 900` — the intended cap — is **unreachable dead code on this path**.
- `_choose_pass` drops a query from a repair pass unless the new budget beats its last by
  `MIN_BUDGET_GROWTH = 1.25`. After one repair pass at the cap a query's `last_budget` is `300`, so
  re-entry needs `375 s` — but `pass_budget_sec` is capped at `300`. **`300 < 375`, so no query can ever
  re-enter a repair pass.** The candidate list empties, `_choose_pass` returns `None`, and the run ends
  with ~73 % of the envelope unspent.
- Raise the cap to the intended `900` and the same arithmetic gives a second pass `382 s ≥ 375 s`, so it
  **is** scheduled. Reproduce both halves with `pass_budget_sec(13000, 50, workers=3, fraction=0.5,
  cap_sec=300 | 900)`.

**This means [§3](#3-the-current-fixed-search-saturates-deeper-search-is-not-yet-tested) overclaimed, and the record is
corrected here.** Across **all 25 recorded rows** `budget_sec` is `300.0` and no pass ever exceeded
`300 s`. So "more search does not help" is established for `25 s → 62 s`, for `120 s → 300 s`, and for
the whole-envelope `1/3/5 h` ladder — but **no query has ever been solved above `300 s` on the whole-run
path, because the code cannot do it.** That regime is untested, not tested-and-flat. §3's conclusion may
survive the test; it has not had it.

**Why it is cheap and low-risk.** `on_result` guarantees keep-best, so an extra pass cannot regress the
split; `pass_fits` keeps the scheduler deadline-aware; fallbacks are pre-written before the first solve.
The cost of trying is wall clock that is currently idle.

**The fix.** Derive the cap from the envelope and query count rather than inheriting the per-query
development default, or at minimum stop passing `budget_sec` as `max_query_sec` so the intended `900`
applies. Either way delete the constant that is now misleading, and keep `--budget-sec` working as an
explicit operator override, since the per-query development gate depends on it.

**Bar.** [R24](tpc_phase2_eval.md#r24--does-a-query-above-300-s-ever-flip-the-owners-question-open) is the
measurement. Read the ordering argument in [P5](#p5--spend-the-idle-envelope-on-fresh-seeds) before
spending an eval slot: on the held-out distribution, coverage plausibly binds before search does.

**R24 measured the outer cap only, 2026-08-07** (Evaluation screen, not a promotion row): `0` flips at
`900 s`, plans byte-identical to `300 s`. Both arms still used the same deterministic seed, the same
`TPC_MAX_RESTARTS=400`, and the same default CP-SAT cap of `30 s`; both stopped around `107 s`.
Therefore P4 alone is a correctness fix that schedules more identical work.

**R25 then tested both internal limits directly, 2026-08-07**
([screen](tpc_phase2_eval.md#r25--separate-the-cp-restart-and-outer-budget-limits)): `TPC_CP_TIME_LIMIT_SEC=300`
(10x default) changed nothing on `10/10` uids; `TPC_MAX_RESTARTS=4000` (10x default) changed plan
content on `6/10` but flipped `0/10` queries, and the recurring blocker across those 6 is timed-window
placement, a clause family neither axis touches. **P4 stays a correctness-only fix**: implement it for
its own sake (it currently silently disables the intended `900 s` cap and burns ~73% of the envelope),
but do not expect it to pay off in flips paired with P5's seed diversity — R25 closed that pairing.

### P5 — spend the idle envelope on fresh seeds

**Not implemented, 2026-08-07, per R25.** P5's own gate (below, §2/§3) was "a positive R25 arm before
default-on implementation." R25 raised `TPC_MAX_RESTARTS` 10x (`400 -> 4000`) directly and measured
`0/10` query flips (one clause-level move on one uid, not a query flip); the failed-clause inspection its
own decision table calls for found the recurring blocker to be timed-window placement, a family that
did not respond to the 10x restart increase. R25 measured restart volume, not distinct-seed diversity —
that a fresh `TPC_SEED_SALT` would fare differently is P5's own §2 mechanism argument (a fresh salt draws
different tuples from the same space that more restarts already sample), not something R25 itself tested.
Given the gate was not met, do not implement `explore_passes`/`TPC_P2_EXPLORE` on this evidence; the
"Where"/"Tests" sketch below is retained as a record of the design, not a live plan. Re-open only if a
future move changes what "failing" means for these queries and search headroom becomes plausible again.

**Correction, 2026-08-07: the previous day's demotion was justified with the wrong reason, and that note
is retracted.** It read "`~0` while FPR is `0` — preference-bounded", which is the argument for
[P17(b)](#p17--stop-trusting-our-own-satisfied-verdict), not for this item. P5 re-attacks **still-failing**
queries, so it targets constraint satisfaction and FPR, not preference terms. The two were conflated.

**The conclusion is still "not first", but on different and weaker grounds.** Three arguments, in
descending strength:

1. **Held-out-specific, and decisive for ordering.** A constraint we never extracted is not in the
   objective the solver optimizes, so **no amount of search can satisfy it** — and the scheduler will not
   even queue that query, because our own checker says it passes (the amplifier in
   [§1](#1-coverage-not-search-what-the-held-out-gap-is-made-of): self-reported `FPR 86.67` against a real
   `6.67`). Where clause failures are extraction failures, extra search is aimed at the wrong failure.
2. **Mechanism.** A fresh `TPC_SEED_SALT` draws different tuples from the *same* `_random_params` space —
   a few thousand combinations sampled independently. That is what continuing the restart loop already
   does.
3. **Current measurement.** Post-P1 the repair pass gives ~50 failing queries the full `300 s` and
   improves `1` (R8 `1/54`, R17 `1/50`); pre-P1 it was `2/66`. Not a pre-P1 artifact — and no longer an
  outer-budget question: [R24](tpc_phase2_eval.md#r24--does-a-query-above-300-s-ever-flip-the-owners-question-open)
  found `0` flips because it changed neither the 400-restart cap nor the 30-second CP cap. The
  internal-limit question remains open and is isolated by R25.

**The owner's Phase 1 experience is real, and it points at the right variant.** Long overnight runs did
fix hard queries there, under two conditions that do not hold now: oracle constraints were available, so
the objective was *correct*; and the gain came from a monotonic merge across many **configurations**
(parameters, flags, repair variants), not from re-seeding one configuration. That is evidence for a
**portfolio over the search space**, which is also what [§4](#4-one-constraint-family-accounted-for-almost-all-of-the-in-distribution-loss)
found paid — `+11` FPR from one new *move*, `~0` from more draws of the same one. If the idle envelope is
to be spent, spend it on configurations before salts.

**Sequencing — resolved.** R25 ran on familiar-100 (extraction is clean there) and found that neither CP
time nor restart breadth flips a query: per the plan above, the envelope goes to configuration-changing
repairs (P20) or targeted repair (P6) instead of blind seed passes.

**Where.** `chinatravel/agent/phase2/sweeps.py`: add `SweepConfig.explore_passes` (env `TPC_P2_EXPLORE`,
**default off**); have `solve_one(task)` read `task["seed_salt"]` and set `TPC_SEED_SALT` for the solve
with the same save/restore discipline as `_fast_accept`; add an `explore` pass kind in
`_candidate_passes`/`_choose_pass` whose candidates are the still-failing queries, ordered **last**, and
to which **`MIN_BUDGET_GROWTH` must not apply** (a new seed is new work at any budget); hand out a
distinct salt per explore pass. `pass_fits` must still bound it against the deadline.

**Tests.** Explore is scheduled when repair and polish are empty but budget remains; not scheduled when
the envelope is exhausted; each pass hands out a different salt; `TPC_P2_EXPLORE=0` reproduces today's
pass sequence exactly.

**Depends on** P0 and P2 (both landed — without the attempt ledger, flips cannot be counted per pass,
and that is the only signal separating the two readings), plus a positive R25 arm before default-on
implementation — R25 was not positive, so this item is closed rather than implemented.

**Considered and dropped: warm-starting later passes.** `solve_one` does not receive the incumbent plan,
so repair and polish re-solve from scratch. Threading plan state through the worker boundary and
re-grounding it through `ground_and_check` before it may occupy a `best` slot is real complexity for a
resource we have in surplus.

### P18 — make phrasing robustness a gate

**Landed 2026-08-07** (`scripts/phase2_generalization_probe.py`, `tests/phase2/test_phrasing_generalization_gate.py`;
[screen](../results/phase2_baselines/screens/20260807_generalization_post_p20/README.md)).

**The recall half is landed. Two precision conditions are still open**, and they are a cheap follow-up
commit rather than a new item. The gate compares each set's `n_parse_gap` against a recorded floor,
which is a recall-only criterion: a change that *invents* constraints instead of missing them passes it
silently. That is exactly how
[§6](#6-we-make-a-third-of-free-prose-queries-infeasible-ourselves) survived every screen this
project ran. Both instruments now exist:

- **No set's `spurious` count may rise.** `phase2_generalization_probe.py` already emits it per set and
  per family; the floor file needs one more recorded number per set, alongside `n_parse_gap`.
- **No set's unsatisfiable-required-name count may rise**, from
  `scripts/phase2_unsatisfiable_names_probe.py`. This is the condition that would have caught the
  `23–50 %` finding, and it costs the same two minutes as the check that landed.

**The process fix, and the cheapest item here.** Nothing in the previous gate could detect a phrasing
dependency: every screen and gate ran on familiar-100 val, and the held-out tripwire was a 20-record
subset of the same templated artifact.

The [phrasing tripwire](tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)
is now an executable check, not a documented habit. `results/phase2_baselines/phrasing_generalization_floor.json`
records, per `DEFAULT_SETS` entry, the last known-good `n_parse_gap` (`tpc_phase2_familiar_100`
pinned at `0`) alongside `n_oracle_clauses` as a snapshot fingerprint.
`scripts/phase2_generalization_probe.py --check-floor <path>` re-measures every set and exits `1` if
any set's parse-gap count rose above its recorded floor; a set whose `n_oracle_clauses` no longer
matches (the released/HF data moved) is a **skip**, not a failure -- that is not phrasing evidence.
`tests/phase2/test_phrasing_generalization_gate.py` runs the same check inside the default
`pytest tests/phase2` suite (measuring all six sets takes ~14 s locally, so it needed no
`integration` marker) and skips cleanly, stating why, when the local HF cache is unavailable; a
second, HF-free tier of synthetic tests in the same file pins that `check_floor`/`write_floor`
actually fire on a regression, hold at the exact floor, and that `--update-floor` can only ratchet a
set's floor down, never up (so it can tighten the gate after a real fix but can never launder a
regression). `make phase2-generalization-gate` is the explicit standalone invocation for the R22
cadence. `phrasing_generalization_floor.json` sits under `results/phase2_baselines/` but outside
`screens/`: it is an Implementation-owned gate artifact the code depends on to run (checked and
ratcheted from this same PR), not an Evaluation-workstream measurement row -- unlike everything else
in that directory, a future change to it should land with the parser change it ratchets, in the same
PR, not from a separate eval-machine run.

**Why it was worth an hour:** a parser change that improves familiar-100 while worsening free prose is
a regression, and before this only a human reading two screens would notice. The seed run's window
spans three landed items (P16, P19, P20), but its README checks attribution (`git diff --stat` over
the range) rather than assuming it: only P20 touches code the probe's default flags-off path
exercises, so the improvement is P20's alone -- every free-prose set's gap count dropped
(`hf_easy 127->97`, `hf_medium 126->78`, `hf_human 99->81`, `hf_preference_base50 19->14`,
`local_released_150 6->5`), `familiar_100` stayed `0/1109` -- see the screen for the full before/after
table and the attribution check.

### P6 — validator-in-loop Qwen repair

**Built and screened 2026-08-08. R27 result: RED — zero accepted flips caused by the repair loop.
Stays library default off.** All five build items landed: `insert_activity` joined `refine.py`'s
typed-edit vocabulary (`TPCAgent._refine_insert_activity`, WorldEnv-catalog-grounded, never
free-form JSON); `orchestrator.llm_refine`'s hardcoded "1 + optional retry" became a
`max_attempts`-bounded loop (default `2`, reproducing `TPC_P2_LLM_REFINE` byte-for-byte — all 28
pre-existing tests pass unchanged) that `TPC_P2_LLM_REPAIR_LOOP=1` raises to `6`, each round seeing
the previous round's own post-edit failure summary (item 4's "deterministic rejection feedback");
`run_sweeps_split` clamps the worker pool to `min(workers, 8)` when the flag is on (item 5's
concurrency throttle — each worker makes at most one LLM call at a time, so pool size directly
bounds concurrency, no cross-process semaphore needed). 36 new/updated unit tests, `pytest tests`
green (full suite, `-m integration` included).

**R27, run against a live DeepInfra backend (`temperature=0`, `TPC_P2_LLM_TIMEOUT_SEC=15`,
`budget_sec=600`):** 10 queries selected from a deterministic-failure pool (9 timed_window, 1
name_type, **0 transport_budget** — the pool's actual residual at this budget/size, reported
honestly rather than forced into an even three-way split; matches this project's own standing
diagnosis that `timed_visit_named_poi` dominates the residual). LLM called on 8/10 (2 were already
accepted deterministically before Stage 3 ran, no call needed). **0/10 accepted flips caused by the
repair loop** — the roadmap's own stated RED condition. Safety properties all held: 0 ungrounded
facts, 0 timeouts, real multi-round iteration happened (one query used all 6 rounds), and
`insert_activity` fired at least once (grounding failed with `next_activity_unreachable`). One edit
individually grounded in one round: still not enough to clear whole-batch acceptance. The dominant
per-edit rejection reasons — `no_time_left_after_arrival`, `next_activity_unreachable` — say the
model's proposed times/insertions are frequently infeasible given the day's real
transport-and-hours structure, which the compact plan + failure summary in the prompt does not let
it reliably avoid. Contrast with [P25](#p25--cross-day-timed-window-relocation)'s `+2/40` on the
same family: P25 is a deterministic search over every grounded candidate slot, this loop proposes
one edit set per round with no equivalent systematic search — that gap is what the RED result
measures. Full account, including a measurement pitfall found and fixed while writing it up (2 of
the 10 "accepted" outcomes were the deterministic solve alone succeeding at the repair arm's larger
budget, not an LLM-caused flip — the summary now reports both the raw and LLM-attributed counts, and
the verdict uses only the latter):
[screen README](../results/phase2_baselines/screens/20260808_r27_llm_repair_loop/README.md).

**Per the roadmap's own bar, this is a stop.** `insert_activity` and the generalized `max_attempts`
loop stay in the codebase (correctness-neutral, tested, off-by-default) for a future architecture
that might reuse either primitive, but no score effect is claimed. Not re-attempted here: a larger
`n` (the bar is met at 10) or richer prompt context (a different experiment).

**Pure unchecked LLM planning is closed; grounded tool-guided planning is not.** The measured `Act`
arm queried `WorldEnv` for 34-42 turns and then emitted itinerary JSON directly. It had no schema or
commonsense feedback, no grounded edit API, and no keep-best loop; all 16 plans failed commonsense.
That is not the interaction that made manual Kiro/Claude repair useful.

Build a bounded experimental loop behind `TPC_P2_LLM_REPAIR_LOOP=1`, library default off:

1. Start from TPCAgent's best grounded candidate. Run only for queries that remain self-failing after
  deterministic solve; never spend calls on an already accepted plan.
2. Prompt with the visible query, compact current plan, parsed branch-local requirements and
  `_describe_check_failure` output. Assert in a unit test that no oracle/verifier-only key can enter
  the prompt.
3. Accept typed edits only. Reuse `refine.py`, `apply_refine_edits` and `ground_and_check`; add an
  insertion/replacement op only through a `WorldEnv` lookup, never as free-form plan JSON. Keep the
  first spike to six rounds and six edits per round.
4. After each rejected batch, return the compact deterministic rejection reason to the next round.
  Keep the incumbent unless the exact existing checker and self-score ordering accept the trial;
  never weaken schema, commonsense or parsed-logic acceptance.
5. Record calls, rounds, proposed/grounded/rejected/committed edits, stop reason, wall time and token
  use per query. Throttle to at most eight concurrent requests for organizer parity.

**Cheap falsification screen:** R27, ten deterministic failures split across timed-window,
name/type and transport/budget blockers, `temperature=0`, at most six calls/query. Continue only if at
least one previously failing query becomes accepted, `MacEPR` does not fall, all emitted facts ground,
and the call/timeout counters prove the loop ran. A partial-score move with zero accepted flips is a
RED result. Do not enable thinking mode.

This can be implemented in parallel with P20/P18. It reuses P16's grounding but does not depend on
LLM parsing being promoted.

## What not to spend time on

- **Anything justified by a familiar-100 number alone.** That is the error that cost this cycle. Pair
  it with a free-prose measurement or it does not count.
- **Reading a free-prose FPR against `100`.** Under `--lang en` the HF splits cap at `38.67–46.0`
  because their oracle literals are Chinese ([P23](#p23--make-the-free-prose-register-scoreable)).
  Every such number in this repository's history was read against the wrong denominator; do not add
  another.
- **Hunting for a further systematic cause of `FPR = 0.0000`.** There are now two sufficient
  explanations — the clause-product model and self-inflicted infeasibility — and the second one has a
  fix. Build the fix; do not commission a third diagnosis.
- **`audit`-mode LLM parsing, free-form LLM-only JSON planning, or another one-shot refine prompt.**
  All measured at or below the deterministic floor. This does not exclude P6's bounded
  validator-in-loop edit proposer; that experiment has deterministic grounding and rejection
  feedback the measured arms lacked.
- **Thinking mode on the planning loop.** `75 s` per one-line call, `~$1.1`/query extrapolated,
  timeouts. Measured and rejected.
- **Within-query parallelism.** Blindly parallelizing the same 400 draws competes with query-level
  workers, and [R25](tpc_phase2_eval.md#r25--separate-the-cp-restart-and-outer-budget-limits) found
  neither CP nor restart breadth productive, so there is no diversity axis this would help schedule.
- **Preference packing (`TPC_PACK_*`).** Bounded by FPR; `~1.5` overall if all three were perfected
  against `~0.85` for one FPR point. `TPC_PACK_HOTEL_BREAKFAST` is permanently off — upstream PR #29
  made a repeated meal type a commonsense failure.
- **More whole-envelope, outer-timeout, CP-time, or restart-cap sensitivity.** `1/3/5 h` is flat, R24
  shows a `900 s` outer cap still replays the same 400-restart/30-second-CP search, and R25 shows
  raising CP time or restart count 10x each independently produces `0/10` flips. All four axes of
  "more compute, same move" are now measured and closed.
- **Improving the empty-itinerary fallback for score.** `empty_plans` is `0` on every real run. It is
  insurance against a cut-off run, not points.
- **`arrive_no_later` emitted from `end_before`.** Tried; its ceiling prunes proper transport, and
  since the evaluator sync a transport-less plan also scores ATT `0`.
- **More calls around the existing one-shot Stage 3 prompt.** Both refine variants show
  `improve_committed=0`. P6 is allowed to revisit the architecture only because it adds deterministic
  rejection feedback and a bounded typed-edit loop; R27 still requires an accepted flip.

## Landed and promoted

### Harness defaults (promoted through a measured gate)

Set by `solve_phase2.apply_deterministic_solver_defaults()`. The **library** default (unset env var) is
unchanged, so the byte-identical opt-in unit tests and the eval tooling's flags-off arm keep working;
an explicit operator override still wins.

| Flag | Evidence |
| --- | --- |
| `TPC_PIN_TIMED_WINDOWS=1` | timed-window pinning + within-day resequencer. Failed a `300 s` gate on timeouts, re-gated clean at `900 s`: e2e continuous `43.72 → 48.04`, FPR `20.0 → 25.0` |
| `TPC_SOLVE_CONVERGE_PATIENCE=15` | early-convergence stop. Quality flat, solve `p50` `366 s → 265 s` |
| `TPC_COMMONSENSE_FIRST=1` | relaxes the repair commit rule for *unaccepted* plans and prefers a schema+commonsense-valid candidate (`best_cs`). Paired screen: `overall_true 51.34 → 60.98`, C-LPR `67.35 → 89.95`, commonsense `30/40 → 40/40`, **`logical_micro` flat** — the gain is the commonsense gate releasing logical credit already earned. Re-verified 2026-08-06 (P3) |
| `TPC_WINDOW_ANCHOR=1` | [§4](#4-one-constraint-family-accounted-for-almost-all-of-the-in-distribution-loss)'s move. R8 `overall 63.58` / FPR `43.0` against R7's `57.75` / `32.0`, and R7 is **three bit-identical repeats**, so `+5.83` cannot be seed noise. Wall clock unchanged |
| `TPC_WINDOW_PUSH=1`, `TPC_WINDOW_INSERT=1` | bounded local window push and absent-POI insertion. R14 GREEN (`+0.5471` overall, `+1.0` FPR); R16/R17 confirm no destructive interaction with P10. Both fire rarely — `1/20` plans on the held-out fold. `TPC_WINDOW_PUSH_MAX_MIN` stays a candidate (a bound, not a pass) |

Every recorded row's per-query `telemetry.json` names these under `solver_flags`
(`PROMOTED_SOLVER_FLAGS`) alongside `CANDIDATE_SOLVER_FLAGS`, so a row states its own configuration
rather than relying on its label. Promotion means *moving* a name between the two sets;
`tests/phase2/test_solver_flag_telemetry.py` fails if they overlap or a recorded key goes missing.

### The phrasing fix *(landed 2026-08-06)*

`parse_constraints.py`: `parse_budget` now recognises a bare total budget (`budget of N`, `budget is
N`, `within N RMB`) **only when no scoped qualifier precedes it**, and room-type parsing recognises
plain wording (`single-bed`/`big bed`/`double bed` → `single`; `twin`/`two beds`/`double room` →
`twin`). Additive alternatives guarded by the existing scoped patterns.

| | before | after |
| --- | --- | --- |
| familiar-100 parse gaps | `0/1109` | **`0/1109`** (byte-identical; floor test keeps verbatim pre-fix extractors and asserts equality over all 100 queries) |
| `hf_medium` parse gaps | `363` | `126` (`35` of the residual are queries whose English text is only a plan title) |
| `hf_medium` F1 / FPR ceiling | `0.417` / `0.00` | `0.768` / `52.67` |
| `hf_medium` e2e (`n=30`, `1800 s`) | `41.6198` | `49.9909` (C-LPR `72.5 → 86.25`, FPR `6.67 → 16.67`) |
| English-literal clauses only | C-LPR `78.38`, FPR `20.00` | **C-LPR `93.24`, FPR `53.33`** |
| familiar-100 first-30 control | `64.56528973412726` | `64.56528973412726` (identical to every decimal) |

Value fidelity: `30/30` extracted budgets and room types match the oracle exactly. Two rejections
recorded rather than silently skipped: a `people_number==1 → single` default (familiar-100 has 2 solo
queries whose oracle says otherwise) and `family room` (its 2 released instances disagree). Screen:
[`20260806_parser_phrasing_fix/`](../results/phase2_baselines/screens/20260806_parser_phrasing_fix/README.md).
Tests: `tests/phase2/test_parser_phrasing_generalization.py` (50 cases), `test_parser_phrasing.py`.

### Infrastructure landed

- **The confirmed entry point runs the real solver** (2026-08-04). `solve_script_with_harness.py`
  ships `--harness tpc`, dispatching in-process to `solve_phase2.run_split` — zero LLM calls, zero
  network, no subprocess. Pinned by `tests/phase2/test_harness_entry_point.py`, which also pins
  method-verbatim, split-from-the-flag and oracle-free-query behaviour.
- **The whole-run envelope and scheduler** (2026-08-04). `sweeps.py`: triage → repair → polish across
  `CPU−1` workers, oracle-free self-scoring, keep-best, fallback written before the first solve.
- **P10: self-scoring uses the solver's exact parsed variants** (2026-08-06). `run_sweeps_split`
  parses each query once in the parent through the canonical path and forwards that object to *both*
  `solve_phase2` and `score_plan`, so solving and self-scoring cannot diverge; acceptance is OR across
  variants. `variants_source` lands in telemetry. **P13** then made `variants=[]` mean the same on both
  sides (truthiness, not identity), so a parent-side parse failure re-parses in the worker instead of
  solving unconstrained; trigger rate `0/100`.
- **P12: two genuine checker gaps closed** — `required_order` had no representation, and a meal
  end-time window could be satisfied by an accommodation-typed activity because the checker never read
  the `activity_types` the parser already recorded. The other three suspected gaps were already
  correctly represented. R17 measured it on the shipped path: GREEN. Note it changes the *acceptance
  gate*, since Phase 2 runs `TPC_USE_ORACLE=0` and `evaluate_parsed_constraints` is then
  `_make_checker`'s `base_check` — a screen claiming otherwise was wrong.
- **P2: per-attempt telemetry ledger** (2026-08-06). `attempts.jsonl` per uid, additive to
  `telemetry.json` (which each pass used to overwrite, destroying attempt history and silently
  measuring only the winners), aggregated into the committed row by `phase2_full_run.py` as
  `row["attempt_ledger"]`.
- **P11: `--mode whole-run` for the pre-gate screen** (2026-08-06). Before it, the shipped run shape
  was the one shape the screen tool could not reach, so every scheduler-level change was unscreenable.
  Per-arm method directories close the incumbent-bleed trap; the committed null screen is the standing
  proof.
- **P0: explicit reproducible restart seed** (2026-08-05). `restart_seed()` replaces a
  `hash((uid, salt))` seed — `hash()` over strings is salted per process, so runs were not reproducible.
  That is the mechanism behind the old `sd 0.35` score spread; post-fix it is `0`.
- **P7: worker count from CPU affinity** (2026-08-05), so a restricted container no longer
  oversubscribes.
- **A cold-start race that could empty the whole submitted split** (2026-08-05). A worker dying in the
  pool initializer takes the pool down while the run still **exits 0** and ships pre-written empty
  fallbacks. Guarded by `tests/phase2/test_cold_start.py`; the failure *shape* is a standing item in
  the [pre-submission checklist](reference/competition.md#pre-submission-checklist--the-cold-start-rule-added-2026-08-05).
- **Solver search telemetry** — `restarts_used`, `stop_reason`, `candidates_evaluated`,
  `best_found_at_restart`. A `func_timeout` kill used to discard it, losing data for exactly the
  budget-bound queries it explains; every leader-improving `consider()` now snapshots it. §3 is built
  on this.
- **Minimal packaging.** `requirements-submission.txt` (eight PyPI packages, no GPU stack) and
  `scripts/assemble_phase2_submission.py`, which builds the archive and verifies it by unpacking and
  running it with a stripped `PATH`. **It uploads nothing, and no agent uploads anything.**
- **Report-ablation and generalization tooling** (2026-08-06). `scripts/phase2_report_ablations.py`
  (LLM-only and upstream-baseline arms, scoreable by `eval_tpc.py`),
  `scripts/phase2_generalization_probe.py`, `scripts/materialize_hf_split.py`,
  `scripts/phase2_llm_parse_arms_probe.py`. Measurement only; no default changed.

### Landed, not promoted (all library-default-off)

| Flag | Status |
| --- | --- |
| `TPC_P2_ENTITY_RESOLUTION=1` | deterministic POI-name canonicalization against the target city's catalog. **Never measured on its own until 2026-08-07** — every prior arm composed it with LLM `extract_fill`. Isolated: parse F1 `0.9552 → 0.9949` familiar-100, `0.8222 → 0.8451` `local_released_150`, flat on the CJK-literal HF sets, zero LLM calls. The strongest promotion candidate on the board; needs [R29](tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end). See [P21](#p21--promote-deterministic-entity-resolution) |
| `TPC_P2_LLM_PARSE_MODE=extract_fill` | fill-only LLM extraction merge: may populate an absent family, never overwrite a regex one. Strictly better than `extract` on every set, and the only merge policy that leaves familiar-100 intact. [P16](#p16--ground-llm-extracted-values-into-the-closed-vocabulary)'s grounding (landed 2026-08-07, `TPC_P2_ENTITY_RESOLUTION=1` composed with this) now moves `matched` too; e2e screen GREEN on familiar-100, flat on `hf_medium`. Still library-default off pending a pinned `full_runs/` gate |
| `TPC_CASCADE_TIMED_WINDOWS` | forward-only cascading shift. Gated at `900 s`: its own target axis flat. Superseded by `TPC_WINDOW_ANCHOR` |
| `TPC_REPAIR_DROP_TRAILING_STAY` | 1 of 3 target uids fully clears; the other 2 have a deeper defect no forward-only repair can reach. Screen was RED, probably because its `_pack_plan` gate also activates general endpoint re-grounding on every query |
| `TPC_PACK_DAV` / `TPC_PACK_DDR` / `TPC_PACK_ATT` / `TPC_DENSIFY_COMPRESS_BEFORE` | preference packing; evidence predates the evaluator sync. See [what not to spend time on](#what-not-to-spend-time-on) |
| `TPC_P2_LLM_PARSE` / `TPC_P2_LLM_REFINE` / `TPC_P2_LLM_AGENTIC_REFINE` | audit-mode parse screened RED twice, on two different distributions; both refine variants commit `improve_committed=0` while their reserved slice costs timeouts |

### Closed — do not reopen without new evidence

- **LLM reachability** is verified, not assumed: a real DeepInfra endpoint completes the happy path,
  and a closed-port endpoint completes with `valid=True fallback=False`, the failure recorded only in
  telemetry. The organizers' SGLang/`Qwen3.6-27B` endpoint remains unreachable from here.
- **Slow queries starving the split** — structurally handled by the triage-first deadline-aware
  scheduler, and measured: `empty_plans 0/100` on every real run.
- **Phase 1's commonsense and preference residuals** — 21 of 22 tail plans repaired, `overall 98.98`.

## LLM packaging: the submission makes zero LLM calls

A packaging fact, not an opinion. `TPC_P2_LLM_BACKEND` defaults to `none`, whose client raises on any
call. `agent_env/config.toml` is **gitignored** and absent from the repository, so an archive built
from git has no `[phase2.llm]` backend. `TPC_P2_LLM_PARSE` is an explicit off-by-default decision in
`resolve_llm_client_and_flags` citing its RED screens, not an auto-enable keyed off backend
configuration. `TPCAgent`'s `backbone_llm` is `TPCLLM`, whose `_get_response` returns the literal
string `"Empty LLM response"`. `Flags.from_env({})` yields `llm_parse=False, backend=none`, and a test
pins it. The optional autodetect only activates when an operator points an env var at a real endpoint.

## Operating rules

1. **No oracle in the agent path.** Local oracle fields may score or attribute a rehearsal, never feed
   parsing, solving or finalization.
2. **Flags off is the floor.** A new behavior goes behind an env flag that is off by default, with a
   unit test asserting the floor stays byte-identical. Only `apply_deterministic_solver_defaults()` may
   turn a flag on by default, and only on measured evidence.
3. **Ground before acceptance.** `WorldEnv` and the deterministic validators decide facts and
   acceptance; LLM output is only a proposal.
4. **Acceptance first.** Do not weaken `_make_checker`, `_accepted`, or the `_pack_plan` commit rules.
5. **Nothing promotes by assertion.** A default flips only through a committed row that passes
   `make phase2-gate` against a like-for-like baseline. A screen triages; it never promotes.
6. **One register is not the distribution.** A parser or constraint-layer change is measured on
   familiar-100 *and* on free prose. This is [P18](#p18--make-phrasing-robustness-a-gate).
7. **Assert a component ran before believing its number.** Every optional stage needs an activity
   counter in telemetry; a green screen without one is unmeasured.
8. **No agent uploads anything.** Packaging is reviewable; submission is the owner's manual action.

## Key source locations

| What | Where |
| --- | --- |
| Restart loop, `restart_seed`, `_random_params`, `TPC_MAX_RESTARTS` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| `_pin_timed_windows` / `_resequence_day` / `_anchor_timed_windows` / `_relayout_movable_block` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| `_repair_intercity_endpoints`, `_repair_commit_allowed`, `_flag_enabled_with_umbrella` | `chinatravel/agent/tpc_agent/tpc_agent.py` |
| Parsed-constraint checker (**also the acceptance gate** under `TPC_USE_ORACLE=0`) | `chinatravel/agent/tpc_agent/parsed_verifier.py` (`evaluate_parsed_constraints`) |
| Natural-language constraint extraction | `parse_constraints.py` (repository root) |
| Oracle-DSL constraint extraction (the reference side of any parse diff) | `chinatravel/agent/tpc_agent/solver_constraints.py` |
| CP-SAT tier and worker count | `chinatravel/agent/tpc_agent/cp_solver.py` |
| Whole-run scheduler (`_choose_pass`, `solve_one`, `default_workers`) | `chinatravel/agent/phase2/sweeps.py` |
| Per-query orchestration, `Flags`, `PROMOTED_SOLVER_FLAGS` | `chinatravel/agent/phase2/orchestrator.py` |
| `apply_deterministic_solver_defaults`, `on_result`, `run_split`, attempt ledger | `agent_env/scripts/solve_phase2.py` |
| Confirmed entry point | `agent_env/scripts/solve_script_with_harness.py` |
| Whole-run measurement | `scripts/phase2_full_run.py` |
| **Phrasing-robustness probe** (which families we fail to extract, per register) | `scripts/phase2_generalization_probe.py` |
| **Unsatisfiable required-POI names** (§6's instrument) | `scripts/phase2_unsatisfiable_names_probe.py` |
| **Deterministic entity-resolution arms** (P21's instrument, zero LLM) | `scripts/phase2_entity_resolution_arms_probe.py` |
| **zh→en oracle-literal map + the free-prose FPR ceiling** (P23's instrument) | `scripts/phase2_oracle_literal_translation.py` |
| Family-recall gap partition by oracle literal language | `scripts/phase2_family_recall_gap_partition.py` |
| Bilingual concept vocabularies and their English casing aliases | `chinatravel/environment/concept_labels.py`, `chinatravel/environment/database{,_en}/` |
| Required-name/category-value resolution and P22's `keep`-vs-`drop` terminal branch | `chinatravel/agent/phase2/normalize.py` (`_resolve_one_required_name`, `_resolve_generic_location`, `resolve_entities`) |
| Report ablations (LLM-only, upstream baselines) | `scripts/phase2_report_ablations.py` |
| Timed-window residual by shape | `scripts/phase2_timed_window_shapes.py` |
| Failure attribution / commonsense headroom | `scripts/phase2_solver_failure_attribution.py`, `scripts/phase2_commonsense_headroom.py` |
| Inner-city transport arithmetic — distance/speed only, **no timetable** | `chinatravel/environment/tools/transportation/apis.py` (`goto`, `add_time`) |
| The evaluator's exact-equality leg check | `chinatravel/symbol_verification/commonsense_constraint.py` (`Is_transport_correct`, `Is_time_correct`, `Is_space_correct`) |
