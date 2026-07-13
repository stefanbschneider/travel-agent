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
  --unsafe-allow-solver-drift --parallel 3
```

`--unsafe-allow-solver-drift` is required: N3.4 touched `chinatravel/agent/tpc_agent/parsed_verifier.py`
and the N2 wiring touched `orchestrator.py`/`solve_phase2.py`, both outside `phase2_diff_eval.py`'s
`PARSE_ONLY_ALLOWLIST` (only `parse_constraints.py`/`normalize.py`/`schema.py` are in it), so the
splice's "unchanged uids reproduce byte-for-byte" assumption is not guaranteed — treat this run's
projected FPR as **exploratory/directional, not gate-quality**. It's still useful: it re-solves only
uids whose parse changed and is fast (minutes). Report the projected FPR delta and the list of flips
(which uids flipped pass/fail and why, from the per-uid family-diff context it prints).

**2. Canonical 300s gate row (rung d) — the real gate.**

Match the baseline row `docs/phase2_baselines/runs/20260712T060018Z.json` exactly: split=val, fold=0,
folds=10, budget=300s, repeats=2, branch_aware=false, n=85, parallel=3 (that row was itself produced
at parallel=3 — match it for apples-to-apples timing and to avoid introducing a second variable).
Use the pinned-worktree variant so the row's `git_sha` is truthful and your main tree stays free:

```
make phase2-baseline-at SHA=be037f37 FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_REPEATS=2 \
  P2_PARALLEL=3 P2_LABEL=plan3-n1n7-gate
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

## Estimated timing (4 CPUs, `parallel=3`)

| Step | Estimate | Basis |
| --- | --- | --- |
| 1. Diff-eval splice | 15-45 min | Only uids whose parse fingerprint changed get re-solved (a subset of the 85-uid fold), each up to the baseline's 300s budget, at parallel=3. Exact time scales with how many of the 85 uids N1-N4 actually touched. |
| 2. Canonical 300s gate row | ~7-8 h | This exact config (fold 0, 85 uids, 2 repeats, both end-to-end + solver-only modes, parallel=3) is what produced the `20260712T060018Z` baseline, which CLAUDE.md documents as taking ~7.5h — same hardware profile, so expect the same order of magnitude. |
| 3. N4 cheap probe | 10-20 min | ~80 total LLM calls (40 disagreement + 40 control), no solver time at all — bounded by DeepInfra request latency, not compute. |
| 4. Paid full-val `--llm-parse` (conditional) | ~100 min | Stated directly in `docs/tpc_phase2_plan3.md`'s N4/M2 sections (cold cache, one call per val uid). |
| **Total (steps 1-3 only)** | **~8-9 h** | Sequential sum; step 2 dominates. |
| **Total (all four)** | **~9.5-10.5 h** | Only if step 4 is triggered. |

Step 2 is the long pole by a wide margin — if wall-clock matters, kick it off first and run steps 1
and 3 while it's in flight (they don't touch the same run directory, so nothing conflicts), rather
than running everything strictly in the priority order above.

---

**Once every step above is complete and reported, delete this file** (`git rm` it, commit, push) —
it's a one-time handoff artifact, not a durable doc; don't leave it lying around after it's served
its purpose.
