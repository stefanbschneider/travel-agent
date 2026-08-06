---
name: chinatravel-agent-env
description: Use when solving or inspecting ChinaTravel queries through the local agent_env CLI, producing an evaluator-valid itinerary, or invoking the no-oracle Phase 2 harness.
---

# ChinaTravel Agent Environment

Use this skill for one query at a time from the repository root.
Use the project interpreter for every command:

```bash
.venv/bin/python -m agent_env.cli --lang en tools
.venv/bin/python -m agent_env.cli --lang en call <tool_name> '<json_arguments>'
.venv/bin/python -m agent_env.cli --lang en world '<WorldEnv command>'
```

Pass `--lang en` on every call (or export `CHINATRAVEL_LANG=en`): the CLI defaults to `zh`, and the
TPC competition data is English. Use English city and POI names to match — `Shanghai`, not `上海`.

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

**`solve_script_with_harness.py --method <method> --split <split>` (no other flags, run from the
repository root) is the organizer-confirmed Phase 2 evaluation command** (2026-08-06 clarification;
see [competition
reference](../docs/reference/competition.md#dsl-free-data-latest-harnessevaluator-and-the-method-argument-2026-08-06)).
Both values are theirs: `--split` picks the held-out split, `--method` names the output directory,
and plans must land at `results/<method>/<uid>.json`. Neither may be hard-coded, and neither is.
It runs the deterministic no-oracle solver in-process — no external CLI, no LLM call, no subprocess:

```bash
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --method <method> --split <split>
```

The same script drives an external agent CLI only when asked explicitly, for baseline comparison:

```bash
.venv/bin/python agent_env/scripts/solve_script_with_harness.py --harness opencode --split <split> --uid <uid>
```

`solve_phase2.py` remains the direct, development-facing runner for the same solver:

```bash
.venv/bin/python agent_env/scripts/solve_phase2.py --split <split> --limit 1 --budget-sec 300
```

All of them write plans to `results/<method>/<uid>.json`. The external-CLI harness stores prompt,
output, and evaluation artifacts under its configured run directory; the deterministic path also
stores `telemetry.json`.

There is no per-query timeout — the organizers give the whole 100-query run a single 5-hour
wall-clock budget, excluding setup. The confirmed command schedules against that envelope itself:
triage every query cheaply, then repair the constraint-failing ones at growing budgets, then polish
preferences, across `CPU count - 1` worker processes, keeping the best plan found for each query
and pre-writing a valid fallback for all of them. `--budget-sec`/`--timeout` remain local per-query
development settings, not organizer rules. See the
[competition reference](../docs/reference/competition.md#confirmed-execution-versioning-feedback-and-timeout-2026-08-04-organizer-reply)
and [agent_env/README.md](README.md#server-and-harness-entry-points).
