"""Unit tests for the opt-in timed-visit-window pinning path (roadmap G8).

These use a bare ``TPCAgent`` instance (``__new__``, no WorldEnv) and exercise only the pure
retiming logic on a synthetic plan where the target is a day's first activity followed by an
intercity leg -- so ``_get_transport`` (the only env-touching call) is never reached.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
    return agent


def _plan_with_breakfast(start_time, end_time):
    # Day 0: hotel breakfast (first activity, no inbound transports) then a departing flight, so a
    # retime of the breakfast needs no transport recomputation.
    return {
        "itinerary": [
            {
                "activities": [
                    {"type": "breakfast", "position": "Nanyang Inn", "start_time": start_time,
                     "end_time": end_time, "price": 0, "cost": 0, "tickets": 0, "transports": []},
                    {"type": "airplane", "start": "APT", "end": "HOME", "start_time": "19:00",
                     "end_time": "20:30", "price": 500, "cost": 500, "tickets": 1, "transports": []},
                ]
            }
        ]
    }


WINDOW = {"location": "Nanyang Inn", "earliest": "07:50", "latest": None,
          "end_after": None, "end_before": "08:40"}


def _window_checker():
    """A stub full-checker: the sole constraint is 'a Nanyang Inn meal within 07:50-08:40'."""
    def check(plan):
        ok = False
        for day in plan.get("itinerary", []):
            for a in day.get("activities", []):
                if a.get("type") in ("breakfast", "lunch", "dinner") and a.get("position") == "Nanyang Inn":
                    if a.get("start_time", "") >= "07:50" and a.get("end_time", "") <= "08:40":
                        ok = True
        return (1, 1) if ok else (0, 1)
    return check


def test_flag_off_by_default():
    assert _bare_agent()._pin_windows_enabled() is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("TPC_PIN_TIMED_WINDOWS", "1")
    assert _bare_agent()._pin_windows_enabled() is True


def test_apply_search_constraints_no_hotel_projection_when_flag_off(monkeypatch):
    monkeypatch.delenv("TPC_PIN_TIMED_WINDOWS", raising=False)
    agent = _bare_agent()
    merged = agent._apply_search_constraints({"activity_time_windows": [WINDOW]}, {})
    # Off: the accommodation name must NOT be forced into required_hotels (floor unchanged).
    assert "required_hotels" not in merged or "Nanyang Inn" not in (merged.get("required_hotels") or [])


def test_apply_search_constraints_projects_hotel_when_flag_on(monkeypatch):
    monkeypatch.setenv("TPC_PIN_TIMED_WINDOWS", "1")
    agent = _bare_agent()
    merged = agent._apply_search_constraints({"activity_time_windows": [WINDOW]}, {})
    assert "Nanyang Inn" in (merged.get("required_hotels") or [])


def test_pin_retimes_mistimed_breakfast_into_window():
    agent = _bare_agent()
    plan = _plan_with_breakfast("07:30", "08:30")  # 20 min too early
    constraints = {"activity_time_windows": [WINDOW]}
    check = _window_checker()
    assert agent._accepted(*check(plan)) is False  # starts before 07:50
    agent._pin_timed_windows(plan, {"target_city": "Shenzhen", "people_number": 1}, constraints, check)
    b = plan["itinerary"][0]["activities"][0]
    assert b["start_time"] >= "07:50" and b["end_time"] <= "08:40"
    assert agent._accepted(*check(plan)) is True


def test_pin_is_noop_when_already_in_window():
    agent = _bare_agent()
    plan = _plan_with_breakfast("07:50", "08:35")
    before = (plan["itinerary"][0]["activities"][0]["start_time"],
              plan["itinerary"][0]["activities"][0]["end_time"])
    agent._pin_timed_windows(plan, {"target_city": "Shenzhen", "people_number": 1},
                             {"activity_time_windows": [WINDOW]}, _window_checker())
    after = (plan["itinerary"][0]["activities"][0]["start_time"],
             plan["itinerary"][0]["activities"][0]["end_time"])
    assert before == after


def test_pin_starts_at_arrival_when_later_than_window_earliest():
    # Reviewer scenario: a POI reachable only partway into its window should still be pinned by
    # starting at max(earliest, arrival), not rejected for missing the earliest edge.
    agent = _bare_agent()
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], "12:15")
    # Day 0: an attraction, then a mistimed lunch at Nanyang Inn as the LAST activity (no outbound).
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "attraction", "position": "A", "start_time": "10:00", "end_time": "11:00",
                 "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "lunch", "position": "Nanyang Inn", "start_time": "09:00", "end_time": "10:00",
                 "price": 10, "cost": 10, "tickets": 1, "transports": []},
            ]}
        ]
    }
    window = {"location": "Nanyang Inn", "earliest": "11:30", "latest": None,
              "end_after": None, "end_before": "13:00"}

    def check(p):
        for day in p.get("itinerary", []):
            for a in day.get("activities", []):
                if a.get("type") == "lunch" and a.get("position") == "Nanyang Inn":
                    if a.get("start_time", "") >= "11:30" and a.get("end_time", "") <= "13:00":
                        return (1, 1)
        return (0, 1)

    agent._pin_timed_windows(plan, {"target_city": "Shenzhen", "people_number": 1},
                             {"activity_time_windows": [window]}, check)
    lunch = plan["itinerary"][0]["activities"][1]
    assert lunch["start_time"] == "12:15"  # arrival, later than the 11:30 earliest edge
    assert lunch["end_time"] <= "13:00"
    assert agent._accepted(*check(plan)) is True


def test_pin_reverts_when_check_rejects():
    # A checker that never accepts must leave the plan untouched (per-move acceptance gate).
    agent = _bare_agent()
    plan = _plan_with_breakfast("07:30", "08:30")
    snapshot = _plan_with_breakfast("07:30", "08:30")
    agent._pin_timed_windows(plan, {"target_city": "Shenzhen", "people_number": 1},
                             {"activity_time_windows": [WINDOW]}, lambda p: (0, 1))
    assert plan == snapshot
