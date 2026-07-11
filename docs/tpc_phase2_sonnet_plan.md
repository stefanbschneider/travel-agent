# Phase 2 Improvement Plan (autonomous implementation)

This is a self-contained, step-by-step plan for improving the Phase 2 agent. It is written so a
separate agent (Sonnet 5) can execute it autonomously, without access to the conversation that
produced it. Read this whole file before starting. Background docs (read as needed, not required
up front): `docs/tpc_phase2_design.md` (architecture), `docs/tpc_phase2_eval.md` (measurement
methodology), `docs/tpc_phase2_implementation_plan.md` (build log + history).

## Context in five sentences

The Phase 2 agent parses a natural-language travel query into solver constraints (Stage 1),
solves deterministically with the existing `TPCAgent` + CP-SAT (Stage 2), has a stubbed
improvement stage (Stage 3), and always finalizes to a schema-valid plan (Stage 4); the
orchestrator is `chinatravel/agent/phase2/orchestrator.py` and the per-query runner is
`agent_env/scripts/solve_phase2.py`. The organizers will run this harness query-by-query on
held-out queries, with oracle constraint fields hidden, under a per-query time budget (~900s
primary / ~300s alternative, unconfirmed), 5 runs averaged, LLM = Qwen3.6-27B via an
OpenAI-compatible SGLang endpoint. Current measured state (2026-07-11): end-to-end FPR **85.88**
vs solver-only (oracle constraints) **94.12** vs ceiling 100 on val fold 0 (n=85, 60s budget,
deterministic parser + disjunction) — parsing loss (8.24 FPR pts) exceeds solver headroom (5.88).
The LLM corrective-audit parse (DeepInfra `Qwen/Qwen3.6-27B`, thinking off) raises full-val
(n=850) behavioral agreement **0.7788 → 0.8694** in the solver-free measurement, but its
end-to-end effect has never been measured (the one ledger row labeled `llm_parse=true` was a
silent-404 artifact; see the Step 8 writeup in `docs/tpc_phase2_implementation_plan.md`).
Everything below either fixes a known concrete defect or lands one prioritized measurement.

## Ground rules (violating these invalidates results)

1. **Working directory / branch:** repo root is the project root. Work on the current branch
   (`stefan/phase2`) unless told otherwise. Commit after each completed step with a
   `phase2(sonnet-plan step N): ...` message; do not push unless asked.
2. **Tests:** `.venv/bin/python -m pytest` must be green before every commit (the default run
   excludes `integration`-marked tests). New behavior gets a test first (TDD is the repo
   convention for Phase 2).
3. **Flags-off invariant:** with all `TPC_P2_*` LLM flags off and library-default `Flags()`, the
   deterministic path must stay byte-identical. New behavior that changes the deterministic path
   (Step 1 below does) must be behind a flag that library `Flags()` defaults OFF and the runner
   (`solve_phase2.py::run_split`) defaults ON — the established pattern used by
   `TPC_P2_DISJUNCTION`.
4. **Measurement hygiene:**
   - Record every promoted measurement in the committed ledger via
     `make phase2-baseline FOLD=<i> P2_FOLDS=<n> P2_BUDGET=<sec> P2_REPEATS=<r> P2_LABEL=<tag>`
     (writes `docs/phase2_baselines/`). n ≥ 10 and repeats ≥ 2 for any row used in a decision.
   - Run the regression gate (`scripts/phase2_gate.py --baseline docs/phase2_baselines/runs/<base>.json
     --candidate docs/phase2_baselines/runs/<cand>.json`) against the stated baseline row before
     declaring a step done. Gate on `fpr`, `parse_failures`, `budget_overruns` — NOT on raw
     `timed_out` counts (those are by-design solve-restart-until-budget events and not comparable
     across different n).
   - **Never commit code changes while a baseline/rehearsal job is running.** The parent process
     imports parser code once at job start, but chunked subprocesses pick up on-disk changes
     mid-run, and the row's `git_sha` is stamped at write time — a mid-run commit silently
     produces a mixed-code, mislabeled row. Docs-only commits are fine.
   - Runtime scales ≈ `repeats × n × 1.9 × budget_sec` (the solve loop deliberately exhausts its
     slice in both modes). The machine has 4 cores — do not run two solver evals concurrently.
5. **LLM economics:** DeepInfra is paid. The API key is `INFRADEEP_API_KEY` in `.env` (backend
   name `infradeep`, model `Qwen/Qwen3.6-27B`; connectivity check: `python scripts/try_deepinfra.py`).
   Responses are disk-cached under `cache/phase2_llm_parse/` keyed by prompt hash, so re-running
   an *unchanged* prompt over val is free; **any prompt change invalidates the cache and a full
   850-uid run costs ~100 minutes of real API calls**. For prompt iterations, always measure first
   with `scripts/phase2_llm_parse_probe.py` (one call per probed uid) before any full-val run.
6. **Never touch the held-out test split** (`tpc_phase2_test.txt`, requires explicit
   `--split-set test`). All iteration happens on val.

## Current bottleneck assessment (why these steps, in this order)

- **B1 — wasted budget (deterministic, free win):** `chinatravel/agent/phase2/budget.py` statically
  gives parse ~28% and improve ~11% of the post-finalize budget, but deterministic parse takes
  ~1s and Stage 3 is a stub — the solver never gets that time back
  (`orchestrator.solve_phase2` uses `b.solve_sec` as a fixed slice). At 900s that is roughly
  300s of solve time thrown away per query; even at the 60s dev budget the solver gets ~33s of 60.
  Solver headroom (5.88 FPR pts) is partly an artifact of this.
- **B2 — no LLM/network timeout (competition reliability risk):** `llm_client.py` sets no request
  timeout and Stage 1 is not time-boxed in the orchestrator. A hung LLM call (a 116s outlier was
  observed live against DeepInfra) consumes unbounded wall-clock inside the parse stage. Under the
  organizers' harness this can burn most of a query's budget before the solver starts.
- **B3 — the headline LLM-parse gain is unmeasured e2e:** behavioral agreement 0.7788 → 0.8694 is
  solver-free evidence; whether it moves end-to-end FPR is unknown. Cheap to measure now (warm
  LLM cache; thinking mode disabled).
- **B4 — measurement realism:** every attribution row so far used a 60s dev budget. At the real
  300–900s budget, solver headroom should shrink and parsing loss should dominate even more —
  but that has never been confirmed.
- **B5 — localized parser family gaps:** latest full-val family stats
  (`cache/phase2_parser_vs_oracle/parser_vs_oracle_tpc_phase2_val.json`, LLM-audit run):
  `poi_distance_hotel` is never extracted (matched 0, missing 32); `hotel_amenity` is
  spurious-only (spurious 22, matched 0 — the parser emits a family the oracle never uses);
  `required_hotel_all_types` (missing 26), `excluded_cuisine_types` (missing 22), `room_type`
  (missing 21), `stay_duration` (missing 19) are the other big recall sinks. 111/850 behavioral
  disagreements remain.
- **B6 — LLM-audit recall regression:** the corrective audit trades recall 0.6977 → 0.6779,
  concentrated in `poi_distance_hotel`, `required_hotel_all_types`, `required_hotel_any_types`
  (it removes families it shouldn't). Fixing B5's `poi_distance_hotel` extraction also shrinks
  this, but the prompt likely needs a guard too.
- Deferred (do NOT work on these): Stage 3 LLM refinement (only becomes relevant if, after Steps
  1–4, solver headroom exceeds parsing loss at a realistic budget), WorldEnv entity resolution
  (valuable but larger and lower certainty than B5's targeted fixes), SGLang endpoint parity
  (Step 7, config-only, do last).

---

## Step 1 — Dynamic budget reallocation: give unused parse/improve time to the solver

**Goal:** the solve stage's deadline should be computed from *actual* elapsed time, not the static
`split_budget` slices, so time the parse stage didn't use (and the improve slice, when
`llm_refine` is off) flows to the solver. Keep the hard finalize buffer.

**Files:** `chinatravel/agent/phase2/orchestrator.py` (main change),
`chinatravel/agent/phase2/budget.py` (helper if useful), `agent_env/scripts/solve_phase2.py`
(default the flag on in `run_split`), `tests/phase2/test_orchestrator.py` + `tests/phase2/test_budget.py`
(new tests), `tests/phase2/test_flags.py` (byte-identical invariant must still pass).

**Design:**

- New flag `TPC_P2_DYNAMIC_BUDGET` on `Flags` (library default OFF; `run_split` defaults it ON
  unless the env var is explicitly set — copy the `TPC_P2_DISJUNCTION` pattern exactly).
- When ON: after Stage 1 returns, compute
  `solve_sec = total_budget - elapsed_so_far - finalize_reserve - improve_reserve`, where
  `finalize_reserve = b.finalize_sec` and `improve_reserve = b.improve_sec if flags.llm_refine else 0`.
  Use that for both the `func_timeout` wrap and the `budget_sec` passed to `solve_fn`. Floor it at
  `b.solve_sec` (never give the solver *less* than the static split would have).
- When OFF: existing behavior, byte-identical.

**Tests:** with a spy `solve_fn` capturing `budget_sec`: (a) flag off ⇒ static slice passed;
(b) flag on, instant parse, `llm_refine` off ⇒ solver budget ≈ total − finalize reserve;
(c) flag on + `llm_refine` on ⇒ improve reserve is withheld; (d) flags-off byte-identical suite
still green.

**Measure & accept:** `make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=60 P2_LIMIT=20
P2_REPEATS=2 P2_LABEL=dynbudget-60s-n20` (~2.5h; leave code frozen while it runs). Gate vs run
`20260710T144747Z` (the last n=20/60s row). Accept if the gate passes; expect solver-only and e2e
FPR to improve or hold (the solver now gets ~52s of 60 instead of ~33s). Update the docs' status
sections with the measured row (see "Doc upkeep" at the end).

## Step 2 — LLM request timeout + parse-stage time-box

**Goal:** no single LLM/network call can hang the harness; the parse stage respects its slice.

**Files:** `chinatravel/agent/phase2/llm_client.py`, `chinatravel/agent/phase2/normalize.py`,
`chinatravel/agent/phase2/orchestrator.py`, `tests/phase2/test_llm_client.py`,
`tests/phase2/test_orchestrator.py`.

**Design:**

- `OpenAILLMClient.__init__`: pass `timeout=<seconds>` and `max_retries=1` to the OpenAI SDK
  client constructor. Default from env `TPC_P2_LLM_TIMEOUT_SEC` (default 30.0), overridable via
  the existing config dict. This alone bounds the hang.
- `parse_to_ir` already catches any `llm_parse_stub` exception and keeps the deterministic IR, so
  a timeout raise degrades correctly — verify with a test that a client raising
  `TimeoutError`/`APITimeoutError` yields the deterministic parse and sets `ir.llm_parse_error`
  (which already flows to the `llm_parse_failed` telemetry counter).
- Orchestrator: pass the parse deadline into Stage 1 — skip the LLM call entirely when the
  remaining parse slice is below the LLM timeout (a cheap deterministic check inside
  `llm_parse_stub`'s call site, e.g. a `deadline` param on `parse_to_ir`; record
  `llm_parse_skipped_deadline` in telemetry). Do NOT wrap the whole parse stage in
  `func_timeout` (it leaks threads on timeout; the repo has prior findings on this — the SDK
  timeout is the actual bound).

**Tests:** mocked client with injected delay/raise: deterministic parse survives; skip-on-tight-
deadline works; `none`/`fixture` backends unaffected; no network in unit tests (use the existing
`no_network` fixture).

**Measure & accept:** unit tests only (this is a robustness change; the deterministic path is
untouched, and the LLM path's behavior only changes under failure). Confirm
`.venv/bin/python -m pytest` green. No ledger row needed.

## Step 3 — Measure the LLM-parse effect end-to-end (the missing headline measurement)

**Goal:** answer whether the 0.7788 → 0.8694 behavioral-agreement gain moves end-to-end FPR.

**Prereq:** Steps 1–2 landed and committed (so the measured configuration is the one we'd ship).
Verify DeepInfra connectivity (`python scripts/try_deepinfra.py`) and that
`cache/phase2_llm_parse/` is populated (it is, from the full-val audit run — warm cache means the
e2e run's LLM calls are mostly free and byte-deterministic).

**Run:** `TPC_P2_LLM_BACKEND=infradeep make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=60
P2_REPEATS=2 P2_LABEL=llmparse-real-dynbudget-fullfold0-60s` (~5.5h at n=85; freeze code while it
runs). **Sanity-check the row before trusting it:** `timing_llm_parse_attempted` must be ~85·2 and
`timing_llm_parse_failed` must be ~0 — if failures are high, the backend is broken again (see the
Step 8 incident in `docs/tpc_phase2_implementation_plan.md`); fix before re-running.

**Gate:** vs run `20260711T000602Z` on fpr / parse_failures / budget_overruns.

**Interpretation & next action:**
- If e2e FPR improves meaningfully (≥ ~2 pts, outside the ±1.8 repeat std): parsing work is
  paying through; continue to Steps 4–6.
- If flat: the remaining parsing loss is concentrated in queries the audit doesn't fix (the 111
  disagreements) or in verifier/solver interaction — Step 5's triage becomes the priority; still
  continue in order.
- Either way, record the conclusion in the docs (this row finally closes the design doc's open
  "does LLM-parse move e2e FPR" question).

## Step 4 — One realistic-budget attribution row (300s)

**Goal:** confirm the parsing-dominant attribution at a budget shaped like the competition's.

**Run:** `TPC_P2_LLM_BACKEND=infradeep make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=300
P2_LIMIT=20 P2_REPEATS=2 P2_LABEL=llmparse-dynbudget-300s-n20` — estimate ~6.5h
(2 × 20 × 1.9 × 300s ÷ [some parallelism from `P2_PARALLEL` chunk workers; check
`scripts/rehearse_phase2.py` — with 4 cores and chunked subprocesses the wall clock may be
~half that]). This is the longest run in the plan; start it at a natural break (e.g. end of a
work session) and do not commit code while it runs.

**Accept:** row recorded; write the new solver-headroom vs parsing-loss split into
`docs/tpc_phase2_design.md`'s status section. Decision rule recorded for later: if solver
headroom at 300s ≥ parsing loss, Stage 3 refinement moves up the priority list; otherwise it
stays deferred.

## Step 5 — Close the biggest deterministic parser family gaps

**Goal:** attack B5 with the same TDD approach that worked for Milestones 5/1c. Work through
these substeps in order; each is small, solver-free to measure, and independently committable.

**Diagnosis tooling:** `python scripts/parser_vs_oracle.py --split-set val --behavioral
--disjunction --branch-aware` (~20s, no LLM, no solver) regenerates
`cache/phase2_parser_vs_oracle/parser_vs_oracle_tpc_phase2_val.{json,csv}`; `family_stats` has
per-family missing/spurious/wrong-value counts with example uids, and `behavioral.disagreements`
lists the disagreeing uids. To inspect a uid's NL text and oracle constraints, load it via
`chinatravel/data/load_datasets.load_query` (see `scripts/run_query.py` for the pattern) —
oracle fields are fine here, this is offline diagnosis, not the agent path.

- **5a. `poi_distance_hotel` extraction (matched 0 / missing 32).** The parser has no extractor
  for "hotel within X km of Y"-style constraints at all. Look at the oracle encodings for the 32
  example uids to learn the target schema, write failing tests from real val phrasings in
  `tests/phase2/test_parser_accuracy.py`, implement in `parse_constraints.py::parse_query_no_oracle`'s
  family extractors, keep the negation guards pattern (`_negated_before`/`_truncate_at_negation`).
- **5b. `hotel_amenity` spurious-only family (spurious 22 / matched 0).** The oracle never emits
  this family — check whether the parsed verifier even evaluates it and whether it can reject
  plans the oracle accepts (that would be direct behavioral loss). If it is dead weight, stop
  emitting it (or stop enforcing it in `parsed_verifier.py`, mirroring the vacuous-oracle
  precedent from roadmap 1c). If the oracle encodes amenities under a different family, remap.
- **5c. Recall sinks `required_hotel_all_types` (26), `excluded_cuisine_types` (22), `room_type`
  (21), `stay_duration` (19).** Same triage recipe per family: read example-uid NL vs oracle,
  fix extraction or mapping, test-first.
- **5d. Re-triage behavioral disagreements.** After 5a–5c, rerun the report and bucket the
  remaining disagreeing uids (spot-check ~15) into parser-fixable vs verifier-semantics vs
  needs-LLM. Fix any cheap verifier-semantics bugs found (precedent: the taxi vacuity fix).

**Guard:** `parse_constraints.py` is shared with the Phase-1 oracle path — after each substep run
the full test suite and confirm no `parse_query` (oracle-mode) regressions (there are existing
tests; Milestone 5 documents the acceptable-change precedent).

**Measure & accept per substep:** full-val `parser_vs_oracle` (deterministic, no `--llm-parse`):
behavioral agreement must not drop; the targeted family's missing/spurious count must fall.
Cumulative target for Step 5: deterministic behavioral agreement 0.7788 → ≥ 0.80. After the last
substep, one paid `--llm-parse` full-val run (~100 min; prompt unchanged ⇒ cache partially warm,
only uids whose deterministic parse changed re-call the LLM) to refresh the combined number.

## Step 6 — Fix the LLM-audit recall regression

**Goal:** stop the corrective audit from deleting real constraints (289 vs 216 missing,
concentrated in `poi_distance_hotel`, `required_hotel_all_types`, `required_hotel_any_types`).

**Note:** do this AFTER Step 5 — 5a may remove most of the `poi_distance_hotel` component (the
LLM can't delete a family whose deterministic extraction now matches the oracle, and the audit
prompt lists extracted families).

**Files:** `chinatravel/agent/phase2/normalize.py` (`build_llm_parse_prompt` and/or the patch
merge logic), `tests/phase2/` (patch-merge unit tests with the `fixture` backend).

**Design options (pick after looking at ~10 concrete removals in the probe output):**
1. Prompt guard: instruct that a `remove` patch requires quoting the NL span that *contradicts*
   the family, not merely failing to find support (recall-preserving asymmetry).
2. Deterministic guard: reject `remove` patches for families whose extraction came from a
   high-precision extractor (e.g. the Step-5a distance extractor), whitelisted in the merge code.

**Measure & accept:** `scripts/phase2_llm_parse_probe.py` on uids where the audit currently
removes real families (cheap, ~1 call/uid) — removals stop, previous fixes retained. Then ONE
full-val `--llm-parse` run (prompt changed ⇒ cold cache, ~100 min paid): accept if recall
recovers toward the deterministic number while behavioral agreement stays ≥ 0.8694's
then-current equivalent (it should improve, since Step 5 raised the deterministic floor).

## Step 7 — SGLang endpoint parity (config-only, do last)

**Goal:** eliminate submission-day surprises: the competition LLM is the organizers' SGLang
endpoint, not DeepInfra.

**Work:** add an `sglang` preset to `build_llm_client` config handling (it is just the `openai`
backend with a different `base_url`/`api_key_env`; the `extra_body chat_template_kwargs
enable_thinking=false` convention IS the SGLang convention, so keep it). Add a small
`scripts/try_sglang.py`-style smoke script (connectivity + one completion + verifies thinking is
off by token count), mirroring `scripts/try_deepinfra.py`. Unit-test the preset wiring with a
mocked client. Document the config switch in `docs/tpc_phase2_design.md`'s LLM section.

## Doc upkeep (applies to every step)

After each step with a measurement: update the status sections of `docs/tpc_phase2_design.md`
and/or `docs/tpc_phase2_implementation_plan.md` with the measured numbers and the ledger run id,
and keep `docs/phase2_baselines/` committed. The user expects docs to always reflect measured
state plus a prioritized recommendation for what's next. Keep this plan file itself updated:
mark steps DONE with a one-line result as you complete them.

## Definition of done for this plan

- Steps 1–3 complete with ledger rows and passed gates (core deliverable).
- Step 4's 300s attribution row recorded and interpreted.
- Step 5 lifts deterministic full-val behavioral agreement to ≥ 0.80 (stretch: LLM-audit
  combined ≥ 0.90 after Step 6).
- Steps 6–7 complete, or explicitly deferred with a written reason in this file.
- All work committed on the branch with green tests; docs current.
