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

**How much is accounted for.** Phrasing brittleness is measured and is the largest identified cause,
but the leaderboard shows it is **not sufficient**: held-out C-LPR (`55.2`) sits below our *pre-fix*
free-prose number, so a second factor of comparable size is still unidentified. Most plausible
candidates, in order: higher constraint density per query (which `FPR = 0.0000` independently implies
is `≥ ~10`), constraint families we have no local example of, and a *partial* infrastructure failure.
A total infrastructure failure is now excluded outright by EPR-micro `99.48`. The standing uncertainty
is that the organizers describe the held-out set as same-distribution as familiar-100; the phrasing
evidence says the two do not behave alike, whatever the intent.

### Submission policy (owner's instruction, 2026-08-06)

**Do not upload `v2`, and never upload automatically.** The owner uploads manually, shortly before the
deadline (2026-08-10, 24:00 Beijing Time), and only with a substantial measured improvement.

The leaderboard published on 2026-08-07 shows **ours as the only submission**, so the rank (`1`)
carries no information about relative quality and does not change this policy. Two facts do bear on
the decision when it is made: `v1`'s score stands regardless, since the higher of two successful
versions wins — so a worse `v2` costs only the slot — and by [reading 4](#the-measured-breakdown) an
*incremental* coverage fix is worth only its C-LPR share, while one that pushes the per-clause rate
past `~0.8` is worth several times more. The threshold, not the increment, is what makes a `v2` worth
spending.

## Run this next

Priority order. Every item states its own acceptance criterion so it can be executed without
re-deriving the argument.

**In flight as of 2026-08-07 (owner started both on separate machines):**
[P15](tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction) and **R19**. Do not start a second
whole-run solve on either host; queue behind them.

| Run | Question | Blocked on | Cost |
| --- | --- | --- | --- |
| **R23** | is the held-out set denser, or does it carry families we never see? — the unidentified half of the gap | nothing; static, cheap | ~1 h |
| **R24** | does a query above `300 s` ever flip? the regime no row has ever measured | nothing; per-query ladder first | ~1 h |
| **R22** | standing phrasing-robustness tripwire before any parser change promotes | nothing; cheap, run alongside | ~2 min |
| R20 | does fill-only LLM extraction plus value grounding convert recall into score? | [P16](tpc_phase2_roadmap.md#p16--ground-llm-extracted-values-into-the-closed-vocabulary) | ~$0 + ~1 h |
| R21 | does spending the unspent envelope on all queries buy preference points? | [P17](tpc_phase2_roadmap.md#p17--stop-trusting-our-own-satisfied-verdict) | ~1.4 h |
| R9 | does re-attacking failures with fresh seeds accumulate flips? | [P5](tpc_phase2_roadmap.md#work-items) + P2 | ~5 h |

R19 closed GREEN ([closed queue](#the-closed-queue-r1r19)) — familiar-100 confirmed unaffected by the
phrasing fix, reproducing R17 on every metric. R20 stays blocked on unlanded Implementation work;
**R24, R23 and R22 are the items this workstream can run without waiting on another lane.**

### R24 — does a query above 300 s ever flip? (the owner's question) *(open)*

**Registered 2026-08-07 because the owner asked whether more time and fresh seeds could fix failing
constraints, and the honest answer was that we had never tested it.** Across all 25 recorded rows the
per-query cap is `300.0 s` and no pass ever exceeded it — not by choice but because
[P4](tpc_phase2_roadmap.md#p4--the-per-query-cap-is-300-s-by-accident-and-it-structurally-forbids-a-second-repair-pass)
makes a higher budget structurally unreachable. This row measures the untested regime.

**Cheapest form first — a per-query ladder, not a whole run.** `--budget-sec` is already the per-query
cap, so no code change is needed to measure it:

```bash
for B in 300 900 2700; do
  .venv/bin/python scripts/phase2_quick_eval.py --mode end-to-end \
    --n 30 --budget-sec $B --parallel 3 --off 0 --on 0 \
    --out results/phase2_quick_eval/budget_ladder_$B
done
```

Run it on the **failing** subset, not a random one: take the uids that fail their constraints in
[R19](#the-closed-queue-r1r19)'s plan directory, since a query that already passes at `120 s` tells you
nothing about the ceiling. **Read flips, not the mean**: how many of the failing queries flip to
fully-passing at `900 s` and at `2700 s` that did not at `300 s`.

| Outcome | Read | Action |
| --- | --- | --- |
| flips grow roughly linearly with budget | the search was clock-bound after all, at a scale we never tried | land P4, then re-measure the envelope ladder post-P1, and move P5 up |
| a few flips at `900 s`, none beyond | there is a modest, bounded gain | land P4 anyway (it is near-zero risk and the envelope is idle), do not pursue P5 |
| no flips at any budget | §3's conclusion extends to the untested regime | land P4 as a correctness fix only, and close P5 with this row as the evidence |

**Then, only if the ladder is positive**, spend a whole-run slot on the paired form: the same 5 h
envelope with the cap raised, against [R19](#the-closed-queue-r1r19). Note that P4 also changes the
*number* of passes, so that row measures the cap and the growth-rule interaction together — which is the
shipping behaviour, and therefore the right thing to measure.

**One caveat that belongs in the reading, not in the design.** On the held-out distribution a large
share of clause failures are plausibly clauses we never extracted, and search cannot satisfy a clause
that is not in the objective. So a positive ladder result on familiar-100 does **not** imply the same
gain held-out, and a negative one does not close the question for a *correctly extracted* constraint
set. This row measures the solver, not the extractor.

### R23 — what else separates the held-out set? *(open, static, ~1 h)*

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

### R22 — the standing phrasing tripwire *(open, ~2 min, run with every parser change)*

The process failure behind the held-out gap was that **no gate could see a phrasing dependency**. This
closes it, and it costs seconds:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
  --out-dir results/phase2_baselines/screens/<date>_generalization_<change>
```

Require: familiar-100 parse gaps still `0/1109` **and** no free-prose set's gap count rising. A parser
change that improves familiar-100 while worsening free prose is now a **regression**, whatever its
familiar-100 number says. Commit the screen next to the change.

### R20 — does LLM extraction convert recall into score? *(needs P16)*

[Tonight's LLM screen](../results/phase2_baselines/screens/20260806_llm_arms/README.md) established
the shape of this precisely, and it is the most valuable open question:

- LLM-first extraction cuts free-prose parse gaps **40–65 %** and breaks **zero** clauses. On HF
  `medium` the `FPR` ceiling rises `52.67 → 81.33`.
- But `matched` — the only count that can actually satisfy a clause — **does not move**. `missing`
  converts into `wrong_value` almost one-for-one. The model detects *that* a constraint was stated
  and fails to emit the exact environment-vocabulary value the verifier compares (`"hotpot"` is
  dropped by `validate_extract_families`).

So the residual is **value grounding into a closed vocabulary, not language comprehension.** That is
[P16](tpc_phase2_roadmap.md#p16--ground-llm-extracted-values-into-the-closed-vocabulary). Run this
only after it lands. All 904 prompt responses are cached (`cache/phase2_llm_parse/`), so re-measuring
a different merge or grounding policy over the identical prompts costs **`$0`**.

Two things are already settled and must not be re-litigated: the merge policy is **fill-only**
(`TPC_P2_LLM_PARSE_MODE=extract_fill`, LLM may populate an absent family, never overwrite a regex
one — the overwrite policy corrupts `budgets` in `15/30` and `excluded_inner_transport` in `14/30`
familiar-100 queries), and **`audit` mode is dead** (recovers `6/126` free-prose gaps against
extraction's `50/126`, and damages familiar-100 family F1 `0.955 → 0.917`).

**Kill criterion, fixed in advance:** `matched` on `local_released_150` — the one set with English
literals throughout, where `extract` currently makes it *worse* (`309 → 296`). If a grounding fix does
not restore that count above `309`, stop; the approach does not convert.

If it does convert, gate it as a paired e2e A/B on the same 30-query free-prose pair *and* the
familiar-100 first-30 control, then a `full_runs/` row. **It stays default-off until a row promotes
it**, and note the deployment constraint: the organizers' endpoint caps concurrency at
`--max-running-requests 8` below our worker count, so any LLM stage must throttle.

### R21 — spend the unspent envelope *(needs P17)*

Every run ends early, and under parse gaps it ends early *and* mis-ranks its queue (see the amplifier
above). Read this row as **per-pass improvement counts**, not as a total: the question is whether
re-polishing queries the scheduler believes are finished converts idle time into preference points.
Acceptance: `overall` up with `FPR` not down. Expected small — preference terms are capped at `FPR`.

### R9 — the falsification run for "spend the idle envelope" *(needs P5)*

```bash
TPC_P2_EXPLORE=1 .venv/bin/python scripts/phase2_full_run.py \
  --method phase2_e2e_r9_seeds --label "seed-diversified explore, 5h"
```

**Read flips per pass, not `overall`.** One extra sampling pass is measured at ~1 flip per 68 queries;
the question is whether that accumulates over the ~10 passes the idle envelope affords. Independent
draws give `5–10` flips (`+1.7..+4.2` overall, promoting P5); an exhausted reachable set gives `1–2`
and closes the "we aren't using our time" question for good. Demoted below R20–R22: it re-attacks the
*search*, and the evidence now says the binding limit is *coverage*.

### What not to spend a slot on

- **Any local row read as a held-out estimate.** That is the error this cycle paid for. A local row
  measures a *configuration*, never a *distribution*.
- **A repeat of a run you already have.** Post-P0 the solver is bit-for-bit reproducible
  ([R7](#the-closed-queue-r1r19)); the same configuration on the same host returns the same number.
- **Any whole-run row whose configuration you cannot read off its own telemetry.** Check
  `solver_flags` first, score second.
- **`audit`-mode LLM parsing, LLM-only planning, or LLM plan refine.** All three measured, all three
  at or below the deterministic floor — see the [closed queue](#the-closed-queue-r1r19).
- **More whole-envelope sensitivity runs at the current cap.** `1/3/5 h` is flat and the
  [diagnosis](tpc_phase2_roadmap.md#the-diagnosis) explains why. **This does not extend to a raised
  per-query cap**, which no row has ever measured — that is
  [R24](#r24--does-a-query-above-300-s-ever-flip-the-owners-question-open), and it is worth running.
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
for what they do and do not predict.

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

**Drift note, same shape as `e7faa9f1`.** P15 (`a4d028bb`/`8688439c`, closes `9/15` `local_released_150`
phrasing gaps) merged to `main` while this run was in flight, so `main`'s tip is again one parser
change past what R19 measured. P15 carries its own screen and floor test
([roadmap](tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction)); it is not remeasured here,
and familiar-100 byte-identity is not itself evidence about it — P15 touches families the budget/
room-type floor test does not cover.

**On R10's `git_dirty: true`.** `eval_tpc.py`'s `update_suboptimal_split_file` rewrites
`chinatravel/evaluation/default_splits/tpc_phase1_suboptimal.txt` on every full-split scoring call, so
the dirtiness is **structural**: any rerun from any commit reproduces it. It touches no solver code or
plan output. A clean row would need an Implementation change (stop writing during a read-only scoring
pass), not a rerun.

### What the closed queue established

1. **The run self-terminates at `26 %` of the envelope**, because `_choose_pass` drops a candidate
   whose new budget cannot beat its last by `MIN_BUDGET_GROWTH` and every candidate is already at the
   cap.
2. **That idle time is not recoverable by scheduling.** Failing queries exhaust a *search*, not a
   clock: `2.5×` the budget buys `4.2×` the restarts and flips **one query in 68**. Extra envelope, a
   higher cap, more workers and fresh seeds are one intervention wearing four hats.
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

**Two promoted-default baselines exist; pick the one matching your host, not the highest number:**

| Host | Workers | Baseline row | `overall` / `FPR` / `constraints_ok` |
| --- | --- | --- | --- |
| 4-core Linux | 3 (`CPU−1`) | **R19 `20260807T043142Z`** (byte-identical to R17 `20260806T115309Z`, moved to the fresher `git_sha`) | `64.17251838310492` / `44.0` / `50/100` |
| 10-core Apple Silicon | 8 | R3 `20260805T215107Z` | `64.0773462893086` / `44.0` / `47/100` |

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

Plus the two instruments this cycle added:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py --out-dir <screen dir>
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
