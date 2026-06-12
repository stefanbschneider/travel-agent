# Agent Design: Structured Planner with Constraint Validation

## Competition: TPC@IJCAI 2026 (Travel Planning Challenge)

- Generate multi-day trip itineraries from natural language queries
- 1000 queries in `tpc_phase1` split (English data in `data/TPC_IJCAI_2026_phase1_EN/`)
- Timeout: 300s per query
- 10 cities: Beijing, Shanghai, Nanjing, Suzhou, Hangzhou, Shenzhen, Chengdu, Wuhan, Guangzhou, Chongqing

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

## Why Not Pure LLM (ReAct)?

The scoring is dominated by **FPR (40%) + C-LPR (25%) + EPR (20%) = 85% from constraint satisfaction**. LLMs are bad at exact arithmetic, time arithmetic, and producing valid IDs. The NeSy approach (symbolic search + backtracking) gets the best results for a reason. An LLM-only ReAct agent will waste tokens and still produce invalid times, costs, and transport IDs.

## Architecture: Rule-Based Planner + LLM for NL Understanding

```
┌─────────────────────────────────────────────┐
│  1. QUERY PARSER (LLM)                      │
│  NL → structured constraints                │
│  - required attractions, cuisines, hotels   │
│  - budget cap, transport preferences        │
│  - special timing requests                  │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│  2. DATA GATHERER (deterministic)           │
│  Query WorldEnv once, cache everything:     │
│  - intercity flights/trains (out + return)  │
│  - all attractions + opening hours          │
│  - all restaurants + opening hours          │
│  - all accommodations + prices              │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│  3. ITINERARY BUILDER (deterministic)       │
│  Day-by-day schedule construction:          │
│  Day 1: intercity arrival → activities      │
│  Day 2..N-1: breakfast → attractions →      │
│              lunch → attractions → dinner → │
│              hotel                           │
│  Day N: activities → intercity departure    │
│                                             │
│  Each step:                                 │
│  - Pick next POI (prioritize required ones) │
│  - Call goto() for transport segments       │
│  - Compute exact times, costs, tickets      │
│  - Validate timing feasibility              │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│  4. CONSTRAINT CHECKER (symbolic)           │
│  Run commonsense + hard_logic_py checks     │
│  If fail → backtrack/adjust                 │
└─────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. LLM role is minimal and front-loaded

Use the LLM only once at the start to extract structured constraints from `nature_language` (required attractions, budget limits, transport preferences, cuisine preferences). Everything else is deterministic — this avoids hallucinated IDs, wrong prices, and timing errors.

### 2. Greedy day-by-day construction, not search

The NeSy agent does breadth-first search with backtracking, which is powerful but complex. A simpler approach: greedily fill each day following a fixed template (intercity → breakfast → attraction → lunch → attraction → dinner → hotel), inserting required POIs first, then filling with nearby ones. This reliably produces valid plans.

### 3. Every value comes from the environment

Never let the LLM generate a price, time, transport ID, or POI name. Always query `WorldEnv` and use the returned values verbatim. This is the single most important principle for passing EPR constraints.

### 4. Transport is computed, not guessed

Always call `goto()` to get exact walk/metro/taxi segments between locations. Use the returned distance, duration, and cost directly.

### 5. Fixed time budgets

Use the same defaults the NeSy agent uses: ~90 min per attraction, ~60 min per meal. This simplifies scheduling enormously.

### 6. Graceful degradation

Even if hard constraints can't all be met, a structurally valid plan still earns EPR points (20%). Always output *something* valid.

## Why This Beats Alternatives

| Approach | Problem |
|----------|---------|
| Pure ReAct | LLM hallucinates IDs, miscalculates costs, times out on tool loops |
| Full NeSy search | Complex to implement, heavy backtracking machinery |
| LLM-Modulo | Needs oracle translation (hidden at test), multiple LLM rounds |
| **Structured planner** | Simple, fast, reliable on the 85% that matters |

## Implementation Phases

### Phase 1 — Baseline that always produces valid plans

Hard-code the day template, pick random valid POIs, compute all times/costs from env. Target: high EPR (environment pass rate).

### Phase 2 — Add NL constraint parsing

Use LLM to extract required attractions/constraints from `nature_language`. Insert required POIs into the plan. Target: high C-LPR + FPR.

### Phase 3 — Optimize preferences

Maximize daily attractions (DAV), minimize transport time (ATT), add 3 meals/day (DDR). Use `attractions_nearby()` to cluster POIs geographically.

### Phase 4 — Constraint validation + retry

Run `func_commonsense_constraints` and `evaluate_constraints_py` on the output. If failures, adjust and retry (still within 300s budget).

## Entry Points

- `chinatravel/agent/tpc_agent/tpc_agent.py` — `TPCAgent.run()` method (to implement)
- `chinatravel/agent/tpc_agent/tpc_llm.py` — `TPCLLM` class (LLM wrapper to implement)

## Run & Evaluate

```bash
python run_tpc.py --splits tpc_phase1 --agent TPCAgent --llm TPCLLM --timeout 300 --lang en
python eval_tpc.py --splits tpc_phase1 --method TPCAgent_TPCLLM_en
```

## Key Environment APIs (WorldEnv)

| Category | Key APIs |
|----------|----------|
| Attractions | `attractions_select`, `attractions_nearby`, `attractions_id_is_open`, `attractions_types` |
| Restaurants | `restaurants_select`, `restaurants_nearby`, `restaurants_id_is_open`, `restaurants_cuisine` |
| Hotels | `accommodations_select`, `accommodations_nearby` |
| Inner-city transport | `goto(city, start, end, time, transport_type)` → route segments with cost/time |
| Intercity transport | `intercity_transport_select(start_city, end_city, type, earliest_time)` → trains/flights |

## Constraints to Satisfy

### Environment (commonsense) constraints
- Intercity transport on first/last day with valid IDs
- Chronological timing (all activities ordered, no overlaps)
- Valid POIs (attractions/restaurants must exist in city DB)
- Correct costs (match environment prices × tickets/rooms)
- Transport segments between different locations
- Restaurant timing (breakfast ≤9:00, lunch 11:00–14:00, dinner ≥17:00)
- Accommodation required if >1 day trip

### Hard logic constraints (from query)
- Visit specific attractions
- Budget limits
- Transport mode restrictions
- Hotel requirements
- People count / ticket count correctness

## Data Sizes (per city, approximate)

- ~330 attractions
- ~470 restaurants
- ~380 accommodations
- 720 flights total (all city pairs)
- 90 train route files

## Phase 2 Status (2026-06-12)

Full evaluation after integrating parsed NL constraints:

- Overall: 73.39
- FPR: 58.00
- C-LPR: 84.81
- EPR-micro: 99.96
- EPR-macro: 99.10
- DAV: 29.26
- ATT: 81.65
- DDR: 69.07

Interpretation:

- Environment validity is already near ceiling (EPR).
- The main remaining score gap is hard-logic satisfaction (FPR/C-LPR), not output schema or commonsense structure.

## Failure Analysis Snapshot

Constraint-category pass rates (from hard logic diagnostics):

- Budget constraints: 53.4% (largest gap)
- Restaurant requirements: 69.2%
- Attraction requirements: 74.6%
- Intercity mode: 87.7%
- Hotel requirements: 88.3%

High-failure parsed keys (support >= 20):

- `timing_constraints`: 67.1% fail ratio
- `hotel_nearby`: 64.1% fail ratio
- `required_attraction_types`: 58.8% fail ratio
- `budgets`: 50.8% fail ratio
- `required_attractions`: 47.7% fail ratio

## Continuation Plan (Next Session)

### Priority 1 — Budget-Aware Construction (highest ROI)

Goal: lift budget constraint pass rate from ~53% to >=75%.

Tasks:

1. Add per-plan budget tracker during itinerary build:
    - `sightseeing`
    - `dining`
    - `accommodation`
    - `intercity`
    - `innercity`
    - `total`
2. Before appending any activity, compute projected bucket totals.
3. If over budget, apply deterministic fallback sequence:
    - attractions: free/cheaper alternative
    - restaurants: cheaper candidate
    - hotels: cheaper valid candidate
    - intercity: train vs airplane fallback (if allowed)
    - inner-city: walk/metro fallback (if allowed)
4. Keep all values from env APIs; never estimate prices.

### Priority 2 — Hard Commitment for Required Entities

Goal: improve required-attraction/restaurant/hotel satisfaction.

Tasks:

1. Build explicit "must-satisfy" sets from parsed constraints:
    - required attractions (name)
    - required attraction types
    - required restaurants
    - required hotels
2. Reserve schedule slots for these before filling optional POIs.
3. Track completion flags and prevent plan finalization until all required items are either satisfied or proven infeasible.
4. For infeasible cases, use best-effort nearest/partial text matching fallback and continue.

### Priority 3 — Timing and Proximity Handlers

Goal: reduce failures on `timing_constraints` and `hotel_nearby`.

Tasks:

1. Implement per-constraint timing guards (`depart_no_earlier`, etc.) in activity placement.
2. For `hotel_nearby`, select hotel from `accommodations_nearby(reference, distance_km)` first, then apply room/budget filters.
3. Re-check feasible departure windows on final day after all insertions.

### Priority 4 — Disjunctive Branch Selection (`groups`)

Goal: increase FPR by choosing easier OR branch.

Tasks:

1. For disjunctive queries, generate one candidate plan per group (or top-2 groups by cheap heuristic).
2. Score each candidate with hard-logic evaluator.
3. Return the best candidate (max passed constraints, then lower total cost).

### Priority 5 — Lightweight Repair Loop

Goal: catch residual misses without heavy search.

Tasks:

1. After initial build, run hard-logic checks once.
2. If fail, run up to 2 targeted repair passes (budget fix, missing required POI fix, timing fix).
3. Keep a strict time guard to remain safely within the 300s timeout.

## Suggested Milestones

1. **M1:** Budget-aware planner + re-eval
2. **M2:** Required-entity hard commitment + re-eval
3. **M3:** Timing/proximity + disjunctive branching + re-eval
4. **M4:** Repair loop + final full eval

## Expected Impact

If priorities 1-3 are implemented correctly, a realistic next target is:

- FPR: 58 -> 65-72
- C-LPR: 84.8 -> 88-92
- Overall: 73.4 -> high 70s / low 80s

Preference metrics can be tuned later; they are lower leverage than constraint satisfaction.
