"""Focused tests for P8's opt-in bounded timed-window suffix push."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for path in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if path not in sys.path:
        sys.path.insert(0, path)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402

QUERY = {"target_city": "TestCity", "people_number": 1}
WINDOW = {"location": "Inn", "earliest": "07:45", "end_before": "08:45",
          "activity_types": ["breakfast"]}


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = None
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _plan(*, successor_start="08:30", successor_end="09:30", tail_type=None):
    activities = [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:30",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Museum", "start_time": successor_start,
         "end_time": successor_end, "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]
    if tail_type:
        tail = {"type": tail_type, "position": "Inn", "start_time": "08:30", "end_time": "24:00",
                "price": 100, "cost": 100, "tickets": 1, "transports": []}
        if tail_type == "train":
            tail.update({"start": "Test Station", "end": "Home Station", "position": None})
        activities = activities[:1] + [tail]
    return {"itinerary": [{"activities": activities}]}


def _check(plan):
    breakfast = plan["itinerary"][0]["activities"][0]
    return (1, 1) if breakfast["start_time"] >= "07:45" and breakfast["end_time"] <= "08:45" else (0, 1)


def test_push_shifts_suffix_and_transports_by_the_exact_delay():
    agent = _bare_agent()
    agent._get_transport = lambda *args: (_ for _ in ()).throw(
        AssertionError("window push must translate existing legs"))
    plan = _plan(successor_start="08:40", successor_end="09:40")
    plan["itinerary"][0]["activities"][0]["transports"] = [
        {"start": "Hotel", "end": "Inn", "start_time": "07:20", "end_time": "07:30",
         "mode": "metro", "price": 2, "distance": 3}]
    plan["itinerary"][0]["activities"][1]["transports"] = [
        {"start": "Inn", "end": "Museum", "start_time": "08:30", "end_time": "08:40", "mode": "walk"}]

    assert agent._push_timed_windows(plan, QUERY, {"activity_time_windows": [WINDOW]}, _check) is True
    breakfast, museum = plan["itinerary"][0]["activities"]
    assert (breakfast["start_time"], breakfast["end_time"]) == ("07:45", "08:45")
    assert breakfast["transports"][0] == {
        "start": "Hotel", "end": "Inn", "start_time": "07:35", "end_time": "07:45",
        "mode": "metro", "price": 2, "distance": 3}
    assert (museum["start_time"], museum["end_time"]) == ("08:55", "09:55")
    assert (museum["transports"][0]["start_time"], museum["transports"][0]["end_time"]) == ("08:45", "08:55")


def test_push_absorbs_existing_slack_without_moving_successor_clock():
    agent = _bare_agent()
    plan = _plan(successor_start="09:15", successor_end="10:15")
    plan["itinerary"][0]["activities"][1]["transports"] = [
        {"start": "Inn", "end": "Museum", "start_time": "08:30", "end_time": "08:40",
         "mode": "walk"}]

    assert agent._push_timed_windows(plan, QUERY, {"activity_time_windows": [WINDOW]}, _check) is True
    museum = plan["itinerary"][0]["activities"][1]
    assert (museum["start_time"], museum["end_time"]) == ("09:15", "10:15")
    assert (museum["transports"][0]["start_time"], museum["transports"][0]["end_time"]) == (
        "08:45", "08:55")


def test_push_rejects_a_delay_above_its_bound(monkeypatch):
    monkeypatch.setenv("TPC_WINDOW_PUSH_MAX_MIN", "30")
    agent = _bare_agent()
    plan = _plan()
    late_window = dict(WINDOW, earliest="08:20", end_before="09:20")

    assert agent._push_timed_windows(plan, QUERY, {"activity_time_windows": [late_window]}, _check) is False
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"


def test_push_rejects_a_successor_past_its_closing_time():
    agent = _bare_agent()
    agent._lookup_poi_open_bounds = lambda city, position, kind, tickets: (0, 9 * 60 + 44) if position == "Museum" else None
    plan = _plan(successor_start="08:30", successor_end="09:30")

    assert agent._push_timed_windows(plan, QUERY, {"activity_time_windows": [WINDOW]}, _check) is False
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"


def test_push_retimes_an_accommodation_tail_but_not_an_intercity_tail():
    agent = _bare_agent()
    accommodation = _plan(tail_type="accommodation")
    assert agent._push_timed_windows(accommodation, QUERY, {"activity_time_windows": [WINDOW]}, _check) is True
    assert accommodation["itinerary"][0]["activities"][1]["start_time"] == "08:45"

    train = _plan(tail_type="train")
    assert agent._push_timed_windows(train, QUERY, {"activity_time_windows": [WINDOW]}, _check) is False
    assert train["itinerary"][0]["activities"][0]["start_time"] == "07:30"


def test_window_push_flag_is_off_by_default_and_reached_only_when_enabled(monkeypatch):
    agent = _bare_agent()
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._pin_windows_enabled = lambda: False
    agent._repair_transport_gaps_enabled = lambda: False
    agent._repair_intercity_enabled = lambda: False
    agent._repair_drop_trailing_stay_enabled = lambda: False
    agent._window_anchor_enabled = lambda: False
    agent._set_transport_context = lambda constraints: None
    calls = {"push": 0}
    agent._push_timed_windows = lambda *args: calls.__setitem__("push", calls["push"] + 1)

    monkeypatch.delenv("TPC_WINDOW_PUSH", raising=False)
    agent._pack_plan(_plan(), QUERY, {}, lambda p: (0, 1), {})
    assert calls["push"] == 0
    monkeypatch.setenv("TPC_WINDOW_PUSH", "1")
    agent._pack_plan(_plan(), QUERY, {}, lambda p: (0, 1), {})
    assert calls["push"] == 1