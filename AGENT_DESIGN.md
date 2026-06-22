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

## Phase 1 Leaderboard Findings (2026-06-22)

Latest self-reported best result:

| Metric | Score |
|--------|-------|
| MicEPR | 100.00 |
| MacEPR | 100.00 |
| C-LPR | 99.3834 |
| FPR | 98.20 |
| DAV | 67.0812 |
| ATT | 82.4477 |
| DDR | 69.5406 |
| Overall | 95.0793 |

The attached public leaderboard snapshot shows the top 7 clustered in the 95.3-98.1 range, so the main gap is no longer basic feasibility. Phase 1 is now a score-maximization problem over already-valid plans.

### Score-gap interpretation

With FPR and C-LPR already near ceiling, hard-constraint work has limited remaining upside. Even a perfect 100/100 on FPR and C-LPR would only add about +0.87 overall from the current best, which is not enough to reach the top-5 band by itself. The remaining lift must come from DAV, ATT, and DDR, while preserving validity.

### Highest-leverage Phase 1 actions

1. Keep searching after the first accepted plan. The current solver stops early once it finds any accepted candidate, but that is leaving preference score on the table. Continue sampling accepted candidates until the per-query time budget is exhausted, then keep the best accepted one.
2. Add a post-acceptance local optimizer. Current packing/densification mainly adds meals and attractions in idle gaps. Extend this into a small acceptance-gated neighborhood search over hotel choice, intercity mode preferences, restaurant rotation, attraction rotation, and visit length.
3. Search `visit_minutes` explicitly. Try shorter optional attraction dwell times such as 60 and 75 minutes, not only the default 90, while respecting explicit stay-duration constraints. This is a low-risk way to improve DAV and sometimes ATT.
4. Use route-aware ranking instead of price-first ranking. Candidate ordering should consider distance to the current anchor, hotel, and intercity endpoints so the plan spends less time in transit.
5. Optimize the low-score tail first. A handful of very weak plans can move the average more than many small gains on already-strong plans. Rank queries by current score and failure signature, not only by unsolved status.
6. Extend CP-SAT from rescue to optimization. The CP tier currently helps only when greedy search stalls. Run it on already-accepted queries as a preference optimizer with soft travel and clustering terms, not just as a feasibility fallback.

### Practical implication

For Phase 1, the best return on engineering time is now:

1. Preserve current hard-constraint strength.
2. Increase the number of accepted candidates per query that are explored.
3. Improve preference quality on accepted plans using local search or CP-based refinement.
4. Spend extra compute on the worst-scoring queries first.

## Competition Phase 1 Strategy: Per-Query Optimization

Treat the leaderboard as a per-query optimization problem over the released 1000 queries:

1. Solve or near-solve each query individually.
2. Track the best result per query in `results/best/`.
3. Persist any fully constraint-solved result in `results/constraints_solved/`.
4. Assemble the submission from the best known answer per query.

Any solver or repair logic developed here should stay modular so it can be reused in the Competition Phase 2 harness.

See extra eval args `--index` and `--update_best` to check and update best and solved results.

## Comparison: Our TPCAgent vs Branch-and-Bound PR Approach

Both approaches are now largely combinatorial and deterministic, with limited LLM dependence in practice.

| Aspect | Our TPCAgent (current) | Branch-and-Bound PR (#22) |
|--------|-------------------------|----------------------------|
| Primary search | Constraint-first multi-tier search (base build + repairs + random restarts) | Branch-and-bound over skeleton choices |
| Exact solver tier | CP-SAT rescue (optional, targeted) | B&B primary, plus CP-SAT / MILP experiments |
| Constraint handling | Branch-local variants + acceptance checker (logic, then schema/commonsense gate) | Skeleton-level pruning with many iterative assembler fixes |
| Plan assembly | Deterministic builder + reconstruction + constraint-safe packing/densify | Deterministic assembler inside chosen skeleton |
| LLM role | Mostly constraint extraction; practical runs are largely solver/heuristic driven | Mostly NL2SL and ranking support; core solving is combinatorial |
| Optimization target | Direct acceptance objective used in selection | Hard-logic-focused with iterative bug-fix tuning |

### Practical Learnings We Should Keep

1. Preserve deterministic-first design. Keep LLM usage narrow (parsing only) and push decisions into searchable/checked components.
2. Keep branch-local OR handling strict. Avoid cross-branch leakage in required entities and budgets.
3. Continue early feasibility filtering. Filter closed/invalid candidates as early as possible before expensive search or repair.
4. Keep name canonicalization robust. Normalize whitespace/casing and maintain safe fuzzy fallback for entity matching.
5. Prioritize invariant-safe densification. Any DAV/DDR lift must remain acceptance-gated (never trade FPR/C-LPR for preferences).
6. Maintain cached, resumable workflows. Content-aware caching and resumable heavy/light loops are high leverage for iterative per-query optimization.
7. Keep CP-SAT focused. Use CP-SAT as a rescue tier for hard leftovers where greedy/repair search stalls, not as mandatory first-line for every query.

### Concrete PR-Derived Actions To Test (Priority Order)

1. Add explicit restaurant "unuse" rollback semantics in assembly/repair.
    If a restaurant is tentatively selected but rejected later (timing, window close, budget), return it to the candidate pool immediately so it remains available for later meal slots.
2. Preserve ordered pins for required entities.
    Do not use unordered sets when parsing/propagating required POI or restaurant pins; keep insertion order to avoid losing NL-specified sequences.
3. Harden entity-name canonicalization.
    Normalize interior whitespace (collapse repeated spaces), trim, and lowercase before matching; keep current fuzzy fallback only after normalized exact/contains checks.
4. Add meal-window-close guards before candidate commitment.
    Skip restaurants whose open time is already beyond the slot close (breakfast/lunch/dinner), instead of selecting then failing later in reconstruction.
5. Move closed-venue filtering earlier in the pipeline.
    Pre-filter by open-hours feasibility before expensive search and before CP candidate extraction to reduce dead-end branches.
6. Add a focused second-pass parse for OR/compound constraints.
    Keep the primary parse, then run a narrow follow-up pass for OR-group structure and conditional clauses; use only when confidence is low or branch extraction is ambiguous.
7. Expand failure-class diagnostics in iterative runs.
    Keep per-query eval traces and bucket failures (timing, required entity/type, budget, transport condition) so repair priors can target the dominant residual class.

These actions should be validated with monotonic acceptance criteria: retain only changes that improve full-score aggregates while preserving or improving FPR and C-LPR.

### Notes For Phase 2

- Current architecture already aligns with a no-oracle harness direction: parsed constraints, deterministic builder, symbolic verification, and optional exact solver rescue.
- Main risk is parser parity on unseen query phrasing; keep improving no-oracle robustness without weakening hard-constraint reliability.

## Remaining Priorities

1. **Phase 1 leaderboard uplift.** Improve DAV/ATT/DDR on already-valid plans while preserving current hard-constraint rates.
2. **Phase-2 no-oracle robustness.** Improve parity between oracle hard-logic pass and parsed-verifier pass on held-out style queries.
3. **Operational reliability.** Keep solve/merge scripts robust for long resumable runs and HPC usage.
4. **Harness packaging.** Keep a reproducible, self-contained harness for organizer evaluation on Qwen3.6-27B via SGLang.
