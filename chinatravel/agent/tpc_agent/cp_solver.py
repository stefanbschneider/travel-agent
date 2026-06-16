"""CP-SAT candidate solver for TPC itinerary construction."""

from __future__ import annotations

import math
import os
import time
from typing import Any

from agent.tpc_agent.cp_candidates import build_candidate_context
from agent.tpc_agent.transport_cache import build_transition_cache
from agent.tpc_agent.tpc_agent import add_minutes, minutes_to_time, time_to_minutes


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
    ctx = build_candidate_context(agent, query, constraints, caps)
    if not (ctx["hotels"] and ctx["outbound_intercity"] and ctx["return_intercity"]):
        return None
    if not ctx["restaurants"]:
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

    visit_minutes = _visit_minutes(constraints)
    attr_slots = _attribute_slots(days, attr_slots_per_day, visit_minutes)
    meal_slots = _meal_slots(days)
    if not attr_slots:
        return None

    model = cp_model.CpModel()
    hotel_idx = model.NewIntVar(0, len(hotels) - 1, "hotel_idx")
    outbound_idx = model.NewIntVar(0, len(outbound) - 1, "outbound_idx")
    return_idx = model.NewIntVar(0, len(returning) - 1, "return_idx")

    attr_vars = [model.NewIntVar(0, len(attractions), f"attr_{i}") for i in range(len(attr_slots))]
    rest_vars = [model.NewIntVar(1, len(restaurants), f"rest_{i}") for i in range(len(meal_slots))]
    attr_eq = _equality_bools(model, attr_vars, len(attractions), "attr_eq")
    rest_eq = _equality_bools(model, rest_vars, len(restaurants), "rest_eq")
    selected_attr_bools = []
    for i, var in enumerate(attr_vars):
        selected = model.NewBoolVar(f"attr_selected_{i}")
        model.Add(var != 0).OnlyEnforceIf(selected)
        model.Add(var == 0).OnlyEnforceIf(selected.Not())
        selected_attr_bools.append(selected)

    _constrain_intercity_timing(model, outbound_idx, return_idx, outbound, returning, attr_slots, meal_slots)
    _constrain_required_hotel(model, hotel_idx, hotels)
    _constrain_slot_domains(model, attr_vars, rest_vars, attr_eq, rest_eq, attractions, restaurants, attr_slots, meal_slots, constraints, agent)
    _constrain_required_pois(model, attr_eq, rest_eq, attractions, restaurants, attr_vars, rest_vars, constraints, agent)
    _constrain_no_duplicates(model, attr_eq, rest_eq, attr_vars, rest_vars, len(attractions), len(restaurants))

    total_cost, selected_restaurant_count = _constrain_budgets(
        cp_model,
        model,
        constraints,
        people,
        hotel_idx,
        outbound_idx,
        return_idx,
        attr_vars,
        rest_vars,
        hotels,
        outbound,
        returning,
        attractions,
        restaurants,
    )
    total_cost_yuan = model.NewIntVar(0, 10**7, "total_cost_yuan")
    model.AddDivisionEquality(total_cost_yuan, total_cost, 100)
    model.Maximize(1000 * sum(selected_attr_bools) + 100 * selected_restaurant_count - total_cost_yuan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, float(time_limit_sec))
    cp_workers = int(os.environ.get("TPC_CP_SEARCH_WORKERS", "1"))
    solver.parameters.num_search_workers = max(1, cp_workers)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignment = {
        "hotel": hotels[solver.Value(hotel_idx)],
        "outbound": outbound[solver.Value(outbound_idx)],
        "return": returning[solver.Value(return_idx)],
        "attrs": [solver.Value(v) - 1 for v in attr_vars],
        "rests": [solver.Value(v) - 1 for v in rest_vars],
        "attr_slots": attr_slots,
        "meal_slots": meal_slots,
        "visit_minutes": visit_minutes,
    }
    plan = _reconstruct_plan(agent, query, constraints, ctx, assignment)
    if plan is None:
        return None
    try:
        passed, total = check(plan)
    except Exception:
        return None
    return plan if passed == total else None


def _equality_bools(model, vars_: list, candidate_count: int, prefix: str) -> dict[tuple[int, int], Any]:
    out = {}
    for slot_idx, var in enumerate(vars_):
        for value in range(1, candidate_count + 1):
            b = model.NewBoolVar(f"{prefix}_{slot_idx}_{value}")
            model.Add(var == value).OnlyEnforceIf(b)
            model.Add(var != value).OnlyEnforceIf(b.Not())
            out[(slot_idx, value)] = b
    return out


def _constrain_intercity_timing(model, outbound_idx, return_idx, outbound: list[dict], returning: list[dict], attr_slots: list[dict], meal_slots: list[dict]) -> None:
    first_start = min([s["start_min"] for s in attr_slots + meal_slots if s["day"] == 1], default=14 * 60)
    final_day = max([s["day"] for s in attr_slots + meal_slots], default=1)
    final_end = max([s["end_min"] for s in attr_slots + meal_slots if s["day"] == final_day], default=13 * 60)
    out_end = model.NewIntVar(0, 24 * 60, "outbound_end")
    ret_begin = model.NewIntVar(0, 24 * 60, "return_begin")
    model.AddElement(outbound_idx, [int(x["end_min"]) for x in outbound], out_end)
    model.AddElement(return_idx, [int(x["begin_min"]) for x in returning], ret_begin)
    model.Add(out_end <= first_start)
    model.Add(ret_begin >= final_end)


def _constrain_required_hotel(model, hotel_idx, hotels: list[dict]) -> None:
    required = [i for i, hotel in enumerate(hotels) if hotel.get("required")]
    if not required:
        return
    model.AddAllowedAssignments([hotel_idx], [[i] for i in required])


def _constrain_slot_domains(model, attr_vars, rest_vars, attr_eq, rest_eq, attractions, restaurants, attr_slots, meal_slots, constraints, agent) -> None:
    for slot_index, slot in enumerate(attr_slots):
        for cand_index, attr in enumerate(attractions, start=1):
            if not _attraction_allowed_in_slot(agent, attr, slot, constraints):
                model.Add(attr_vars[slot_index] != cand_index)
    for slot_index, slot in enumerate(meal_slots):
        for cand_index, rest in enumerate(restaurants, start=1):
            if not _restaurant_allowed_in_slot(rest, slot):
                model.Add(rest_vars[slot_index] != cand_index)


def _constrain_required_pois(model, attr_eq, rest_eq, attractions, restaurants, attr_vars, rest_vars, constraints, agent) -> None:
    required_attractions = constraints.get("required_attractions", []) or []
    for req in required_attractions:
        matches = [
            attr_eq[(slot, idx + 1)]
            for slot in range(len(attr_vars))
            for idx, attr in enumerate(attractions)
            if agent._match_constraint_text(attr.get("name", ""), req)
        ]
        if matches:
            model.Add(sum(matches) >= 1)

    for req_type in constraints.get("required_attraction_types", []) or []:
        matches = [
            attr_eq[(slot, idx + 1)]
            for slot in range(len(attr_vars))
            for idx, attr in enumerate(attractions)
            if agent._match_type(attr.get("type", ""), req_type)
        ]
        if matches:
            model.Add(sum(matches) >= 1)

    required_restaurants = constraints.get("required_restaurants", []) or []
    for req in required_restaurants:
        matches = [
            rest_eq[(slot, idx + 1)]
            for slot in range(len(rest_vars))
            for idx, rest in enumerate(restaurants)
            if agent._match_constraint_text(rest.get("name", ""), req)
        ]
        if matches:
            model.Add(sum(matches) >= 1)

    cuisine_preferences = _as_list(constraints.get("cuisine_preference"))
    for cuisine in cuisine_preferences:
        matches = [
            rest_eq[(slot, idx + 1)]
            for slot in range(len(rest_vars))
            for idx, rest in enumerate(restaurants)
            if agent._match_constraint_text(rest.get("cuisine", ""), cuisine)
        ]
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


def _constrain_budgets(cp_model, model, constraints, people: int, hotel_idx, outbound_idx, return_idx, attr_vars, rest_vars, hotels, outbound, returning, attractions, restaurants):
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
    accommodation = hotel_cost
    intercity = out_cost + ret_cost
    total = sightseeing + dining + accommodation + intercity
    budgets = constraints.get("budgets") if isinstance(constraints.get("budgets"), dict) else {}
    for key, expr in (
        ("sightseeing", sightseeing),
        ("dining", dining),
        ("accommodation", accommodation),
        ("intercity_transport", intercity),
        ("total", total),
    ):
        if key in budgets:
            model.Add(expr <= _budget_cents(budgets[key]))
    # Inner transport is checked during reconstruction with the real checker; it
    # depends on selected transition modes and exact departure times.
    selected_restaurant_count = len(rest_vars)
    return total, selected_restaurant_count


def _reconstruct_plan(agent, query: dict, constraints: dict, ctx: dict, assignment: dict) -> dict | None:
    people = ctx["people"]
    days = ctx["days"]
    city = ctx["target_city"]
    hotel = assignment["hotel"]
    hotel_name = str(hotel["name"])
    outbound = assignment["outbound"]
    returning = assignment["return"]
    attr_by_slot = assignment["attrs"]
    rest_by_slot = assignment["rests"]
    attr_slots = assignment["attr_slots"]
    meal_slots = assignment["meal_slots"]
    attractions = ctx["attractions"]
    restaurants = ctx["restaurants"]

    selected_points = [city, hotel_name]
    selected_points.extend(attractions[i]["name"] for i in attr_by_slot if i >= 0)
    selected_points.extend(restaurants[i]["name"] for i in rest_by_slot if i >= 0)
    build_transition_cache(agent, city, selected_points, people, ("walk",))

    old_transport_constraints = getattr(agent, "_transport_constraints", {})
    old_budget_limits = getattr(agent, "_budget_limits", {})
    old_timing = getattr(agent, "_active_timing_constraints", [])
    old_forced = getattr(agent, "_forced_inner_mode", None)
    agent._transport_constraints = constraints
    agent._budget_limits = agent._extract_budget_limits(constraints)
    agent._active_timing_constraints = constraints.get("timing_constraints", []) or []
    agent._forced_inner_mode = None
    try:
        itinerary = []
        attr_cursor = 0
        meal_cursor = 0
        current_pos = None
        current_time = "00:00"
        for day in range(1, days + 1):
            activities = []
            if day == 1:
                out_act = agent._make_intercity_activity(outbound, people)
                activities.append(out_act)
                current_pos = out_act["end"]
                current_time = out_act["end_time"]
            else:
                current_pos = hotel_name
                current_time = "08:00"
                activities.append(agent._make_hotel_breakfast(hotel_name, "08:00", "09:00"))
                current_time = "09:00"

            day_events = []
            while meal_cursor < len(meal_slots) and meal_slots[meal_cursor]["day"] == day:
                idx = rest_by_slot[meal_cursor]
                if idx >= 0:
                    slot = meal_slots[meal_cursor]
                    day_events.append((slot["start_min"], "meal", slot, restaurants[idx]))
                meal_cursor += 1
            while attr_cursor < len(attr_slots) and attr_slots[attr_cursor]["day"] == day:
                idx = attr_by_slot[attr_cursor]
                if idx >= 0:
                    slot = attr_slots[attr_cursor]
                    day_events.append((slot["start_min"], "attraction", slot, attractions[idx]))
                attr_cursor += 1
            day_events.sort(key=lambda x: x[0])

            for _start, kind, slot, item in day_events:
                start_time = minutes_to_time(slot["start_min"])
                end_time = minutes_to_time(slot["end_min"])
                if time_to_minutes(current_time) > slot["start_min"]:
                    return None
                transports, arrival = agent._get_transport(agent.env, city, current_pos, item["name"], current_time, people)
                if transports is None or arrival is None or time_to_minutes(arrival) > slot["start_min"]:
                    return None
                if kind == "meal":
                    activities.append(agent._make_meal_activity(slot["meal_type"], item, people, start_time, end_time, transports))
                else:
                    activities.append(agent._make_attraction_activity(item, people, start_time, end_time, transports))
                current_pos = item["name"]
                current_time = end_time

            if day < days:
                check_in_floor = max(time_to_minutes(current_time), 20 * 60)
                if check_in_floor >= 24 * 60:
                    return None
                check_in = minutes_to_time(check_in_floor)
                transports, arrival = agent._get_transport(agent.env, city, current_pos, hotel_name, current_time, people)
                if transports is None or arrival is None or time_to_minutes(arrival) > time_to_minutes(check_in):
                    return None
                activities.append(agent._make_accommodation_activity(hotel, int(hotel["rooms"]), check_in, transports))
                current_pos = hotel_name
                current_time = "24:00"
            else:
                if time_to_minutes(current_time) > int(returning["begin_min"]):
                    return None
                transports, arrival = agent._get_transport(agent.env, city, current_pos, returning["From"], current_time, people)
                if transports is None or arrival is None or time_to_minutes(arrival) > int(returning["begin_min"]):
                    return None
                activities.append(agent._make_intercity_activity(returning, people, transports))

            itinerary.append({"day": day, "activities": activities})
        return {
            "people_number": people,
            "start_city": query.get("start_city", ""),
            "target_city": city,
            "itinerary": itinerary,
        }
    finally:
        agent._transport_constraints = old_transport_constraints
        agent._budget_limits = old_budget_limits
        agent._active_timing_constraints = old_timing
        agent._forced_inner_mode = old_forced


def _attribute_slots(days: int, attr_slots_per_day: int, visit_minutes: int) -> list[dict]:
    slots = []
    for day in range(1, days + 1):
        starts = [14 * 60, 16 * 60, 19 * 60 + 30] if day == 1 else [9 * 60 + 30, 14 * 60, 16 * 60, 19 * 60 + 30]
        if day == days:
            starts = [9 * 60 + 30, 13 * 60 + 30, 15 * 60]
        for start in starts[:attr_slots_per_day]:
            end = start + visit_minutes
            if end <= 22 * 60:
                slots.append({"day": day, "start_min": start, "end_min": end})
    return slots


def _meal_slots(days: int) -> list[dict]:
    slots = []
    for day in range(1, days + 1):
        slots.append({"day": day, "meal_type": "lunch", "start_min": 12 * 60, "end_min": 13 * 60})
        if day < days:
            slots.append({"day": day, "meal_type": "dinner", "start_min": 18 * 60, "end_min": 19 * 60})
    return slots


def _visit_minutes(constraints: dict) -> int:
    longest = 90
    for item in constraints.get("stay_duration", []) or []:
        if isinstance(item, dict):
            try:
                longest = max(longest, int(item.get("min_minutes", 0)))
            except Exception:
                pass
    return min(240, max(90, longest))


def _attraction_allowed_in_slot(agent, attr: dict, slot: dict, constraints: dict) -> bool:
    if not _open_for(attr, slot["start_min"], slot["end_min"]):
        return False
    for window in constraints.get("activity_time_windows", []) or []:
        if not isinstance(window, dict) or not agent._match_constraint_text(attr.get("name", ""), window.get("location", "")):
            continue
        if window.get("earliest") and slot["start_min"] < time_to_minutes(str(window["earliest"])):
            return False
        if window.get("latest") and slot["start_min"] > time_to_minutes(str(window["latest"])):
            return False
        if window.get("end_after") and slot["end_min"] < time_to_minutes(str(window["end_after"])):
            return False
        if window.get("end_before") and slot["end_min"] > time_to_minutes(str(window["end_before"])):
            return False
    for duration in constraints.get("stay_duration", []) or []:
        if not isinstance(duration, dict) or not agent._match_constraint_text(attr.get("name", ""), duration.get("location", "")):
            continue
        try:
            if (slot["end_min"] - slot["start_min"]) < int(duration.get("min_minutes", 0)):
                return False
        except Exception:
            pass
    return True


def _restaurant_allowed_in_slot(rest: dict, slot: dict) -> bool:
    return _open_for(rest, slot["start_min"], slot["end_min"])


def _open_for(item: dict, start_min: int, end_min: int) -> bool:
    open_min = item.get("open_min")
    close_min = item.get("close_min")
    if open_min is None or close_min is None:
        return False
    if close_min <= open_min:
        close_min += 24 * 60
        if start_min < open_min:
            start_min += 24 * 60
            end_min += 24 * 60
    return int(open_min) <= start_min and end_min <= int(close_min)


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
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]
