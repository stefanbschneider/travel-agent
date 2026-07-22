"""Regression tests for the abbreviation-period truncation residual (roadmap Next step 6).

The base regex parser's ``_list_after_marker`` (``parse_constraints.py``, shared by
``_do_not_include_items``/``_the_following_items`` across required/excluded attractions, attraction
types, hotels, restaurants, and cuisine types) captured a name-list chunk with
``(.+?)(?:\\.|;|$)``. Because ``.`` is a literal match target too, the *first* period anywhere in
the chunk terminated the capture -- including a period embedded in an entity name, not just a
real sentence boundary. Two real familiar-100 examples exposed this as a `wrong_value` residual
(``excluded_hotels``/``excluded_restaurants``, 3 cases each): "St. Regis" (an abbreviation) and
"No. 3955 Baishi Road ..." (an abbreviation directly followed by a number). Before the fix, the
captured chunk was truncated at (or even before) the abbreviation, silently dropping the rest of
the list -- not just mis-splitting it. The fix only special-cases a closed set of address/title
abbreviations directly preceding the period (a fixed-width lookbehind); it deliberately does not
also gate on "not followed by a digit", since familiar-100's numbered requirement lists routinely
follow a genuine end-of-item period with the next item's digit.

These tests use the real familiar-100 NL phrasing (visible query text, not oracle fields) to check
the parser recovers the full chunk. The downstream comma-in-name segmentation into separate
catalog entries is a distinct, already-landed concern (entity resolution, opt-in); this only
guards the upstream capture.
"""

from __future__ import annotations

import parse_constraints as pc


def _q(nl, people=2, days=3):
    return {"nature_language": nl, "people_number": people, "days": days,
            "start_city": "Suzhou", "target_city": "Shenzhen", "uid": "t"}


def test_excluded_hotels_survives_title_abbreviation_period():
    nl = (
        "Do not include any of these hotels: The St. Regis Hotel and Grand Ocean Plaza."
    )
    names = pc.parse_excluded_hotels(nl)
    assert names == ["The St. Regis Hotel", "Grand Ocean Plaza"], names


def test_excluded_hotels_survives_numbered_address_abbreviation():
    nl = (
        "Do not include any of these hotels: VON Hotel, Shenzhen Nanshan The MixC and "
        "Mangonet Building, No. 3955 Baishi Road, Nanshan District, Shenzhen, Guangdong, China."
    )
    raw = pc.parse_query_no_oracle(_q(nl))
    # Before the fix this truncated at "No." and lost everything from "3955" onward -- assert the
    # full address chunk is present somewhere in the extracted values (segmentation into exactly
    # two catalog names is the separate, already-landed entity-resolution concern).
    joined = " ".join(raw.get("excluded_hotels") or [])
    assert "Baishi Road" in joined, raw.get("excluded_hotels")
    assert "Nanshan District" in joined, raw.get("excluded_hotels")
    assert "Guangdong" in joined, raw.get("excluded_hotels")
    assert "China" in joined, raw.get("excluded_hotels")


def test_excluded_restaurants_survives_title_abbreviation_period():
    nl = (
        "Do not include any of these restaurants: Shenzhen St. Regis Hotel Starry Chinese "
        "Restaurant and JW Marriott Hotel Shenzhen JINMAO Marriott Chinese Restaurant."
    )
    names = pc.parse_excluded_restaurants(nl)
    assert names == [
        "Shenzhen St. Regis Hotel Starry Chinese Restaurant",
        "JW Marriott Hotel Shenzhen JINMAO Marriott Chinese Restaurant",
    ], names


def test_required_the_following_still_stops_at_real_sentence_end():
    """The fix must not swallow a following, unrelated sentence -- a genuine end-of-sentence
    period (not preceded by a whitelisted abbreviation) still terminates the capture."""
    nl = (
        "Do not include any of these hotels: Grand Plaza and Ocean View Inn. "
        "Visit the following attractions: West Lake."
    )
    raw = pc.parse_query_no_oracle(_q(nl))
    assert raw.get("excluded_hotels") == ["Grand Plaza", "Ocean View Inn"], raw.get("excluded_hotels")
    assert raw.get("required_attractions") == ["West Lake"], raw.get("required_attractions")


def test_required_attractions_survives_numbered_abbreviation():
    nl = "Visit the following attractions: No. 3955 Baishi Road Memorial Hall and West Lake."
    names = pc.parse_required_attractions(nl) or []
    joined = " ".join(names)
    assert "Baishi Road Memorial Hall" in joined, names
    assert any(n == "West Lake" for n in names), names


def test_numbered_requirement_list_item_still_terminates_at_its_own_period():
    """Regression guard for a near-miss found while developing this fix: familiar-100 requirements
    are numbered lists, so a genuine end-of-item period is routinely followed by whitespace + the
    *next* item's digit ("... 9. Do not include any of these attractions: X.\\n10. Dine at ...").
    A digit-lookahead termination guard (considered and rejected) would treat that as non-
    terminating too, swallowing every later numbered requirement into the capture. Only the
    abbreviation-lookbehind signal is used, so this must NOT regress."""
    nl = (
        "We are 2 people traveling to Shenzhen for 2 days.\n"
        "Requirements:\n"
        "9. Do not include any of these attractions: Museum of the Nanyue King.\n"
        "10. Dine at Guangzhou Junye Hotel between 07:50 and 08:45.\n"
        "11. Include the following attraction types: Museum/Memorial Hall and natural scenery."
    )
    raw = pc.parse_query_no_oracle(_q(nl))
    assert raw.get("excluded_attractions") == ["Museum of the Nanyue King"], raw.get("excluded_attractions")
