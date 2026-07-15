# TPC 2026 Phase 2 — WorldEnv-Backed Normalization Plan

Plan to close **Gap 2** from `docs/tpc_phase2_design.md`:

> **Normalization is not yet doing the intended WorldEnv-backed resolution work.** The IR and `env`
> hooks exist, but field-level entity resolution, validation, and confidence-aware normalization are
> still largely unimplemented.

This maps to Roadmap item 2 in `docs/tpc_phase2_implementation_plan.md` ("Finish Stage 1
normalization before adding refinement"). It is deliberately scoped short of Gap 3 (corrective LLM
parsing): all work here is deterministic and needs no network.

## What the gap actually is (grounded in code)

`chinatravel/agent/phase2/normalize.py::ir_to_solver_variants(ir, query, *, env=None, flags=None)`
already receives an `env` hook but **never uses it** — it is a pure pass-through to
`solver_constraint_variants(query, ir.raw, use_oracle=False)`.

Meanwhile the no-oracle parser (`parse_constraints.parse_query_no_oracle`) leaks substantial garbage
into entity-name fields, and the verifier (`chinatravel/agent/tpc_agent/parsed_verifier._match_text`)
matches by **substring containment** after normalization (`c == q or q in c or c in q`). So garbage
in an entity field is not inert — it actively breaks plans.

### Measured opportunity (all 1000 phase-1 queries)

Fraction of extracted entity values that do **not** resolve to any real POI name in the target city
(via `WorldEnv(lang='en')`):

| Field group                | Resolve   | Unresolved (garbage)   |
| -------------------------- | --------- | ---------------------- |
| attractions (req + excl)   | 120 / 187 | **67 (36%)**           |
| restaurants (req + excl)   | 121 / 223 | **102 (46%)**          |
| hotels (req + excl)        | 256 / 312 | **56 (18%)**           |

Representative unresolved values:

- `required_attractions: "14:00"`
- `required_attractions: "Bistro Sola between 17:00"`
- `required_hotels: "a hotel of the following type: Sauna"`
- `required_hotels: "request a single bed room"`
- `excluded_restaurants: "and Other"`
- `required_restaurants: "a Hot pot restaurant"`
- `required_restaurants: "Japanese cuisine restaurants"`

### Why it matters

A spurious `required_attractions: "14:00"` makes the verifier's
`any(_match_text(activity_position(a), "14:00") for a in attractions)` **always false**, so the
entire plan is rejected and that query scores 0. Every unresolvable *required* value is therefore a
potential hard zero; ~225 such values exist across the set.

Two bonuses fall out of the same pass:

- **Canonicalization is also a recall win.** The verifier uses `q in c or c in q`, so
  `"Powerlong Museum between 12:30"` fails `q in c` because of the leaked suffix. Trimming to the
  real POI name `"Powerlong Museum"` makes it match.
- **WorldEnv holds English names/types** (`env.attractions.select(city, 'name', …)`,
  `get_type_list`, `get_cuisine_list`), so resolution matches the English queries directly — verified.

## Design decision

Gate the new behavior behind a new flag **`TPC_P2_RESOLVE`** (default OFF in the library `Flags()`,
so the byte-identical invariant tests are untouched), and enable it **by default in the production
runner** `agent_env/scripts/solve_phase2.py` — exactly the pattern Milestone 6 used for
`TPC_P2_DISJUNCTION`. Resolution runs only when `flags.resolve` **and** `env is not None`.

Alternative considered: activate whenever `env is not None` with no new flag. Rejected in favor of
the flag because it gives an explicit A/B for the regression gate and matches the project's
"flag-gated evolution + flags-off byte-identical" ground rule.

## Plan

### Step 1 — Entity resolver: new module `chinatravel/agent/phase2/resolve.py`

- Memoize per-`(city, kind)` the lowercased name pool and the type/cuisine lists from `env` (keyed on
  `id(env)` + city) so repeated lookups within a run are cheap.
- `resolve_name(value, pool) -> (canonical | None, confidence, candidates)`:
  - exact (normalized) match → confidence 1.0
  - unique substring / `difflib` near-match → canonical real name, confidence ~0.7–0.9, alternates
    recorded in `entity_candidates`
  - no match → `None`, confidence 0.0
- `resolve_types(values, allowed) -> (kept, dropped)` for `required/excluded_attraction_types`,
  `cuisine_preference`, `excluded_cuisine_types`, and hotel type fields.

### Step 2 — Confidence-aware normalization policy in `normalize.py`

New `resolve_entities(variant, query, env, ir)` applied to each solver variant **after**
`solver_constraint_variants(...)` (and after disjunction expansion, so each branch-local arm is
resolved independently):

- **`required_*` names:** high-confidence → replace with canonical name; **no match → drop** (removes
  the unsatisfiable-constraint hard zero). If a leaked value clearly looks like a type phrase
  (`"a Hot pot restaurant"`, `"Japanese cuisine restaurants"`), optionally re-route to
  `cuisine_preference` — a nice-to-have; **drop is the safe floor.**
- **`excluded_*` names:** match → canonical; no match → drop (excluding a nonexistent entity is a
  harmless no-op, and dropping avoids over-broad substring exclusions like `"and Other"`).
- **type / cuisine fields:** drop values not present in the env's type list.
- Populate `ir.confidence` and `ir.entity_candidates` as this runs, so the IR fields carry real
  signal (the second half of the gap).
- Wire into `ir_to_solver_variants`:
  `if flags.resolve and env is not None: variants = [resolve_entities(v, …) for v in variants]`.

### Step 3 — Flag plumbing

- Add `resolve: bool` to `Flags` + `TPC_P2_RESOLVE` in `Flags.from_env` (`orchestrator.py`).
- Default ON in `solve_phase2.py` unless explicitly set (mirror the Milestone-6 disjunction default).
- Docs: add the flag row to the feature-flag tables in both `tpc_phase2_design.md` and
  `tpc_phase2_implementation_plan.md`.

### Step 4 — Tests (`tests/phase2/test_resolve.py`, TDD-first)

- Unit: exact / fuzzy / no-match resolution; type validation; confidence values populated.
- Policy: unresolvable `required_attractions: "14:00"` is dropped; leaked
  `"Powerlong Museum between 12:30"` canonicalizes; unresolvable exclusion dropped.
- **Byte-identical invariant:** with `TPC_P2_RESOLVE` off (or `env=None`), `ir_to_solver_variants`
  output is unchanged — extend `test_flags.py` / `test_schema_normalize.py`.
- Mark the real-WorldEnv end-to-end test `@pytest.mark.integration`.

### Step 5 — Measure with the existing harness

- `scripts/parser_vs_oracle.py --disjunction` (add an env-resolution toggle) before/after — expect a
  precision jump (fewer `spurious` / `wrong_value`) with recall flat-or-up from canonicalization.
- `scripts/phase2_gate.py` on a val fold to confirm no official-score regression.
- Target signal: the ~225 unresolved values get dropped/canonicalized, recovering the hard zeros they
  were causing.

## Risk guards

- Never *add* constraints — only drop or canonicalize what the parser already produced — so the pass
  cannot manufacture new failures.
- Fuzzy matching stays conservative (require a unique dominant match); ambiguous → keep the original
  value with low confidence rather than guess a wrong POI.
- All behind the flag; library default OFF preserves every existing byte-identical test.

## Out of scope (intentionally)

- Gap 3 (corrective LLM parsing / OR-arm recovery) — deferred; this plan is deterministic only.
- Gap 4 (Stage 3 LLM refinement) — remains lower priority until the parser gap is no longer dominant.
