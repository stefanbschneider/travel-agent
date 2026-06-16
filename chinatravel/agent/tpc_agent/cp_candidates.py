"""Finite candidate extraction for the CP-SAT itinerary solver."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from agent.tpc_agent.tpc_agent import time_to_minutes


DEFAULT_CAPS = {"attractions": 60, "restaurants": 40, "hotels": 60}


def build_candidate_context(agent, query: dict, constraints: dict, caps: dict | None) -> dict:
    """Build deterministic CP-SAT candidate pools from full environment tables.

    The WorldEnv string interface paginates table output.  This function talks to
    the underlying tool objects and returns row dictionaries with normalized
    integer time/cost fields.  Required named candidates are never removed by a
    cap; required type/cuisine matches are also kept before optional cheapest
    candidates are appended.
    """

    env = getattr(agent, "env", None)
    if env is None:
        return _empty_context(query, constraints)

    caps = {**DEFAULT_CAPS, **(caps or {})}
    city = query.get("target_city", "")
    start_city = query.get("start_city", "")
    people = int(query.get("people_number", 1) or 1)
    days = int(query.get("days", 1) or 1)

    attractions = _attraction_candidates(agent, env, city, constraints, int(caps["attractions"]))
    restaurants = _restaurant_candidates(agent, env, city, constraints, int(caps["restaurants"]))
    hotels = _hotel_candidates(agent, env, city, people, days, constraints, int(caps["hotels"]))
    outbound, returning = _intercity_candidates(agent, env, start_city, city, constraints)

    points = _candidate_points(start_city, city, attractions, restaurants, hotels, outbound, returning)
    return {
        "people": people,
        "days": days,
        "start_city": start_city,
        "target_city": city,
        "constraints": constraints,
        "attractions": attractions,
        "restaurants": restaurants,
        "hotels": hotels,
        "outbound_intercity": outbound,
        "return_intercity": returning,
        "points": points,
    }


def _empty_context(query: dict, constraints: dict) -> dict:
    return {
        "people": int(query.get("people_number", 1) or 1),
        "days": int(query.get("days", 1) or 1),
        "start_city": query.get("start_city", ""),
        "target_city": query.get("target_city", ""),
        "constraints": constraints,
        "attractions": [],
        "restaurants": [],
        "hotels": [],
        "outbound_intercity": [],
        "return_intercity": [],
        "points": [],
    }


def _attraction_candidates(agent, env, city: str, constraints: dict, cap: int) -> list[dict]:
    df = _select_all(env.attractions, city, "id")
    if df.empty:
        return []

    required_names = agent._resolve_required_names(
        constraints.get("required_attractions", []) or [], [str(v) for v in df["name"].tolist()]
    )
    required_types = _as_list(constraints.get("required_attraction_types"))
    excluded_names = _as_list(constraints.get("excluded_attractions"))
    excluded_types = _as_list(constraints.get("excluded_attraction_types"))
    free_only = bool(constraints.get("free_attractions_only", False))

    required_rows: list[dict] = []
    optional_rows: list[dict] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        item = row.to_dict()
        name = str(item.get("name", ""))
        attr_type = str(item.get("type", ""))
        if not name:
            continue
        if excluded_names and any(agent._match_constraint_text(name, ex) for ex in excluded_names):
            continue
        if excluded_types and any(agent._match_type(attr_type, ex) or agent._match_constraint_text(attr_type, ex) for ex in excluded_types):
            continue
        if free_only and _float(item.get("price"), 0.0) > 0.0:
            continue
        key = agent._norm_text(name)
        if key in seen:
            continue
        seen.add(key)
        required = bool(required_names and any(agent._match_constraint_text(name, req) for req in required_names))
        type_match = bool(required_types and any(agent._match_type(attr_type, req) for req in required_types))
        normalized = _normalize_attraction(item, required=required, type_match=type_match)
        if required or type_match:
            required_rows.append(normalized)
        else:
            optional_rows.append(normalized)

    optional_rows.sort(key=lambda x: (x["price_cents"], x["name"]))
    return required_rows + optional_rows[: max(0, cap - len(required_rows))]


def _restaurant_candidates(agent, env, city: str, constraints: dict, cap: int) -> list[dict]:
    df = _select_all(env.restaurants, city, "id")
    if df.empty:
        return []

    required_names = agent._resolve_required_names(
        constraints.get("required_restaurants", []) or [], [str(v) for v in df["name"].tolist()]
    )
    cuisine_preferences = _as_list(constraints.get("cuisine_preference"))
    excluded_names = _as_list(constraints.get("excluded_restaurants"))
    excluded_cuisines = _as_list(constraints.get("excluded_cuisine_types"))

    required_rows: list[dict] = []
    optional_rows: list[dict] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        item = row.to_dict()
        name = str(item.get("name", ""))
        cuisine = str(item.get("cuisine", ""))
        if not name:
            continue
        if excluded_names and any(agent._match_constraint_text(name, ex) for ex in excluded_names):
            continue
        if excluded_cuisines and any(agent._match_constraint_text(cuisine, ex) for ex in excluded_cuisines):
            continue
        key = agent._norm_text(name)
        if key in seen:
            continue
        seen.add(key)
        required = bool(required_names and any(agent._match_constraint_text(name, req) for req in required_names))
        cuisine_match = bool(cuisine_preferences and any(agent._match_constraint_text(cuisine, pref) for pref in cuisine_preferences))
        normalized = _normalize_restaurant(item, required=required, cuisine_match=cuisine_match)
        if required or cuisine_match:
            required_rows.append(normalized)
        else:
            optional_rows.append(normalized)

    optional_rows.sort(key=lambda x: (x["price_cents"], x["name"]))
    return required_rows + optional_rows[: max(0, cap - len(required_rows))]


def _hotel_candidates(agent, env, city: str, people: int, days: int, constraints: dict, cap: int) -> list[dict]:
    df = _select_all(env.accommodations, city, "id")
    if df.empty:
        return []

    required_names = agent._resolve_required_names(
        constraints.get("required_hotels", []) or [], [str(v) for v in df["name"].tolist()]
    )
    excluded_names = _as_list(constraints.get("excluded_hotels"))
    any_types = _as_list(constraints.get("required_hotel_any_types"))
    all_types = _as_list(constraints.get("required_hotel_all_types"))
    room_numbed = agent._room_type_to_numbed(constraints.get("room_type"))
    nearby_names = _nearby_hotel_names(env, city, constraints)

    required_rows: list[dict] = []
    optional_rows: list[dict] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        item = row.to_dict()
        name = str(item.get("name", ""))
        feature = str(item.get("featurehoteltype", ""))
        if not name:
            continue
        if required_names and not any(agent._match_constraint_text(name, req) for req in required_names):
            continue
        if excluded_names and any(agent._match_constraint_text(name, ex) for ex in excluded_names):
            continue
        if room_numbed is not None and int(_float(item.get("numbed"), -1)) != int(room_numbed):
            continue
        if all_types and any(not agent._match_constraint_text(feature, req) for req in all_types):
            continue
        if any_types and not any(agent._match_constraint_text(feature, req) for req in any_types):
            continue
        if nearby_names is not None and name not in nearby_names:
            continue
        key = agent._norm_text(name)
        if key in seen:
            continue
        seen.add(key)
        required = bool(required_names and any(agent._match_constraint_text(name, req) for req in required_names))
        normalized = _normalize_hotel(item, people, days, required=required)
        if required:
            required_rows.append(normalized)
        else:
            optional_rows.append(normalized)

    optional_rows.sort(key=lambda x: (x["total_cost_cents"], x["name"]))
    return required_rows + optional_rows[: max(0, cap - len(required_rows))]


def _nearby_hotel_names(env, city: str, constraints: dict) -> set[str] | None:
    specs = []
    if isinstance(constraints.get("hotel_nearby"), dict):
        specs.append(constraints["hotel_nearby"])
    specs.extend([x for x in _as_list(constraints.get("poi_distance_hotel")) if isinstance(x, dict)])
    if not specs:
        return None

    allowed: set[str] | None = None
    for spec in specs:
        ref = spec.get("reference")
        if not ref:
            continue
        dist = _float(spec.get("distance_km"), 5.0)
        try:
            near = env.accommodations.nearby(city, ref, topk=None, dist=dist)
        except Exception:
            near = None
        if near is None or isinstance(near, str) or len(near) == 0:
            names = set()
        else:
            names = {str(v) for v in near["name"].tolist()}
        allowed = names if allowed is None else allowed & names
    return allowed


def _intercity_candidates(agent, env, start_city: str, target_city: str, constraints: dict) -> tuple[list[dict], list[dict]]:
    mode = constraints.get("intercity_mode") if isinstance(constraints, dict) else None
    outbound_modes = _direction_modes(mode, "outbound")
    return_modes = _direction_modes(mode, "return")
    outbound = _intercity_direction(agent, env, start_city, target_city, outbound_modes)
    returning = _intercity_direction(agent, env, target_city, start_city, return_modes)
    return outbound, returning


def _direction_modes(mode: Any, direction: str) -> list[str]:
    if isinstance(mode, dict) and mode.get(direction):
        text = str(mode[direction]).lower()
        return ["airplane" if text in ("airplane", "flight", "plane") else "train"]
    if isinstance(mode, str) and mode:
        text = mode.lower()
        return ["airplane" if text in ("airplane", "flight", "plane") else "train"]
    return ["airplane", "train"]


def _intercity_direction(agent, env, from_city: str, to_city: str, modes: list[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for mode in modes:
        try:
            df = env.intercitytransport.select(from_city, to_city, mode, "00:00")
        except Exception:
            df = None
        if df is None or isinstance(df, str) or len(df) == 0:
            continue
        for _, row in df.iterrows():
            item = row.to_dict()
            key = (mode, str(item.get("FlightID", item.get("TrainID", len(rows)))))
            if key in seen:
                continue
            seen.add(key)
            rows.append(_normalize_intercity(item, mode))
    rows.sort(key=lambda x: (x["begin_min"], x["cost_cents"], x.get("TrainID", x.get("FlightID", ""))))
    return rows


def _candidate_points(start_city: str, target_city: str, attractions: list[dict], restaurants: list[dict], hotels: list[dict], outbound: list[dict], returning: list[dict]) -> list[str]:
    points: list[str] = []
    for value in (start_city, target_city):
        _append_point(points, value)
    for rows, field in ((attractions, "name"), (restaurants, "name"), (hotels, "name")):
        for row in rows:
            _append_point(points, row.get(field))
    for rows in (outbound, returning):
        for row in rows:
            _append_point(points, row.get("From"))
            _append_point(points, row.get("To"))
    return points


def _append_point(points: list[str], value: Any) -> None:
    text = str(value).strip() if value is not None else ""
    if text and text not in points:
        points.append(text)


def _normalize_attraction(item: dict, required: bool, type_match: bool) -> dict:
    item = dict(item)
    item["name"] = str(item.get("name", ""))
    item["type"] = str(item.get("type", ""))
    item["open_min"] = _time_or_none(item.get("opentime"))
    item["close_min"] = _time_or_none(item.get("endtime"))
    item["price_cents"] = _cents(item.get("price"))
    item["required"] = bool(required)
    item["type_match"] = bool(type_match)
    return item


def _normalize_restaurant(item: dict, required: bool, cuisine_match: bool) -> dict:
    item = dict(item)
    item["name"] = str(item.get("name", ""))
    item["cuisine"] = str(item.get("cuisine", ""))
    item["open_min"] = _time_or_none(item.get("opentime"))
    item["close_min"] = _time_or_none(item.get("endtime"))
    item["price_cents"] = _cents(item.get("price"))
    item["required"] = bool(required)
    item["cuisine_match"] = bool(cuisine_match)
    return item


def _normalize_hotel(item: dict, people: int, days: int, required: bool) -> dict:
    item = dict(item)
    item["name"] = str(item.get("name", ""))
    item["featurehoteltype"] = str(item.get("featurehoteltype", ""))
    numbed = max(1, int(_float(item.get("numbed"), 1)))
    rooms = max(1, math.ceil(people / numbed))
    item["numbed"] = numbed
    item["rooms"] = rooms
    item["price_cents"] = _cents(item.get("price"))
    item["total_cost_cents"] = item["price_cents"] * rooms * max(days - 1, 0)
    item["required"] = bool(required)
    return item


def _normalize_intercity(item: dict, mode: str) -> dict:
    item = dict(item)
    item["mode"] = mode
    item["begin_min"] = _time_or_none(item.get("BeginTime")) or 0
    item["end_min"] = _time_or_none(item.get("EndTime")) or 0
    item["cost_cents"] = _cents(item.get("Cost"))
    return item


def _select_all(tool, city: str, key: str) -> pd.DataFrame:
    try:
        df = tool.select(city, key, lambda _value: True)
    except Exception:
        return pd.DataFrame()
    if df is None or isinstance(df, str):
        return pd.DataFrame()
    return df.reset_index(drop=True)


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


def _time_or_none(value: Any) -> int | None:
    try:
        text = str(value)
        if not text or text.lower() == "nan" or text == "不营业":
            return None
        if text == "24:00":
            return 24 * 60
        return time_to_minutes(text)
    except Exception:
        return None


def _float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except Exception:
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _cents(value: Any) -> int:
    return int(round(_float(value, 0.0) * 100))
