"""Phase B parser-coverage tests: DSL-structured families the no-oracle parser previously missed.

These mirror the oracle solver-dict shapes exactly (verified against val examples):
- required_hotel_any_types / required_hotel_all_types
- activity_time_windows: {location, earliest, latest, end_after, end_before}
- stay_duration: {location, min_minutes}  (legacy free-form "between A and B" -> B-A)
- position_presence: locations referenced by time-window / stay-duration constraints
"""

from __future__ import annotations

import parse_constraints as pc
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants


def _q(nl, people=2, days=3):
    return {"nature_language": nl, "people_number": people, "days": days,
            "start_city": "Suzhou", "target_city": "Hangzhou", "uid": "t"}


# --- required_hotel_any_types / all_types ----------------------------------

def test_hotel_any_types_one_of_the_following():
    raw = pc.parse_query_no_oracle(
        _q("Requirements: We hope to stay at one of the following hotel types: Swimming pool.")
    )
    assert raw.get("required_hotel_any_types") == ["Swimming pool"], raw
    assert not raw.get("hotel_type"), raw.get("hotel_type")


def test_hotel_all_types_offers():
    raw = pc.parse_query_no_oracle(
        _q("With the requirement: we prefer to stay at a hotel that offers free parking.")
    )
    assert raw.get("required_hotel_all_types") == ["Free parking"], raw


def test_hotel_all_types_of_the_type():
    raw = pc.parse_query_no_oracle(
        _q("Prefer to stay in a hotel of the type: Charging station.")
    )
    assert raw.get("required_hotel_all_types") == ["Charging station"], raw
    assert not raw.get("hotel_type"), raw.get("hotel_type")


# --- activity_time_windows -------------------------------------------------

def _win(loc, earliest=None, latest=None, end_after=None, end_before=None):
    return {"location": loc, "earliest": earliest, "latest": latest,
            "end_after": end_after, "end_before": end_before}


def test_arrive_no_later_than_sets_latest():
    raw = pc.parse_query_no_oracle(
        _q("We need to arrive at Southern Song Dynasty Imperial City Ruins no later than 08:00.")
    )
    assert raw.get("activity_time_windows") == [
        _win("Southern Song Dynasty Imperial City Ruins", latest="08:00")
    ], raw.get("activity_time_windows")


def test_leave_no_earlier_than_sets_end_after():
    raw = pc.parse_query_no_oracle(
        _q("Hope to leave Big Pear Roast Duck no earlier than 12:00.")
    )
    assert raw.get("activity_time_windows") == [
        _win("Big Pear Roast Duck", end_after="12:00")
    ], raw.get("activity_time_windows")


def test_visit_between_sets_window_and_stay_duration():
    raw = pc.parse_query_no_oracle(
        _q("We wish to visit Feilaifeng Grottoes between 08:10 and 09:40.")
    )
    assert raw.get("activity_time_windows") == [
        _win("Feilaifeng Grottoes", latest="08:10", end_after="09:40")
    ], raw.get("activity_time_windows")
    assert raw.get("stay_duration") == [
        {"location": "Feilaifeng Grottoes", "min_minutes": 90}
    ], raw.get("stay_duration")


def test_numbered_imperative_between_forms_are_contained_windows():
    raw = pc.parse_query_no_oracle(
        _q(
            "Requirements:\n"
            "1. Visit Maple Bridge Scenic Area between 08:15 and 10:05.\n"
            "2. Dine at Jiahong Hotel between 07:45 and 08:40.\n"
            "3. Stay at Jiahong Hotel between 20:10 and 24:00."
        )
    )
    assert raw.get("activity_time_windows") == [
        _win("Maple Bridge Scenic Area", earliest="08:15", end_before="10:05"),
        _win("Jiahong Hotel", earliest="07:45", end_before="08:40"),
        _win("Jiahong Hotel", earliest="20:10", end_before="24:00"),
    ]
    assert raw.get("stay_duration") is None
    assert raw.get("position_presence") == ["Maple Bridge Scenic Area", "Jiahong Hotel"]


def test_oracle_window_location_preserves_apostrophes():
    logic = (
        "result=False\n"
        "for activity in allactivities(plan):\n"
        "  if activity_position(activity)==\"Bear Grandma's Garden\":\n"
        "    if activity_start_time(activity)>=\"17:57\" and "
        "activity_end_time(activity)<=\"19:47\": result=True"
    )
    constraints = solver_constraint_variants(
        {"hard_logic_py": [logic], "nature_language": "", "people_number": 1, "days": 1},
        {},
        use_oracle=True,
    )[0]
    assert constraints.get("activity_time_windows") == [
        _win("Bear Grandma's Garden", earliest="17:57", end_before="19:47")
    ]
    assert constraints.get("position_presence") == ["Bear Grandma's Garden"]


# --- Timing-constraint parsing regression ----------------------------------------------------
#
# parse_timing_constraints matched exactly two of activity_time_windows's patterns
# ("arrive at X no later than T", "leave X no earlier than T") but the oracle never uses this
# family (0/850 matched on the val split; it was pure over-extraction). Both NL patterns are
# still fully covered by activity_time_windows above.


def test_arrive_no_later_than_does_not_emit_timing_constraints():
    raw = pc.parse_query_no_oracle(
        _q("We need to arrive at Southern Song Dynasty Imperial City Ruins no later than 08:00.")
    )
    assert "timing_constraints" not in raw
    assert not hasattr(pc, "parse_timing_constraints")


def test_leave_no_earlier_than_does_not_emit_timing_constraints():
    raw = pc.parse_query_no_oracle(
        _q("Hope to leave Big Pear Roast Duck no earlier than 12:00.")
    )
    assert "timing_constraints" not in raw


# --- position_presence -----------------------------------------------------

def test_position_presence_from_time_constrained_locations():
    raw = pc.parse_query_no_oracle(
        _q("We wish to visit Feilaifeng Grottoes between 08:10 and 09:40.")
    )
    assert raw.get("position_presence") == ["Feilaifeng Grottoes"], raw.get("position_presence")


def test_stay_at_for_minutes_still_supported():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: stay at Grand Museum for at least 60 minutes.")
    )
    assert {"location": "Grand Museum", "min_minutes": 60} in (raw.get("stay_duration") or []), raw
    assert "Grand Museum" in (raw.get("position_presence") or []), raw
