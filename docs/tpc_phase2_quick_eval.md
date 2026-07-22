# TPC 2026 Phase 2 Quick A/B Screen

A way to decide, **within an hour or two on a short-lived box**, whether a landed-but-ungated
Phase 2 improvement helps enough to flip its default on — without waiting for the 8h+ pinned
end-to-end baseline that runs continuously on the evaluation machine.

This is a **screen, not a promotion gate.** It ranks and triages changes so the slow pinned gate
(`make phase2-baseline-at` + `make phase2-gate`, see [evaluation](tpc_phase2_eval.md)) is only spent
on changes that already show a positive signal. A screen never promotes a change by itself; the
[measurement rules](tpc_phase2_eval.md#gates) and the [roadmap](tpc_phase2_roadmap.md) gate items
still own promotion.

## Why the slow gate is slow, and how the screen gets around it

The pinned end-to-end baseline runs `100` familiar-100 queries at a `300 s` solve budget, twice.
The solver's random-restart loop spends the whole budget (solve `p50 ≈ 270 s` at a `300 s` budget),
so wall-clock is roughly `queries × budget × repeats / parallelism` — hours.

The screen cuts that on three independent axes at once, and trusts only the **paired delta**, never
the absolute numbers:

1. **Subset.** A deterministic slice of the split (`--n`, default `40`) instead of all `100`.
2. **Reduced budget.** `--budget-sec` (default `60`) instead of `300`. The deterministic solver
   flags act at the **acceptance boundary** inside `_pack_plan` (before the acceptance gate), so
   their effect on FPR shows up even when the restart loop is cut short. Measured: solver-only FPR
   is `20%` on `n=30` at `60 s`, versus `25.5%` on the full `100` at `300 s` — the reduced budget
   recovers most of the signal.
3. **Paired same-everything A/B.** Baseline (flag off) and candidate (flag on) run on the **same**
   subset, budget, and seed; only the one flag changes. Because everything else is held fixed, the
   *difference* isolates the flag even though the reduced-budget absolute FPR is not comparable to a
   full pinned row. This is a controlled experiment, not a baseline row.

The tool is [`scripts/phase2_quick_eval.py`](../scripts/phase2_quick_eval.py).

## What it measures

Default mode is `solver-only` (oracle constraints fed to the bounded solver, **no LLM**, fully
deterministic on this box) because that is what the highest-leverage recent flags target. For each
arm it reports, from the run's per-query results and telemetry:

| Signal | Meaning | Better |
| --- | --- | --- |
| `FPR` | % of queries whose final plan passes every check (the target of the acceptance-flipping flags) | higher |
| `overall_true` | mean per-query preference-weighted score (`continuous_score`) | higher |
| `timeouts` | queries that hit the budget wall (all recovered via the timeout snapshot unless `used_fallback` moves) | lower |
| `solve p50` | median solve wall-time | lower |
| `used_fallback` | queries that fell back to the schema-shaped empty plan (a real correctness loss) | lower |
| `parse_failures` | invalid-JSON / eval / solver errors | lower |

It then runs the existing monotonic [`phase2_gate.check_gate`](../scripts/phase2_gate.py) on the
gate-shaped keys (`fpr`, `continuous_score`, `parse_failures`, `timeouts`) and prints a reconciled
verdict (see [reading the verdict](#reading-the-verdict)).

## Setup on a fresh box (no GPU needed)

The screen never loads a local model, so the heavy GPU requirements (`torch`, `vllm`,
`flashinfer`, `transformers`, …) are not needed — they are lazily imported only by the local-model
LLM backends. A minimal CPU-only environment is enough:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install \
  geopy==2.4.1 numpy==1.26.4 pandas==2.2.3 jsonschema==4.23.0 tqdm==4.66.6 \
  openai==1.53.0 json_repair==0.30.0 scikit-learn==1.5.2 psutil==7.2.2 \
  packaging==24.2 fuzzywuzzy==0.18.0 func_timeout==4.3.5 httpx==0.27.2 \
  z3-solver==4.14.1.0 ortools==9.9.3963 tiktoken==0.9.0 python-Levenshtein==0.25.1
```

The environment database under `chinatravel/environment/database_en/` and the imported
`tpc_phase2_familiar_100` split must be present (they are committed).

## How to run

```bash
# Screen the timed-window pinning flag, solver-only, 40 queries at a 60s budget, 3 in parallel:
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_PIN_TIMED_WINDOWS \
    --n 40 --budget-sec 60 --parallel 3 --out results/phase2_quick_eval/pin

# Screen the early-convergence stop at patience 15 (its target is fewer timeouts at held FPR):
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_SOLVE_CONVERGE_PATIENCE \
    --on 15 --n 40 --budget-sec 60 --parallel 3

# Stack flags: screen repair on top of an already-on pin:
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_REPAIR_TRANSPORT_GAPS \
    --extra-env TPC_PIN_TIMED_WINDOWS=1 --n 40 --budget-sec 60 --parallel 3
```

**Reuse one baseline across several flags.** The `flag=off` arm is identical (all-flags-off, same
subset/budget/seed) for every deterministic solver flag, so run it once and reuse it:

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_PIN_TIMED_WINDOWS \
    --n 40 --budget-sec 60 --out results/phase2_quick_eval/pin
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_REPAIR_TRANSPORT_GAPS \
    --n 40 --budget-sec 60 --baseline-json results/phase2_quick_eval/pin/baseline.json
```

This halves the cost of each additional flag (candidate arm only). You are responsible for the
subset/budget/seed matching; the tool trusts the reused baseline.

### Cost model

Wall-clock per arm ≈ `ceil(n / parallel) × (budget_sec + ~3 s startup)`. On a 4-core box with
`--parallel 3`:

| n | budget | per arm | both arms |
| --- | --- | --- | --- |
| 30 | 60 s | ~11 min | ~23 min |
| 40 | 60 s | ~14 min | ~28 min |
| 40 | 90 s | ~21 min | ~42 min |

Screening three flags against one shared baseline (one baseline arm + three candidate arms) at
`n=40, 60 s` is `~4 × 14 min ≈ 55 min` — comfortably inside a 1–2h session. Keep `--parallel` at
`cores − 1`: each CP-SAT solve is single-threaded, and one core is left for the OS/orchestrator.

## Reading the verdict

The screen reconciles the target signal against the strict monotonic gate:

- **GREEN LIGHT** — target signal improves *and* the like-for-like gate passes. Spend a pinned gate.
- **GREEN LIGHT (with caveat)** — target signal improves, but the *only* gate block is more
  timeouts at the tight screen budget (all recovered). This is expected when a flag does more work
  per solve: fewer restarts fit in the reduced budget, so more queries hit the wall — a wall-clock
  cost, not a correctness loss. The pinned gate at full budget must confirm the cost is acceptable;
  the acceptance/preference gain is real. **Still worth a pinned gate.**
- **MIXED** — target improves but the gate blocks on a non-timeout metric. Read the blocks first.
- **RED** — a correctness signal regresses (FPR, `overall_true`, or `parse_failures`). Do not
  default on; investigate before spending a pinned gate.
- **NEUTRAL** — no measurable delta. Enlarge `--n`/`--budget-sec` or choose a subset that actually
  exercises the flag.

The strict gate blocking on timeouts alone is *informative, not disqualifying* on a screen — it is
precisely the "FPR/timeout-boundary nondeterminism at tight budgets" the
[gate doc](tpc_phase2_eval.md#gates) warns about. That is why the screen prints both the raw gate
result and a reconciled verdict.

## Worked example: the ungated solver flags on `main` (2026-07-22)

Solver-only, `tpc_phase2_familiar_100`, deterministic subset `n=30`, `60 s` budget, `--parallel 3`,
seed `20260705`, one shared all-flags-off baseline (FPR `20.0`, `overall_true 43.88`, `7` timeouts).
Screen only — reduced-budget deltas, not a promotion.

| Flag | FPR | overall_true | timeouts | Screen verdict |
| --- | --- | --- | --- | --- |
| `TPC_PIN_TIMED_WINDOWS=1` | `20.0 → 26.67` (**+6.67**) | `43.88 → 49.88` (**+6.00**) | `7 → 9` | GREEN LIGHT (caveat: +2 recovered timeouts) |
| `TPC_REPAIR_TRANSPORT_GAPS=1` | `20.0 → 23.33` (**+3.33**) | `43.88 → 46.60` (**+2.72**) | `7 → 8` | GREEN LIGHT (caveat: +1 recovered timeout) |
| `TPC_SOLVE_CONVERGE_PATIENCE=15` | `20.0 → 20.0` (+0.0) | `43.88 → 46.16` (+2.28) | `7 → 6` (**−1**) | GREEN LIGHT (weak: −1 timeout is at the noise floor) |

**Reading it:** both `TPC_PIN_TIMED_WINDOWS` and `TPC_REPAIR_TRANSPORT_GAPS` clearly move their
target metric (solver-only FPR, the binding ceiling per the [roadmap](tpc_phase2_roadmap.md)) and
the preference score in the right direction, at the cost of a small number of *recovered* timeouts
from the extra per-candidate work. Neither loses a plan to the fallback and neither adds a parse
failure. `TPC_SOLVE_CONVERGE_PATIENCE=15` holds FPR and shaves a timeout without any regression, but
its `−1` timeout delta is inside the run-to-run noise floor, so it is a *weak* positive: it targets
wall-clock, whose payoff only shows clearly at the full `300 s` budget where the restart loop
actually plateaus — the screen confirms it does no harm and is safe to carry into the pinned patience
sweep the roadmap calls for, rather than proving a win on its own.

**Decision:** all three earn time on the pinned end-to-end gate (roadmap Next steps 1, 4, 5) — the
two acceptance-flippers as strong candidates, the convergence stop as a no-harm wall-clock tweak to
sweep. The screen cannot flip a default by itself, but it turns "we have not measured it" into a
ranked, evidenced go/no-go, which is the whole point.

## Limits — read before trusting a screen

- **A screen never promotes.** A positive screen authorizes spending a pinned end-to-end gate; only
  that gate, on a committed row from a pinned SHA, promotes a default. This preserves the
  [non-negotiable invariants](../CLAUDE.md#non-negotiable-invariants) — "flags off is the floor" and
  "a measurement promotes a change only through the gate".
- **Absolute numbers are not comparable to a ledger row** (reduced budget/subset). Only the paired
  delta at a fixed budget is meaningful. Do not commit screen outputs into
  `results/phase2_baselines/`.
- **Timeout counts carry run-to-run noise** — the wall-clock-bounded restart loop picks different
  random params each run, so a `±1–2` timeout swing at a tight budget is nondeterminism, not a
  regression. That is exactly why FPR/`continuous_score` are the correctness signals and the
  timeout-only gate block is a caveat, not a red.
- **Familiar-100 is a development signal, not the held-out set.** A screen inherits every
  [dataset-boundary caveat](tpc_phase2_eval.md#dataset-boundaries); it never estimates final
  performance.
- **Use `n ≥ 30`.** Smaller subsets are dominated by per-query noise; verdicts on `n < 30` are
  smoke checks only.

## LLM-backed flags (`TPC_P2_LLM_PARSE`, `TPC_P2_LLM_REFINE`)

The same tool screens the LLM flags with `--mode end-to-end` and a configured Phase 2 backend.
Unlike the deterministic flags, these require a reachable OpenAI-compatible endpoint:

```bash
# with agent_env/config.toml [phase2.llm] backend set (or the env vars below), and the key sourced:
export TPC_P2_LLM_BACKEND=deepinfra          # or openai
export TPC_P2_LLM_MODEL=Qwen/Qwen3.6-27B-Instruct
# DEEPINFRA_API_KEY / OPENAI_API_KEY must be in the environment (source .env)
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_LLM_REFINE \
    --mode end-to-end --n 30 --budget-sec 120 --parallel 3
```

Notes specific to the LLM flags:

- With the backend at `none` (the library default), the end-to-end path makes **zero** LLM calls,
  so the deterministic solver flags can also be screened `--mode end-to-end` on a box with no key.
- `TPC_P2_LLM_PARSE` is auto-enabled by the harness whenever a backend is configured, so to screen
  it cleanly set `--off 0 --on 1` explicitly and keep the backend fixed across both arms (the tool
  passes the flag as an env override, which wins over the auto-enable).
- Give the LLM arm a larger `--budget-sec` (the refine/parse call must fit inside the stage slice)
  and expect higher per-arm wall-clock from network latency.
- The screen's honesty rules are unchanged: a green screen still only earns the pinned paired
  on/off gate at one SHA (roadmap Next steps 3 and 7).

## See also

- [Phase 2 evaluation](tpc_phase2_eval.md) — the pinned gate, ledger comparability, dataset boundaries.
- [Phase 2 roadmap](tpc_phase2_roadmap.md) — the ungated flags and their Next-steps gate items.
- [Baseline ledger guide](phase2_baselines/README.md) — the slow, promotable rows this screen feeds.
