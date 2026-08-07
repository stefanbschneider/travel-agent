"""Phrasing generalization of the two value-clean constraint families: budgets, room_type.

Why these exist: the v1 submission scored 33.2473 held-out against 64.17 on familiar-100, and the
2026-08-06 generalization probe
(``results/phase2_baselines/screens/20260806_generalization_probe/README.md``) measured the cause --
the no-oracle extractor recognised a *total* budget only through the familiar-100 template line or
the literal word "total", and a room type only after a trigger verb. Ordinary released prose
("with a budget of 6000 RMB", "stay in two twin rooms") produced neither family, so those clauses
were never even attempted.

Two properties are pinned here:

1. the new bare phrasings extract (``budgets["total"]``, ``room_type``);
2. they can never *steal* an amount that belongs to a scoped budget family, and they cannot fire on
   familiar-100 text at all -- the last one is asserted as byte-identity against a verbatim copy of
   the pre-fix extractors over all 100 familiar-100 queries, so "familiar-100 is unchanged" is a
   test, not a claim.
"""

from __future__ import annotations

import argparse
import re

import pytest

import parse_constraints as pc
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants


def _q(nl, people=2, days=3):
    return {"nature_language": nl, "people_number": people, "days": days,
            "start_city": "Shanghai", "target_city": "Hangzhou", "uid": "t"}


# --- 1. bare total budget ---------------------------------------------------

def test_bare_budget_of_n_rmb_is_a_total():
    assert pc.parse_budget("I want to travel to Hangzhou alone for a day with a budget of 1500 "
                           "RMB.") == {"total": 1500.0}


def test_bare_budget_reaches_the_solver_dict_as_budgets_total():
    """The family has to survive the whole no-oracle parse -> solver-dict path, not just the
    helper: the probe counts solver-dict families, and so does the solver."""
    raw = pc.parse_query_no_oracle(
        _q("Three of us want to visit Chengdu for 3 days with a budget of 6000 RMB.", people=3)
    )
    assert raw.get("budgets") == {"total": 6000.0}, raw
    variants = solver_constraint_variants(_q("Three of us want to visit Chengdu for 3 days with a "
                                             "budget of 6000 RMB.", people=3), raw,
                                          use_oracle=False)
    assert variants and variants[0].get("budgets") == {"total": 6000.0}, variants


@pytest.mark.parametrize("text,value", [
    ("with a budget of 6000 RMB", 6000.0),
    ("with a budget of 3,500 RMB. I plan to take the train.", 3500.0),
    ("Our budget is 3000 yuan, and we need two twin rooms for the nights.", 3000.0),
    ("The budget is 4000.", 4000.0),
    ("efficient city transportation, with a travel budget of 4000", 4000.0),
    ("with a budget of around 8,000 yuan for both of us", 8000.0),
    ("hoping to keep the total budget under 3000 yuan", 3000.0),
    ("we want to keep it within 3000 RMB", 3000.0),
    ("Budget travel in Beijing, budget 1000, travel by train", 1000.0),
])
def test_released_prose_total_budget_phrasings(text, value):
    assert pc.parse_budget(text).get("total") == value, text


# --- 2. a scoped budget must never become the total ------------------------

@pytest.mark.parametrize("text,key,value", [
    ("The accommodation budget of 400.", "accommodation", 400.0),
    ("My accommodation budget is 400", "accommodation", 400.0),
    ("a budget of 400 for accommodation", "accommodation", 400.0),
    ("the sightseeing budget is 120.0", "sightseeing", 120.0),
    ("the dining budget is 300", "dining", 300.0),
    ("Requirement: the intra-city transportation budget is 150.0.", "inner_transport", 150.0),
    ("Requirement: the cross-city transportation budget is 2300.0.", "intercity_transport", 2300.0),
    ("Intra-city travel budget of 50.0", "inner_transport", 50.0),
])
def test_scoped_budget_keeps_its_own_key_and_sets_no_total(text, key, value):
    budgets = pc.parse_budget(text)
    assert budgets.get(key) == value, budgets
    assert "total" not in budgets, budgets


def test_scoped_accommodation_budget_of_400_does_not_set_total():
    """The single case named in the probe's §6 spec, kept explicit rather than parametrized."""
    budgets = pc.parse_budget("Our accommodation budget of 400 should be enough.")
    assert budgets == {"accommodation": 400.0}, budgets


@pytest.mark.parametrize("text", [
    # per-unit rates: the oracle's total_cost is plan-wide, so reading a per-meal / per-night /
    # per-head rate as the trip total would impose an unsatisfiable budget.
    "I plan to spend no more than 70 RMB per meal. Please provide me with a travel itinerary.",
    "We plan to spend no more than 100 RMB per person per meal.",
    "Our budget is 6000 RMB per person",
    "a budget of 500 yuan per day",
    # no amount at all -- "budget" as an adjective must not pick up an unrelated later number.
    "Please help me draft a budget-friendly plan for 3 days.",
    "My budget is limited, so I hope to visit places with free entry for 2 people.",
    "I am looking to travel on a budget, so I hope the attractions are free.",
])
def test_no_spurious_total_budget(text):
    assert "total" not in pc.parse_budget(text), text


def test_familiar_within_template_never_reads_as_a_total():
    """familiar-100 says "Keep the <scope> cost within N" with no currency word. The bare
    within-alternative requires a currency token precisely so this cannot be re-read as a total."""
    budgets = pc.parse_budget("5. Keep the accommodation cost within 342.\n"
                              "6. Keep the dining cost within 268.")
    assert budgets == {"accommodation": 342.0, "dining": 268.0}, budgets


# --- 3. plain room-type wording -------------------------------------------

@pytest.mark.parametrize("text,expected", [
    # twin == two beds
    ("The three of us want to visit Beijing for 2 days and stay in two twin rooms.", "twin"),
    ("We will book a twin room.", "twin"),
    ("We need to book two twin-bed rooms", "twin"),
    ("We plan to travel round-trip by train and stay in a room with two beds.", "twin"),
    # "double room" (a two-person room) is two beds -- the opposite of "double BED room"
    ("stay in a hotel with a sauna, a double room is sufficient.", "twin"),
    # single == one bed, whatever it is called
    ("I plan to take the train round-trip and stay in a single room.", "single"),
    ("plan to book a single-bed room", "single"),
    ("I want to take my child to Suzhou for 3 days and stay in a big bed room.", "single"),
    ("stay in a hotel with a large bed", "single"),
    ("We plan to travel round-trip by train and stay in a room with a double bed.", "single"),
    # neither: a room *count* is not a room type, and an ambiguous name carries no bed count
    ("We plan to travel round-trip by train and stay in two rooms.", None),
    ("We only need one room.", None),
    ("My family and I want to visit Guangzhou for 3 days and stay in a family room.", None),
    # hotel feature-type lists and POI names must not be read as a room type
    ("Include the following hotel feature types: Mountain View Room.", None),
    ("Do not include any of these hotel feature types: Media Room.", None),
    ("Dine at Old Zhou's Shunde Double-Skin Milk between 12:17 and 13:32.", None),
    ("We want to visit the Twin Pagodas.", None),
])
def test_plain_room_wording(text, expected):
    assert pc.parse_room_type(text) == expected, text


def test_familiar_bed_room_templates_unchanged():
    assert pc.parse_room_type("Each accommodation stay must use twin-bed rooms.") == "twin"
    assert pc.parse_room_type("Each accommodation stay must use single-bed rooms.") == "single"


# --- 4. familiar-100 floor: byte-identical to the pre-fix extractors -------
#
# Verbatim copies of the two extractors as they were before the 2026-08-06 phrasing fix (commit
# 2e996eb6). Kept here, not imported, precisely so the floor test cannot drift with the code it
# guards: if any familiar-100 query's budgets/room_type parse changes, this fails.

_PRE_FIX_TOTAL = re.compile(r"total\s*(?:travel\s*|trip\s*)?budget[^0-9]*?([\d]+(?:\.[\d]+)?)", re.I)
_PRE_FIX_ROOM = re.compile(
    r"(?:stay\s+in\s+(?:a\s+)?|prefer\s+(?:a\s+)?|want\s+|(?:must\s+)?use\s+)"
    r"(single-bed|double-bed|twin-bed|single\s+bed|double\s+bed|twin)\s*rooms?", re.I)


def _pre_fix_budget(text):
    budgets = {}
    for key, pattern in pc._LINE_SCOPED_BUDGET_PATTERNS:
        match = pattern.search(text)
        if match:
            budgets[key] = float(match.group("value"))
    for key, patterns in (
        ("sightseeing", (
            r"(?:sightseeing|attractions?\s+)budget[^0-9]*?([\d]+(?:\.[\d]+)?)",
            r"budget\s+for\s+sightseeing[^0-9]*?([\d]+(?:\.[\d]+)?)",
            r"(?:the\s+)?sightseeing\s+budget\s+is\s+([\d]+(?:\.[\d]+)?)",
            r"(?:a\s+)?budget\s+of\s+([\d]+(?:\.[\d]+)?)\s+for\s+sightseeing")),
        ("accommodation", (
            r"(?:accommodation|hotel|lodging)\s*budget[^0-9]*?([\d]+(?:\.[\d]+)?)",
            r"budget\s+for\s+accommodation[^0-9]*?([\d]+(?:\.[\d]+)?)",
            r"(?:a\s+)?budget\s+of\s+([\d]+(?:\.[\d]+)?)\s+for\s+accommodation")),
        ("dining", (
            r"(?:dining|meal|food|restaurant)\s*budget[^0-9]*?([\d]+(?:\.\d+)?)",
            r"budget\s+for\s+(?:dining|meals|food)[^0-9]*?([\d]+(?:\.\d+)?)")),
    ):
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                budgets[key] = float(m.group(1))
                break
    m = _PRE_FIX_TOTAL.search(text)
    if m:
        budgets["total"] = float(m.group(1))
    return budgets


def _pre_fix_room_type(text):
    m = _PRE_FIX_ROOM.search(text)
    if m:
        rt = m.group(1).lower()
        if "single" in rt:
            return "single"
        if "double" in rt:
            return "double"
        return "twin"
    if re.search(r"stay\s+in\s+(?:a\s+)?twin\s+rooms?", text, re.I):
        return "twin"
    return None


@pytest.fixture(scope="module")
def familiar_100_texts():
    from chinatravel.data.load_datasets import load_query

    ids, data = load_query(argparse.Namespace(splits="tpc_phase2_familiar_100", lang="en",
                                              oracle_translation=False))
    return [(uid, data[uid].get("nature_language") or "") for uid in ids]


def test_familiar_100_is_present(familiar_100_texts):
    assert len(familiar_100_texts) == 100


def test_familiar_100_budget_parse_is_byte_identical(familiar_100_texts):
    changed = [(uid, _pre_fix_budget(t), pc.parse_budget(t))
               for uid, t in familiar_100_texts if _pre_fix_budget(t) != pc.parse_budget(t)]
    assert changed == [], changed


def test_familiar_100_room_type_parse_is_byte_identical(familiar_100_texts):
    changed = [(uid, _pre_fix_room_type(t), pc.parse_room_type(t))
               for uid, t in familiar_100_texts
               if _pre_fix_room_type(t) != pc.parse_room_type(t)]
    assert changed == [], changed


def test_familiar_100_contains_no_budget_wording(familiar_100_texts):
    """The structural reason the guard holds: there is no familiar-100 text for the new
    alternatives to fire on. If a future dataset refresh introduces the word, the floor tests above
    stop being trivially safe -- this test is the tripwire that says so."""
    with_budget = [uid for uid, t in familiar_100_texts if re.search(r"\bbudget", t, re.I)]
    assert with_budget == [], with_budget
    with_currency_within = [uid for uid, t in familiar_100_texts
                            if re.search(r"within\s+\d[\d,.]*\s*(?:RMB|CNY|yuan|元)", t, re.I)]
    assert with_currency_within == [], with_currency_within
