"""Unit tests for the opt-in within-day resequencing move (roadmap G8 follow-on).

These use a bare ``TPCAgent`` instance (``__new__``, no WorldEnv) and a stubbed
``_get_transport`` that returns the requested departure time as the arrival (zero travel time),
so the tests exercise only the pure reordering/retiming logic in ``_resequence_day``.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# TPCAgent uses internal ``from agent.base import ...`` imports, which require the ``chinatravel``
# directory on sys.path.
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = None
    # Zero travel time: arrival == requested departure clock, so the test can reason about
    # absolute times without modelling a transport graph.
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _misplaced_evening_plan():
    # Day 0: an attraction with a required evening window built into the morning slot (index 0),
    # followed by an ordinary morning attraction with no window (index 1), then the overnight stay.
    return {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "position": "Bear Garden", "start_time": "09:00",
                     "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "attraction", "position": "Museum", "start_time": "14:00",
                     "end_time": "15:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "accommodation", "position": "Hotel X", "start_time": "20:00",
                     "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                     "tickets": 1, "transports": []},
                ]
            }
        ]
    }


WINDOW = {"location": "Bear Garden", "earliest": "17:00", "latest": None,
          "end_after": None, "end_before": "19:00"}


def _window_checker():
    def check(plan):
        for day in plan.get("itinerary", []):
            for a in day.get("activities", []):
                if a.get("type") == "attraction" and a.get("position") == "Bear Garden":
                    if a.get("start_time", "") >= "17:00" and a.get("end_time", "") <= "19:00":
                        return (1, 1)
        return (0, 1)
    return check


def test_resequence_reorders_misplaced_window_activity():
    agent = _bare_agent()
    plan = _misplaced_evening_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    check = _window_checker()
    assert agent._accepted(*check(plan)) is False

    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, check)

    assert committed is True
    acts = plan["itinerary"][0]["activities"]
    # Museum (no window) moved to the front; Bear Garden moved into its evening window.
    assert acts[0]["position"] == "Museum"
    assert acts[1]["position"] == "Bear Garden"
    assert acts[1]["start_time"] >= "17:00" and acts[1]["end_time"] <= "19:00"
    assert agent._accepted(*check(plan)) is True


def test_resequence_first_slot_keeps_own_time_with_no_fixed_predecessor():
    # Reviewer scenario: with no fixed activity before the movable block, whichever activity lands
    # in slot 0 after reordering (Museum, originally at 14:00) must keep its own original time and
    # get no invented inbound leg -- consistent with _try_pin_activity's act_idx == 0 convention --
    # rather than a guessed "hotel departure" time derived from either activity's start_time.
    agent = _bare_agent()
    plan = _misplaced_evening_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, _window_checker())
    assert committed is True
    acts = plan["itinerary"][0]["activities"]
    assert acts[0]["position"] == "Museum"
    assert acts[0]["start_time"] == "14:00"
    assert acts[0]["transports"] == []


def test_resequence_bails_when_fixed_predecessor_position_unresolvable():
    # Reviewer scenario: a fixed activity precedes the movable block (movable_slots[0] > 0) but its
    # end position can't be resolved (e.g. a malformed intercity arrival). Silently treating this as
    # "no predecessor" would drop a real inbound leg and produce a discontinuous day; it must bail
    # instead.
    agent = _bare_agent()
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "airplane", "start": "HOME", "end": "", "start_time": "07:00",
                 "end_time": "09:00", "price": 500, "cost": 500, "tickets": 1, "transports": []},
                {"type": "attraction", "position": "Bear Garden", "start_time": "09:30",
                 "end_time": "10:30", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "attraction", "position": "Museum", "start_time": "14:00",
                 "end_time": "15:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "accommodation", "position": "Hotel X", "start_time": "20:00",
                 "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                 "tickets": 1, "transports": []},
            ]}
        ]
    }
    snapshot = [dict(a) for a in plan["itinerary"][0]["activities"]]
    constraints = {"activity_time_windows": [WINDOW]}
    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, _window_checker())
    assert committed is False
    assert plan["itinerary"][0]["activities"] == snapshot


def test_resequence_bails_when_fixed_tail_position_unresolvable():
    # Symmetric reviewer scenario on the tail side: the fixed activity after the movable block has
    # an unresolvable position (e.g. a malformed accommodation record). Calling _get_transport with
    # an invalid destination and silently accepting whatever it returns risks a bogus leg; it must
    # bail instead.
    agent = _bare_agent()
    plan = _misplaced_evening_plan()
    plan["itinerary"][0]["activities"][2]["position"] = ""
    snapshot = [dict(a) for a in plan["itinerary"][0]["activities"]]
    constraints = {"activity_time_windows": [WINDOW]}
    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, _window_checker())
    assert committed is False
    assert plan["itinerary"][0]["activities"] == snapshot


def test_resequence_recomputes_intercity_tail_transports():
    # Reviewer scenario: when the day ends in a fixed intercity leg, its inbound `transports` must
    # still be recomputed against the new (reordered) predecessor -- otherwise a checker validating
    # transport continuity rejects every last-day resequence, silently disabling the move there.
    agent = _bare_agent()
    agent._get_transport = lambda env, city, frm, to, depart, people: ([{"from": frm, "to": to}], depart)
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "attraction", "position": "Bear Garden", "start_time": "09:00",
                 "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "attraction", "position": "Museum", "start_time": "14:00",
                 "end_time": "15:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "airplane", "start": "APT", "end": "HOME", "start_time": "19:00",
                 "end_time": "20:30", "price": 500, "cost": 500, "tickets": 1,
                 "transports": [{"stale": True}]},
            ]}
        ]
    }
    constraints = {"activity_time_windows": [WINDOW]}

    def check(p):
        acts = p["itinerary"][0]["activities"]
        bear = next(a for a in acts if a["position"] == "Bear Garden")
        tail = acts[-1]
        ok = (
            bear["start_time"] >= "17:00" and bear["end_time"] <= "19:00"
            and bool(tail["transports"]) and tail["transports"][0].get("from") == "Bear Garden"
        )
        return (1, 1) if ok else (0, 1)

    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, check)
    assert committed is True
    tail = plan["itinerary"][0]["activities"][-1]
    assert tail["transports"][0]["from"] == "Bear Garden"


def test_resequence_leaves_accommodation_anchor_fixed():
    agent = _bare_agent()
    plan = _misplaced_evening_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, _window_checker())
    tail = plan["itinerary"][0]["activities"][2]
    assert tail["type"] == "accommodation"
    assert tail["position"] == "Hotel X"


def test_resequence_bails_when_movable_activities_are_not_contiguous():
    # Reviewer scenario: a fixed activity (here, a second accommodation) sits between two movable
    # activities, splitting them into two separate blocks. The head/tail recompute assumes a single
    # contiguous movable block bounded by at most one fixed predecessor and one fixed successor, so
    # this must bail rather than reorder across the fixed anchor.
    agent = _bare_agent()
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "attraction", "position": "Bear Garden", "start_time": "09:00",
                 "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "accommodation", "position": "Mid Inn", "start_time": "12:00",
                 "end_time": "13:00", "price": 50, "cost": 50, "rooms": 1, "room_type": 2,
                 "tickets": 1, "transports": []},
                {"type": "attraction", "position": "Museum", "start_time": "14:00",
                 "end_time": "15:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "accommodation", "position": "Hotel X", "start_time": "20:00",
                 "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                 "tickets": 1, "transports": []},
            ]}
        ]
    }
    snapshot = [dict(a) for a in plan["itinerary"][0]["activities"]]
    constraints = {"activity_time_windows": [WINDOW]}
    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, _window_checker())
    assert committed is False
    assert plan["itinerary"][0]["activities"] == snapshot


def test_resequence_is_noop_when_already_ordered():
    agent = _bare_agent()
    plan = _misplaced_evening_plan()
    # Already-satisfied window: no reorder needed, and current order already sorts correctly
    # (window earliest 08:30 < Museum's own start 14:00).
    window = {"location": "Bear Garden", "earliest": "08:30", "latest": None,
              "end_after": None, "end_before": "10:00"}
    constraints = {"activity_time_windows": [window]}
    before = [dict(a) for a in plan["itinerary"][0]["activities"]]
    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints,
        lambda p: (1, 1))
    assert committed is False
    assert plan["itinerary"][0]["activities"] == before


def test_resequence_reverts_when_checker_rejects():
    agent = _bare_agent()
    plan = _misplaced_evening_plan()
    snapshot = _misplaced_evening_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    committed = agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints, lambda p: (0, 1))
    assert committed is False
    assert plan == snapshot


def test_resequence_returns_false_with_fewer_than_two_movable_slots():
    agent = _bare_agent()
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "attraction", "position": "Bear Garden", "start_time": "09:00",
                 "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "accommodation", "position": "Hotel X", "start_time": "20:00",
                 "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                 "tickets": 1, "transports": []},
            ]}
        ]
    }
    constraints = {"activity_time_windows": [WINDOW]}
    assert agent._resequence_day(
        plan, 0, {"target_city": "Shenzhen", "people_number": 1}, constraints,
        _window_checker()) is False
