"""Unit tests for scripts/repair_commonsense.py (docs/tpc_shortcomings_and_plan.md W1).

These use synthetic plan dicts and a fake, stubbed TPCAgent instance -- no real WorldEnv, no
solve, no dependency on results/best.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel"), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent, minutes_to_time  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "repair_commonsense", str(PROJECT_ROOT / "scripts" / "repair_commonsense.py")
)
rc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rc)

CITY = "TestCity"


def _bare_agent(travel_minutes=None, poi_bounds=None):
    """A TPCAgent with no WorldEnv, only the grounding helpers repair_commonsense.py calls
    stubbed with a small deterministic travel-time table."""
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = object()
    agent._injected_variants = None
    agent._transport_constraints = {}
    agent._forced_inner_mode = None
    agent._budget_limits = {}
    travel_minutes = dict(travel_minutes or {})
    poi_bounds = dict(poi_bounds or {})

    def _get_transport(env, city, from_pos, to_pos, start_time, people):
        if from_pos == to_pos:
            return [], start_time
        minutes = travel_minutes.get((from_pos, to_pos), travel_minutes.get((to_pos, from_pos)))
        if minutes is None:
            return None, None
        from chinatravel.agent.tpc_agent.tpc_agent import time_to_minutes
        end_time = minutes_to_time(time_to_minutes(start_time) + minutes)
        leg = {
            "start": from_pos, "end": to_pos, "mode": "walk",
            "start_time": start_time, "end_time": end_time,
            "distance": 0.1, "price": 0, "cost": 0,
        }
        return [leg], end_time

    def _best_transport_via_get_transport(city, from_pos, to_pos, start_time, people):
        return _get_transport(None, city, from_pos, to_pos, start_time, people)

    def _lookup_poi_open_bounds(city, position, activity_type, tickets=None):
        return poi_bounds.get(position)

    agent._get_transport = _get_transport
    agent._best_transport_via_get_transport = _best_transport_via_get_transport
    agent._lookup_poi_open_bounds = _lookup_poi_open_bounds
    return agent


def _act(type_, position, start, end, transports=None):
    return {
        "type": type_, "position": position, "start_time": start, "end_time": end,
        "price": 0, "cost": 0, "tickets": 1, "transports": transports or [],
    }


def _intercity(type_, start_pos, end_pos, start, end):
    return {
        "type": type_, "start": start_pos, "end": end_pos, "start_time": start, "end_time": end,
        "price": 0, "cost": 0, "tickets": 1, "transports": [],
    }


def test_r1_drops_duplicate_meal_and_regrounds_next_activity():
    agent = _bare_agent(travel_minutes={("B", "D"): 15})
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("breakfast", "A", "08:00", "08:30"),
        _act("lunch", "B", "11:00", "12:00"),
        _act("lunch", "C", "11:30", "12:30"),
        _act("attraction", "D", "13:00", "13:30", transports=[
            {"start": "C", "end": "D", "mode": "walk", "start_time": "12:30", "end_time": "12:45"}
        ]),
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}

    changed = rc._repair_duplicate_meals(agent, plan, query, CITY, 1)

    assert changed is True
    acts = plan["itinerary"][0]["activities"]
    assert [a["type"] for a in acts] == ["breakfast", "lunch", "attraction"]
    assert acts[1]["position"] == "B"  # first duplicate kept, matching rule 2/3 fallback order
    # The attraction after the dropped lunch is re-grounded from the kept lunch's end position/time.
    assert acts[2]["transports"] == [
        {"start": "B", "end": "D", "mode": "walk", "start_time": "12:00", "end_time": "12:15",
         "distance": 0.1, "price": 0, "cost": 0}
    ]
    # Not shifted -- the recomputed arrival (12:15) is earlier than its existing start (13:00).
    assert acts[2]["start_time"] == "13:00"


def test_r2_reorders_list_with_no_overlap_and_drops_nothing():
    agent = _bare_agent(travel_minutes={("A", "Y"): 5, ("Y", "X"): 5})
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("breakfast", "A", "08:00", "08:30"),
        _act("attraction", "X", "10:00", "10:30"),  # listed first, later time
        _act("attraction", "Y", "09:00", "09:30"),  # listed second, earlier time
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}

    changed = rc._restore_chronological_order(agent, plan, query, CITY, 1)

    assert changed is True
    acts = plan["itinerary"][0]["activities"]
    assert len(acts) == 3  # nothing dropped
    assert [a["position"] for a in acts] == ["A", "Y", "X"]
    assert acts[1]["start_time"] == "09:00"  # R2 recomputes legs, not times
    assert acts[2]["start_time"] == "10:00"


def test_r3_shifts_overlap_that_fits_inside_opening_window():
    agent = _bare_agent(
        travel_minutes={("A", "B"): 10},
        poi_bounds={"B": (0, 24 * 60)},  # open all day, plenty of room to shift into
    )
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("attraction", "A", "09:00", "10:00"),
        _act("attraction", "B", "09:50", "10:20"),  # overlaps A's end by 10 minutes
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}

    changed = rc._respace_overlaps(agent, plan, query, CITY, 1)

    assert changed is True
    acts = plan["itinerary"][0]["activities"]
    assert len(acts) == 2  # shifted, not dropped
    assert acts[1]["start_time"] == "10:10"  # A ends 10:00 + 10 min leg
    assert acts[1]["end_time"] == "10:40"  # own 30-minute duration preserved


def test_r3_drops_overlap_that_would_miss_closing_time():
    agent = _bare_agent(
        travel_minutes={("A", "B"): 10},
        poi_bounds={"B": (0, 10 * 60 + 15)},  # closes 10:15 -- the shifted window would miss it
    )
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("attraction", "A", "09:00", "10:00"),
        _act("attraction", "B", "09:50", "10:20"),
        _act("attraction", "C", "10:30", "11:00"),
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}

    changed = rc._respace_overlaps(agent, plan, query, CITY, 1)

    assert changed is True
    acts = plan["itinerary"][0]["activities"]
    assert [a["position"] for a in acts] == ["A", "C"]  # B dropped


def test_r4_regrounds_leg_that_starts_before_previous_activity_ends():
    agent = _bare_agent(travel_minutes={("A", "B"): 10})
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("attraction", "A", "09:00", "10:00"),
        # B's inbound leg (09:50-09:55) departs before A even ends (10:00) -- the bug R4 targets.
        _act("attraction", "B", "10:02", "10:32", transports=[
            {"start": "A", "end": "B", "mode": "walk", "start_time": "09:50", "end_time": "09:55"}
        ]),
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}

    changed = rc._reground_early_transport(agent, plan, query, CITY, 1)

    assert changed is True
    acts = plan["itinerary"][0]["activities"]
    assert acts[1]["transports"][0]["start_time"] == "10:00"  # re-requested from A's real end
    assert acts[1]["start_time"] == "10:10"  # clamped to the new arrival (10:00 + 10 min)
    assert acts[1]["end_time"] == "10:40"  # own 30-minute duration preserved


def test_rejected_repair_leaves_the_original_plan_untouched():
    """repair_plan works on a deepcopy; a caller that finds the repaired trial still rejected
    (docs' byte-identical-floor case) writes nothing because it never touches `plan` itself."""
    agent = _bare_agent(travel_minutes={})
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("lunch", "A", "11:00", "12:00"),
        _act("lunch", "B", "11:30", "12:30"),
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}
    snapshot = deepcopy(plan)

    trial = rc.repair_plan(agent, plan, query)

    assert plan == snapshot  # original untouched regardless of whether trial is later accepted
    assert trial is not plan


def test_intercity_head_and_tail_never_moved_dropped_or_retimed():
    agent = _bare_agent(travel_minutes={("Airport", "A"): 20, ("A", "Airport"): 20})
    head = _intercity("airplane", "Origin Airport", "Airport", "07:00", "08:00")
    tail = _intercity("airplane", "Airport", "Origin Airport", "20:00", "21:00")
    plan = {"itinerary": [{"day": 1, "activities": [
        deepcopy(head),
        _act("lunch", "A", "07:30", "08:30"),  # overlaps the head's own end_time (08:00)
        _act("lunch", "B", "07:10", "07:40"),  # out of list order and overlapping too
        deepcopy(tail),
    ]}]}
    query = {"hard_logic_py": [], "nature_language": "", "target_city": CITY, "people_number": 1}

    trial = rc.repair_plan(agent, plan, query)

    acts = trial["itinerary"][0]["activities"]
    # The intercity head/tail's own ticketed schedule (type, positions, start/end time) is never
    # moved or dropped by any pass -- only its inbound leg's "transports" field may be recomputed
    # (R4's job: re-ground the hop *to* the boarding station/airport, never the flight itself).
    for key in ("type", "start", "end", "start_time", "end_time"):
        assert acts[0][key] == head[key]
        assert acts[-1][key] == tail[key]


def test_dry_run_reports_applicable_repairs_without_touching_disk(tmp_path, monkeypatch):
    best_dir = tmp_path / "results" / "best"
    best_dir.mkdir(parents=True)
    method_dir = tmp_path / "results" / "repair_commonsense"
    plan = {"itinerary": [{"day": 1, "activities": [
        _act("lunch", "A", "11:00", "12:00"),
        _act("lunch", "B", "11:30", "12:30"),
    ]}]}
    import json
    (best_dir / "u1.json").write_text(json.dumps(plan))

    root_dir = tmp_path
    monkeypatch.setattr(rc, "ROOT", str(root_dir))
    monkeypatch.setattr(rc, "load_query", lambda query_args: (["u1"], {"u1": {"hard_logic_py": []}}))

    from types import SimpleNamespace
    args = SimpleNamespace(split="s", method=None, limit=None, dry_run=True)
    rc._process(args)

    assert list(method_dir.glob("*.json")) == []
