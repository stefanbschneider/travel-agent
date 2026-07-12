"""Parser-accuracy regression tests (Phase A): deterministic no-oracle fixes.

A1: derive taxi_cars_equals from people_number.
A2: restaurant negation guard + bogus cuisine cleanup.
A3: budget category disambiguation (cross-city must not leak into inner_transport).

These lock in the concrete parser bugs found in the val-split analysis.
"""

from __future__ import annotations

import math

import pytest

import parse_constraints as pc
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants
from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2.orchestrator import Flags


def _q(nl, people=2, days=2):
    return {
        "nature_language": nl,
        "people_number": people,
        "days": days,
        "start_city": "Shanghai",
        "target_city": "Nanjing",
        "uid": "t",
    }


# --- A1: taxi_cars_equals derivation ---------------------------------------

@pytest.mark.parametrize("people,expected", [(1, 1), (2, 1), (3, 1), (4, 1), (5, 2), (8, 2), (9, 3)])
def test_taxi_cars_equals_derived_from_people(people, expected):
    raw = pc.parse_query_no_oracle(_q("A simple trip.", people=people))
    assert raw.get("taxi_cars_equals") == expected == math.ceil(people / 4)


def test_taxi_cars_equals_survives_disjunction_expansion():
    # A genuinely disjunctive, recoverable query; every expanded branch keeps the global taxi count.
    nl = ("We are 5 people for a trip and must satisfy at least one of the following:\n"
          "1. Want to visit Cultural Landscape\n"
          "2. Do not want to visit Confucius Temple")
    q = _q(nl, people=5)
    ir = normalize.parse_to_ir(q, flags=Flags(disjunction=True))
    variants = normalize.ir_to_solver_variants(ir, q, flags=Flags(disjunction=True))
    assert len(variants) >= 2, "query should expand into >=2 branches"
    for v in variants:
        assert v.get("taxi_cars_equals") == 2, v


# --- A2: restaurant negation guard -----------------------------------------

def test_negated_restaurant_is_excluded_not_required():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: we do not want to try the following restaurant: West Dyke Thick Steak.")
    )
    assert not raw.get("required_restaurants"), raw.get("required_restaurants")
    assert raw.get("excluded_restaurants") == ["West Dyke Thick Steak"]
    # no bogus cuisine leakage
    assert raw.get("cuisine_preference") in (None, [], ""), raw.get("cuisine_preference")


def test_positive_restaurant_still_required():
    raw = pc.parse_query_no_oracle(
        _q("We want to dine at the following restaurant: Grandma's Home.")
    )
    assert raw.get("required_restaurants") == ["Grandma's Home"]
    assert not raw.get("excluded_restaurants")


def test_negated_restaurant_type_is_excluded_cuisine():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: do not want to try restaurants of the type Snacks.")
    )
    # must NOT produce a garbage required_restaurants entry
    assert not raw.get("required_restaurants"), raw.get("required_restaurants")
    assert raw.get("excluded_cuisine_types") == ["Snacks"], raw


def test_negated_plural_restaurants_are_excluded():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: do not want to try the following restaurants: Rest A and Rest B.")
    )
    assert not raw.get("required_restaurants"), raw.get("required_restaurants")
    assert raw.get("excluded_restaurants") == ["Rest A", "Rest B"], raw


def test_negated_the_restaurant_singular_is_excluded():
    raw = pc.parse_query_no_oracle(
        _q("Must: do not want to try the restaurant: Cloud View Hotel Diner.")
    )
    assert not raw.get("required_restaurants"), raw.get("required_restaurants")
    assert raw.get("excluded_restaurants") == ["Cloud View Hotel Diner"], raw


# --- Step 5 (val-split family_stats triage): "restaurants of the following type" ------------


def test_restaurant_of_the_following_type_is_not_a_required_restaurant_name():
    # Regression: the "of (the) type(s)" guard didn't account for "of the FOLLOWING type", so
    # this leaked through as a bogus required_restaurants entry (val-split top spurious family).
    raw = pc.parse_query_no_oracle(
        _q("We hope to try restaurants of the following type: Shanghai cuisine.")
    )
    assert not raw.get("required_restaurants"), raw.get("required_restaurants")


def test_restaurant_of_the_following_type_is_cuisine_preference():
    raw = pc.parse_query_no_oracle(
        _q("We hope to try restaurants of the following type: Shanghai cuisine.")
    )
    assert raw.get("cuisine_preference") == "Shanghai cuisine", raw


def test_negated_restaurant_of_the_following_type_is_excluded_not_preferred():
    # The new "restaurants of (the) (following) type(s)" cuisine_preference pattern must respect
    # negation (the trigger sits ~15 chars before "restaurants", outside a naive adjacent check).
    raw = pc.parse_query_no_oracle(
        _q("Do not want to try restaurants of the type Sichuan cuisine.")
    )
    assert raw.get("cuisine_preference") in (None, [], ""), raw.get("cuisine_preference")
    assert raw.get("excluded_cuisine_types") == ["Sichuan cuisine"], raw


# --- A3: budget category disambiguation ------------------------------------

def test_cross_city_budget_does_not_leak_into_inner_transport():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: the cross-city transportation budget is 2300.0.")
    )
    b = raw.get("budgets") or {}
    assert b.get("intercity_transport") == 2300.0, b
    assert "inner_transport" not in b, b


def test_intercity_budget_wording_does_not_leak():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: the intercity transportation budget is 2700.0.")
    )
    b = raw.get("budgets") or {}
    assert b.get("intercity_transport") == 2700.0, b
    assert "inner_transport" not in b, b


def test_genuine_inner_transport_budget_still_parsed():
    raw = pc.parse_query_no_oracle(
        _q("Requirement: the intra-city transportation budget is 150.0.")
    )
    b = raw.get("budgets") or {}
    assert b.get("inner_transport") == 150.0, b


# --- 1c: negation guard extended to hotels ---------------------------------

def test_negated_hotels_are_excluded_not_required():
    # Real val query 20250320230800586344 shape: "Do not wish to stay at the
    # following hotels: X and Y" previously also emitted a spurious required_hotels.
    raw = pc.parse_query_no_oracle(
        _q("Do not wish to stay at the following hotels: Yucheng Hotel (Wuhan) "
           "and All Seasons Hotel (Wuhan).")
    )
    assert not raw.get("required_hotels"), raw.get("required_hotels")
    assert raw.get("excluded_hotels") == [
        "Yucheng Hotel (Wuhan)",
        "All Seasons Hotel (Wuhan)",
    ], raw.get("excluded_hotels")


def test_negated_hotels_short_form_excluded():
    raw = pc.parse_query_no_oracle(
        _q("Do not want to stay at Modern Classic Hotel and Holiday Inn Express Dongmen.")
    )
    assert not raw.get("required_hotels"), raw.get("required_hotels")
    assert raw.get("excluded_hotels") == [
        "Modern Classic Hotel",
        "Holiday Inn Express Dongmen",
    ], raw.get("excluded_hotels")


def test_positive_hotel_still_required():
    raw = pc.parse_query_no_oracle(
        _q("We want to stay at one of the following hotels: Huayueju Serviced Apartment.")
    )
    # The negation guard must not suppress a positive hotel requirement: the clean
    # hotel name is still present (a pre-existing "one of the following hotels:" prefix
    # over-extraction is out of scope here and harmless -- the verifier matches by `any`).
    req = raw.get("required_hotels") or []
    assert "Huayueju Serviced Apartment" in req, req
    assert not raw.get("excluded_hotels"), raw.get("excluded_hotels")


# --- 1c: negation guard extended to attractions ----------------------------

def test_negated_attraction_types_do_not_leak_into_required():
    # Real val query 20250321111720443608: a positive "visit X" clause followed by
    # a negated "do not want to visit any Museum/... or university campus" clause.
    raw = pc.parse_query_no_oracle(
        _q("We want to visit Xixi Paradise Commercial Street and do not want to "
           "visit any Museum/Memorial Hall or university campus.")
    )
    # positive name survives ...
    assert raw.get("required_attractions") == ["Xixi Paradise Commercial Street"], raw
    # ... but the negated types must NOT be required
    req_types = raw.get("required_attraction_types") or []
    assert "Museum/Memorial Hall" not in req_types, raw
    assert "university campus" not in req_types, raw
    # they belong to the excluded set instead
    excl_types = raw.get("excluded_attraction_types") or []
    assert "Museum/Memorial Hall" in excl_types, raw
    assert "university campus" in excl_types, raw


def test_negated_attraction_name_not_required():
    raw = pc.parse_query_no_oracle(
        _q("We do not want to visit West Yellow Temple and Hall of Benevolent Longevity.")
    )
    assert not raw.get("required_attractions"), raw.get("required_attractions")


def test_positive_attraction_still_required():
    raw = pc.parse_query_no_oracle(
        _q("We want to visit Xixi Paradise Commercial Street.")
    )
    assert raw.get("required_attractions") == ["Xixi Paradise Commercial Street"], raw


# --- 5a: poi_distance_hotel schema parity (real val uids) ------------------
#
# The no-oracle NL path already extracts "accommodation within X km of Y" correctly via
# parse_hotel_nearby, but only stored it as the singular `hotel_nearby` dict -- the oracle (and
# the shared solver-dict schema) also expects a list-shaped `poi_distance_hotel` family, which the
# oracle-mode DSL converter (solver_constraints.py::_parse_hotel_distance) already mirrors. Real
# val uid 20250323092547439734 (oracle: [{"reference": "North Bund Riverside Green Space",
# "distance_km": 8.851522495588497}]) was 100% missing on this family before the fix.

def test_hotel_nearby_also_populates_poi_distance_hotel_list():
    raw = pc.parse_query_no_oracle(
        _q("Accommodation must be within 8.86 km of North Bund Riverside Green Space.")
    )
    assert raw.get("hotel_nearby") == {
        "reference": "North Bund Riverside Green Space", "distance_km": 8.86,
    }
    assert raw.get("poi_distance_hotel") == [
        {"reference": "North Bund Riverside Green Space", "distance_km": 8.86},
    ]


def test_hotel_nearby_strips_leading_the_from_reference():
    # Real val uid 20250323092305147660 phrasing: "... within 2.11 km of the Great Hall of the
    # People." Oracle reference is "Great Hall of the People" (no leading "the").
    raw = pc.parse_query_no_oracle(
        _q("We want accommodation within 2.11 km of the Great Hall of the People.")
    )
    assert raw["hotel_nearby"]["reference"] == "Great Hall of the People"
    assert raw["poi_distance_hotel"][0]["reference"] == "Great Hall of the People"


def test_hotel_nearby_variant_matches_solver_schema_family():
    query = _q("We hope the accommodation is within 9.65 kilometers of Futian District Sports Park.")
    raw = pc.parse_query_no_oracle(query)
    variants = solver_constraint_variants(query, raw, use_oracle=False)
    assert variants[0].get("poi_distance_hotel") == [
        {"reference": "Futian District Sports Park", "distance_km": 9.65},
    ]


# --- 5b: "hotel with X" amenity phrasing -> required_hotel_all_types -------
#
# The oracle never has a `hotel_amenity` family; "hotel with a swimming pool" / "hotel with Free
# parking" / "hotel with an Executive Lounge" are all encoded as required_hotel_all_types (e.g.
# ['Swimming pool'], ['Free parking'], ['Executive Lounge']) -- literally the same string, just the
# wrong family. `hotel_amenity` no longer exists as an output family at all: it was spurious-only
# against the oracle (32/32 val queries) and could reject oracle-acceptable plans.

@pytest.mark.parametrize("phrase,expected", [
    ("we prefer to stay at a hotel that offers free parking.", "Free parking"),
    ("we do not want to stay in hotels with a Sunbathing area.", "Sunbathing area"),
    ("want to stay in a hotel with an Executive Lounge.", "Executive Lounge"),
    ("we want to stay in a hotel with a Family Room.", "Family Room"),
    ("we want to stay at a hotel with a swimming pool.", "Swimming pool"),
    ("wish to stay in a hotel with Free parking.", "Free parking"),
])
def test_hotel_with_amenity_becomes_required_hotel_all_type(phrase, expected):
    raw = pc.parse_query_no_oracle(_q(f"We are 2 people traveling for 3 days. {phrase}"))
    assert expected in (raw.get("required_hotel_all_types") or []), raw
    assert "hotel_amenity" not in raw


def test_hotel_amenity_family_no_longer_produced():
    assert not hasattr(pc, "parse_hotel_amenity")


def test_parsed_verifier_no_longer_enforces_hotel_amenity():
    import inspect
    from chinatravel.agent.tpc_agent import parsed_verifier
    assert "hotel_amenity" not in inspect.getsource(parsed_verifier)


# --- 5c: excluded_cuisine_types word-order gap + cleanup bugs --------------

def test_reversed_word_order_type_of_restaurant_singular():
    # Real val phrasing: "type of restaurant" (singular), not "restaurant of type".
    raw = pc.parse_query_no_oracle(
        _q("2. Do not want to try the following type of restaurant: Hot pot")
    )
    assert raw.get("excluded_cuisine_types") == ["Hot pot"], raw


def test_reversed_word_order_types_of_restaurants_plural_multi():
    raw = pc.parse_query_no_oracle(
        _q("We do not want to try the following types of restaurants: Middle Eastern cuisine "
           "and Northwestern Chinese cuisine.")
    )
    assert raw.get("excluded_cuisine_types") == [
        "Middle Eastern cuisine", "Northwestern Chinese cuisine",
    ], raw


def test_restaurants_serving_x_phrasing():
    raw = pc.parse_query_no_oracle(
        _q("2. Do not want to try restaurants serving fusion cuisine.")
    )
    assert raw.get("excluded_cuisine_types") == ["fusion cuisine"], raw


def test_cuisine_suffix_kept_in_x_cuisine_restaurants_phrasing():
    # Previously dropped the word "cuisine" itself: captured "fusion" instead of "fusion cuisine".
    raw = pc.parse_query_no_oracle(
        _q("2. Do not want to try fusion cuisine restaurants.")
    )
    assert raw.get("excluded_cuisine_types") == ["fusion cuisine"], raw


def test_oxford_comma_and_before_last_item_not_kept():
    raw = pc.parse_query_no_oracle(
        _q("Do not want to try restaurants of types Bar/Pub, Other, and Halal cuisine.")
    )
    assert raw.get("excluded_cuisine_types") == ["Bar/Pub", "Other", "Halal cuisine"], raw


def test_embedded_quotes_stripped():
    raw = pc.parse_query_no_oracle(
        _q('We do not wish to try restaurants of the types "Other Chinese Cuisine" and '
           '"Jiangsu-Zhejiang cuisine."')
    )
    assert raw.get("excluded_cuisine_types") == [
        "Other Chinese Cuisine", "Jiangsu-Zhejiang cuisine",
    ], raw
