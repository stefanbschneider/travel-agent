"""Tests for the cross-phrasing generalization probe (scripts/phase2_generalization_probe.py).

The probe's conclusions in ``results/phase2_baselines/screens/20260806_generalization_probe/``
rest on two contracts, both asserted here:

- ``clause_is_covered`` maps a real oracle ``hard_logic_py`` clause to the solver-dict families that
  could satisfy it, honouring the ``result_list`` disjunction shape (any arm suffices) versus the
  plain conjunctive shape (every kind must be covered);
- ``clause_gap_kind`` separates a **parse gap** (the oracle dict carries a covering family, our parse
  does not -- phrasing evidence) from a **schema gap** (no family in the vocabulary can express the
  clause, so the oracle side drops it too -- no phrasing signal). Conflating the two is what would
  make familiar-100 look like it has extraction gaps when it has none.

Clause texts below are verbatim shapes from the released data (familiar-100 and HF
LAMDA-NeSy/ChinaTravel), trimmed only in the literal values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

probe = pytest.importorskip("phase2_generalization_probe")


TOTAL_COST_CLAUSE = (
    "total_cost=0 \nfor activity in allactivities(plan):\n"
    "    total_cost+=activity_cost(activity)\n"
    "    total_cost += innercity_transport_cost(activity_transports(activity))\n"
    "result=(total_cost<=1500)"
)
DAYS_CLAUSE = "result=(day_count(plan)==2)"
ROOM_TYPE_CLAUSE = (
    "result=True\nfor activity in allactivities(plan):\n"
    "  if activity_type(activity)=='accommodation' and room_type(activity)!=2: result=False"
)
EXCLUDED_HOTEL_TYPE_CLAUSE = (
    "accommodation_type_set=set()\nfor activity in allactivities(plan):\n"
    "  if activity_type(activity)=='accommodation': "
    "accommodation_type_set.add(accommodation_type(activity, target_city(plan)))\n"
    'result=not({"Media Room"}&accommodation_type_set)'
)
DISJUNCTIVE_CLAUSE = (
    "result_list=[]\nattraction_type_set=set()\nfor activity in allactivities(plan):\n"
    "  if activity_type(activity)=='attraction': "
    "attraction_type_set.add(attraction_type(activity, target_city(plan)))\n"
    'result=({"park"}<=attraction_type_set)\nresult_list.append(result)\n'
    "total_cost=0 \nfor activity in allactivities(plan):\n"
    "    total_cost+=activity_cost(activity)\n"
    "result=(total_cost<=6100)\nresult_list.append(result)\n"
    "result=False\nfor r in result_list:\n  result = result or r"
)


def test_metadata_clause_needs_no_extracted_family():
    """A day-count clause is guaranteed by trip metadata: covered even with an empty parse."""
    covered, kinds = probe.clause_is_covered(DAYS_CLAUSE, set())
    assert covered is True
    assert kinds == ("days",)


def test_budget_clause_uncovered_without_budgets_family():
    covered, kinds = probe.clause_is_covered(TOTAL_COST_CLAUSE, {"taxi_cars_equals"})
    assert covered is False
    assert "cost_total" in kinds

    covered, _ = probe.clause_is_covered(TOTAL_COST_CLAUSE, {"budgets"})
    assert covered is True


def test_room_type_clause_needs_room_type_family():
    assert probe.clause_is_covered(ROOM_TYPE_CLAUSE, set())[0] is False
    assert probe.clause_is_covered(ROOM_TYPE_CLAUSE, {"room_type"})[0] is True


def test_disjunctive_clause_is_covered_by_any_single_arm():
    """``result_list`` clauses are ORs, so covering one arm is enough -- covering neither is not."""
    kinds, disjunctive = probe.classify_clause(DISJUNCTIVE_CLAUSE)
    assert disjunctive is True
    assert {"attraction_type", "cost_total"} <= set(kinds)

    assert probe.clause_is_covered(DISJUNCTIVE_CLAUSE, {"budgets"})[0] is True
    assert probe.clause_is_covered(DISJUNCTIVE_CLAUSE, {"required_attraction_types"})[0] is True
    assert probe.clause_is_covered(DISJUNCTIVE_CLAUSE, {"room_type"})[0] is False


def test_conjunctive_clause_needs_every_kind_covered():
    """The same two kinds without the ``result_list`` wrapper are a conjunction."""
    conjunctive = TOTAL_COST_CLAUSE + "\nif activity_type(activity)=='accommodation' and room_type(activity)!=2: result=False"
    assert probe.clause_is_covered(conjunctive, {"budgets"})[0] is False
    assert probe.clause_is_covered(conjunctive, {"budgets", "room_type"})[0] is True


def test_parse_gap_vs_schema_gap():
    """Only a clause the oracle dict *can* express counts as phrasing evidence."""
    # Oracle expresses the budget, our parse does not -> phrasing failure.
    assert probe.clause_gap_kind(TOTAL_COST_CLAUSE, set(), {"budgets"}) == "parse_gap"
    # Excluded accommodation *type* has no family in the vocabulary: the oracle drops it too.
    assert probe.clause_gap_kind(
        EXCLUDED_HOTEL_TYPE_CLAUSE, set(), {"budgets", "activity_time_windows"}
    ) == "schema_gap"


def test_kind_families_only_reference_real_solver_dict_names():
    """Guard against a typo silently inflating the parse-gap count: every family named in the
    rules must exist in the solver-dict vocabulary the parsed and oracle sides actually emit."""
    from chinatravel.agent.tpc_agent import parsed_verifier  # noqa: F401

    known = {
        "activity_time_windows", "budgets", "conditional_transport", "cuisine_preference",
        "excluded_attraction_types", "excluded_attractions", "excluded_cuisine_types",
        "excluded_hotels", "excluded_inner_transport", "excluded_restaurants",
        "free_attractions_only", "hotel_nearby", "hotel_type", "intercity_mode",
        "poi_distance_hotel", "position_presence", "required_attraction_types",
        "required_attractions", "required_hotel_all_types", "required_hotel_any_types",
        "required_hotels", "required_order", "required_restaurants", "room_type",
        "stay_duration", "taxi_cars_equals",
    }
    for _kind, _markers, families in probe.CLAUSE_KIND_RULES:
        assert set(families) <= known, f"unknown solver-dict family in rules: {set(families) - known}"


def test_phrasing_fingerprint_separates_the_two_registers():
    templated = ("We are 2 people traveling from Nanjing to Guangzhou for 2 days. Requirements: "
                 "1. The trip must last 2 days. 2. The plan must be for 2 travelers.")
    prose = ("Current location: Shanghai. I want to travel to Hangzhou alone for a day with a "
             "budget of 1500 RMB. Please provide me with a travel plan.")
    bracketed = ("[Current location: Shanghai, Destination: Suzhou, Number of travelers: 2] "
                 "I want to take my eldest son to Suzhou.")

    assert probe.phrasing_fingerprint(templated)["has_requirements_list"] is True
    assert probe.phrasing_fingerprint(prose)["has_requirements_list"] is False
    assert probe.phrasing_fingerprint(bracketed)["has_bracket_header"] is True
    assert probe.phrasing_fingerprint(templated)["has_bracket_header"] is False
