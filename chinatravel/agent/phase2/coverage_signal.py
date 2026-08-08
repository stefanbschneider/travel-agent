"""Roadmap P17(a): an honest "unknown" for a requirement the parse could not represent.

The scheduler asks ``evaluate_parsed_constraints`` whether a plan satisfies a query, so a clause we
never extracted always reads as satisfied -- a query whose parse silently dropped a real requirement
gets promoted to the polish pass exactly like one that genuinely has nothing left to fix. P12
considered a signal-phrase heuristic for this and rejected it: a phrase imprecise enough to fire on
already-correctly-parsed queries manufactures false negatives that cost budget the same way P10's
false positives cost queries. This module is deliberately narrower than a phrase heuristic --
**coverage**, not phrasing: does the visible query text mention something in one of a small set of
closed, checkable categories while the parsed constraints carry no family that could represent it at
all. A query can mention its own budget in prose without that meaning the parse is wrong; the
trigger is the *combination* of "clearly stated" and "nothing on the parse side could possibly cover
it", which familiar-100 -- already parsed essentially perfectly -- should almost never produce (see
``tests/phase2/test_coverage_signal.py`` and ``scripts/phase2_generalization_probe.py``'s
``coverage_signal`` table for the measured trigger rate).

Two categories ship: a currency amount with no ``budgets`` family, and a room-type noun with no
``room_type`` family. Both measured `0/100` on familiar-100 (the P13 precedent's bar) before this
landed.

**Cuisine mention was attempted and rejected, on measurement, not implemented here.** A closed-
vocabulary substring match against the environment's own cuisine values (mirroring
``parse_constraints._compound_cuisine_types``) triggered on **58/100** familiar-100 queries -- the
overwhelming majority false positives. Cause: cuisine words are common substrings of real restaurant
*names* in this dataset ("Leap路Yue Modern **Cantonese Cuisine**" is a restaurant a query's
``excluded_restaurants`` correctly named in full), so a bare substring match fires on a POI name
being handled correctly by an entirely different family, not on an actual unmet cuisine preference.
This is exactly the P12 failure mode restated for a word list instead of a phrase: precise-looking
does not mean precise. A real fix needs the mention to be excluded when it is fully contained inside
an already-covered POI name span, which is closer to catalog-grounded matching (P24's
``_salvage_catalog_name`` shape) than a coverage check -- filed as a residual, not built here.

Named-POI mention is also **not** implemented here yet, for the same reason cuisine was dropped: a
precise version needs a catalog-grounded scan (matching a real POI name is a very different
reliability bar than matching a closed word list), and per-city catalog loading would be the most
expensive of the checks this section originally scoped. See the roadmap item for both residuals.

Oracle-free by construction: every function here takes the **visible** query text and the already-
parsed ``variants`` list, never ``hard_logic*``. Pure and side-effect-free.
"""

from __future__ import annotations

import re

# --- Currency / budget mention -------------------------------------------------------------------
# Deliberately looser than parse_constraints.py's scoped budget regexes (which extract a *value*
# per bucket) -- this only needs to detect that *some* amount is being stated as a budget, in any
# phrasing shape, so it stays useful exactly when the precise parser's shape-specific patterns miss.
_CURRENCY_AMOUNT_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:RMB|CNY|yuan|元|¥|￥)", re.IGNORECASE
)
_BUDGET_WORD_NEAR_DIGIT_RE = re.compile(r"\bbudget\b[^.!?\n]{0,24}?\d", re.IGNORECASE)


def _mentions_currency(text: str) -> bool:
    return bool(_CURRENCY_AMOUNT_RE.search(text) or _BUDGET_WORD_NEAR_DIGIT_RE.search(text))


def _variant_get(variant, key: str):
    """``variant.get(key)`` that tolerates a non-dict entry (``None``, a malformed branch) instead
    of raising -- a defensive default matching every other family-presence check in this file."""
    return variant.get(key) if isinstance(variant, dict) else None


def _has_budget_family(variants: list[dict]) -> bool:
    return any(bool(_variant_get(v, "budgets")) for v in (variants or []))


# --- Room-type mention ----------------------------------------------------------------------------
# Narrow on purpose: bare "room" fires on idiom ("there's room for...") and on unrelated nouns
# ("living room" never appears in this dataset's register, but the qualifier keeps the pattern
# precise regardless). Requires a bed/room-count or -size qualifier immediately adjacent.
_ROOM_TYPE_RE = re.compile(
    r"\b(?:single|double|twin|triple|king|queen|deluxe)[- ]?(?:size[d]?[- ]?)?(?:room|bed)s?\b"
    r"|\bsuite\b",
    re.IGNORECASE,
)


def _mentions_room_type(text: str) -> bool:
    return bool(_ROOM_TYPE_RE.search(text))


def _has_room_family(variants: list[dict]) -> bool:
    return any(bool(_variant_get(v, "room_type")) for v in (variants or []))


# --- Public entry point ----------------------------------------------------------------------------

_CHECKS = (
    ("budget", _mentions_currency, _has_budget_family),
    ("room_type", _mentions_room_type, _has_room_family),
)


def uncovered_mentions(text: str, variants: list[dict] | None) -> tuple[str, ...]:
    """Which coverage categories fired: ``text`` mentions something in that category, but no
    variant in ``variants`` carries a family that could represent it. Returns a tuple of matched
    category names (empty when nothing fires, which is expected for the overwhelming majority of
    queries). Pure; never raises (a malformed ``variants`` entry is treated as non-covering, same
    as an empty list -- a defensive default, not a silently-swallowed exception, since ``_variant_get``
    tolerates a non-dict entry)."""
    text = text or ""
    if not text:
        return ()
    fired = tuple(
        category for category, mentions, has_family in _CHECKS
        if mentions(text) and not has_family(variants)
    )
    return fired
