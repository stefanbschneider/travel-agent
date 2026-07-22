"""Unit tests for TPCAgent's Stage 3 LLM refine primitives (ground_and_check,
apply_refine_edits, and the typed _refine_* edit ops).

These use a bare ``TPCAgent`` instance (``__new__``, no WorldEnv) with a stubbed
``_get_transport`` returning zero travel time (same pattern as test_resequence_day.py), so the
tests exercise only the pure grounding/relegging logic, not a real transport graph.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402


def _bare_agent(zero_travel=True):
    agent = TPCAgent.__new__(TPCAgent)
    # Phase 2's no-oracle path: ground_and_check must route through evaluate_parsed_constraints,
    # not the oracle's hard_logic_py (which these synthetic queries don't carry).
    agent.use_oracle = False
    agent.env = None
    agent.lang = "en"
    agent._last_solve_constraints = None
    agent._injected_variants = None
    if zero_travel:
        agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _day_plan():
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {"type": "attraction", "position": "Museum", "start_time": "09:00",
                     "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "lunch", "position": "Cafe X", "start_time": "12:00",
                     "end_time": "13:00", "price": 20, "cost": 20, "tickets": 1, "transports": []},
                    {"type": "attraction", "position": "Park Y", "start_time": "14:00",
                     "end_time": "15:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "accommodation", "position": "Hotel Z", "start_time": "20:00",
                     "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                     "tickets": 1, "transports": []},
                ],
            }
        ]
    }


QUERY = {"target_city": "Shenzhen", "people_number": 1, "uid": "test_uid"}


# --- apply_refine_edits dispatch --------------------------------------------------------------

def test_apply_refine_edits_drops_unknown_op():
    agent = _bare_agent()
    trial, applied = agent.apply_refine_edits(_day_plan(), QUERY, [{"op": "rewrite_everything"}])
    assert applied == 0
    assert trial == _day_plan()


def test_apply_refine_edits_caps_at_max_edits():
    agent = _bare_agent()
    edits = [{"op": "drop_activity", "day": 1, "location": "Museum"}] * 20
    # Each successive attempt after the first drop targets a name no longer present -> only the
    # cap matters here, not whether every attempt individually succeeds.
    trial, applied = agent.apply_refine_edits(_day_plan(), QUERY, edits)
    assert applied <= agent._REFINE_MAX_EDITS


def test_apply_refine_edits_never_raises_on_malformed_edit():
    agent = _bare_agent()
    trial, applied = agent.apply_refine_edits(_day_plan(), QUERY, [None, 42, {"op": None}, "x"])
    assert applied == 0


# --- shift_activity_window ---------------------------------------------------------------------

def test_shift_activity_window_retimes_named_activity():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "10:30", "end_time": "11:30"},
        "Shenzhen", 1,
    )
    assert ok is True
    act = plan["itinerary"][0]["activities"][0]
    assert act["start_time"] == "10:30" and act["end_time"] == "11:30"


def test_shift_activity_window_drops_when_location_not_found():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Nonexistent Place", "start_time": "10:30", "end_time": "11:30"},
        "Shenzhen", 1,
    )
    assert ok is False


def test_shift_activity_window_rejects_empty_window():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "11:00", "end_time": "10:00"},
        "Shenzhen", 1,
    )
    assert ok is False


# --- drop_activity -------------------------------------------------------------------------------

def test_drop_activity_removes_named_activity_and_reconnects():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_drop_activity(plan, {"day": 1, "location": "Cafe X"}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert "Cafe X" not in positions
    assert positions == ["Museum", "Park Y", "Hotel Z"]


def test_drop_activity_never_empties_a_day():
    agent = _bare_agent()
    plan = {"itinerary": [{"day": 1, "activities": [
        {"type": "attraction", "position": "Only One", "start_time": "09:00", "end_time": "10:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]}]}
    ok = agent._refine_drop_activity(plan, {"day": 1, "location": "Only One"}, "Shenzhen", 1)
    assert ok is False
    assert len(plan["itinerary"][0]["activities"]) == 1


# --- swap_activity -------------------------------------------------------------------------------

def test_swap_activity_swaps_two_named_activities():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_swap_activity(
        plan, {"day": 1, "location_a": "Museum", "location_b": "Park Y"}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions[:3] == ["Park Y", "Cafe X", "Museum"]


def test_swap_activity_drops_unknown_location():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_swap_activity(
        plan, {"day": 1, "location_a": "Museum", "location_b": "Nowhere"}, "Shenzhen", 1)
    assert ok is False


# --- reorder_day -----------------------------------------------------------------------------

def test_reorder_day_applies_explicit_order():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_reorder_day(
        plan, {"day": 1, "order": ["Park Y", "Museum", "Cafe X"]}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions[:3] == ["Park Y", "Museum", "Cafe X"]
    assert positions[3] == "Hotel Z"  # fixed anchor untouched


def test_reorder_day_noop_when_already_in_order():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_reorder_day(
        plan, {"day": 1, "order": ["Museum", "Cafe X", "Park Y"]}, "Shenzhen", 1)
    assert ok is False


def test_reorder_day_ignores_unmatched_names_but_still_reorders_known_ones():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_reorder_day(
        plan, {"day": 1, "order": ["Park Y", "Nonexistent"]}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions[0] == "Park Y"


# --- ground_and_check --------------------------------------------------------------------------

def test_ground_and_check_uses_last_solve_constraints_when_present():
    agent = _bare_agent()
    agent._last_solve_constraints = {"required_attractions": ["Museum"]}
    plan = _day_plan()
    accepted, grounded, key, failure = agent.ground_and_check(plan, QUERY)
    assert isinstance(grounded, dict)
    assert isinstance(failure, dict)
    assert "failed_constraint_families" in failure


def test_ground_and_check_reports_failed_family_when_constraint_unmet():
    agent = _bare_agent()
    agent._last_solve_constraints = {"required_attractions": ["Not In Plan"]}
    plan = _day_plan()
    accepted, grounded, key, failure = agent.ground_and_check(plan, QUERY)
    assert accepted is False
    assert "required_attractions" in failure["failed_constraint_families"]


def test_ground_and_check_family_not_failed_when_constraint_met():
    # A synthetic minimal plan won't pass the full schema/commonsense gate (real plans have far
    # more required fields), so this checks the family-level failure summary specifically, not
    # overall `accepted` -- that's covered by the "unmet" case above, which fails outright before
    # schema/commonsense are even consulted.
    agent = _bare_agent()
    agent._last_solve_constraints = {"required_attractions": ["Museum"]}
    plan = _day_plan()
    _accepted, _grounded, _key, failure = agent.ground_and_check(plan, QUERY)
    assert "required_attractions" not in failure["failed_constraint_families"]


def test_ground_and_check_never_raises_on_bad_query():
    agent = _bare_agent()
    accepted, grounded, key, failure = agent.ground_and_check(_day_plan(), {})
    assert accepted in (True, False)
