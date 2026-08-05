# Stage 3 — bounded, acceptance-gated LLM plan refinement

You are a Sonnet 5 implementation agent (see [parallel workstream guidance](../../CLAUDE.md#parallel-workstreams) for the
general contract; this file is the focused task prompt for the specific implementation item below). Your job is to
turn the Phase 2 **Stage 3 "improve" no-op into a real, bounded, acceptance-gated LLM refinement pass**, behind an
explicit off-by-default flag, preserving every invariant. You run in parallel with docs/planning and evaluation
workstreams; none should block the others.

Read [`CLAUDE.md`](../../CLAUDE.md), the [Phase 2 roadmap](../tpc_phase2_roadmap.md) (Next step 6 and "Shortcomings"
item 3), the [Phase 2 design doc](../tpc_phase2_design.md) (no-oracle contract and flow), and the
[TPCAgent internals](../../chinatravel/agent/tpc_agent/readme.md) before writing code. Read the owning code path
before editing it.

## Status: v1 is LANDED — your job is to make its edits actually commit

**This brief no longer asks you to fill an empty stub — v1 is implemented.** `orchestrator._improve_stage`
(`chinatravel/agent/phase2/orchestrator.py`) calls the LLM behind `TPC_P2_LLM_REFINE`; `chinatravel/agent/phase2/refine.py`
builds the prompt (`build_llm_refine_prompt`) and parses typed edits (`parse_llm_refine_edits`); and
`TPCAgent.apply_refine_edits` / `TPCAgent.ground_and_check` (`chinatravel/agent/tpc_agent/tpc_agent.py`, ~lines 1667/1743)
ground each edit against `WorldEnv` and re-check the whole batch. Telemetry records `improve_llm_called`,
`improve_committed`, `improve_edit_count`, and `improve_skip_reason`. The floor-off, no-hook, and acceptance-gate tests
exist (`tests/phase2/test_*refine*`). **Do not reimplement any of this.**

The problem is that **v1 commits nothing yet.** A quick end-to-end screen on familiar-100 val (`n=30`, `90 s`, DeepInfra
`Qwen/Qwen3.6-27B`, `TPC_P2_LLM_TIMEOUT_SEC=8`) found `improve_llm_called=18`, `improve_committed=0`, with these
`improve_skip_reason` buckets — this is your work list, in priority order:

| bucket | count | what it means | where to look |
| --- | --- | --- | --- |
| `no_groundable_edits` | 8 | the LLM proposed edits but **every one failed grounding** against `WorldEnv`, so nothing was even trialed | `apply_refine_edits` + the prompt's feasibility context |
| `not_accepted_or_regressed` | 5 | edits grounded and were trialed, but the **checker still rejected** the batch (or the preference key regressed) | `build_llm_refine_prompt`'s `failure_summary`; batch/iterate logic |
| `llm_error_or_invalid_json` | 5 | the refine call **errored or returned bad JSON** | partly a screen artifact — see below |

**Reproduce it first** (this is your baseline, and how you'll know v2 works): run the screen from
[Phase 2 quick-screen guidance](../tpc_phase2_eval.md#quick-ab-screen) with
`--flag TPC_P2_LLM_REFINE`, and read the `LLM activity (cand)` line and the per-uid `improve_skip_reason` in
`agent_env/runs/phase2_e2e_*/<uid>/telemetry.json`. **Success = `improve_committed` rises above 0 without any regression,
and the screen verdict moves off `NO BENEFIT`.**

### Concrete v2 work, by bucket

1. **`no_groundable_edits` (biggest bucket).** The prompt already forbids inventing POIs ("must be the exact `position` of
   an activity already in the plan"), so the edits reference real activities but still fail to ground — most likely a
   `shift_activity_window` to a time outside the POI's opening hours, or a `swap`/`reorder` whose resulting transport leg
   can't be grounded. **Give the LLM the feasibility context it is missing:** include each activity's *grounded* feasible
   window (opening/closing, and the time actually available given neighbours) in the compact plan, and/or have
   `apply_refine_edits` snap a proposed window to the nearest groundable one rather than dropping the whole edit. Add a
   short per-edit diagnostic (which op failed grounding and why) so the next screen shows the shift.
2. **`not_accepted_or_regressed`.** Edits ground but the plan still fails — usually because a single edit does not resolve
   *all* failing clauses, or fixes one and breaks another. **Sharpen the `failure_summary`** so each failing clause names
   the specific POI / day / window / leg at fault (not just a family name), and let the model address the full failing set
   in one batch (`MAX_REFINE_EDITS` already allows several). A bounded **second attempt** — re-prompt once with the
   post-edit checker failures — is in scope if the first batch grounds but still fails; keep it to one extra call within
   the `improve_sec` slice.
3. **`llm_error_or_invalid_json`.** At `timeout=8` on the reduced screen slice some calls simply time out; at the full
   `300 s` budget the improve slice is ~30 s, so this bucket should mostly evaporate — **confirm** by re-screening at a
   larger `--budget-sec` / timeout and checking the errored count drops. Any residual JSON-shape errors are prompt/schema
   robustness (tighten the schema instruction or the tolerant parse), not a logic change.

Stay in **v1 repair-only scope**: if the input plan already passes acceptance, no-op and return it (preference-lift on an
already-valid plan stays a documented stretch behind its own sub-flag). You are closing the gap on produced-but-invalid
plans — the binding surface, since the orchestrator's Stage 4 gate is shape-only (`_valid_plan_shape` checks
`isinstance(plan.get("itinerary"), list)`, not acceptance), so a produced-but-invalid plan is emitted verbatim and Stage 3
is the only place left that can flip it to accepted end-to-end. This complements the deterministic passes
(`_pin_timed_windows`, `_repair_transport_gaps`) by covering exactly the cascading-shift / resequencing cases they decline.

## Invariants your change must hold (do not weaken any of these)

- **Flags off is the floor.** Ships behind `TPC_P2_LLM_REFINE` (the existing `Flags.llm_refine`), default **off**, so the
  library-default deterministic path stays **byte-identical** and makes **zero** LLM calls. Assert both with unit tests
  (a spy client records `calls == []`; output equals the no-refine output).
- **Acceptance-gated, deepcopy-trialed.** Apply every LLM-proposed edit to a **deepcopy** (`trial`), then keep the result
  only if the full deterministic checker accepts (`_accepted(*check(trial))`) **and** the preference key does not regress
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

## Where the code lives (you are modifying this, not building it)

The full v1 path already exists; touch these and keep the flow intact:

- **`chinatravel/agent/phase2/orchestrator.py`** — `_improve_stage` is the Stage 3 body (bounded by `improve_sec`,
  reverts to last-valid on timeout/exception, pulls `ground_and_check`/`apply_refine_edits` off the solve_fn hook; no-ops
  when the hook is absent). `make_tpcagent_solve_fn` attaches the hooks. Keep Stage 3 **in the orchestrator** — its
  separate slice and revert safety are deliberate; do not move refine into `TPCAgent.run()` (that spends the *solve*
  budget). Most of your prompt/edit changes will *not* need to touch this file.
- **`chinatravel/agent/phase2/refine.py`** — `build_llm_refine_prompt` (the prompt + compact plan + `failure_summary`),
  `parse_llm_refine_edits`, `REFINE_ALLOWED_OPS`, `MAX_REFINE_EDITS`. **Bucket 1 (feasibility context) and bucket 2
  (sharper `failure_summary`, optional second attempt) mostly live here.**
- **`chinatravel/agent/tpc_agent/tpc_agent.py`** — `ground_and_check` (~1667: builds the same no-oracle `constraints` +
  `_make_checker` the solve used, runs `_sanitize_plan_for_grounding`, `_accepted`, `_accepted_eval_key`, and returns the
  `(accepted, grounded_plan, eval_key, failure_summary)` tuple) and `apply_refine_edits` (~1743: grounds each typed op
  against `WorldEnv`, dropping the ungroundable). **Bucket 1's "snap to a groundable window / emit a per-edit reason"
  work lives in `apply_refine_edits`; enriching the failure summary for bucket 2 may touch `ground_and_check`.**

If you add a bounded second attempt (bucket 2), keep the whole stage within one `improve_sec` slice: it is ~30 s at a
`300 s` budget (≈ one `DEFAULT_LLM_TIMEOUT_SEC` call plus grounding + check), so two calls need a smaller per-call timeout
or a check that the slice can fit both — skip and record a telemetry reason otherwise, exactly like the parse stage's
`llm_parse_skipped_deadline`.

## Build and verify

- Use Python 3.12 through `.venv/bin/python`.
- **The v1 invariant tests already exist and must keep passing** — flags-off byte-identical floor (spy client, `calls ==
  []`), no-hook no-op, repair-commits (a `FixtureLLMClient` edit flips invalid→accepted and commits), rejects-on-non-
  acceptance, rejects-on-preference-regression, graceful-degrade, and no-oracle-in-prompt. Do not remove or weaken them.
- **Add v2 tests for the specific gap you close**, with a `FixtureLLMClient` returning the exact edit shape that used to
  fail: e.g. a `shift_activity_window` to an out-of-hours time now **snaps to the groundable window and commits** (bucket
  1); a multi-clause failure where a single-edit batch was rejected but the fuller batch / second attempt now **commits**
  (bucket 2). Model them on `test_repair_transport_gaps.py` and the existing refine tests. Keep tests hermetic — use the
  `fixture` backend, never a live call.
- Run the unit suite before committing:

  ```bash
  make phase2-test
  .venv/bin/python -m pytest tests/phase2/ -q
  ```

- **Then screen your change end-to-end on val** (the self-check that tells you it actually worked — see
  [Phase 2 quick-screen guidance](../tpc_phase2_eval.md#quick-ab-screen)):

  ```bash
  .venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_LLM_REFINE --mode end-to-end \
    --off 0 --on 1 --extra-env "TPC_P2_LLM_BACKEND=deepinfra,TPC_P2_LLM_TIMEOUT_SEC=8" \
    --n 30 --budget-sec 90 --parallel 3
  ```

  Success is `improve_committed > 0` on the candidate arm (up from 0) with no correctness regression and the verdict off
  `NO BENEFIT`. Put the before/after `called`/`committed` counts and the verdict in your PR body.
- Keep the change one coherent, acceptance-preserving unit. Match the surrounding code's naming, comment density, and idiom.
- **`.env`:** the DeepInfra key lives in `.env` and is loaded by `load_local_env` when a backend is selected. Do **not**
  read, edit, stage, or print `.env`. For unit tests, use the `fixture` backend (`FixtureLLMClient`) — never a live call —
  so the suite stays hermetic; the live DeepInfra call is only for the end-to-end screen above.

## Finish — open a PR

Develop on a branch named `claude/phase2-impl-stage3-refine` (create it from the latest `main`). Then:

1. Rebase on the latest `main` before pushing; resolve unexpected changes as user work, never overwrite them.
2. Push and open a PR. In the body: state the roadmap item (Next step 6 / shortcoming 3), the mechanism (LLM proposes
   bounded edits → deterministic re-grounding → acceptance gate), the flag that gates it (and that the floor stays
  byte-identical when off), the tests you added, and any offline/solver-free diagnostic evidence — labeled diagnostic,
  pending an end-to-end gate. Do **not** present familiar-100 or local numbers as final-evaluation performance,
  and do **not** self-promote: run the paired `TPC_P2_LLM_REFINE` on/off gate at one SHA and record the outcome in
  the roadmap.
3. After opening the PR, wait for GitHub Copilot review comments (poll up to 10 minutes) and address or resolve each one.

Report faithfully: if the mechanism does not flip any plan or a test fails, say so with the output rather than papering
over it. Hand the gate to the evaluation workstream.
