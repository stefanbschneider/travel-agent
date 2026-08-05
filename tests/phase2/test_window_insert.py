"""Focused tests for P9's opt-in named timed-POI insertion."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for path in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if path not in sys.path:
        sys.path.insert(0, path)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402

QUERY = {"target_city": "TestCity", "people_number": 1}
WINDOW = {"location": "Museum", "earliest": "08:10", "end_before": "09:30",
          "activity_types": ["attraction"]}


class _Pool:
    def select(self, city, column, predicate):
        return [{"name": "Museum", "opentime": "08:00", "endtime": "18:00", "price": 10,
                 "cost": 10, "tickets": 1, "type": "Art museum"}]


class _Env:
    attractions = _Pool()
    restaurants = _Pool()


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = _Env()
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _plan():
    return {"itinerary": [{"activities": [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Gallery", "start_time": "10:00", "end_time": "11:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]}]}


def _check(plan):
    for activity in plan["itinerary"][0]["activities"]:
        if activity.get("position") == "Museum":
            return (1, 1) if activity["start_time"] >= "08:10" and activity["end_time"] <= "09:30" else (0, 1)
    return (0, 1)


def test_insert_resolves_absent_poi_and_commits_even_when_key_is_lower():
    agent = _bare_agent()
    plan = _plan()
    agent._accepted_eval_key = lambda candidate: 0 if any(
        activity.get("position") == "Museum"
        for activity in candidate["itinerary"][0]["activities"]) else 100

    assert agent._insert_absent_timed_window_pois(plan, QUERY, {"activity_time_windows": [WINDOW]}, _check)
    museum = plan["itinerary"][0]["activities"][1]
    assert museum["position"] == "Museum"
    assert (museum["start_time"], museum["end_time"]) == ("08:10", "09:00")


def test_insert_skips_a_duplicate_named_poi_and_an_unresolvable_poi():
    agent = _bare_agent()
    duplicate = _plan()
    duplicate["itinerary"][0]["activities"][1]["position"] = "Museum"
    assert agent._insert_absent_timed_window_pois(duplicate, QUERY, {"activity_time_windows": [WINDOW]}, _check) is False

    unresolved = _plan()
    unknown = dict(WINDOW, location="Unknown Museum")
    assert agent._insert_absent_timed_window_pois(unresolved, QUERY, {"activity_time_windows": [unknown]}, _check) is False


def test_insert_does_not_treat_an_accommodation_as_a_matching_visit():
    agent = _bare_agent()
    plan = _plan()
    plan["itinerary"][0]["activities"].append(
        {"type": "accommodation", "position": "Museum", "start_time": "20:00", "end_time": "24:00",
         "price": 100, "cost": 100, "tickets": 1, "transports": []})
    assert agent._insert_absent_timed_window_pois(plan, QUERY, {"activity_time_windows": [WINDOW]}, _check)


def test_insert_treats_all_meal_types_as_the_same_restaurant_use():
    agent = _bare_agent()
    plan = _plan()
    plan["itinerary"][0]["activities"].append(
        {"type": "lunch", "position": "Museum", "start_time": "12:00", "end_time": "13:00",
         "price": 10, "cost": 10, "tickets": 1, "transports": []})
    dinner_window = dict(WINDOW, earliest="18:00", end_before="19:30", activity_types=["dinner"])
    assert agent._insert_absent_timed_window_pois(
        plan, QUERY, {"activity_time_windows": [dinner_window]}, _check) is False


def test_window_insert_flag_is_off_by_default_and_reached_only_when_enabled(monkeypatch):
    agent = _bare_agent()
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._pin_windows_enabled = lambda: False
    agent._repair_transport_gaps_enabled = lambda: False
    agent._repair_intercity_enabled = lambda: False
    agent._repair_drop_trailing_stay_enabled = lambda: False
    agent._window_anchor_enabled = lambda: False
    agent._window_push_enabled = lambda: False
    agent._set_transport_context = lambda constraints: None
    calls = {"insert": 0}
    agent._insert_absent_timed_window_pois = lambda *args: calls.__setitem__("insert", calls["insert"] + 1)

    monkeypatch.delenv("TPC_WINDOW_INSERT", raising=False)
    agent._pack_plan(_plan(), QUERY, {}, lambda p: (0, 1), {})
    assert calls["insert"] == 0
    monkeypatch.setenv("TPC_WINDOW_INSERT", "1")
    agent._pack_plan(_plan(), QUERY, {}, lambda p: (0, 1), {})
    assert calls["insert"] == 1