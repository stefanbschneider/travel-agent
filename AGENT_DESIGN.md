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
