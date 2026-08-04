---
name: chinatravel-agent-env
description: Use when solving or inspecting ChinaTravel queries through the local agent_env CLI, producing an evaluator-valid itinerary, or invoking the no-oracle Phase 2 harness.
---

# ChinaTravel Agent Environment

Use this skill for one query at a time from the repository root.
Use the project interpreter for every command:

```bash
.venv/bin/python -m agent_env.cli tools
.venv/bin/python -m agent_env.cli call <tool_name> '<json_arguments>'
.venv/bin/python -m agent_env.cli world '<WorldEnv command>'
```

## Query and tool workflow

1. Load the assigned query with `china_travel_load_query`; use only its visible fields in a Phase 2 solve. The tool rejects oracle-translation overrides and strips oracle verifier fields defensively.
2. Inspect the structured tool catalog and the relevant table keys before filtering a city, POI, restaurant, accommodation, or transport route.
3. Use structured calls first. Use `world` only when the catalog has no equivalent lookup. It accepts direct calls to allowlisted `WorldEnv` functions with literal arguments or safe one-argument predicates; imports, attribute access, and arbitrary Python are rejected.
4. Check every response's `success` field before consuming `data`.
5. Copy exact returned names, IDs, prices, times, distances, route segments, room metadata, and transport counts into the itinerary. Never invent an environment fact.

The Phase 2 agent path must not read, infer from, emit, or retain oracle verifier fields.
The harness may keep those fields separately for evaluation; that does not authorize access by the agent.
Phase 1 may use released oracle data only when its caller explicitly selects that offline workflow.

## Output discipline

Return one final JSON itinerary and no explanatory prose.
When a harness requires wrapper tags, put only that JSON between its prescribed tags.
The structural contract is [output_schema.json](../chinatravel/evaluation/output_schema.json).
A schema-valid object is necessary but not sufficient: the semantic authority is [commonsense_constraint.py](../chinatravel/symbol_verification/commonsense_constraint.py), plus the hard-constraint evaluator used by the harness.

Every activity has `type`, `start_time`, `end_time`, `price`, `cost`, and `transports`.
Use `HH:MM` times and preserve activity order.

| Activity | Required semantic fields and facts |
| --- | --- |
| `train` / `airplane` | Use the exact first outbound and final return service. Include `start`, `end`, `tickets`, the matching `TrainID` or `FlightID`, returned times and price, and `cost = price × tickets`. Do not provide `position`. |
| `attraction` | Include exact `position`, `tickets`, returned price, and `cost = price × tickets`. Schedule entirely within the returned opening interval. Do not repeat an attraction. |
| `breakfast` / `lunch` / `dinner` | Include exact restaurant or breakfast-hotel `position`, returned price, and `cost = price × people_number`. A hotel breakfast has price and cost zero. Do not repeat restaurants. Respect returned opening hours. Start meals in the inclusive planner windows: breakfast `07:00`–`09:00`, lunch `11:00`–`13:00`, dinner `17:00`–`20:00`. |
| `accommodation` | Include exact `position`, returned `price` and `room_type`, `rooms`, and `cost = price × rooms`. A multi-day itinerary needs accommodation. |

For each non-empty in-city `transports` route, preserve the exact tool-returned segments and their order.
Do not synthesize a metro route: it has the returned walk–metro–walk segments.
Walk and taxi are their returned single segments; use the returned fare, distance, times, tickets or cars, and matching cost formula.

## Validate before delivery

Check all visible hard requirements against the constructed itinerary before returning it.
Then verify structure, semantic facts, timing, route continuity, and cost arithmetic against the sources above.
If a requirement or verifier behavior is unclear, inspect the source or query the environment; do not guess.

## Harness entry points

Use the generic compatibility harness when a caller asks for OpenCode or Codex execution:

```bash
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --split <split> --uid <uid>
```

Use the repository no-oracle implementation for Phase 2 orchestration:

```bash
.venv/bin/python agent_env/scripts/solve_phase2.py --split <split> --limit 1 --budget-sec 300
```

Both write plans to `results/<method>/<uid>.json`. The generic harness stores prompt, output, and evaluation artifacts under its configured run directory; the repository runner also stores `telemetry.json`.

**`solve_script_with_harness.py --split <split>` (no other flags) is the organizer-confirmed Phase 2
evaluation command** (2026-08-04 direct reply). There is no per-query timeout — the organizers give the
whole 100-query run a single 5-hour wall-clock budget, excluding setup; `--budget-sec`/`--timeout` values
above remain local per-query development settings, not organizer rules. As shipped, the confirmed
command's default harness (`opencode`) is the external-CLI demo, not the real deterministic solver behind
`solve_phase2.py` — see the [competition reference](../docs/reference/competition.md#a-critical-gap-this-reply-surfaces-our-real-solver-isnt-wired-to-the-confirmed-entry-point)
for the gap and its fix priority.
