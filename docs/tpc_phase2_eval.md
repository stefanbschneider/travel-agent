# TPC 2026 Phase 2 Evaluation and Dataset Boundaries

This document defines how to measure a no-oracle harness without confusing local diagnostics for organizer results, and which data source each measurement is drawn from.
Generated rows live in [`results/phase2_baselines/`](../results/phase2_baselines/); this document defines their interpretation.

## Three axes

| Axis | Input and purpose | Meaning |
| --- | --- | --- |
| Ceiling | `results/best` with released oracle logic and offline iteration | Aspirational upper bound, not a harness baseline. |
| Solver-only | Oracle constraints, bounded autonomous solve | Solver headroom after parsing is removed. |
| End-to-end | Visible text, no oracle, bounded harness | The local approximation to the submitted path. |

The gap from ceiling to solver-only is bounded-solver headroom.
The gap from solver-only to end-to-end is parsing and harness loss.
Use `scripts/parser_vs_oracle.py` to diagnose constraint-family differences and behavioral agreement, but promote a parsing change only after an end-to-end measurement.

## Score semantics

`eval_tpc.py` publishes one aggregate score:

$$
0.10\,\mathrm{EPR\!\text{-}micro} + 0.10\,\mathrm{EPR\!\text{-}macro} + 0.25\,\mathrm{C\!\text{-}LPR} + 0.40\,\mathrm{FPR} + 0.05\,(\mathrm{DAV}+\mathrm{ATT}+\mathrm{DDR}).
$$

Its per-query score for monotonic merging is different: it assigns both 10% environmental slots from that query's binary commonsense result.
That implementation choice helps rank merge candidates; it is not a second official aggregate.

## Dataset boundaries

Phase 2 measurements must name their data source.
These four sources have different trust and generalization properties; none substitutes for the organizer's final held-out set.
Do not compare rows across sources as if they had the same distribution or oracle exposure.

### 1. Official familiar-100 development set (preferred signal)

The organizers released the [familiar-100 archive](https://chinatravel-competition.github.io/IJCAI2026/TPC_IJCAI_2026_phase2_familiar_100_data.zip) on 2026-07-15 with the Agent Environment Guide.
The 100 source records are imported unchanged under `chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/` and selected by `tpc_phase2_familiar_100`.
`_provenance.json` pins the source URL, release/retrieval dates, archive SHA-256, and every extracted member's size, CRC32, and SHA-256.
The records contain `hard_logic_py`; loaders retain it only for scoring and attribution, while the adapter and both harnesses expose only `uid`, trip metadata, and `nature_language` to the agent path.
Familiar-100 is drawn from the same distribution as final evaluation, so it is the preferred new-development signal — but a familiar-100 result must identify this imported artifact and run configuration and must not be presented as a final-evaluation estimate.

**Val / held-out-test partition (since 2026-07-23).** To avoid overfitting familiar-100 itself, `scripts/make_familiar_splits.py` splits the 100 records once, deterministically (seed `20260723`), into `tpc_phase2_familiar_100_val` (80) and `tpc_phase2_familiar_100_test` (20) — regenerate/inspect with `make phase2-familiar-splits` (frozen unless `--force`). The split is **stratified by trip length (`days`)** — the strongest available difficulty signal (`days` spans 1–5 with real spread and drives solve difficulty/timeout rate, whereas the `hard_logic_py` clause count is a narrow 9–13) — so val and test carry the same day-count mix (each stratum contributes ~20% to test) and a val gain is more likely to carry to test. **Every screen and development gate runs on the val split; the test split is an occasional overfitting tripwire, never a per-change signal** — you compare val↔test only rarely (e.g. before a submission) to check the two haven't diverged. Two caveats stand regardless: 20 records is a *coarse, high-variance* tripwire (stratification narrows the val↔test gap but cannot manufacture precision from 20 records), and neither familiar split is the organizer final held-out set — that remains the only true generalization measure. The full `tpc_phase2_familiar_100` split file stays in place for backward comparison with the already-committed 100-record baseline rows; new development rows use val.

### 2. Repository-local released data

The repository contains the released Phase 1 English queries and their oracle fields under `chinatravel/data/en/TPC_IJCAI_2026_phase1_EN/`.
`make phase2-splits` deterministically partitions that released source into `tpc_phase2_val` and `tpc_phase2_test` for local development.
Despite the local `test` name, these are not organizer-held-out Phase 2 data.
They average `~16` `hard_logic_py` constraints per record versus `~38` in familiar-100, so a val result under-represents the constraint density of the final distribution.
They remain useful only when the agent path hides `hard_logic_py` and other oracle-only fields.

### 3. Hugging Face ChinaTravel

[`LAMDA-NeSy/ChinaTravel`](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel) is public benchmark data with multiple configurations and splits.
It is useful only as an out-of-distribution phrasing-generalization probe for an auxiliary parser or solver, never as a tuning target.
The set is natively Chinese; `load_hf_queries` uses its English translation field (`nature_language_en`), so the "OOD" gap versus familiar-100 is a phrasing-register difference within English (free prose vs. rigid templates), not a cross-language difference.
Keep the HF configuration and split names with every result; do not merge different configurations into one comparison.
The repository comparison utility is:

```bash
.venv/bin/python scripts/compare_hf_dataset.py --hf-config default
```

### 4. Organizer final held-out set

The final Phase 2 set is separate, unavailable locally, and evaluated only through the organizer-run no-oracle harness on Qwen3.6-27B via SGLang.
No local split, HF subset, or familiar-100 result proves performance on it.
Use those sources to diagnose and rank work, then preserve no-oracle boundaries and regression gates so the submitted harness remains robust to unseen requests.

## Baselines and repetitions

Use a deterministic fold, fresh outputs, and a pinned source revision for a promotable baseline.
Long runs should use `make phase2-baseline-at SHA=<ref> ...` so the recorded revision is the code that executed.
Record a local repeat count whenever variance matters.

**Primary gate budget: `900 s` (since 2026-07-24).** The public competition material still does not
specify a repeat count or per-query timeout, so every budget remains a local assumption — but the
working expectation is now that the official per-query timeout is closer to `900 s` than to the `300 s`
we originally used to keep e2e eval fast. Development gates therefore run at **`900 s`** so a change is
judged in the budget regime it will actually run in; several landed solver features (`TPC_PIN_TIMED_WINDOWS`,
`TPC_REPAIR_TRANSPORT_GAPS`) trade wall-clock for FPR and were blocked only by the `300 s` no-new-timeouts
guard, which a `900 s` gate is expected to relax. `300 s` is retained as a **faster sensitivity setting**
(and the quick A/B screen still runs at a reduced `60 s`); the `make phase2-budget-sweep`
(`30,60,120,300,900`) attribution stays the tool for checking a promotion is not `900 s`-fragile — a
change that only helps at the full `900 s` and collapses at, say, `600 s` is a warning, since the true
timeout is unconfirmed. Do not overfit any single budget number the organizer has not published.

Familiar-100 ledger rows must carry the manifest-derived data-source ID and remain separate from the repository-local `tpc_phase2_val`/`tpc_phase2_test` partitions and the organizer final held-out set.

## Ledger comparability

Compare rows only when they match on:

- source revision, data source, split, deterministic fold/limit, and language;
- local budget, repeat count, parallelism, and fresh-output policy;
- parser, solver, and feature flags; and
- LLM backend/model and cache policy when an LLM is enabled.

A row must expose enough telemetry to explain its score: valid-output rate, parse failures, timeout and recovery counts, fallback use, stage timings, LLM attempts/failures, and the three attribution axes.
Low-`n` rows are smoke checks, not promotion evidence.

## Quick A/B screen (pre-gate triage)

The pinned end-to-end gate below is authoritative but slow (hours). Gating **every** landed change
behind its own isolated long e2e does not scale: at `O(changes × 8h)` it falls behind the rate of
new work, and most of that compute is wasted re-establishing the same baseline. The quick A/B
**screen** is the pre-filter that keeps the slow gate for changes that already show a signal. It
decides *within 1–2h on a short-lived box* whether an off-by-default flag is even worth an e2e run.
It **ranks and triages; it never promotes** — only a committed ledger row through the [gate](#gates)
promotes a default. Tool: [`scripts/phase2_quick_eval.py`](../scripts/phase2_quick_eval.py)
(`make phase2-quick-eval P2_FLAG=<env var>`).

### How the screen beats the wall-clock

The pinned baseline runs `100` familiar-100 queries at a `300 s` budget, twice; the solver's
restart loop spends the whole budget (solve `p50 ≈ 270 s`), so wall-clock is roughly
`queries × budget × repeats / parallelism` — hours. The screen cuts that on three axes at once and
trusts only the **paired delta**, never the absolute numbers:

1. **Subset** — a deterministic slice (`--n`, default `40`) instead of all `100`.
2. **Reduced budget** — `--budget-sec` (default `60`) instead of `300`. The deterministic solver
   flags act at the **acceptance boundary** inside `_pack_plan` (before the acceptance gate), so
   their FPR effect shows even when the restart loop is cut short. Measured: solver-only FPR is
   `20%` at `n=30`/`60 s` vs `25.5%` at `100`/`300 s` — the reduced budget keeps most of the signal.
3. **Paired same-everything A/B** — baseline (off) and candidate (on) share subset, budget, and
   seed; only the one flag changes, so the *difference* isolates it even though the reduced-budget
   absolute FPR is not comparable to a ledger row. It is a controlled experiment, not a baseline.

### What it measures

Default mode is `solver-only` (oracle constraints, **no LLM**, fully deterministic) because that is
what the highest-leverage flags target. Per arm, from the run's per-query results and telemetry:

| Signal | Meaning | Better |
| --- | --- | --- |
| `FPR` | % of queries whose final plan passes every check (target of the acceptance-flipping flags) | higher |
| `overall_true` | mean per-query preference-weighted score (`continuous_score`) | higher |
| `timeouts` | queries that hit the budget wall (recovered via the timeout snapshot unless `used_fallback` moves) | lower |
| `solve p50` | median solve wall-time | lower |
| `used_fallback` | queries that fell back to the schema-shaped empty plan (a real correctness loss) | lower |
| `parse_failures` | invalid-JSON / eval / solver errors | lower |

It then runs the monotonic [`phase2_gate.check_gate`](../scripts/phase2_gate.py) on the gate-shaped
keys and prints a reconciled verdict (see [reading the verdict](#reading-the-verdict)).

### How to run

```bash
# Screen the timed-window pinning flag, solver-only, 40 queries at a 60s budget, 3 in parallel:
make phase2-quick-eval P2_FLAG=TPC_PIN_TIMED_WINDOWS P2_N=40 P2_BUDGET=60 P2_PARALLEL=3
# equivalently:
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_PIN_TIMED_WINDOWS --n 40 --budget-sec 60 --parallel 3

# Early-convergence stop at patience 15 (target: fewer timeouts at held FPR):
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_SOLVE_CONVERGE_PATIENCE --on 15 --n 40 --budget-sec 60 --parallel 3

# Stack flags: screen repair on top of an already-on pin (this is also how the nightly batch is screened):
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_REPAIR_TRANSPORT_GAPS --extra-env TPC_PIN_TIMED_WINDOWS=1 --n 40 --budget-sec 60 --parallel 3
```

**Reuse one baseline across flags.** The `flag=off` arm is identical (all-flags-off, same
subset/budget/seed) for every deterministic flag, so run it once and reuse it with `--baseline-json`
(`results/<out>/baseline.json`) — halving the cost of each additional flag. You own the
subset/budget/seed match; the tool trusts the reused baseline.

Cost per arm ≈ `ceil(n / parallel) × (budget_sec + ~3 s)`. On a 4-core box (`--parallel 3`),
`n=40`/`60 s` is ~14 min/arm; screening three flags against one shared baseline is ~55 min. Keep
`--parallel` at `cores − 1` (each CP-SAT solve is single-threaded).

### Reading the verdict

- **GREEN LIGHT** — target improves *and* the like-for-like gate passes. Queue for e2e.
- **GREEN LIGHT (with caveat)** — target improves, but the *only* gate block is more timeouts at the
  tight screen budget (all recovered). Expected when a flag does more work per solve: fewer restarts
  fit, so more queries hit the wall — a wall-clock cost, not a correctness loss. The full-budget e2e
  must confirm the cost is acceptable; the acceptance/preference gain is real. Still queue for e2e.
- **MIXED** — target improves but the gate blocks on a non-timeout metric. Read the blocks first.
- **RED** — a correctness signal regresses (FPR, `overall_true`, or `parse_failures`). Do not queue;
  bounce it back to the author.
- **NEUTRAL** — no measurable delta. Enlarge `--n`/`--budget-sec` or pick a subset that exercises
  the flag.

A timeout-only gate block is *informative, not disqualifying* on a screen — it is exactly the
tight-budget timeout-boundary nondeterminism the [gate](#gates) warns about, which is why the tool
prints both the raw gate result and the reconciled verdict.

### Recommended cadence: daily screen, nightly batched e2e

The screen and the continuous e2e are complementary, not either/or. Do **not** gate every change
behind its own isolated e2e (it cannot keep up), and do **not** promote off a screen alone (it does
not estimate final performance). Everything below runs on the **`tpc_phase2_familiar_100_val`**
split; the `tpc_phase2_familiar_100_test` split stays out of this loop entirely. Instead:

1. **On each landing — fast screen** (`familiar_100_val`). RED bounces back to the author and never
   enters the batch. GREEN / GREEN-caveat: the flag **stays off on `main`** but joins tonight's queue.
2. **Nightly — one *batched* e2e** (`familiar_100_val`). Run a single pinned e2e with **all** queued
   green flags stacked ON, against the **current promoted baseline** (the flags already
   defaulted-on, same val split). This is the real gate, and it is `1` run/night regardless of how
   many changes landed — that is what makes the cadence keep up. Before spending the night, a stacked
   *screen* (all-queued-on vs all-off, the `--extra-env` form above) is a cheap interaction check.
3. **Morning — promote or bisect.** If the batch improves `continuous_score` with no new parse
   failures or timeouts vs the baseline, promote the **whole batch**: flip the defaults on, commit
   the ledger row, and it becomes the new baseline. If the batch regresses, promote nothing and run
   drop-one-out *screens* (fast) to find the offending change or interaction, drop it, and re-batch
   the rest the next night.
4. **Keep the continuous e2e running** (`familiar_100_val`). It maintains the promoted-baseline
   ledger row that the nightly batch compares against and catches drift a screen cannot see.
5. **Periodically — the test tripwire** (`familiar_100_test`, e.g. before a submission). Run the
   current promoted config on the held-out 20 and compare the val↔test gap. A val-only gain that
   does not carry to test is overfitting the val split; treat it as a warning, not a per-change gate.

Why batch rather than gate each change in isolation: two changes that each screen green can still
interact when stacked (e.g. `TPC_PIN_TIMED_WINDOWS` and `TPC_REPAIR_TRANSPORT_GAPS` both retime /
re-leg the same plan, so order and overlap matter). The batched e2e measures the *net* effect that
actually ships; the per-change screen only pre-qualifies candidates for it. Promotion stays honest —
still only a gated e2e ledger row — but the gate runs **once per night against a moving baseline**,
not once per change. This preserves "flags off is the floor" and "promote only through the gate"
while absorbing the daily churn.

### Setup on a fresh box (no GPU needed)

The screen never loads a local model, so the heavy GPU requirements (`torch`, `vllm`, `flashinfer`,
`transformers`, …) are not needed — they are lazily imported only by the local-model LLM backends. A
minimal CPU-only environment is enough:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install \
  geopy==2.4.1 numpy==1.26.4 pandas==2.2.3 jsonschema==4.23.0 tqdm==4.66.6 \
  openai==1.53.0 json_repair==0.30.0 scikit-learn==1.5.2 psutil==7.2.2 \
  packaging==24.2 fuzzywuzzy==0.18.0 func_timeout==4.3.5 httpx==0.27.2 \
  z3-solver==4.14.1.0 ortools==9.9.3963 tiktoken==0.9.0 python-Levenshtein==0.25.1
```

The environment database (`chinatravel/environment/database_en/`) and the imported
`tpc_phase2_familiar_100` split must be present (both committed).

### LLM-backed flags (`TPC_P2_LLM_PARSE`, `TPC_P2_LLM_REFINE`)

The same tool screens the LLM flags with `--mode end-to-end` and a configured Phase 2 backend. The
one extra requirement is a reachable OpenAI-compatible endpoint and an API key — and the key is
loaded **for you**: `build_llm_client` calls `load_local_env()`, which reads the repo-root `.env`
into the process environment when the backend is `openai`/`deepinfra`. So you only export the
backend selector; you never read, source, or print `.env`:

```bash
# DeepInfra Qwen (the organizer model family); DEEPINFRA_API_KEY is picked up from .env automatically.
# TPC_P2_LLM_TIMEOUT_SEC must be BELOW the reduced parse/improve slices -- see the note below.
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_LLM_PARSE --mode end-to-end \
    --off 0 --on 1 --extra-env "TPC_P2_LLM_BACKEND=deepinfra,TPC_P2_LLM_TIMEOUT_SEC=6" \
    --n 30 --budget-sec 90 --parallel 3 --out results/phase2_quick_eval/llm_parse

# Screen refine reusing the same all-LLM-off baseline; pin llm_parse=0 in both arms so only refine moves.
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_P2_LLM_REFINE --mode end-to-end \
    --off 0 --on 1 --extra-env "TPC_P2_LLM_BACKEND=deepinfra,TPC_P2_LLM_PARSE=0,TPC_P2_LLM_TIMEOUT_SEC=6" \
    --n 30 --budget-sec 90 --parallel 3 --baseline-json results/phase2_quick_eval/llm_parse/baseline.json
```

- **Lower the LLM timeout below the reduced slice, or the flag silently no-ops.** Both stages skip
  the LLM when the slice they run in is smaller than the client timeout (`parse_to_ir` and Stage 3
  both guard `slice < client_timeout` to avoid a mid-flight overrun). The default timeout is `30 s`;
  at a `90 s` screen budget the parse slice is `~22 s` and the improve slice is `~9 s`, so with the
  default you would measure a no-op. Set `TPC_P2_LLM_TIMEOUT_SEC` under the smaller slice (`6 s`
  works at `90 s`; the improve slice is the binding one for refine). This is safe and faithful:
  DeepInfra Qwen answers in `~1.2 s` with thinking off, and at the full `300 s` budget the default
  `30 s` fits the larger slices — so a low-timeout reduced-budget screen exercises exactly the path
  the full-budget run takes. Verify the arm actually called out: the `flag=on` arm's per-query
  telemetry must show `llm_parse` fired (no `llm_parse_skipped_deadline`) or `improve_llm_called:
  true` — a green screen where the LLM never fired is meaningless.
- With the backend at `none` (library default) the end-to-end path makes **zero** LLM calls, so the
  deterministic flags can also be screened `--mode end-to-end` on a box with no key.
- `TPC_P2_LLM_PARSE` is auto-enabled whenever a backend is configured, so screen each LLM flag with
  explicit `--off 0 --on 1` and pin the *other* LLM flag across both arms (the env override wins
  over the auto-enable); otherwise the refine baseline silently also runs the parse audit.
- Expect higher per-arm wall-clock from network latency; the response cache (on by default, keyed by
  prompt hash at temperature 0) makes reruns and the shared baseline cheap.

### Worked example: the ungated solver flags on `main` (2026-07-22)

Solver-only, `tpc_phase2_familiar_100`, deterministic subset `n=30`, `60 s`, `--parallel 3`, seed
`20260705`, one shared all-flags-off baseline (FPR `20.0`, `overall_true 43.88`, `7` timeouts).
Screen only — reduced-budget deltas, not a promotion.

| Flag | FPR | overall_true | timeouts | Screen verdict |
| --- | --- | --- | --- | --- |
| `TPC_PIN_TIMED_WINDOWS=1` | `20.0 → 26.67` (**+6.67**) | `43.88 → 49.88` (**+6.00**) | `7 → 9` | GREEN (caveat: +2 recovered timeouts) |
| `TPC_REPAIR_TRANSPORT_GAPS=1` | `20.0 → 23.33` (**+3.33**) | `43.88 → 46.60` (**+2.72**) | `7 → 8` | GREEN (caveat: +1 recovered timeout) |
| `TPC_SOLVE_CONVERGE_PATIENCE=15` | `20.0 → 20.0` (+0.0) | `43.88 → 46.16` (+2.28) | `7 → 6` (**−1**) | GREEN (weak: −1 timeout at the noise floor) |

Both acceptance-flippers clearly move solver-only FPR (the binding ceiling) and the preference score
at the cost of a few *recovered* timeouts from extra per-candidate work; neither loses a plan to the
fallback or adds a parse failure. The convergence stop holds FPR and shaves a timeout, but its `−1`
delta is inside the run-to-run noise floor — a *weak* positive whose real payoff (wall-clock) only
shows at the full `300 s` budget where the restart loop plateaus. All three are safe to carry into
one **batched** e2e (roadmap Next steps 1, 4, 5); the screen ranks them but flips no default.

### Worked example: the LLM flags on `main` (2026-07-22)

End-to-end, `tpc_phase2_familiar_100`, `n=30`, `90 s`, `--parallel 3`, DeepInfra `Qwen/Qwen3.6-27B`,
shared all-LLM-off baseline (`overall_true 47.38`, `11` timeouts). Both came back **do-not-default**,
and each carries the lesson that made the screen honest:

| Flag | FPR | overall_true | timeouts | LLM activity (cand) | Verdict |
| --- | --- | --- | --- | --- | --- |
| `TPC_P2_LLM_PARSE=1` (timeout `15`) | `20.0 → 20.0` | `47.38 → 44.18` (**−3.20**) | `11 → 11` | audit fired `30/30` | **RED** |
| `TPC_P2_LLM_REFINE=1` (timeout `8`) | `20.0 → 20.0` | `47.38 → 47.35` (−0.02) | `11 → 19` | refine called `18`, committed `0` | **NO BENEFIT** |

- **`TPC_P2_LLM_PARSE` regresses preference** by `3.2` once the audit actually fires on every query —
  an end-to-end confirmation of the parser-level "audit is neutral-to-negative" finding, so it stays
  off. **This is the timeout lesson in one row:** a first pass at `timeout=6` looked *positive*
  (`+1.97`) only because `10/30` audits silently timed out and fell back to the deterministic parse;
  raising the timeout so all `30` fired flipped the verdict to RED. Always read the LLM-activity line
  before trusting an LLM screen.
- **`TPC_P2_LLM_REFINE` (Stage 3 v1) flips nothing here** — called on `18` produced-but-invalid
  plans, committed `0` (`8` proposed ungroundable edits, `5` didn't satisfy the checker, `5`
  LLM-errored) — while its reserved improve slice costs `+8` timeouts. Quality is flat within the
  noise band, so it is NO BENEFIT (a thumbs-down on cost), not RED (it cannot regress by
  construction). The committed/called telemetry is the actionable output: v1 needs groundable,
  checker-satisfying edits before it earns an e2e gate (roadmap Next step 7).

### Limits — read before trusting a screen

- **A screen never promotes.** It authorizes an e2e run; only a committed ledger row from a pinned
  SHA through the [gate](#gates) promotes a default. Preserves the
  [non-negotiable invariants](../CLAUDE.md#non-negotiable-invariants).
- **Absolute numbers are not ledger-comparable** (reduced budget/subset). Only the paired delta at a
  fixed budget is meaningful; do not commit screen outputs into `results/phase2_baselines/`.
- **Timeout counts carry run-to-run noise** — a `±1–2` swing at a tight budget is nondeterminism,
  not a regression, so FPR/`continuous_score` are the correctness signals and a timeout-only block is
  a caveat. A sub-point `overall_true` wobble is likewise noise: the verdict treats `|Δ| ≤ --tol`
  (default `0.5`) as flat, so a pass that commits nothing does not read as RED.
- **Verify an LLM flag actually fired** (LLM-activity line / per-query telemetry) before trusting an
  LLM screen — a slice-vs-timeout mismatch silently no-ops it, and a partial fire skews the delta.
- **Familiar-100 is a development signal**, inheriting every [dataset-boundary
  caveat](#dataset-boundaries); a screen never estimates final performance.
- **Use `n ≥ 30`.** Smaller subsets are noise-dominated smoke checks.

## Gates

Run the regression gate on like-for-like ledger rows:

```bash
make phase2-gate BASELINE=results/phase2_baselines/runs/<base>.json \
  CANDIDATE=results/phase2_baselines/runs/<candidate>.json
```

When both inputs supply `continuous_score`, it is the blocking score and FPR is advisory; otherwise FPR blocks.
In every case, more parse failures or timeouts block promotion. The no-new-timeouts guard is evaluated
**relative to the budget both rows ran at** — pair rows at the same budget (now `900 s`; see [Baselines and
repetitions](#baselines-and-repetitions)). A timeout regression measured at `300 s` does not by itself block
a change whose intended budget is `900 s`; re-gate the pair at `900 s` before concluding.

Early-stop evaluation modes are diagnostic only and are not comparable with normal preference-scoring rows.
Two exist, both eval-tooling only and never set by the real harness:

- `--fast-fpr` (`TPC_SOLVE_STOP_AT_ACCEPT`) stops each solve at the first accepted plan and **skips
  `_pack_plan`**, so it is the cheapest FPR signal but **cannot** measure the `_pack_plan` repair passes
  (`_pin_timed_windows`, `_repair_transport_gaps`) — those never run under it. Rows are forced to a
  `fastfpr-` label prefix.
- `--fast-fpr-packed` (`TPC_SOLVE_STOP_AT_ACCEPT_PACKED`) also stops at the first accept but **still runs
  `_pack_plan`**, so the repair passes execute. Use this — not `--fast-fpr` — to fast-measure the FPR of
  those passes in the `900 s` regime without paying for full preference polishing on every query. Its
  continuous score is still uncalibrated; rows are forced to a `fastfprpacked-` label prefix and must never
  be gate-compared against normal (or `fastfpr-`) rows.

Both preserve the binary FPR signal (a pre-pack accept stays accepted; `_pack_plan` only commits changes
that keep the checker accepting and do not regress the preference key), so they let you drive toward higher
FPR at `900 s` while keeping local iteration cheap.

## Command path

Use Make targets rather than duplicating script arguments:

```bash
make phase2-rehearse FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_LIMIT=20
make phase2-parser-report P2_LIMIT=20
make phase2-baseline FOLD=0 P2_FOLDS=10 P2_BUDGET=300 P2_LIMIT=20 P2_REPEATS=2 P2_LABEL=<tag>
make phase2-timing P2_METHOD=<method> P2_BUDGET=300
```

Use `make phase2-help` for the full catalog.
The [baseline ledger guide](phase2_baselines/README.md) covers row fields and generated artifacts.

## Measurement rule

Record the source name, selected split, deterministic selection, budget, flags, and model/backend with every measurement.
Do not infer final-evaluation performance from local rows or from familiar-100.
For ledger semantics, see the [baseline ledger guide](phase2_baselines/README.md); for current priorities, see the [Phase 2 roadmap](tpc_phase2_roadmap.md).
