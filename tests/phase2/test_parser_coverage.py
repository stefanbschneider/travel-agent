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


# --- "Do not include any of these <category>: ..." (familiar-100 exclusions) ----
# The familiar-100 set states every exclusion with this one uniform template. The older
# "do not want to visit/stay/try ..." patterns never matched it, leaving all five excluded_*
# families at zero recall. See docs/tpc_phase2_roadmap.md.

def test_do_not_include_attractions_names():
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these attractions: Golden Buddha Mountain and Nanshan Scenic Area.")
    )
    assert raw.get("excluded_attractions") == [
        "Golden Buddha Mountain", "Nanshan Scenic Area"
    ], raw.get("excluded_attractions")


def test_do_not_include_attraction_types_kept_verbatim():
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these attraction types: Other and Red tourism sites.")
    )
    # Values stay in the oracle's own vocabulary/casing (not lower-cased via the alias table).
    assert raw.get("excluded_attraction_types") == ["Other", "Red tourism sites"], raw
    # The name family must NOT also fire on the "attraction types" line.
    assert not raw.get("excluded_attractions"), raw.get("excluded_attractions")


def test_do_not_include_hotels_not_confused_with_feature_types():
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these hotels: Xinshan Hotel King Shinning. "
           "Do not include any of these hotel feature types: Media Room.")
    )
    assert raw.get("excluded_hotels") == ["Xinshan Hotel King Shinning"], raw.get("excluded_hotels")


def test_do_not_include_restaurants_names():
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these restaurants: Artful Cafe.")
    )
    assert raw.get("excluded_restaurants") == ["Artful Cafe"], raw.get("excluded_restaurants")
    assert not raw.get("excluded_cuisine_types"), raw.get("excluded_cuisine_types")


def test_do_not_include_restaurant_types_protects_compound_cuisine():
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these restaurant types: Hot pot and Fast food and casual dining.")
    )
    # "Fast food and casual dining" is a single environment cuisine value and must not be split
    # on its internal " and ".
    assert raw.get("excluded_cuisine_types") == [
        "Hot pot", "Fast food and casual dining"
    ], raw.get("excluded_cuisine_types")
    assert not raw.get("excluded_restaurants"), raw.get("excluded_restaurants")


def test_do_not_include_oxford_comma_no_leading_and():
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these attractions: A Park, B Tower, and C Temple.")
    )
    assert raw.get("excluded_attractions") == ["A Park", "B Tower", "C Temple"], raw


def test_compound_cuisine_vocab_not_loaded_without_template():
    # The compound-cuisine CSV scan must stay lazy: parsing text that lacks the
    # "restaurant types" exclusion template should not trigger the filesystem read.
    pc._compound_cuisine_cache = None
    pc.parse_query_no_oracle(_q("We want to try a Hot pot restaurant and visit a museum."))
    assert pc._compound_cuisine_cache is None
    # When the template IS present, the vocab loads and protects the compound value.
    raw = pc.parse_query_no_oracle(
        _q("Do not include any of these restaurant types: Fast food and casual dining.")
    )
    assert raw.get("excluded_cuisine_types") == ["Fast food and casual dining"], raw
    assert pc._compound_cuisine_cache is not None


# --- "<Visit|Dine at|Stay at|Include> the following <category>: ..." (required_* families) ------
# The positive mirror of the "Do not include any of these ..." template; familiar-100 states every
# requirement this way, which the older "want/wish to ..." patterns missed. See the roadmap.

def test_visit_the_following_attractions_names():
    raw = pc.parse_query_no_oracle(
        _q("Visit the following attractions: Golden Buddha Mountain and Nanshan Scenic Area.")
    )
    assert raw.get("required_attractions") == [
        "Golden Buddha Mountain", "Nanshan Scenic Area"
    ], raw.get("required_attractions")
    # The name line must NOT leak into required_attraction_types.
    assert not raw.get("required_attraction_types"), raw.get("required_attraction_types")


def test_include_the_following_attraction_types_verbatim():
    raw = pc.parse_query_no_oracle(
        _q("Include the following attraction types: Museum/Memorial Hall and natural scenery.")
    )
    assert raw.get("required_attraction_types") == [
        "Museum/Memorial Hall", "natural scenery"
    ], raw.get("required_attraction_types")
    assert not raw.get("required_attractions"), raw.get("required_attractions")


def test_dine_at_the_following_restaurants_names():
    raw = pc.parse_query_no_oracle(
        _q("Dine at the following restaurants: Moon Pavilion (Guanqian Branch).")
    )
    assert raw.get("required_restaurants") == ["Moon Pavilion (Guanqian Branch)"], raw
    assert not raw.get("cuisine_preference"), raw.get("cuisine_preference")


def test_include_the_following_restaurant_types_protects_compound():
    raw = pc.parse_query_no_oracle(
        _q("Include the following restaurant types: Sichuan cuisine and Bakery and Desserts.")
    )
    cuisine = raw.get("cuisine_preference")
    assert cuisine == ["Sichuan cuisine", "Bakery and Desserts"], cuisine


def test_include_the_following_hotel_feature_types_all():
    raw = pc.parse_query_no_oracle(
        _q("Include the following hotel feature types: Free parking.")
    )
    assert raw.get("required_hotel_all_types") == ["Free parking"], raw


def test_hotel_feature_types_negated_lead_in_not_required():
    # A negated lead-in ("do not want to include the following ...") is an exclusion, never a hard
    # requirement -- parse_required_hotel_types must not emit a required all_type for it.
    raw = pc.parse_query_no_oracle(
        _q("We do not want to include the following hotel feature types: Free parking.")
    )
    assert not raw.get("required_hotel_all_types"), raw.get("required_hotel_all_types")


def test_stay_at_the_following_hotels_names():
    raw = pc.parse_query_no_oracle(
        _q("Stay at the following hotels: Golden Eagle Summit Hotel and Suning Universal Hotel.")
    )
    assert raw.get("required_hotels") == [
        "Golden Eagle Summit Hotel", "Suning Universal Hotel"
    ], raw.get("required_hotels")


def test_time_windowed_stay_at_is_not_a_required_hotel():
    # "Stay at X between HH:MM and HH:MM" is a time-window/position constraint, not a required-hotel
    # name list -- it must not produce a (junk-valued) required_hotels entry.
    raw = pc.parse_query_no_oracle(
        _q("Stay at Beijing LanWan International Hotel (Capital Airport) between 21:39 and 24:00.")
    )
    assert not raw.get("required_hotels"), raw.get("required_hotels")


def test_room_type_must_use_bed_rooms():
    assert pc.parse_query_no_oracle(
        _q("Each accommodation stay must use twin-bed rooms.")
    ).get("room_type") == "twin"
    assert pc.parse_query_no_oracle(
        _q("Each accommodation stay must use single-bed rooms.")
    ).get("room_type") == "single"


def test_positive_template_guards_against_negation():
    # A negated lead-in must not be read as a positive requirement.
    raw = pc.parse_query_no_oracle(
        _q("We do not want to visit the following attractions: Sea Rainbow.")
    )
    assert not raw.get("required_attractions"), raw.get("required_attractions")
