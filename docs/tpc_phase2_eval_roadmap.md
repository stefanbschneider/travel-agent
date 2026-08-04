# Phase 2 evaluation roadmap — 5-hour envelope, parallel

**Written 2026-08-04, after the whole-run-envelope rewrite.** This is the run order for the
evaluation workstream. It replaces the per-query-budget run plan in
[`docs/agents/`](agents/README.md), which measured a contract the competition does not use.

For metric definitions, dataset boundaries and the gate mechanics, see
[Phase 2 evaluation](tpc_phase2_eval.md). For what to *implement* next, see the
[roadmap](tpc_phase2_roadmap.md).

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

### R4 — pass shape: where should the envelope go?

Every knob is an environment variable, so these need no code change:

| Variable | Default | What it changes |
| --- | --- | --- |
| `TPC_P2_TRIAGE_CAP_SEC` | `120` | ceiling on the first, everything-once pass |
| `TPC_P2_TRIAGE_FRACTION` | `0.25` | share of the envelope triage may spend |
| `TPC_P2_PASS_FRACTION` | `0.5` | share of what remains each later pass may spend |
| `TPC_P2_MAX_QUERY_SEC` | `900` | ceiling on any single query's solve |
| `TPC_P2_MIN_QUERY_SEC` | `20` | floor below which a query is not worth starting |
| `TPC_P2_MAX_PASSES` | `24` | hard stop on pass count |
| `TPC_P2_FAST_TRIAGE` | `1` | triage stops each query at its first accepted plan instead of polishing preference |
| `TPC_P2_WORKERS` | `CPU - 1` | worker processes |

Two arms worth running once R1 exists, at a **reduced 2 h envelope** so each is ~2 h:

```bash
# A: cheap triage, more repair passes
TPC_P2_TRIAGE_CAP_SEC=60 .venv/bin/python scripts/phase2_full_run.py \
  --total-budget-sec 7200 --label "triage cap 60"
# B: fewer, longer solves
TPC_P2_MAX_QUERY_SEC=300 .venv/bin/python scripts/phase2_full_run.py \
  --total-budget-sec 7200 --label "per-query cap 300"
```

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

All three must be compared against a **2 h control** (`--total-budget-sec 7200`, no overrides), not
against R1.

### R5 — the held-out tripwire (once, and only after R1 is settled)

```bash
.venv/bin/python scripts/phase2_full_run.py \
  --split tpc_phase2_familiar_100_test --total-budget-sec 3600 --label "test tripwire"
```

20 records, so **coarse and high-variance**: a gap versus val is a prompt to investigate, never a
per-change signal. Run it at most once per submission. Note the envelope must scale with the split
— 20 queries in 5 h is not the same pressure as 100 in 5 h, so use 1 h.

### R6 — the packaged archive, end to end

The submission is a zip, not a working tree. Once R1 looks right:

```bash
.venv/bin/python scripts/assemble_phase2_submission.py --dry-run
.venv/bin/python scripts/assemble_phase2_submission.py --verify-budget-sec 120
```

The builder unpacks the archive into a temporary directory and runs the organizers' exact command
inside it with a stripped `PATH`. That checks the package, not the score.

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
