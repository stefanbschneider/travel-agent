# R31 — the first real free-prose FPR gate

**Date** 2026-08-08 · **Branch** `eval/r31-oracle-literal-translation` · **`git_sha`** `d72268a3`
(current `main` tip at branch cut — includes P22 salvage-before-drop static half, P23 oracle-literal
translation, P24, R25–R30) · **host** 4-core Linux (3-way sharded) · **Contract**: full `hf_medium`
free-prose split (n=150), per-query mode (`agent_env/scripts/solve_phase2.py`, no
`--total-budget-sec`), `budget-sec=90`, `--lang en`, no `--resume`, single method directory (see
"single solve" below). Screen, not a `full_runs/`/`runs/` row.
Evaluation workstream instrument:
[R31](../../../../docs/tpc_phase2_eval.md#r31--the-first-real-free-prose-fpr-gate), the item
[P23](../../../../docs/tpc_phase2_roadmap.md#p23--make-the-free-prose-register-scoreable) unblocked.

## Headline: GREEN. FPR 20.67 → 44.67, C-LPR 82.44 → 88.29, zero clauses regress

Measured against the doc's own bar: **the translated arm's C-LPR and FPR are both higher**, **74
clauses flip fail→pass and zero flip pass→fail** (checked per-clause, per-uid, not just aggregate —
see "clause-level method" below), and no clause count changed between arms. This is R31's GREEN, not
its RED.

| metric | control (untranslated, today's contract) | translated (P23 map applied) | Δ |
| --- | --- | --- | --- |
| FPR | 20.6667 (31/150) | 44.6667 (67/150) | **+24.00** |
| C-LPR | 82.4367 | 88.2911 | **+5.85** |
| MicEPR / MacEPR | 100.0 / 100.0 | 100.0 / 100.0 | flat (unaffected, as expected — grounding, not logic) |
| overall | 51.0570 | 64.5689 | **+13.51** |
| clause micro (raw, unconditional) | 82.44 (1042/1264) | 88.29 (1116/1264) | +5.85 |
| clause macro (query all-clauses-pass) | 20.67 (31/150) | 44.67 (67/150) | +24.00 |

Full `eval_tpc.py` logs: [`eval/hf_medium_r31_control.log`](eval/hf_medium_r31_control.log),
[`eval/hf_medium_translated.log`](eval/hf_medium_translated.log).

## The cap, re-priced first (per the doc, costs seconds, no solve)

Reproduced byte-identical to the existing [P23 screen](../20260808_p23_oracle_literal_translation/README.md):
`hf_medium` n=150, 1264 oracle clauses, 126 structurally unsatisfiable under `--lang en`, 125 of those
mappable, 92 queries blocked, **FPR ceiling 38.67**, C-LPR ceiling 90.03. `report.json`/`summary.md`
in this directory are that reproduction. **Read this number carefully against the result above: the
control arm's FPR (20.67) is measured under that 38.67 ceiling (53.4 % of the achievable range,
consistent with prior free-prose measurements), but the translated arm's FPR (44.67) is *not* — once
the literals are translated, the structural cap is gone and the ceiling is no longer 38.67. There is
no contradiction in the translated arm exceeding the old ceiling.**

## Single-solve design (not two solves)

Confirmed directly before spending any solve time: `materialize_hf_split.py --translate-oracle-literals`
only rewrites `hard_logic_py`; `nature_language` (and every other agent-visible field) is byte-identical
between `hf_medium_r31` (control) and `hf_medium_en_oracle` (translated) for all 150 uids (diffed
directly, not assumed). The Phase 2 agent path never reads `hard_logic_py` (phase boundary), so the
plan the solver produces cannot depend on which split name it was invoked under. **One solve, scored
twice** — the same `results/phase2_e2e_r31_hf_medium/` plans are scored once against each split's
oracle. This is what the doc's own phrasing ("score the same free-prose subset twice") already
implies; it is not a deviation from the contract, and it halves the wall-clock cost the doc priced at
`~1 h` (measured: `814.7 s` on the slowest of 3 shards, `~15 min` total elapsed, well under the
estimate — the `90 s`/query budget-sec ceiling was rarely needed).

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split medium --name hf_medium_r31
HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py \
  --hf-split medium --name hf_medium_en_oracle --translate-oracle-literals \
  --report-out .../translation_report_medium.json

# 150 uids, 3-way sharded, one solve:
HF_HUB_OFFLINE=1 .venv/bin/python agent_env/scripts/solve_phase2.py \
  --split hf_medium_r31 --uids-file <shard> --method phase2_e2e_r31_hf_medium \
  --budget-sec 90 --lang en   # x3, parallel, one process per shard

# scored twice against the same plans, once per split's oracle:
.venv/bin/python eval_tpc.py --splits hf_medium_r31        --method phase2_e2e_r31_hf_medium --lang en
.venv/bin/python eval_tpc.py --splits hf_medium_en_oracle  --method phase2_e2e_r31_hf_medium --lang en
```

`TPC_P2_ENTITY_RESOLUTION` was left unset on the solve (harness force-default `True` per
[R29](../../../../docs/tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end)
applies identically regardless of which split is later used to score — the oracle split is not read
during solve at all). Telemetry confirms zero LLM calls across all 3 shards
(`llm_parse_attempts: 0`).

## Clause-level method (the part aggregate C-LPR/FPR cannot show)

Two arms can land on the same aggregate C-LPR while satisfying a different set of clauses, and the
doc's RED condition ("a clause flipping pass → fail means the translation changed a literal's
meaning") is only checkable per clause, per uid. [`clause_diff_tool.py`](clause_diff_tool.py) (kept
here for reproducibility) reuses the real checker
(`chinatravel.evaluation.hard_constraint.evaluate_hard_constraints_v2`, the exact function
`eval_tpc.py` calls for C-LPR/FPR) to emit one 0/1 result per `hard_logic_py` clause per uid, for both
arms, then diffs them index-wise (translation only rewrites literals inside a clause — it does not
add, remove, or reorder clauses, and `clause_count_mismatch` in the diff below confirms this held for
all 150 uids).

```bash
.venv/bin/python clause_diff_tool.py score --splits hf_medium_r31       --method phase2_e2e_r31_hf_medium --lang en --out control.json
.venv/bin/python clause_diff_tool.py score --splits hf_medium_en_oracle --method phase2_e2e_r31_hf_medium --lang en --out translated.json
.venv/bin/python clause_diff_tool.py diff control.json translated.json
```

Full per-uid clause tables: [`clause_table_control.json`](clause_table_control.json),
[`clause_table_translated.json`](clause_table_translated.json). Full diff:
[`clause_diff.txt`](clause_diff.txt).

**Result: `clause_count_mismatch: 0`, `74` fail→pass, `0` pass→fail.** Every flip is a
literal that was previously a bare CJK string (`'火锅'`, `'川菜'`, `'历史古迹'`, `'商业街区'`,
`'博物馆/纪念馆'`, …) now reading the English catalog value (`'Hot pot'`, `'Sichuan cuisine'`,
`'historical site'`, `'commercial district'`, `'Museum/Memorial Hall'`) the plan's own facts are drawn
from — sampled fully in `clause_diff.txt`, none is a value substitution that changes what the clause
means, only the language it is expressed in. `74` of the `125` mappable clauses flip; the other `51`
stayed failing because the solved plan genuinely does not satisfy that requirement (translation lifts
the structural cap, it does not manufacture a matching plan) — this is the expected, correct shape,
not a shortfall.

## Cleanup (confirmed, per the doc's "never ship" rule)

Both materialized splits (`chinatravel/data/en/hf_medium_r31/`, `chinatravel/data/en/hf_medium_en_oracle/`,
and their `default_splits/*.txt`/`*_suboptimal.txt`) were deleted after scoring —
`git status --porcelain` shows neither. `results/phase2_e2e_r31_hf_medium/` is `.gitignore`d
(`results/*` with an explicit allowlist) and was not committed.

## What this changes and does not change

**Read every prior free-prose FPR/C-LPR number in this document against the ceiling next to it, not
against 100** — that correction stands as already written. **This row does not retroactively rewrite
any of them.** It also does not promote any solver default — R31 recalibrates the measurement (proves
the translation is safe and that the cap was real), it does not change solver behavior at all. The
next open question this unlocks: re-run other pinned free-prose e2e screens (R26 addendum, R29, R30)
under the translated oracle to see whether their solver-side conclusions (P20, entity resolution,
drop-unsatisfiable-names) look different once the structural cap is lifted — not scheduled with a
number yet, candidate for a future evaluation-machine slot.
