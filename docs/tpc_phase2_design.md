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

**Expected per-query budget: ~15 minutes (900s) primary, ~5 minutes (300s) alternative — to be
confirmed with the organizers.** The default lives in `chinatravel/agent/phase2/orchestrator.py`
(`PHASE2_DEFAULT_BUDGET_SEC = 900`, `PHASE2_ALT_BUDGET_SEC = 300`) and is overridable per query via the
`TPC_P2_BUDGET_SEC` env var, the `budget_sec` argument, or `--budget-sec` on the runner/rehearsal.

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
     Fix: dynamic reallocation (plan Step 1, `TPC_P2_DYNAMIC_BUDGET`, runner-default-on pattern).
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
