"""Edge cases of the 2026-08-06 phrasing fix that the paired-set tests do not pin.

``tests/phase2/test_parser_phrasing_generalization.py`` covers the main contract (bare total
budgets, scoped budgets staying scoped, plain room wording, familiar-100 byte-identity). This file
adds only the cases found by the 2026-08-06 released-data audit behind
``results/phase2_baselines/screens/20260806_llm_arms/README.md`` that are not covered there:
comma-grouped amounts, "limited to" qualifiers, an amount with no connector at all, the
earliest-match rule for "two single beds", and a bed word that is really part of a POI name.
"""

from __future__ import annotations

import pytest

from parse_constraints import parse_budget, parse_room_type


@pytest.mark.parametrize(
    "text,expected",
    [
        # Comma-grouped amounts. The pre-fix "total budget" pattern read "total budget of 10,000"
        # as 10.0 -- a 1000x error, live on hf_human uid h20241029143812547929.
        ("The total budget of 10,000 must not be exceeded.", 10000.0),
        ("Our budget is 15,000 RMB.", 15000.0),
        ("with a budget of 8,000 yuan", 8000.0),
        # Qualifier vocabulary observed in the human-written set.
        ("The budget is limited to 50,000 RMB.", 50000.0),
        ("We have a budget capped at 3000 RMB.", 3000.0),
        # No connector at all: "Budget travel in Beijing, budget 1000, travel by train."
        ("Budget travel in Beijing, budget 1000, travel by train.", 1000.0),
    ],
)
def test_total_budget_edge_phrasings(text, expected):
    assert parse_budget(text).get("total") == expected


def test_small_amount_is_not_a_total_budget():
    # A trip total in the released data is in the hundreds at least; a single-digit number after
    # the word "budget" is a count or a day, not money.
    assert "total" not in parse_budget("Our budget is 3 days and we want a budget of 4.")


def test_two_single_beds_is_twin_not_single():
    # room_type is the bed count per room (verifier: the hotel's ``numbed``), so "two beds" is 2
    # whatever the beds are called. Earliest match wins, so the "two ... beds" reading beats the
    # "single bed" substring inside it.
    assert parse_room_type("a room with two single beds") == "twin"


def test_bed_word_inside_a_poi_name_is_not_a_room_type():
    # familiar-100 carries "Chimelong Ocean Kingdom" in 5 queries, none with a room_type clause;
    # the "king" alternative must require an actual bed.
    assert parse_room_type("Visit Chimelong Ocean Kingdom on day 2.") is None
