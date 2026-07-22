# Stage 3 — bounded, acceptance-gated LLM plan refinement

You are a Sonnet 5 implementation agent (role 3 — see [`role3_implementation.md`](role3_implementation.md) for the
general role contract; this file is the focused task prompt for the specific implementation item below). Your job is to
turn the Phase 2 **Stage 3 "improve" no-op into a real, bounded, acceptance-gated LLM refinement pass**, behind an
explicit off-by-default flag, preserving every invariant. You run in parallel with a docs/planning agent (role 1) and a
long-running evaluation agent (role 2); you do not block them and they do not block you.

Read [`CLAUDE.md`](../../CLAUDE.md), the [Phase 2 roadmap](../tpc_phase2_roadmap.md) (Next step 7 and "Shortcomings"
item 3), the [Phase 2 design doc](../tpc_phase2_design.md) ("Improve" stage and "Extension points"), and the
[TPCAgent internals](../../chinatravel/agent/tpc_agent/readme.md) before writing code. Read the owning code path
before editing it.

## Why this is the next implementation target

Every other landed opt-in feature (`TPC_PIN_TIMED_WINDOWS`, `TPC_REPAIR_TRANSPORT_GAPS`, `TPC_SOLVE_CONVERGE_PATIENCE`)
is now waiting on a role-2 gate, and the two parser residual fixes have landed on `main`. Stage 3 is the only
**new-implementation** item left in the roadmap's "Next steps" that is not merely a gate.

Today `orchestrator.llm_refine_stub` (`chinatravel/agent/phase2/orchestrator.py`) returns the plan unchanged and never
calls the LLM. Its stage is wired end-to-end — a `func_timeout`-bounded slice (`b.improve_sec`), a revert-to-last-valid
safety path, telemetry (`improve_timed_out`, `improve_reverted_to_last_valid`), and a `dynamic_budget` reserve
(`dynamic_solve_sec(..., improve_reserved=flags.llm_refine)`) — but the body is empty, so the reserved slice is wasted.
This task fills that body.

## The target the refine pass should attack

The binding failure surface end-to-end is **produced-but-invalid plans**, not solver crashes or timeouts:

- Solver-only FPR (`~26/100` familiar-100) is the ceiling; `timed_visit_named_poi` dominates logical failures and
  "Invalid Transport information across positions" dominates commonsense failures (see the roadmap's
  [Solver-only headroom](../tpc_phase2_roadmap.md#solver-only-headroom) and
  [Commonsense-transport repair](../tpc_phase2_roadmap.md#commonsense-transport-repair)).
- **Crucially, the orchestrator's Stage 4 gate is shape-only.** `_valid_plan_shape` checks `isinstance(plan.get("itinerary"), list)` — **not** semantic acceptance. A plan that the checker would reject
  still flows through to output as-is (it is not replaced by the fallback, because it is plan-shaped). So a
  produced-but-invalid plan is emitted verbatim today, and **Stage 3 is the only place left that can flip it to
  accepted end-to-end.**

**v1 scope — repair, not polish.** Target produced-but-invalid plans: ask the LLM for a small set of targeted edits,
re-ground them deterministically, and commit only if the deterministic checker then accepts. Explicitly out of v1:
preference polishing of already-accepted plans (the solver's restart loop already spends its whole budget polishing
DAV/ATT/DDR — see roadmap shortcoming 2 — so the marginal LLM gain there is low and the regression risk is real). If
the input plan already passes acceptance, v1 should no-op and return it unchanged. Leave preference-lift as a documented
stretch, gated behind its own sub-flag, only if v1 lands cleanly.

This aligns with the deterministic repair passes already landed (`_pin_timed_windows`, `_repair_transport_gaps`) but
covers the cases those explicitly decline — e.g. a leg or window that needs a **cascading time shift / resequencing** the
bounded deterministic passes refuse. The LLM proposes the reorder; the deterministic path grounds and checks it.

## Invariants your change must hold (do not weaken any of these)

- **Flags off is the floor.** Ships behind `TPC_P2_LLM_REFINE` (the existing `Flags.llm_refine`), default **off**, so the
  library-default deterministic path stays **byte-identical** and makes **zero** LLM calls. Assert both with unit tests
  (a spy client records `calls == []`; output equals the no-refine output).
- **Acceptance-gated, deepcopy-trialed.** Apply every LLM-proposed edit to a **deepcopy**, then keep the result only if
  the full deterministic checker accepts (`_accepted(*check(plan))`) **and** the preference key does not regress
  (`_accepted_eval_key(trial) >= _accepted_eval_key(input)`). Never trade a valid or higher-scored plan for a worse one.
  Follow the exact pattern in `_pin_timed_windows` / `_resequence_day` (`chinatravel/agent/tpc_agent/tpc_agent.py`), which
  trial on a deepcopy and commit on `self._accepted(*check(trial)) and self._accepted_eval_key(trial) >= before_key`.
- **Deterministic grounding, LLM only proposes.** The LLM authorizes nothing. Every POI, time window, price, and
  transport leg in an edited plan must be re-derived from `WorldEnv` (reuse `_sanitize_plan_for_grounding`, `_get_transport`
  / `_get_transport_resilient`, and the existing packing helpers) — never trust a name, time, or cost the model wrote.
  An edit that references a POI the environment cannot ground is dropped, not fabricated.
- **No oracle leakage.** The refine prompt sees only visible query fields (`uid`, `people_number`, `start_city`,
  `target_city`, `nature_language`) plus the current plan and the **checker's own failure summary** — mirror
  `build_llm_parse_prompt`'s allowlisted `visible` dict (`chinatravel/agent/phase2/normalize.py`). Never read or embed
  `hard_logic_py`, `hard_logic`, `plan` oracle fields, or any `*_py` verifier field. Note the no-oracle checker
  (`_make_checker`, `use_oracle=False`) scores against parsed `constraints`, not `hard_logic_py`, so its failure signal is
  already oracle-free — use that, not the oracle.
- **Branch-local alternatives** stay isolated through normalize → solve → check; refine operates on the single winning
  plan the solver already chose, it does not re-open disjunction.
- **Bounded fallback.** On LLM error, timeout, invalid/empty JSON, or no accepted improvement, return the **input plan
  unchanged**. The orchestrator already reverts to `last_valid_plan` on timeout/exception/invalid-shape; your function
  must additionally degrade gracefully within its own body (never raise, never return a worse plan).

## Recommended wiring (you may adjust, but keep the invariants)

The refine needs three things the current `llm_refine_stub(plan, query, llm_client, budget_sec)` signature lacks: the
ability to (1) ground a candidate plan against `WorldEnv`, (2) run the acceptance checker, and (3) read the failure
summary for the prompt. All three live inside `TPCAgent`, not the orchestrator. Keep Stage 3 in the orchestrator (its
separate `improve_sec` slice and revert-to-last-valid safety are deliberate — do **not** move refine inside
`TPCAgent.run()`, which would spend the *solve* budget and lose that safety). Instead expose a hook the way
`make_tpcagent_solve_fn` already exposes `get_timeout_recovery_plan`:

1. In `make_tpcagent_solve_fn` (`orchestrator.py`), attach a `ground_and_check` callable to the returned `_solve`
   (alongside `get_timeout_recovery_plan`). It takes a plan dict and returns something like
   `(accepted: bool, grounded_plan: dict, eval_key, failure_summary: dict)` — internally building the same
   `constraints` + `check = _make_checker(query, constraints)` the solve used, running `_sanitize_plan_for_grounding`,
   `_accepted`, and `_accepted_eval_key`, and collecting a compact, oracle-free description of which clauses / commonsense
   checks fail. Reuse the agent's existing no-oracle constraint build so the checker matches the solve path exactly.
2. In `solve_phase2`, pull `ground_and_check = getattr(solve_fn, "ground_and_check", None)` and pass it into the refine
   function. When it is `None` (unit tests inject a bare `solve_fn`), the refine **no-ops and returns the input** — this
   keeps existing tests and the floor intact.
3. Rename `llm_refine_stub` to `llm_refine` (or keep the name; update `TODO` docstring either way) and implement:
   - Call `ground_and_check(plan)`. If already accepted → return `plan` unchanged (v1 is repair-only).
   - Build a repair prompt (new `build_llm_refine_prompt`, colocated with `build_llm_parse_prompt` in `normalize.py` or a
     small `refine.py`): visible query, the current plan, and the failure summary; ask for **strict JSON** with a small,
     bounded list of typed edit ops (e.g. `reorder_day`, `shift_activity_window`, `swap_activity`, `drop_activity`) — no
     free-form plan rewrites. Cache the call with a `refine_<uid>_<hash>` key (mirror `llm_parse_cache_key`).
   - Parse the JSON defensively (reuse the tolerant JSON extraction already used by the parse stubs). Apply each edit to a
     deepcopy via deterministic, environment-grounded helpers; drop any edit that references an ungroundable POI.
   - Run `ground_and_check` on the edited deepcopy; commit only on `accepted and eval_key >= input_eval_key`. Otherwise
     return the input plan.
   - Add refine telemetry (e.g. `improve_llm_called`, `improve_committed`, `improve_edit_count`) so role 2 can see the
     effect in the row, without changing the existing `improve_*` keys.

Keep the LLM call within one bounded request: `improve_sec` at a 300 s budget is ~30 s, i.e. roughly one
`DEFAULT_LLM_TIMEOUT_SEC` call plus grounding + check. Budget accordingly and skip the call (record a telemetry reason)
if the remaining slice cannot fit one call, exactly as the parse stage skips on `llm_parse_skipped_deadline`.

## Build and verify

- Use Python 3.12 through `.venv/bin/python`.
- Add focused tests under `tests/phase2/` (model them on `test_orchestrator.py`, `test_pin_timed_windows.py`, and
  `test_repair_transport_gaps.py`). Cover at least:
  - **Flags-off floor:** `TPC_P2_LLM_REFINE` off → zero LLM calls (spy client) and output identical to no-refine.
  - **No hook → no-op:** a bare injected `solve_fn` (no `ground_and_check`) leaves the plan unchanged.
  - **Repair commits:** a `FixtureLLMClient` proposing a valid edit flips a produced-but-invalid plan to accepted, and it
    is committed.
  - **Rejects on non-acceptance:** a proposal that still fails the checker → input returned unchanged.
  - **Rejects on preference regression:** a proposal that lowers `_accepted_eval_key` → input returned unchanged.
  - **Graceful degrade:** LLM error / timeout / invalid JSON / ungroundable POI → input returned, telemetry set, no raise.
  - **No oracle in the prompt:** assert `build_llm_refine_prompt` output contains no oracle field
    (`hard_logic_py`, etc.).
- Run before committing:

  ```bash
  make phase2-test
  .venv/bin/python -m pytest tests/phase2/ -q
  ```

- Keep the change one coherent, acceptance-preserving unit. Match the surrounding code's naming, comment density, and idiom.
- **`.env`:** the DeepInfra key lives in `.env` and is loaded by `load_local_env` when a backend is selected. Do **not**
  read, edit, stage, or print `.env`. For tests, use the `fixture` backend (`FixtureLLMClient`) — never a live call — so
  the suite stays hermetic and byte-deterministic.

## Finish — open a PR

Develop on a branch named `claude/phase2-impl-stage3-refine` (create it from the latest `main`). Then:

1. Rebase on the latest `main` before pushing; resolve unexpected changes as user work, never overwrite them.
2. Push and open a PR. In the body: state the roadmap item (Next step 7 / shortcoming 3), the mechanism (LLM proposes
   bounded edits → deterministic re-grounding → acceptance gate), the flag that gates it (and that the floor stays
   byte-identical when off), the tests you added, and any offline/solver-free diagnostic evidence — labeled diagnostic,
   pending role 2's end-to-end gate. Do **not** present familiar-100 or local numbers as final-evaluation performance,
   and do **not** self-promote: role 2 runs the paired `TPC_P2_LLM_REFINE` on/off gate at one SHA, role 1 records the
   outcome.
3. After opening the PR, wait for GitHub Copilot review comments (poll up to 10 minutes) and address or resolve each one.

Report faithfully: if the mechanism does not flip any plan or a test fails, say so with the output rather than papering
over it. Hand the gate to role 2.
