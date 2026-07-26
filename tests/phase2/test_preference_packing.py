"""Focused tests for Task 3 preference packing flags.

These use a bare ``TPCAgent`` instance plus a monkeypatched candidate-context module, so they
exercise only the accepted-plan packing logic. The library floor must stay byte-identical when the
new flags are off.
"""

from __future__ import annotations

import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent, minutes_to_time, time_to_minutes  # noqa: E402


QUERY = {"target_city": "Testopolis", "people_number": 1}


def _row(name, *, lat, lon, price_cents=0, open_min=0, close_min=24 * 60):
    return {
        "name": name,
        "price_cents": price_cents,
        "price": price_cents,
        "lat": lat,
        "lon": lon,
        "open_min": open_min,
        "close_min": close_min,
    }


def _leg(frm, to, depart, arrive, mode, *, price=0, cost=0):
    return [{
        "start": frm,
        "end": to,
        "mode": mode,
        "start_time": depart,
        "end_time": arrive,
        "distance": 1000,
        "price": price,
        "cost": cost,
    }]


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = object()
    agent.solve_budget_sec = 10_000.0
    agent.start_clock = 0.0
    agent._transport_constraints = {}
    agent._forced_inner_mode = None
    agent._budget_limits = {}
    agent._schema = {}
    durations = {"walk": 8, "metro": 5, "taxi": 3}
    prices = {"walk": 0, "metro": 2, "taxi": 9}

    def fake_get_transport(env, city, from_pos, to_pos, start_time, people):
        if from_pos == to_pos:
            return [], start_time
        mode = getattr(agent, "_forced_inner_mode", None) or "metro"
        end_min = time_to_minutes(start_time) + durations[mode]
        end_time = minutes_to_time(end_min)
        price = prices[mode]
        return _leg(from_pos, to_pos, start_time, end_time, mode, price=price, cost=price * people), end_time

    agent._get_transport = fake_get_transport
    return agent


def _install_candidate_context(monkeypatch, *, attractions=None, restaurants=None, hotels=None):
    module = types.SimpleNamespace(
        build_candidate_context=lambda *args, **kwargs: {
            "attractions": list(attractions or []),
            "restaurants": list(restaurants or []),
            "hotels": list(hotels or []),
        }
    )
    monkeypatch.setitem(sys.modules, "agent.tpc_agent.cp_candidates", module)


def _accepted_check(plan):
    return (1, 1)


def _base_plan():
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "attraction",
                        "position": "Museum",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "price": 0,
                        "cost": 0,
                        "tickets": 1,
                        "transports": [],
                    },
                    {
                        "type": "lunch",
                        "position": "Cafe",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "price": 20,
                        "cost": 20,
                        "tickets": 1,
                        "transports": _leg("Museum", "Cafe", "10:30", "10:35", "metro", price=2, cost=2),
                    },
                    {
                        "type": "attraction",
                        "position": "Gallery",
                        "start_time": "15:00",
                        "end_time": "16:00",
                        "price": 0,
                        "cost": 0,
                        "tickets": 1,
                        "transports": _leg("Cafe", "Gallery", "13:30", "13:35", "metro", price=2, cost=2),
                    },
                ],
            }
        ]
    }


def _meal_gap_plan():
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "lunch",
                        "position": "Cafe",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "price": 20,
                        "cost": 20,
                        "tickets": 1,
                        "transports": [],
                    },
                    {
                        "type": "accommodation",
                        "position": "Hotel Alpha",
                        "start_time": "21:00",
                        "end_time": "24:00",
                        "price": 100,
                        "cost": 100,
                        "tickets": 1,
                        "transports": _leg("Cafe", "Hotel Alpha", "20:30", "20:35", "metro", price=2, cost=2),
                    },
                ],
            }
        ]
    }


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("TPC_PACK_DAV", "TPC_PACK_DDR", "TPC_PACK_HOTEL_BREAKFAST"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("flag_name", ["TPC_PACK_DAV", "TPC_PACK_DDR", "TPC_PACK_HOTEL_BREAKFAST"])
def test_pack_flags_off_are_byte_identical(monkeypatch, flag_name):
    agent = _bare_agent()
    plan = _base_plan()
    snapshot = deepcopy(plan)
    monkeypatch.setenv(flag_name, "0")
    agent._build_plan = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_build_plan should not run"))
    agent._densify_plan = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_densify_plan should not run"))

    packed = agent._pack_plan(plan, QUERY, {}, _accepted_check, {})

    assert packed == snapshot


def test_pack_dav_commits_one_attraction_and_reroutes_with_fastest_mode(monkeypatch):
    monkeypatch.setenv("TPC_PACK_DAV", "1")
    agent = _bare_agent()
    plan = _base_plan()
    _install_candidate_context(
        monkeypatch,
        attractions=[_row("Botanical Garden", lat=0.0, lon=0.02)],
        restaurants=[],
        hotels=[_row("Hotel Alpha", lat=0.0, lon=0.03)],
    )
    agent._build_plan = lambda *args, **kwargs: deepcopy(plan)

    packed = agent._pack_plan(plan, QUERY, {}, _accepted_check, {})
    activities = packed["itinerary"][0]["activities"]

    assert [activity.get("position") for activity in activities] == [
        "Museum", "Botanical Garden", "Cafe", "Gallery"
    ]
    assert activities[1]["transports"][0]["mode"] == "taxi"
    assert activities[2]["transports"][0]["mode"] == "taxi"


def test_pack_dav_reverts_when_checker_stops_accepting(monkeypatch):
    monkeypatch.setenv("TPC_PACK_DAV", "1")
    agent = _bare_agent()
    plan = _base_plan()
    snapshot = deepcopy(plan)
    _install_candidate_context(monkeypatch, attractions=[_row("Botanical Garden", lat=0.0, lon=0.02)])
    agent._build_plan = lambda *args, **kwargs: deepcopy(plan)

    def check(candidate):
        attraction_count = sum(
            1
            for day in candidate.get("itinerary", [])
            for activity in day.get("activities", [])
            if activity.get("type") == "attraction"
        )
        return (1, 1) if attraction_count <= 2 else (0, 1)

    packed = agent._pack_plan(plan, QUERY, {}, check, {})

    assert packed == snapshot


def test_pack_dav_reverts_when_preference_key_regresses(monkeypatch):
    monkeypatch.setenv("TPC_PACK_DAV", "1")
    agent = _bare_agent()
    plan = _base_plan()
    snapshot = deepcopy(plan)
    _install_candidate_context(monkeypatch, attractions=[_row("Botanical Garden", lat=0.0, lon=0.02)])
    agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    agent._accepted_eval_key = lambda candidate: (
        -sum(len(day.get("activities", []) or []) for day in candidate.get("itinerary", []) or []),
        0.0,
        0.0,
        0.0,
    )

    packed = agent._pack_plan(plan, QUERY, {}, _accepted_check, {})

    assert packed == snapshot


def test_pack_ddr_inserts_missing_dinner_only_when_enabled(monkeypatch):
    plan = _meal_gap_plan()
    restaurants = [_row("Bistro", lat=0.0, lon=0.01, price_cents=30)]
    _install_candidate_context(monkeypatch, restaurants=restaurants, hotels=[_row("Hotel Alpha", lat=0.0, lon=0.03)])

    off_agent = _bare_agent()
    off_agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    off_result = off_agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})
    assert [activity.get("type") for activity in off_result["itinerary"][0]["activities"]] == [
        "lunch", "accommodation"
    ]

    monkeypatch.setenv("TPC_PACK_DDR", "1")
    on_agent = _bare_agent()
    on_agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    on_result = on_agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})
    assert [activity.get("type") for activity in on_result["itinerary"][0]["activities"]] == [
        "lunch", "dinner", "accommodation"
    ]
    assert on_result["itinerary"][0]["activities"][1]["position"] == "Bistro"


def test_hotel_breakfast_topup_requires_own_flag(monkeypatch):
    plan = _meal_gap_plan()
    _install_candidate_context(monkeypatch, hotels=[_row("Hotel Alpha", lat=0.0, lon=0.03)])

    agent = _bare_agent()
    agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    off_result = agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})
    assert sum(
        1
        for activity in off_result["itinerary"][0]["activities"]
        if activity.get("type") in ("breakfast", "lunch", "dinner")
    ) == 1

    monkeypatch.setenv("TPC_PACK_HOTEL_BREAKFAST", "1")
    agent = _bare_agent()
    agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    on_result = agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})
    activities = on_result["itinerary"][0]["activities"]
    breakfasts = [activity for activity in activities if activity.get("type") == "breakfast"]
    assert len(breakfasts) == 2
    assert all(activity.get("position") == "Hotel Alpha" for activity in breakfasts)
    assert sum(
        1
        for activity in activities
        if activity.get("type") in ("breakfast", "lunch", "dinner")
    ) == 3