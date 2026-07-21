"""Unit tests for the solver-only failure-attribution diagnostic (scripts/)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "phase2_solver_failure_attribution",
    PROJECT_ROOT / "scripts" / "phase2_solver_failure_attribution.py",
)
attrib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(attrib)


# --- classifier ------------------------------------------------------------------------------

TIMED_MEAL = (
    "result=False\n"
    "for activity in allactivities(plan):\n"
    "  if activity_type(activity) in ['breakfast', 'lunch', 'dinner'] and "
    'activity_position(activity)=="Guangzhou Junye Hotel":\n'
    '    if activity_start_time(activity)>="07:50" and activity_end_time(activity)<="08:45": result=True'
)
TIMED_ATTR = (
    "result=False\n"
    "for activity in allactivities(plan):\n"
    "  if activity_type(activity)=='attraction' and "
    'activity_position(activity)=="Maple Bridge Scenic Area":\n'
    '    if activity_start_time(activity)>="08:15" and activity_end_time(activity)<="10:05": result=True'
)
EXCL_ATTR_TYPE = (
    "attraction_type_set=set()\n"
    "for activity in allactivities(plan):\n"
    "  if activity_type(activity)=='attraction': attraction_type_set.add(attraction_type(activity, target_city(plan)))\n"
    'result=not({"Red tourism sites"}&attraction_type_set)'
)
REQ_ATTR_TYPE = (
    "attraction_type_set=set()\n"
    "for activity in allactivities(plan):\n"
    "  if activity_type(activity)=='attraction': attraction_type_set.add(attraction_type(activity, target_city(plan)))\n"
    'result=({"Museum/Memorial Hall", "natural scenery"}<=attraction_type_set)'
)
EXCL_HOTEL = (
    "accommodation_name_set=set()\n"
    "for activity in allactivities(plan):\n"
    "  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_position(activity))\n"
    'result=not({"Guangzhou Jingge Hotel"}&accommodation_name_set)'
)
REQ_RESTAURANT_TYPE = (
    "restaurant_type_set=set()\n"
    "for activity in allactivities(plan):\n"
    "  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_type_set.add(restaurant_type(activity, target_city(plan)))\n"
    'result=({"Snacks", "Fast food and casual dining"}<=restaurant_type_set)'
)


def test_classify_timed_visit_named_poi_meal_and_attraction():
    assert attrib.classify_constraint(TIMED_MEAL) == "timed_visit_named_poi"
    assert attrib.classify_constraint(TIMED_ATTR) == "timed_visit_named_poi"


def test_classify_structural_and_counts():
    assert attrib.classify_constraint("result=(day_count(plan)==2)") == "structural_days"
    assert attrib.classify_constraint("result=(people_count(plan)==2)") == "structural_people"
    assert attrib.classify_constraint(
        "for activity in allactivities(plan):\n  if activity_tickets(activity)!=2: result=False"
    ) == "ticket_count"
    assert attrib.classify_constraint(
        "for activity in allactivities(plan):\n  if room_count(activity)!=2: result=False"
    ) == "room_count"


def test_classify_exclusion_vs_requirement_polarity():
    assert attrib.classify_constraint(EXCL_ATTR_TYPE) == "excluded_attraction_types"
    assert attrib.classify_constraint(REQ_ATTR_TYPE) == "required_attraction_types"
    assert attrib.classify_constraint(EXCL_HOTEL) == "excluded_hotels"
    assert attrib.classify_constraint(REQ_RESTAURANT_TYPE) == "required_cuisine_types"


def test_classify_unknown_shape_is_unclassified_not_mislabelled():
    assert attrib.classify_constraint("result=some_new_helper(plan)") == "unclassified"
    assert attrib.classify_constraint("") == "unclassified"


# --- per-clause verdict readers -------------------------------------------------------------


def test_failed_logic_indices_ignores_nan_padding():
    row = {"data_id": "u", "logic_py_0": 1, "logic_py_1": 0, "logic_py_2": 1,
           "logic_py_3": float("nan")}
    assert attrib.failed_logic_indices(row) == [1]


def test_failed_commonsense_uses_inverted_sign():
    # Commonsense: 0 == pass, non-zero == violation (opposite of logical).
    row = {"data_id": "u", "Unavailable attractions": 0, "Does not follow Chronological Order": 1,
           "Repeated attraction Choices": float("nan")}
    assert attrib.failed_commonsense_categories(row) == ["Does not follow Chronological Order"]


# --- attribution join -----------------------------------------------------------------------


def test_attribute_counts_sole_blocker():
    # One failing query whose only failed clause is a timed-visit window -> sole blocker.
    run = {
        "rehearsal": {"modes": {"solver-only": {"raw": {
            "evaluated": 2,
            "all_pass_ids": ["passing"],
            "logical_details": [
                {"data_id": "passing", "logic_py_0": 1, "logic_py_1": 1},
                {"data_id": "failing", "logic_py_0": 1, "logic_py_1": 0},
            ],
            "commonsense_details": [
                {"data_id": "passing"}, {"data_id": "failing"},
            ],
        }}}}
    }
    hard_logic = {"passing": [EXCL_HOTEL, TIMED_MEAL], "failing": [EXCL_HOTEL, TIMED_MEAL]}
    att = attrib.attribute(run, hard_logic, "solver-only")
    assert att["failing_query_count"] == 1
    tv = att["logical"]["timed_visit_named_poi"]
    assert tv["failing_queries"] == 1
    assert tv["sole_blocker_queries"] == 1
    assert tv["uids"] == ["failing"]
