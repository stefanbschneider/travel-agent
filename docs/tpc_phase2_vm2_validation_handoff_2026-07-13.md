# VM2 handoff: validate plan-3 near-term items (N1-N7), 2026-07-13

You are running on the eval VM ("VM2") for the china-travel-agent repo (TPC @ IJCAI 2026 competition
entry). Read CLAUDE.md first — it defines the two-VM operating model: this machine (VM2) is the only
one allowed to run long e2e evals; the coding VM only does short/solver-free checks. You are here to
validate a batch of parser/orchestration changes that just landed on branch `stefan/phase2` (plan-3
near-term items N1-N7), which have only been checked with short/solver-free measurements so far.

## Setup

1. `git fetch && git checkout stefan/phase2 && git pull` — the commits you're validating are already
   pushed, most recent is `be037f37` ("phase2(plan3): correct N5 framing again..."). Confirm
   `git log --oneline -1` shows that SHA or later on this branch.
2. `.venv/bin/python -m pytest tests/phase2 -q` must be green before you run anything expensive — if
   it isn't, stop and report back rather than debugging it yourself (that's coding-VM work).
3. Confirm `DEEPINFRA_API_KEY` is set (check `.env`) — several runs below need the real LLM backend.

## What changed and why you're validating it

N1: `parser_vs_oracle.py` diff-metric hygiene fixes (taxi-default handling, hotel-distance
canonicalization). N2: a deterministic entity-resolution layer in `normalize.py` (behind
`TPC_P2_ENTITY_RESOLUTION`, defaults ON in the runner once a backend is configured). N3: four
targeted parser fixes (intercity-mode negation ordering, OR-arm/bare-imperative recovery, budget
wording, hotel_nearby distance tightening in `parsed_verifier.py`). N4: a deterministic merge guard
in `normalize.py`'s LLM-audit patch application (`_guard_remove_patches` — a `remove` patch is now
rejected unless paired with an opposite-polarity add/replace, or whitelisted) plus a prompt reframe.
N5: read-only HF generalization probe (no code path changes, skip). N6/N7: retry-count fix and test
infra (no e2e-relevant behavior change, skip).

All of this was validated only with `docs/tpc_phase2_eval.md`'s solver-free rung (a): the full-val
`parser_vs_oracle.py --behavioral` report and 3 live DeepInfra pytest smokes. Rungs (b)-(d) of the
measurement ladder — diff-eval splice, fastfpr row, canonical 300s row — were explicitly deferred to
you. Read `docs/tpc_phase2_eval.md` and `docs/tpc_phase2_plan3.md` (N1-N7 sections, all tagged
`[landed 2026-07-13...]`) for full detail before you start; don't just trust this summary.

Note: per CLAUDE.md, differential eval and tiny-budget smokes are actually permitted on the coding
VM too — routing steps 1 and 3 below to VM2 as well is a convenience (one agent runs the whole
validation batch end to end), not a hard requirement. Don't worry about this either way; just run
the batch here.

## Runs, in priority order

**1. Differential e2e splice (rung b) — cheapest, do this first.**

```
.venv/bin/python scripts/phase2_diff_eval.py \
  --baseline docs/phase2_baselines/runs/20260712T060018Z.json \
  --unsafe-allow-solver-drift --parallel 4
```

(`--parallel 4` uses all 4 cores — this run isn't being compared against a fixed-parallelism
baseline, it's exploratory, so there's no reason to hold a core back.)

`--unsafe-allow-solver-drift` is required: N3.4 touched `chinatravel/agent/tpc_agent/parsed_verifier.py`
and the N2 wiring touched `orchestrator.py`/`solve_phase2.py`, both outside `phase2_diff_eval.py`'s
`PARSE_ONLY_ALLOWLIST` (only `parse_constraints.py`/`normalize.py`/`schema.py` are in it), so the
splice's "unchanged uids reproduce byte-for-byte" assumption is not guaranteed — treat this run's
projected FPR as **exploratory/directional, not gate-quality**. It's still useful: it re-solves only
uids whose parse changed and is fast (minutes). Report the projected FPR delta and the list of flips
(which uids flipped pass/fail and why, from the per-uid family-diff context it prints).

**2. Canonical 300s gate row (rung d) — the real gate.**

Match the baseline row `docs/phase2_baselines/runs/20260712T060018Z.json` on everything that
affects the *result*: split=val, fold=0, folds=10, budget=300s, repeats=2, branch_aware=false,
n=85. That row was itself produced at `parallel=3` (one core deliberately left free); use
`parallel=4` instead to use all 4 cores on this box. Parallelism is a pure throughput knob — each
worker still gets its own CP-SAT process on its own core either way — so it doesn't change what's
being measured (unlike budget_sec, flags, or fold selection, which do), it just finishes faster.
Use the pinned-worktree variant so the row's `git_sha` is truthful and your main tree stays free:

```
make phase2-baseline-at SHA=be037f37 FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_REPEATS=2 \
  P2_PARALLEL=4 P2_LABEL=plan3-n1n7-gate
```

This takes hours — use `make phase2-progress FOLD=0 P2_FOLDS=10 P2_REPEATS=2
P2_PROGRESS_ARGS=--watch` to check on it, don't poll by re-running the baseline command.

Before gating, check the LLM-backend/flag config actually used matches the 2026-07-12 baseline's
(CLAUDE.md's measurement-hygiene rule: only compare rows with matching `llm_backend`/`llm_parse`/
budget). Per CLAUDE.md, several flags (disjunction, entity_resolution) default ON inside
`solve_phase2.py::run_split` once `TPC_P2_LLM_BACKEND` is set — if the original canonical row was
produced the same way (just setting the backend env var and letting the runner's own defaults apply),
you should do the same rather than hand-setting flags, so N2's entity-resolution default-on is
naturally included for this commit (it wasn't for the baseline, which predates N2 — that's expected
and correct, that's exactly what you're testing).

Once done, extract `{"fpr":..., "parse_failures":..., "timeouts":...}` from both the new row and the
baseline row (see `docs/tpc_phase2_eval.md`'s regression-gate section for the exact shape
`phase2_gate.py` expects) and run:

```
make phase2-gate BASELINE=<baseline_metrics.json> CANDIDATE=<new_metrics.json>
```

Report pass/fail and the reasons if it fails.

**3. N4 cheap LLM-parse probe — do this regardless of how (1)/(2) turn out, it's specifically for N4.**

```
.venv/bin/python scripts/phase2_llm_parse_probe.py --limit 850 --max-probes 40
```

This scans the full val split for behavioral disagreements, probes ~40 of them plus ~40 matched
control (already-agreeing) uids through the live LLM-audit path (one call each, cheap), and reports
how many disagreements get fixed vs how many previously-correct parses regress. This is the specific
acceptance check N4's plan section calls for before the merge guard can be trusted at scale. Report
the fixed/broke counts plainly.

**4. Paid full-val `--llm-parse` report — only if (3) looks promising, and confirm with the user
first if cost is a concern (~100 min run, this is the expensive one).**

This refreshes the stale 0.8694 LLM-audit accept-side number and is the real verdict input for M2
(`docs/tpc_phase2_plan3.md`'s M2 section) as well as N4's own promotion decision. Don't run this
speculatively — only if step 3's probe result makes it worth the spend, or the user explicitly asks
for it in your next check-in.

## What NOT to do

- Don't fix, tune, or touch parser code based on what you find — that's coding-VM work. Your job is
  to measure and report, not to close the loop yourself.
- Don't tune anything against the HF `LAMDA-NeSy/ChinaTravel` dataset if you touch it — it's a
  measurement set only (see N5 in the plan doc).
- Follow the commit conventions in CLAUDE.md: commit each new baseline-ledger row under
  `docs/phase2_baselines/` with a `phase2(plan3 validation): ...` message and push to
  `stefan/phase2` as you go, same as the coding-VM side has been doing. Never create/push a
  `phase2-eval-ledger` branch.

## Report back

For each run: what you ran, the exact command, the resulting numbers, and — for the gate — pass/fail
with reasons. If anything is ambiguous (e.g. you can't tell what flag config produced the 2026-07-12
baseline), say so explicitly rather than guessing silently.

## Estimated timing (4 CPUs on VM2)

**Only steps 1 and 2 actually use multiple cores.** Both spawn one CP-SAT/TPCAgent solve process
per `--parallel`/`P2_PARALLEL` worker, so throughput scales with cores. Steps 3 and 4 are plain
sequential Python scripts making one LLM API call at a time — neither `phase2_llm_parse_probe.py`
nor `parser_vs_oracle.py --llm-parse` has a `--parallel` flag, and there's nothing to solve, so
they run on a single core regardless of how many are free; their wall-clock time is bounded by
DeepInfra request latency, not local compute. (Adding concurrency to those two scripts would be a
real speedup opportunity, but it's a code change — out of scope for a measurement-only VM2 run;
flag it back to the coding VM if steps 3/4 latency becomes a bottleneck worth fixing.)

| Step | Cores used | Estimate | Basis |
| --- | --- | --- | --- |
| 1. Diff-eval splice | 4 (`--parallel 4`) | 10-35 min | Only uids whose parse fingerprint changed get re-solved (a subset of the 85-uid fold), each up to the baseline's 300s budget. Exact time scales with how many of the 85 uids N1-N4 actually touched. |
| 2. Canonical 300s gate row | 4 (`P2_PARALLEL=4`) | ~5.5-6.5 h | The `20260712T060018Z` baseline (same config, both end-to-end + solver-only modes, 85 uids x 2 repeats) took ~7.5h at `parallel=3`; using all 4 cores instead of 3 is a ~25% throughput gain (near-linear for independent CPU-bound solve processes with no other load on the box), so expect roughly 3/4 of that wall-clock time. |
| 3. N4 cheap probe | 1 (no parallel option) | 10-20 min | ~80 total LLM calls (40 disagreement + 40 control), sequential, bounded by DeepInfra request latency, not compute. |
| 4. Paid full-val `--llm-parse` (conditional) | 1 (no parallel option) | ~100 min | Stated directly in `docs/tpc_phase2_plan3.md`'s N4/M2 sections (cold cache, one call per val uid, sequential). |
| **Total (steps 1-3 only)** | | **~6-7.5 h** | Sequential sum; step 2 dominates. |
| **Total (all four)** | | **~7.5-9 h** | Only if step 4 is triggered. |

Step 2 is the long pole by a wide margin. Steps 3 and 4 are single-core/network-bound, so there's
no resource conflict running either of them **concurrently with step 2** in another shell — kick
off step 2 first, then run step 3 (and step 4, if triggered) alongside it, since neither competes
for CPU in any way that matters. Step 1 also wants all 4 cores (`--parallel 4`), so don't run it
concurrently with step 2 — either run it first (it's short) or drop it to `--parallel 1` if you do
want it running in the background while step 2 has the other cores.

---

**Once every step above is complete and reported, delete this file** (`git rm` it, commit, push) —
it's a one-time handoff artifact, not a durable doc; don't leave it lying around after it's served
its purpose.
