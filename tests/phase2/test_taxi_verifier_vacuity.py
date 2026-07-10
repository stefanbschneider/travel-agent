"""Parsed-verifier taxi-check regression tests (roadmap 1c).

The oracle encodes an inner-city transport exclusion by scanning *top-level* activities
whose ``activity_type == 'transportation'`` -- a category the plan schema never emits
(inner-city transport rides live as embedded ``transports`` segments). The oracle set is
therefore always empty and the clause is vacuously true. The parsed verifier must match
that semantics, otherwise it falsely rejects oracle-accepted plans.

The taxi-car-count clause is only enforced for taxi transports (decided by the same
``innercity_transport_type`` helper the oracle uses), so a taxi-free plan is vacuously
accepted too.

These tests build minimal plans directly (no solver/LLM) and assert the exact booleans
returned by ``evaluate_parsed_constraints``.
"""

from __future__ import annotations

from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints


TARGET_CITY = "Shanghai"


def _seg(mode, cars=None):
    seg = {
        "start": "A",
        "end": "B",
        "mode": mode,
        "start_time": "09:00",
        "end_time": "09:20",
        "distance": 5.0,
        "price": 10.0,
        "cost": 10.0,
    }
    if cars is not None:
        seg["cars"] = cars
    return seg


def _plan(transport_segments):
    """A one-day plan whose single attraction carries the given transport segments."""
    return {
        "people_number": 2,
        "start_city": "Beijing",
        "target_city": TARGET_CITY,
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "attraction",
                        "position": "Some Attraction",
                        "start_time": "09:20",
                        "end_time": "11:00",
                        "transports": transport_segments,
                    }
                ],
            }
        ],
    }


def test_excluded_taxi_vacuous_even_when_plan_uses_taxi():
    # Mirrors the oracle: the exclusion is vacuously true because the plan has no
    # top-level 'transportation' activities, even though a taxi ride is embedded.
    plan = _plan([_seg("taxi", cars=1)])
    res = evaluate_parsed_constraints({"excluded_inner_transport": ["taxi"]}, plan, TARGET_CITY)
    assert res == [True], res


def test_excluded_taxi_vacuous_on_taxi_free_plan():
    plan = _plan([_seg("metro")])
    res = evaluate_parsed_constraints({"excluded_inner_transport": ["taxi"]}, plan, TARGET_CITY)
    assert res == [True], res


def test_taxi_cars_equals_vacuous_when_no_taxi_used():
    plan = _plan([_seg("metro")])
    res = evaluate_parsed_constraints({"taxi_cars_equals": 1}, plan, TARGET_CITY)
    assert res == [True], res


def test_taxi_cars_equals_enforced_when_taxi_used():
    # A single-segment taxi transport => innercity_transport_type == 'taxi'; car count is checked.
    good = _plan([_seg("taxi", cars=1)])
    assert evaluate_parsed_constraints({"taxi_cars_equals": 1}, good, TARGET_CITY) == [True]

    bad = _plan([_seg("taxi", cars=3)])
    assert evaluate_parsed_constraints({"taxi_cars_equals": 1}, bad, TARGET_CITY) == [False]


def test_combined_taxi_family_accepts_taxi_free_plan():
    # The exact parse shape from roadmap 1c: {excluded_inner_transport:[taxi], taxi_cars_equals:1}.
    plan = _plan([_seg("metro")])
    res = evaluate_parsed_constraints(
        {"excluded_inner_transport": ["taxi"], "taxi_cars_equals": 1}, plan, TARGET_CITY
    )
    assert res == [True, True], res
