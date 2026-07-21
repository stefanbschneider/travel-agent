"""
Parse a TPC query's nature_language (and hard_logic_py, when present) into structured
constraints consumed by TPCAgent. Pure regex; runs live per query at agent runtime.
"""

import re
import math


# --- Negation guards (shared) -------------------------------------------------
# The dataset expresses exclusions as "do not want/wish to <verb> X". Positive
# extractors (required_*) must not fire on those clauses. Two helpers cover the
# two shapes we see:
#   * the trigger is *directly* preceded by a negation ("do not wish to stay ..."),
#   * a positive clause runs into a following negated clause ("visit X and do not
#     want to visit Y") and the greedy chunk swallows the negated tail.
#
# `_NEG_BEFORE` matches a negation that ends just before the (a few words before
# the) trigger; `_NEG_DESIRE_TAIL` matches an embedded negated-desire clause so a
# captured chunk can be truncated at it.
_NEG_BEFORE = re.compile(
    r"\b(?:do(?:es)?\s+not|do\s+n't|don't|doesn't|did\s+not|didn't|will\s+not|"
    r"won't|not|never|avoid|no)\b[\w'\s]{0,20}$",
    re.I,
)
_NEG_DESIRE_TAIL = re.compile(
    r"(?:\band\b\s+|\bbut\b\s+|;\s*|,\s*)?"
    r"\b(?:do(?:es)?\s+not|do\s+n't|don't|doesn't|did\s+not|didn't|will\s+not|"
    r"won't|never|avoid)\b\s+(?:want|wish|hope|like|plan|intend)?",
    re.I,
)


def _negated_before(text, pos, window=28):
    """True when the text immediately preceding ``pos`` expresses a negation.

    A ``window``-char lookback catches both "do not <trigger>" and phrasings where
    a couple of words sit between the negation and the trigger (e.g.
    "do not wish to stay at ...").
    """
    return bool(_NEG_BEFORE.search(text[max(0, pos - window):pos]))


def _truncate_at_negation(chunk):
    """Cut ``chunk`` at the first embedded negated-desire clause.

    "Xixi Paradise Commercial Street and do not want to visit any Museum" ->
    "Xixi Paradise Commercial Street". Returns the (stripped) prefix, or the
    original chunk when no negated tail is present.
    """
    m = _NEG_DESIRE_TAIL.search(chunk)
    if m:
        return chunk[: m.start()].strip().rstrip(",").strip()
    return chunk


# --- Uniform familiar-100 list templates -------------------------------------
# Every familiar-100 query states its exclusions and its requirements with two mirror-image
# templates that none of the older "do not want to visit/stay/try ..." / "want to visit ..."
# patterns matched -- leaving the excluded_* and required_* families at zero recall (see
# docs/tpc_phase2_roadmap.md):
#     negative: "Do not include any of these <category>: A, B and C."
#     positive: "<Visit|Dine at|Stay at|Include> the following <category>: A, B and C."
# The <category> is passed by each extractor as a regex anchored immediately before the ':'
# list marker, so a name category ("hotels"/"attractions") cannot swallow a sibling type
# category ("hotel feature types"/"attraction types") that shares the same prefix.
def _list_after_marker(text, lead_pattern, category_pattern, *, protect=(), check_negation=False):
    """Match ``<lead> <category>: A, B and C`` and return the split list items (or None).

    Items are split on commas / " and " / " or "; any phrase in ``protect`` (a closed
    environment vocabulary of compound values that legitimately contain " and ", e.g.
    "Fast food and casual dining") is masked before splitting so it survives as one item.
    ``protect`` may be a zero-arg callable, resolved lazily only when the template actually
    matches, so callers can pass an expensive vocabulary builder without paying for it on the
    (common) inputs that never use this template. ``check_negation`` drops a match whose lead-in
    is itself negated ("do not visit the following ..."), so the positive template does not fire
    on a negated clause in unseen data."""
    pattern = lead_pattern + category_pattern + r"\s*:\s*(.+?)(?:\.|;|$)"
    matches = [
        m for m in re.finditer(pattern, text, re.I)
        if not (check_negation and _negated_before(text, m.start()))
    ]
    if not matches:
        return None
    protect = protect() if callable(protect) else protect
    protect = sorted((p for p in protect if p), key=len, reverse=True)
    items = []
    for m in matches:
        chunk = m.group(1).strip().rstrip(".")
        placeholders = {}
        for i, phrase in enumerate(protect):
            token = f"\x00{i}\x00"
            masked = re.sub(re.escape(phrase), token, chunk, flags=re.I)
            if masked != chunk:
                chunk = masked
                placeholders[token] = phrase
        # Consume an optional "and"/"or" right after a comma so an Oxford-comma list
        # ("A, B, and C") does not leave a leading "and C" fragment.
        for piece in re.split(r"\s+and\s+|\s+or\s+|,\s*(?:and\s+|or\s+)?", chunk):
            piece = piece.strip().rstrip(".")
            for token, phrase in placeholders.items():
                if token in piece:
                    piece = piece.replace(token, phrase)
            if piece and piece not in items:
                items.append(piece)
    return items or None


def _do_not_include_items(text, category_pattern, protect=()):
    """Negative template: "Do not include any of these <category>: A, B and C." -> items."""
    return _list_after_marker(
        text, r"do\s+not\s+include\s+any\s+of\s+these\s+", category_pattern, protect=protect
    )


def _the_following_items(text, category_pattern, protect=()):
    """Positive template: "<Visit|Dine at|Stay at|Include|Try> the following <category>: A and B."
    -> items. Guards against a negated lead-in so it never fires on a "do not ..." clause."""
    return _list_after_marker(
        text,
        r"(?:visit|dine\s+at|stay\s+at|include|try)\s+the\s+following\s+",
        category_pattern,
        protect=protect,
        check_negation=True,
    )


_compound_cuisine_cache = None


def _compound_cuisine_types():
    """The closed set of environment cuisine/restaurant-type values that contain " and "
    (e.g. "Bakery and Desserts", "Fast food and casual dining"). Read once from the same
    committed database_en restaurant CSVs WorldEnv loads -- deterministic environment data,
    not oracle -- so the negative-list splitter never breaks a compound type in two. Empty on
    any read/decode/parse failure (splitter then falls back to naive splitting)."""
    global _compound_cuisine_cache
    if _compound_cuisine_cache is not None:
        return _compound_cuisine_cache
    import csv
    import glob
    import os

    root = os.path.dirname(os.path.abspath(__file__))
    compound = set()
    pattern = os.path.join(
        root, "chinatravel", "environment", "database_en", "restaurants", "*", "*.csv"
    )
    try:
        for path in glob.glob(pattern):
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    value = (row.get("cuisine") or row.get("type") or "").strip()
                    if value and " and " in value.lower():
                        compound.add(value)
    # A best-effort vocabulary helper: a missing/unreadable (OSError), non-UTF8 (UnicodeError),
    # or malformed (csv.Error) CSV must degrade to naive splitting, never crash live query
    # parsing -- matching the "empty on any read/decode/parse failure" contract.
    except (OSError, UnicodeError, csv.Error):
        compound = set()
    _compound_cuisine_cache = compound
    return compound


_LINE_SCOPED_BUDGET_PATTERNS = (
    (
        "accommodation",
        re.compile(
            r"^[ \t]*(?:\d+\.[ \t]+)?Keep[ \t]+the[ \t]+accommodation[ \t]+cost"
            r"[ \t]+within[ \t]+(?P<value>\d+(?:\.\d+)?)[ \t]*[.;]?[ \t]*$",
            re.I | re.M,
        ),
    ),
    (
        "inner_transport",
        re.compile(
            r"^[ \t]*(?:\d+\.[ \t]+)?Keep[ \t]+transportation[ \t]+within[ \t]+the"
            r"[ \t]+destination[ \t]+city[ \t]+within[ \t]+"
            r"(?P<value>\d+(?:\.\d+)?)[ \t]*[.;]?[ \t]*$",
            re.I | re.M,
        ),
    ),
    (
        "total",
        re.compile(
            r"^[ \t]*(?:\d+\.[ \t]+)?Keep[ \t]+the[ \t]+total[ \t]+activity"
            r"[ \t]+and[ \t]+in-city[ \t]+transportation[ \t]+cost[ \t]+within"
            r"[ \t]+(?P<value>\d+(?:\.\d+)?)[ \t]*[.;]?[ \t]*$",
            re.I | re.M,
        ),
    ),
    (
        "dining",
        re.compile(
            r"^[ \t]*(?:\d+\.[ \t]+)?Keep[ \t]+the[ \t]+dining[ \t]+cost"
            r"[ \t]+within[ \t]+(?P<value>\d+(?:\.\d+)?)[ \t]*[.;]?[ \t]*$",
            re.I | re.M,
        ),
    ),
    (
        "sightseeing",
        re.compile(
            r"^[ \t]*(?:\d+\.[ \t]+)?Keep[ \t]+the[ \t]+attraction[ \t]+ticket"
            r"[ \t]+cost[ \t]+within[ \t]+(?P<value>\d+(?:\.\d+)?)"
            r"[ \t]*[.;]?[ \t]*$",
            re.I | re.M,
        ),
    ),
)


def parse_budget(text):
    """Extract budget constraints from text."""
    budgets = {}
    for key, pattern in _LINE_SCOPED_BUDGET_PATTERNS:
        match = pattern.search(text)
        if match:
            budgets[key] = float(match.group("value"))


    # Sightseeing budget
    m = re.search(r"(?:sightseeing|attractions?\s+)budget[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"budget\s+for\s+sightseeing[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"(?:the\s+)?sightseeing\s+budget\s+is\s+([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"(?:a\s+)?budget\s+of\s+([\d]+(?:\.[\d]+)?)\s+for\s+sightseeing", text, re.I)
    if m:
        budgets["sightseeing"] = float(m.group(1))

    # Accommodation budget
    m = re.search(r"(?:accommodation|hotel|lodging)\s*budget[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"budget\s+for\s+accommodation[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"(?:a\s+)?budget\s+of\s+([\d]+(?:\.[\d]+)?)\s+for\s+accommodation", text, re.I)
    if m:
        budgets["accommodation"] = float(m.group(1))

    # Dining/meal budget
    m = re.search(r"(?:dining|meal|food|restaurant)\s*budget[^0-9]*?([\d]+(?:\.\d+)?)", text, re.I)
    if not m:
        m = re.search(r"budget\s+for\s+(?:dining|meals|food)[^0-9]*?([\d]+(?:\.\d+)?)", text, re.I)
    if m:
        budgets["dining"] = float(m.group(1))

    # Intercity transportation budget
    m = re.search(r"(?:intercity|inter-city|cross-city)\s*transport(?:ation)?\s*budget[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"budget\s+for\s+(?:intercity|inter-city|cross-city)\s*transport(?:ation)?[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"(?:intercity|inter-city|cross-city)\s*transport(?:ation)?\s+budget\s+(?:of|is)\s+([\d]+(?:\.[\d]+)?)", text, re.I)
    if m:
        budgets["intercity_transport"] = float(m.group(1))

    # Intra-city transportation budget.
    # NOTE: the bare "city" alternative can match inside "cross-city"/"inter-city"; guard against
    # that by rejecting a match whose token is immediately preceded by a hyphen (A3 fix).
    m = None
    for cand in re.finditer(
        r"(?:intra-city|inner-city|city|intra\s*city|local)\s*(?:transportation|travel)\s*(?:budget|is)[^0-9]*?([\d]+(?:\.[\d]+)?)",
        text, re.I,
    ):
        if cand.start() > 0 and (text[cand.start() - 1] == "-" or text[cand.start() - 1].isalnum()):
            continue  # part of "cross-city" / "inter-city" / "intercity"
        m = cand
        break
    if not m:
        m = re.search(r"budget\s+for\s+(?:intra-city|inner-city|intra\s*city|local)\s*transportation[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"budget\s+for\s+(?:travel|transport(?:ation)?)\s+within\s+the\s+city[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"(?:travel|transport(?:ation)?)\s+within\s+the\s+city\s+(?:budget\s+)?is\s+([\d]+(?:\.[\d]+)?)", text, re.I)
    if m:
        budgets["inner_transport"] = float(m.group(1))

    # Total travel budget
    m = re.search(r"total\s*(?:travel\s*|trip\s*)?budget[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if m:
        budgets["total"] = float(m.group(1))

    return budgets


def parse_intercity_mode(text):
    """Extract intercity transport mode requirements.

    The mode domain is binary (train/airplane), so a negated mode resolves to its complement --
    the oracle does the same. Negation patterns are checked *before* the corresponding positive
    pattern (plan3 G4/N3.2): a negated sentence like "do not want to take the train to the
    destination" contains "take the train to the destination" as a literal substring, so checking
    positive patterns first would match it and read the sentence as an affirmative -- exactly
    backwards from what it says.
    """
    outbound = None
    ret = None

    # --- negative outbound: "do not want to take the/a(n) train to the destination" ---
    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?take\s+(?:the\s+|an?\s+)?(airplane|plane|flight|train)\s+to\s+(?:the\s+)?destination",
        text, re.I,
    )
    if m:
        excluded = m.group(1).lower()
        outbound = "train" if excluded in ("airplane", "plane", "flight") else "airplane"

    # --- negative outbound, "fly" verb: "do not want to fly to the destination" ---
    if outbound is None:
        m = re.search(r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?fly\s+to\s+(?:the\s+)?destination", text, re.I)
        if m:
            outbound = "train"  # negated "fly" (airplane) -> complement

    # --- negative return: "do not want to take the/a(n) train back / for the return trip" ---
    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?take\s+(?:the\s+|an?\s+)?(airplane|plane|flight|train)\s+(?:for\s+the\s+return|back|for\s+return)",
        text, re.I,
    )
    if m:
        excluded = m.group(1).lower()
        ret = "train" if excluded in ("airplane", "plane", "flight") else "airplane"

    # --- negative return, "fly" verb: "do not want to fly back" ---
    if ret is None:
        m = re.search(r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?fly\s+(?:for\s+the\s+return|back|for\s+return)", text, re.I)
        if m:
            ret = "train"

    # --- positive outbound: "take a/the train to the destination" ---
    if outbound is None:
        m = re.search(
            r"(?:take\s+(?:the\s+|a\s+)?|go\s+by\s+|travel\s+(?:to\s+\w+\s+)?by\s+)(train|airplane|plane|flight)\s+to\s+(?:the\s+)?destination",
            text, re.I,
        )
        if m:
            outbound = "train" if "train" in m.group(1).lower() else "airplane"

    # --- positive return: "return by X" / "take the X back" ---
    if ret is None:
        m = re.search(r"(?:return|back)\s+by\s+(train|airplane|plane|flight)", text, re.I)
        if not m:
            m = re.search(r"(?:take\s+(?:the\s+|a\s+)?)(train|airplane|plane|flight)\s+(?:back|for\s+the\s+return)", text, re.I)
        if m:
            ret = "train" if "train" in m.group(1).lower() else "airplane"

    # --- positive outbound, alt phrasing: "travel to the destination by X" ---
    if outbound is None:
        m = re.search(r"(?:travel|go)\s+to\s+(?:the\s+)?destination\s+by\s+(train|airplane|plane|flight)", text, re.I)
        if m:
            outbound = "train" if "train" in m.group(1).lower() else "airplane"

    # Fallback: bare "by train" / "by airplane" without direction context.
    if outbound is None and ret is None:
        m = re.search(r"(?:take|by|use)\s+(?:a\s+|the\s+)?(train|airplane|plane|flight)", text, re.I)
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


def parse_inner_transport_restrictions(text):
    """Extract inner-city transport mode restrictions."""
    excluded = []

    # "no taxi" / "no walking" / "no metro" patterns
    if re.search(r"no\s+taxi|not\s+(?:want\s+to\s+)?(?:use\s+)?taxi|without\s+taxi|no\s+taxis|prefer\s+not\s+to\s+use\s+taxi", text, re.I):
        excluded.append("taxi")
    if re.search(r"no\s+walk|not\s+(?:want\s+to\s+)?(?:use\s+)?walk|without\s+walk|no\s+walking|prefer\s+not\s+to\s+(?:use\s+)?walk", text, re.I):
        excluded.append("walk")
    if re.search(r"no\s+metro|not\s+(?:want\s+to\s+)?(?:use\s+)?metro|without\s+metro|prefer\s+not\s+to\s+(?:use\s+)?metro", text, re.I):
        excluded.append("metro")

    # "do not wish to use taxis for transportation"
    if not excluded:
        if re.search(r"(?:do\s+not|don't|not)\s+(?:wish|want)\s+to\s+use\s+taxis?\s+for\s+transport", text, re.I):
            excluded.append("taxi")
        if re.search(r"(?:do\s+not|don't|not)\s+(?:wish|want)\s+to\s+use\s+(?:walking|walk)\s+for\s+transport", text, re.I):
            excluded.append("walk")

    # "No taxi or walking for getting around"
    m = re.search(r"no\s+(taxi|walking|metro)\s+or\s+(taxi|walking|metro)", text, re.I)
    if m:
        for g in [m.group(1), m.group(2)]:
            mode = g.lower().replace("walking", "walk")
            if mode not in excluded:
                excluded.append(mode)

    # General multi-mode exclusion list: "do not want to use walking or taxi (as means of
    # transportation) within the city" -- any ,/or/and-separated run of mode words after a
    # negated "use", in any order/count (plan3 G4/N3.3; the earlier patterns above only fire when
    # the negation cue is directly adjacent to a single mode word).
    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+)?use\s+"
        r"((?:taxis?|walking|walk|metro)(?:\s*(?:,|or|and)\s*(?:taxis?|walking|walk|metro))*)",
        text, re.I,
    )
    if m:
        for word in re.findall(r"taxis?|walking|walk|metro", m.group(1), re.I):
            mode = word.lower().replace("walking", "walk").replace("taxis", "taxi")
            if mode not in excluded:
                excluded.append(mode)

    return excluded if excluded else None


# Attraction TYPE phrases (lowercased) the NL parser must not mistake for specific names.
_ATTRACTION_TYPE_PHRASES = {
    "park", "museum/memorial hall", "cultural landscape", "natural scenery",
    "red tourism sites", "red tourism", "commercial district",
    "amusement park/sports entertainment", "amusement park", "sports entertainment",
    "university campus", "historical site", "art museum", "cultural tourism area", "other",
}


def parse_required_attractions(text):
    """Extract specific attraction names that must be visited."""
    names = []

    # "want to visit X" / "must visit X" - capture names after
    # Names are typically capitalized phrases, possibly with parentheses
    patterns = [
        r"(?:want|wish|hope)\s+to\s+visit\s+(.+?)(?:\.|;|,\s*(?:and|we|the|do|hope|want|with|stay|if)|$)",
        r"must\s+visit\s+(.+?)(?:\.|;|,\s*(?:and|we|the|do)|$)",
        # Bare imperative ("Visit X"), common in OR-arm bullet text with no surrounding
        # "we want to"/"must" framing (plan3 G3/N3.1) -- anchored to the start of the text so it
        # doesn't also fire mid-sentence.
        r"^visit\s+(.+?)(?:\.|;|,\s*(?:and|we|the|do|hope|want|with|stay|if)|$)",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            # Respect negation: "do not want/wish to visit ..." is not a requirement.
            if _negated_before(text, m.start()):
                continue
            # Truncate a greedy chunk that ran into a following negated clause,
            # e.g. "visit X and do not want to visit Y" -> keep only "X".
            chunk = _truncate_at_negation(m.group(1).strip())
            if not chunk:
                continue
            # "Visit the following attractions: <names>" is handled verbatim by the
            # _the_following_items template below; the bare "^visit ..." pattern would otherwise
            # capture the "the following attractions:" label as part of the first name.
            if re.match(r"the\s+following\s+attractions?\s*:", chunk, re.I):
                continue
            # Skip attraction TYPE phrases (those belong to parse_required_attraction_types).
            if chunk.lower().strip() in _ATTRACTION_TYPE_PHRASES:
                continue
            # Skip if this is an attraction TYPE (common words)
            type_words = {"a park", "park", "free attractions", "only free attractions",
                         "cultural landscape", "museum", "natural scenery", "red tourism",
                         "commercial district", "amusement park", "university campus",
                         "historical site", "art museum", "other"}
            if chunk.lower().strip() in type_words:
                continue
            # Check if this starts with "a " which indicates a type
            if re.match(r"^a\s+", chunk, re.I):
                continue
            # Check if it's a conjunction of types
            if all(w.lower() in {"park", "museum", "and", "or", "a", "the", "an", ",",
                                  "university", "campus", "historical", "site", "natural",
                                  "scenery", "red", "tourism", "sites", "cultural",
                                  "landscape", "art", "commercial", "district", "amusement",
                                  "sports", "entertainment", "venues", "other"}
                   for w in chunk.replace(",", " ").replace("/", " ").split()):
                continue
            # Split on " and " to get individual names
            parts = re.split(r"\s+and\s+", chunk)
            for p in parts:
                p = p.strip().rstrip(".")
                if p and len(p) > 1:
                    names.append(p)

    # "Visit the following attractions: X and Y." (familiar-100). Anchored at ':' so it stays on
    # the attraction-name line and never fires on "attraction types:" (-> required_attraction_types).
    for n in _the_following_items(text, r"attractions?") or []:
        if n and n not in names:
            names.append(n)

    return names if names else None


def parse_required_attraction_types(text):
    """Extract required attraction types."""
    types = []

    # Known attraction types in the dataset
    known_types = [
        "park", "Museum/Memorial Hall", "Cultural Landscape", "natural scenery",
        "red tourism sites", "red tourism", "commercial district",
        "amusement park/sports entertainment", "amusement park",
        "sports entertainment", "university campus", "historical site",
        "Art Museum", "Cultural Tourism Area", "Other"
    ]

    # "want to visit a park" / "want to visit Cultural Landscape"
    # But NOT "do not want to visit..." (negated)
    m = re.search(r"(?<!not\s)(?<!not\s\w\s)(?:want|wish|hope)\s+to\s+visit\s+(?:a\s+)?(.+?)(?:\.|;|,\s*(?:and\s+we|we|the\s+budget|do|hope|stay|if)|$)", text, re.I)
    if m and _negated_before(text, m.start()):
        m = None
    if not m:
        # Try "visit X and Y" (positive form, not preceded by "not")
        m = re.search(r"[Vv]isit\s+(.+?)(?:\.|;|,\s*(?:and\s+we|we|the)|$)", text, re.I)
        # Skip if preceded by "not" within 20 chars
        if m and re.search(r"(?:not|don't|no)\s+(?:\w+\s+){0,3}visit", text[:m.start() + 10], re.I):
            m = None
    if m:
        # Truncate a greedy chunk that ran into a following negated clause so
        # negated types ("... and do not want to visit any Museum") do not leak
        # into the *required* set (parse_excluded_attraction_types owns those).
        chunk = _truncate_at_negation(m.group(1).strip().rstrip("."))
        # "Visit the following attractions: <names>" is a required-NAME list, not a type list --
        # parse_required_attractions owns it. Without this guard the broad "Visit ..." pattern
        # above scans the names for embedded type words (e.g. "... Art Museum" inside a proper
        # name) and emits a spurious required_attraction_type.
        if re.match(r"the\s+following\s+attractions?\s*:", chunk, re.I):
            chunk = ""
        if not chunk:
            return _finish_required_attraction_types(text, types)
        # Check if it matches known types or type-like patterns
        for kt in known_types:
            if kt.lower() in chunk.lower():
                types.append(kt)

        # Multiple types: "park, amusement park/sports entertainment, or natural scenery"
        if not types:
            # Split on comma and "or"/"and"
            parts = re.split(r",\s*(?:or\s+|and\s+)?|\s+or\s+|\s+and\s+", chunk)
            for p in parts:
                p = p.strip()
                for kt in known_types:
                    if kt.lower() == p.lower() or kt.lower() in p.lower():
                        if kt not in types:
                            types.append(kt)

    return _finish_required_attraction_types(text, types)


def _finish_required_attraction_types(text, types):
    """Append the familiar-100 "Include the following attraction types: X and Y." matches.
    Values are kept verbatim (the NL uses the oracle's vocabulary/casing, so unaliased types
    like "Library/Memorial Hall" or "University campus" survive intact)."""
    for t in _the_following_items(text, r"attraction\s+types?") or []:
        if t and t not in types:
            types.append(t)
    return types if types else None


def parse_excluded_attraction_types(text):
    """Extract attraction types to exclude."""
    types = []
    known_types = [
        "park", "Museum/Memorial Hall", "Cultural Landscape", "natural scenery",
        "red tourism sites", "red tourism", "commercial district",
        "commercial districts", "amusement park/sports entertainment",
        "amusement park", "sports entertainment", "university campus",
        "historical site", "Art Museum", "Cultural Tourism Area", "Other"
    ]
    # Normalized lookup
    type_aliases = {
        "museum/memorial hall": "Museum/Memorial Hall",
        "museums or memorial halls": "Museum/Memorial Hall",
        "museums": "Museum/Memorial Hall",
        "memorial halls": "Museum/Memorial Hall",
        "cultural landscape": "Cultural Landscape",
        "natural scenery": "natural scenery",
        "red tourism sites": "red tourism sites",
        "red tourism": "red tourism sites",
        "commercial district": "commercial district",
        "commercial districts": "commercial district",
        "amusement park/sports entertainment": "amusement park/sports entertainment",
        "amusement park": "amusement park",
        "sports entertainment": "sports entertainment",
        "university campus": "university campus",
        "historical site": "historical site",
        "art museum": "Art Museum",
        "cultural tourism area": "Cultural Tourism Area",
        "park": "park",
        "other": "Other",
    }

    # "do not wish to visit Museum/Memorial Hall"
    # "no visits to commercial districts"
    # "No university campus visits"
    patterns = [
        r"(?:do\s+not|don't|not)\s+(?:want|wish|hope)\s+to\s+visit\s+(?:any\s+)?(.+?)(?:\.|;|,\s*(?:and\s+we|we|want)|$)",
        r"no\s+visit(?:s)?\s+to\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        r"[Nn]o\s+(.+?)\s+visits?(?:\.|;|,|\s)",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            chunk = m.group(1).strip().rstrip(".")
            # Check against aliases
            chunk_lower = chunk.lower()
            if chunk_lower in type_aliases:
                t = type_aliases[chunk_lower]
                if t not in types:
                    types.append(t)
            else:
                # Only trust a comma/and/or-separated PIECE that is itself a known type phrase --
                # a raw substring match against the whole chunk (e.g. alias "park" inside "Shenzhen
                # Bay Park") misfires on proper-noun venue names that merely contain a type word.
                for piece in re.split(r"\s+and\s+|\s+or\s+|,\s*", chunk_lower):
                    piece = piece.strip()
                    canonical = type_aliases.get(piece)
                    if canonical and canonical not in types:
                        types.append(canonical)

    # "Do not include any of these attraction types: X and Y." (familiar-100). Values are written
    # in the oracle's own vocabulary/casing, so they are kept verbatim rather than routed through
    # the alias table (which lower-cases and would drop unaliased types like "Library/Memorial
    # Hall"). The "attraction types" category cannot collide with the bare "attractions" name
    # family: the ':' anchor stops each extractor at its own line.
    for t in _do_not_include_items(text, r"attraction\s+types?") or []:
        if t not in types:
            types.append(t)

    return types if types else None


def parse_excluded_attractions(text):
    """Extract specific attraction names to NOT visit."""
    names = []

    patterns = [
        r"(?:do\s+not|don't|not)\s+(?:want|wish|hope)\s+to\s+visit\s+(.+?)(?:\.|;|,\s*(?:and\s+we|we\s+want|want|the)|$)",
        r"[Nn]o\s+visit\s+to\s+(.+?)(?:\.|;|$)",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            chunk = m.group(1).strip().rstrip(".")
            # Check if it's a type reference (not a specific name)
            known_type_words = {"museum/memorial hall", "cultural landscape", "natural scenery",
                               "red tourism sites", "red tourism", "commercial district",
                               "commercial districts", "amusement park", "park", "parks",
                               "university campus", "historical site", "art museum",
                               "cultural tourism area", "other", "sports entertainment",
                               "amusement park/sports entertainment venues",
                               "amusement park/sports entertainment"}
            # If all words map to type keywords, it's a type exclusion, not name exclusion
            chunk_lower = chunk.lower().strip()
            if chunk_lower in known_type_words:
                continue
            # Check for "and" separated type exclusions
            if all(p.strip().lower() in known_type_words for p in re.split(r"\s+and\s+|,\s*", chunk_lower)):
                continue
            # It's a specific name
            parts = re.split(r"\s+and\s+", chunk)
            for p in parts:
                p = p.strip().rstrip(".")
                if p and len(p) > 2 and p.lower() not in known_type_words:
                    names.append(p)

    # "Do not include any of these attractions: X and Y." (familiar-100). The "attractions"
    # category is anchored at ':' so it never fires on the sibling "attraction types:" line.
    for n in _do_not_include_items(text, r"attractions?") or []:
        if n and n not in names:
            names.append(n)

    return names if names else None


def parse_free_attractions(text):
    """Check if only free attractions are required."""
    return bool(re.search(r"(?:only|just)\s+(?:want\s+to\s+)?(?:visit\s+)?free\s+attractions", text, re.I))


def parse_room_type(text):
    """Extract preferred room type."""
    # Triggers: "stay in a ... room", "prefer a ... room", "want ... room", and the familiar-100
    # "(Each accommodation stay must) use ...-bed rooms" phrasing.
    m = re.search(
        r"(?:stay\s+in\s+(?:a\s+)?|prefer\s+(?:a\s+)?|want\s+|(?:must\s+)?use\s+)"
        r"(single-bed|double-bed|twin-bed|single\s+bed|double\s+bed|twin)\s*rooms?",
        text, re.I,
    )
    if m:
        rt = m.group(1).lower()
        if "single" in rt:
            return "single"
        elif "double" in rt:
            return "double"
        elif "twin" in rt:
            return "twin"
    # "stay in twin rooms"
    if re.search(r"stay\s+in\s+(?:a\s+)?twin\s+rooms?", text, re.I):
        return "twin"
    return None


def parse_hotel_type(text):
    """Extract preferred hotel amenity type (e.g., Sauna, Swimming pool)."""
    patterns = [
        r"hotel\s+(?:of\s+)?(?:the\s+)?type[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        r"hotel\s+types?[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        r"stay\s+(?:at|in)\s+(?:one\s+of\s+)?(?:the\s+following\s+)?hotel\s+types?[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        r"types?\s+of\s+hotels?[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip().rstrip(".")
    return None


def parse_hotel_nearby(text):
    """Extract hotel proximity constraint: (distance_km, reference_point)."""
    patterns = [
        r"(?:accommodation|hotel|stay)\s+(?:should\s+be\s+)?within\s+([\d.]+)\s*(?:km|kilometers?)\s+of\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        r"(?:accommodation|hotel)\s+(?:is|should\s+be)\s+within\s+([\d.]+)\s*(?:km|kilometers?)\s+of\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        r"within\s+([\d.]+)\s*(?:km|kilometers?)\s+of\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            reference = re.sub(r"^the\s+", "", m.group(2).strip().rstrip("."), flags=re.I).strip()
            return {"distance_km": float(m.group(1)), "reference": reference}
    return None


def parse_required_hotels(text):
    """Extract specific hotel names that must be stayed at."""
    names = []
    patterns = [
        r"(?:stay\s+at|stay\s+in)\s+(?:the\s+following\s+)?(?:hotel[:\s]+)?(.+?)(?:\.|;|,\s*(?:and\s+we|we)|$)",
        r"(?:wish|hope|want)\s+to\s+stay\s+at\s+(?:the\s+following\s+)?(?:hotel[:\s]+)?(.+?)(?:\.|;|,\s*(?:and\s+we|we)|$)",
        r"stay\s+at\s+(?:one\s+of\s+)?(?:the\s+following\s+)?hotels?[:\s]+(.+?)(?:\.|;|,\s*(?:and\s+we|we)|$)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            # Negation guard: "do not wish to stay at ..." is an *exclusion*
            # (parse_excluded_hotels handles it), never a required hotel.
            if _negated_before(text, m.start()):
                continue
            chunk = _truncate_at_negation(m.group(1).strip().rstrip("."))
            if not chunk:
                continue
            # "Stay at X between 21:39 and 24:00" is a time-window/position constraint
            # (parse_activity_time_windows owns it), not a required-hotel-name list. Without this
            # guard the broad "stay at ..." pattern captures the venue plus its window ("... between
            # 21:39") and splits it into junk names -- the dominant required_hotels precision leak.
            if re.search(r"\bbetween\s+\d{1,2}:\d{2}", chunk, re.I):
                continue
            # "Stay at the following hotels: X and Y" -- the broad pattern's optional
            # "(?:hotel[:\s]+)?" fails to consume the plural "hotels:" label, leaving a junk
            # "hotels: X" first name. The dedicated "hotels?[:\s]+" pattern below extracts the
            # clean list, so drop the label-prefixed chunk here.
            if re.match(r"hotels?\s*:", chunk, re.I):
                continue
            # Skip if it matches room type or hotel type patterns
            if re.match(r"(?:a\s+)?(single|double|twin)", chunk, re.I):
                continue
            if re.match(r"(?:a\s+)?hotel\s+(?:of\s+)?(?:the\s+)?type", chunk, re.I):
                continue
            if re.match(r"(?:one\s+of\s+)?(?:the\s+following\s+)?(?:hotel\s+)?types?", chunk, re.I):
                continue
            # Skip "a hotel with/that" patterns (amenity references)
            if re.match(r"(?:a\s+)?hotel\s+(?:with|that)", chunk, re.I):
                continue
            parts = re.split(r"\s+and\s+", chunk)
            for p in parts:
                p = p.strip().rstrip(".")
                if p and len(p) > 3 and p not in names:
                    names.append(p)
    return names if names else None


def parse_excluded_hotels(text):
    """Extract specific hotel names to NOT stay at."""
    names = []
    patterns = [
        r"(?:do\s+not|don't|not)\s+(?:want|wish|hope)\s+to\s+stay\s+at\s+(?:the\s+following\s+)?(?:hotels?[:\s]+)?(.+?)(?:\.|;|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            chunk = m.group(1).strip().rstrip(".")
            parts = re.split(r"\s+and\s+", chunk)
            for p in parts:
                p = p.strip().rstrip(".")
                if p and len(p) > 3:
                    names.append(p)

    # "Do not include any of these hotels: X and Y." (familiar-100). The "hotels" category is
    # anchored at ':' so it never fires on the sibling "hotel feature types:" line.
    for n in _do_not_include_items(text, r"hotels?") or []:
        if n and n not in names:
            names.append(n)

    return names if names else None


_CONTAINED_BETWEEN_WINDOW_RE = re.compile(
    r"^[ \t]*(?:\d+\.[ \t]+)?"
    r"(?:visit|(?:dine|stay)[ \t]+at)[ \t]+"
    r"(?P<location>.+?)[ \t]+between[ \t]+"
    r"(?P<start>\d{1,2}:\d{2})[ \t]+and[ \t]+(?P<end>\d{1,2}:\d{2})"
    r"[ \t]*[.;]?[ \t]*$",
    re.I | re.M,
)


def parse_stay_duration(text):
    """Extract minimum stay duration at a specific location."""
    constraints = []
    seen = set()

    def _add(loc, minutes):
        loc = loc.strip().rstrip(".")
        if loc and loc not in seen:
            seen.add(loc)
            constraints.append({"location": loc, "min_minutes": int(minutes)})

    for m in re.finditer(r"stay\s+at\s+(.+?)\s+for\s+(?:at\s+least\s+)?(\d+)\s*minutes?", text, re.I):
        _add(m.group(1), m.group(2))
    for m in re.finditer(r"spend\s+(?:at\s+least\s+)?(\d+)\s*minutes?\s+at\s+(.+?)(?:\.|;|,|$)", text, re.I):
        _add(m.group(2), m.group(1))
    between_text = _CONTAINED_BETWEEN_WINDOW_RE.sub("", text)
    # "visit/be at X between A and B" -> min stay = (B - A) minutes
    for m in re.finditer(r"(?:visit|be\s+at)\s+(.+?)\s+between\s+(\d{1,2}:\d{2})\s+and\s+(\d{1,2}:\d{2})", between_text, re.I):
        dur = _hhmm_to_min(m.group(3)) - _hhmm_to_min(m.group(2))
        if dur > 0:
            _add(m.group(1), dur)
    return constraints if constraints else None


def parse_conditional_transport(text):
    """Extract conditional transport rule: if distance > X km, take taxi."""
    m = re.search(r"if\s+(?:the\s+)?distance\s+(?:between\s+two\s+locations\s+)?exceeds?\s+([\d.]+)\s*(?:km|kilometers?)", text, re.I)
    if m:
        threshold = float(m.group(1))
        # What mode to use
        mode_m = re.search(r"exceeds?\s+[\d.]+\s*(?:km|kilometers?),?\s*(?:then\s+)?(?:take\s+(?:a\s+)?|use\s+)(taxi|metro|walk)", text, re.I)
        mode = mode_m.group(1).lower() if mode_m else "taxi"
        return {"threshold_km": threshold, "mode": mode}
    return None


def parse_required_restaurants(text):
    """Extract specific restaurant names that must be visited.

    Guards against negated phrasing ("do not want to try ...") which must map to *excluded*
    restaurants / cuisine types, not required ones.
    """
    names = []
    # Negation immediately preceding the "want/wish/hope to try" trigger.
    neg_prefix = re.compile(r"(?:do\s+not|don't|didn't|does\s+not|do\s+n't|not|avoid|never|no)\s+$", re.I)

    patterns = [
        r"(?:want|wish|hope)\s+to\s+(?:try|dine\s+at)\s+(?:the\s+following\s+)?(?:restaurants?[:\s]+)?(.+?)(?:\.|;|$)",
        r"(?:want|wish|hope)\s+to\s+(?:try|dine\s+at)\s+(?:these\s+)?restaurants?[:\s]+(.+?)(?:\.|;|$)",
        # Bare imperative ("Try one of these restaurants: X"), common in OR-arm bullet text with
        # no surrounding "we want to" framing (plan3 G3/N3.1) -- anchored to the start of the text.
        r"^try\s+(?:one\s+of\s+(?:the\s+following|these)\s+)?restaurants?[:\s]+(.+?)(?:\.|;|$)",
    ]

    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            # Skip when the trigger is negated ("do not want to try ...").
            if neg_prefix.search(text[: m.start()]):
                continue
            chunk = m.group(1).strip().rstrip(".")
            # Skip cuisine-TYPE phrasing ("of the type X" / "of the following type(s): X"); those
            # are not restaurant names.
            if re.match(r"of\s+(?:the\s+)?(?:following\s+)?types?\b", chunk, re.I):
                continue
            # Split on " and " or ", "
            parts = re.split(r"\s+and\s+|,\s*", chunk)
            for p in parts:
                p = p.strip()
                if p and len(p) > 2:
                    # Skip if it's a cuisine type word
                    cuisine_words = {"hot pot", "a hot pot", "hot pot restaurant",
                                    "chinese", "western", "japanese", "korean"}
                    if p.lower() in cuisine_words:
                        continue
                    if p not in names:
                        names.append(p)

    # "Dine at the following restaurants: X and Y." (familiar-100). Anchored at ':' so it stays on
    # the restaurant-name line and never fires on "restaurant types:" (-> cuisine_preference).
    for n in _the_following_items(text, r"restaurants?") or []:
        if n and n not in names:
            names.append(n)

    return names if names else None


def parse_excluded_restaurants(text):
    """Extract specific restaurant names to NOT visit.

    Handles singular/plural ("restaurant"/"restaurants"), an optional "the following" / "the"
    determiner, and "try/dine at/visit" verbs. Cuisine-TYPE phrasing ("of the type X") is left to
    parse_excluded_cuisine_types.
    """
    names = []

    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want|wish|hope)\s+to\s+(?:try|dine\s+at|visit)\s+"
        r"(?:the\s+following\s+)?(?:the\s+)?restaurants?[:\s]+(.+?)(?:\.|;|$)",
        text, re.I,
    )
    if m:
        chunk = m.group(1).strip().rstrip(".")
        # Not a restaurant name list — it's a cuisine type ("of the type X" / "of the following
        # type(s): X"); handled elsewhere.
        if re.match(r"of\s+(?:the\s+)?(?:following\s+)?types?\b", chunk, re.I):
            return None
        parts = re.split(r"\s+and\s+|,\s*", chunk)
        for p in parts:
            p = p.strip()
            if p and len(p) > 2 and p not in names:
                names.append(p)

    # "Do not include any of these restaurants: X and Y." (familiar-100). Anchored at ':' so it
    # stays on the restaurant-name line and never fires on "restaurant types:" (-> cuisine).
    for n in _do_not_include_items(text, r"restaurants?") or []:
        if n and n not in names:
            names.append(n)

    return names if names else None


def parse_cuisine_preference(text):
    """Extract cuisine/restaurant type preference (positive only)."""
    cuisines = []
    _STOP = {"the", "following", "these", "the following", "of the type", "a"}
    neg_prefix = re.compile(r"(?:do\s+not|don't|didn't|does\s+not|not|avoid|never|no)\s+$", re.I)
    # "want to try a Hot pot restaurant"
    m = re.search(r"(?:want|wish|hope)\s+to\s+try\s+(?:a\s+)?(.+?)\s+restaurant", text, re.I)
    if m and not neg_prefix.search(text[: m.start()]):
        cuisine = m.group(1).strip()
        if cuisine.lower() not in _STOP:
            cuisines.append(cuisine)

    # "try one of these restaurant types: Beijing cuisine, Barbecue, or Japanese cuisine"
    m = re.search(r"(?:try|visit)\s+(?:one\s+of\s+)?(?:these|the\s+following)\s+restaurant\s+types?[:\s]+(.+?)(?:\.|;|$)", text, re.I)
    if m and not _negated_before(text, m.start()):
        chunk = m.group(1).strip().rstrip(".")
        parts = re.split(r",\s*(?:or\s+)?|\s+or\s+", chunk)
        for p in parts:
            p = p.strip()
            if p and p.lower() not in {"the", "following", "these"}:
                cuisines.append(p)

    # "try the following types of restaurants: Hot pot and Western cuisine". Negated phrasing
    # ("do not want to try the following types of restaurants: X") maps to excluded_cuisine_types,
    # not here -- same guard as the "restaurants of type" pattern below.
    m = re.search(r"(?:try|visit)\s+(?:the\s+following\s+)?types?\s+of\s+restaurants?[:\s]+(.+?)(?:\.|;|$)", text, re.I)
    if m and not _negated_before(text, m.start()):
        chunk = m.group(1).strip().rstrip(".")
        parts = re.split(r"\s+and\s+|,\s*(?:or\s+)?|\s+or\s+", chunk)
        for p in parts:
            p = p.strip()
            if p and p.lower() not in {"the", "following", "these"}:
                if p not in cuisines:
                    cuisines.append(p)

    # "hope to try restaurants of the following type: Shanghai cuisine" (restaurant(s) BEFORE
    # "of the (following) type(s)", vs. the "types of restaurants" pattern above). Negated phrasing
    # ("do not want to try restaurants of the type X") maps to excluded_cuisine_types, not here --
    # use the wider lookback (_negated_before) since "restaurants" isn't adjacent to "do not".
    m = re.search(
        r"restaurants?\s+of\s+(?:the\s+)?(?:following\s+)?types?[:\s]+(.+?)(?:\.|;|$)", text, re.I
    )
    if m and not _negated_before(text, m.start()):
        chunk = m.group(1).strip().rstrip(".")
        parts = re.split(r"\s+and\s+|,\s*(?:or\s+)?|\s+or\s+", chunk)
        for p in parts:
            p = p.strip()
            if p and p.lower() not in {"the", "following", "these"}:
                if p not in cuisines:
                    cuisines.append(p)

    # "Try a Southeast Asian cuisine restaurant"
    m = re.search(r"[Tt]ry\s+(?:a\s+)?(.+?)\s+cuisine\s+restaurant", text, re.I)
    if m and not _negated_before(text, m.start()):
        c = m.group(1).strip()
        full = c + " cuisine"
        if full not in cuisines:
            cuisines.append(full)

    # "Include the following restaurant types: X and Y." (familiar-100) -> cuisine preference.
    # Values are verbatim oracle vocabulary; compound cuisines that legitimately contain " and "
    # (e.g. "Fast food and casual dining") are protected from the splitter.
    for c in _the_following_items(
        text, r"restaurant\s+types?", protect=_compound_cuisine_types
    ) or []:
        if c and c not in cuisines:
            cuisines.append(c)

    if len(cuisines) == 1:
        return cuisines[0]
    elif cuisines:
        return cuisines
    return None


_NEG_TRY = (
    r"(?:do\s+not|don't|didn't|does\s+not|not|avoid|never)\s+(?:want|wish|hope)?\s*(?:to\s+)?"
    r"(?:try|dine\s+at|eat|visit|have)\s+(?:at\s+)?"
)


def parse_excluded_cuisine_types(text):
    """Extract cuisine/restaurant TYPES the traveler wants to avoid.

    Handles negated type phrasing such as "do not want to try restaurants of the type Snacks"
    (-> ["Snacks"]), the reversed word order "the following type(s) of restaurant(s): X", and
    "restaurants serving X". Restaurant *names* under negation are handled by
    parse_excluded_restaurants.
    """
    types = []
    patterns = [
        # "do not want to try (restaurants) of the type X (and Y)"
        _NEG_TRY + r"(?:restaurants?\s+)?of\s+(?:the\s+)?types?\s+(.+?)(?:\.|;|$)",
        # "do not want to try the following type(s) of restaurant(s): X (and Y)" (reversed order)
        _NEG_TRY + r"(?:the\s+following\s+)?types?\s+of\s+restaurants?[:\s]+(.+?)(?:\.|;|$)",
        # "do not want to try restaurants serving X"
        _NEG_TRY + r"restaurants?\s+serving\s+(.+?)(?:\.|;|$)",
        # "do not want ... X-type restaurants" (anchor word dropped -- it's not part of the value)
        _NEG_TRY + r"(?:the\s+)?(.+?)\s+type\s+restaurants?",
        # "do not want ... X cuisine restaurants" (anchor word "cuisine" IS part of the value, so
        # it stays inside the capture group instead of being consumed as a separator)
        _NEG_TRY + r"(?:the\s+)?(.+?\s+cuisine)\s+restaurants?",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            chunk = m.group(1).strip().rstrip(".")
            for p in re.split(r"\s+and\s+|,\s*(?:and\s+|or\s+)?|\s+or\s+", chunk):
                p = p.strip().strip('"').strip()
                if p and p.lower() not in {"the", "following", "these", "a"}:
                    if p not in types:
                        types.append(p)

    # "Do not include any of these restaurant types: X and Y." (familiar-100) -> excluded cuisine
    # types. Values are verbatim oracle vocabulary; compound cuisines that legitimately contain
    # " and " (e.g. "Fast food and casual dining") are protected from the splitter.
    for t in _do_not_include_items(
        text, r"restaurant\s+types?", protect=_compound_cuisine_types
    ) or []:
        if t and t not in types:
            types.append(t)

    return types if types else None


def _cap_first(s):
    s = s.strip().rstrip(".")
    return s[:1].upper() + s[1:] if s else s


def _split_types(chunk):
    out = []
    for p in re.split(r"\s+and\s+|,\s*(?:and\s+|or\s+)?|\s+or\s+", chunk):
        # Strip a leading article ("a Sunbathing area" -> "Sunbathing area") before
        # capitalizing, so "hotel with a/an X" phrasing matches the oracle's bare-noun vocabulary.
        p = re.sub(r"^(?:a|an)\s+", "", p.strip(), flags=re.I)
        p = _cap_first(p)
        if p and p.lower() not in {"the", "following", "these", "a", "an", ""}:
            if p not in out:
                out.append(p)
    return out


def parse_required_hotel_types(text):
    """Extract hotel FEATURE types, split into (any_types, all_types).

    "one of the following (hotel) types: A, B"  -> any_types (at least one must hold)
    "hotel of (the) type X" / "hotel that offers X" -> all_types (all must hold)
    Values are normalized to sentence case to match the oracle vocabulary
    ("free parking" -> "Free parking").
    """
    any_types, all_types = [], []
    m = re.search(
        r"one\s+of\s+the\s+following\s+(?:hotel\s+)?types?(?:\s+of\s+hotels?)?[:\s]+(.+?)(?:\.|;|$)",
        text, re.I,
    )
    # Required_* extractors must not fire on a negated-desire clause ("do not want to include the
    # following hotel feature types: ...") -- that is an exclusion, never a hard requirement.
    if m and not _negated_before(text, m.start()):
        any_types = _split_types(m.group(1))
    if not any_types:
        for pat in (
            # "Include the following hotel feature types: X and Y." (familiar-100) -- all required.
            r"(?:include\s+)?the\s+following\s+hotel\s+feature\s+types?[:\s]+(.+?)(?:\.|;|$)",
            r"hotels?\s+of\s+(?:the\s+)?type[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
            r"stay\s+(?:at|in)\s+(?:a\s+)?hotels?\s+of\s+(?:the\s+)?type[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
            r"hotels?\s+(?:that\s+)?offer(?:s|ing)?\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
            r"hotels?\s+with\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)",
        ):
            m = re.search(pat, text, re.I)
            if m and not _negated_before(text, m.start()):
                all_types = _split_types(m.group(1))
                break
    return any_types, all_types


def _hhmm_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def parse_activity_time_windows(text):
    """Extract per-location time windows in the oracle shape.

    {location, earliest, latest, end_after, end_before}
      - "arrive at/reach X no later than T"    -> latest=T
      - "arrive at/reach X no earlier than T"   -> earliest=T
      - "leave/depart (from) X no earlier than T" / "depart no earlier than T from X" -> end_after=T
      - "leave/depart (from) X no later than T"  -> end_before=T
      - "visit/be at X between A and B"          -> latest=A, end_after=B
      - numbered/line-start "Visit/Dine at/Stay at X between A and B"
        -> earliest=A, end_before=B (the activity must fit inside the interval)
    """
    def _loc(s):
        return re.sub(r"^the\s+", "", s.strip().rstrip("."), flags=re.I).strip()

    contained = [
        {
            "location": _loc(match.group("location")),
            "earliest": match.group("start"),
            "latest": None,
            "end_after": None,
            "end_before": match.group("end"),
        }
        for match in _CONTAINED_BETWEEN_WINDOW_RE.finditer(text)
    ]
    # Preserve the legacy free-form "wish to visit X between A and B" cover-window
    # interpretation below without letting it match the line-scoped contained form too.
    text = _CONTAINED_BETWEEN_WINDOW_RE.sub("", text)

    by_loc = {}
    order = []

    def _mark(loc):
        loc = _loc(loc)
        if loc not in order:
            order.append(loc)

    def _set(loc, key, val):
        loc = _loc(loc)
        w = by_loc.setdefault(loc, {"location": loc, "earliest": None, "latest": None,
                                    "end_after": None, "end_before": None})
        if w[key] is None:
            w[key] = val

    for m in re.finditer(r"(?:arrive\s+at|reach)\s+(.+?)\s+no\s+later\s+than\s+(\d{1,2}:\d{2})", text, re.I):
        _mark(m.group(1)); _set(m.group(1), "latest", m.group(2))
    for m in re.finditer(r"(?:arrive\s+at|reach)\s+(.+?)\s+no\s+earlier\s+than\s+(\d{1,2}:\d{2})", text, re.I):
        _mark(m.group(1)); _set(m.group(1), "earliest", m.group(2))
    for m in re.finditer(r"(?:leave|depart(?:\s+from)?)\s+(.+?)\s+no\s+earlier\s+than\s+(\d{1,2}:\d{2})", text, re.I):
        _mark(m.group(1)); _set(m.group(1), "end_after", m.group(2))
    for m in re.finditer(r"(?:leave|depart(?:\s+from)?)\s+(.+?)\s+no\s+later\s+than\s+(\d{1,2}:\d{2})", text, re.I):
        _mark(m.group(1)); _set(m.group(1), "end_before", m.group(2))
    # "depart no earlier/later than T from X" (reversed order)
    for m in re.finditer(r"depart\s+no\s+earlier\s+than\s+(\d{1,2}:\d{2})\s+from\s+(.+?)(?:\.|;|,|$)", text, re.I):
        _mark(m.group(2)); _set(m.group(2), "end_after", m.group(1))
    for m in re.finditer(r"depart\s+no\s+later\s+than\s+(\d{1,2}:\d{2})\s+from\s+(.+?)(?:\.|;|,|$)", text, re.I):
        _mark(m.group(2)); _set(m.group(2), "end_before", m.group(1))
    # "visit/be at X between A and B"
    for m in re.finditer(r"(?:visit|be\s+at)\s+(.+?)\s+between\s+(\d{1,2}:\d{2})\s+and\s+(\d{1,2}:\d{2})", text, re.I):
        _mark(m.group(1)); _set(m.group(1), "latest", m.group(2)); _set(m.group(1), "end_after", m.group(3))

    return (contained + [by_loc[loc] for loc in order]) if (contained or order) else None


def detect_disjunctive(text):
    """Detect if the query has OR/disjunctive constraints."""
    if re.search(r"(?:at\s+least\s+one|either|any\s+one)\s+of\s+(?:the\s+following)?", text, re.I):
        return True
    # Inline: "require either X or Y"
    if re.search(r"require\s+either\s+.+?\s+or\s+", text, re.I):
        return True
    # "satisfying either: 1. X 2. Y"
    if re.search(r"satisfying\s+either", text, re.I):
        return True
    # "(must/need to) satisfy one of the following: 1. X 2. Y" -- distinct from "stay at one of
    # the following hotels: X" (a single-list membership constraint, not a disjunctive branch;
    # that phrasing has no numbered alternatives so it's excluded by requiring one below).
    if re.search(r"satisfy\s+one\s+of\s+(?:the\s+)?following", text, re.I) and re.search(r"\b1[\.\)]", text):
        return True
    return False


def split_disjunctive_groups(text):
    """Split disjunctive constraints into groups."""
    # Pattern: "1. ... 2. ..." or "- ... - ..."
    groups = []

    # Inline: "require either visiting X or trying Y"
    m = re.search(r"require\s+either\s+(.+?)\s+or\s+(.+?)(?:\.|;|$)", text, re.I)
    if m:
        return [m.group(1).strip().rstrip("."), m.group(2).strip().rstrip(".")]

    # "satisfying either: 1. X; 2. Y"
    m = re.search(r"satisfying\s+either[:\s]+(?:1[\.\)]\s*)?(.+)", text, re.I | re.S)
    if m:
        remainder = m.group(1).strip()
        parts = re.split(r"\s*(?:\n\s*)?2[\.\)]\s*", remainder, maxsplit=1)
        if len(parts) == 2:
            return [parts[0].strip().rstrip("."), parts[1].strip().rstrip(".")]

    # Find the disjunctive marker phrase (not the colon/list-number handling -- that's done below
    # via anchored re.sub, which tolerates a label word between "the following" and the colon,
    # e.g. "the following conditions:", that would otherwise leak into the first arm's text).
    m = re.search(
        r"(?:at\s+least\s+one|either|any\s+one|must\s+satisfy\s+(?:either|any\s+one)"
        r"|(?:must\s+|need\s+to\s+)?satisfy\s+one\s+of)\s+(?:of\s+)?(?:the\s+following)?",
        text, re.I,
    )
    if not m:
        # Try "satisfy either ...": 1. X 2. Y"
        m = re.search(r"(?:satisfy|meet)\s+(?:either|any\s+one)", text, re.I)
    if m:
        remainder = text[m.end():]
        # Strip a trailing label + colon/period ("... conditions:", ": ") ...
        remainder = re.sub(r"^[^:.\n]*[:.]\s*", "", remainder, count=1)
        # ... then a leading numbered-item marker ("1.", "1)") before the first arm's text.
        remainder = re.sub(r"^\n?\s*(?:1[\.\)]\s*)?", "", remainder).strip()
        # Split on "2." or "\n2." etc.
        parts = re.split(r"\s*(?:\n\s*)?2[\.\)]\s*", remainder, maxsplit=1)
        if len(parts) == 2:
            groups = [parts[0].strip().rstrip("."), parts[1].strip().rstrip(".")]
        else:
            # Try splitting on "; " or numbered items
            parts = re.split(r"\s*;\s*|\s*\n\s*", remainder)
            groups = [p.strip().rstrip(".") for p in parts if p.strip()]

    return groups if len(groups) >= 2 else None


def parse_single_constraint_text(text):
    """Parse a single constraint clause (used for disjunctive branches)."""
    result = {}

    budgets = parse_budget(text)
    if budgets:
        result["budgets"] = budgets

    if parse_free_attractions(text):
        result["free_attractions_only"] = True

    intercity = parse_intercity_mode(text)
    if intercity:
        result["intercity_mode"] = intercity

    inner_excl = parse_inner_transport_restrictions(text)
    if inner_excl:
        result["excluded_inner_transport"] = inner_excl

    room = parse_room_type(text)
    if room:
        result["room_type"] = room

    any_hotel_types, all_hotel_types = parse_required_hotel_types(text)
    if any_hotel_types:
        result["required_hotel_any_types"] = any_hotel_types
    if all_hotel_types:
        result["required_hotel_all_types"] = all_hotel_types

    hotel_near = parse_hotel_nearby(text)
    if hotel_near:
        result["hotel_nearby"] = hotel_near
        # Mirror solver_constraints.py::_parse_hotel_distance's oracle-mode behavior: the shared
        # solver-dict schema also expects this as a list-shaped poi_distance_hotel family, which
        # the no-oracle NL path previously never populated (100% missing on that family).
        result["poi_distance_hotel"] = [hotel_near]

    req_attr = parse_required_attractions(text)
    if req_attr:
        result["required_attractions"] = req_attr

    req_types = parse_required_attraction_types(text)
    if req_types:
        result["required_attraction_types"] = req_types

    excl_types = parse_excluded_attraction_types(text)
    if excl_types:
        result["excluded_attraction_types"] = excl_types

    excl_attr = parse_excluded_attractions(text)
    if excl_attr:
        result["excluded_attractions"] = excl_attr

    req_rest = parse_required_restaurants(text)
    if req_rest:
        result["required_restaurants"] = req_rest

    excl_rest = parse_excluded_restaurants(text)
    if excl_rest:
        result["excluded_restaurants"] = excl_rest

    cuisine = parse_cuisine_preference(text)
    if cuisine:
        result["cuisine_preference"] = cuisine

    excl_cuisine = parse_excluded_cuisine_types(text)
    if excl_cuisine:
        result["excluded_cuisine_types"] = excl_cuisine

    time_windows = parse_activity_time_windows(text)
    if time_windows:
        result["activity_time_windows"] = time_windows

    cond = parse_conditional_transport(text)
    if cond:
        result["conditional_transport"] = cond

    req_hotels = parse_required_hotels(text)
    if req_hotels:
        result["required_hotels"] = req_hotels

    excl_hotels = parse_excluded_hotels(text)
    if excl_hotels:
        result["excluded_hotels"] = excl_hotels

    stay_dur = parse_stay_duration(text)
    if stay_dur:
        result["stay_duration"] = stay_dur

    # position_presence: any location that carries a time-window or stay-duration constraint must
    # appear in the plan (mirrors the oracle, which lists these locations explicitly).
    presence = []
    for w in result.get("activity_time_windows", []) or []:
        loc = w.get("location")
        if loc and loc not in presence:
            presence.append(loc)
    for sd in result.get("stay_duration", []) or []:
        loc = sd.get("location")
        if loc and loc not in presence:
            presence.append(loc)
    if presence:
        result["position_presence"] = presence

    return result


def parse_hard_logic(query):
    """Parse constraints directly from hard_logic_py code (exact values)."""
    constraints = {}
    hard_logic_list = query.get("hard_logic_py", [])
    disjunctive_groups = []
    is_disjunctive = False

    for logic in hard_logic_list:
        # Skip people_count and day_count (already in query fields)
        if "people_count(plan)" in logic or "day_count(plan)" in logic:
            continue
        # Skip ticket/taxi count checks (structural, not content constraints)
        if "activity_tickets(activity)" in logic and "result=True" in logic:
            continue
        if "taxi_cars(activity_transports" in logic:
            continue

        # Disjunctive (result_list pattern)
        if "result_list" in logic:
            is_disjunctive = True
            # Parse each constraint within the disjunctive block
            groups = _parse_disjunctive_logic(logic)
            if groups:
                disjunctive_groups = groups
            continue

        # Single constraint patterns
        parsed = _parse_single_logic(logic)
        if parsed:
            for k, v in parsed.items():
                if k == "budgets":
                    constraints.setdefault("budgets", {}).update(v)
                elif isinstance(v, list) and k in constraints:
                    constraints[k].extend(v)
                else:
                    constraints[k] = v

    if is_disjunctive and disjunctive_groups:
        return {"disjunctive": True, "groups": disjunctive_groups}

    constraints["disjunctive"] = False
    return constraints


def _parse_disjunctive_logic(logic):
    """Parse a disjunctive (result_list) block into separate constraint groups."""
    groups = []
    # Split on result_list.append(result) to find each sub-constraint
    parts = re.split(r"result_list\.append\(result\)", logic)
    for part in parts:
        if not part.strip():
            continue
        parsed = _parse_single_logic(part)
        if parsed:
            groups.append(parsed)
    return groups if len(groups) >= 2 else None


def _parse_single_logic(logic):
    """Parse a single hard_logic_py constraint block."""
    result = {}

    # --- Excluded attraction names (check BEFORE required) ---
    m = re.search(r'result\s*=\s*not\s*\(\s*\{(.+?)\}\s*(?:&|<=)\s*attraction_name_set', logic)
    if m:
        names = re.findall(r'"([^"]+)"', m.group(1))
        if names:
            result["excluded_attractions"] = names

    # --- Required attraction names (only if not excluded) ---
    if "excluded_attractions" not in result:
        m = re.search(r'\{(.+?)\}\s*(?:&|<=)\s*attraction_name_set', logic)
        if m:
            names = re.findall(r'"([^"]+)"', m.group(1))
            if names:
                result["required_attractions"] = names

    # --- Excluded attraction types (check BEFORE required) ---
    m = re.search(r'result\s*=\s*not\s*\(\s*\{(.+?)\}\s*(?:&|<=)\s*attraction_type_set', logic)
    if m:
        types = re.findall(r'"([^"]+)"', m.group(1))
        if types:
            result["excluded_attraction_types"] = types

    # --- Required attraction types ---
    if "excluded_attraction_types" not in result:
        m = re.search(r'\{(.+?)\}\s*(?:<=|&)\s*attraction_type_set', logic)
        if m:
            types = re.findall(r'"([^"]+)"', m.group(1))
            if types:
                result["required_attraction_types"] = types

    # --- Excluded restaurant names (check BEFORE required) ---
    m = re.search(r'result\s*=\s*not\s*\(\s*\{(.+?)\}\s*(?:&|<=)\s*restaurant_name_set', logic)
    if m:
        names = re.findall(r'"([^"]+)"', m.group(1))
        if names:
            result["excluded_restaurants"] = names

    # --- Required restaurant names ---
    if "excluded_restaurants" not in result:
        m = re.search(r'\{(.+?)\}\s*(?:<=|&)\s*restaurant_name_set', logic)
        if m:
            names = re.findall(r'"([^"]+)"', m.group(1))
            if names:
                result["required_restaurants"] = names

    # --- Excluded restaurant types (check BEFORE required) ---
    m = re.search(r'result\s*=\s*not\s*\(\s*\{(.+?)\}\s*(?:&|<=)\s*restaurant_type_set', logic)
    if m:
        types = re.findall(r'"([^"]+)"', m.group(1))
        if types:
            result["excluded_cuisine_types"] = types

    # --- Required restaurant types (cuisine) ---
    if "excluded_cuisine_types" not in result:
        m = re.search(r'\{(.+?)\}\s*(?:<=|&)\s*restaurant_type_set', logic)
        if m:
            types = re.findall(r'"([^"]+)"', m.group(1))
            if types:
                result["cuisine_preference"] = types if len(types) > 1 else types[0]

    # --- Excluded hotel names (check BEFORE required) ---
    m = re.search(r'result\s*=\s*not\s*\(\s*\{(.+?)\}\s*(?:&|<=)\s*accommodation_name_set', logic)
    if m:
        names = re.findall(r'"([^"]+)"', m.group(1))
        if names:
            result["excluded_hotels"] = names

    # --- Required hotel names ---
    if "excluded_hotels" not in result:
        m = re.search(r'\{(.+?)\}\s*(?:<=|&)\s*accommodation_name_set', logic)
        if m:
            names = re.findall(r'"([^"]+)"', m.group(1))
            if names:
                result["required_hotels"] = names

    # --- Required hotel types ---
    m = re.search(r'\{(.+?)\}\s*(?:<=|&)\s*accommodation_type_set', logic)
    if m and "not(" not in logic[:logic.find(m.group(0))].split('\n')[-1]:
        types = re.findall(r'"([^"]+)"', m.group(1))
        if types:
            result["hotel_type"] = types if len(types) > 1 else types[0]

    # --- Budgets ---
    # Sightseeing: attraction_cost<=X
    m = re.search(r'attraction_cost\s*<=\s*([\d.]+)', logic)
    if m:
        val = float(m.group(1))
        if val == 0:
            result["free_attractions_only"] = True
        else:
            result.setdefault("budgets", {})["sightseeing"] = val

    # Accommodation: accommodation_cost<=X
    m = re.search(r'accommodation_cost\s*<=\s*([\d.]+)', logic)
    if m:
        result.setdefault("budgets", {})["accommodation"] = float(m.group(1))

    # Dining: restaurant_cost<=X
    m = re.search(r'restaurant_cost\s*<=\s*([\d.]+)', logic)
    if m:
        result.setdefault("budgets", {})["dining"] = float(m.group(1))

    # Intercity transport: inter_city_transportation_cost<=X
    m = re.search(r'inter_city_transportation_cost\s*<=\s*([\d.]+)', logic)
    if m:
        result.setdefault("budgets", {})["intercity_transport"] = float(m.group(1))

    # Inner-city transport: inner_city_transportation_cost<=X
    m = re.search(r'inner_city_transportation_cost\s*<=\s*([\d.]+)', logic)
    if m:
        result.setdefault("budgets", {})["inner_transport"] = float(m.group(1))

    # Total: total_cost<=X
    m = re.search(r'total_cost\s*<=\s*([\d.]+)', logic)
    if m:
        result.setdefault("budgets", {})["total"] = float(m.group(1))

    # --- Transport mode restrictions ---
    # not({"taxi"}&inner_city_transportation_set)
    m = re.search(r'result\s*=\s*not\s*\(\s*\{(.+?)\}\s*(?:&|<=)\s*inner_city_transportation_set', logic)
    if m:
        modes = re.findall(r'"([^"]+)"', m.group(1))
        if modes:
            result["excluded_inner_transport"] = modes

    # --- Intercity mode ---
    # Check for airplane/train type constraints
    if "intercity_transport_go" in logic or "intercity_transport_back" in logic:
        intercity = {}
        if "'train'" in logic or '"train"' in logic:
            if "intercity_transport_go" in logic:
                # Look at what it checks
                if re.search(r"intercity_transport_go\s*==\s*['\"]train['\"]", logic):
                    intercity["outbound"] = "train"
                elif re.search(r"intercity_transport_go\s*!=\s*['\"]airplane['\"]", logic):
                    intercity["outbound"] = "train"
            if "intercity_transport_back" in logic:
                if re.search(r"intercity_transport_back\s*==\s*['\"]train['\"]", logic):
                    intercity["return"] = "train"
                elif re.search(r"intercity_transport_back\s*!=\s*['\"]airplane['\"]", logic):
                    intercity["return"] = "train"
        if "'airplane'" in logic or '"airplane"' in logic:
            if re.search(r"intercity_transport_go\s*==\s*['\"]airplane['\"]", logic):
                intercity["outbound"] = "airplane"
            if re.search(r"intercity_transport_back\s*==\s*['\"]airplane['\"]", logic):
                intercity["return"] = "airplane"
        # Handle negation: "not airplane" means train
        if re.search(r"allactivities\(plan\)\[0\]\['type'\]\s*!=\s*\"airplane\"", logic):
            intercity["outbound"] = "train"
        if re.search(r"allactivities\(plan\)\[-1\]\['type'\]\s*!=\s*\"airplane\"", logic):
            intercity["return"] = "train"
        if intercity:
            result["intercity_mode"] = intercity

    # --- Room type ---
    # Real hard_logic_py uses "room_type(activity)!=N" (no target_city arg, "!="not "=="); a scan
    # of every hard_logic_py in the dataset found only codes 1 and 2 ever appear, and every NL
    # query using code 2 says "twin" ("twin beds room" / "a twin room") -- never "double bed".
    m = re.search(r'room_type\(activity(?:,\s*target_city\(plan\))?\)\s*(?:==|!=)\s*([\d]+)', logic)
    if m:
        room_num = int(m.group(1))
        if room_num == 1:
            result["room_type"] = "single"
        elif room_num == 2:
            result["room_type"] = "twin"

    # --- Hotel nearby ---
    m = re.search(r'accommodation_distance\(activity,\s*\"([^\"]+)\",\s*target_city\(plan\)\)\s*<=\s*([\d.]+)', logic)
    if m:
        result["hotel_nearby"] = {"reference": m.group(1), "distance_km": float(m.group(2))}

    # --- Timing constraints ---
    # depart no earlier than
    m = re.search(r'depart_time\(\"([^\"]+)\"\s*,\s*plan\)\s*>=\s*\"(\d{2}:\d{2})\"', logic)
    if m:
        result.setdefault("timing_constraints", []).append(
            {"type": "depart_no_earlier", "location": m.group(1), "time": m.group(2)})
    # arrive no later than
    m = re.search(r'arrive_time\(\"([^\"]+)\"\s*,\s*plan\)\s*<=\s*\"(\d{2}:\d{2})\"', logic)
    if m:
        result.setdefault("timing_constraints", []).append(
            {"type": "arrive_no_later", "location": m.group(1), "time": m.group(2)})

    # --- Stay duration ---
    m = re.search(r'stay_duration\(\"([^\"]+)\"\s*,\s*plan\)\s*>=\s*(\d+)', logic)
    if m:
        result.setdefault("stay_duration", []).append(
            {"location": m.group(1), "min_minutes": int(m.group(2))})

    # --- Conditional transport ---
    m = re.search(r'distance[^<>]*>\s*([\d.]+).*?transport.*?(taxi|metro|walk)', logic, re.S)
    if m:
        result["conditional_transport"] = {"threshold_km": float(m.group(1)), "mode": m.group(2)}

    return result if result else None


def parse_query(query):
    """Parse constraints from hard_logic_py (primary) + NL (supplementary)."""
    # Primary: parse from hard_logic_py (exact values)
    result = parse_hard_logic(query)

    # Supplementary: get NL-only constraints not in hard_logic_py
    text = query["nature_language"]
    nl_parsed = parse_single_constraint_text(text)

    # Merge NL-parsed fields that hard_logic didn't capture
    if not result.get("disjunctive"):
        for key, val in nl_parsed.items():
            if key not in result:
                result[key] = val
    elif result.get("disjunctive") and result.get("groups"):
        # For disjunctive: NL parsing might provide context not in logic
        # (e.g., conditional transport, hotel amenity)
        for key, val in nl_parsed.items():
            if key not in ("disjunctive",):
                # Add NL-only fields at the top level as context
                if key not in result:
                    result[key] = val

    return result


def parse_query_no_oracle(query):
    """Parse constraints from nature_language only (Phase-2: hard_logic_py unavailable).

    Returns a single (non-disjunctive) variant; the parsed verifier and per-query search
    explore satisfying plans without the oracle's disjunctive decomposition.
    """
    result = parse_single_constraint_text(query["nature_language"])
    result["disjunctive"] = False
    # A1: taxi car count is a deterministic function of party size (the oracle always encodes it as
    # ceil(people/4): 1-4 people -> 1 car, 5-8 -> 2, ...). The NL rarely states it explicitly, so
    # derive it here to match the oracle instead of leaving it unconstrained. No-oracle path only;
    # the oracle path already gets it from hard_logic_py.
    try:
        people = int(query.get("people_number", 1) or 1)
    except (TypeError, ValueError):
        people = 1
    result["taxi_cars_equals"] = max(1, math.ceil(people / 4))
    return result
