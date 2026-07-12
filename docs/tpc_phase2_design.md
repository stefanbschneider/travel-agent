# TPC 2026 Phase 2 Design

This document is the **authoritative design** for the Phase 2 (final harness) system.

Companion docs:

- `docs/tpc_phase2_eval.md` — the evaluation methodology used to measure and iterate on this design
- `docs/tpc_phase1_playbook.md` — Phase 1 public-leaderboard strategy (oracle-guided)
- `AGENT_DESIGN.md` — shared overview of the deterministic planning core
- `IJCAI2026_competition.md` — source-based summary of the official competition pages

## Current implementation snapshot (2026-07-10)

The Phase 2 harness is no longer hypothetical. The following pieces are already implemented:

- `chinatravel/agent/phase2/orchestrator.py` owns the Stage 1–4 control loop
- `agent_env/scripts/solve_phase2.py` is the per-query runner
- deterministic no-oracle disjunctive expansion exists behind `TPC_P2_DISJUNCTION`
- `scripts/rehearse_phase2.py`, `scripts/parser_vs_oracle.py`, and `scripts/phase2_timing.py`
   provide rehearsal, parser diagnostics, and telemetry aggregation
- `scripts/phase2_record_baseline.py` + `make phase2-baseline` persist deterministic baseline metrics
   to committed history files under `docs/phase2_baselines/` (fresh-run semantics, `--repeats`
   score variance, `--label` tagging)

First trustworthy deterministic baseline (fold 0, n=20, 60s budget, run `20260710T124113Z`):
end-to-end FPR **85.0** vs solver-only **95.0** vs ceiling 100 — parsing loss (10 pts) is twice the
solver headroom (5 pts), and run-to-run e2e variance is ~0.09 score points. Stage 1 parsing is the
confirmed priority; details in `docs/tpc_phase2_eval.md`.

**2026-07-10 (later same day) update — memory + LLM-parse robustness + a full-val OR-detection
fix:**

- The in-process rehearsal memory ceiling (~26 cumulative solves) is resolved: `llms.py`'s
  torch/vllm imports are now lazy (single-uid solver-only RSS 898MB → 281MB), and
  `rehearse_phase2.py` runs both modes as chunked subprocesses so a leaked func_timeout
  thread/whatever a chunk accumulates is reclaimed by the OS at chunk exit instead of compounding
  across an entire fold. See "Current Gaps To Close" below for the full root-cause writeup.
- `orchestrator.solve_phase2`'s parse stage previously discarded a perfectly good deterministic
  parse (`variants=[]`) on ANY exception, including a transient LLM failure — `llm_parse_stub` is
  documented to raise on error "so the orchestrator can degrade safely," but nothing actually kept
  the pre-call `ir` near that raise. Fixed in `parse_to_ir`. This was the correctness prerequisite
  for defaulting `TPC_P2_LLM_PARSE` on, which `solve_phase2.py::run_split` now does once a backend
  is configured (mirroring the existing `TPC_P2_DISJUNCTION` default-on pattern). LLM responses are
  cached by default (`CachingLLMClient`, `TPC_P2_LLM_CACHE=0` to disable) so warm reruns are free
  and byte-deterministic.
- The deterministic disjunction detector missed bare "(must/need to) satisfy one of the following"
  phrasing (6/850 val queries), plus two more bugs found diagnosing the same case (a label word
  leaking into an OR arm's text; a type-keyword substring match misfiring on a proper-noun venue
  name). Full-val behavioral agreement (LLM off): 0.7565 → 0.7788.

**2026-07-11 update — full-fold baseline (run `20260711T000602Z`, fold 0, n=85, 60s), and a
`llm_parse=true` mislabel found and fixed:** end-to-end FPR **85.88** vs solver-only **94.12** vs
ceiling 100 — flat vs the n=20 baseline (85.0) and within this row's own repeat noise
(`e2e_fpr_std=1.76`); regression gate vs `20260710T144747Z` passed
(fpr/parse_failures/budget_overruns all held or improved). This row is a **valid deterministic +
disjunction baseline**, but its `llm_parse=true`/`llm_backend=infradeep` label is misleading: the
infradeep backend's default model string was broken (`"qwen3.6-27b"`, no org prefix — DeepInfra
404'd it as "model ... does not exist"; correct id is `Qwen/Qwen3.6-27B`), so every LLM audit call
in this run silently failed and fell back to the deterministic parse via `parse_to_ir`'s
by-design fallback-on-exception. The non-trivial `stage_sec.parse` latency (0.47–1.26s) that was
initially read as proof the LLM ran was actually just the round-trip time of a failing 404
request — a parse-latency check cannot distinguish "call succeeded" from "call failed over the
network," which is exactly why this went unnoticed. Fixed in a follow-up commit (default model
string + a new `llm_parse_failed` telemetry counter so a broken backend shows up as a nonzero
count instead of passing silently). See `docs/tpc_phase2_implementation_plan.md` (Step 8) for the
full incident writeup and the corrected LLM-parse measurement once it lands.

**2026-07-11 update — the corrected LLM-parse measurement:** `Qwen/Qwen3.6-27B` also runs in
"thinking mode" by default on DeepInfra (a full chain-of-thought before every answer, verified
live: 10.6s/232 tokens with thinking vs 1.1s/9 tokens without, same prompt) — with it on, a full
850-uid val audit was projected at ~9h; disabling it (`extra_body:
{"chat_template_kwargs": {"enable_thinking": false}}`, now the infradeep default) brought a real
run down to ~100 minutes, matching the plan's original estimate. Result
(`scripts/parser_vs_oracle.py --llm-parse`, n=850, warm-cache rerun byte-identical): behavioral
agreement **0.7788 → 0.8694** (top of the plan's hoped-for 0.80–0.85 range),
`disjunction_flattened` 134 → 80, precision/f1/value_accuracy all up; recall trades down slightly
(0.6977 → 0.6779). Full numbers in `docs/tpc_phase2_eval.md`. Since this demonstrates a real
parsing-quality gain, an e2e re-run of Step 8 (same fold/n/budget as `20260711T000602Z`, this time
with a genuinely working LLM backend) follows to see whether it moves the harness's own FPR.

**2026-07-11 update — the genuine Step 8 e2e re-run (run `20260711T071751Z`) — regression, not a
win.** Same fold/n/budget as the mislabeled row, this time verified genuine
(`timing_llm_parse_failed=0`/85). **End-to-end FPR dropped 85.88 → 81.18; the regression gate vs
the mislabeled row failed.** The parser-level win (behavioral agreement 0.87) does not transfer to
the harness's own score at this 60s dev budget — those measure different things (parsed-vs-oracle
acceptance on a fixed plan, vs. whether a freshly bounded-time solve passes). Flipped-uid
diagnosis: some flips are timeout-driven (tighter/more-correct constraints, plus 54 more queries
now expanding into multiple solver-searched branches via `disjunction_flattened` dropping
134 → 80), but at least 2/5 pass→fail flips did **not** time out — CP-SAT's single-worker,
fixed-budget search is sensitive to the exact constraint formulation handed to it, so even a
*correct* simplification (removing a redundant constraint) can send the bounded search down a
different, non-passing trajectory. Whether this is specific to the 60s dev budget (vs. the
organizer's real ~900s) is unresolved and not something to test without authorization, given the
cost. Full mechanism writeup in `docs/tpc_phase2_eval.md`.

**2026-07-11 update — final-agent memory soak (single long-lived process, the actual competition
path):** `python agent_env/scripts/solve_phase2.py --split tpc_phase2_val --limit 150
--budget-sec 10 --method phase2_soak`, in-process (not chunked — this is the one runner mode Step
3's subprocess mitigation doesn't cover, since the real harness genuinely does run every query in
one process). **Measured:** RSS ranged 235–262 MB across all 150 queries, first→last delta 8.9 MB,
linear-fit slope 0.07 MB/query (≈70 MB extrapolated to 1000 queries) — flat, no monotone growth,
comfortably inside the ~500 MB acceptance bar. This held despite 128/150 (85%) solves hitting
`timed_out` (solve-slice exhaustion at the tight 10s budget, all recovered to valid plans) and 2/150
falling back — i.e. the `func_timeout` thread-leak concern from the chunked-rehearsal writeup above
does not reproduce at this scale in the single-process runner. Added a warn-only
`TPC_P2_MAX_RSS_MB` env guard to `run_split` (prints, never aborts, if a query's RSS grows past the
threshold since the process's first solved query) for future longer soaks; it stayed silent
throughout this run. No further escalation (func_timeout grace tuning, no-func-timeout mode,
chunked wrapper for the real runner) is needed on this evidence.

What remains incomplete is mostly Stage 1 quality and Stage 3 refinement:

- Stage 1 still starts from `parse_query_no_oracle()` and is therefore still dominated by the current
   regex parser
- the richer parser IR exists, but entity-resolution fields are still mostly scaffolding
- `TPC_P2_LLM_PARSE` now supports corrective proposals (replace/remove/add), OR-arm recovery input,
   and field alternatives/confidence; it still depends on deterministic re-parse + validation.
   **First live measurement (2026-07-10, Qwen3.6-27B via DeepInfra,
   `scripts/phase2_llm_parse_probe.py`):** on 8 behavioral-disagreement uids it fixed 4 and broke 0;
   on 6 correct-parse control uids it proposed no changes (0 regressions). The unfixed cases split
   into LLM conservatism (returned no patches) and non-parse causes (see gaps below).
- `TPC_P2_LLM_REFINE` is still a no-op placeholder

## Official Execution Model

Phase 2 differs from Phase 1 in five ways that drive the whole design:

1. Organizers run **our** harness **query by query**, not in batch.
2. The evaluation set is **held out** (unseen phrasing and possibly unseen cities).
3. Oracle verifier fields (`hard_logic`, `hard_logic_py`, `hard_logic_nl`) are **not visible** to the agent.
4. The harness runs under a **bounded per-query timeout**.
5. The model is **fixed to Qwen3.6-27B via SGLang (2×A800, no NVLink)**, and each harness is
   **run 5× and averaged**, so run-to-run variance matters.

Phase 2 is therefore **not a new planning problem**. It is a stronger **no-oracle parsing +
orchestration** problem wrapped around the existing deterministic solver.

## What The Baseline Harness Does

The organizer-style baseline in `agent_env/scripts/solve_script_with_harness.py`:

- loads one query locally,
- hides oracle-only fields from the visible prompt,
- delegates the whole solve to a generic agent runtime (`opencode` or `codex`),
- parses `<output>...</output>` JSON,
- writes the official result-file layout,
- runs the official local evaluators.

This is a useful compatibility reference and our **floor baseline**, but it is a prompt-only agent.
Our final submission inverts the control: **our harness owns the loop** and calls the LLM only for
targeted subproblems.

## High-Level Approach

**LLM-assisted parsing plus deterministic solving**, with optional bounded LLM-assisted refinement.

```text
Visible NL query
  -> Stage 1: hybrid parser (deterministic + optional LLM-assist)
  -> Parser IR (alt parses, OR-groups, confidence, raw spans, entity candidates)
  -> Normalization layer (validate/resolve vs WorldEnv)
  -> branch-local solver constraint variants
  -> Stage 2: deterministic TPCAgent + CP-SAT (TPC_USE_ORACLE=0)
  -> Stage 3: gated improvement (deterministic densify + optional bounded LLM refinement)
  -> Stage 4: finalize (hard time buffer + guaranteed-valid fallback)
  -> final JSON result
On any timeout/parse failure -> constraint-light feasible fallback -> finalize
(never emit a parse_failure zero when a schema-valid plan can be returned)
```

### Stage 1: Query Understanding

Input is the visible natural-language query only. Map it into structured constraints using a hybrid parser:

- deterministic extraction for stable patterns (current `parse_constraints.parse_query_no_oracle`),
- optional LLM assistance for paraphrases, compound clauses, and ambiguity,
- deterministic validation and normalization against the environment data.

The LLM here **proposes**; it does not decide. Every LLM-proposed constraint or entity is validated
against `WorldEnv` before it reaches the solver, which bounds hallucination risk and keeps the
deterministic verifier authoritative.

### Stage 2: Deterministic Planning

Feed normalized branch-local constraints into the existing `TPCAgent` + CP-SAT stack in **no-oracle
mode** (`TPC_USE_ORACLE=0`). This remains the primary planner because it is reproducible, cacheable,
debuggable, already strong on validity, and already designed around branch-local constraint reasoning.
Phase 2 reuses it as-is; it is **not** rewritten.

### Stage 3: Bounded Improvement

If a valid plan is found early enough, run a short improvement pass:

- deterministic densify and local swaps first (already inside `TPCAgent`),
- optional narrow LLM-guided refinement second,
- always acceptance-gated (never trade validity for preference),
- always stopped before a hard safety margin.

### Stage 4: Finalization

Validate the plan and always return a result before timeout. If solving fails or times out, return
the best plan produced so far, or a **constraint-light feasible fallback** — never a bare parse
failure when a schema-valid plan can be emitted. An empty `itinerary: []` is schema-valid and is the
last-resort floor.

## Module Layout

The Phase 2 harness lives in its own package so it can evolve without touching the shared solver:

- `chinatravel/agent/phase2/llm_client.py` — LLM client abstraction (backends: `none`/`fixture`/`openai`/`infradeep`)
- `chinatravel/agent/phase2/schema.py` — two-layer schema: parser IR + solver constraint dict
- `chinatravel/agent/phase2/normalize.py` — IR → branch-local solver variants (currently mostly a
   deterministic passthrough plus disjunction expansion; full WorldEnv-backed validation/entity
   resolution is still to be added)
- `chinatravel/agent/phase2/budget.py` — per-query time budgeting
- `chinatravel/agent/phase2/fallback.py` — guaranteed-valid fallback plan
- `chinatravel/agent/phase2/orchestrator.py` — Stage 1–4 control loop + telemetry
- `agent_env/scripts/solve_phase2.py` — per-query runner (oracle hidden, official output layout, resume-safe)
- `scripts/rehearse_phase2.py`, `scripts/parser_vs_oracle.py`, `scripts/phase2_timing.py` — evaluation pipeline (see `docs/tpc_phase2_eval.md`)

## LLM Client Abstraction And Model-Access Constraints

The final Phase 2 run uses the organizers' Qwen3.6-27B, exposed via SGLang as an **OpenAI-compatible
endpoint**. During development we do **not** have a general programmatic LLM API:

- Kiro / Copilot subscriptions are **interactive only** (not callable from inside a harness).
- A teammate has OpenRouter access (paid).
- A local Qwen VM may be set up later.

To work within these constraints, the LLM is behind a swappable client with three backends:

| Backend   | Purpose | Network |
| --------- | ------- | ------- |
| `none`    | Deterministic; no LLM. The default, the reliability floor, and the fallback path. | none |
| `fixture` | Replays cached LLM responses from disk (keyed by prompt/query hash). Lets us hand-produce parses interactively (via Kiro/Copilot) and replay them deterministically, and drives unit tests. | none |
| `openai`  | Real OpenAI-compatible endpoint. OpenRouter is just a `base_url` + `api_key_env` preset here; the organizers' SGLang and a local Qwen VM are other presets. | yes |

Default is `none`. Configuration reuses the existing `agent_env/config.toml` shape
(`base_url` + `api_key_env`, as already modeled for `opencode`/`codex`).

Design rule: **the deterministic path must be byte-identical when all LLM/improvement flags are off.**
The LLM is only consulted by Stage 1 (parse disambiguation) and Stage 3 (bounded refinement), and only
when its feature flag is on.

## Two-Layer Constraint Schema

Keep the **solver-facing** constraint format stable; enrich only the **parser-side** representation.

1. **Parser output schema (IR).** Used only inside the Phase 2 harness. Richer and uncertainty-aware:
   - alternative parses,
   - disjunctive groups,
   - confidence scores,
   - raw extracted spans,
   - entity-resolution candidates,
   - hard constraints vs softer preferences.

2. **Solver input schema.** Used by `TPCAgent`. Kept close to the current normalized dict shape
   (budgets, required/excluded entities, transport preferences, timing, hotel proximity, stay
   duration, etc.) so the solver never has to absorb parser ambiguity.

The **normalization layer** (`normalize.py`) is the bridge and is a first-class Phase 2 component. In
the skeleton it is a faithful passthrough of the current deterministic parse (so behavior is unchanged);
richer IR and disjunctive expansion are added later behind flags.

## Time Budgeting

**Organizers' stated budget: ~15 minutes (900s) primary, ~5 minutes (300s) alternative — to be
confirmed.** Our own working default (2026-07-11, chosen for baseline/CI iteration cost) is the
300s alternative — `chinatravel/agent/phase2/orchestrator.py` has
`DEFAULT_BUDGET_SEC = PHASE2_ALT_BUDGET_SEC` (300s); `PHASE2_ORGANIZER_BUDGET_SEC` (900s) remains
available for a final pre-submission check. Overridable per query via the `TPC_P2_BUDGET_SEC` env
var, the `budget_sec` argument, or `--budget-sec`/`P2_BUDGET` on the runner/rehearsal/Makefile.

Budget the per-query timeout explicitly rather than spending it in one undifferentiated loop
(`budget.py`). Suggested allocation:

- 20–30%: parsing and normalization
- 50–60%: deterministic solve and branch search
- 10–20%: optional improvement
- 5–10%: safety buffer for finalization and output

The harness always preserves a hard finalization buffer and returns before the timeout.

## Feature Flags (all default OFF; deterministic path unchanged when off)

| Flag (env var) | Default | Effect when ON |
| -------------- | ------- | -------------- |
| `TPC_P2_LLM_BACKEND` | `none` | Select LLM backend: `none` / `fixture` / `openai` / `infradeep`. |
| `TPC_P2_DISJUNCTION` | `0` | Enable true no-oracle disjunctive branch generation (Stage 1). Implemented (Milestone 4); deterministic NL splitting, one branch-local variant per OR arm. |
| `TPC_P2_LLM_PARSE` | `0` (library `Flags()`); **effectively `1`** in `solve_phase2.py::run_split` once a usable `TPC_P2_LLM_BACKEND` is configured, unless this var is set explicitly | Enable the LLM corrective-audit second-pass parse (Stage 1). Implemented; falls back to the deterministic parse on any LLM failure (see "Current Gaps To Close"). |
| `TPC_P2_LLM_REFINE` | `0` | Enable bounded LLM-guided plan refinement (Stage 3). Stub in skeleton. |
| `TPC_P2_BUDGET_SEC` | inherits per-query timeout | Total per-query time budget the orchestrator splits across stages. |

These are the extension points; the skeleton wires them as no-op stubs so improvements can be added and
measured incrementally without destabilizing the deterministic baseline.

## Current Gaps To Close (post-review, updated 2026-07-11)

> The prioritized closing plan for all gaps below is `docs/tpc_phase2_sonnet_plan.md`
> (2026-07-11 review; written to be executable autonomously).

0. **Two newly identified harness defects (2026-07-11 review):**
   - **Static budget slices waste solve time.** `budget.py` reserves ~28% of the post-finalize
     budget for parse and ~11% for improve, but deterministic parse takes ~1s and Stage 3 is a
     stub; the orchestrator passes the static `b.solve_sec` to the solver regardless of what
     earlier stages actually used. At 900s that discards roughly 300s of solve time per query.
     **Fixed 2026-07-12 (plan Step 1):** `TPC_P2_DYNAMIC_BUDGET` (library `Flags()` default OFF,
     `run_split` default ON, same pattern as `TPC_P2_DISJUNCTION`) recomputes the solve slice from
     actual elapsed time after Stage 1 -- `total - parse_elapsed - finalize_reserve -
     (improve_reserve if llm_refine else 0)`, floored at the static `solve_sec` -- instead of the
     fixed split. At 300s this returns roughly 100s/query (unused parse slice + the fully-unused
     improve slice) to the solver. Not yet re-measured end-to-end (next ledger row).
   - **No LLM request timeout; Stage 1 not deadline-enforced.** `llm_client.py` never sets an SDK
     timeout and the orchestrator does not time-box the parse stage, so one hung LLM/network call
     (a 116s outlier was observed live against DeepInfra) can consume most of a query's budget
     before the solver starts. Fix: SDK-level timeout + skip-LLM-when-slice-too-small (plan
     Step 2). The existing `parse_to_ir` fallback-on-exception already handles the raise safely.

1. **Regex-only brittleness remains the main Phase 2 risk.** The live Stage 1 path still starts from
   `parse_query_no_oracle()`, so held-out phrasing robustness is still mostly bounded by the current
   regex parser. A behavioral-disagreement triage (first 60 val queries: 8/60 disagree) decomposes
   the remaining Stage-1 loss into three concrete buckets:
   - **Negation/over-extraction regex bugs** producing spurious `required_*` families next to the
     correct `excluded_*` ones (e.g. "Do not wish to stay at the following hotels: X and Y" also
     emits a bogus `required_hotels`). **Resolved 2026-07-10 (roadmap 1c):** the Milestone-5 A2
     negation guard was extended to hotels and attractions via shared `_negated_before` /
     `_truncate_at_negation` helpers in `parse_constraints.py`.
   - **Parsed-verifier semantics mismatches**, e.g. a parse `{excluded_inner_transport: [taxi],
     taxi_cars_equals: 1}` failing an oracle-accepted best plan. **Resolved 2026-07-10 (roadmap 1c):**
     the real root cause was that the oracle's inner-transport exclusion scans top-level
     `activity_type=='transportation'` activities (never emitted) and is therefore vacuously true on
     all 76 val queries; `parsed_verifier.py` now mirrors that (and uses `innercity_transport_type`
     for taxi-ness), so it no longer over-constrains. Verifier fix, not parser fix.
   - **LLM-parse conservatism** (see gap 3).
2. **Normalization is not yet doing the intended WorldEnv-backed resolution work.** The IR and `env`
   hooks exist, but field-level entity resolution, validation, and confidence-aware normalization are
   still largely unimplemented.
3. **LLM parsing upgraded from conservative to corrective (2026-07-10).** First live probe
   (Qwen3.6-27B via DeepInfra) fixed 4/8 disagreements, 0 regressions, but in 3 of the 4 unfixed
   cases the LLM returned no patches despite removable spurious families. `build_llm_parse_prompt`
   was rewritten to make the model *audit each extracted family against the quoted NL* (locate the
   supporting span, check negation/polarity, confirm-or-remove) instead of optionally "refining".
   Re-measured live after the roadmap-1c deterministic fixes: **4/5 disagreements fixed, 0/5 control
   regressions** (controls unchanged). The remaining gap was OR-arm recovery on flattened-disjunction
   queries, not family auditing. **Resolved 2026-07-10 for the flagged probe uid
   (`20250321124345084418`)** — but by fixing the *deterministic* disjunction detector (it never
   recognized bare "satisfy one of the following" phrasing) rather than the LLM: the uid now
   behaviorally agrees with the oracle without any LLM call. `build_llm_parse_prompt` still gained
   an explicit OR-arm-recovery section + worked example as the fallback for phrasing beyond regex
   reach. Also fixed the plumbing gap that blocked defaulting this on: `parse_to_ir` now catches
   `llm_parse_stub`'s raise and keeps the deterministic `ir` instead of the caller discarding it
   entirely, and responses are cached (`CachingLLMClient`) so repeat runs are free. `TPC_P2_LLM_PARSE`
   now defaults on in `solve_phase2.py::run_split` once a backend is configured.
4. **Stage 3 refinement is still a stub.** Current Phase 2 performance is effectively deterministic
   TPCAgent plus fallback, not deterministic solve plus bounded refinement.
5. ~~Operational benchmarking is not yet mature.~~ **Resolved 2026-07-10:** the earlier solver-only
   instability was a measurement artifact of n=1 smoke rows plus stale-resume contamination; the
   baseline recorder now runs fresh by default, labels smoke rows, and records run-to-run score
   variance via `--repeats`. See `docs/tpc_phase2_eval.md` and `docs/phase2_baselines/README.md`.
6. ~~In-process rehearsal memory growth capped folds at ~26 cumulative solves.~~ **Resolved
   2026-07-10.** Two root causes, both fixed rather than worked around:
   - `chinatravel/agent/llms.py` imported `transformers`/`vllm` (→ torch, ~600MB) unconditionally at
     module top. `init_llm("TPCLLM")` is on the hot path for every Phase 2 solve (the deterministic
     orchestrator wires a stub backbone LLM), so every process paid that cost even though Phase 2
     never uses a local-model backend. Moved the imports into the local-model classes'
     (Deepseek/Qwen/Mistral/Llama) constructors. **Measured:** single-uid solver-only RSS
     898MB → 281MB.
   - A timed-out solve leaves a thread `func_timeout` cannot kill running in the background —
     verified directly (RSS still grows and a stray thread is still alive after the harness moves
     on from a timeout). Rather than chase the leak, `scripts/rehearse_phase2.py` now runs both
     end-to-end and solver-only rehearsal as chunked subprocesses (`P2_CHUNK` env, default 5); the
     OS reclaims whatever a chunk leaks when that chunk's process exits, so fold size is no longer
     memory-bounded regardless of cause. `agent_env/scripts/solve_phase2.py` gained `--uids-file`
     to support this; solver-only mode gained a self-exec `--worker solver-only` entry point since
     it had no standalone script.
   - Six modules building their own Accommodations/Restaurants/Attractions/... at import time were
     switched to a lazy-construction `LazyTool` proxy; the real duplication cost turned out to be
     modest (~10-20MB per redundant build, not the several-hundred-MB hypothesized), but it's a
     real win regardless.

## Step 5 parser-family diagnosis (2026-07-11, code-verified, not yet implemented)

Done ahead of implementation while a solver eval (`llmparse-disj-fullfold0-300s`, ~9h) held the
Phase 2 source frozen (chunked subprocesses re-import mid-run). Diagnosis only, read-only —
`scripts/parser_vs_oracle.py --disjunction --branch-aware` full-val report plus direct NL/oracle
inspection via `parser_vs_oracle.query_variants`/`load_datasets.load_query`. All six B5 families
were root-caused to specific code locations; none need a from-scratch extractor.

- **5a. `poi_distance_hotel` (missing 69, matched 0) — one-line fix, not a missing extractor.**
  `parse_constraints.py::parse_hotel_nearby` already extracts `{reference, distance_km}` correctly
  from "accommodation/hotel/stay within X km of Y" phrasing and stores it as `result["hotel_nearby"]`
  (singular dict) in `parse_single_constraint_text` (~line 922-924). The oracle-side DSL converter
  (`solver_constraints.py::_parse_hotel_distance`, oracle mode only) sets **both** `hotel_nearby` and
  `poi_distance_hotel` (as `[hotel_near]`) when it recognizes the `poi_distance(...)` DSL call — the
  no-oracle NL path never got the same list-mirroring. Fix: add
  `result["poi_distance_hotel"] = [hotel_near]` next to the existing `result["hotel_nearby"] = hotel_near`
  assignment. Secondary bug found in the same function: the reference-name capture sometimes keeps a
  leading "the " (e.g. "the Great Hall of the People" vs oracle's "Great Hall of the People"),
  which would show up as `wrong_value` once the list is populated — strip `^the\s+` from the
  captured reference (mirror the `_loc()` helper already used in `parse_activity_time_windows`).

- **5b. `hotel_amenity` (spurious 32) and `required_hotel_all_types` (missing 42, ~35 of them the
  same root cause) — remap, not enforcement-guard.** The oracle **never** emits `hotel_amenity`;
  amenity/facility preferences ("hotel with a swimming pool", "hotel with Free parking", "hotel with
  an Executive Lounge") are encoded by the oracle as `required_hotel_all_types` (e.g.
  `['Free parking']`, `['Swimming pool']`, `['Family Room']`) — literally the same string, just
  routed through the wrong family. Root cause: `parse_required_hotel_types` (the function that feeds
  `required_hotel_all_types`) only matches `hotel(s) of type X` / `hotel(s) that offer(s) X`; it has
  no pattern for `hotel(s) with X`, so that phrasing falls through to the separate
  `parse_hotel_amenity` function instead, which stores it under the dead-end `hotel_amenity` key.
  Fix: add a `hotels?\s+with\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)` pattern to
  `parse_required_hotel_types`'s `all_types` branch (reuse `_split_types`/`_cap_first`, plus strip a
  leading `a `/`an ` article before capitalizing — "a Sunbathing area" → "Sunbathing area"); then
  delete `parse_hotel_amenity` and its call site (`parse_constraints.py:974-976`) and the
  `hotel_amenity` enforcement branch in `parsed_verifier.py:170-171` (verified dead once the
  extractor is gone — it can only ever be populated by the function being deleted). Confirmed via
  direct uid inspection that the `required_hotel_all_types` "missing" bucket and the `hotel_amenity`
  "spurious" bucket are the same underlying queries (same "hotel with X" phrasing, same target
  string) — one fix closes both.

- **5c. `excluded_cuisine_types` (missing 30, wrong_value 5) — word-order gap + minor cleanup bugs.**
  `parse_excluded_cuisine_types` only matches `restaurant(s) of type(s) X` / `X cuisine restaurants`;
  the dominant missed phrasing is the reversed order `the following type(s) of restaurant(s): X`
  ("do not want to try the following types of restaurants: A and B"), which needs its own pattern
  (mirror `parse_cuisine_preference`'s already-correct `types?\s+of\s+restaurants?` pattern, negated).
  `wrong_value` bugs, all minor: (1) the `X cuisine restaurants` pattern's capture group drops the
  trailing word "cuisine" itself (`"fusion cuisine restaurants"` → captures `"fusion"`, oracle wants
  `"fusion cuisine"`) — capture should include the anchor word when it's "cuisine", not just "type";
  (2) split-on-comma doesn't also split on "and" before the last item (`"Bar/Pub, Other, and Halal
  cuisine"` → last item keeps a stray leading `"and "`) — extend the split regex to `,\s*(?:and\s+)?`
  like other extractors already do; (3) embedded double-quotes around quoted type names aren't
  stripped (`"Other Chinese Cuisine"` → literal `'"Other Chinese Cuisine"'`) — strip `"` before
  appending. One case (`"Bakery and Desserts"` split into `['Bakery', 'Desserts']`) needs a cuisine
  vocabulary lookup to disambiguate "and"-as-separator vs "and"-in-name; not worth building for one
  observed instance — leave as a known residual miss.

- **5d. `room_type` (missing 29, wrong_value 19) — two independent bugs, one fixable, one not.**
  (1) **Fixable, high-confidence:** the oracle's numeric `room_type` code → label mapping used in
  both `parse_constraints.py::parse_hard_logic` (~line 1211-1219) and
  `solver_constraints.py::_parse_room_type` (~line 280-286) is `{1: "single", 2: "double", 3:
  "twin"}`. A full scan of every `hard_logic_py` in `chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/`
  shows **only codes 1 and 2 ever appear** (74× code 1, 35× code 2, zero code 3), and every NL query
  whose oracle uses code 2 says "twin" ("twin beds room", "a twin room") — never "double bed". The
  no-oracle NL parser (`parse_room_type` in `parse_constraints.py`) already returns the literal
  `"twin"` for that phrasing, so today it disagrees with the oracle's (mislabeled) `"double"` on
  every single one of these — a pure label bug, not a parsing gap. Fix: relabel code 2 as `"twin"` in
  both places (code 3 can stay mapped to `"twin"` too, or be left/removed — it's never observed, so
  it's moot either way). This alone should close most of the 19 `wrong_value` cases.
  (2) **Not fixable from NL, don't chase:** a meaningful share of `missing` cases have **no room-type
  mention anywhere in the NL** yet the oracle still constrains `room_type` (e.g. a 5-person, no-room-
  mention query has oracle `room_type=single`) — evidently a hard_logic_py constraint independent of
  the stated preference (unlike `taxi_cars_equals`, which *is* a deterministic function of party size
  and is already defaulted). Checked whether the unstated default is at least people-count-driven:
  among the "missing" uids, the oracle value split is single 22 / double(→twin, per the mapping fix
  above) 13 / twin 3 — not a clean function of `people_number`, so no safe default exists. Leave
  as-is; this is a real, roughly ~40%-of-missing ceiling on this family, not a bug.

- **5e (bonus, found while diagnosing 5c-adjacent `stay_duration`, missing 4 / wrong_value 3).**
  (1) `parse_stay_duration`'s `stay at X for (at least) N minutes` pattern doesn't accept "for no
  less than N minutes" (only "for at least N minutes") — extend the optional-phrase group to
  `(?:at\s+least\s+|no\s+less\s+than\s+)?`. It also has no pattern at all for "a stay of at least N
  minutes at X" (reversed order) — needs a new `finditer` pattern. (2) The `"visit/be at X between A
  and B"` pattern's location capture (`.+?`) is greedy across an earlier `visit` in the same
  sentence when two visit-clauses are joined by a comma ("we wish to visit natural scenery, and we
  wish to visit Feilaifeng Grottoes between 08:10 and 09:40" → captures the whole run-on instead of
  just "Feilaifeng Grottoes") — change `.+?` to `[^,;]+?` so the match can't cross a clause boundary
  (forces backtracking to the later, correct "visit" anchor). (3) One `wrong_value` case
  (`"Peppa Pig's World of Fun"` vs oracle's truncated `"Peppa Pig"`) is an oracle-side data artifact —
  the ground-truth DSL string literal itself is apostrophe-truncated (same class of issue already
  noted for hotel names in `solver_constraints.py`'s oracle-mode comment). Our parser's extraction is
  correct; this one is unfixable from our side and should be left as a known ceiling.

**Net assessment:** 5a and 5b's `required_hotel_all_types` component are single, well-scoped,
high-confidence fixes (schema-parity bug and a missing regex pattern + dead-family removal,
respectively) expected to close ~140 of the ~850-query family-level gaps outright. 5c and 5e are
small regex extensions plus 2-3 line cleanups each. 5d's fix is a one-token relabel with a clear
falsifiable justification (zero code-3 occurrences, 100% code-2-implies-"twin" correlation in the
sampled cases) but its `missing` bucket has a genuine, evidenced non-recoverable ceiling — don't
spend further time trying to default it. Implementation is blocked until the
`llmparse-disj-fullfold0-300s` job (see plan Step 4) releases the source freeze; then follow the
plan's existing substep order (5a → 5b → 5c → 5d) with TDD per substep and a full-val
`parser_vs_oracle` rerun after each to confirm the family's missing/spurious count actually falls
before moving on.

## Step 3/4 measurement: the `llmparse-disj-fullfold0-300s` job (2026-07-12)

Steps 3 (measure LLM-parse e2e) and 4 (one realistic-budget attribution row) from
`docs/tpc_phase2_sonnet_plan.md` are both closed by existing ledger rows, though not exactly as the
plan specified them (n=85 full-fold rows throughout, not the plan's n=20 sub-sample; the 300s row
predates Step 1's dynamic-budget code, so it's a static-budget measurement, not a `dynbudget` one).

- **Step 3 (60s, `20260711T071751Z`, "llmparse-disj-fullfold0-60s-fixed"):** e2e FPR 81.18 vs
  solver-only 94.12 (parsing loss 12.94 pts) — already recorded in commit `aed04a91` as a
  regression against the deterministic-parse baseline (85.88); LLM-parse defaulted on anyway per
  `cf7d145d`'s reasoning (see that commit). This is the "does LLM-parse move e2e FPR" answer the
  design doc's open question asked for: **yes, it moves it, but currently in the wrong direction**
  at 60s — the parser-family fixes in the "Step 5 parser-family diagnosis" section above are the
  planned remedy (LLM-audit recall regression, plan gap B6, concentrated in exactly the families
  Step 5 targets).
- **Step 4 (300s, `20260711T192208Z`, "llmparse-disj-fullfold0-300s", run 2026-07-11 21:22 →
  2026-07-12 05:08 UTC, pid 178752, git_sha stamped at completion `f36a326b` — a docs-only commit
  landed mid-run, which is safe per the measurement-hygiene rule since it touched no `.py` the
  chunked subprocesses import):** e2e FPR **80.00**, solver-only FPR **95.29** (std 0.0 across both
  repeats), `llm_parse_failed=0`/`llm_parse_attempted=85` (backend healthy). Parsing loss **15.29
  pts**, *larger* than the 60s row's 12.94 — confirms plan gap B4 (parsing loss dominates more, not
  less, at realistic budgets) but for a different reason than hypothesized: solver-only FPR barely
  moved (94.12→95.29, +1.17) while e2e FPR *dropped* (81.18→80.00, −1.18) going 60s→300s. Under the
  static budget in effect for this run, the extra 240s bought the solver almost nothing — direct
  evidence for Step 1's diagnosis (`budget.py` was only ever handing the solver ~165s of the 300s;
  see the dynamic-budget gap entry above) rather than a parser-quality effect.
- **Decision rule from the plan:** solver headroom (4.71 pts at 300s) is well below parsing loss
  (15.29 pts), so Stage 3 LLM refinement stays deferred; Step 5's parser fixes remain the priority,
  now implemented for 5a/5b (below) with 5c/5d next.
- **Next measurement:** re-run this same 300s/n=85/repeats=2 configuration with
  `TPC_P2_DYNAMIC_BUDGET` on (now the runner default post-Step-1, `33795fab`) to see whether giving
  the solver its withheld ~100s actually moves solver-only/e2e FPR, now that the "extra budget did
  nothing" finding above is understood to be a budget-allocation artifact rather than a solver
  ceiling.

## Fast e2e iteration loop (2026-07-12)

The 300s/n=85/repeats=2 full-fold row above took ~7h46m — too slow for iterating on individual
fixes. Established convention going forward:

- **Full fold (n=85), `TPC_P2_BUDGET_SEC`/`P2_BUDGET=100`, `P2_REPEATS=1`, `P2_PARALLEL=3-4`** —
  estimated 67-90 min (`repeats × n × 1.9 × budget_sec ÷ parallel`; the 300s job's actual 7h46m
  came in slightly under the parallel=3 formula estimate of ~9h, so real runs may run a bit faster
  than this predicts). Not under the original 1h ask but close, and a ~6x speedup over the 300s
  loop with no new infrastructure.
- **100s, not 60s:** 60s produced too many solver timeouts to be a reliable signal (the reason the
  default was raised to 300s in the first place, see `cf7d145d`); 100s is the chosen compromise.
- **repeats=1, not 2:** every repeat-pair measured so far has std=0.0 (temp-0 LLM + warm cache +
  deterministic CP-SAT) -- that's solver determinism, not measurement precision, so a second repeat
  currently just redoes identical work. Keep `repeats>=2` for a final submission-facing
  characterization of the organizers' 5-run averaging (a different, later concern), not for
  iteration.
- **Full n, not a subset:** FPR here is an integer count over n, so at n=85 the resolution is
  ~1.2pts; shrinking to a hand-picked or even random n=20 subset raises that to 5pts -- the ~1-2pt
  effects this project cares about would fall between grid lines. A curated/stratified subset is
  additionally *non-comparable* to the full-fold baselines and to itself across changes (it
  deliberately over- or under-weights families) -- don't build one. Per-family coverage (which a
  subset would otherwise be for) is already served for free by `parser_vs_oracle.py`
  (~20s, no solver) -- that's the actual fast loop for parser-only changes.
- **Budget mostly doesn't matter for parser changes:** e2e FPR was 81.18@60s vs 80.00@300s, nearly
  flat -- parsing correctness is an accept/reject property, not a function of solve time. The one
  exception is validating budget-allocation changes themselves (Step 1's dynamic budget), where the
  realistic 300s (or 900s) run is the point and this fast loop doesn't substitute for it.

## Plan 2 Step 0 status (2026-07-12, coding VM)

Executing `docs/tpc_phase2_sonnet_plan2.md` from the coding VM (no long evals here; the 300s
ground-truth loop runs on a separate, larger eval VM — see the two-VM model in that plan).

- **Step 0.3 (parser behavioral re-run, solver-free, ~50s):** re-ran
  `scripts/parser_vs_oracle.py --split-set val --behavioral --disjunction --branch-aware` on the
  current tree (post step-5d, pre-plan-2 code). Result: n=850, precision 0.5725, recall 0.6814,
  f1 0.6222, value_accuracy 0.8069, disjunction_flattened 134, **behavioral agreement_rate
  0.7988** — confirms the plan's "last measured 0.7988 after 5c" number exactly (5d's room_type
  fix didn't move behavioral agreement, consistent with it closing a `wrong_value` bucket the
  behavioral check doesn't directly credit).
- **Step 0.1 (confirm `dynbudget-step5-fullfold0-300s` job) / 0.2 (queue the det-only anchor):**
  **not checkable from the coding VM.** `docs/phase2_baselines/history.jsonl` on this machine's
  checkout has no row past `20260711T192208Z` (the pre-step-5, static-budget row already
  documented above), and there is no local process for `record_baseline`/`rehearse_phase2`
  running here (`ps aux` clean). The job launched 2026-07-12 ~08:00 UTC+2 either hasn't landed on
  this branch yet or is running/queued on the eval VM. Both the "did dynamic budget + step-5
  parser move 300s numbers" read and the deterministic-only `det-step5-dynbudget-300s` anchor
  remain open — needed before Step 6 can conclude, and should come from the eval VM (Step 4's
  worker once it exists, or a manual overnight run there).

## Design Rules For Phase 2

1. Solver-first, not prompt-first.
2. Deterministic where possible, LLM where necessary (LLM proposes, deterministic validates).
3. Never trade acceptance for preference.
4. Normalize parser output before it reaches `TPCAgent`.
5. Treat no-oracle OR handling as a first-class requirement.
6. Reserve time for safe final output; always return a schema-valid plan.
7. Keep the deterministic path byte-identical when all LLM/improvement flags are off.

## Relationship To Phase 1

Phase 1 and Phase 2 share the same deterministic core but not the same top-level control assumptions.

| | Phase 1 | Phase 2 |
| --- | --- | --- |
| Constraints | released oracle `hard_logic_py` | inferred from visible NL only |
| Runtime | unlimited resumable offline iterations | one bounded per-query run |
| Output | prediction files only | harness-executed result |
| LLM | none (placeholder) | optional, bounded, flag-gated |

Phase 2 is primarily a parsing and orchestration problem wrapped around the existing solver, not a
replacement of it.
