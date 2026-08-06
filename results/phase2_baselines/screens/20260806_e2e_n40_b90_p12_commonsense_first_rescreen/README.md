# P3 re-screen: `TPC_COMMONSENSE_FIRST` (2026-08-06)

**Roadmap item:** [P3 — emit commonsense-valid plans when nothing is accepted](../../../../docs/tpc_phase2_roadmap.md#p3--emit-commonsense-valid-plans-when-nothing-is-accepted).

P3 asks for a *re-screen*, not a re-implementation: the mechanism (`TPC_COMMONSENSE_FIRST`, the
`best_cs` bucket in `TPCAgent._solve` plus the relaxed repair-commit rule for unaccepted plans) is
already implemented, already unit-tested
(`tests/phase2/test_prefer_commonsense_valid.py`), and has been a harness default
(`apply_deterministic_solver_defaults()`) since before the 2026-07-30 evaluator sync. Its existing
evidence therefore predates that sync, and the roadmap's own C-LPR/MacEPR framing needs a value
measured against the current tree.

## Command

```bash
.venv/bin/python scripts/phase2_quick_eval.py --flag TPC_COMMONSENSE_FIRST \
  --mode end-to-end --split-set familiar_100_val --n 40 --budget-sec 90 --parallel 7 \
  --out results/phase2_baselines/screens/20260806_e2e_n40_b90_p12_commonsense_first_rescreen
```

`familiar_100_val`, `n=40`, `budget_sec=90`, `parallel=7`, seed `20260705` (the tool's default,
shared with every other per-query screen in this ledger). End-to-end mode with the LLM backend at
`none` (library default), so this makes zero LLM calls; every other promoted deterministic solver
flag (`TPC_PIN_TIMED_WINDOWS`, `TPC_SOLVE_CONVERGE_PATIENCE`, `TPC_WINDOW_ANCHOR`,
`TPC_WINDOW_PUSH`, `TPC_WINDOW_INSERT`) is on in both arms via
`apply_deterministic_solver_defaults()` — the screen isolates only `TPC_COMMONSENSE_FIRST`, exactly
as `--flag` is designed to.

## Result

| | off (`0`) | on (`1`) | Δ |
| --- | --- | --- | --- |
| FPR | 47.50 | 50.00 | **+2.50** |
| overall_true (continuous) | 63.264 | 67.794 | **+4.53** |
| commonsense pass (n/40) | 36 | 40 | **+4** |
| EPR-macro (`commonsense_macro`) | 90.00 | 100.00 | **+10.00** |
| EPR-micro (`commonsense_micro`) | 99.63 | 100.00 | +0.37 |
| **C-LPR** (`conditional_logical_micro`) | 82.42 | 92.01 | **+9.59** |
| logical micro (unconditional) | 92.01 | 92.01 | **+0.00 (flat)** |
| all_pass (n/40) | 19 | 20 | +1 |
| timeouts | 0 | 0 | +0.00 |
| solve p50 (sec) | 48.97 | 47.32 | -1.65 (faster) |
| used_fallback / parse_failures | 0 / 0 | 0 / 0 | +0.00 / +0.00 |

Full arm detail: [`summary.json`](summary.json) (also `baseline.json`, `candidate.json`).

**Monotonic gate: PASS. Verdict: GREEN LIGHT** — improves its target signal and passes the
like-for-like gate on this screen.

## Reading against the P3 bar

The roadmap's bar is **"MacEPR and C-LPR up, FPR not down. Ceiling `~+0.5`, one screen, then stop
either way."** This screen clears the bar on all three axes at once:

- **MacEPR (EPR-macro) up**: `90.00 → 100.00` (+10.00) — the reference row's framing ("MacEPR `97`
  means 3 queries" caught in the schema+commonsense-fails-but-logic-nearly-passes state) is exactly
  what moved: 4 of 40 queries that used to fail commonsense now pass it.
- **C-LPR up**: `82.42 → 92.01` (+9.59) — releasing exactly the logical credit those 4 queries had
  already earned but forfeited for failing commonsense.
- **FPR not down**: `47.50 → 50.00`, up, not merely flat.
- **Proof of mechanism, not a search-side effect**: `logical_micro` (the *unconditional* logical
  score) is **exactly unchanged** at `92.00913242009132` on both arms — to 11 decimal places, the
  same plans' logical credit, just no longer conditionally zeroed. The gain is entirely the
  commonsense gate releasing credit the solver had already earned, matching the mechanism's own
  design intent and the pre-sync evidence cited in `apply_deterministic_solver_defaults()`'s
  docstring.
- **No cost elsewhere**: zero timeouts, zero fallbacks, zero parse failures on either arm; solve
  `p50` is actually *faster* on (`47.3s` vs `49.0s`), consistent with `best_cs` finalizing on a
  cheaper accepted candidate rather than continuing to search.

This is a **screen, not a promotion** — and this flag needs no promotion decision here: it has
already been a harness default since before this cycle, and this screen's only job was to confirm
that the promoted default still holds its measured shape on the current tree. It does, so
**no code or default changes are needed for P3** — per the roadmap ("stop either way"), this closes
the item.

## Caveats

- Absolute numbers on this screen (a 40-query, 90-second-budget subset) are not ledger-comparable
  to a full whole-run row; only the paired delta is trusted, per the screen tool's own limits
  section.
- This is a per-query (`end-to-end`) screen, not `--mode whole-run`. `TPC_COMMONSENSE_FIRST` acts
  inside `TPCAgent._solve`/`_pack_plan`, below the scheduler, so the per-query path exercises the
  same code the whole-run scheduler calls per attempt — unlike a scheduler-level change (P5, P10),
  this flag's effect is not structurally hidden from `--mode end-to-end`.
