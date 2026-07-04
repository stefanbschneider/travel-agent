# TPC 2026 Phase 2 Design

This document covers the **final harness** phase only.

## Official Execution Model

Phase 2 differs from Phase 1 in four critical ways:

1. Organizers run our harness **query by query**, not in batch
2. The evaluation set is held out
3. Oracle verifier fields are not visible to the agent
4. The harness runs under a bounded per-query timeout on Qwen3.6-27B via SGLang

Relevant source notes are summarized in `IJCAI2026_competition.md` and mirrored from the
official pages.

## What The Baseline Harness Does

The organizer-style baseline in `agent_env/scripts/solve_script_with_harness.py`:

- loads a query locally
- hides oracle-only fields from the visible prompt
- delegates solving to a generic agent runtime (`opencode` or `codex`)
- parses JSON output
- writes the official result file layout
- runs the official local evaluators

This is useful as a compatibility reference, but it is not the best final architecture for us.

## Recommended High-Level Approach

The right Phase 2 design is **LLM-assisted parsing plus deterministic solving**, with optional
bounded LLM-assisted refinement.

### Stage 1: Query Understanding

Input is the visible natural-language query only.

We should map it into structured constraints using a hybrid parser:

- deterministic extraction for stable patterns
- LLM assistance for paraphrases, compound clauses, and ambiguity
- deterministic validation and normalization against the environment data

### Stage 2: Deterministic Planning

Feed normalized branch-local constraints into the existing TPCAgent and CP-SAT stack.

This remains the primary planner because it is:

- reproducible
- easy to cache and debug
- already strong on validity
- already designed around branch-local constraint reasoning

### Stage 3: Bounded Improvement

If a valid plan is found early enough, run a short improvement pass:

- deterministic densify and local swaps first
- optional narrow LLM-guided refinement second
- always acceptance-gated
- always stopped before a hard safety margin to ensure final output is returned on time

## Recommended Harness Architecture

The recommended submission harness should be **our own orchestrator**, not a generic prompt-only
agent runner.

```text
query
-> own Python harness
-> parser pipeline
-> normalized constraint variants
-> deterministic TPCAgent / CP-SAT solve
-> deterministic local improvement
-> optional bounded LLM refinement
-> final JSON result
```

### Role of `opencode` / `codex`

`opencode` and `codex` are optional local experimentation backends, not architectural requirements.

For our final Phase 2 submission, the harness should own the control loop itself and call the LLM
only for targeted subproblems such as:

- parse disambiguation
- OR-group expansion
- entity resolution hints
- optional late-stage plan improvement

## Constraint Schema Guidance

We should **keep the solver-facing constraint format mostly stable**.

The current normalized dict shape used by TPCAgent is already close to what the deterministic
planner wants: budgets, required and excluded entities, transport preferences, timing constraints,
hotel proximity, stay duration, and related fields.

What should change is the parser-side representation.

### Recommended Two-Layer Representation

1. Parser output schema
   Used only inside the Phase 2 harness. It can be richer and more uncertain.

   Suggested contents:

   - alternative parses
   - disjunctive groups
   - confidence scores
   - raw extracted spans
   - entity resolution candidates
   - hard constraints versus softer preferences

2. Solver input schema
   Used by TPCAgent. Keep this close to the current normalized dict shape so the solver does not
   need to absorb parser ambiguity.

The normalization layer between these schemas becomes a core Phase 2 component.

## Current Gaps To Close

### 1. No-oracle disjunction handling

This is the highest-priority known gap.

The current no-oracle parser path in `parse_constraints.py` collapses too early:

- `parse_query_no_oracle()` returns one flat parse
- it sets `disjunctive = False`
- `solver_constraint_variants(..., use_oracle=False)` therefore returns only one normalized variant

That is acceptable for Phase 1 tail experiments, but it is too weak for final Phase 2 robustness.

### 2. Regex-only brittleness

The current parser is strong on repeated released phrasing, but held-out Phase 2 wording will vary.
We need a better second-pass parser for:

- paraphrase robustness
- compound clauses
- OR constraints
- conditional transport and timing phrasing
- entity and type disambiguation

### 3. Generic-runner-oriented baseline harness

The current baseline harness delegates the whole solve loop to `opencode` or `codex`.
Our final system should invert that control: the harness owns the loop and invokes the LLM only
where needed.

### 4. CLI overhead for deterministic steps

For our own code, direct Python environment calls are preferable to shelling out through
`agent_env.cli` for every deterministic lookup. CLI, MCP, and HTTP wrappers are still useful for
external-agent experiments.

## Timeout Budgeting

The final harness should budget time per query explicitly rather than spending the full timeout in
one undifferentiated solve loop.

Suggested allocation:

- 20–30%: parsing and normalization
- 50–60%: deterministic solve and branch search
- 10–20%: optional improvement
- 5–10%: safety buffer for finalization and output

The harness should always preserve a hard finalization buffer.

## Recommended Implementation Plan

1. Add an internal harness backend alongside `opencode` and `codex`
2. Add a richer parser-side intermediate representation
3. Add true no-oracle disjunctive branch generation
4. Keep TPCAgent solver input mostly stable
5. Add a local no-oracle rehearsal workflow on the public Phase 1 queries with oracle hidden from the agent but still available for offline comparison
6. Add deterministic-first post-solve refinement
7. Add optional bounded LLM-guided refinement only after the no-oracle base path is reliable

## Design Rules For Phase 2

1. Solver-first, not prompt-first
2. Deterministic where possible, LLM where necessary
3. Never trade acceptance for preference
4. Normalize parser output before it reaches TPCAgent
5. Treat no-oracle OR handling as a first-class requirement
6. Reserve time for safe final output

## Relationship To Phase 1

Phase 1 and Phase 2 should share the same deterministic core, but not the same top-level control
assumptions.

Phase 1:

- optimize directly against released oracle constraints
- run many resumable offline iterations
- submit prediction files only

Phase 2:

- interpret visible natural language only
- solve one query within a bounded runtime
- return a harness-executed result

That means Phase 2 is primarily a **parsing and orchestration problem wrapped around the existing
solver**, not a full replacement of the solver itself.