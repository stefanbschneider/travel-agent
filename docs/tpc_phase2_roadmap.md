# Phase 2 implementation roadmap

**The active Phase 2 work plan: where the points are, what to build next, and what is already
settled.** How the system is built: [design doc](tpc_phase2_design.md). What to *measure*:
[evaluation roadmap](tpc_phase2_eval.md). What the competition requires:
[competition reference](reference/competition.md). Read [CLAUDE.md](../CLAUDE.md) first for the
non-negotiable invariants; nothing here overrides them. Phase 1's record is in the
[Phase 1 playbook](tpc_phase1_playbook.md); superseded plans are in the [archive](archive/README.md).

## The one-paragraph version

**Our held-out score is `33.2473`. Our local score is `64.17`. That gap, not the local score, is the
work.** The largest identified cause is measured: our constraint extraction has **zero** clause-level
gaps on the familiar-100 split it was built against and **12–29 %** on every differently-phrased
released set. We optimized, screened and gated against the one register we were already perfect on,
and our held-out tripwire was a 20-record subset of that same templated artifact, so nothing in the
process could have caught it. The first fix is landed and free on familiar-100 by construction; the
next ones are ranked below. The earlier diagnosis — that the score was *representation*-bound rather
than compute-bound — was correct and still holds, but it was a diagnosis of one distribution.

## Where we are

| Measurement | Score | What it licenses |
| --- | --- | --- |
| **Organizer held-out, `v1`** | **`33.2473`** | the only external calibration; see the [eval doc](tpc_phase2_eval.md#the-one-fact-that-reorganizes-this-document) |
| familiar-100, [R17](tpc_phase2_eval.md#the-closed-queue-r1r18) `20260806T115309Z` | `64.17251838310492`, FPR `44.0` | best local row; a configuration on one phrasing register |
| local released 150, R18 | `90.5603` | **nothing about generalization** — same template, a third the constraint density |
| free prose (HF `medium`), matched-budget screen | `41.62 → 49.99` after the phrasing fix | the register the held-out set may resemble |

Current shipped configuration: `TPC_WINDOW_ANCHOR` + `TPC_PIN_TIMED_WINDOWS` + `TPC_COMMONSENSE_FIRST`
+ `TPC_SOLVE_CONVERGE_PATIENCE` + `TPC_WINDOW_PUSH` + `TPC_WINDOW_INSERT`, all set by
`apply_deterministic_solver_defaults()`, zero LLM calls, `1.38 h` of the `5 h` envelope.

**`v2` is not packaged and must not be uploaded by an agent.** The owner uploads manually, after the
leaderboard publishes and only with a substantial measured improvement. See the
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

### 3. The solver is bimodal, and more search does not help

Per-query telemetry from a 1 h diagnostic (`n=42`, triage, `25 s`/query):

| | accepted (`n=15`) | failed (`n=27`) |
| --- | --- | --- |
| `stop_reason` | `accepted_stop` ×15 | **`budget` ×26** |
| restarts used, median | **0** | **39** |
| solve seconds, median | **3.2** | **22.7** of `~23 s` |

A query that gets solved is solved by the **first constructed plan**. A query that does not spends its
whole slice on ~39 randomized restarts. **There is no middle population that "just needed more time."**
Giving the failures `2.5×` the budget raised restarts to a median of 166 and flipped **one query in
68**; the 5 h reference run agrees (repair improved `2 of 66`, polish `11 of 34`), which is why
`1/3/5 h` score `57.35 / 57.86 / 57.99`.

**Why more restarts cannot help.** A restart resamples one parameter tuple (`_random_params`):
attraction offset, hotel index, attractions per day, visit minutes, a forced transport mode, optional
intercity preferences, a meal offset. Extra budget, a raised `TPC_MAX_RESTARTS`, more workers,
within-query parallelism *and* a fresh seed salt are all the same intervention: **draw more tuples from
that space.** The space does not contain a fix for these queries.

**So the idle time is a symptom, not the problem** — with one correction from §1: part of it is now
known to be the scheduler idling on queries it wrongly believes are done.

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

## Work items

Ranked. `P0`…`P18` are stable identifiers. Nothing below is on a critical path to an upload, because
[there is no scheduled upload](tpc_phase2_eval.md#submission-policy-owners-instruction-2026-08-06);
they are ranked by expected effect on the held-out score.

| | Item | Effort | Expected | Status |
| --- | --- | --- | --- | --- |
| **P15** | [Finish phrasing-robust extraction](#p15--finish-phrasing-robust-extraction) | half day | the measured residual: free-prose parse gaps beyond budget/room-type | **landed (partial) 2026-08-07; residual re-scoped, see below** |
| **P16** | [Ground LLM-extracted values into the closed vocabulary](#p16--ground-llm-extracted-values-into-the-closed-vocabulary) | 1 day | converts a measured `40–65 %` recall gain into score, or kills the approach cleanly | **open** |
| **P17** | [Stop trusting our own "satisfied" verdict](#p17--stop-trusting-our-own-satisfied-verdict) | half day (a), 2 h (b) | re-aims the repair queue; recovers `~85 %` idle envelope | **open** |
| **P18** | [Make phrasing robustness a gate](#p18--make-phrasing-robustness-a-gate) | 1 h | prevents the recurrence of the failure that cost this cycle | **open** |
| P5 | Spend the idle envelope on fresh seeds | half day | `~0` or `+1.7..+4.2` — genuinely open; needs P2 (landed) | open, demoted |
| P4 | Derive `max_query_sec` from the envelope | 1 h | `~0` by §3; tidy-up only, **do not run as a scoring A/B** | open, low |
| P6 | LLM-backed repair/move proposer | 1–2 days | **weakened by measurement**: LLM-only planning scores `2.64` with `MacEPR 0.00`, so the model's unaided grounding is far below the floor. As a *bounded proposer* still untested | open, low |
| ~~P1~~ | ~~`timed_visit_named_poi` window-aware move~~ (`TPC_WINDOW_ANCHOR`) | — | **promoted 2026-08-05**: `overall +5.83`, `FPR +11.0` | landed |
| ~~P8/P9~~ | ~~Window push / absent-POI insert~~ | — | **promoted 2026-08-06** (R14 GREEN, `+0.5471`); fire rarely | landed |
| ~~P10~~ | ~~Scheduler self-scoring uses the solver's exact variants~~ | — | **landed 2026-08-06**, default-on; R16 GREEN | landed |
| ~~P12~~ | ~~Close P10's false-positive half~~ | — | **landed 2026-08-06**; R17 GREEN on the shipped path | landed |
| ~~P13~~ | ~~Empty parent parse means the same on both sides~~ | — | **landed 2026-08-06**; trigger fires on `0/100` | landed |
| ~~P2~~ | ~~Per-attempt telemetry ledger~~ | — | **landed 2026-08-06**; `attempts.jsonl`, aggregated into the row | landed |
| ~~P3~~ | ~~Commonsense-valid emission~~ | — | **closed 2026-08-06**, re-screened, no code change needed | closed |
| ~~P11~~ | ~~Whole-run mode for the pre-gate screen~~ | — | **landed 2026-08-06**, tooling only | landed |
| ~~P14~~ | ~~Promote P8/P9 to harness defaults~~ | — | **landed 2026-08-06** | landed |
| ~~P0/P7~~ | ~~Reproducible restart seed; worker count from affinity~~ | — | **landed 2026-08-05** | landed |

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

**Kill criterion, fixed in advance:** `matched` on `local_released_150` must exceed `309`. If a
grounding fix does not restore that count, stop — the approach does not convert recall into score, and
that is a publishable finding rather than a failure.

**Residual risk to watch.** Family *precision* falls with LLM extraction (`0.958 → 0.894` familiar,
`0.883 → 0.808` medium) because the model adds families the oracle lacks. Per P15's trap, a spurious
constraint can make a query infeasible, so precision is not a cosmetic metric here.

**Bar.** Flag, default off, byte-identical library floor (`Flags.from_env({})` must keep
`llm_parse=False, backend=none`), the `matched` criterion above, then a paired e2e A/B on the same
30-query free-prose pair **and** the familiar-100 first-30 control, then a `full_runs/` row before any
default flips. Note the deployment constraint: the organizers' endpoint caps concurrency at
`--max-running-requests 8`, below our worker count, so any LLM stage must throttle to ≤8 in flight.

### P17 — stop trusting our own "satisfied" verdict

Two halves. **(b) is safe and should be done first; (a) is the real fix and needs care.**

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

### P18 — make phrasing robustness a gate

**The process fix, and the cheapest item here.** Nothing in the previous gate could detect a phrasing
dependency: every screen and gate ran on familiar-100 val, and the held-out tripwire was a 20-record
subset of the same templated artifact.

Add the [phrasing tripwire](tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)
as an executable check, not a documented habit: a test (or a `make` target invoked by the screen
tooling) that runs `scripts/phase2_generalization_probe.py` and **fails** when familiar-100 parse gaps
rise above `0/1109` or any free-prose set's gap count rises. It needs the local HF cache, so it must
skip cleanly (not fail) when the cache is absent, and say which condition it skipped on.

**Why it is worth an hour:** a parser change that improves familiar-100 while worsening free prose is a
regression, and right now only a human reading two screens would notice.

## What not to spend time on

- **Anything justified by a familiar-100 number alone.** That is the error that cost this cycle. Pair
  it with a free-prose measurement or it does not count.
- **`audit`-mode LLM parsing, LLM-only planning, LLM plan refine.** All measured, all at or below the
  deterministic floor. LLM-only planning scores `2.64` with `MacEPR 0.00` — not one of 16 plans passed
  commonsense.
- **Thinking mode on the planning loop.** `75 s` per one-line call, `~$1.1`/query extrapolated,
  timeouts. Measured and rejected.
- **Within-query parallelism.** More draws from the space §3 measured as exhausted, now competing for
  cores the whole-run scheduler already uses across queries. Its one screen came back RED.
- **Preference packing (`TPC_PACK_*`).** Bounded by FPR; `~1.5` overall if all three were perfected
  against `~0.85` for one FPR point. `TPC_PACK_HOTEL_BREAKFAST` is permanently off — upstream PR #29
  made a repeated meal type a commonsense failure.
- **More envelope-sensitivity runs.** `1/3/5 h` is flat and §3 explains why.
- **Improving the empty-itinerary fallback for score.** `empty_plans` is `0` on every real run. It is
  insurance against a cut-off run, not points.
- **`arrive_no_later` emitted from `end_before`.** Tried; its ceiling prunes proper transport, and
  since the evaluator sync a transport-less plan also scores ATT `0`.
- **An agentic loop on Stage 3 refine.** Both refine variants show `improve_committed=0`. Revisit only
  if a screen ever shows `improve_committed > 0`.

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
| `TPC_P2_LLM_PARSE_MODE=extract_fill` | fill-only LLM extraction merge: may populate an absent family, never overwrite a regex one. Strictly better than `extract` on every set, and the only merge policy that leaves familiar-100 intact. Blocked on [P16](#p16--ground-llm-extracted-values-into-the-closed-vocabulary) — recall rises, `matched` does not |
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
| Report ablations (LLM-only, upstream baselines) | `scripts/phase2_report_ablations.py` |
| Timed-window residual by shape | `scripts/phase2_timed_window_shapes.py` |
| Failure attribution / commonsense headroom | `scripts/phase2_solver_failure_attribution.py`, `scripts/phase2_commonsense_headroom.py` |
| Inner-city transport arithmetic — distance/speed only, **no timetable** | `chinatravel/environment/tools/transportation/apis.py` (`goto`, `add_time`) |
| The evaluator's exact-equality leg check | `chinatravel/symbol_verification/commonsense_constraint.py` (`Is_transport_correct`, `Is_time_correct`, `Is_space_correct`) |
