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
