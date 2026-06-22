# Agent Design: Constraint-First Search + CP-SAT Rescue

## Competition Overview: TPC@IJCAI 2026

Two competition phases:

- **Competition Phase 1 (public leaderboard, deadline 1 Aug 2026):** Submit prediction files for the released 1000-query set (`tpc_phase1`). Any method allowed. Only the latest submission per team is scored. Goal: finish top 5 to advance.
- **Competition Phase 2 (final test, 1–7 Aug 2026):** Top 5 teams submit a self-contained harness. Organizers run it on Qwen3.6-27B (SGLang, 2× A800 80G). Final rankings determine 1st–3rd place.

Data: English queries in `data/TPC_IJCAI_2026_phase1_EN/`, 10 cities (Beijing, Shanghai, Nanjing, Suzhou, Hangzhou, Shenzhen, Chengdu, Wuhan, Guangzhou, Chongqing), 300s timeout per query.

## Scoring Formula

$$\text{Score} = 0.40 \cdot \text{FPR} + 0.25 \cdot \text{C-LPR} + 0.10 \cdot \text{EPR-micro} + 0.10 \cdot \text{EPR-macro} + 0.05 \cdot (\text{DAV} + \text{ATT} + \text{DDR})$$

| Metric | Weight | Description |
|--------|--------|-------------|
| FPR | 40% | Full Passing Rate — plans passing ALL constraints |
| C-LPR | 25% | Conditional Logic constraint pass rate |
| EPR-micro | 10% | Proportion of individual environment constraints passed |
| EPR-macro | 10% | Proportion of plans passing all environment constraints |
| DAV | 5% | Daily Average Visits (attractions/day, normalized to [0,4]) |
| ATT | 5% | Average Transport Time (normalized to [0,1] over 15–120 min) |
| DDR | 5% | Daily Dining Recommendations (restaurants/day, normalized to [0,1] over 0–3) |

Hard constraints (FPR + C-LPR + EPR) account for **85%** of the total score.

## Current Agent (TPCAgent)

`chinatravel/agent/tpc_agent/tpc_agent.py` — `TPCAgent`  
`chinatravel/agent/tpc_agent/solver_constraints.py` — branch-local constraint variants  
`chinatravel/agent/tpc_agent/cp_candidates.py` — candidate pool extraction  
`chinatravel/agent/tpc_agent/cp_solver.py` — CP-SAT tier + reconstruction  
`chinatravel/agent/tpc_agent/parsed_verifier.py` — no-oracle verifier

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│  1. CONSTRAINT EXTRACTION + VARIANTS                    │
│  parse_constraints + branch-local hard-logic extraction │
│  (one normalized constraint dict per OR branch)         │
└───────────────────────┬──────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────┐
│  2. ACCEPTANCE CHECKER                                  │
│  base: oracle hard_logic_py (or parsed verifier)        │
│  gate: schema + commonsense once base is fully passed   │
└───────────────────────┬──────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────┐
│  3. MULTI-TIER PLAN SEARCH                              │
│  base build -> guided repair priors -> random restarts  │
│  optional CP-SAT rescue for hard leftovers              │
└───────────────────────┬──────────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────┐
│  4. CONSTRAINT-SAFE PREFERENCE PACKING                  │
│  pack + densify only when acceptance remains true       │
│  monotonic best-of updates via eval_tpc --update_best   │
└──────────────────────────────────────────────────────────┘
```

### Key Principles

- **Constraint-first optimization.** Optimize the exact acceptance criterion (logic + schema + commonsense), not a proxy.
- **Deterministic data grounding.** POIs, prices, schedules, and transport details are read from `WorldEnv`; no fabricated values.
- **Branch-local correctness.** OR-style constraints are solved per branch to avoid cross-branch contamination.
- **Any preference lift is gated by validity.** Packing/densification is accepted only when full checks still pass.

### Key Environment APIs

| Category | Key APIs |
|----------|----------|
| Attractions | `attractions_select`, `attractions_nearby`, `attractions_id_is_open`, `attractions_types` |
| Restaurants | `restaurants_select`, `restaurants_nearby`, `restaurants_id_is_open`, `restaurants_cuisine` |
| Hotels | `accommodations_select`, `accommodations_nearby` |
| Inner-city transport | `goto(city, start, end, time, transport_type)` → segments with cost/time |
| Intercity transport | `intercity_transport_select(start_city, end_city, type, earliest_time)` |

### Run & Evaluate

```bash
.venv/bin/python run_tpc.py --splits tpc_phase1 --agent TPCAgent --llm TPCLLM --lang en
.venv/bin/python eval_tpc.py --splits tpc_phase1 --method TPCAgent_TPCLLM_en
```

Recommended resumable pipeline:

```bash
make heavy
make light
make score
```

## Current Score (2026-06-19, `results/best`)

Overall **94.54**.

| Metric | Score |
|--------|-------|
| Overall | 94.54 |
| Overall (official) | 94.54 |
| FPR | 97.10 |
| C-LPR | 98.91 |
| EPR-micro | 100.00 |
| EPR-macro | 100.00 |
| DAV | 67.55 |
| ATT | 82.41 |
| DDR | 69.50 |

EPR is saturated and hard-constraint pass rates are now also very high. Remaining improvements are mostly incremental preference and robustness gains.

Key improvements in place: branch-local OR handling, CP-SAT rescue for leftovers, constraint-safe densification, and monotonic best-result merging.

Negative lesson: a cuisine-normalization attempt regressed the full score and was reverted. Keep changes behavior-scoped and validate with full eval before retaining.

## Competition Phase 1 Strategy: Per-Query Optimization

Treat the leaderboard as a per-query optimization problem over the released 1000 queries:

1. Solve or near-solve each query individually.
2. Track the best result per query in `results/best/`.
3. Persist any fully constraint-solved result in `results/constraints_solved/`.
4. Assemble the submission from the best known answer per query.

Any solver or repair logic developed here should stay modular so it can be reused in the Competition Phase 2 harness.

See extra eval args `--index` and `--update_best` to check and update best and solved results.

## Remaining Priorities

1. **Phase-2 no-oracle robustness.** Improve parity between oracle hard-logic pass and parsed-verifier pass on held-out style queries.
2. **Operational reliability.** Keep solve/merge scripts robust for long resumable runs and HPC usage.
3. **Preference uplift under strict validity.** Improve DAV/DDR/ATT without reducing FPR/C-LPR.
4. **Harness packaging.** Keep a reproducible, self-contained harness for organizer evaluation on Qwen3.6-27B via SGLang.
