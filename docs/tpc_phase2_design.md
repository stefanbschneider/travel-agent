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
| `TPC_P2_LLM_PARSE` | `0` | Enable LLM-assisted second-pass parsing (Stage 1). Stub in skeleton. |
| `TPC_P2_LLM_REFINE` | `0` | Enable bounded LLM-guided plan refinement (Stage 3). Stub in skeleton. |
| `TPC_P2_BUDGET_SEC` | inherits per-query timeout | Total per-query time budget the orchestrator splits across stages. |

These are the extension points; the skeleton wires them as no-op stubs so improvements can be added and
measured incrementally without destabilizing the deterministic baseline.

## Current Gaps To Close (post-review, updated 2026-07-10)

1. **Regex-only brittleness remains the main Phase 2 risk.** The live Stage 1 path still starts from
   `parse_query_no_oracle()`, so held-out phrasing robustness is still mostly bounded by the current
   regex parser. A behavioral-disagreement triage (first 60 val queries: 8/60 disagree) decomposes
   the remaining Stage-1 loss into three concrete buckets:
   - **Negation/over-extraction regex bugs** producing spurious `required_*` families next to the
     correct `excluded_*` ones (e.g. "Do not wish to stay at the following hotels: X and Y" also
     emits a bogus `required_hotels`). The Milestone-5 A2 negation guard covered restaurants; the
     same guard is still missing for hotels and attractions. Deterministically fixable.
   - **Parsed-verifier semantics mismatches**, e.g. a correct parse
     `{excluded_inner_transport: [taxi], taxi_cars_equals: 1}` fails the oracle-accepted best plan —
     the parsed verifier's taxi check is not vacuous when the plan contains no taxis. Verifier fix,
     not parser fix.
   - **LLM-parse conservatism** (see gap 3).
2. **Normalization is not yet doing the intended WorldEnv-backed resolution work.** The IR and `env`
   hooks exist, but field-level entity resolution, validation, and confidence-aware normalization are
   still largely unimplemented.
3. **LLM parsing works but is still too conservative.** First live probe (Qwen3.6-27B via DeepInfra):
   4/8 behavioral disagreements fixed, 0 regressions on 8 probed + 6 control uids. In 3 of the 4
   unfixed cases the LLM returned no patches at all even though the deterministic parse contained
   spurious families it was allowed to remove. Prompting it to actively audit each extracted family
   against the quoted NL (rather than only "refine") is the obvious next iteration; the OR-arm
   recovery path also did not trigger on the one flattened-disjunction probe.
4. **Stage 3 refinement is still a stub.** Current Phase 2 performance is effectively deterministic
   TPCAgent plus fallback, not deterministic solve plus bounded refinement.
5. ~~Operational benchmarking is not yet mature.~~ **Resolved 2026-07-10:** the earlier solver-only
   instability was a measurement artifact of n=1 smoke rows plus stale-resume contamination; the
   baseline recorder now runs fresh by default, labels smoke rows, and records run-to-run score
   variance via `--repeats`. See `docs/tpc_phase2_eval.md` and `docs/phase2_baselines/README.md`.

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
