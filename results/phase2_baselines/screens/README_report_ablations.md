# Report ablations: LLM-only planner, and the upstream baseline agents

One script runs both arms: `scripts/phase2_report_ablations.py`. Screens only, never promotion rows.
The 24-uid subset is committed as `tpc_phase2_familiar_100_val_n24` (any `--dry-run` regenerates it),
so every arm scores the same queries.

```bash
# 0. offline plumbing check (no network, no key, ~5 s) -- not a reportable arm
.venv/bin/python scripts/phase2_report_ablations.py --arm llm-only --n 2 --llm-backend stub
# 1. LLM-only arm: a model plans autonomously with the env tools, no solver
TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
    --arm llm-only --agent Act --n 24 --max-steps 30 --workers 4
# 2. upstream baseline arm: the neuro-symbolic agent shipped in chinatravel/agent/
TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
    --arm upstream --agent RuleNeSy --n 24 --workers 4
# 3. our own solver over the same 24 queries, for the comparison column
.venv/bin/python agent_env/scripts/solve_script_with_harness.py \
    --method tpc_val_n24 --split tpc_phase2_familiar_100_val_n24
# 4. score each arm (use the method each run printed)
.venv/bin/python eval_tpc.py --splits tpc_phase2_familiar_100_val_n24 --method <method> --lang en
```

**Measured cost** (live, 1 query, `Qwen/Qwen3.6-27B` on DeepInfra, thinking off, 2026-08-06): Act at
`--max-steps 30` = **29 calls, 238k tokens, $0.085, 54 s/query** (the scratchpad is resent whole each
step, so tokens grow quadratically). Arm 1 ≈ **$2, ~6 min** at `--workers 4`. RuleNeSy is DFS-bound:
few calls, under $1, minutes per query. `ReAct` resends a 20k one-shot example every call (~10x arm 1).

**How to read it.** Open `summary.json` in `results/phase2_baselines/screens/report_ablations/<method>/`
*before* the score. `reportable: false` / `UNMEASURED` means the arm has **no result** — usually
`llm_calls_total == 0` (bad model id, missing key, warm translation cache); fix and rerun, never
report it as a null result. `MEASURED but DEGRADED` means >20% of calls failed, so the score is a lower
bound. `llm_calls_per_query` / `tokens_per_query` / `est_cost_usd_per_query` are the cost row.
`plans_nonempty < queries` means the LLM-only arm ran out of steps on some queries (upstream records
`{"error": "Exceed maximum steps"}`, scores 0) — a real finding, not a bug.

**Comparability.** 24 of 80 queries, one repeat, per-query budget: these arms compare only to each
other and to a solver run over the same 24 uids — not to any `full_runs/` or `runs/` row. `LLM-modulo`
is excluded: it refuses to run without oracle translation.
