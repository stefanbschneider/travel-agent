"""CP-SAT candidate solver for TPC itinerary construction.

CP-SAT selects the *set* of POIs (attractions, restaurants), the hotel, and the
intercity legs subject to hard selection/budget constraints.  It deliberately
does NOT pin wall-clock times: travel time between chosen POIs is only known at
reconstruction.  ``_reconstruct_plan`` then distributes the selected set across
days and schedules each activity as early as travel/open-hours/windows allow,
mirroring the greedy builder's meal and breakfast conventions so the emitted
plan is accepted by the same oracle ``check``.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

from agent.tpc_agent.tpc_agent import minutes_to_time, time_to_minutes


DAY_OPEN = 9 * 60
DAY_CLOSE = 22 * 60
LUNCH_OPEN, LUNCH_LATEST_START, LUNCH_CLOSE = 11 * 60, 13 * 60, 14 * 60
DINNER_OPEN, DINNER_LATEST_START, DINNER_CLOSE = 17 * 60, 19 * 60, 20 * 60
STATION_BUFFER = 45


def solve_with_cp_sat(agent, query: dict, constraints: dict, check, time_limit_sec: float) -> dict | None:
    """Build and check one CP-SAT itinerary candidate.

    OR-Tools is imported lazily so the legacy greedy/search path still imports in
    environments where the optional solver dependency has not been installed.
    """

    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None

    try:
        attr_cap = int(os.environ.get("TPC_CP_ATTR_CAP", "60"))
        rest_cap = int(os.environ.get("TPC_CP_REST_CAP", "40"))
        hotel_cap = int(os.environ.get("TPC_CP_HOTEL_CAP", "60"))
    except Exception:
        attr_cap, rest_cap, hotel_cap = 60, 40, 60

    caps = {"attractions": max(1, attr_cap), "restaurants": max(1, rest_cap), "hotels": max(1, hotel_cap)}
    constraints = _augment_required_presence(constraints)
    ctx = build_candidate_context_relaxed(agent, query, constraints, caps)
    if not (ctx["hotels"] and ctx["outbound_intercity"] and ctx["return_intercity"] and ctx["restaurants"]):
        return None

    start = time.time()
    templates = (2, 3, 4)
    for index, attr_slots_per_day in enumerate(templates):
        remaining = float(time_limit_sec) - (time.time() - start)
        if remaining <= 0.2:
            break
        per_template = max(1.0, remaining / max(1, len(templates) - index))
        plan = _solve_template(cp_model, agent, query, constraints, check, ctx, attr_slots_per_day, per_template)
        if plan is not None:
            return plan
    return None


def _augment_required_presence(constraints: dict) -> dict:
    """A positioned time-window / stay-duration clause can only pass if that POI
    is actually in the plan, so treat its location as required presence.  The
    name is added to both required pools; it only binds the pool it truly matches
    (the other pool finds no candidate and silently ignores it)."""
    locations = []
    for window in constraints.get("activity_time_windows", []) or []:
        if isinstance(window, dict) and window.get("location"):
            locations.append(str(window["location"]))
    for stay in constraints.get("stay_duration", []) or []:
        if isinstance(stay, dict) and stay.get("location"):
            locations.append(str(stay["location"]))
    for name in constraints.get("position_presence", []) or []:
        if name:
            locations.append(str(name))
    if not locations:
        return constraints
    out = dict(constraints)
    req_attr = list(out.get("required_attractions", []) or [])
    req_rest = list(out.get("required_restaurants", []) or [])
    for loc in locations:
        if loc not in req_attr:
            req_attr.append(loc)
        if loc not in req_rest:
            req_rest.append(loc)
    out["required_attractions"] = req_attr
    out["required_restaurants"] = req_rest
    return out


def build_candidate_context_relaxed(agent, query: dict, constraints: dict, caps: dict) -> dict:
    """Candidate context with a fallback that drops optional pool filters when a
    filtered pool comes back empty (so over-strict nearby/type/mode filters do
    not make the whole solve infeasible)."""
    from agent.tpc_agent.cp_candidates import build_candidate_context

    ctx = build_candidate_context(agent, query, constraints, caps)
    if not ctx["hotels"]:
        relaxed = dict(constraints)
        relaxed.pop("hotel_nearby", None)
        relaxed.pop("poi_distance_hotel", None)
        relaxed.pop("required_hotel_any_types", None)
        ctx_h = build_candidate_context(agent, query, relaxed, caps)
        if ctx_h["hotels"]:
            ctx["hotels"] = ctx_h["hotels"]
    if not (ctx["outbound_intercity"] and ctx["return_intercity"]) and isinstance(constraints.get("intercity_mode"), dict):
        relaxed = dict(constraints)
        relaxed.pop("intercity_mode", None)
        ctx_i = build_candidate_context(agent, query, relaxed, caps)
        if not ctx["outbound_intercity"]:
            ctx["outbound_intercity"] = ctx_i["outbound_intercity"]
        if not ctx["return_intercity"]:
            ctx["return_intercity"] = ctx_i["return_intercity"]
    return ctx


def _solve_template(cp_model, agent, query, constraints, check, ctx: dict, attr_slots_per_day: int, time_limit_sec: float) -> dict | None:
    attractions = ctx["attractions"]
    restaurants = ctx["restaurants"]
    hotels = ctx["hotels"]
    outbound = ctx["outbound_intercity"]
    returning = ctx["return_intercity"]
    people = ctx["people"]
    days = ctx["days"]
    if not attractions or not restaurants or not hotels or not outbound or not returning:
        return None

    visit_minutes = _base_visit_minutes(constraints)
    attr_slot_count = max(1, attr_slots_per_day * days)
    meal_slots = _meal_slots(days)

    model = cp_model.CpModel()
    hotel_idx = model.NewIntVar(0, len(hotels) - 1, "hotel_idx")
    outbound_idx = model.NewIntVar(0, len(outbound) - 1, "outbound_idx")
    return_idx = model.NewIntVar(0, len(returning) - 1, "return_idx")

    attr_vars = [model.NewIntVar(0, len(attractions), f"attr_{i}") for i in range(attr_slot_count)]
    rest_vars = [model.NewIntVar(0, len(restaurants), f"rest_{i}") for i in range(len(meal_slots))]
    attr_eq = _equality_bools(model, attr_vars, len(attractions), "attr_eq")
    rest_eq = _equality_bools(model, rest_vars, len(restaurants), "rest_eq")
    attr_selected = _selection_bools(model, attr_vars, "attr_sel")
    rest_selected = _selection_bools(model, rest_vars, "rest_sel")

    out_units, ret_units = _constrain_intercity(model, outbound_idx, return_idx, outbound, returning)
    _constrain_required_hotel(model, hotel_idx, hotels)
    _constrain_attr_eligibility(model, attr_vars, attractions, constraints, agent, visit_minutes)
    _constrain_meal_eligibility(model, rest_vars, restaurants, meal_slots)
    _constrain_meal_type_windows(model, rest_vars, restaurants, meal_slots, constraints, agent)
    _constrain_required_pois(model, attr_eq, rest_eq, attractions, restaurants, attr_vars, rest_vars, constraints, agent)
    _constrain_no_duplicates(model, attr_eq, rest_eq, attr_vars, rest_vars, len(attractions), len(restaurants))

    total_cost = _constrain_budgets(
        model, constraints, people, hotel_idx, outbound_idx, return_idx,
        attr_vars, rest_vars, attr_selected, rest_selected,
        hotels, outbound, returning, attractions, restaurants,
    )
    total_cost_yuan = model.NewIntVar(0, 10**7, "total_cost_yuan")
    model.AddDivisionEquality(total_cost_yuan, total_cost, 100)
    model.Maximize(
        1000 * sum(attr_selected) + 100 * sum(rest_selected) - total_cost_yuan + ret_units - out_units
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, float(time_limit_sec))
    solver.parameters.num_search_workers = max(1, int(os.environ.get("TPC_CP_SEARCH_WORKERS", "1")))
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignment = {
        "hotel": hotels[solver.Value(hotel_idx)],
        "outbound": outbound[solver.Value(outbound_idx)],
        "return": returning[solver.Value(return_idx)],
        "attrs": [attractions[solver.Value(v) - 1] for v in attr_vars if solver.Value(v) > 0],
        "lunch": [restaurants[solver.Value(rest_vars[i]) - 1] for i, s in enumerate(meal_slots)
                  if s["meal_type"] == "lunch" and solver.Value(rest_vars[i]) > 0],
        "dinner": [restaurants[solver.Value(rest_vars[i]) - 1] for i, s in enumerate(meal_slots)
                   if s["meal_type"] == "dinner" and solver.Value(rest_vars[i]) > 0],
        "visit_minutes": visit_minutes,
    }
    plan = _reconstruct_plan(agent, query, constraints, ctx, assignment, check)
    if plan is None:
        return None
    try:
        passed, total = check(plan)
    except Exception:
        return None
    return plan if passed == total else None


# ---------------------------------------------------------------------------
# CP-SAT model helpers
# ---------------------------------------------------------------------------

def _equality_bools(model, vars_: list, candidate_count: int, prefix: str) -> dict[tuple[int, int], Any]:
    out = {}
    for slot_idx, var in enumerate(vars_):
        for value in range(1, candidate_count + 1):
            b = model.NewBoolVar(f"{prefix}_{slot_idx}_{value}")
            model.Add(var == value).OnlyEnforceIf(b)
            model.Add(var != value).OnlyEnforceIf(b.Not())
            out[(slot_idx, value)] = b
    return out


def _selection_bools(model, vars_: list, prefix: str) -> list:
    bools = []
    for i, var in enumerate(vars_):
        b = model.NewBoolVar(f"{prefix}_{i}")
        model.Add(var != 0).OnlyEnforceIf(b)
        model.Add(var == 0).OnlyEnforceIf(b.Not())
        bools.append(b)
    return bools


def _constrain_intercity(model, outbound_idx, return_idx, outbound: list[dict], returning: list[dict]):
    """Return daytime-preference unit vars (30-min granularity) for the objective.

    No hard time bound: reconstruction validates real feasibility; the objective
    just prefers early arrival / late departure when otherwise tied."""
    out_units = model.NewIntVar(0, 48, "out_units")
    ret_units = model.NewIntVar(0, 48, "ret_units")
    model.AddElement(outbound_idx, [min(48, int(x["end_min"]) // 30) for x in outbound], out_units)
    model.AddElement(return_idx, [min(48, int(x["begin_min"]) // 30) for x in returning], ret_units)
    return out_units, ret_units


def _constrain_required_hotel(model, hotel_idx, hotels: list[dict]) -> None:
    required = [i for i, hotel in enumerate(hotels) if hotel.get("required")]
    if required:
        model.AddAllowedAssignments([hotel_idx], [[i] for i in required])


def _constrain_attr_eligibility(model, attr_vars, attractions, constraints, agent, visit_minutes) -> None:
    """Forbid an attraction in any slot only when it can never be scheduled in a
    day window (closed too short, or a named time window is unsatisfiable)."""
    blocked = []
    for cand_index, attr in enumerate(attractions, start=1):
        if attr.get("required") or attr.get("type_match"):
            continue
        if not _attr_day_feasible(agent, attr, constraints, visit_minutes):
            blocked.append(cand_index)
    if not blocked:
        return
    for var in attr_vars:
        for cand_index in blocked:
            model.Add(var != cand_index)


def _constrain_meal_eligibility(model, rest_vars, restaurants, meal_slots) -> None:
    for slot_index, slot in enumerate(meal_slots):
        for cand_index, rest in enumerate(restaurants, start=1):
            if not _restaurant_meal_feasible(rest, slot["meal_type"]):
                model.Add(rest_vars[slot_index] != cand_index)


def _constrain_meal_type_windows(model, rest_vars, restaurants, meal_slots, constraints, agent) -> None:
    """A restaurant whose time window implies a specific meal (e.g. start <= 11:00
    is a lunch; end >= 17:40 is a dinner) must occupy only that meal's slots."""
    for cand_index, rest in enumerate(restaurants, start=1):
        window = _attr_window(agent, rest, constraints)
        if not any(v is not None for v in window.values()):
            continue
        is_lunch = (window["latest"] is not None and window["latest"] <= LUNCH_CLOSE) or \
                   (window["end_before"] is not None and window["end_before"] <= LUNCH_CLOSE)
        is_dinner = (window["earliest"] is not None and window["earliest"] >= DINNER_OPEN - 30) or \
                    (window["end_after"] is not None and window["end_after"] >= DINNER_OPEN)
        for slot_index, slot in enumerate(meal_slots):
            if is_lunch and not is_dinner and slot["meal_type"] == "dinner":
                model.Add(rest_vars[slot_index] != cand_index)
            if is_dinner and not is_lunch and slot["meal_type"] == "lunch":
                model.Add(rest_vars[slot_index] != cand_index)


def _constrain_required_pois(model, attr_eq, rest_eq, attractions, restaurants, attr_vars, rest_vars, constraints, agent) -> None:
    for req in constraints.get("required_attractions", []) or []:
        matches = [attr_eq[(slot, idx + 1)] for slot in range(len(attr_vars))
                   for idx, attr in enumerate(attractions) if agent._match_constraint_text(attr.get("name", ""), req)]
        if matches:
            model.Add(sum(matches) >= 1)
    for req_type in constraints.get("required_attraction_types", []) or []:
        matches = [attr_eq[(slot, idx + 1)] for slot in range(len(attr_vars))
                   for idx, attr in enumerate(attractions) if _eq_norm(attr.get("type", ""), req_type)]
        if matches:
            model.Add(sum(matches) >= 1)
    for req in constraints.get("required_restaurants", []) or []:
        matches = [rest_eq[(slot, idx + 1)] for slot in range(len(rest_vars))
                   for idx, rest in enumerate(restaurants) if agent._match_constraint_text(rest.get("name", ""), req)]
        if matches:
            model.Add(sum(matches) >= 1)
    for cuisine in _as_list(constraints.get("cuisine_preference")):
        matches = [rest_eq[(slot, idx + 1)] for slot in range(len(rest_vars))
                   for idx, rest in enumerate(restaurants) if _eq_norm(rest.get("cuisine", ""), cuisine)]
        if matches:
            model.Add(sum(matches) >= 1)


def _constrain_no_duplicates(model, attr_eq, rest_eq, attr_vars, rest_vars, attr_count: int, rest_count: int) -> None:
    for value in range(1, attr_count + 1):
        for i in range(len(attr_vars)):
            for j in range(i + 1, len(attr_vars)):
                model.AddBoolOr([attr_eq[(i, value)].Not(), attr_eq[(j, value)].Not()])
    for value in range(1, rest_count + 1):
        for i in range(len(rest_vars)):
            for j in range(i + 1, len(rest_vars)):
                model.AddBoolOr([rest_eq[(i, value)].Not(), rest_eq[(j, value)].Not()])


def _constrain_budgets(model, constraints, people, hotel_idx, outbound_idx, return_idx, attr_vars, rest_vars, attr_selected, rest_selected, hotels, outbound, returning, attractions, restaurants):
    max_cost = 10**9
    hotel_cost = model.NewIntVar(0, max_cost, "hotel_cost")
    out_cost = model.NewIntVar(0, max_cost, "out_cost")
    ret_cost = model.NewIntVar(0, max_cost, "ret_cost")
    model.AddElement(hotel_idx, [int(h["total_cost_cents"]) for h in hotels], hotel_cost)
    model.AddElement(outbound_idx, [int(t["cost_cents"]) * people for t in outbound], out_cost)
    model.AddElement(return_idx, [int(t["cost_cents"]) * people for t in returning], ret_cost)

    attr_cost_vars = []
    for i, var in enumerate(attr_vars):
        cost = model.NewIntVar(0, max_cost, f"attr_cost_{i}")
        model.AddElement(var, [0] + [int(a["price_cents"]) * people for a in attractions], cost)
        attr_cost_vars.append(cost)
    rest_cost_vars = []
    for i, var in enumerate(rest_vars):
        cost = model.NewIntVar(0, max_cost, f"rest_cost_{i}")
        model.AddElement(var, [0] + [int(r["price_cents"]) * people for r in restaurants], cost)
        rest_cost_vars.append(cost)

    sightseeing = sum(attr_cost_vars)
    dining = sum(rest_cost_vars)
    intercity = out_cost + ret_cost
    selected_inner_legs = sum(attr_selected) + sum(rest_selected)
    inner_reserve = int(people) * 300 * selected_inner_legs
    total = sightseeing + dining + hotel_cost + intercity
    total_with_inner_reserve = total + inner_reserve
    budgets = constraints.get("budgets") if isinstance(constraints.get("budgets"), dict) else {}
    for key, expr in (("sightseeing", sightseeing), ("dining", dining), ("accommodation", hotel_cost),
                      ("intercity_transport", intercity)):
        if key in budgets:
            model.Add(expr <= _budget_cents(budgets[key]))
    if "inner_transport" in budgets:
        model.Add(inner_reserve <= _budget_cents(budgets["inner_transport"]))
    if "total" in budgets:
        model.Add(total_with_inner_reserve <= _budget_cents(budgets["total"]))
    return total_with_inner_reserve if ("total" in budgets or "inner_transport" in budgets) else total


# ---------------------------------------------------------------------------
# Reconstruction: travel-aware flexible scheduler
# ---------------------------------------------------------------------------

def _reconstruct_plan(agent, query: dict, constraints: dict, ctx: dict, assignment: dict, check=None) -> dict | None:
    """Try several attraction orderings/distributions; return the first emitted
    plan that passes ``check`` (or the first non-None plan when check is None).

    A single greedy order cannot satisfy every routing/time-window combination,
    so we search a small set of orders (window/required-first, geographic
    nearest-neighbour from the city centroid and from the hotel, open-time, and
    a few seeded shuffles) and let the oracle decide."""
    hotel = assignment["hotel"]
    base_attrs = _ordered_attractions(agent, assignment["attrs"], constraints)
    lunch_pool = _ordered_restaurants(agent, assignment["lunch"], constraints)
    dinner_pool = _ordered_restaurants(agent, assignment["dinner"], constraints)
    orderings = _attraction_orderings(agent, base_attrs, constraints, hotel)

    saved = {
        "tc": getattr(agent, "_transport_constraints", {}),
        "bl": getattr(agent, "_budget_limits", {}),
        "tm": getattr(agent, "_active_timing_constraints", []),
        "fm": getattr(agent, "_forced_inner_mode", None),
    }
    agent._transport_constraints = constraints
    agent._budget_limits = agent._extract_budget_limits(constraints)
    agent._active_timing_constraints = constraints.get("timing_constraints", []) or []
    agent._forced_inner_mode = "taxi" if constraints.get("taxi_cars_equals") is not None else None
    try:
        first_plan = None
        for order in orderings:
            plan = _reconstruct_one(agent, query, constraints, ctx, assignment, order, lunch_pool, dinner_pool)
            if plan is None:
                continue
            if check is None:
                return plan
            if first_plan is None:
                first_plan = plan
            try:
                passed, total = check(plan)
            except Exception:
                continue
            if passed == total:
                return plan
        return first_plan if check is None else None
    finally:
        agent._transport_constraints = saved["tc"]
        agent._budget_limits = saved["bl"]
        agent._active_timing_constraints = saved["tm"]
        agent._forced_inner_mode = saved["fm"]


def _reconstruct_one(agent, query, constraints, ctx, assignment, attr_order, lunch_src, dinner_src):
    people = ctx["people"]
    days = ctx["days"]
    city = ctx["target_city"]
    hotel = assignment["hotel"]
    hotel_name = str(hotel["name"])
    outbound = assignment["outbound"]
    returning = assignment["return"]
    base_visit = assignment["visit_minutes"]

    itinerary = []
    attr_queue = list(attr_order)
    lunch_pool = list(lunch_src)
    dinner_pool = list(dinner_src)
    for day in range(1, days + 1):
        is_last = day == days
        activities = []
        if day == 1:
            out_act = agent._make_intercity_activity(outbound, people)
            activities.append(out_act)
            pos = out_act["end"]
            clock = time_to_minutes(out_act["end_time"])
        else:
            # Skip hotel breakfast on days that open with an early-anchored
            # attraction (window latest-start before breakfast ends); start at the
            # hotel early so the anchor's start-time window can be met.
            if _early_anchor_pending(agent, attr_queue, constraints):
                pos = hotel_name
                clock = 7 * 60
            else:
                activities.append(agent._make_hotel_breakfast(hotel_name, "07:30", "08:30"))
                pos = hotel_name
                clock = 8 * 60 + 30

        day_close = int(returning["begin_min"]) - STATION_BUFFER if is_last else DAY_CLOSE
        pos, clock = _fill_day(
            agent, city, people, constraints, base_visit, attr_queue, lunch_pool, dinner_pool,
            activities, pos, clock, day_close,
        )

        if is_last:
            transports, arrival = agent._get_transport(agent.env, city, pos, returning["From"], minutes_to_time(min(clock, 23 * 60 + 59)), people)
            if transports is None or arrival is None or time_to_minutes(arrival) > int(returning["begin_min"]):
                return None
            activities.append(agent._make_intercity_activity(returning, people, transports))
        else:
            if clock >= 24 * 60:
                return None
            transports, arrival = agent._get_transport(agent.env, city, pos, hotel_name, minutes_to_time(min(clock, 23 * 60 + 59)), people)
            if transports is None or arrival is None:
                return None
            check_in = max(time_to_minutes(arrival), clock)
            if check_in >= 24 * 60:
                return None
            activities.append(agent._make_accommodation_activity(hotel, int(hotel["rooms"]), minutes_to_time(check_in), transports))
            pos = hotel_name

        itinerary.append({"day": day, "activities": activities})

    if any(a.get("required") for a in attr_queue):
        return None
    return {
        "people_number": people,
        "start_city": query.get("start_city", ""),
        "target_city": city,
        "itinerary": itinerary,
    }


def _attraction_orderings(agent, attrs: list[dict], constraints: dict, hotel: dict) -> list[list[dict]]:
    if len(attrs) <= 1:
        return [list(attrs)]
    orders = []
    seen = set()

    def add(order):
        key = tuple(id(x) for x in order)
        if key not in seen:
            seen.add(key)
            orders.append(order)

    add(list(attrs))
    add(_nn_order(attrs, _centroid(attrs)))
    return orders


def _centroid(attrs: list[dict]):
    lats = [a.get("lat") for a in attrs if _is_num(a.get("lat"))]
    lons = [a.get("lon") for a in attrs if _is_num(a.get("lon"))]
    if not lats or not lons:
        return (None, None)
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _nn_order(attrs: list[dict], seed) -> list[dict]:
    remaining = list(attrs)
    if not _is_num(seed[0]) or not _is_num(seed[1]):
        return remaining
    order = []
    cur = seed
    while remaining:
        nxt = min(remaining, key=lambda a: _haversine(cur, (a.get("lat"), a.get("lon"))))
        order.append(nxt)
        remaining.remove(nxt)
        if _is_num(nxt.get("lat")) and _is_num(nxt.get("lon")):
            cur = (nxt.get("lat"), nxt.get("lon"))
    return order


def _haversine(a, b) -> float:
    if not (_is_num(a[0]) and _is_num(a[1]) and _is_num(b[0]) and _is_num(b[1])):
        return 1e9
    lat1, lon1, lat2, lon2 = map(math.radians, [float(a[0]), float(a[1]), float(b[0]), float(b[1])])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _is_num(v) -> bool:
    try:
        f = float(v)
        return f == f
    except (TypeError, ValueError):
        return False


def _fill_day(agent, city, people, constraints, base_visit, attr_queue, lunch_pool, dinner_pool, activities, pos, clock, day_close):
    """Greedily place attractions (earliest feasible) interleaving lunch/dinner by
    clock window. Optional attractions that do not fit are dropped; required ones
    are left in the queue for a later day (and ultimately fail the build)."""
    lunch_done = False
    dinner_done = False
    guard = 0
    while guard < 64:
        guard += 1
        if not lunch_done and lunch_pool and clock >= LUNCH_OPEN and clock < LUNCH_LATEST_START:
            placed = _place_meal(agent, city, people, "lunch", lunch_pool, activities, pos, clock,
                                 LUNCH_OPEN, LUNCH_CLOSE, day_close)
            lunch_done = True
            if placed:
                pos, clock = placed
                continue
        if not dinner_done and dinner_pool and clock >= DINNER_OPEN and clock < DINNER_LATEST_START:
            placed = _place_meal(agent, city, people, "dinner", dinner_pool, activities, pos, clock,
                                 DINNER_OPEN, DINNER_CLOSE, day_close)
            dinner_done = True
            if placed:
                pos, clock = placed
                continue
        if not attr_queue:
            break
        attr = attr_queue[0]
        outcome = _place_attraction(agent, city, people, constraints, base_visit, attr, activities, pos, clock, day_close)
        if outcome == "placed":
            placed_attr = activities[-1]
            pos = placed_attr["position"]
            clock = time_to_minutes(placed_attr["end_time"])
            attr_queue.pop(0)
        elif outcome == "drop":
            attr_queue.pop(0)
        else:  # "carry": cannot fit remaining day
            break

    # Place any meal still due before its window closes (e.g. late morning arrival).
    if not lunch_done and lunch_pool and clock < LUNCH_LATEST_START:
        placed = _place_meal(agent, city, people, "lunch", lunch_pool, activities, pos, clock, LUNCH_OPEN, LUNCH_CLOSE, day_close)
        if placed:
            pos, clock = placed
    if not dinner_done and dinner_pool and clock < DINNER_LATEST_START:
        placed = _place_meal(agent, city, people, "dinner", dinner_pool, activities, pos, clock, DINNER_OPEN, DINNER_CLOSE, day_close)
        if placed:
            pos, clock = placed
    return pos, clock


def _place_attraction(agent, city, people, constraints, base_visit, attr, activities, pos, clock, day_close):
    name = str(attr["name"])
    transports, arrival = agent._get_transport(agent.env, city, pos, name, minutes_to_time(min(clock, 23 * 60 + 59)), people)
    if transports is None or arrival is None:
        return "carry" if attr.get("required") else "drop"
    window = _attr_window(agent, attr, constraints)
    visit = _visit_len_for(agent, attr, constraints, base_visit)
    floor = DAY_OPEN
    if window["latest"] is not None and window["latest"] < DAY_OPEN:
        floor = 7 * 60  # early-morning anchor: allow start before the usual 09:00 floor
    start = max(time_to_minutes(arrival), floor)
    if attr.get("open_min") is not None:
        start = max(start, int(attr["open_min"]))
    if window["earliest"] is not None:
        start = max(start, window["earliest"])
    end = start + visit
    if window["end_after"] is not None:
        end = max(end, window["end_after"])
    cap = day_close
    if attr.get("close_min") is not None and int(attr["close_min"]) > int(attr.get("open_min") or 0):
        cap = min(cap, int(attr["close_min"]))
    if window["end_before"] is not None:
        cap = min(cap, window["end_before"])
    required = bool(attr.get("required"))
    if window["latest"] is not None and start > window["latest"]:
        return "carry" if required else "drop"
    if end > cap:
        return "carry" if required else "drop"
    activities.append(agent._make_attraction_activity(attr, people, minutes_to_time(start), minutes_to_time(end), transports))
    return "placed"


def _place_meal(agent, city, people, meal_type, pool, activities, pos, clock, window_open, window_close, day_close):
    for i, rest in enumerate(pool):
        name = str(rest["name"])
        transports, arrival = agent._get_transport(agent.env, city, pos, name, minutes_to_time(min(clock, 23 * 60 + 59)), people)
        if transports is None or arrival is None:
            continue
        start = max(time_to_minutes(arrival), window_open)
        end = start + 60
        if end > window_close or end > day_close:
            continue
        activities.append(agent._make_meal_activity(meal_type, rest, people, minutes_to_time(start), minutes_to_time(end), transports))
        pool.pop(i)
        return name, end
    return None


# ---------------------------------------------------------------------------
# Ordering / feasibility helpers
# ---------------------------------------------------------------------------

def _ordered_attractions(agent, attrs: list[dict], constraints: dict) -> list[dict]:
    def key(a):
        window = _attr_window(agent, a, constraints)
        windowed = 0 if any(v is not None for v in window.values()) else 1
        priority = 0 if (a.get("required") or a.get("type_match")) else 1
        anchor = window["earliest"] if window["earliest"] is not None else (a.get("open_min") if a.get("open_min") is not None else 9999)
        return (windowed, priority, anchor)
    return sorted(attrs, key=key)


def _ordered_restaurants(agent, rests: list[dict], constraints: dict) -> list[dict]:
    return sorted(rests, key=lambda r: 0 if r.get("required") or r.get("cuisine_match") else 1)


def _attr_window(agent, attr: dict, constraints: dict) -> dict:
    result = {"earliest": None, "latest": None, "end_after": None, "end_before": None}
    for window in constraints.get("activity_time_windows", []) or []:
        if not isinstance(window, dict) or not agent._match_constraint_text(attr.get("name", ""), window.get("location", "")):
            continue
        for key in result:
            value = window.get(key)
            if value:
                result[key] = time_to_minutes(str(value))
    return result


def _early_anchor_pending(agent, attr_queue: list[dict], constraints: dict) -> bool:
    """True when the next queued attraction must start before breakfast ends."""
    if not attr_queue:
        return False
    window = _attr_window(agent, attr_queue[0], constraints)
    return window["latest"] is not None and window["latest"] < 9 * 60 + 30


def _attr_day_feasible(agent, attr: dict, constraints: dict, visit_minutes: int) -> bool:
    visit = _visit_len_for(agent, attr, constraints, visit_minutes)
    open_min = attr.get("open_min")
    close_min = attr.get("close_min")
    window = _attr_window(agent, attr, constraints)
    earliest = max(DAY_OPEN, open_min if open_min is not None else DAY_OPEN, window["earliest"] or 0)
    latest_close = DAY_CLOSE
    if close_min is not None and int(close_min) > int(open_min or 0):
        latest_close = min(latest_close, int(close_min))
    if window["end_before"] is not None:
        latest_close = min(latest_close, window["end_before"])
    if window["latest"] is not None and earliest > window["latest"]:
        return False
    return earliest + visit <= latest_close


def _restaurant_meal_feasible(rest: dict, meal_type: str) -> bool:
    open_min = rest.get("open_min")
    close_min = rest.get("close_min")
    if open_min is None or close_min is None:
        return False
    if meal_type == "lunch":
        return _open_covers(open_min, close_min, LUNCH_OPEN, LUNCH_CLOSE)
    return _open_covers(open_min, close_min, DINNER_OPEN, DINNER_CLOSE)


def _open_covers(open_min: int, close_min: int, win_open: int, win_close: int) -> bool:
    """A 60-minute meal need only fit *within* the overlap of the restaurant's
    open hours and the meal window, not span the whole window."""
    open_min = int(open_min)
    close_min = int(close_min)
    if close_min <= open_min:
        close_min += 24 * 60
    start_lo = max(open_min, win_open)
    start_hi = min(close_min, win_close) - 60
    return start_lo <= start_hi


def _visit_len_for(agent, attr: dict, constraints: dict, base: int) -> int:
    need = base
    name = str(attr.get("name", ""))
    for d in constraints.get("stay_duration", []) or []:
        if isinstance(d, dict) and agent._match_constraint_text(name, d.get("location", "")):
            try:
                need = max(need, int(d.get("min_minutes", 0)))
            except (TypeError, ValueError):
                pass
    return min(240, max(90, need))


def _base_visit_minutes(constraints: dict) -> int:
    return 90


def _meal_slots(days: int) -> list[dict]:
    slots = []
    for _ in range(days):
        slots.append({"meal_type": "lunch"})
        slots.append({"meal_type": "dinner"})
    return slots


def _eq_norm(a: Any, b: Any) -> bool:
    """Exact case-sensitive equality (strip only): the oracle compares raw column
    values with case-sensitive set membership, so casefolding would let CP pick a
    candidate the oracle rejects."""
    return str(a).strip() == str(b).strip()


def _budget_cents(value: Any) -> int:
    try:
        return int(round(float(value) * 100))
    except Exception:
        return 0


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]
