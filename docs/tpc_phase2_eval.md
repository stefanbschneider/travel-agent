# Phase 2 evaluation roadmap

**One document for both halves of evaluation: what a measurement is allowed to prove, and what to
run next.** Merged 2026-08-05 from the former `tpc_phase2_eval.md` (definitions) and
`tpc_phase2_eval_roadmap.md` (run queue); both are preserved verbatim in the
[archive](archive/README.md). What to *implement* is the [implementation roadmap](tpc_phase2_roadmap.md);
how the system is built is the [design doc](tpc_phase2_design.md).

Generated rows live in [`results/phase2_baselines/`](../results/phase2_baselines/); this document
defines their interpretation.

## Run this next

R1–R10 are closed (see [what the closed queue established](#what-the-closed-queue-r1r10-established)).
R7 (2026-08-05, post-P0) found the same-config spread is now **zero**: three independent 5 h
repeats scored bit-for-bit identical (`overall 57.74985419574877`, `FPR 32.0`, `constraints_ok
36/100`, all three times) — every remaining arm below is judged against that near-zero floor rather
than the pre-fix `sd 0.35`, so an effect well under `1` point is resolvable in a single run and
**no arm on this list needs repeats** unless a future result actually shows spread. R8
(2026-08-05) gated the window-aware move **GREEN and full-sized**: `overall 63.58` (`+5.83` over
R7), `FPR 43.0` (`+11.0`), `constraints_ok 46/100` (`+10`) — close to the paired screen's predicted
`FPR 32.5 → 42.5`. **`TPC_WINDOW_ANCHOR` is now gate-cleared; flipping it on by default is an
Implementation-workstream change**, not something this run performs. R10 (2026-08-05, diagnostic
only) put `tpc_phase1` through the same no-oracle path: `overall 85.20` against the oracle-fed
Phase 1 pipeline's `98.98` — a `13.78`-point removing-the-oracle cost, the report figure this run
exists to produce.

| Run | What it answers | Blocked on | Cost |
| --- | --- | --- | --- |
| **R9** | does re-attacking failures with fresh seeds accumulate flips? | [P5](tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds) + [P2](tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger) | ~5 h |
| **R11** | LLM-backed repair, v2 only | [P6](tpc_phase2_roadmap.md#p6--llm-backed-repair-proposer-v2-candidate-default-off) | not before the v1 upload |
| **R3** | does cross-query parallelism convert into score? | a ≥8-core machine | ~5 h |

**R9 and R11 did not run this pass.** Both are blocked on unimplemented work items (R9 needs
[P5](tpc_phase2_roadmap.md#p5--spend-the-idle-envelope-on-fresh-seeds) +
[P2](tpc_phase2_roadmap.md#p2--per-attempt-telemetry-ledger); R11 needs
[P6](tpc_phase2_roadmap.md#p6--llm-backed-repair-proposer-v2-candidate-default-off) and is
explicitly gated to not run before the `v1` upload) that belong to the Implementation workstream,
not Evaluation — see the [parallel workstreams](../CLAUDE.md#parallel-workstreams) split. R3 stays
blocked on an ≥8-core machine, unrelated to this pass.

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

### R11 — LLM-backed repair arm *(needs P6; v2 only)*

Off by default and stays off for `v1`. The confirmed endpoint (`Qwen3.6-27B` via SGLang,
`--max-running-requests 8`) exists only on the organizers' host, so any local number is a proxy
against a different backend. Gate only if `v1` feedback leaves room for a `v2`.

### R3 — worker scaling: still blocked

```bash
TPC_P2_WORKERS=1 .venv/bin/python scripts/phase2_full_run.py --workers 1 --label "1 worker, 5h"
```

The direct test of the claim behind the whole-run rewrite: with `W` workers a pass costs
`ceil(n/W)` query-budgets instead of `n`, so each query can afford a much larger budget. Compare
against R1 at the same envelope. **Skip below 8 cores** — the comparison would say more about the
box than the code. This box has 4.

### What not to spend a slot on

- **The old per-query `900 s` pinned gate as a ship signal.** It measures a contract the competition
  does not use. Keep it for solver-change A/Bs only.
- **More envelope-sensitivity runs.** `1 h / 3 h / 5 h` is flat and the
  [diagnosis](tpc_phase2_roadmap.md#the-diagnosis) explains why.
- **Preference-packing flags (`TPC_PACK_*`).** Every preference term is zeroed for a query that fails
  its constraints, so the whole headroom across DAV/ATT/DDR is `~1.5` overall at today's FPR.
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

## What the closed queue (R1–R10) established

Run 2026-08-04/05 on a 4-core box (3 workers), `evaluator_parity: c89cfca`, rows under
`results/phase2_baselines/full_runs/`. **Nothing on this list needs re-running.**

| Run | Row | Result |
| --- | --- | --- |
| R1 reference, 5 h | `20260804T201638Z` | `overall 57.99`; MicEPR `99.48`, MacEPR `97.00`, C-LPR `87.83`, **FPR `33.00`**, DAV `18.15`, ATT `26.25`, DDR `19.39`; `empty_plans 0/100`, `constraints_ok 35/100`; **used `26%` of the envelope** (`4723 s` of `18000 s`) |
| R2 envelope sensitivity | `20260804T213636Z` (1 h), `20260804T221103Z` (3 h) | `57.35 / 57.86 / 57.99` at 1/3/5 h — **flat** |
| R3 worker scaling | — | not run: 4-core box, below the 8-core floor |
| R4 pass shape | `20260804T231910Z` control, `20260805T001808Z` A, `20260805T011733Z` B, `20260805T021805Z` C, `20260805T032037Z` control repeat | arms A/B were accidental no-ops (their caps never bound); arm C (`TPC_P2_FAST_TRIAGE=0`) `58.40` vs `57.81` |
| R5 held-out tripwire | `20260805T042106Z` | `overall 62.59` on the 20-record test split, `constraints_ok 10/20` |
| R6 packaged archive | no row (checks the zip, not a split) | `fabiundstefan_v1.zip`, `1676` entries, `4.0 MB`, from commit `b44bb73c096b`; unpacked and run with a stripped `PATH`: `valid_output=True` |
| **R7 seed-variance baseline, 5 h ×3** | `20260805T081535Z`, `20260805T094549Z`, `20260805T110654Z` | **bit-for-bit identical across all three repeats**: `overall 57.74985419574877`, MicEPR `99.67`, MacEPR `98.00`, C-LPR `88.82`, FPR `32.0`, DAV `16.625`, ATT `24.53`, DDR `18.42`; `constraints_ok 36/100`; per-pass telemetry (`improved`/`elapsed_sec`) matches to within noise across the three runs too |
| **R8 window-aware move, 5 h** (`TPC_WINDOW_ANCHOR=1`) | `20260805T123142Z` | `overall 63.58` (**`+5.83`** over R7); MicEPR `99.67`, MacEPR `98.00`, C-LPR `89.90`, **FPR `43.0`** (**`+11.0`**), DAV `24.71`, ATT `33.65`, DDR `24.50`; `empty_plans 0/100`, `constraints_ok 46/100` (**`+10`**); matches the paired `n=80`/`90 s` screens (predicted FPR `32.5 → 42.5`) closely; used `26%` of the envelope (`4733 s`) |
| **R10 phase1-under-phase2, 5 h** (diagnostic, 1000 queries) | `20260805T135254Z` | `overall 85.20`; MicEPR `100.0`, MacEPR `100.0`, C-LPR `95.57`, FPR `85.4`, DAV `29.86`, ATT `59.52`, DDR `53.53`; `empty_plans 0/1000`, `constraints_ok 715/1000`; `1.60 h` of the envelope. `git_dirty: true` (see caveat below) |

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

R5 is recorded standalone: `familiar_100_test` is a *subset* of `familiar_100` (R1's split), so no
val↔test gap is computed. `62.59` above R1's `57.99` is consistent with a smaller, easier split, not
a generalization signal. R6 checks packaging only, never score.

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
- parser, solver and feature flags;
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
