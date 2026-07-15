"""Tests for the hotel_nearby tighter-or-equal distance check.

Natural-language distance values are display-rounded from the oracle's unrounded threshold.
The parsed verifier therefore uses a threshold 0.01 km tighter than the parsed value, preventing
a hotel whose true distance lies just below the display value from passing internally while
failing the oracle threshold.
"""

from __future__ import annotations

from chinatravel.agent.tpc_agent import parsed_verifier as pv


TARGET_CITY = "Shanghai"


def _plan_with_hotel(hotel_name="Some Hotel"):
    return {
        "people_number": 2,
        "start_city": "Beijing",
        "target_city": TARGET_CITY,
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "accommodation",
                        "position": hotel_name,
                        "start_time": "21:00",
                        "end_time": "23:00",
                        "transports": [],
                    }
                ],
            }
        ],
    }


def test_hotel_within_the_tightened_bound_is_accepted(monkeypatch):
    # True distance 8.849 km; parsed (NL-rounded) value 8.86 km. 8.849 <= 8.86 - 0.01 (8.85).
    monkeypatch.setitem(pv.func_dict, "poi_distance", lambda city, a, b: 8849.0)
    constraints = {"hotel_nearby": {"reference": "Some POI", "distance_km": 8.86}}
    results = pv.evaluate_parsed_constraints(constraints, _plan_with_hotel(), TARGET_CITY)
    assert results == [True]


def test_hotel_between_tightened_and_display_bound_is_rejected(monkeypatch):
    # True distance 8.855 km -- passes the old (parsed-value) check (<=8.86) but would fail the
    # real oracle's unrounded threshold (e.g. 8.8515...); the tightened check must reject it too.
    monkeypatch.setitem(pv.func_dict, "poi_distance", lambda city, a, b: 8855.0)
    constraints = {"hotel_nearby": {"reference": "Some POI", "distance_km": 8.86}}
    results = pv.evaluate_parsed_constraints(constraints, _plan_with_hotel(), TARGET_CITY)
    assert results == [False]


def test_hotel_exactly_at_tightened_bound_is_accepted(monkeypatch):
    monkeypatch.setitem(pv.func_dict, "poi_distance", lambda city, a, b: 8850.0)  # 8.86 - 0.01
    constraints = {"hotel_nearby": {"reference": "Some POI", "distance_km": 8.86}}
    results = pv.evaluate_parsed_constraints(constraints, _plan_with_hotel(), TARGET_CITY)
    assert results == [True]
