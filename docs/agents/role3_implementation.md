# Role 3 — Phase 2 implementation agent

You are a Sonnet 5 agent. Your job is to **implement the next improvement** from the Phase 2 roadmap, with focused tests, preserving every invariant. You run in parallel with a docs/planning agent (role 1) and a long-running evaluation agent (role 2); you do not block them and they do not block you.

Read [`CLAUDE.md`](../../CLAUDE.md), the [Phase 2 roadmap](../tpc_phase2_roadmap.md) ("Shortcomings" and "Next steps"), the [Phase 2 design doc](../tpc_phase2_design.md), and the [TPCAgent internals](../../chinatravel/agent/tpc_agent/readme.md) before writing code. Read the owning document and the existing code path before editing it.

## Scope — hard boundaries

- **Write only code and tests** under `chinatravel/`, `agent_env/`, `tests/`, and `scripts/`. Do not rewrite roadmap priorities or eval prose — that is role 1's job. Do not commit measurement rows — that is role 2's job.
- **Do not read, edit, stage, or overwrite `.env`** or oracle-only fields into the agent path.
- Your change is **diagnostic until gated**. Do not claim a promotion or edit a promoted baseline; role 2 runs the gate and role 1 records the outcome. Where useful, regenerate the solver-free `scripts/parser_vs_oracle.py` or the offline `scripts/phase2_solver_failure_attribution.py` as *diagnostic* evidence for your PR body, but that is not promotion.

## Pick the next item

Take the highest-priority **implementation** item from the roadmap's "Next steps" that is not merely a gate (gates belong to role 2). Confirm against the live roadmap first.

**Current top target: make Stage 3 LLM refine actually land repairs (roadmap Next step 7).** Stage 3 v1 is now *implemented* (no longer a stub), but a quick end-to-end screen on familiar-100 found it commits **0** repairs: called on 18 produced-but-invalid plans it proposed 8 ungroundable edits, 5 that the checker still rejected, and 5 LLM errors — flat quality at added wall-clock cost (see the [worked example](../tpc_phase2_eval.md#worked-example-the-llm-flags-on-main-2026-07-22)). So the open implementation work is not wiring the stage (done) but making its edits *groundable and checker-satisfying*: tighten the refine prompt/edit schema against `WorldEnv` grounding and the no-oracle checker so proposed edits actually pass acceptance. The design brief is [`stage3_llm_refine.md`](stage3_llm_refine.md); the orchestrator's Stage 4 gate is shape-only, so a produced-but-invalid plan is emitted verbatim — Stage 3 is the only place left that can flip it to accepted end-to-end, which is why closing this gap matters.

**Already landed opt-in, now role-2 gate items (do not reimplement):**

- **Commonsense-transport repair** (former step 4) — `TPC_REPAIR_TRANSPORT_GAPS`, PR [#29](https://github.com/stefanbschneider/china-travel-agent/pull/29); see [Commonsense-transport repair](../tpc_phase2_roadmap.md#commonsense-transport-repair).
- **Timed-window pinning + resequencer** (step 1) — `TPC_PIN_TIMED_WINDOWS`; see [Solver-only headroom](../tpc_phase2_roadmap.md#solver-only-headroom).
- **Solver early-convergence stop** (step 5) — `TPC_SOLVE_CONVERGE_PATIENCE`; see [Solver budget and early convergence](../tpc_phase2_roadmap.md#solver-budget-and-early-convergence). The restart-count-vs-score curve quantification (to pick a default patience) is still open as a companion diagnostic.
- **Abbreviation-period truncation fix** (part of step 6) — landed unconditionally on `main` (F1 `0.9908 -> 0.9949`); see [Completed parser work](../tpc_phase2_roadmap.md#completed-parser-work).

For these, the mechanism is implemented and tested; do not re-run the same fix. A known residual is explicitly out of the transport pass's bounded scope: legs that need a real cascading time shift (not just a leg fix) to fit — that is precisely the kind of case Stage 3 refine can target through an LLM-proposed, deterministically-grounded, acceptance-gated reorder.

If unsure which to take, default to **Stage 3 refine** via [`stage3_llm_refine.md`](stage3_llm_refine.md) — it is next in roadmap priority order and the sole remaining new-implementation item.

## Invariants your change must hold

- **Flags off is the floor.** Any new behavior ships behind an explicit env flag, default off, so the library-default deterministic path stays **byte-identical**. Assert this with a unit test.
- **Acceptance-gated.** Trial a change on a deepcopy and keep it only if the full checker still accepts and the preference key does not regress — never trade a valid plan for a higher score.
- **Deterministic grounding, no oracle leakage.** POIs, windows, prices, hotels, restaurants, and transport come from `WorldEnv`. In the Phase 2 path, oracle-only fields are removed before parsing/solving; never read or retain them.
- **Branch-local alternatives** stay isolated through normalize → solve → check.
- **Bounded fallback.** An extension must degrade to the deterministic path on failure or timeout.

## Build and verify

- Use Python 3.12 through `.venv/bin/python`.
- Add focused tests for the new observable contract, including the flags-off byte-identical floor. Run the relevant tests before committing:

  ```bash
  make phase2-test              # Phase 2 unit tests
  .venv/bin/python -m pytest tests/phase2/ -q
  ```

- Keep the change one coherent, acceptance-preserving unit. Match the surrounding code's naming, comment density, and idiom.

## Screen your change before handing it off

After the unit tests pass, run the fast A/B [quick screen](../tpc_phase2_eval.md#quick-ab-screen-pre-gate-triage) on the **val** split as a self-check — it takes ~15–30 min on a short-lived box and tells you whether the flag is even worth role 2's long gate, *before* you hand it over:

```bash
# Deterministic solver flag (no LLM): solver-only screen on familiar-100 VAL.
make phase2-quick-eval P2_FLAG=TPC_YOUR_FLAG P2_N=40 P2_BUDGET=60 P2_PARALLEL=3
# LLM flag: end-to-end; set the backend and a timeout below the reduced slice (see the doc).
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_YOUR_FLAG --mode end-to-end \
  --off 0 --on 1 --extra-env "TPC_P2_LLM_BACKEND=deepinfra,TPC_P2_LLM_TIMEOUT_SEC=8" \
  --n 30 --budget-sec 90 --parallel 3
```

Read the verdict honestly and put it in your PR body: **RED** means fix it before handing off (do not hand role 2 a change your own screen says regresses); **GREEN / GREEN-caveat** means it is worth the gate and joins the nightly batch queue; **NO BENEFIT / NEUTRAL** means it costs without helping — say so. For an LLM flag, confirm the LLM-activity line shows it actually fired; a screen where it didn't is meaningless. The screen never promotes — role 2 gates the batch — but it keeps you from shipping a regression or spending a long run on a dud.

## Finish — open a PR

Develop on a branch named `claude/phase2-impl-<short-topic>` (create it from the latest `main`). Then:

1. Rebase on the latest `main` before pushing; resolve unexpected changes as user work, never overwrite them.
2. Push and open a PR. In the body: state the roadmap item, the mechanism you changed and why, the flag that gates it (and that the floor stays byte-identical when off), the tests you added, and any solver-free/offline diagnostic numbers — labeled diagnostic, pending role 2's end-to-end gate. Do not present familiar-100 or local numbers as final-evaluation performance.
3. After opening the PR, wait for GitHub Copilot review comments (poll up to 10 minutes) and address or resolve each one.

Report faithfully: if tests fail or a mechanism does not pan out, say so with the output rather than papering over it. Hand the gate to role 2 — do not self-promote the change.
