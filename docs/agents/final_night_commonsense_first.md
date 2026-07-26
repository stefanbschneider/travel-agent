# Phase 2 Final-Evening Brief: Commonsense-First (2026-07-26)

Self-contained implementation brief for the last change window before the Phase 2 submission.
Everything needed to execute is in this file: baseline numbers, root causes, task order, exact
commands, and acceptance criteria. Use Python 3.12 through `.venv/bin/python`.

Never read, edit, stage, or overwrite `.env`; it is local user configuration.

## Baseline to beat

`results/phase2_baselines/runs/20260724T192503Z.json` (`tpc_phase2_familiar_100_val`, `n=80`,
`900 s`, sha `a72357c3`, 2 repeats, pin+converge on):

| axis | FPR | overall_true | schema | commonsense pass | EPR micro/macro | logical micro/macro | C-LPR | all_pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| end-to-end | 25.0 (25.63 ± 0.63) | 47.04 (47.98 ± 0.94) | 80/80 | 59/80 | 98.41 / 73.75 | 89.47 / 25.0 | 66.02 | 20 |
| solver-only | 27.5 (± 0.0) | 49.72 (49.54 ± 0.17) | 80/80 | 61/80 | 98.13 / 76.25 | 90.71 / 28.75 | 69.65 | 22 |

Zero parse failures, zero timeouts, zero fallbacks; solve `p50` `265 s` / `p95` `499 s`.

Later single-repeat rows on sha `6d354b99` are worse (e2e FPR `21.25`, `overall_true` ≤ `45.43`), so
never compare across SHAs. Only paired same-SHA arms decide anything tonight.

## Root causes that motivate the work

1. **C-LPR is conditional on commonsense.** `eval_tpc.py` derives the scored C-LPR from
   `evaluate_hard_constraints_v2(..., env_pass_id=commonsense_pass_id)`. A commonsense-failing query
   contributes `0` to the `0.25`-weighted C-LPR term and `0` to EPR-macro (`0.10`). The gap between
   `logical_micro` `89.47` and C-LPR `66.02` is exactly the 21 commonsense-failing plans. Making
   those valid with logic unchanged is worth about `+5.9` (C-LPR) `+2.6` (EPR-macro) ≈ **`+8.5`
   `overall_true`** before any FPR conversion.
2. **The unaccepted search key ignores commonsense.** `tpc_agent.py::_make_checker` adds
   schema/commonsense only once all parsed constraints pass (`if passed == total`).
3. **Finalization emits the parsed-pass leader.** `_solve` does
   `chosen = best_accepted if best_accepted["plan"] is not None else best`, so when nothing is
   accepted, commonsense validity of the emitted plan is incidental (39 of 60 pass by luck).
4. **The landed repair passes cannot commit where the failures live.** `_pack_plan` runs on
   unaccepted plans and calls `_repair_transport_gaps` / `_repair_intercity_endpoints` before the
   acceptance check, but both bail on `if not self._accepted(*check(trial)): return`. Acceptance
   requires all parsed constraints, so the repair is always discarded on exactly the plans that need
   it. That is why `TPC_REPAIR_TRANSPORT_GAPS` and `TPC_REPAIR_INTERCITY` gated flat — a commit-rule
   limitation, not a broken repair.
5. **Preference is capped.** `eval_tpc.cal_default_pr_score` averages DAV/ATT/DDR only over
   `all_pass_id`, so maxpack-style packing is worth near `+1` overall at FPR 25. Measure first
   (Task 1).
6. **LLM packaging.** `TPC_P2_LLM_BACKEND` defaults to `none`, `agent_env/config.toml` is gitignored
   and absent (only `.example` is tracked), `resolve_llm_client_and_flags` auto-enables `llm_parse`
   only when a backend is already configured, and `TPCAgent`'s `backbone_llm` is `TPCLLM`, whose
   `_get_response` returns the literal string `"Empty LLM response"`. As packaged the submission
   makes zero LLM calls and cannot reach the organizers' Qwen3.6-27B/SGLang endpoint.

Invariants that must not break: no oracle fields in the Phase 2 agent path; library defaults (unset
env vars) keep the deterministic floor byte-identical; every new behavior sits behind an explicit env
flag with a deterministic fallback; only grounded `WorldEnv` facts and deterministic checkers decide
acceptance.

## Design decision: one umbrella flag

All behavior changes in Tasks 2 and 3 are gated by a single env var `TPC_COMMONSENSE_FIRST`
(truthy = not in `("", "0", "false", "False")`). Library default off. When on it enables:

- the relaxed repair commit rule for unaccepted plans (Task 2),
- the commonsense-valid finalization preference (Task 3),
- `TPC_REPAIR_TRANSPORT_GAPS` and `TPC_REPAIR_INTERCITY` behavior, i.e.
  `_repair_transport_gaps_enabled()` / `_repair_intercity_enabled()` return `True` when
  `TPC_COMMONSENSE_FIRST` is truthy, unless the operator explicitly set those vars to `0`.

One flag to screen, one flag to promote.

## Task order and budget

`Task 0 → 1 → 4 → 2 → 3 → 5 → 6 → 7 → 8`, then optional `9 → 10`.
Estimates: T1 15 m, T4 20 m, T2 60 m, T3 60 m, T5 50 m, T6 20 m, T7 15 m, T8 25 m (≈ 4 h 15 m);
optional T9 45 m, T10 30 m.

## Task 0: this brief on disk

Create this file and link it from the "Active focused prompts" table in
[`docs/agents/README.md`](README.md) and from [`docs/tpc_phase2_roadmap.md`](../tpc_phase2_roadmap.md)
(the latter happens in Task 8).

## Task 1: size the lever offline (no solve, no LLM, seconds)

Implement `scripts/phase2_commonsense_headroom.py`:

- `--row` (default `results/phase2_baselines/runs/20260724T192503Z.json`),
  `--mode {end-to-end,solver-only,both}` (default `both`).
- The row holds `rehearsal.modes.<mode>.raw` with `commonsense_details` (per-uid dict of the 26
  official commonsense columns, `1` = failed) and `logical_details` (per-uid `logic_py_i` values of
  `1` / `0` / `NaN`, where `NaN` means the clause does not apply).
- Per mode, report each uid with any commonsense column `== 1`, which columns failed, and that uid's
  logical pass fraction `sum(v == 1) / count(v in {0, 1})`.
- Project: recompute `conditional_logical_micro` assuming every commonsense-failing uid passes
  commonsense with logical verdicts unchanged, set EPR-macro to `100`, and print the implied
  `overall_true` delta with weights
  `0.10 MicEPR + 0.10 MacEPR + 0.25 C-LPR + 0.40 FPR + 0.05 DAV + 0.05 ATT + 0.05 DDR`, holding FPR
  and preference fixed (state that assumption in the output).
- Secondary: for the end-to-end `all_pass_ids`, compute DAV/ATT/DDR from
  `results/phase2_e2e_tpc_phase2_familiar_100_val/<uid>.json` with the exact `eval_tpc` formulas
  (`DAV = attractions / (4 · days)`, `ATT = (-1/105) · avg_innercity_minutes + 8/7`,
  `DDR = (meals / days) / 3`, each clamped to `[0, 1]`), print the means and the implied
  `0.05 · (300 − sum)` headroom, and report skipped/missing plan files.
- Final line: `projected overall_true 47.04 -> X.XX (commonsense lever, logic held)`.

Test `tests/phase2/test_commonsense_headroom.py`: synthetic row with 2 uids (one commonsense-failing)
asserting the recomputed C-LPR and the projection.

Demo: `.venv/bin/python scripts/phase2_commonsense_headroom.py`. Record the numbers in the commit
message; they are Task 5's target. If the preference headroom is below ≈ `1.0` overall point, do no
packing work tonight.

## Task 2: relax the repair commit rule for unaccepted plans

In `chinatravel/agent/tpc_agent/tpc_agent.py`:

- Add `_commonsense_first_enabled()` next to `_repair_transport_gaps_enabled()` /
  `_repair_intercity_enabled()`, reading `TPC_COMMONSENSE_FIRST`.
- Make both `_enabled` helpers return `True` when `_commonsense_first_enabled()` is `True`, unless
  their own env var is explicitly `"0"`.
- Add a shared commit helper:

  ```python
  def _repair_commit_allowed(self, plan, trial, query, check, was_accepted):
      """Commit rule for the deterministic repair passes.

      Accepted input: unchanged legacy rule -- the trial must still be accepted and must not
      regress the preference key. Unaccepted input (only when TPC_COMMONSENSE_FIRST is on): commit
      when the trial is schema-valid, turns a commonsense-invalid plan commonsense-valid, and does
      not lower the parsed-constraint pass count.
      """
  ```

  The unaccepted branch compares `check(plan)` / `check(trial)` passed counts (the `+2`
  schema/commonsense bonus only applies when the base is full, so a straight `passed` comparison is
  safe) and requires `self._schema_ok(query, trial)`, `self._commonsense_ok(query, trial)`, and
  `not self._commonsense_ok(query, plan)`.
- Rewire the tails of `_repair_transport_gaps` and `_repair_intercity_endpoints` to call the helper,
  keeping every existing early return (`if not changed: return`, the exception swallow, and the
  `finally` that restores `_forced_inner_mode`).
- `_commonsense_ok` already returns `False` on exception; keep that degradation.

Tests: extend `tests/phase2/test_repair_transport_gaps.py` (flag-off byte-identical floor on an
unaccepted plan with a broken leg; flag-on commit that flips `_commonsense_ok`; commit refused when
the parsed pass count drops) and `tests/phase2/test_repair_intercity_endpoints.py` (flag-off
byte-identical, one flag-on commit). Existing accepted-path tests must pass unchanged.

Demo:

```bash
.venv/bin/python -m pytest tests/phase2/test_repair_transport_gaps.py \
  tests/phase2/test_repair_intercity_endpoints.py -q

TPC_COMMONSENSE_FIRST=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split tpc_phase2_familiar_100_val \
  --uid phase2_familiar_e20241028160444030851_00066 \
  --budget-sec 120 --method phase2_t2_check
```

Known intercity-failing uids for the single-uid check:
`phase2_familiar_e20241028160403455246_00065`, `phase2_familiar_e20241028160409480928_00071`,
`phase2_familiar_e20241028160444030851_00066`. Compare
`agent_env/runs/phase2_t2_check/<uid>/evaluation.json` against the same run with the flag off.

## Task 3: prefer a commonsense-valid candidate at finalization

In `_solve`:

- Add a `best_cs` bucket (`plan`/`key`/`constraints`/`check`/`params`) beside `best` and
  `best_accepted`.
- Inside `consider(...)`, only when `_commonsense_first_enabled()` and only on the path where the
  candidate set a new best search key, and only while a bounded counter allows it, evaluate
  `self._schema_ok(query, plan) and self._commonsense_ok(query, plan)`. Bound with
  `int(os.environ.get("TPC_CS_CHECK_BUDGET", "40"))` checks per `_solve` call; once exhausted stop
  checking and never raise.
- Rank `best_cs` by `(base_passed / max(base_total, 1), self._accepted_eval_key(plan))` using
  `check(plan)`.
- Selection: prefer `best_accepted`; else, when the flag is on and `best_cs["plan"]` is not `None`
  and `best["plan"]` is not commonsense-valid, choose `best_cs`; else `best`. Keep the existing
  `_pack_plan` + `_sanitize_plan_for_grounding` tail, passing the chosen bucket's `constraints`,
  `check`, and `params`.
- Mirror the same preference in the `_set_timeout_recovery_plan` export (accepted, then
  commonsense-valid, then raw leader) so a timeout recovers the same quality of plan.

Tests in `tests/phase2/test_prefer_commonsense_valid.py`: flag off returns today's plan; flag on
returns the commonsense-valid lower-key candidate; an accepted candidate still wins;
`TPC_CS_CHECK_BUDGET=0` behaves like flag off. Reuse the stubbing patterns in
`tests/phase2/test_pin_timed_windows.py` so no `WorldEnv` is needed.

Demo: `.venv/bin/python -m pytest tests/phase2 -q` green, plus one uid from the commonsense-failing
set whose emitted plan changes and whose `evaluation.json` commonsense columns go to all-zero.

## Task 4: surface the per-layer metrics in the quick screen

In `scripts/phase2_quick_eval.py::_run_condition`, read `m.get("raw", {})` and copy
`commonsense_micro`, `commonsense_macro`, `logical_micro`, `logical_macro`,
`conditional_logical_micro`, `all_pass_count`, `commonsense_pass_count` into the arm dict, and print
them for both arms in the A/B summary. Do not change the gate-shaped keys (`fpr`,
`continuous_score`, `parse_failures`, `timeouts`) and do not touch `decide_verdict` or
`phase2_gate.check_gate`.

Test: synthetic `rehearse` report asserting extraction and safe defaults for missing keys.

Demo: a 2-uid screen (`--n 2 --budget-sec 30 --parallel 2`) prints the new columns for both arms.

## Task 5: paired screen on this MacBook (≤ ~1 h)

8 cores, up to 7 workers. LLM backend left at `none`, so zero LLM calls:

```bash
.venv/bin/python scripts/phase2_quick_eval.py \
  --flag TPC_COMMONSENSE_FIRST --on 1 \
  --mode end-to-end --n 40 --budget-sec 120 --parallel 7
```

Then `--mode solver-only` if time remains.

Promotion bar (all must hold):

- `continuous_score` up by more than the `0.5` noise band,
- `conditional_logical_micro` up and `commonsense_macro` up,
- `fpr` not lower,
- no new `timeouts`, no new `parse_failures`.

If the verdict is MIXED, re-run at `--n 20` with one arm per mechanism: candidate A = repair rule
only (`TPC_COMMONSENSE_FIRST=1` plus `TPC_CS_CHECK_BUDGET=0`), candidate B = full flag. Record which
mechanism carries the effect.

Save the screen JSON under `results/phase2_baselines/screens/` with date, mode, `n`, budget, and flag
in the filename, and commit it.

## Task 6: promote if green

In `agent_env/scripts/solve_phase2.py::apply_deterministic_solver_defaults()`:

```python
if "TPC_COMMONSENSE_FIRST" not in os.environ:
    os.environ["TPC_COMMONSENSE_FIRST"] = "1"
```

Document the promoting evidence in the docstring the way `TPC_PIN_TIMED_WINDOWS` and
`TPC_SOLVE_CONVERGE_PATIENCE` are documented (screen id, `n`, budget, deltas). The library default
stays off and the byte-identical floor tests must still pass.

Verify with `.venv/bin/python -m pytest tests/phase2 -q` and
`make phase2-solve P2_SPLIT_SET=val P2_BUDGET=120 P2_LIMIT=1`. If the screen was not green, skip this
task, leave the flag off, and say so explicitly in Task 8's doc update.

## Task 7: second-machine handoff

Create `docs/agents/final_night_eval_commands.md` with copy-paste-only blocks and no interpretation
required: the promoted SHA (`git rev-parse HEAD`), prerequisites (Python 3.12 venv,
`requirements.txt`, environment database, LLM backend unset), two pinned `900 s` `familiar_100_val`
rows at that SHA (one arm with `TPC_COMMONSENSE_FIRST=0`, one with harness defaults),
`--repeats 2 --parallel 3` via the existing `make phase2-baseline-at SHA=<sha> ...` interface
(verify the target name and variables in the `Makefile` first), and the exact
`git add results/phase2_baselines/runs/ && git commit && git push` follow-up.

## Task 8: update roadmap and README

In `docs/tpc_phase2_roadmap.md`: replace the "Last-evening plan (2026-07-26)" section with this
plan and the actual outcome of Tasks 1-6; add a "Commonsense-first finding" section recording the
C-LPR conditionality arithmetic (`logical_micro` `89.47` vs C-LPR `66.02`, 21/80 commonsense
failures), the repair-commit-rule root cause for the earlier flat gates, the Task 1 projection, and
the preference cap; correct the standing claim that solver-side logical quality is the sole binding
ceiling; record the LLM packaging finding and what Task 9 did or did not change; fix the duplicated
"Solver-only headroom" heading; and link both new agent docs.

Update the README "Current state" paragraph only if Task 6 promoted, phrased as screen evidence, not
a gate.

## Task 9 (optional): make the organizers' LLM reachable, default off

In `chinatravel/agent/phase2/llm_client.py::build_llm_client` and
`agent_env/scripts/solve_phase2.py::_phase2_llm_config`: when `TPC_P2_LLM_BACKEND` is unset and no
config backend is given, auto-select the `openai` backend if any of `TPC_P2_LLM_BASE_URL`,
`OPENAI_BASE_URL`, `OPENAI_API_BASE`, `SGLANG_BASE_URL` is set. Resolve the model from
`TPC_P2_LLM_MODEL` or `OPENAI_MODEL`, else query `<base_url>/models` once with a short timeout and
take the first id; any failure degrades to the `none` backend rather than raising. Keep the parse
audit off when the backend was auto-detected unless the operator set `TPC_P2_LLM_PARSE` explicitly.
Add a tracked `agent_env/config.phase2.example.toml` documenting the `[phase2.llm]` SGLang wiring.

Tests: monkeypatched-env only, no network. A fake `OPENAI_BASE_URL` yields `backend == "openai"` with
`llm_parse is False`; nothing set yields `backend == "none"`; a failing model probe degrades to
`none`.

## Task 10 (optional, after Task 9): three-arm LLM parse screen

`n=20`, `--budget-sec 120`, arms: parse off, `TPC_P2_LLM_PARSE=1` (audit), and
`TPC_P2_LLM_PARSE=1 TPC_P2_LLM_PARSE_MODE=extract`. Use `TPC_P2_LLM_BACKEND=deepinfra` and set
`TPC_P2_LLM_TIMEOUT_SEC` below the parse slice (about `8` at a `120 s` budget); do not source or echo
`.env` (`load_local_env()` reads `DEEPINFRA_API_KEY` itself). Confirm `llm_parse_fired > 0` before
trusting an arm. Ship an LLM parse mode only if it beats parse-off on both `fpr` and
`continuous_score` with no new parse failures; otherwise set `TPC_P2_LLM_PARSE=0` explicitly for the
submission harness and record that decision in the roadmap.

## Risks and mitigations

- Tasks 2 and 3 are screened together under one flag; if the verdict is MIXED, split them at `n=20`
  as described in Task 5.
- `_commonsense_ok` runs the full official evaluator and costs wall clock inside the solve loop. It
  is bounded by `TPC_CS_CHECK_BUDGET` (default `40`) and watched via the screen's timeout counter; if
  timeouts appear in the candidate arm, lower the default to `15` and re-screen.
- Everything is off by default in the library, so the promoted `20260724T192503Z` configuration stays
  shippable if the screen is not green.
- Do not chase the `Is_time_correct_strict` "patched" scoring; the official lenient checker is what
  the organizers run. Patched numbers are a self-audit only.
