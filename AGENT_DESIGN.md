# Agent Design: Structured Planner with Constraint Validation

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

`chinatravel/agent/tpc_agent/tpc_agent.py` — `TPCAgent.run()`  
`chinatravel/agent/tpc_agent/tpc_llm.py` — `TPCLLM` (LLM wrapper)

### Architecture

```
┌─────────────────────────────────────────────┐
│  1. QUERY PARSER (LLM, once)                │
│  NL → structured constraints                │
│  required attractions/restaurants/hotels,   │
│  budget cap, transport mode, timing         │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│  2. DATA GATHERER (deterministic)           │
│  Query WorldEnv once, cache everything:     │
│  intercity transport, attractions,          │
│  restaurants, hotels + all prices/hours     │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│  3. ITINERARY BUILDER (deterministic)       │
│  Fixed daily template:                      │
│  Day 1: arrival → activities                │
│  Mid days: breakfast → attr → lunch →       │
│            attr → dinner → hotel            │
│  Last day: activities → departure           │
│  Required POIs inserted first; goto() for   │
│  all transport; budget tracked per bucket   │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│  4. BRANCH SELECTOR (symbolic)              │
│  For OR/group queries: generate one         │
│  candidate per branch, score with           │
│  hard_logic_py, keep best plan              │
└─────────────────────────────────────────────┘
```

### Key Principles

- **LLM only for NL parsing.** All prices, times, transport IDs, and POI names come from `WorldEnv` verbatim. Never let the LLM generate them.
- **goto() for every transport segment.** Exact duration, distance, and cost; never estimated.
- **Fixed time budgets.** ~90 min per attraction, ~60 min per meal.
- **Graceful degradation.** Always output a structurally valid plan; EPR points are worth 20% even when hard logic fails.

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

## Current Score (2026-06-13)

Overall **79.28** — leaderboard position ~9, top 5 threshold estimated ~89+.

| Metric | Score |
|--------|-------|
| Overall | 79.28 |
| FPR | 69.60 |
| C-LPR | 89.18 |
| EPR-micro | 99.96 |
| EPR-macro | 99.20 |
| DAV | 29.17 |
| ATT | 86.99 |
| DDR | 66.93 |

EPR is effectively saturated. The remaining gap to the top 5 is almost entirely in FPR and C-LPR — hard-logic failures.

Key improvements already in place: budget-aware cost tracking, required-entity enforcement, timing/proximity guards, disjunctive branch selection for OR-style queries.

Negative lesson: a cuisine-normalization attempt regressed the full score and was reverted. Keep changes behavior-scoped and validate with full eval before retaining.

## Competition Phase 1 Strategy: Per-Query Optimization

The gap to the top 5 is too large for incremental agent tuning alone. For Competition Phase 1, treat the leaderboard as a per-query optimization problem over the released 1000 queries:

1. Solve or near-solve each query individually.
2. Track the best result per query in `results/best/`.
3. Persist any fully constraint-solved result in `results/constraints_solved/`.
4. Assemble the submission from the best known answer per query.

Any solver or repair logic developed here should stay modular so it can be reused in the Competition Phase 2 harness.

## Remaining Weak Areas

Based on current diagnostics:

- `timing_constraints` — depart/arrive window violations
- `hotel_nearby` — hotel not close enough to requested area
- `required_attraction_types` — missing semantic attraction categories
- Budget edge cases — overflow or under-spend near the limit
- Conditional transport — "take taxi if distance > X km" not yet enforced

## Next Steps (ordered by expected impact)

### 1. Conditional inner-city transport enforcement

Satisfy queries like "take taxi only if distance exceeds X km". In `_get_transport`, check route distance against `conditional_transport.threshold_km` and apply the mode conditionally. Preserve fallback when the mode is infeasible.

### 2. Lightweight repair loop

After the initial build, score with `evaluate_constraints_py`. If failing, run up to 2 targeted repair passes: budget overflow, missing required POI/type, final-day timing miss, hotel-nearby miss. Guard total wall time to stay inside 300s.

### 3. Required-type completion

Reserve slots for unmet required attraction types before optional attractions. Track satisfaction state during build; do not finalize the plan until all required types are either satisfied or infeasible.

### 4. Targeted timing repair

Detect which activity violates a `depart_no_earlier` / `arrive_no_later` clause. Shift, swap, or drop only that activity, then re-check final-day departure feasibility.

### 5. Competition Phase 2 harness packaging

Package the constraint parser, planner, scorer, and repair operators into a reproducible self-contained harness that runs on Qwen3.6-27B via SGLang (no hardcoded answers, no memorized solutions).
