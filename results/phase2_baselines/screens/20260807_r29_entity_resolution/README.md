# R29 — does deterministic entity resolution convert end-to-end?

**Date** 2026-08-07 · **Branch** `eval/r29-entity-resolution-e2e` · **`git_sha`** `2c730daf`
(current `main` tip; post-R28 `aed4363e`, includes the P22 merge `c75ec1a0` — P22 defaults off, so it
does not affect this row) · **host** 4-core Linux (3 workers) · **Contract** two per-query e2e
screens (`phase2_quick_eval.py --mode end-to-end` for familiar-100, direct sharded
`solve_phase2.py` for the free-prose register — see "Deviations from the doc" below), plus the
already-committed static parse-diff probe. Not a `full_runs/`/`runs/` row.
Evaluation workstream instrument:
[R29](../../../../docs/tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end),
gating [P21](../../../../docs/tpc_phase2_roadmap.md#p21--promote-deterministic-entity-resolution).

## Headline finding: the flag is not actually off-by-default on the harness path — it already fired in R28 and in `v1`

The doc frames this row as measuring an "already-landed, default-off" flag, citing only
`Flags()`/`Flags.from_env({})` (true — `chinatravel/agent/phase2/orchestrator.py:89`,
`entity_resolution: bool = False`). But the code path every real run actually takes,
`agent_env/scripts/solve_phase2.py:resolve_llm_client_and_flags()` (called from `run_split`, which
is what both `solve_phase2.py`'s CLI and the organizer harness entry point dispatch to), overrides
that:

```python
if "TPC_P2_ENTITY_RESOLUTION" not in os.environ:
    flags.entity_resolution = True
```

— the same auto-promotion pattern already used for `disjunction` and `dynamic_budget`. This landed at
`b53a0747` ("phase2(plan3 N2): deterministic entity-resolution layer", 2026-07-13), which is an
ancestor of **both** [R28](../../../../docs/tpc_phase2_eval.md#r28--a-whole-run-row-on-the-current-main)'s
`aed4363e` and the `v1` submission's build ancestor `be196d00`
(`git merge-base --is-ancestor b53a0747 <ref>` confirms both).

**Confirmed directly against R28's own on-disk telemetry**, not just by reading code — every
`telemetry.json` under `agent_env/runs/phase2_e2e_tpc_phase2_familiar_100/*/` (mtimes `2026-08-07
15:xx–16:4x` UTC, matching R28's run window) shows:

```json
"flags": {"disjunction": true, "llm_parse": false, "llm_parse_mode": "audit",
          "llm_refine": false, "dynamic_budget": true, "entity_resolution": true}
```

**So R28's baseline row and the held-out `v1` score already include `entity_resolution=1`.** This
does not change either recorded number (they are what they are), but it means:

- The roadmap's promotion bar text — "GREEN → add `entity_resolution` to `PROMOTED_SOLVER_FLAGS` and
  set it in `apply_deterministic_solver_defaults()`" — describes an action that is **already a
  behavioral no-op** on the harness path; the flag fires today regardless. What a GREEN here actually
  licenses is formalizing the bookkeeping (moving it out of the "isolated, unmeasured" category) and
  updating the doc's own "landed and default-off" framing, not flipping a switch that changes
  submission behavior.
- The correct experimental framing is therefore reversed from the doc's: **on** is the shipped/`R28`
  configuration; **off** is the counterfactual (what would have shipped if this override had never
  landed). Both arms below still isolate exactly one variable, so the mechanics are unaffected — only
  the reading is.
- This does **not** explain the `v1` held-out shortfall by itself — `v1`'s low C-LPR/FPR happened
  *with* this flag on. It does mean nobody had actually measured what turning it *off* would cost, which
  is what R29 was nominally for; that measurement is still useful and is below.

## Deviations from the doc's literal commands

1. **`--mode end-to-end` added explicitly.** `phase2_quick_eval.py`'s default mode is `solver-only`,
   which feeds the solver oracle `hard_logic` directly and never calls `chinatravel/agent/phase2/normalize.py`
   — so a parse-time hook like `entity_resolution` is structurally inert there. The doc's own prose
   calls this "the paired **e2e** A/B" but the literal command omits `--mode`; ran with
   `P2_QE_MODE=end-to-end`/`--mode end-to-end` to actually exercise the flag.
2. **No `--split` flag on `phase2_quick_eval.py`.** The doc's free-prose command
   (`--split <materialized hf_medium subset>`) names a flag that does not exist on this script —
   `--split-set` only accepts the fixed `{val,test,familiar_100,familiar_100_val,familiar_100_test}`
   enum. Per the R24/R25/R26 precedent (and confirmed with the advisor before spending the slot), ran
   the free-prose arm as a direct paired `solve_phase2.py` invocation on a materialized split instead
   of extending `phase2_quick_eval.py` — adding a `--split` option there is implementation-workstream
   scope, not something this row should do to get its own answer.

## Method

**Static probe** (already committed at this path, reproduced first as the doc requires):
`scripts/phase2_entity_resolution_arms_probe.py` — see `summary.md` / `report.json` in this
directory. Byte-identical to the numbers already recorded in
[P21](../../../../docs/tpc_phase2_roadmap.md#p21--promote-deterministic-entity-resolution) and
[R29's own doc entry](../../../../docs/tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end).

**Familiar-100 e2e A/B** (`familiar100_e2e/`):
```
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_ENTITY_RESOLUTION \
  --mode end-to-end --split-set familiar_100_val \
  --n 40 --budget-sec 90 --parallel 3 \
  --out results/phase2_baselines/screens/20260807_r29_entity_resolution/familiar100_e2e
```
Paired same-subset/same-seed (`seed=20260705`), `TPC_P2_ENTITY_RESOLUTION` the only variable.

**Free-prose e2e A/B** (`hfmedium_e2e_summary.json`): materialized 30 uids from HF `medium`
(deterministic prefix, `scripts/materialize_hf_split.py --hf-split medium --name hf_medium_r29
--limit 30`), then two arms, each 3-way sharded across `cores-1` `solve_phase2.py` subprocesses
(one uid file per shard, no `--resume`, distinct `--method` per arm, arms run strictly sequentially —
same discipline as R24/R25/R26):
```bash
TPC_P2_ENTITY_RESOLUTION=0 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split hf_medium_r29 --uids-file <shard> --method phase2_e2e_r29_hfmedium_off \
  --budget-sec 90 --lang en
TPC_P2_ENTITY_RESOLUTION=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split hf_medium_r29 --uids-file <shard> --method phase2_e2e_r29_hfmedium_on \
  --budget-sec 90 --lang en
```
Scored with `eval_tpc.py --splits hf_medium_r29 --method <method> --lang en`. The materialized split
(`chinatravel/data/en/hf_medium_r29/`, `chinatravel/evaluation/default_splits/hf_medium_r29.txt`) was
**deleted immediately after scoring** — confirmed absent from `git status`.

Both arms' `telemetry.json` were read directly to confirm (a) `flags.entity_resolution` actually
toggled `False`/`True` on all 30 uids in each arm respectively, and (b) `llm_parse`/`llm_refine`
stayed `False` throughout (`llm_parse_fired: 0`, `refine_called: 0`) — zero LLM calls in both arms,
confirmed from telemetry rather than assumed from the backend default, as the doc requires.

## Result

### Familiar-100 (n=40, budget=90s, end-to-end): GREEN

| metric | off | on | Δ |
| --- | --- | --- | --- |
| FPR (pass %) | 45.00 | 50.00 | **+5.00** |
| overall_true (continuous) | 64.83 | 67.53 | **+2.70** |
| C-LPR (conditional logical micro) | 91.10 | 91.55 | **+0.46** |
| EPR-macro / EPR-micro | 100.0 / 100.0 | 100.0 / 100.0 | flat |
| commonsense pass (n) | 40/40 | 40/40 | flat |
| all_pass (n) | 18 | 20 | **+2** |
| timeouts | 0 | 0 | flat |
| `llm_parse_fired` | 0 | 0 | flat (zero LLM calls, both arms) |
| parse_failures | 0 | 0 | flat |
| solve p50 (sec) | 81.14 | 81.05 | flat |

Monotonic gate: **PASS**. `phase2_quick_eval.py`'s own verdict: **GREEN LIGHT**. Two additional
queries flip from failing to fully-passing with the flag on and nothing regresses — this is the first
row that turns P21's static parse-diff gain into an actual scored-query flip, on the register where
the static probe predicted a real gain (English-literal oracle values).

### hf_medium free prose (n=30, budget=90s, end-to-end): NEUTRAL — byte-identical plans

| metric | off | on |
| --- | --- | --- |
| FPR | 16.67 | 16.67 |
| overall | 49.99 | 49.99 |
| C-LPR | 86.25 | 86.25 |
| MicEPR / MacEPR | 100.0 / 100.0 | 100.0 / 100.0 |

**All 30/30 plan files are byte-identical between arms** (modulo the timing field) — not just the
aggregate score. This is the expected shape given the static probe: `hf_medium`'s F1 was already
flat-to-slightly-negative off→on (`0.7404 → 0.7384`, +5 spurious `position_presence` clauses from the
category-misroute reroute) because the oracle literals are Chinese while the corrected values are
English — there is no clause here entity resolution's English-literal repair can turn into a pass.
Also remember `hf_medium`'s own FPR ceiling under `--lang en` is **38.67**, not 100 — `16.67` is
`43%` of what's reachable, same caveat as every other free-prose number in this document.

## Reading against the doc's own acceptance bar

**GREEN** was defined as: `overall`/FPR up or flat on familiar-100, up on free prose, no new timeouts,
`EPR-macro` not falling. **RED**: any FPR fall on either register, or a rise in `spurious` clauses at
the parse level. **NEUTRAL was explicitly sanctioned** as a real, informative outcome on free prose.

Measured: familiar-100 **GREEN** (FPR/overall/C-LPR all up, zero regressions). Free prose **NEUTRAL**,
not RED — no FPR fall, and the static probe already predicted exactly this shape (flat `matched`,
small `spurious` uptick that this particular 30-uid e2e sample happened not to hit). Overall verdict:
**GREEN**, on the strength of the familiar-100 flip and the absence of any RED condition, with the
free-prose NEUTRAL read as the doc says to read it — raising [R30](../../../../docs/tpc_phase2_eval.md#r30--does-dropping-unsatisfiable-names-flip-queries)'s
relative priority, since the English-literal-value fix this flag provides has already been shown to
have no further free-prose headroom to give.

## What this authorizes

Per [P21](../../../../docs/tpc_phase2_roadmap.md#p21--promote-deterministic-entity-resolution)'s own
bar, GREEN authorizes formalizing `entity_resolution` as a recorded, committed-default configuration
(it already fires today; this makes that fact explicit and durably documented rather than an
undocumented side effect of `resolve_llm_client_and_flags()`) plus a `full_runs/` row — which, given
the flag was already on for [R28](../../../../docs/tpc_phase2_eval.md#r28--a-whole-run-row-on-the-current-main),
**does not require a new whole-run row to re-confirm familiar-100** (R28 already is that row, with
the flag on). What remains open, and is genuinely new information from this row, not yet measured
anywhere: whether an operator who explicitly sets `TPC_P2_ENTITY_RESOLUTION=0` (turning the harness
default *off*) would score worse — this row's familiar-100 arm says yes, by a measurable margin, on a
40-query screen; a `full_runs/` row confirming this at n=100 has not been done and is the honest
"promotion still needs a pinned gate" item, same shape as R26's close.

**Recommended follow-up (not this row's job):** the roadmap and eval doc should stop describing this
flag as "off by default" without the harness-path qualifier, since that framing is what let this ship
unmeasured-as-isolated for three weeks. See the doc updates accompanying this PR.
