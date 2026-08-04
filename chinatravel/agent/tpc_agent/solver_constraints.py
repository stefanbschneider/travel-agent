"""Branch-local constraint normalization for the TPC solver.

The public parser intentionally stays broad and NL-friendly.  CP-SAT needs the
opposite: small, branch-local, hard facts copied from the oracle DSL without
leaking one OR arm into another.  This module only recognizes the finite DSL
families emitted in the Phase-1 data; it does not execute hard_logic_py.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from chinatravel.environment.concept_labels import normalize_concept_value

_BRANCH_LOCAL_KEYS = {
    "required_attractions",
    "excluded_attractions",
    "required_restaurants",
    "excluded_restaurants",
    "required_hotels",
    "excluded_hotels",
    "required_attraction_types",
    "excluded_attraction_types",
    "cuisine_preference",
    "excluded_cuisine_types",
    "hotel_type",
    "hotel_amenity",
    "required_hotel_any_types",
    "required_hotel_all_types",
    "budgets",
    "free_attractions_only",
    "activity_time_windows",
    "stay_duration",
    "hotel_nearby",
    "poi_distance_hotel",
    "intercity_mode",
    "taxi_cars_equals",
    "excluded_inner_transport",
    "position_presence",
}

_LIST_KEYS = {
    "required_attractions",
    "excluded_attractions",
    "required_restaurants",
    "excluded_restaurants",
    "required_hotels",
    "excluded_hotels",
    "required_attraction_types",
    "excluded_attraction_types",
    "excluded_cuisine_types",
    "required_hotel_any_types",
    "required_hotel_all_types",
    "activity_time_windows",
    "stay_duration",
    "poi_distance_hotel",
    "excluded_inner_transport",
    "position_presence",
}

_BUDGET_FIELDS = (
    ("sightseeing", r"attraction_cost\s*<=\s*([-+]?\d+(?:\.\d+)?)"),
    ("accommodation", r"accommodation_cost\s*<=\s*([-+]?\d+(?:\.\d+)?)"),
    ("dining", r"restaurant_cost\s*<=\s*([-+]?\d+(?:\.\d+)?)"),
    ("intercity_transport", r"inter_city_transportation_cost\s*<=\s*([-+]?\d+(?:\.\d+)?)"),
    ("inner_transport", r"inner_city_transportation_cost\s*<=\s*([-+]?\d+(?:\.\d+)?)"),
    ("total", r"total_cost\s*<=\s*([-+]?\d+(?:\.\d+)?)"),
)
_INNER_TRANSPORT_MODES = {"walk", "metro", "taxi"}

# Concept-valued constraint keys, by the sandbox concept kind whose canonical labels they
# must be expressed in.  The English sandbox exposes one canonical label per concept
# (``chinatravel/environment/concept_labels.py``), and the verifier normalizes both the
# hard_logic_py literals (``normalize_concept_constraint_source``) and the values it reads
# back from the tools (``concept_func.normalize_concept_value``) into that same label.  The
# solver compares constraint values against tool column values with case-sensitive equality,
# so it has to canonicalize its own literals the same way or a query asking for
# "Art Museum" would match none of the attractions the verifier accepts as "Art museum".
_CONCEPT_VALUE_KEYS = {
    "attraction": ("required_attraction_types", "excluded_attraction_types"),
    "restaurant": ("cuisine_preference", "excluded_cuisine_types"),
    "accommodation": (
        "hotel_type",
        "hotel_amenity",
        "required_hotel_any_types",
        "required_hotel_all_types",
    ),
}



def solver_constraint_variants(query: dict, parsed_raw: dict, use_oracle: bool = True) -> list[dict]:
    """Return one normalized solver-constraint dict per OR branch.

    ``parsed_raw`` is the output of parse_constraints.parse_query*().  Oracle
    mode augments it from hard_logic_py.  If a result_list disjunction exists,
    hard-logic extraction is performed per branch snippet so constraints from
    one OR arm never contaminate another.
    """

    raw = parsed_raw if isinstance(parsed_raw, dict) else {}
    if not use_oracle:
        return [_normalize_variant(_base_from_raw(raw), use_oracle=False)]

    branch_texts = _hard_logic_branches(query)
    # In oracle mode, hard_logic_py is the source of truth for branch-local facts.
    # Raw NL parser outputs can contain tokenization noise (for example names with
    # apostrophes split into fragments), so drop branch-local keys and rehydrate
    # them from hard logic only.
    base_oracle = {k: v for k, v in _base_from_raw(raw).items() if k not in _BRANCH_LOCAL_KEYS}
    if branch_texts:
        variants = []
        raw_groups = raw.get("groups") if isinstance(raw.get("groups"), list) else []
        for index, branch in enumerate(branch_texts):
            merged = deepcopy(base_oracle)
            if index < len(raw_groups) and isinstance(raw_groups[index], dict):
                group = {k: v for k, v in raw_groups[index].items() if k not in _BRANCH_LOCAL_KEYS}
                _merge_into(merged, group, use_oracle=True)
            _merge_into(merged, _parse_logic_snippet(branch, include_inner_transport=True), use_oracle=True)
            variants.append(_normalize_variant(merged, use_oracle=True))
        return variants or [_normalize_variant(base_oracle, use_oracle=True)]

    merged = deepcopy(base_oracle)
    for expr in query.get("hard_logic_py", []) or []:
        if isinstance(expr, str):
            _merge_into(merged, _parse_logic_snippet(expr, include_inner_transport=True), use_oracle=True)
    return [_normalize_variant(merged, use_oracle=True)]


def _base_from_raw(raw: dict) -> dict:
    return deepcopy({k: v for k, v in raw.items() if k not in ("groups", "disjunctive")})


def _hard_logic_branches(query: dict) -> list[str]:
    branches: list[str] = []
    for expr in query.get("hard_logic_py", []) or []:
        if not isinstance(expr, str) or "result_list" not in expr:
            continue
        pieces = re.split(r"result_list\.append\(result\)", expr)
        for piece in pieces[:-1]:
            text = piece.strip()
            if not text:
                continue
            # Drop the initializer; keep all local loops and assignments.
            text = re.sub(r"^result_list\s*=\s*\[\]\s*", "", text).strip()
            if _looks_like_branch(text):
                branches.append(text)
    return branches


def _looks_like_branch(text: str) -> bool:
    if "for r in result_list" in text:
        return False
    return "result" in text or any(token in text for token in ("_set", "_cost", "activity_", "poi_distance"))


def _parse_logic_snippet(logic: str, include_inner_transport: bool) -> dict:
    result: dict[str, Any] = {}
    _parse_name_sets(logic, result)
    _parse_type_sets(logic, result)
    _parse_budgets(logic, result)
    _parse_intercity(logic, result)
    _parse_room_type(logic, result)
    _parse_hotel_distance(logic, result)
    _parse_activity_windows(logic, result)
    _parse_taxi_cars(logic, result)
    _parse_position_names(logic, result)
    if include_inner_transport:
        _parse_excluded_inner_transport(logic, result)
    return result


def _parse_name_sets(logic: str, result: dict[str, Any]) -> None:
    families = (
        ("attraction_name_set", "required_attractions", "excluded_attractions"),
        ("restaurant_name_set", "required_restaurants", "excluded_restaurants"),
        ("accommodation_name_set", "required_hotels", "excluded_hotels"),
    )
    for set_name, required_key, excluded_key in families:
        excluded = _set_literals_for(logic, set_name, excluded=True)
        if excluded:
            result[excluded_key] = excluded
            continue
        required = _set_literals_for(logic, set_name, excluded=False)
        if required:
            result[required_key] = required


def _parse_type_sets(logic: str, result: dict[str, Any]) -> None:
    excluded_attr = _set_literals_for(logic, "attraction_type_set", excluded=True)
    if excluded_attr:
        result["excluded_attraction_types"] = excluded_attr
    else:
        required_attr = _set_literals_for(logic, "attraction_type_set", excluded=False)
        if required_attr:
            result["required_attraction_types"] = required_attr

    excluded_cuisine = _set_literals_for(logic, "restaurant_type_set", excluded=True)
    if excluded_cuisine:
        result["excluded_cuisine_types"] = excluded_cuisine
    else:
        cuisine = _set_literals_for(logic, "restaurant_type_set", excluded=False)
        if cuisine:
            result["cuisine_preference"] = cuisine if len(cuisine) > 1 else cuisine[0]

    hotel_excluded = _set_literals_for(logic, "accommodation_type_set", excluded=True)
    if hotel_excluded:
        return
    for literals, op in _set_literal_ops(logic, "accommodation_type_set"):
        key = "required_hotel_all_types" if op == "<=" else "required_hotel_any_types"
        result.setdefault(key, [])
        result[key].extend(literals)


def _set_literals_for(logic: str, set_name: str, excluded: bool) -> list[str]:
    values: list[str] = []
    for literals, _op in _set_literal_ops(logic, set_name):
        start = logic.find("{")
        if start < 0:
            start = 0
        prefix = logic[max(0, start - 80):start]
        is_excluded = bool(re.search(r"not\s*\([^\n]*$", prefix)) or "result=not" in prefix.replace(" ", "")
        if is_excluded == excluded:
            values.extend(literals)
    return _dedupe(values)


def _set_literal_ops(logic: str, set_name: str) -> list[tuple[list[str], str]]:
    matches: list[tuple[list[str], str]] = []
    pattern = re.compile(r"\{([^{}]*)\}\s*(&|<=)\s*" + re.escape(set_name), re.DOTALL)
    for match in pattern.finditer(logic):
        literals = _extract_quoted_literals(match.group(1))
        if literals:
            matches.append((_dedupe(literals), match.group(2)))
    return matches


def _extract_quoted_literals(text: str) -> list[str]:
    """Extract quoted string literals while respecting quote type.

    This preserves apostrophes inside double-quoted values (for example
    "Cong's Restaurant"), which a naive quote-agnostic regex would split.
    """
    values: list[str] = []
    pattern = re.compile(r"(['\"])((?:\\.|(?!\1).)*)\1", re.DOTALL)
    for quote, raw in pattern.findall(text):
        value = raw.replace("\\" + quote, quote).replace("\\\\", "\\")
        if value.strip():
            values.append(value)
    return values


def _parse_budgets(logic: str, result: dict[str, Any]) -> None:
    budgets: dict[str, float] = {}
    for key, pattern in _BUDGET_FIELDS:
        match = re.search(pattern, logic)
        if not match:
            continue
        value = float(match.group(1))
        if key == "sightseeing" and value == 0:
            result["free_attractions_only"] = True
        else:
            budgets[key] = value
    if budgets:
        result["budgets"] = budgets


def _parse_intercity(logic: str, result: dict[str, Any]) -> None:
    intercity: dict[str, str] = {}
    first_type = _activity_type_constraint(logic, r"allactivities\(plan\)\[0\]")
    last_type = _activity_type_constraint(logic, r"allactivities\(plan\)\[-1\]")
    if first_type:
        intercity["outbound"] = first_type
    if last_type:
        intercity["return"] = last_type

    for field, side in (("intercity_transport_go", "outbound"), ("intercity_transport_back", "return")):
        for mode in ("train", "airplane"):
            if re.search(re.escape(field) + r"\s*==\s*['\"]" + mode + r"['\"]", logic):
                intercity[side] = mode
        if re.search(re.escape(field) + r"\s*!=\s*['\"]airplane['\"]", logic):
            intercity[side] = "train"
        if re.search(re.escape(field) + r"\s*!=\s*['\"]train['\"]", logic):
            intercity[side] = "airplane"

    if intercity:
        result["intercity_mode"] = intercity


def _activity_type_constraint(logic: str, activity_expr: str) -> str | None:
    for mode in ("train", "airplane"):
        if re.search(activity_expr + r"\['type'\]\s*==\s*['\"]" + mode + r"['\"]", logic):
            return mode
    if re.search(activity_expr + r"\['type'\]\s*!=\s*['\"]airplane['\"]", logic):
        return "train"
    if re.search(activity_expr + r"\['type'\]\s*!=\s*['\"]train['\"]", logic):
        return "airplane"
    return None


def _parse_room_type(logic: str, result: dict[str, Any]) -> None:
    match = re.search(r"room_type\(activity(?:,\s*target_city\(plan\))?\)\s*(?:==|!=)\s*(\d+)", logic)
    if not match:
        return
    room_num = int(match.group(1))
    # A full scan of every hard_logic_py in the dataset found only codes 1 and 2 ever appear, and
    # every NL query using code 2 says "twin" ("twin beds room" / "a twin room") -- never "double
    # bed". Code 3 is unobserved; kept mapped to "twin" too rather than left undefined, since
    # nothing distinguishes it from code 2 in the data we've seen.
    room_map = {1: "single", 2: "twin", 3: "twin"}
    result["room_type"] = room_map.get(room_num, room_num)


def _parse_hotel_distance(logic: str, result: dict[str, Any]) -> None:
    match = re.search(
        r"accommodation_distance\(activity,\s*['\"](.+)['\"],\s*target_city\(plan\)\)\s*<=\s*([\d.]+)",
        logic,
    )
    if match:
        result["hotel_nearby"] = {"reference": match.group(1), "distance_km": float(match.group(2))}

    match = re.search(
        r"poi_distance\(\s*target_city\(plan\)\s*,\s*['\"](.+)['\"]\s*,\s*accommodation_position\s*\)\s*<=\s*([\d.]+)",
        logic,
    )
    if match:
        item = {"reference": match.group(1), "distance_km": float(match.group(2))}
        result["hotel_nearby"] = item
        result.setdefault("poi_distance_hotel", []).append(item)


_ACTIVITY_POSITION_EQ_RE = re.compile(
    r"activity_position\(\s*activity\s*\)\s*==\s*"
    r"(?P<quote>['\"])(?P<location>[^\r\n]*?)(?P=quote)"
)


def _parse_activity_windows(logic: str, result: dict[str, Any]) -> None:
    positions = list(_ACTIVITY_POSITION_EQ_RE.finditer(logic))
    if not positions:
        return
    for idx, match in enumerate(positions):
        loc = match.group("location")
        end = positions[idx + 1].start() if idx + 1 < len(positions) else len(logic)
        block = logic[match.start():end]
        min_minutes = _duration_minutes(block)
        earliest, latest = _time_bounds(block, "activity_start_time")
        end_after, end_before = _time_bounds(block, "activity_end_time")
        if latest and end_after:
            span = _time_to_minutes(end_after) - _time_to_minutes(latest)
            if span > 0:
                min_minutes = max(min_minutes or 0, span)
        if min_minutes and min_minutes > 0:
            result.setdefault("stay_duration", []).append({"location": loc, "min_minutes": min_minutes})
        if earliest or latest or end_after or end_before:
            result.setdefault("activity_time_windows", []).append(
                {
                    "location": loc,
                    "earliest": earliest,
                    "latest": latest,
                    "end_after": end_after,
                    "end_before": end_before,
                }
            )


def _duration_minutes(block: str) -> int | None:
    match = re.search(r"activity_time\(activity\)\s*/\s*60\s*>=\s*(\d+(?:\.\d+)?)", block)
    if match:
        return int(round(float(match.group(1)) * 60))
    match = re.search(r"activity_time\(activity\)\s*>=\s*(\d+)", block)
    if match:
        return int(match.group(1))
    return None


def _time_bounds(block: str, func: str) -> tuple[str | None, str | None]:
    lower = upper = None
    pattern = re.compile(re.escape(func) + r"\(activity\)\s*([<>]=?)\s*['\"](\d{2}:\d{2})['\"]")
    for op, value in pattern.findall(block):
        if op.startswith(">"):
            lower = value if lower is None or _time_to_minutes(value) > _time_to_minutes(lower) else lower
        else:
            upper = value if upper is None or _time_to_minutes(value) < _time_to_minutes(upper) else upper
    return lower, upper


def _parse_taxi_cars(logic: str, result: dict[str, Any]) -> None:
    if "taxi_cars" not in logic:
        return
    match = re.search(r"taxi_cars\(activity_transports\(activity\)\)\s*(?:==|!=)\s*(\d+)", logic)
    if match:
        result["taxi_cars_equals"] = int(match.group(1))


def _parse_position_names(logic: str, result: dict[str, Any]) -> None:
    """Any POI referenced positively by activity_position(...)=='NAME' must be in
    the plan for the clause to pass, so record it as required presence (covers
    ordering and other position clauses, not just time windows)."""
    names = [match.group("location") for match in _ACTIVITY_POSITION_EQ_RE.finditer(logic)]
    if names:
        result.setdefault("position_presence", []).extend(names)


def _parse_excluded_inner_transport(logic: str, result: dict[str, Any]) -> None:
    excluded: list[str] = []
    for match in re.finditer(r"result\s*=\s*not\s*\(\s*\{([^{}]+)\}\s*(?:&|<=)\s*inner_city_transportation_set", logic, re.DOTALL):
        excluded.extend(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))

    for match in re.finditer(r"\{([^{}]+)\}\s*<=\s*inner_city_transportation_set", logic, re.DOTALL):
        prefix = logic[max(0, match.start() - 32):match.start()].replace(" ", "")
        if prefix.endswith("not(") or prefix.endswith("=not("):
            continue
        allowed = {m.strip().lower() for m in re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))}
        excluded.extend(sorted(_INNER_TRANSPORT_MODES - allowed))

    if excluded:
        result["excluded_inner_transport"] = excluded

def _normalize_variant(constraints: dict, use_oracle: bool) -> dict:
    normalized = deepcopy(constraints) if isinstance(constraints, dict) else {}
    for key in _LIST_KEYS:
        value = normalized.get(key)
        if value is None:
            continue
        if key in ("activity_time_windows", "stay_duration", "poi_distance_hotel"):
            normalized[key] = _dedupe_dicts(_as_list(value))
        else:
            normalized[key] = _dedupe([str(v) for v in _as_list(value) if str(v).strip()])

    cuisine = normalized.get("cuisine_preference")
    if isinstance(cuisine, tuple):
        normalized["cuisine_preference"] = list(cuisine)
    elif isinstance(cuisine, set):
        normalized["cuisine_preference"] = sorted(str(v) for v in cuisine)

    budgets = normalized.get("budgets")
    if isinstance(budgets, dict):
        normalized["budgets"] = {str(k): float(v) for k, v in budgets.items() if _is_number(v)}
    else:
        normalized.pop("budgets", None)

    _normalize_concept_values(normalized)
    _normalize_hotel_type(normalized)
    _normalize_intercity_mode(normalized)
    return normalized


def _normalize_concept_values(normalized: dict) -> None:
    """Rewrite concept-valued literals into the sandbox's canonical labels, mirroring the
    verifier's own normalization of hard_logic_py literals and tool column values."""
    for kind, keys in _CONCEPT_VALUE_KEYS.items():
        for key in keys:
            if key not in normalized:
                continue
            value = normalized[key]
            if isinstance(value, str):
                normalized[key] = normalize_concept_value(kind, value, "en")
            elif isinstance(value, list):
                normalized[key] = _dedupe(
                    normalize_concept_value(kind, v, "en") if isinstance(v, str) else v
                    for v in value
                )


def _normalize_hotel_type(normalized: dict) -> None:
    hotel_type = normalized.pop("hotel_type", None)
    if hotel_type:
        any_types = normalized.get("required_hotel_any_types")
        if not isinstance(any_types, list):
            any_types = []
        any_types.extend(str(v) for v in _as_list(hotel_type) if str(v).strip())
        normalized["required_hotel_any_types"] = _dedupe(any_types)
    for key in ("required_hotel_any_types", "required_hotel_all_types"):
        if key in normalized:
            normalized[key] = _dedupe(str(v) for v in _as_list(normalized[key]) if str(v).strip())


def _normalize_intercity_mode(normalized: dict) -> None:
    mode = normalized.get("intercity_mode")
    if isinstance(mode, str):
        normalized["intercity_mode"] = {"outbound": mode, "return": mode}
    elif isinstance(mode, dict):
        out = {}
        if mode.get("outbound"):
            out["outbound"] = str(mode["outbound"])
        if mode.get("return"):
            out["return"] = str(mode["return"])
        normalized["intercity_mode"] = out
    elif mode is not None:
        normalized.pop("intercity_mode", None)


def _merge_into(target: dict, source: dict | None, use_oracle: bool) -> None:
    if not isinstance(source, dict):
        return
    source = _normalize_variant(source, use_oracle=use_oracle)
    for key, value in source.items():
        if key == "budgets" and isinstance(value, dict):
            budgets = target.get("budgets") if isinstance(target.get("budgets"), dict) else {}
            budgets.update(value)
            target["budgets"] = budgets
        elif key == "intercity_mode" and isinstance(value, dict):
            intercity = target.get("intercity_mode") if isinstance(target.get("intercity_mode"), dict) else {}
            intercity.update(value)
            target["intercity_mode"] = intercity
        elif key in _LIST_KEYS:
            existing = _as_list(target.get(key))
            target[key] = existing + _as_list(value)
        else:
            target[key] = value


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


def _dedupe(values) -> list:
    seen = set()
    out = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _dedupe_dicts(values: list) -> list[dict]:
    seen = set()
    out = []
    for value in values:
        if not isinstance(value, dict):
            continue
        key = tuple(sorted((str(k), str(v)) for k, v in value.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _time_to_minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)
