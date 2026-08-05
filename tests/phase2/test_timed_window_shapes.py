"""Unit tests for the timed-window *shape* diagnostic (roadmap P1, Step 0).

``scripts/phase2_solver_failure_attribution.py`` says which constraint family blocks a query;
``scripts/phase2_timed_window_shapes.py`` says which *move* would unblock it. Both are pure
functions over a clause string and a plan, so both are unit-testable without a solve.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "phase2_timed_window_shapes",
    PROJECT_ROOT / "scripts" / "phase2_timed_window_shapes.py",
)
shapes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shapes)


def _clause(type_test, poi, lo, hi):
    return (
        "result=False\n"
        "for activity in allactivities(plan):\n"
        f"  if activity_type(activity){type_test} and activity_position(activity)==\"{poi}\":\n"
        f"    if activity_start_time(activity)>=\"{lo}\" and "
        f"activity_end_time(activity)<=\"{hi}\": result=True"
    )


MEAL_TEST = " in ['breakfast', 'lunch', 'dinner']"
ATTR_TEST = "=='attraction'"


# --- clause parsing --------------------------------------------------------------------------


def test_parse_timed_visit_reads_the_meal_type_set():
    parsed = shapes.parse_timed_visit(_clause(MEAL_TEST, "Junye Hotel", "07:50", "08:45"))
    assert parsed == {
        "types": ("breakfast", "lunch", "dinner"),
        "poi": "Junye Hotel",
        "lo": 7 * 60 + 50,
        "hi": 8 * 60 + 45,
    }


def test_parse_timed_visit_reads_a_single_type():
    parsed = shapes.parse_timed_visit(_clause(ATTR_TEST, "Maple Bridge", "08:15", "10:05"))
    assert parsed["types"] == ("attraction",)
    assert (parsed["lo"], parsed["hi"]) == (8 * 60 + 15, 10 * 60 + 5)


def test_parse_timed_visit_rejects_a_foreign_clause():
    assert shapes.parse_timed_visit("result = day_count(plan) == 3") is None
    assert shapes.parse_timed_visit("") is None


def test_parse_timed_visit_accepts_the_24_00_end_sentinel():
    parsed = shapes.parse_timed_visit(_clause("=='accommodation'", "Inn", "20:10", "24:00"))
    assert parsed["hi"] == 24 * 60


# --- shape classification --------------------------------------------------------------------


def _plan(*activities):
    return {"itinerary": [{"day": 1, "activities": list(activities)}]}


def _act(atype, position, start, end):
    return {"type": atype, "position": position, "start_time": start, "end_time": end}


WINDOW = {"types": ("attraction",), "poi": "Museum", "lo": 10 * 60, "hi": 12 * 60}


def test_absent_poi_when_the_named_poi_is_nowhere_in_the_plan():
    plan = _plan(_act("attraction", "Other Park", "10:00", "11:00"))
    assert shapes.classify_shape(plan, WINDOW)["shape"] == "absent_poi"


def test_wrong_type_when_the_poi_is_present_under_another_type():
    plan = _plan(_act("lunch", "Museum", "10:00", "11:00"))
    verdict = shapes.classify_shape(plan, WINDOW)
    assert verdict["shape"] == "wrong_type"
    assert verdict["detail"]["present_as"] == ["lunch"]


def test_forward_shift_when_the_activity_starts_too_early():
    plan = _plan(_act("attraction", "Museum", "08:00", "09:00"))
    verdict = shapes.classify_shape(plan, WINDOW)
    assert verdict["shape"] == "forward_shift"
    assert verdict["detail"]["minutes_off"] == 120  # 08:00 -> 10:00


def test_backward_shift_when_the_activity_ends_too_late():
    plan = _plan(_act("attraction", "Museum", "13:00", "14:00"))
    verdict = shapes.classify_shape(plan, WINDOW)
    assert verdict["shape"] == "backward_shift"
    assert verdict["detail"]["minutes_off"] == 120  # 14:00 -> 12:00


def test_shorten_when_the_dwell_exceeds_the_whole_window():
    """The dominant residual sub-shape: a 60-minute hotel breakfast against a 55-minute window."""
    window = {"types": ("breakfast",), "poi": "Inn", "lo": 7 * 60 + 50, "hi": 8 * 60 + 45}
    plan = _plan(_act("breakfast", "Inn", "07:30", "08:30"))
    verdict = shapes.classify_shape(plan, window)
    assert verdict["shape"] == "shorten"
    assert (verdict["detail"]["dwell"], verdict["detail"]["span"]) == (60, 55)


def test_the_cheapest_copy_decides_the_shape():
    """The clause is existential, so a same-POI copy needing a smaller move wins."""
    plan = _plan(
        _act("attraction", "Museum", "06:00", "07:00"),   # 240 min too early
        _act("attraction", "Museum", "09:30", "10:30"),   # only 30 min too early
    )
    verdict = shapes.classify_shape(plan, WINDOW)
    assert verdict["shape"] == "forward_shift"
    assert verdict["detail"]["minutes_off"] == 30
    assert verdict["detail"]["act"] == 1


def test_neighbour_context_reports_what_pins_the_activity():
    plan = _plan(
        {"type": "train", "start": "A Station", "end": "B Station",
         "start_time": "07:00", "end_time": "08:00"},
        _act("attraction", "Museum", "08:30", "09:30"),
        _act("lunch", "Diner", "12:00", "13:00"),
        _act("accommodation", "Inn", "20:00", "24:00"),
    )
    detail = shapes.classify_shape(plan, WINDOW)["detail"]
    assert detail["prev_type"] == "train" and detail["prev_movable"] is False
    assert detail["next_type"] == "lunch" and detail["next_movable"] is True
    assert detail["movable_block_contiguous"] is True
    assert detail["movable_count"] == 2


def test_noncontiguous_movable_block_is_reported():
    """A fixed activity between two movable ones is what every landed relayout refuses to cross."""
    plan = _plan(
        _act("attraction", "Museum", "08:00", "09:00"),
        {"type": "accommodation", "position": "Inn", "start_time": "09:00", "end_time": "10:00"},
        _act("lunch", "Diner", "12:00", "13:00"),
    )
    assert shapes.classify_shape(plan, WINDOW)["detail"]["movable_block_contiguous"] is False


def test_satisfied_clause_is_flagged_rather_than_bucketed():
    """``analyse`` only passes *failing* clauses, so a satisfied one means plan/clause disagree."""
    plan = _plan(_act("attraction", "Museum", "10:15", "11:15"))
    assert shapes.classify_shape(plan, WINDOW)["shape"] == "satisfiable_elsewhere"


def test_classify_shape_survives_a_malformed_time():
    plan = _plan(_act("attraction", "Museum", "not-a-time", "11:00"))
    assert shapes.classify_shape(plan, WINDOW)["shape"] == "unclassified"
