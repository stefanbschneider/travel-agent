"""P15 (docs/tpc_phase2_roadmap.md#p15--finish-phrasing-robust-extraction): the released-data
phrasings that ``restaurant_name``/``restaurant_type``/``inner_transport_set``/``cost_transport``
missed on ``local_released_150`` after the 2026-08-06 budget/room-type fix
(``results/phase2_baselines/screens/20260806_generalization_probe_after_fix/``), plus the negative
cases that pin the precision guard added alongside them.

The floor this file protects is not just "these 9 clauses now extract" -- it is "the earlier draft
of this fix, which made the restaurant-name anchor optional, silently swallowed whole sentences on
free prose that never mention a restaurant at all" (measured: hf_easy/medium/human
``required_restaurants`` spurious count rose with zero matching recall gain). The negative tests
below are the only durable record of why the anchor is mandatory for "try" but not for "dine at".
"""

from __future__ import annotations

import argparse
import hashlib
import json

import pytest

from parse_constraints import (
    parse_budget,
    parse_excluded_cuisine_types,
    parse_excluded_restaurants,
    parse_inner_transport_restrictions,
    parse_required_restaurants,
)


# --- restaurant_name: positive fixes (local_released_150 uids) -------------


def test_excluded_restaurants_multiline_requirements_block():
    # uid 20250322150411173164: the restaurant-exclusion line is NOT the last line of the block,
    # so the old `(?:\.|;|$)` terminator (which `.` can never cross a `\n` to reach) failed to
    # match at all, not just mis-capture.
    text = (
        "Do not want to try the following restaurants: Let's Have Some Barbecue "
        "(Suzhou Guanqian Street Branch) and One Foot Garden (Taihu Lake Store 1)\n"
        "Do not want to stay at the following hotels: CM+ Service Apartment and Suzhou Central Hotel"
    )
    assert parse_excluded_restaurants(text) == [
        "Let's Have Some Barbecue (Suzhou Guanqian Street Branch)",
        "One Foot Garden (Taihu Lake Store 1)",
    ]


def test_excluded_restaurants_do_not_try_without_want():
    # uid 20250322152104796797: "do not try" with the "want/wish/hope" step dropped.
    text = "Do not try the following restaurant: Da Wu Yakiniku (Zhuoyue Center Branch)."
    assert parse_excluded_restaurants(text) == ["Da Wu Yakiniku (Zhuoyue Center Branch)"]


def test_excluded_restaurants_avoid_verb():
    # uid 20250322120300879962: "avoid" with no "do not" framing, and the name itself contains a
    # literal " and " ("Rib and Lotus Root Soup") that the naive and/comma splitter would
    # otherwise cut in two -- singular "restaurant" (not "restaurants") means exactly one name.
    text = (
        "Avoid the following restaurant: Rongchu Hubei Cuisine: Rib and Lotus Root Soup in a "
        "Clay Pot (Jianghan Road Branch 1)."
    )
    assert parse_excluded_restaurants(text) == [
        "Rongchu Hubei Cuisine: Rib and Lotus Root Soup in a Clay Pot (Jianghan Road Branch 1)"
    ]


def test_required_restaurants_would_like_to_try_oxford_comma():
    # uid 20250322114048262328: "Would like to try" (not "want/wish/hope"), and an Oxford-comma
    # list must not leave a leading "and " on the last item.
    text = (
        "Would like to try these restaurants: Imperial Treasure (Yifeng Waitanyuan Branch), "
        "Jingyunhua Roast Duck & Dim Sum (New World Store), and O'mills Sourdough Bakery & "
        "Bistro (Yongjia Road Branch)."
    )
    assert parse_required_restaurants(text) == [
        "Imperial Treasure (Yifeng Waitanyuan Branch)",
        "Jingyunhua Roast Duck & Dim Sum (New World Store)",
        "O'mills Sourdough Bakery & Bistro (Yongjia Road Branch)",
    ]


def test_required_restaurants_try_one_of_the_following_still_matches():
    # Regression pin: making the "try" pattern's restaurant-word anchor mandatory (below) must not
    # drop "try one of the following restaurants: X" (familiar-derived phrasing, live on
    # tests/phase2/test_entity_resolution.py's uid 20250321144415070996).
    text = "We also want to try one of the following restaurants: OMBRA Terrace Garden Western Restaurant."
    assert parse_required_restaurants(text) == ["OMBRA Terrace Garden Western Restaurant"]


# --- restaurant_name: the precision guard (free-prose false positives) -----


@pytest.mark.parametrize(
    "text",
    [
        # hf_easy m20241028164727691681
        "Four of us want to visit Nanjing for 3 days and would like to try some local Jiangsu and "
        "Zhejiang cuisine. Please provide us with a travel plan.",
        # hf_human h20241029143512507336
        "I am currently in Nanjing and would like to go on a 5-day trip to Beijing with a friend. "
        "We plan to travel by high-speed train both ways and hope to try some local specialty foods.",
        # hf_human h20241029143549773288
        "My parents and I are planning to travel from Chengdu to Chongqing for three days. We want "
        "to try hot pot, explore the local history and culture, and prefer a relaxed itinerary.",
        # hf_human h20241029143625307702
        "I am planning to travel from Beijing to Shanghai for a 3-day stay. I would like to try "
        "high-end dining options in Shanghai, such as Michelin three-star restaurants, but I want "
        "to save money on hotels.",
    ],
)
def test_would_like_to_try_cuisine_is_not_a_restaurant_name(text):
    # These are the exact free-prose sentences that regressed `required_restaurants` precision
    # (spurious rose, matched flat) when the "would like to try X" trigger's restaurant-word
    # anchor was made optional instead of mandatory. None of them name a specific restaurant.
    assert parse_required_restaurants(text) is None


def test_dine_at_does_not_require_the_word_restaurant():
    # Unlike "try", "dine at" always names a specific venue in the released phrasing register
    # (hf_easy/medium: "would like to dine at Yan Jintang near Longfu Temple", "want to dine at
    # Quanjude (Qianmen branch)"), so its anchor is deliberately looser than "try"'s.
    text = "Four of us want to visit Nanjing for 3 days and would like to dine at LONFOOD in the Excellence Century Center."
    assert parse_required_restaurants(text) == ["LONFOOD in the Excellence Century Center"]


# --- restaurant_type -------------------------------------------------------


def test_excluded_cuisine_types_restaurants_of_the_x_type():
    # uid 20250322141653938197: value BEFORE the word "type" ("restaurants of the cafe type"),
    # the mirror image of the already-supported "of the type X" order.
    text = "Do not want to try any restaurants of the cafe type."
    assert parse_excluded_cuisine_types(text) == ["cafe"]


def test_excluded_restaurants_does_not_capture_the_reversed_type_phrase():
    # The same "of the X type" chunk must not leak into excluded_restaurants as a bogus name.
    assert parse_excluded_restaurants("Do not want to try restaurants of the cafe type.") is None


# --- inner_transport_set ----------------------------------------------------


def test_inner_transport_wish_to_use_single_mode():
    # uid 20250322184829394258: "wish to" (not "want to"), the pre-existing multi-mode regex
    # only accepted "want to".
    text = "dining budget of 2400.0, and do not wish to use taxi for intra-city transportation."
    assert parse_inner_transport_restrictions(text) == ["taxi"]


def test_inner_transport_travel_by_walking():
    # uid 20250323001735264616: "travel by X" is a distinct verb from "use X".
    text = "do not want to travel by walking within the city, and the budget for intra-city transportation is 1020.0."
    assert parse_inner_transport_restrictions(text) == ["walk"]


def test_inner_transport_wish_to_use_multi_mode():
    # uid 20250324200943774601: "wish to" + a two-mode "or" list in one sentence.
    text = "Do not wish to use taxi or walking for intra-city transportation."
    assert parse_inner_transport_restrictions(text) == ["taxi", "walk"]


# --- cost_transport (budget) -------------------------------------------------


def test_budget_in_city_synonym():
    # uid 20250324225301554257: "in-city" alongside the already-supported "intra-city"/"inner-city".
    text = "the budget for in-city transportation is 120, and we prefer single bed rooms."
    assert parse_budget(text).get("inner_transport") == 120.0


# --- the real floor: familiar-100 parsed output, whole-pipeline ------------
#
# `test_parser_phrasing_generalization.py`'s byte-identity test keeps verbatim copies of the
# *budget and room-type* extractors only -- this PR also touches restaurant name/type, cuisine
# type and inner-transport extraction, none of which that test's verbatim copies would notice a
# change in. The floor that actually matters is "familiar-100's parsed solver-dict variants did
# not change at all", checked here as a hash of `query_variants()` (the same function the
# generalization probe and `parser_vs_oracle` use) over all 100 queries, disjunction-aware. A
# passing test here is what backs the "familiar-100 byte-identical" claim in the roadmap/PR, not
# just the two-family verbatim test.
#
# To regenerate after a deliberate familiar-100-affecting change: rerun the hash computation below
# with the new code, update `_EXPECTED_HASH`, and say why in the commit message -- this hash must
# never be updated to silence a failure without reading the diff first.
_EXPECTED_HASH = "aa50249aa7eada6cfe8e33519912a729697e27454722d37b71f52ec09561c6c3"


@pytest.fixture(scope="module")
def familiar_100_parsed_variants():
    from chinatravel.data.load_datasets import load_query
    from parser_vs_oracle import query_variants

    # oracle_translation=False strips hard_logic/hard_logic_py/hard_logic_nl before this fixture
    # ever sees the query dicts (CLAUDE.md's no-oracle-leakage invariant): this floor pins the
    # no-oracle parsed side only, so it should reflect the same oracle-free input the harness
    # actually feeds the parser, not a dict that happens to still carry oracle-only fields the
    # parse path must not read. `query_variants` also returns an oracle-side variant for parity
    # with `parser_vs_oracle`'s other callers; it is discarded below since only the parsed side is
    # the floor here, and `solver_constraint_variants(..., use_oracle=True)` degrades gracefully
    # when the oracle fields are absent (the same "absent, never required" contract Phase 2 queries
    # carry for real).
    ids, data = load_query(
        argparse.Namespace(splits="tpc_phase2_familiar_100", lang="en", oracle_translation=False)
    )
    out = {}
    for uid in ids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        variants, _ = query_variants(q, disjunction=True)
        out[uid] = variants
    return out


def test_familiar_100_parsed_variants_are_byte_identical(familiar_100_parsed_variants):
    assert len(familiar_100_parsed_variants) == 100
    canon = json.dumps(familiar_100_parsed_variants, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    assert digest == _EXPECTED_HASH, (
        "familiar-100 parsed constraints changed -- if this is a deliberate, measured change "
        "(not a P15 side effect), regenerate _EXPECTED_HASH and say why in the commit message."
    )
