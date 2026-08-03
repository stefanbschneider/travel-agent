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
    for name in ("TPC_PACK_DAV", "TPC_PACK_DDR", "TPC_PACK_HOTEL_BREAKFAST", "TPC_PACK_ATT"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "flag_name", ["TPC_PACK_DAV", "TPC_PACK_DDR", "TPC_PACK_HOTEL_BREAKFAST", "TPC_PACK_ATT"]
)
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

def _arrival_day_plan():
    """Day 1 of a real trip shape: an inbound intercity leg, then a 06:00--09:00 hole where the
    DDR top-up used to give up because it only ever tried lunch and dinner."""
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "train",
                        "start": "Origin Station",
                        "end": "Testopolis Station",
                        "TrainID": "G1",
                        "start_time": "02:00",
                        "end_time": "05:00",
                        "price": 100,
                        "cost": 100,
                        "tickets": 1,
                        "transports": [],
                    },
                    {
                        "type": "attraction",
                        "position": "Museum",
                        "start_time": "10:00",
                        "end_time": "11:00",
                        "price": 0,
                        "cost": 0,
                        "tickets": 1,
                        "transports": _leg(
                            "Testopolis Station", "Museum", "09:50", "09:55", "metro", price=2, cost=2
                        ),
                    },
                    {
                        "type": "lunch",
                        "position": "Cafe",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "price": 20,
                        "cost": 20,
                        "tickets": 1,
                        "transports": _leg("Museum", "Cafe", "11:30", "11:35", "metro", price=2, cost=2),
                    },
                    {
                        "type": "dinner",
                        "position": "Bistro",
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "price": 30,
                        "cost": 30,
                        "tickets": 1,
                        "transports": _leg("Cafe", "Bistro", "17:30", "17:35", "metro", price=2, cost=2),
                    },
                    {
                        "type": "accommodation",
                        "position": "Hotel Alpha",
                        "start_time": "21:00",
                        "end_time": "24:00",
                        "price": 100,
                        "cost": 100,
                        "tickets": 1,
                        "transports": _leg(
                            "Bistro", "Hotel Alpha", "20:30", "20:35", "metro", price=2, cost=2
                        ),
                    },
                ],
            }
        ]
    }


def test_pack_ddr_fills_an_arrival_day_breakfast_at_a_real_restaurant(monkeypatch):
    plan = _arrival_day_plan()
    _install_candidate_context(
        monkeypatch,
        restaurants=[_row("Morning Noodles", lat=0.0, lon=0.01, price_cents=15)],
        hotels=[_row("Hotel Alpha", lat=0.0, lon=0.03)],
    )

    off_agent = _bare_agent()
    off_agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    off_result = off_agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})
    assert not [
        activity
        for activity in off_result["itinerary"][0]["activities"]
        if activity.get("type") == "breakfast"
    ]

    monkeypatch.setenv("TPC_PACK_DDR", "1")
    on_agent = _bare_agent()
    on_agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    on_result = on_agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})

    activities = on_result["itinerary"][0]["activities"]
    breakfasts = [activity for activity in activities if activity.get("type") == "breakfast"]
    assert len(breakfasts) == 1
    breakfast = breakfasts[0]
    # A grounded, priced restaurant -- not the free hotel-breakfast variant, which keeps its own flag.
    assert breakfast["position"] == "Morning Noodles"
    assert breakfast["price"] == 15
    # Inside the evaluator's breakfast band and after the inbound leg lands.
    assert "05:00" <= breakfast["start_time"] < "09:00"
    assert breakfast["end_time"] <= "09:00"
    assert activities.index(breakfast) == 1


def _slow_walk_plan():
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
                        "transports": _leg("Museum", "Cafe", "10:00", "11:00", "walk"),
                    },
                ],
            }
        ]
    }


def _install_fast_taxi_env(agent):
    """Give the bare agent a ``transportation.goto`` so ``_rebuild_hop`` can find a faster mode."""

    def goto(city, from_pos, to_pos, start_time, mode):
        if mode != "taxi":
            return []
        end_min = time_to_minutes(start_time) + 5
        return [{
            "start": from_pos,
            "end": to_pos,
            "mode": "taxi",
            "start_time": start_time,
            "end_time": minutes_to_time(end_min),
            "distance": 3.0,
            "cost": 12,
        }]

    agent.env = types.SimpleNamespace(transportation=types.SimpleNamespace(goto=goto))


def test_pack_att_shortens_a_hop_without_changing_activity_counts(monkeypatch):
    plan = _slow_walk_plan()
    _install_candidate_context(monkeypatch)

    off_agent = _bare_agent()
    _install_fast_taxi_env(off_agent)
    off_agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    off_result = off_agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})
    assert off_result["itinerary"][0]["activities"][1]["transports"][0]["mode"] == "walk"

    monkeypatch.setenv("TPC_PACK_ATT", "1")
    on_agent = _bare_agent()
    _install_fast_taxi_env(on_agent)
    on_agent._build_plan = lambda *args, **kwargs: deepcopy(plan)
    on_result = on_agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})

    activities = on_result["itinerary"][0]["activities"]
    assert [activity.get("type") for activity in activities] == ["attraction", "lunch"]
    hop = activities[1]["transports"]
    assert hop[0]["mode"] == "taxi"
    # Start time is pinned, so the arrival can only move earlier -- no downstream cascade.
    assert hop[0]["start_time"] == "10:00"
    assert hop[-1]["end_time"] == "10:05"
    assert on_agent._inner_activity_minutes(activities[1]) == 5


def _two_day_plan():
    """Day 1 is boxed in by a fixed departure-shaped tail; day 2 is wide open. Plan-level DAV
    (attractions / (4 * days)) lets day 2 carry day 1's shortfall."""
    def _day(day, activities):
        return {"day": day, "activities": activities}

    return {
        "itinerary": [
            _day(1, [
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
                    "type": "accommodation",
                    "position": "Hotel Alpha",
                    "start_time": "10:30",
                    "end_time": "24:00",
                    "price": 100,
                    "cost": 100,
                    "tickets": 1,
                    "transports": _leg(
                        "Museum", "Hotel Alpha", "10:10", "10:15", "metro", price=2, cost=2
                    ),
                },
            ]),
            _day(2, [
                {
                    "type": "attraction",
                    "position": "Gallery",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "price": 0,
                    "cost": 0,
                    "tickets": 1,
                    "transports": _leg(
                        "Hotel Alpha", "Gallery", "08:50", "08:55", "metro", price=2, cost=2
                    ),
                },
                {
                    "type": "accommodation",
                    "position": "Hotel Alpha",
                    "start_time": "21:00",
                    "end_time": "24:00",
                    "price": 100,
                    "cost": 100,
                    "tickets": 1,
                    "transports": _leg(
                        "Gallery", "Hotel Alpha", "20:30", "20:35", "metro", price=2, cost=2
                    ),
                },
            ]),
        ]
    }


def test_pack_dav_lets_a_free_day_carry_the_plan_level_shortfall(monkeypatch):
    monkeypatch.setenv("TPC_PACK_DAV", "1")
    plan = _two_day_plan()
    _install_candidate_context(
        monkeypatch,
        attractions=[_row("Park {}".format(i), lat=0.0, lon=0.01 * i) for i in range(1, 12)],
        hotels=[_row("Hotel Alpha", lat=0.0, lon=0.03)],
    )
    agent = _bare_agent()
    agent._build_plan = lambda *args, **kwargs: deepcopy(plan)

    packed = agent._pack_plan(deepcopy(plan), QUERY, {}, _accepted_check, {})

    per_day = [
        sum(1 for activity in day["activities"] if activity.get("type") == "attraction")
        for day in packed["itinerary"]
    ]
    # Day 2 is allowed past the old hard four-per-day ceiling because the plan is still short of
    # its 4 * day_count target, and stops at the TPC_DENSIFY_ATTR_DAY_CAP ceiling.
    assert per_day[1] > 4
    assert max(per_day) <= 8


def _long_visit_plan():
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "attraction",
                        "position": "Museum",
                        "start_time": "09:00",
                        "end_time": "14:30",  # 330 minutes, swallowing the whole lunch band
                        "price": 0,
                        "cost": 0,
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
                        "transports": _leg(
                            "Museum", "Hotel Alpha", "20:30", "20:35", "metro", price=2, cost=2
                        ),
                    },
                ],
            }
        ]
    }


def test_compress_before_is_opt_in_and_frees_room_for_the_meal_top_up(monkeypatch):
    monkeypatch.setenv("TPC_PACK_DDR", "1")
    _install_candidate_context(
        monkeypatch,
        restaurants=[_row("Bistro", lat=0.0, lon=0.01, price_cents=20)],
        hotels=[_row("Hotel Alpha", lat=0.0, lon=0.03)],
    )

    off_agent = _bare_agent()
    off_agent._build_plan = lambda *args, **kwargs: deepcopy(_long_visit_plan())
    off_result = off_agent._pack_plan(deepcopy(_long_visit_plan()), QUERY, {}, _accepted_check, {})
    off_acts = off_result["itinerary"][0]["activities"]
    assert off_acts[0]["end_time"] == "14:30"
    assert not [a for a in off_acts if a.get("type") == "lunch"]

    monkeypatch.setenv("TPC_DENSIFY_COMPRESS_BEFORE", "1")
    monkeypatch.setenv("TPC_DENSIFY_COMPRESS_ATTR_DWELL", "60")
    on_agent = _bare_agent()
    on_agent._build_plan = lambda *args, **kwargs: deepcopy(_long_visit_plan())
    on_result = on_agent._pack_plan(deepcopy(_long_visit_plan()), QUERY, {}, _accepted_check, {})
    on_acts = on_result["itinerary"][0]["activities"]
    assert on_acts[0]["end_time"] == "10:00"  # trimmed back to the standard dwell
    lunches = [a for a in on_acts if a.get("type") == "lunch"]
    assert len(lunches) == 1
    assert lunches[0]["position"] == "Bistro"


def test_compress_before_reverts_a_trim_the_checker_rejects(monkeypatch):
    """A stay_duration-style clause that needs the long visit keeps it."""
    monkeypatch.setenv("TPC_PACK_DDR", "1")
    monkeypatch.setenv("TPC_DENSIFY_COMPRESS_BEFORE", "1")
    monkeypatch.setenv("TPC_DENSIFY_COMPRESS_ATTR_DWELL", "60")
    _install_candidate_context(monkeypatch, restaurants=[], hotels=[])

    def check(candidate):
        museum = candidate["itinerary"][0]["activities"][0]
        return (1, 1) if museum["end_time"] >= "14:00" else (0, 1)

    agent = _bare_agent()
    agent._build_plan = lambda *args, **kwargs: deepcopy(_long_visit_plan())
    result = agent._pack_plan(deepcopy(_long_visit_plan()), QUERY, {}, check, {})

    assert result["itinerary"][0]["activities"][0]["end_time"] == "14:30"
