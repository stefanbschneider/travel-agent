"""P20 (docs/tpc_phase2_roadmap.md#p20--close-the-two-dominant-family-recall-gaps):
``required_attraction_types``/``cuisine_preference`` are the two largest ranked residuals from
P19's ``instances x miss_rate`` analysis. This file has two parts.

Part 1 pins the two bugs found while measuring P19's target list
(``results/phase2_baselines/screens/20260807_p20_family_recall/``): a list-lead-in leak and a
numbered-OR-arm boundary swallow, both in ``parse_cuisine_preference``, both on
``local_released_150`` -- the only English-literal-oracle set where either family has any
measurable ``matched`` headroom at all (every HF set's oracle values for these two families are
Chinese literals regardless of English `nature_language`, so a value match there is unmeasurable
locally; see the screen).

Part 2 pins the new free-prose fallback patterns for both families. They are unmeasurable as
``matched`` locally (no English-literal miss exists for ``required_attraction_types`` anywhere in
released data, and only 3 for ``cuisine_preference`` -- all fixed by Part 1's bugs alone), so these
tests exist to pin *behavior* (extraction correctness, the fallback-only gate, the OR-drop guard)
rather than to back a promotion claim; promotion is R26's job on the held-out-shaped register.
"""

from __future__ import annotations

import pytest

from parse_constraints import parse_cuisine_preference, parse_required_attraction_types


# --- Part 1: the "one of the following" lead-in leak ------------------------
#
# `["one of the following", "Japanese cuisine"]` is the exact shape the roadmap's P16 section
# cites. The "want to try X restaurant" pattern is a non-greedy scan for the first " restaurant" it
# can reach; on "want to try one of the following restaurant types: X" that first occurrence is
# inside the lead-in itself, not the value the sibling list-pattern below it already extracts
# correctly.


def test_cuisine_preference_one_of_the_following_lead_in_is_not_a_value():
    # local_released_150 uid 20250322174632709770.
    text = (
        "We are 2 people, departing from Shanghai to Nanjing for 3 days. Requirements (any one): "
        "1. Want to try one of the following restaurant types: buffet. 2. Dining budget is 2100.0."
    )
    assert parse_cuisine_preference(text) == "buffet"


def test_cuisine_preference_one_of_the_following_lead_in_reversed_type_order():
    # local_released_150 uid 20250322130847337844: "types of restaurants" (types before
    # "restaurants"), the mirror word order of the pattern above -- the "one of " prefix was
    # missing from this pattern entirely, so it did not match at all before the fix.
    text = (
        "We are a group of 3, departing from Chongqing, traveling to Suzhou for 2 days. We need to "
        "satisfy one of the following: 1. Only visit free attractions. 2. Try one of the following "
        "types of restaurants: Hot pot."
    )
    assert parse_cuisine_preference(text) == "Hot pot"


# --- Part 1: the numbered-OR-arm boundary swallow ----------------------------
#
# The released generator does not always end an OR arm with a period before the next arm's digit
# ("... restaurant types: Cantonese cuisine 2. The total budget ..."), so a bare `.+?` scanning for
# the next period over-captures into the next arm's leading number.


def test_cuisine_preference_stops_at_next_numbered_arm_without_a_period():
    # local_released_150 uid 20250322175216115859: the pre-fix parse returned
    # "Cantonese cuisine 2" (the OR arm's own trailing digit swallowed whole).
    text = (
        "One person, traveling from Beijing to Shenzhen for 3 days, with the requirement that "
        "either: 1. I want to try one of the following restaurant types: Cantonese cuisine "
        "2. The total budget for the trip is 4800.0"
    )
    assert parse_cuisine_preference(text) == "Cantonese cuisine"


def test_cuisine_preference_numbered_boundary_terminator_does_not_eat_a_real_period():
    # A genuine end-of-sentence period right before the next numbered item must still terminate
    # normally -- the boundary lookahead is an *additional* terminator, not a replacement that
    # could swallow past a real "." into the digit.
    text = "Try one of the following restaurant types: Sichuan cuisine. 2. Dining budget is 1500.0."
    assert parse_cuisine_preference(text) == "Sichuan cuisine"


def test_numbered_item_boundary_does_not_match_inside_a_decimal():
    # "2100.0" must not be mistaken for a numbered-list-item boundary: the lookahead requires
    # digit(s) + "." + whitespace immediately, and a decimal's fractional digit follows the "."
    # instead of whitespace. Checked at the regex level (rather than through the full parse,
    # which also has a pre-existing, unrelated plain-"." terminator alternative that can still
    # stop at an embedded decimal for reasons this fix does not change) so the assertion is about
    # this fix's own lookahead only.
    import re

    from parse_constraints import _NUMBERED_ITEM_BOUNDARY

    assert re.match(_NUMBERED_ITEM_BOUNDARY, "2100.0 total.") is None
    assert re.match(_NUMBERED_ITEM_BOUNDARY, " 2. The total budget") is not None


def test_cuisine_preference_negated_lead_in_still_extracts_nothing():
    # Negative control: a negated "one of the following restaurant types" clause must not surface
    # a cuisine_preference at all (it is parse_excluded_cuisine_types's clause), lead-in leak or not.
    text = "We do not want to try one of the following restaurant types: buffet."
    assert parse_cuisine_preference(text) is None


def test_cuisine_preference_or_arms_stay_branch_local():
    # Each OR arm of a disjunctive requirements block is parsed against its own isolated text by
    # the branch-splitting layer upstream of this function (chinatravel/agent/phase2/normalize.py),
    # so a single parse_cuisine_preference call only ever sees one arm's sentence. Pin that the
    # lead-in fix does not change this: arm 2 (cuisine) parses independently of arm 1's unrelated
    # attraction-type text and does not pick up any fragment of it.
    arm_1 = "Only visit free attractions."
    arm_2 = "Try one of the following restaurant types: Hot pot."
    assert parse_cuisine_preference(arm_1) is None
    assert parse_cuisine_preference(arm_2) == "Hot pot"


# --- Part 2: the free-prose fallback -----------------------------------------
#
# Unmeasurable as `matched` locally (see the module docstring and the screen), so these tests pin
# behavior, not a promotion claim.


def test_cuisine_free_prose_bare_verb_plus_value():
    # hf_medium e20241028160845920703 -- no "restaurant" word anywhere in the sentence.
    text = (
        "Current location: Shenzhen. I plan to visit Guangzhou for two days with a budget of 1000 "
        "RMB. I want to eat hotpot and book a single-bed room. Please provide me with a travel plan."
    )
    assert parse_cuisine_preference(text) == "Hot pot"


def test_cuisine_free_prose_we_like_shape():
    # hf_easy: "We like X cuisine" has no "eat"/"try" verb at all.
    text = (
        "Current location: Hangzhou. My friend and I want to visit Shenzhen for 2 days. We like "
        "Hunan cuisine. Please provide us with a travel plan."
    )
    assert parse_cuisine_preference(text) == "Hunan cuisine"


def test_cuisine_free_prose_verb_not_adjacent_to_value():
    # hf_medium: "would like to" is followed by an unrelated verb ("stay in a room ..."), not
    # directly by the food verb -- the windowed scan (not a `want/wish/hope to <verb>` anchor) is
    # what recovers this.
    text = (
        "Current location: Hangzhou. My friend and I are planning to visit Suzhou for 2 days with "
        "a budget of 6000 RMB. We would like to stay in a room with a large bed, travel by train, "
        "and enjoy Jiangsu and Zhejiang cuisine. Ideally, we would prefer to stay in a boutique "
        "hotel or a guesthouse."
    )
    assert parse_cuisine_preference(text) == "Jiangsu-Zhejiang cuisine"


@pytest.mark.parametrize(
    "text",
    [
        # "such as X" introduces an example, not a stated requirement.
        "Four of us want to go to Shenzhen for a 3-day trip and try new things, such as Southeast "
        "Asian cuisine. Please provide us with a travel plan.",
        # Deliberately excluded: no cuisine is actually named in the sentence (oracle value is
        # city-derived, which this file has no access to).
        "Four of us want to visit Shanghai for 3 days and try local cuisine. Please provide us "
        "with a travel plan.",
        # Deliberately excluded: too ambiguous an anchor (confusable with "drinks"/"drinking
        # water").
        "Four of us want to go to Shanghai for a 3-day trip and would like to go drinking. Please "
        "provide us with a travel plan.",
    ],
)
def test_cuisine_free_prose_deliberately_excluded_cases(text):
    assert parse_cuisine_preference(text) is None


def test_attraction_type_free_prose_bare_verb_plus_value():
    # hf_easy m20241028164620332052 -- "see natural landscapes", no "attraction type" noun phrase.
    text = (
        "Current location: Hangzhou. I want to travel alone to Guangzhou for 3 days to see "
        "natural landscapes. Please provide me with a travel plan."
    )
    assert parse_required_attraction_types(text) == ["natural scenery"]


def test_attraction_type_free_prose_interested_in_shape():
    text = (
        "Current location: Beijing. My friend and I want to visit Chongqing for 2 days. We are "
        "interested in cultural attractions. Could you please provide us with a travel itinerary?"
    )
    assert parse_required_attraction_types(text) == ["Cultural Tourism Area"]


def test_attraction_type_free_prose_cultural_and_historical_beats_bare_historical():
    # Most-specific-first ordering: "cultural and historical sites" -> Cultural Landscape (人文景观),
    # not the bare "historical site" entry (历史古迹) below it in the table.
    text = (
        "Current location: Wuhan. Two of us are planning to visit Suzhou for two days with a "
        "budget of 3,500 RMB. We want to enjoy cultural and historical sites and book two rooms. "
        "Please provide a travel plan."
    )
    assert parse_required_attraction_types(text) == ["Cultural Landscape"]


def test_attraction_type_free_prose_does_not_leak_into_a_negated_later_clause():
    # Regression: a non-negated trigger's window can still reach into a *later*, separately
    # negated clause (real val query 20250321111720443608's shape). Negation must be checked at
    # the matched value's own position, not only at the trigger's.
    text = (
        "We want to visit Xixi Paradise Commercial Street and do not want to visit any "
        "Museum/Memorial Hall or university campus."
    )
    result = parse_required_attraction_types(text) or []
    assert "Museum/Memorial Hall" not in result
    assert "university campus" not in result


def test_attraction_type_free_prose_does_not_match_inside_a_dash_suffixed_poi_name():
    # Regression (familiar-100 uid phase2_familiar_20250323022540312612_00032): a POI name can
    # append a type word after " - ", so the literal preceding token is punctuation, not the
    # capitalized proper-noun word that actually disqualifies the match.
    text = "Visit Sichuan University (Wangjiang Campus) - Museum between 16:01 and 17:10."
    assert parse_required_attraction_types(text) is None


def test_attraction_type_free_prose_bare_university_word_excluded():
    # Regression (hf_human): a bare "universit(y|ies)" alternative was tried and dropped because it
    # matched "university students" (describes the travelers, not an attraction) and "universities"
    # inside "tour universities like [[3 named universities]]" (the oracle records only
    # required_attractions there, no type clause). Only the anchored "university campus(es)" phrase
    # remains in the table.
    text = (
        "My best friend and I are planning to join a tour group to visit Chengdu for 4 days. We "
        "are both university students and enjoy taking photos."
    )
    assert parse_required_attraction_types(text) is None


def test_attraction_type_free_prose_or_arms_are_dropped_not_flattened():
    # Two distinct type mentions with a bare " or " between them: this flat AND-list field cannot
    # express OR-alternative semantics, so the extraction is dropped rather than guessed.
    text = "We are interested in either parks or museums for our trip."
    assert parse_required_attraction_types(text) is None


def test_attraction_type_free_prose_gate_is_fallback_only():
    # The free-prose scan must not run at all when an anchored pattern already found something --
    # this is what makes the familiar-100 floor structural rather than merely tested. A type-list
    # template plus an unrelated bare mention in the same text: only the template's value survives.
    text = (
        "Include the following attraction types: park. We are also interested in cultural "
        "attractions."
    )
    assert parse_required_attraction_types(text) == ["park"]


def test_attraction_type_free_prose_window_is_bounded():
    # Every safety property claimed for the fallback (the OR-drop guard, the negation-at-value
    # check, the proper-noun guard) is scoped to `_FREE_PROSE_WINDOW` chars after the trigger --
    # this pins that the bound is real, not just documented. A value placed well past the window
    # must not be picked up.
    from parse_constraints import _FREE_PROSE_WINDOW

    padding = "x" * (_FREE_PROSE_WINDOW + 20)
    text = f"We are interested in {padding} cultural attractions."
    assert parse_required_attraction_types(text) is None
