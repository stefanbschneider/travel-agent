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


# --- 5. free-prose intercity transport mode (P26) ---------------------------
#
# Measured gap before this fix (`scripts/phase2_generalization_probe.py`, `parse_gap_by_kind`):
# `intercity_transport` was the single largest ASCII-literal residual on free prose -- 33 of 85
# oracle clauses missed on HF `medium`, 27 of 32 on HF `human`, against 0 on familiar-100. The
# pre-fix extractor only recognised the family through the literal word "destination" or through
# "take/by/use" immediately followed by the bare mode noun, so an ordinary verb form ("we have
# chosen to fly") or a qualified noun ("by high-speed train (G)") produced nothing.

@pytest.mark.parametrize("text,expected", [
    # verb forms
    ("We have chosen to fly and have a budget of 8,000 RMB.", "airplane"),
    ("We will be flying and booking a twin room, with a budget of 7,000 RMB.", "airplane"),
    ("We plan to fly round-trip and stay in a room with a king-size bed.", "airplane"),
    ("Our family wants to visit Chongqing and we plan to fly there.", "airplane"),
    ("Two people are planning to fly from Guangzhou to Beijing for a four-day trip.", "airplane"),
    ("I would like to fly both ways.", "airplane"),
    # qualified noun forms
    ("I plan to visit Suzhou for two days, traveling by high-speed train (G).", "train"),
    ("We plan to travel by high-speed train both ways and hope to try local food.", "train"),
    ("Round trip by high-speed train (G), with a budget of 2000.", "train"),
    ("They plan to take a round-trip train and wish to experience local cuisine.", "train"),
    ("I plan to take a round-trip high-speed train (G), leaving before 8 AM.", "train"),
    ("A day trip; make sure to catch the train back before 7 PM.", "train"),
    ("We would like to travel by air.", "airplane"),
    ("Booking a direct flight for the two of us.", "airplane"),
])
def test_free_prose_intercity_mode_extracts_both_legs(text, expected):
    """The oracle clause for this family constrains the *set* of intercity legs
    (``intercity_transport_set == {'train'}``), so an undirected statement means every leg."""
    assert pc.parse_intercity_mode(text) == {"outbound": expected, "return": expected}


@pytest.mark.parametrize("text", [
    # A station or airport is a place, not a stated mode of travel.
    "The hotel should be near the train station.",
    "I would like to stay close to the high-speed rail station.",
    "Please book a hotel within 2 km of the airport.",
    # No mode statement at all.
    "We want two rooms and a budget of 5000 RMB.",
    "Please include a visit to the aviation museum.",
    "We would like to see historical sites and avoid a rushed itinerary.",
])
def test_no_spurious_intercity_mode(text):
    """A spurious intercity mode is not free -- it pins both endpoint legs and can invalidate an
    otherwise-passing plan (the P24 lesson), so the free-prose fallback must stay silent here."""
    assert pc.parse_intercity_mode(text) is None


def test_contradictory_free_prose_modes_say_nothing():
    """Both modes named with no direction to attach them to: return no mode rather than guess."""
    assert pc.parse_intercity_mode(
        "We are still deciding whether to fly or to take the high-speed train.") is None


def test_directional_reading_wins_over_the_free_prose_fallback():
    """A mixed request keeps the per-leg reading the directional patterns produce; the undirected
    fallback must not overwrite it with one mode for both legs."""
    got = pc.parse_intercity_mode("We plan to fly to the destination and take the train back.")
    assert got == {"outbound": "airplane", "return": "train"}, got


def test_negation_still_wins_over_the_free_prose_fallback():
    """``do not want to fly to the destination`` must still resolve to the complement (train), not
    be swept up as an affirmative flight statement by the new verb pattern."""
    got = pc.parse_intercity_mode(
        "We do not want to fly to the destination, and we do not want to fly back.")
    assert got == {"outbound": "train", "return": "train"}, got


def test_familiar_100_intercity_parse_is_byte_identical(familiar_100_texts):
    """Structural reason the familiar register cannot move: its template always states the mode in
    the "to the destination" / "back" form the directional patterns already covered, so the new
    undirected fallback never runs. Asserted, not claimed."""
    changed = [(uid, _pre_fix_intercity_mode(t), pc.parse_intercity_mode(t))
               for uid, t in familiar_100_texts
               if _pre_fix_intercity_mode(t) != pc.parse_intercity_mode(t)]
    assert changed == [], changed


def _pre_fix_intercity_mode(text):
    """Verbatim copy of ``parse_intercity_mode``'s body as of `1630bbb7` (before the free-prose
    fallback), kept here rather than imported so the floor cannot drift with the code it guards."""
    outbound = None
    ret = None
    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?take\s+(?:the\s+|an?\s+)?"
        r"(airplane|plane|flight|train)\s+to\s+(?:the\s+)?destination", text, re.I)
    if m:
        excluded = m.group(1).lower()
        outbound = "train" if excluded in ("airplane", "plane", "flight") else "airplane"
    if outbound is None:
        m = re.search(r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?fly\s+to\s+(?:the\s+)?destination",
                      text, re.I)
        if m:
            outbound = "train"
    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?take\s+(?:the\s+|an?\s+)?"
        r"(airplane|plane|flight|train)\s+(?:for\s+the\s+return|back|for\s+return)", text, re.I)
    if m:
        excluded = m.group(1).lower()
        ret = "train" if excluded in ("airplane", "plane", "flight") else "airplane"
    if ret is None:
        m = re.search(r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?fly\s+"
                      r"(?:for\s+the\s+return|back|for\s+return)", text, re.I)
        if m:
            ret = "train"
    if outbound is None:
        m = re.search(
            r"(?:take\s+(?:the\s+|a\s+)?|go\s+by\s+|travel\s+(?:to\s+\w+\s+)?by\s+)"
            r"(train|airplane|plane|flight)\s+to\s+(?:the\s+)?destination", text, re.I)
        if m:
            outbound = "train" if "train" in m.group(1).lower() else "airplane"
    if ret is None:
        m = re.search(r"(?:return|back)\s+by\s+(train|airplane|plane|flight)", text, re.I)
        if not m:
            m = re.search(r"(?:take\s+(?:the\s+|a\s+)?)(train|airplane|plane|flight)\s+"
                          r"(?:back|for\s+the\s+return)", text, re.I)
        if m:
            ret = "train" if "train" in m.group(1).lower() else "airplane"
    if outbound is None:
        m = re.search(r"(?:travel|go)\s+to\s+(?:the\s+)?destination\s+by\s+"
                      r"(train|airplane|plane|flight)", text, re.I)
        if m:
            outbound = "train" if "train" in m.group(1).lower() else "airplane"
    if outbound is None and ret is None:
        m = re.search(r"(?:take|by|use)\s+(?:a\s+|the\s+)?(train|airplane|plane|flight)",
                      text, re.I)
        if m:
            mode = "train" if "train" in m.group(1).lower() else "airplane"
            outbound = mode
            ret = mode
    result = {}
    if outbound:
        result["outbound"] = outbound
    if ret:
        result["return"] = ret
    return result if result else None


def test_free_prose_intercity_mode_reaches_the_solver_dict():
    """End of the chain, not just the extractor: the family must survive into the solver dict the
    planner consumes."""
    q = _q("Current location: Chongqing. Four of us are planning to travel to Beijing for two "
           "days. We have chosen to fly and have a budget of 8,000 RMB.")
    raw = pc.parse_query_no_oracle(q)
    assert raw.get("intercity_mode") == {"outbound": "airplane", "return": "airplane"}, raw
    variants = solver_constraint_variants(q, raw, use_oracle=False)
    assert variants, variants
    assert variants[0].get("intercity_mode") == {"outbound": "airplane", "return": "airplane"}


def test_familiar_100_contains_no_budget_wording(familiar_100_texts):
    """The structural reason the guard holds: there is no familiar-100 text for the new    alternatives to fire on. If a future dataset refresh introduces the word, the floor tests above
    stop being trivially safe -- this test is the tripwire that says so."""
    with_budget = [uid for uid, t in familiar_100_texts if re.search(r"\bbudget", t, re.I)]
    assert with_budget == [], with_budget
    with_currency_within = [uid for uid, t in familiar_100_texts
                            if re.search(r"within\s+\d[\d,.]*\s*(?:RMB|CNY|yuan|元)", t, re.I)]
    assert with_currency_within == [], with_currency_within


# --- 6. preference-verb triggers for attraction types (P27) ------------------
#
# The one measured survivor of P27's investigation: the free-prose *phrase table* is deliberately
# not extended (the oracle labels the remaining phrasings inconsistently -- see the roadmap entry),
# but a bare statement of interest re-uses the existing table and converts end-to-end (R35).

@pytest.mark.parametrize("text,expected", [
    ("I like natural scenery, please help me plan a travel itinerary in Nanjing.",
     ["natural scenery"]),
    ("We love museums and would like a relaxed pace.", ["Museum/Memorial Hall"]),
    ("I prefer gardens, with a budget of 2000 RMB.", ["Garden"]),
    ("They are keen on cultural attractions.", ["Cultural Tourism Area"]),
])
def test_preference_verbs_fire_the_existing_type_table(text, expected):
    assert pc.parse_required_attraction_types(text) == expected


@pytest.mark.parametrize("text", [
    # A preference about something that is not an attraction category.
    "I like spicy food and would rather not walk much.",
    # A preference naming a specific POI: the proper-noun guard must still hold.
    "We love the Humble Administrator's Garden and want to see it early.",
    # Negation must still win.
    "I do not like museums.",
])
def test_preference_verbs_do_not_invent_a_type(text):
    assert pc.parse_required_attraction_types(text) in (None, [])


def test_preference_verbs_leave_the_familiar_template_alone(familiar_100_texts):
    """Byte-identity on the register the trigger set must never touch. The template always states
    the family through "Include the following attraction types: X", which an anchored pattern
    already claims, so the free-prose fallback never runs -- asserted over all 100 queries rather
    than argued."""
    changed = [uid for uid, t in familiar_100_texts
               if pc.parse_required_attraction_types(t) != _pre_p27_required_attraction_types(t)]
    assert changed == [], changed


def _pre_p27_required_attraction_types(text):
    """``parse_required_attraction_types`` with the pre-P27 trigger set, by patching the module
    constant for one call -- the trigger regex is the entire change, so restoring it restores the
    old behaviour exactly, without copying 200 lines of scanning logic."""
    pre = re.compile(
        r"\b(?:visit(?:ing)?|see|explor(?:e|ing)|tour(?:ing)?|interested\s+in|enjoy(?:ing)?|"
        r"go\s+to|go\s+shopping\s+in|take\s+walks?\s+in|spend\s+(?:some\s+)?(?:leisure\s+)?time\s+in)\b",
        re.I,
    )
    current = pc._ATTRACTION_TYPE_FREE_PROSE_TRIGGER
    pc._ATTRACTION_TYPE_FREE_PROSE_TRIGGER = pre
    try:
        return pc.parse_required_attraction_types(text)
    finally:
        pc._ATTRACTION_TYPE_FREE_PROSE_TRIGGER = current
