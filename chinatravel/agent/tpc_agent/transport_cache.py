"""Pairwise inner-city transition cache for CP-SAT candidate routes."""

from __future__ import annotations

import math
from typing import Any

from agent.tpc_agent.tpc_agent import time_to_minutes


def build_transition_cache(agent, city: str, points: list[str], people: int, modes: tuple[str, ...]) -> dict:
    """Cache every ordered point-pair/mode transition once.

    ``Transportation.goto`` performs POI lookup, geodesic work, and for metro a
    nearest-station scan plus shortest-path search.  CP-SAT model construction
    consumes this precomputed table only; selected transitions are rebuilt later
    through ``agent._get_transport`` with real start times.
    """

    env = getattr(agent, "env", None)
    transportation = getattr(env, "transportation", None) if env is not None else None
    if transportation is None:
        return {"by_pair": {}, "by_pair_mode": {}}

    unique_points = _dedupe_points(points)
    allowed_modes = tuple(m for m in modes if m in ("walk", "metro", "taxi")) or ("metro", "walk", "taxi")
    by_pair: dict[tuple[str, str], list[dict]] = {}
    by_pair_mode: dict[tuple[str, str, str], dict] = {}
    for start in unique_points:
        for end in unique_points:
            pair = (start, end)
            options: list[dict] = []
            if start == end:
                entry = {
                    "start": start,
                    "end": end,
                    "mode": "walk",
                    "duration_minutes": 0,
                    "cost_cents": 0,
                    "distance": 0.0,
                    "segments": [],
                }
                options.append(entry)
                by_pair_mode[(start, end, "walk")] = entry
                by_pair[pair] = options
                continue
            for mode in allowed_modes:
                try:
                    raw = transportation.goto(city, start, end, "00:00", mode)
                except Exception:
                    raw = None
                entry = _transition_entry(raw, start, end, mode, people)
                if entry is None:
                    continue
                options.append(entry)
                by_pair_mode[(start, end, mode)] = entry
            if options:
                options.sort(key=lambda item: (item["cost_cents"], item["duration_minutes"], item["mode"]))
                by_pair[pair] = options
    return {"by_pair": by_pair, "by_pair_mode": by_pair_mode}


def _transition_entry(raw: Any, start: str, end: str, mode: str, people: int) -> dict | None:
    if not isinstance(raw, list) or len(raw) == 0:
        return None
    duration = 0
    cost_cents = 0
    distance = 0.0
    segments = []
    for seg in raw:
        if not isinstance(seg, dict):
            return None
        seg_start = str(seg.get("start_time", "00:00"))
        seg_end = str(seg.get("end_time", seg_start))
        duration += _duration_minutes(seg_start, seg_end)
        distance += _float(seg.get("distance"), 0.0)
        seg_mode = str(seg.get("mode", mode))
        base_cost = _float(seg.get("cost"), 0.0)
        if seg_mode == "taxi":
            cost = base_cost * max(1, int(math.ceil(float(people) / 4.0)))
        elif seg_mode == "metro":
            cost = base_cost * people
        else:
            cost = 0.0
        cost_cents += int(round(cost * 100))
        segments.append({
            "start": seg.get("start"),
            "end": seg.get("end"),
            "mode": seg_mode,
            "distance": seg.get("distance", 0),
            "cost": seg.get("cost", 0),
        })
    return {
        "start": start,
        "end": end,
        "mode": mode,
        "duration_minutes": max(0, duration),
        "cost_cents": cost_cents,
        "distance": distance,
        "segments": segments,
    }


def _duration_minutes(start: str, end: str) -> int:
    try:
        begin = _time_to_minutes(start)
        finish = _time_to_minutes(end)
    except Exception:
        return 0
    if finish < begin:
        finish += 24 * 60
    return max(0, finish - begin)


def _time_to_minutes(value: str) -> int:
    if value == "24:00":
        return 24 * 60
    return time_to_minutes(value)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _dedupe_points(points: list[str]) -> list[str]:
    seen = set()
    out = []
    for point in points or []:
        text = str(point).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
