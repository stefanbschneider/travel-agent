"""Regression tests for roadmap P12 (close P10's false-positive half).

The 150-query packaged-v1 replay found five "official=no, parsed=yes" semantics the parsed
checker treated as vacuously satisfied (docs/tpc_phase2_roadmap.md#p12). Investigating each
against real released-data phrasing/hard_logic_py (Phase 1, permitted for offline dev per
CLAUDE.md's phase boundary -- no held-out uid or field was read) found two were genuine
representation gaps and closed them here; the other three were already correctly represented
by the existing ``required_restaurants`` / ``required_attractions`` / ``budgets.inner_transport``
checks, so those get a regression lock instead of a new check:

1. **Required visit ordering** -- no field existed at all (``required_order``, new: parser in
   parse_constraints.py + checker in parsed_verifier.py).
2. **Meal end-time window** -- the oracle gates a "Dine at X between A and B" / "Stay at X
   between A and B" window by *activity type*, not location alone (the same POI name routinely
   carries both, e.g. a hotel with an on-site restaurant); the parser already recorded the verb's
   ``activity_types`` but the checker discarded it, so an accommodation activity could satisfy a
   meal-only window purely by time overlap. Fixed by threading ``activity_types`` through
   ``acts_at()``.
3-5. Required restaurant lists, required attraction lists, and the inner-transport budget were
   already correct on every case tried here; the residual gap for those, if any, is parser
   *recall* on the specific held-out phrasing, not a checker representation gap -- out of scope
   without the held-out artifacts (see the roadmap item's own "where the evidence lives" note).

Both fixes were corpus-scanned against every locally available query (the 1000-query
``TPC_IJCAI_2026_phase1_EN`` set plus the 100-query familiar-100 set, 1100 total -- Phase 1 data,
offline dev, permitted; the same corpus ``test_parser_accuracy.py``'s 5d section cites) before
landing, not just spot-checked against the three/one examples below:

- ``parse_required_order`` vs. the oracle's ``idx_activity0``/``idx_activity1`` DSL: 3 NL hits,
  3 oracle hits, the same 3 uids, the same names in the same order both sides -- zero spurious,
  zero missed.
- the ``activity_types`` a contained "<verb> X between A and B" window carries, vs. the
  ``activity_type(activity)`` gate on the matching oracle clause (matched by location + start/end):
  149 type-bearing windows, zero mismatches, zero unmatched -- covers every "visit"/"dine at"/
  "stay at" instance the corpus has, so ``_WINDOW_VERB_ACTIVITY_TYPES`` is not just plausible on
  the one dine+stay example below, it is exact everywhere it was checkable offline.
"""

from __future__ import annotations

import parse_constraints as pc
from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints

TARGET_CITY = "Shanghai"


def _act(type_, position, start, end, cost=0, transports=None):
    return {
        "type": type_,
        "position": position,
        "start_time": start,
        "end_time": end,
        "cost": cost,
        "transports": transports or [],
    }


def _plan(days):
    return {
        "people_number": 2,
        "start_city": "Beijing",
        "target_city": TARGET_CITY,
        "itinerary": [{"day": i + 1, "activities": day_acts} for i, day_acts in enumerate(days)],
    }


# --- 1. Required visit ordering --------------------------------------------------------------


def test_required_order_field_did_not_exist_is_now_checked():
    plan = _plan([[
        _act("attraction", "B Museum", "09:00", "10:00"),
        _act("attraction", "A Park", "11:00", "12:00"),
    ]])
    # A visits after B: violates "A Park" before "B Museum".
    res = evaluate_parsed_constraints({"required_order": ["A Park", "B Museum"]}, plan, TARGET_CITY)
    assert res == [False], res


def test_required_order_satisfied():
    plan = _plan([[
        _act("attraction", "A Park", "09:00", "10:00"),
        _act("attraction", "B Museum", "11:00", "12:00"),
    ]])
    res = evaluate_parsed_constraints({"required_order": ["A Park", "B Museum"]}, plan, TARGET_CITY)
    assert res == [True], res


def test_required_order_fails_closed_when_a_poi_is_missing():
    # The oracle's own index-comparison DSL initializes both indices to 0, so a plan that omits
    # the first POI but visits the second anywhere can flip the oracle check True by accident.
    # The parsed checker deliberately does not mirror that quirk (stricter, never more lenient).
    plan = _plan([[_act("attraction", "B Museum", "09:00", "10:00")]])
    res = evaluate_parsed_constraints({"required_order": ["A Park", "B Museum"]}, plan, TARGET_CITY)
    assert res == [False], res


def test_parse_required_order_matches_real_released_phrasing():
    # Real Phase 1 NL (TPC_IJCAI_2026_phase1_EN, both real generator templates).
    assert pc.parse_required_order(
        "we want to visit Optics Valley International Tennis Center first, then "
        "The Boots Muddy Boots & MINI (Optics Valley Branch)."
    ) == ["Optics Valley International Tennis Center", "The Boots Muddy Boots & MINI (Optics Valley Branch)"]
    assert pc.parse_required_order(
        "first go to Squirrel Paradise, then Chef's Wife in Charge (East Lake Branch)."
    ) == ["Squirrel Paradise", "Chef's Wife in Charge (East Lake Branch)"]


def test_parse_required_order_chain_split_is_case_insensitive():
    # Copilot review (PR #78): the >2-stop chain split on "then" was case-sensitive, so a
    # capitalized "Then" (e.g. starting a new sentence/clause) fell through as part of the
    # previous POI's name instead of splitting.
    assert pc.parse_required_order("visit A first, then B, Then C.") == ["A", "B", "C"]


# --- 2. Meal end-time window (activity-type-gated POI window) --------------------------------


def test_dine_at_window_no_longer_satisfied_by_a_different_typed_activity_at_same_poi():
    # An accommodation stay at "Grand Hotel" happens to overlap the "dine at Grand Hotel between
    # 07:45 and 08:40" window's time bounds -- it must NOT satisfy a meal-only window.
    plan = _plan([[_act("accommodation", "Grand Hotel", "07:50", "08:00")]])
    window = {
        "location": "Grand Hotel",
        "earliest": "07:45",
        "end_before": "08:40",
        "activity_types": ["breakfast", "lunch", "dinner"],
    }
    res = evaluate_parsed_constraints({"activity_time_windows": [window]}, plan, TARGET_CITY)
    assert res == [False], res


def test_dine_and_stay_windows_on_the_same_poi_are_checked_independently():
    plan = _plan([[
        _act("dinner", "Grand Hotel", "20:00", "20:30"),
        _act("accommodation", "Grand Hotel", "22:00", "24:00"),
    ]])
    dine_window = {
        "location": "Grand Hotel", "earliest": "19:45", "end_before": "20:40",
        "activity_types": ["breakfast", "lunch", "dinner"],
    }
    stay_window = {
        "location": "Grand Hotel", "earliest": "21:45", "end_before": "24:00",
        "activity_types": ["accommodation"],
    }
    res = evaluate_parsed_constraints(
        {"activity_time_windows": [dine_window, stay_window]}, plan, TARGET_CITY
    )
    assert res == [True, True], res


def test_window_without_activity_types_still_matches_any_type_unchanged():
    # The legacy "arrive at/reach X ..." shape carries no verb-derived activity_types; behaviour
    # for it must be unchanged (matches any activity at the position, as before this fix).
    plan = _plan([[_act("attraction", "Some Attraction", "09:00", "10:00")]])
    window = {"location": "Some Attraction", "latest": "09:30"}
    res = evaluate_parsed_constraints({"activity_time_windows": [window]}, plan, TARGET_CITY)
    assert res == [True], res


def test_real_released_dine_at_window_parses_with_activity_types():
    # Real Phase 2 familiar-100 phrasing (phase2_familiar_20250323001701860855_00088).
    windows = pc.parse_activity_time_windows(
        "Dine at Fang Fang Casual Dining (New Town Plaza Branch) between 12:04 and 13:24."
    )
    assert windows == [{
        "location": "Fang Fang Casual Dining (New Town Plaza Branch)",
        "earliest": "12:04",
        "latest": None,
        "end_after": None,
        "end_before": "13:24",
        "activity_types": ["breakfast", "lunch", "dinner"],
    }]


# --- 3-5. Already-correct families: regression locks, not new checks -------------------------


def test_required_restaurants_missing_already_scores_false():
    plan = _plan([[_act("lunch", "Other Restaurant", "12:00", "13:00")]])
    res = evaluate_parsed_constraints(
        {"required_restaurants": ["Famous Duck House"]}, plan, TARGET_CITY
    )
    assert res == [False], res


def test_required_attractions_missing_already_scores_false():
    plan = _plan([[_act("attraction", "Other Park", "09:00", "10:00")]])
    res = evaluate_parsed_constraints(
        {"required_attractions": ["Famous Tower"]}, plan, TARGET_CITY
    )
    assert res == [False], res


def test_inner_transport_budget_exceeded_already_scores_false():
    seg = {
        "start": "A", "end": "B", "mode": "taxi", "start_time": "09:00", "end_time": "09:20",
        "distance": 5.0, "price": 100.0, "cost": 100.0,
    }
    plan = _plan([[_act("attraction", "Some Attraction", "09:20", "11:00", transports=[seg])]])
    res = evaluate_parsed_constraints({"budgets": {"inner_transport": 10.0}}, plan, TARGET_CITY)
    assert res == [False], res


# --- Non-affected floor -----------------------------------------------------------------------


def test_unrelated_family_unaffected_by_this_change():
    plan = _plan([[_act("lunch", "Some Restaurant", "12:00", "13:00")]])
    res = evaluate_parsed_constraints({"cuisine_preference": "Sichuan cuisine"}, plan, TARGET_CITY)
    # No cuisine data reachable without WorldEnv in this unit test -- same [False] the checker
    # returned before this change (restaurant_type_fn falls back to a lookup that finds nothing).
    assert res == [False], res
