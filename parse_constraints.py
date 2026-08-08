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
# A period ending the captured list must be a genuine sentence boundary, not an abbreviation
# period embedded in an entity name ("St. Regis", "No. 3955 Baishi Road ..." -- both seen in
# familiar-100 hotel/restaurant names). Rule a period out as a terminator when it directly follows
# one of a short closed set of address/title abbreviations, each checked as a whole word via a
# fixed-width lookbehind so e.g. "Stanford." or "West." never match (grouped by lookbehind width,
# since Python's `re` requires each lookbehind assertion to be fixed-width, though separate
# assertions may still differ in width from each other).
#
# Deliberately *not* also gated on "not followed by a digit": these familiar-100 requirements are
# numbered lists ("... 9. Do not include any of these attractions: X.\n10. Dine at ..."), so a
# genuine end-of-sentence period is routinely followed by whitespace + the next item's digit --
# adding that lookahead would swallow every subsequent numbered requirement into the capture
# instead of just the one abbreviation case it targeted.
_ABBREV_NO_TERM = (
    r"(?<!\bSt)(?<!\bNo)(?<!\bMt)(?<!\bDr)(?<!\bMr)(?<!\bRd)(?<!\bCo)(?<!\bJr)(?<!\bSr)(?<!\bMs)(?<!\bFt)"
    r"(?<!\bAve)(?<!\bInc)(?<!\bLtd)(?<!\bMrs)"
    r"(?<!\bBlvd)"
)
# A bare newline also terminates a captured list (2026-08-07, P15): free-prose "Requirements:"
# blocks put one clause per line with no trailing punctuation ("Do not want to try the following
# restaurants: A and B\nDo not want to stay at the following hotels: C and D"), and `.` never
# matches `\n` regardless, so without this alternative the capture group could not reach any
# terminator at all when a clause was not the last line of the block -- the match failed outright
# rather than mis-capturing. Purely additive: `.+?` still cannot cross a newline either way, so
# this can only turn a previously-failed match (no terminator reachable) into a successful one; it
# never changes where an already-succeeding match stops, since `\n` cannot occur before whatever
# terminator that match already found.
_LIST_TERM = _ABBREV_NO_TERM + r"\.|;|\n|$"


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
    pattern = lead_pattern + category_pattern + r"\s*:\s*(.+?)(?:" + _LIST_TERM + r")"
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


# --- Bare ("un-scoped") total-budget phrasing -----------------------------
#
# Added 2026-08-06 after the generalization probe
# (results/phase2_baselines/screens/20260806_generalization_probe/README.md §6) measured that the
# total-budget family is missed on 91.7-100 % of the released differently-phrased sets: the old
# total-budget route required either the familiar-100 template line ("Keep the total activity and
# in-city transportation cost within N") or the literal word "total". Ordinary prose says
# "with a budget of 6000 RMB" / "Our budget is 4000" / "a travel budget of 4000".
#
# familiar-100 contains the word "budget" in 0/100 queries and "within <N> <currency>" in 0/100, so
# none of these alternatives can fire on it -- the guard is by construction, not by tuning.
_BARE_BUDGET_VALUE = r"(?P<value>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_BARE_BUDGET_APPROX = (
    r"(?:(?:about|around|approximately|roughly|up\s+to|at\s+most|max(?:imum)?(?:\s+of)?|"
    r"no\s+more\s+than|no\s+higher\s+than|not\s+exceeding|does\s+not\s+exceed|less\s+than|"
    r"limited\s+to|capped\s+at|under|below|within)\s+)?"
)
_BARE_BUDGET_CURRENCY_PRE = r"(?:(?:RMB|CNY|¥|￥)\s*)?"
_BARE_BUDGET_CURRENCY_POST = r"(?:\s*(?:RMB|CNY|yuan|元|¥|￥))"

# Scope words: if one of these sits immediately before "budget" (or immediately after the amount as
# "... for accommodation"), the amount is a *scoped* budget already handled above, never the total.
_BARE_BUDGET_SCOPE = (
    r"(?:accommodation|hotel|lodging|room|dining|meal|meals|food|restaurant|catering|"
    r"sightseeing|attraction|attractions|ticket|tickets|entrance|entry|shopping|souvenir|"
    r"transport|transportation|transit|taxi|cab|metro|subway|bus|flight|airfare|train|"
    r"intercity|inter-city|cross-city|intra-city|inner-city|city|local|"
    r"daily|nightly|per\s*day|per\s*night|per\s*person|each\s+day|each\s+person)"
)
_BARE_BUDGET_SCOPE_BEFORE = re.compile(
    _BARE_BUDGET_SCOPE + r"['\u2019]?s?[\s\-]*"
    # A scope word may be separated from "budget" by a generic filler ("intra-city *travel*
    # budget", "hotel *cost* budget"); "travel"/"trip" on their own are NOT scope words, since
    # "a travel budget of 4000" is a total.
    r"(?:(?:travel|trip|transport(?:ation)?|transit|cost|costs|expense|expenses|spending|fee|fees)"
    r"[\s\-]*)?$",
    re.I,
)
_BARE_BUDGET_SCOPE_AFTER = re.compile(
    r"^(?:\s*(?:RMB|CNY|yuan|元|¥|￥))?\s*(?:"
    # "... 500 for accommodation" -- a scoped family, already parsed above.
    r"(?:for|on|towards?)\s+(?:the\s+|our\s+|my\s+)?" + _BARE_BUDGET_SCOPE
    # "... 10,000 RMB per person" / "each" -- a per-head figure, not the plan total, and the
    # oracle's total_cost is plan-wide. Dropping it is safer than multiplying by party size.
    + r"|(?:per|/|a|an|each)\s*(?:person|people|head|adult|traveler|traveller|pax|of\s+us"
    # "... 70 RMB per meal" / "500 a day" / "200 per night" -- a per-unit *rate*. The oracle scores
    # a plan-wide total_cost, so reading a per-meal rate as the trip total imposes a budget an
    # order of magnitude too small and makes the query unsatisfiable -- strictly worse than not
    # extracting it (measured: HF medium e20241028161351544529 "spend no more than 70 RMB per
    # meal" was being read as total=70).
    + r"|meal|meals|dish|day|days|night|nights|room|rooms|hotel|attraction|attractions)"
    + r")",
    re.I,
)

_BARE_TOTAL_BUDGET_PATTERNS = (
    # "with a budget of 6000 RMB", "a travel budget of 4000", "budget of about 8,000 yuan"
    re.compile(r"\bbudget\s+(?:of|at)\s+" + _BARE_BUDGET_APPROX + _BARE_BUDGET_CURRENCY_PRE
               + _BARE_BUDGET_VALUE, re.I),
    # "Our budget is 4000", "the budget: 4000", "budget = 4000", "budget is under 3000"
    re.compile(r"\bbudget\s*(?:is|was|will\s+be|would\s+be|:|=)\s*" + _BARE_BUDGET_APPROX
               + _BARE_BUDGET_CURRENCY_PRE + _BARE_BUDGET_VALUE, re.I),
    # "budget within 5000", "budget under 5000", "budget no more than 5000" -- the qualifier is
    # required here, so a bare "budget 5000 attractions" cannot match.
    re.compile(r"\bbudget\s+" + _BARE_BUDGET_APPROX[:-1] + _BARE_BUDGET_CURRENCY_PRE
               + _BARE_BUDGET_VALUE, re.I),
    # "budget 1000" -- amount immediately after the word, no connector at all (observed in the
    # human-written set: "Budget travel in Beijing, budget 1000, travel by train").
    re.compile(r"\bbudget\s+" + _BARE_BUDGET_CURRENCY_PRE + _BARE_BUDGET_VALUE, re.I),
)

# "keep it within 3000 RMB" / "spend no more than 2000 yuan" -- currency word REQUIRED, because a
# bare "within N" is the familiar-100 scoped-cost template and must not be re-read as a total.
_BARE_TOTAL_SPEND_PATTERN = re.compile(
    r"\b(?:within|under|below|no\s+more\s+than|not\s+exceeding|at\s+most|up\s+to|spend(?:ing)?"
    r"(?:\s+(?:no\s+more\s+than|less\s+than|up\s+to|at\s+most|under|within))?)\s+"
    + _BARE_BUDGET_CURRENCY_PRE + _BARE_BUDGET_VALUE + _BARE_BUDGET_CURRENCY_POST,
    re.I,
)


def _bare_total_budget(text):
    """Total budget from un-scoped prose, or None.

    A candidate is rejected when a scope word (accommodation / dining / sightseeing / transport /
    per-day ...) sits immediately before the word "budget" or immediately after the amount, since
    that amount belongs to one of the scoped families parsed above.
    """
    best = None
    patterns = _BARE_TOTAL_BUDGET_PATTERNS + (_BARE_TOTAL_SPEND_PATTERN,)
    for pattern in patterns:
        for match in pattern.finditer(text):
            head = text[max(0, match.start() - 32):match.start()]
            if _BARE_BUDGET_SCOPE_BEFORE.search(head):
                continue
            if _BARE_BUDGET_SCOPE_AFTER.match(text[match.end():match.end() + 48]):
                continue
            try:
                value = float(match.group("value").replace(",", ""))
            except (TypeError, ValueError):
                continue
            # A total budget below ~50 is not a trip budget (it is a count, a rating, a distance);
            # the released data's smallest total is in the hundreds.
            if value < 50:
                continue
            if best is None or match.start() < best[0]:
                best = (match.start(), value)
        if best is not None:
            return best[1]
    return None


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
        r"(?:intra-city|inner-city|in-city|city|intra\s*city|local)\s*(?:transportation|travel)\s*(?:budget|is)[^0-9]*?([\d]+(?:\.[\d]+)?)",
        text, re.I,
    ):
        if cand.start() > 0 and (text[cand.start() - 1] == "-" or text[cand.start() - 1].isalnum()):
            continue  # part of "cross-city" / "inter-city" / "intercity"
        m = cand
        break
    if not m:
        # "in-city" added 2026-08-06 (P15): released phrasing for the same intra-city budget
        # (local_released_150 uid 20250324225301554257's "the budget for in-city transportation").
        m = re.search(r"budget\s+for\s+(?:intra-city|inner-city|in-city|intra\s*city|local)\s*transportation[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"budget\s+for\s+(?:travel|transport(?:ation)?)\s+within\s+the\s+city[^0-9]*?([\d]+(?:\.[\d]+)?)", text, re.I)
    if not m:
        m = re.search(r"(?:travel|transport(?:ation)?)\s+within\s+the\s+city\s+(?:budget\s+)?is\s+([\d]+(?:\.[\d]+)?)", text, re.I)
    if m:
        budgets["inner_transport"] = float(m.group(1))

    # Total travel budget. The value alternation must try the comma-grouped form first: the old
    # `(\d+)` read "total budget of 10,000" as 10.0 (2026-08-06 audit, hf_human).
    m = re.search(r"total\s*(?:travel\s*|trip\s*)?budget[^0-9]*?" + _BARE_BUDGET_VALUE, text, re.I)
    if m:
        budgets["total"] = float(m.group("value").replace(",", ""))
    elif "total" not in budgets:
        # Un-scoped prose phrasing ("with a budget of 6000 RMB"). See _bare_total_budget.
        bare = _bare_total_budget(text)
        if bare is not None:
            budgets["total"] = bare

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

    # --- positive outbound, "fly" verb: "fly to the destination" ---
    # The mirror of the negated "do not want to fly to the destination" pattern above, which had no
    # affirmative counterpart: a mixed request ("fly to the destination and take the train back")
    # therefore recorded only the return leg and left the outbound one free. Deliberately *not*
    # extended to undirected wording like "fly there" -- that states a mode for the whole trip, and
    # the oracle's undirected clause constrains every intercity leg, so it belongs to the
    # both-legs fallback below rather than to the outbound leg alone.
    if outbound is None:
        m = re.search(r"\bfly(?:ing)?\s+to\s+(?:the\s+)?destination", text, re.I)
        if m:
            outbound = "airplane"

    # Fallback: bare "by train" / "by airplane" without direction context.
    if outbound is None and ret is None:
        m = re.search(r"(?:take|by|use)\s+(?:a\s+|the\s+)?(train|airplane|plane|flight)", text, re.I)
        if m:
            mode = "train" if "train" in m.group(1).lower() else "airplane"
            outbound = mode
            ret = mode

    # Free-prose fallback (P26). The two fallbacks above are template-shaped: they need the literal
    # word "destination", or "take/by/use" immediately followed by the bare mode noun. Ordinary
    # prose states the same requirement as a *verb* ("we have chosen to fly", "we plan to fly
    # round-trip") or with a qualifier between the preposition and the noun ("traveling by
    # high-speed train (G)"), and neither reaches the patterns above -- measured as 33/85 missed
    # intercity clauses on HF ``medium`` and 27/32 on HF ``human``
    # (``scripts/phase2_generalization_probe.py``, ``parse_gap_by_kind``).
    #
    # Only fires when nothing directional was found, so a mixed request ("fly there, take the
    # train back") keeps the per-leg reading the patterns above produced. The oracle's clause for
    # this family constrains the *set* of intercity legs (``intercity_transport_set == {'train'}``),
    # so an undirected statement means both legs, which is what this sets.
    if outbound is None and ret is None:
        mode = _parse_intercity_mode_free_prose(text)
        if mode:
            outbound = ret = mode

    result = {}
    if outbound:
        result["outbound"] = outbound
    if ret:
        result["return"] = ret
    return result if result else None


# A place name, not a mode of travel: "the hotel is near the train station", "close to the
# high-speed rail station". Stripped before any mode word is looked for, so a station mention can
# never be read as a transport requirement.
_INTERCITY_PLACE_NOUN_RE = re.compile(
    r"\b(?:high[-\s]?speed\s+)?(?:train|railway|rail|bus|coach|subway|metro)\s+"
    r"(?:station|stations|terminal|terminals|depot)\b|\bairports?\b",
    re.I,
)

# "fly", "flying", "flight(s)", "by air/plane" -- an explicit airplane requirement. Each
# alternative carries its own intent context (a planning/travel verb, a preposition of travel, or
# an explicit round-trip phrase) so that a bare noun mention cannot fire it.
_INTERCITY_AIRPLANE_RE = re.compile(
    r"\b(?:"
    r"(?:plan|planning|planned|prefer|prefers|preferred|decide|decided|choose|chose|chosen|want|"
    r"wants|wish|wishes|hope|hopes|intend|intends|will|going|would\s+like)\b"
    r"(?:\s+\w+){0,4}?\s+(?:to\s+)?fly(?:ing)?\b"
    r"|fly(?:ing)?\s+(?:round[-\s]?trip|both\s+ways|there|over|out|in|back|to\b|from\b)"
    r"|\bby\s+(?:air|plane|airplane|aeroplane|flight)\b"
    r"|(?:round[-\s]?trip|both\s+ways|one[-\s]?way)\s+(?:by\s+)?(?:flight|plane|airplane|air)\b"
    r"|\b(?:take|takes|taking|catch|catching|board|boarding|book|booking)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:round[-\s]?trip\s+)?(?:direct\s+)?(?:flight|plane|airplane)\b"
    r"|\bwe\s+(?:are|will\s+be|'ll\s+be)\s+flying\b"
    r")",
    re.I,
)

# "high-speed train (G)", "bullet train", "by rail", "take a round-trip train". Same shape: every
# alternative requires an intent context or an unambiguous mode noun phrase.
_INTERCITY_TRAIN_RE = re.compile(
    r"\b(?:"
    r"high[-\s]?speed\s+(?:train|rail|railway)"
    r"|bullet\s+train"
    r"|\bby\s+(?:high[-\s]?speed\s+)?(?:train|rail|railway)\b"
    r"|(?:round[-\s]?trip|both\s+ways|one[-\s]?way)\s+(?:by\s+)?(?:high[-\s]?speed\s+)?"
    r"(?:train|rail|railway)\b"
    r"|\b(?:take|takes|taking|catch|catching|board|boarding|book|booking)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:round[-\s]?trip\s+)?(?:high[-\s]?speed\s+)?(?:train|rail|railway)\b"
    r"|(?:plan|planning|planned|prefer|prefers|preferred|decide|decided|choose|chose|chosen|want|"
    r"wants|wish|wishes|hope|hopes|intend|intends|will|going|would\s+like)\b"
    r"(?:\s+\w+){0,4}?\s+(?:to\s+)?(?:take|catch|board|ride)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?:round[-\s]?trip\s+)?(?:high[-\s]?speed\s+)?(?:train|rail|railway)\b"
    r")",
    re.I,
)


# Loose *mentions* of either mode, used only to veto a strict match. A request that names both
# modes without a direction to attach them to ("still deciding whether to fly or take the
# high-speed train") is ambiguous, and the cost of guessing is a pinned wrong leg.
_INTERCITY_AIR_MENTION_RE = re.compile(r"\b(?:fly|flying|flight|flights|plane|airplane|air)\b", re.I)
_INTERCITY_TRAIN_MENTION_RE = re.compile(r"\b(?:train|trains|rail|railway|high[-\s]?speed)\b", re.I)


def _parse_intercity_mode_free_prose(text):
    """Return ``"airplane"``/``"train"`` for a free-prose intercity mode statement, else ``None``.

    Deliberately conservative, because a *spurious* intercity mode is not free: it pins arrival and
    departure legs and can invalidate an otherwise-passing plan (the P24 lesson). So:

    - station/airport *place* mentions are removed before matching;
    - a mode word must come with a planning verb, a preposition of travel, or an explicit
      round-trip phrase (the strict patterns above decide the value);
    - a loose mention of the *other* mode vetoes the match, so a request naming both says nothing
      rather than picking one.
    """
    stripped = _INTERCITY_PLACE_NOUN_RE.sub(" ", text or "")
    air = bool(_INTERCITY_AIRPLANE_RE.search(stripped))
    train = bool(_INTERCITY_TRAIN_RE.search(stripped))
    if air == train:  # neither, or both stated strictly -> say nothing
        return None
    if air and _INTERCITY_TRAIN_MENTION_RE.search(stripped):
        return None
    if train and _INTERCITY_AIR_MENTION_RE.search(stripped):
        return None
    return "airplane" if air else "train"



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
    # the negation cue is directly adjacent to a single mode word). "wish to" and the "travel by"
    # verb were added 2026-08-06 (P15): "do not wish to use taxi ... transportation" and "do not
    # want to travel by walking within the city" are both released phrasing this trigger missed --
    # the trailing "for/within ... transportation/city" text needs no pattern of its own since
    # nothing is required to follow the captured mode list.
    m = re.search(
        r"(?:do\s+not|don't|not)\s+(?:want\s+to\s+|wish\s+to\s+)?(?:use|travel\s+by)\s+"
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
            # The same greedy "visit <city> for N days and ..." split routinely lands a
            # restaurant/cuisine clause somewhere in the chunk ("... and would like to try Hubei
            # cuisine", "... and would like to try some local Jiangsu and Zhejiang cuisine", "...
            # and would like to eat at Siji Minfu near Qianmen") -- a real requirement, but for
            # `required_restaurants`/`cuisine_preference`, not this family. Their own anchored
            # patterns catch cuisine-type phrasing ("try X cuisine") reliably; specific-restaurant
            # phrasing ("would like to eat/dine at <name>") is caught only sometimes -- a sampled
            # check found ~40% captured, ~60% dropped by both families on this exact phrasing. That
            # gap is a `required_restaurants` recall residual, not something to fix by recording it
            # here under the wrong family. Checked on the whole chunk, before splitting on " and ":
            # an eat/dine/try cue anywhere means the whole capture is a food clause, e.g. "try
            # Jiangsu and Zhejiang cuisine" splits into two cuisine names, not one cuisine name plus
            # an unrelated attraction.
            if re.search(
                r"\b(?:try|eat|dine\s+at|have\s+(?:coffee|tea|a\s+meal)\s+at)\b",
                chunk, re.I,
            ):
                continue
            # Split on " and " to get individual names. The remaining guards below run per split
            # part, not on the whole chunk (P24, 2026-08-07): "visit Chongqing for 2 days and
            # would like to go to the Great Hall of the People" is one greedy capture split into a
            # trip-framing part and a genuine trailing attraction reference -- filtering the chunk
            # as a whole would drop the real half along with the invented one.
            parts = re.split(r"\s+and\s+", chunk)
            for p in parts:
                p = p.strip().rstrip(".")
                if not p or len(p) <= 1:
                    continue
                # "I want to visit <target city> for <N> days ... with a budget of ... RMB" is the
                # trip-framing sentence, not an attraction request -- with no comma before the
                # trailing budget/day-count clause, the pattern's own delimiter never fires and the
                # whole tail is swallowed as one "attraction name". Measured as the dominant
                # required_attractions precision leak on every HF free-prose set (every sampled
                # spurious instance had no matching oracle attraction_name_set clause at all; see
                # docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints).
                # Trip metadata never appears inside a real attraction name in this dataset, so its
                # presence anywhere in a part is disqualifying on its own.
                if re.search(
                    r"\bbudget\b|\bRMB\b|¥|\byuan\b|\balone\b|\bby\s+myself\b"
                    r"|\bfor\s+(?:\w+\s+){0,2}days?\b",
                    p, re.I,
                ):
                    continue
                # A real attraction name is a short proper-noun phrase. Free prose also uses
                # "visit" for plain sentiment with no name in it at all ("some cool places",
                # "places with beautiful scenery", "the university town there") -- every genuine
                # capture in the released registers carries at least one capitalized word, so
                # require one to filter the sentiment parts out (same measurement as above).
                if not re.search(r"[A-Z]", p):
                    continue
                names.append(p)

    # "Visit the following attractions: X and Y." (familiar-100). Anchored at ':' so it stays on
    # the attraction-name line and never fires on "attraction types:" (-> required_attraction_types).
    for n in _the_following_items(text, r"attractions?") or []:
        if n and n not in names:
            names.append(n)

    return names if names else None


# --- required_attraction_types: free-prose fallback -------------------------
#
# P19 (docs/tpc_phase2_roadmap.md#p19--find-the-unidentified-half-of-the-gap) ranked
# `required_attraction_types` as the single largest family-recall residual (160 released
# instances, 63.75% missed) -- almost entirely because every pattern above requires a "visit"/
# "want to visit" verb immediately adjacent to a type phrase, while free prose usually states the
# same requirement as a bare interest verb ("are interested in cultural attractions", "would like
# to take walks in parks", "We like Hunan cuisine"-shaped sentences with no "visit X" clause at
# all). This is a **fallback only**: it runs exclusively when every pattern above found nothing,
# so it can only turn a `missing` family into `matched`/`wrong_value` -- it never overrides a value
# an anchored pattern already found, and it never runs on familiar-100 (which always populates this
# family through the "Include the following attraction types: X" template above), so the
# familiar-100 floor cannot move by construction (2026-08-07, P20).
#
# Every value below is the canonical English string `chinatravel/symbol_verification/concept_func.py`
# actually returns (`normalize_concept_value` in `concept_labels.py`, cross-checked against
# `chinatravel/agent/nesy_agent/ast_checker_en.py`'s 13-value vocabulary) -- not the varying
# casing free text itself uses, since `parsed_verifier._match_text` compares case-insensitively.
# Ordered most-specific-first so e.g. "cultural and historical sites" is not swallowed by the
# bare "historical site" entry below it, and "amusement park" by the bare "park" entry.
# "university campus(es)" is deliberately anchored -- a bare "universit(y|ies)" alternative was
# tried and measured spurious on hf_human ("We are both university students", "tour universities
# like Shanghai Jiao Tong University, Fudan University, and Tongji University" -- the latter names
# specific universities and the oracle records only `required_attractions`, no type clause) -- so
# the bare form is dropped even though it costs one recoverable hf_easy instance ("visit some
# universities") (2026-08-07, P20 screen).
_ATTRACTION_TYPE_FREE_PROSE_VALUES = [
    (r"cultural\s+and\s+historical\s+(?:attractions?|sites?)", "Cultural Landscape"),
    (r"(?:historical\s+revolutionary|revolutionary)\s+sites?", "red tourism sites"),
    (r"amusement\s+parks?|theme\s+parks?", "amusement park/sports entertainment"),
    (r"sports\s+(?:and\s+)?entertainment\s+venues?", "amusement park/sports entertainment"),
    (r"garden\s+attractions?|gardens?\b", "Garden"),
    (r"natural\s+(?:landscapes?|scenery|attractions?)", "natural scenery"),
    (r"university\s+campus(?:es)?", "university campus"),
    (r"museums?\s+or\s+memorials?|memorial\s+halls?|museums?\b", "Museum/Memorial Hall"),
    (r"commercial\s+districts?", "commercial district"),
    (r"cultural\s+attractions?", "Cultural Tourism Area"),
    (r"historical\s+sites?", "historical site"),
    (r"parks?\b", "park"),
]

# A deliberately bare trigger-verb set (not "want/wish/hope to X", which the free-prose evidence
# routinely drops -- "would like to [stay in a room ... and] visit garden attractions" has no
# adjacent "to visit"). Precision is carried by `_negated_before` and `_looks_like_generic_mention`
# below, not by a narrow trigger.
#
# The preference verbs (`like`/`love`/`prefer`/`keen on`/`focus on`/`experience`) were added
# 2026-08-09 (P27). They were the only *measured* survivor of that entry's investigation: the phrase
# table itself is deliberately not extended, because the oracle labels the remaining free-prose
# phrasings inconsistently, but a bare statement of interest ("I like natural scenery") re-uses the
# existing table and converts. Blast radius, checked by diffing the full parsed solver dicts rather
# than inferred from aggregate probe columns: **4** of 854 queries across the five measured sets
# change, all on `hf_human`; familiar-100, `local_released_150`, `hf_medium` and `hf_easy` are
# byte-identical. End-to-end on translated `hf_human` (R35): FPR `51.95 -> 53.25`, overall
# `67.80 -> 68.50`, 2 clauses fail->pass against 1 pass->fail.
_ATTRACTION_TYPE_FREE_PROSE_TRIGGER = re.compile(
    r"\b(?:visit(?:ing)?|see|explor(?:e|ing)|tour(?:ing)?|interested\s+in|enjoy(?:ing)?|"
    r"lik(?:e|es)|love|prefer(?:s)?|keen\s+on|focus(?:ing)?\s+on|experienc(?:e|ing)|"
    r"go\s+to|go\s+shopping\s+in|take\s+walks?\s+in|spend\s+(?:some\s+)?(?:leisure\s+)?time\s+in)\b",
    re.I,
)

_FREE_PROSE_WINDOW = 80


def _looks_like_generic_mention(text, pos):
    """False when the nearest real word before ``pos`` looks like part of a capitalized
    proper-noun run (a POI name, e.g. "Three Gorges Museum", "Administrator's Garden") rather
    than a bare category word ("some museums", "local university campuses"). Cheap and
    conservative, not a full NER pass -- but skips past bare punctuation/dash/paren separators
    to the nearest actual word rather than checking only the literal preceding token, since a POI
    name routinely appends a type word after " - " or "(...)" (familiar-100: "Sichuan University
    (Wangjiang Campus) - Museum", whose immediately-preceding token is just "-")."""
    words = re.findall(r"[A-Za-z][\w'&.]*", text[max(0, pos - 60):pos])
    if not words:
        return True
    prev = words[-1]
    if prev[0].isupper() and prev.lower() not in {"i"}:
        return False
    return True


_EXAMPLE_MARKER_BEFORE = re.compile(r"(?:such\s+as|e\.g\.,?|for\s+example)\s*$", re.I)


def _preceded_by_example_marker(text, pos, window=15):
    """True when the text immediately before ``pos`` introduces an example ("such as X", "e.g.
    X"), not a stated requirement -- "try new things, such as Southeast Asian cuisine" is not a
    cuisine_preference clause; "Southeast Asian cuisine" is offered as one example of "new
    things", not itself the value asked for (P20's own worked case)."""
    return bool(_EXAMPLE_MARKER_BEFORE.search(text[max(0, pos - window):pos]))


def _free_prose_type_mentions(text, trigger_re, value_table):
    """Shared scan for both `required_attraction_types` and `cuisine_preference`'s free-prose
    fallback: for each trigger occurrence, search a bounded window after it against every entry of
    `value_table` (most-specific-first; a later entry cannot re-match a span an earlier, more
    specific entry already claimed), skipping negated, proper-noun-looking and example-introduced
    matches. Returns canonical values in first-found order, deduplicated across the whole text.

    Two or more *distinct* values found within the *same trigger's window* with a bare " or "
    between their span is an OR-alternative this flat AND-list field cannot express (P20: "never
    flatten 'A or B' into two simultaneous requirements") -- that window's contribution is dropped
    entirely rather than guessed, since a dropped extraction stays `missing` (no regression) while
    a wrong AND-flattening risks making a satisfiable query infeasible (P15's precision trap). The
    OR check is scoped per-window, not across the whole text, so two *separate* sentences each
    stating one value (no "or" involved) still both contribute."""
    found = []
    for tm in trigger_re.finditer(text):
        if _negated_before(text, tm.start()):
            continue
        window_start = tm.end()
        window = text[window_start:window_start + _FREE_PROSE_WINDOW]
        window_found = []  # [(canonical, abs_start, abs_end), ...] for this trigger's window only
        consumed = []  # spans already claimed by a more specific (earlier-in-table) entry
        for phrase_re, canonical in value_table:
            for vm in re.finditer(phrase_re, window, re.I):
                abs_start = window_start + vm.start()
                abs_end = window_start + vm.end()
                if any(abs_start < ce and cs < abs_end for cs, ce in consumed):
                    continue  # overlaps a more specific match already accepted in this window
                # The window can run past a *later* negated clause the trigger itself isn't part
                # of ("visit X and do not want to visit any Museum...": the first, non-negated
                # "visit" trigger's 80-char window still reaches the second clause's "Museum").
                # Re-checking negation at the value's own position (not just the trigger's) is
                # what actually excludes it.
                if _negated_before(text, abs_start):
                    continue
                if not _looks_like_generic_mention(text, abs_start):
                    continue
                if _preceded_by_example_marker(text, abs_start):
                    continue
                consumed.append((abs_start, abs_end))
                if canonical not in [c for c, _, _ in window_found]:
                    window_found.append((canonical, abs_start, abs_end))
                break
        if len(window_found) > 1:
            outer_start = min(s for _, s, _ in window_found)
            outer_end = max(e for _, _, e in window_found)
            if re.search(r"\bor\b", text[outer_start:outer_end], re.I):
                continue
        for canonical, _, _ in window_found:
            if canonical not in found:
                found.append(canonical)
    return found


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
        # Try "visit X and Y" (positive form, not preceded by "not"). Strip line-scoped
        # "Visit X between A and B" sentences first: those are activity_time_windows
        # constraints on a named POI (parse_activity_time_windows owns them via
        # _CONTAINED_BETWEEN_WINDOW_RE), not a type preference. Left in, a POI name that
        # happens to contain a type word -- "Golden Eagle Art Museum", "Baihua Tan Park",
        # "Cloudrise Art Museum" -- leaks through the known-types substring scan below as a
        # spurious required_attraction_type.
        fallback_text = _CONTAINED_BETWEEN_WINDOW_RE.sub("", text)
        m = re.search(r"[Vv]isit\s+(.+?)(?:\.|;|,\s*(?:and\s+we|we|the)|$)", fallback_text, re.I)
        # Skip if preceded by "not" within 20 chars
        if m and re.search(r"(?:not|don't|no)\s+(?:\w+\s+){0,3}visit", fallback_text[:m.start() + 10], re.I):
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
    if not types:
        # Free-prose fallback (P20, see the block above `parse_required_attraction_types`): only
        # when neither the generic "visit X" scan nor the verbatim template above found anything.
        types = _free_prose_type_mentions(
            text, _ATTRACTION_TYPE_FREE_PROSE_TRIGGER, _ATTRACTION_TYPE_FREE_PROSE_VALUES
        )
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


# --- Room type -------------------------------------------------------------
#
# Semantics, read off the verifier: room_type is the *bed count* per room
# (chinatravel/symbol_verification/concept_func.py room_type() -> the hotel's ``numbed``). So the
# oracle's code 1 is a one-bed room and code 2 is a two-bed room. In hotel English a "big bed" /
# "large bed" / "king bed" / "double bed" room is *one* bed (numbed 1) and a "twin" room is *two*
# (numbed 2). Verified against every released English query carrying a room_type clause
# (2026-08-06 audit): big bed -> 1, large bed -> 1, double bed -> 1, king bed -> 1, single(-bed) -> 1,
# twin / twin-bed -> 2, with no counterexample. The pre-fix code returned "double" for "double bed",
# which parsed_verifier._room_type_to_numbed maps to 2 -- the opposite of the oracle.
#
# familiar-100 only ever says "single-bed rooms" / "twin-bed rooms" (audited: 4x single-bed -> code 1,
# 5x twin-bed -> code 2, no other wording), both of which these patterns read exactly as before.
_ROOM_TYPE_BED_WORD_TWIN = r"twin"
_ROOM_TYPE_BED_WORD_SINGLE = (
    r"(?:single|big|large|king(?:[\s-]*size[d]?)?|queen(?:[\s-]*size[d]?)?|double)"
)
_ROOM_TYPE_PATTERNS = (
    # two beds / twin, in any of the observed shapes
    ("twin", re.compile(r"\btwin[\s-]*(?:bed(?:ded|s)?[\s-]*)?rooms?\b", re.I)),
    ("twin", re.compile(r"\btwin[\s-]*beds?\b", re.I)),
    ("twin", re.compile(r"\b(?:two|2)\s+(?:separate\s+|individual\s+|single\s+)?beds?\b", re.I)),
    ("twin", re.compile(r"\brooms?\s+with\s+(?:two|2)\s+(?:separate\s+|single\s+)?beds?\b", re.I)),
    ("twin", re.compile(r"\btwin\s+rooms?\b", re.I)),
    # "a double room is sufficient" -- a *double room* (双人间) is a two-person room = 2 beds, the
    # opposite of a "double BED room" (大床房) = 1 bed, which the single patterns below own. The one
    # released instance confirms it: HF medium e20241028161347428726, 2 travelers, oracle
    # room_type == 2. Deliberately NOT extended to "family room": its two released instances
    # disagree (easy m20241028164807696509 -> 2, medium e20241028161318465643 -> 1), so it carries
    # no reliable bed count.
    ("twin", re.compile(r"\bdouble\s+rooms?\b", re.I)),
    # one bed, whatever its marketing name
    ("single", re.compile(r"\b" + _ROOM_TYPE_BED_WORD_SINGLE
                          + r"[\s-]*bed(?:ded)?[\s-]*rooms?\b", re.I)),
    ("single", re.compile(r"\b" + _ROOM_TYPE_BED_WORD_SINGLE + r"[\s-]*beds?\b", re.I)),
    ("single", re.compile(r"\brooms?\s+with\s+(?:a\s+|one\s+|1\s+)?"
                          + _ROOM_TYPE_BED_WORD_SINGLE + r"[\s-]*bed\b", re.I)),
    ("single", re.compile(r"\bsingle\s+rooms?\b", re.I)),
)


def parse_room_type(text):
    """Extract preferred room type ("single" = one bed per room, "twin" = two).

    Un-anchored: the pre-fix version required a trigger verb ("stay in a ... room", "prefer a ...",
    "use ...-bed rooms"), which the released prose sets do not use ("... and stay in two twin
    rooms.", "book a single-bed room", "a room with a big bed"). The earliest match in the text
    wins, so "two single beds" reads as twin rather than single.
    """
    best = None
    for label, pattern in _ROOM_TYPE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        key = (match.start(), -(match.end() - match.start()))
        if best is None or key < best[0]:
            best = (key, label)
    return best[1] if best else None


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
            # P24 (2026-08-07): "stay in two twin rooms" / "stay in a room with a double bed" /
            # "stay in a big bed room" is a room-type/room-count requirement, not a hotel name --
            # the guard above only caught chunks *starting* with "a single/double/twin", missing
            # every quantified ("two twin rooms", "two rooms") or "a room ..." phrasing, which was
            # the dominant required_hotels precision leak on every HF free-prose set (every sampled
            # spurious instance had no matching oracle accommodation_name_set clause; see
            # docs/tpc_phase2_roadmap.md#p24--stop-inventing-satisfiable-but-unrequested-constraints).
            # A real hotel name never opens with a bare quantifier/article immediately in front of
            # "room(s)".
            if re.match(r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
                        r"(?:[\w-]+[\s-]+)*rooms?\b", chunk, re.I):
                continue
            if re.match(r"(?:a|an)\s+room\b", chunk, re.I):
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
    r"(?P<verb>visit|(?:dine|stay)[ \t]+at)[ \t]+"
    r"(?P<location>.+?)[ \t]+between[ \t]+"
    r"(?P<start>\d{1,2}:\d{2})[ \t]+and[ \t]+(?P<end>\d{1,2}:\d{2})"
    r"[ \t]*[.;]?[ \t]*$",
    re.I | re.M,
)

# Which itinerary activity types a "<verb> X between A and B" line can be satisfied by. The oracle
# clause for the same sentence gates on exactly this set (``activity_type(activity) in [...]``), so
# recording it keeps two windows on the *same* POI name distinguishable -- a hotel routinely carries
# both a "Dine at <hotel> between 07:45 and 08:40" and a "Stay at <hotel> between 20:10 and 24:00"
# window, and collapsing them onto the name alone makes the pair unsatisfiable.
_WINDOW_VERB_ACTIVITY_TYPES = {
    "visit": ("attraction",),
    "dine at": ("breakfast", "lunch", "dinner"),
    "stay at": ("accommodation",),
}


def _window_activity_types(verb):
    """Activity types a contained-between window applies to, or ``None`` when unknown.

    ``None`` means "any activity at this position", which is how every window without a type-bearing
    verb (the free-form arrive/leave/visit-between patterns) has always been interpreted.
    """
    key = re.sub(r"[ \t]+", " ", (verb or "").strip().lower())
    return list(_WINDOW_VERB_ACTIVITY_TYPES.get(key, ())) or None


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


def _split_restaurant_names(chunk, match_text):
    """Split a captured restaurant-name chunk into names, unless the trigger used the singular
    "restaurant" (not "restaurants") -- in which case grammar says exactly one name was named, so
    the chunk is returned whole even if the name itself contains a literal " and " (e.g. "Rib and
    Lotus Root Soup in a Clay Pot"), which the naive and/comma splitter would otherwise cut in two
    (2026-08-06, P15: `local_released_150` uid `20250322120300879962`)."""
    if not re.search(r"restaurants\b", match_text, re.I):
        return [chunk]
    # Consume an optional "and" right after a comma so an Oxford-comma list ("A, B, and C") does
    # not leave a leading "and C" fragment (same fix as `_list_after_marker`).
    return re.split(r"\s+and\s+|,\s*(?:and\s+)?", chunk)


def _looks_like_cuisine_type_chunk(chunk):
    """True if a chunk captured after "restaurant(s):" is cuisine-TYPE phrasing, not a name --
    either word order ("of the type X" / "of the following types: X", handled by
    parse_cuisine_preference/parse_excluded_cuisine_types instead) or the mirrored "of the X type"
    (2026-08-06, P15: local_released_150 uid 20250322141653938197's "restaurants of the cafe
    type", which the first form alone does not catch and which would otherwise read as the
    literal restaurant name "of the cafe type")."""
    if re.match(r"of\s+(?:the\s+)?(?:following\s+)?types?\b", chunk, re.I):
        return True
    if re.match(r"(?:any\s+)?of\s+(?:the\s+)?\w[\w\s-]{0,40}?\s+types?\s*$", chunk, re.I):
        return True
    return False


def parse_required_restaurants(text):
    """Extract specific restaurant names that must be visited.

    Guards against negated phrasing ("do not want to try ...") which must map to *excluded*
    restaurants / cuisine types, not required ones.
    """
    names = []
    # Negation immediately preceding the "want/wish/hope/would like to try" trigger.
    neg_prefix = re.compile(r"(?:do\s+not|don't|didn't|does\s+not|do\s+n't|not|avoid|never|no)\s+$", re.I)

    patterns = [
        # "would like" added 2026-08-06 (P15): "Would like to try these restaurants: X" is a
        # released paraphrase of "want to try" that carries the identical restaurant-name payload.
        # The "restaurants?[:\s]+" anchor is deliberately NOT optional here: an earlier draft made
        # it optional (matching the pre-existing "want/wish/hope" pattern), and on free prose that
        # swallowed the *rest of the sentence* after "want/would like to try" on any clause that
        # never says the word "restaurant" at all -- "would like to try some local Jiangsu and
        # Zhejiang cuisine", "would like to try high-end dining options", "want to try hot pot,
        # explore the local history and culture, and prefer a relaxed itinerary" were all captured
        # whole (measured: hf_easy/medium/human `required_restaurants` spurious count rose with
        # zero matching recall gain until this anchor was made mandatory). "try" is ambiguous
        # between a cuisine/dish and a named venue, so it needs the anchor; "dine at" is not (see
        # next pattern).
        r"(?:want|wish|hope|would\s+like)\s+to\s+try\s+(?:one\s+of\s+)?(?:the\s+following\s+|these\s+)?restaurants?[:\s]+(.+?)(?:" + _LIST_TERM + r")",
        # "want to dine at X" / "would like to dine at X" -- unlike "try", "dine at" always names a
        # specific venue, so the "restaurant(s)" word is genuinely optional here (free-prose
        # evidence: hf_easy/medium consistently write "dine at <Name>" with no "restaurant" word at
        # all, e.g. "would like to dine at Yan Jintang near Longfu Temple"). Restricting this verb
        # to a mandatory anchor would drop those real names (regression check, 2026-08-06).
        r"(?:want|wish|hope|would\s+like)\s+to\s+dine\s+at\s+(?:the\s+following\s+|these\s+)?(?:restaurants?[:\s]+)?(.+?)(?:" + _LIST_TERM + r")",
        # Bare imperative ("Try one of these restaurants: X"), common in OR-arm bullet text with
        # no surrounding "we want to" framing (plan3 G3/N3.1) -- anchored to the start of the text.
        r"^try\s+(?:one\s+of\s+(?:the\s+following|these)\s+)?restaurants?[:\s]+(.+?)(?:" + _LIST_TERM + r")",
    ]

    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            # Skip when the trigger is negated ("do not want to try ...").
            if neg_prefix.search(text[: m.start()]):
                continue
            chunk = m.group(1).strip().rstrip(".")
            # Skip cuisine-TYPE phrasing ("of the type X" / "of the following type(s): X" / "of
            # the X type"); those are not restaurant names.
            if _looks_like_cuisine_type_chunk(chunk):
                continue
            parts = _split_restaurant_names(chunk, m.group(0))
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

    patterns = [
        r"(?:do\s+not|don't|not)\s+(?:want|wish|hope)\s+to\s+(?:try|dine\s+at|visit)\s+"
        r"(?:the\s+following\s+)?(?:the\s+)?restaurants?[:\s]+(.+?)(?:" + _LIST_TERM + r")",
        # "Do not try the following restaurant: X" -- the same clause with the "want/wish/hope"
        # step dropped (2026-08-06, P15: released, not in familiar-100's template).
        r"(?:do\s+not|don't|not)\s+try\s+(?:the\s+following\s+)?(?:the\s+)?restaurants?[:\s]+(.+?)(?:" + _LIST_TERM + r")",
        # "Avoid the following restaurant: X" -- a third verb the released set uses for the same
        # exclusion (2026-08-06, P15), common as an OR-arm bullet with no "do not" framing at all.
        r"avoid\s+(?:the\s+following\s+)?(?:the\s+)?restaurants?[:\s]+(.+?)(?:" + _LIST_TERM + r")",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            chunk = m.group(1).strip().rstrip(".")
            # Not a restaurant name list — it's a cuisine type ("of the type X" / "of the following
            # type(s): X" / "of the X type"); handled elsewhere.
            if _looks_like_cuisine_type_chunk(chunk):
                continue
            parts = _split_restaurant_names(chunk, m.group(0))
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


# The four "restaurant type(s)"/"type(s) of restaurant(s)" list patterns below are OR-arms of a
# numbered requirements block ("1. ... 2. ...") in local/HF free prose, and the released generator
# does not always end the first arm with a period before the next arm's digit -- "Cantonese cuisine
# 2. The total budget..." has no sentence boundary between the value and "2.". A bare `.+?` scanning
# for the next period/semicolon over-captures into the next arm's leading number. This lookahead
# terminates the capture at that boundary without needing a period there; deliberately local to
# these cuisine-list patterns rather than added to the shared `_LIST_TERM` (2026-08-07, P20).
_NUMBERED_ITEM_BOUNDARY = r"(?=\s*\d+\.\s)"
_CUISINE_LIST_TERM = r"(?:\.|;|" + _NUMBERED_ITEM_BOUNDARY + r"|$)"


# --- cuisine_preference: free-prose fallback ---------------------------------
#
# P19 ranked `cuisine_preference` the second-largest family-recall residual (127 released
# instances, 78.74% missed) -- every pattern above requires a "restaurant(s)"/"restaurant type(s)"
# noun phrase, while free prose almost always states the same requirement as a bare verb + value
# ("want to eat hotpot", "try Sichuan cuisine", "We like Hunan cuisine") with no "restaurant" word
# anywhere in the sentence. Fallback-only, same contract as the attraction-type fallback above:
# only runs when every pattern above found nothing, so it can only turn a `missing` family into
# `matched`/`wrong_value`, and it never runs on familiar-100 (always populated through the
# "Include the following restaurant types: X" template), so the familiar-100 floor cannot move by
# construction (2026-08-07, P20).
#
# Values are `chinatravel/agent/nesy_agent/ast_checker_en.py`'s 41-value cuisine vocabulary
# (cross-checked against `concept_labels.ENGLISH_CONCEPT_VALUE_ALIASES["restaurant"]` for the few
# that need normalizing, e.g. "cafe" -> "coffee shop"). Several plausible free-prose values are
# deliberately excluded, not merely unconsidered: "local specialties"/"local cuisine"/"local
# specialty dishes" name no cuisine at all in the sentence (the oracle value is derived from the
# destination city, which this file has no access to -- CLAUDE.md's no-oracle-leakage invariant
# would be violated by guessing it); "such as X" introduces an example, not a stated requirement;
# a single observed "Huaiyang cuisine" -> Huizhou cuisine instance looks like a released-data
# translation quirk rather than a general synonym (Huaiyang and Huizhou are different real
# cuisines) and is not trustworthy from one instance; "sweet foods and bread" and "go
# drinking"/"drinking" are too ambiguous a signal (the former one instance, the latter easily
# confused with unrelated "drinks"/"drinking water" mentions) to anchor safely.
_CUISINE_FREE_PROSE_VALUES = [
    (r"hot\s*pot", "Hot pot"),
    (r"sichuan\s+cuisine", "Sichuan cuisine"),
    (r"cantonese\s+cuisine", "Cantonese cuisine"),
    (r"hubei\s+cuisine", "Hubei cuisine"),
    (r"xinjiang\s+cuisine", "Xinjiang cuisine"),
    (r"hunan\s+cuisine", "Hunan cuisine"),
    (r"beijing\s+cuisine", "Beijing cuisine"),
    (r"korean\s+cuisine", "Korean cuisine"),
    (r"japanese\s+cuisine", "Japanese cuisine"),
    (r"jiangsu(?:\s+and\s+|-)zhejiang\s+cuisine", "Jiangsu-Zhejiang cuisine"),
    (r"southeast\s+asian\s+cuisine", "Southeast Asian cuisine"),
    (r"northeastern\s+chinese\s+cuisine", "Northeastern Chinese cuisine"),
    (r"western\s+(?:cuisine|food)", "Western cuisine"),
    (r"halal\s+(?:cuisine|food)", "Halal cuisine"),
    # "simple meals" is checked against every set's oracle before shipping: it fires zero
    # spurious cuisine_preference extractions on all five non-familiar sets (2026-08-07 P20
    # screen), unlike the bare "universit(y|ies)" alternative this file dropped for the same
    # reason. Kept, unlike that one, but flagged here in case held-out data disagrees.
    (r"fast\s+food(?:\s+and\s+(?:simple|casual)\s+meals)?|simple\s+meals", "Fast food and casual dining"),
    (r"seafood", "Seafood"),
    (r"teahouses?", "Teahouse"),
    (r"fusion\s+cuisines?", "fusion cuisine"),
    (r"buffet", "buffet"),
    (r"snacks?", "Snacks"),
]

# Same rationale as `_ATTRACTION_TYPE_FREE_PROSE_TRIGGER`: a bare verb set, since the free-prose
# evidence routinely separates "want/would like to" from the actual food verb ("would like to
# stay in a room with a large bed, travel by train, and enjoy Jiangsu and Zhejiang cuisine"), plus
# a bare "We like X"/"We enjoy X" shape that has no "eat/try" verb at all.
_CUISINE_FREE_PROSE_TRIGGER = re.compile(
    r"\b(?:eat(?:ing)?|try(?:ing)?|taste|have|like|enjoy(?:ing)?)\b", re.I
)


def parse_cuisine_preference(text):
    """Extract cuisine/restaurant type preference (positive only)."""
    cuisines = []
    # A closed set of list lead-in fillers, not a stoplist over cuisine values: the "want to try X
    # restaurant" pattern below is a non-greedy scan for the *first* " restaurant" it can reach, so
    # on "want to try one of the following restaurant types: X" it stops at the lead-in words
    # instead of the real value (2026-08-07, P20 -- the roadmap's own cited example,
    # `["one of the following", "Japanese cuisine"]`). The list-pattern below this one still
    # extracts the real value from the same sentence; this only drops the spurious extra entry.
    _STOP = {"the", "following", "these", "the following", "of the type", "a",
             "one of the following", "one of these", "any of the following", "any of these"}
    neg_prefix = re.compile(r"(?:do\s+not|don't|didn't|does\s+not|not|avoid|never|no)\s+$", re.I)
    # "want to try a Hot pot restaurant"
    m = re.search(r"(?:want|wish|hope)\s+to\s+try\s+(?:a\s+)?(.+?)\s+restaurant", text, re.I)
    if m and not neg_prefix.search(text[: m.start()]):
        cuisine = m.group(1).strip()
        if cuisine.lower() not in _STOP:
            cuisines.append(cuisine)

    # "try one of these restaurant types: Beijing cuisine, Barbecue, or Japanese cuisine"
    m = re.search(r"(?:try|visit)\s+(?:one\s+of\s+)?(?:these|the\s+following)\s+restaurant\s+types?[:\s]+(.+?)" + _CUISINE_LIST_TERM, text, re.I)
    if m and not _negated_before(text, m.start()):
        chunk = m.group(1).strip().rstrip(".")
        parts = re.split(r",\s*(?:or\s+)?|\s+or\s+", chunk)
        for p in parts:
            p = p.strip()
            if p and p.lower() not in {"the", "following", "these"}:
                cuisines.append(p)

    # "try the following types of restaurants: Hot pot and Western cuisine". Negated phrasing
    # ("do not want to try the following types of restaurants: X") maps to excluded_cuisine_types,
    # not here -- same guard as the "restaurants of type" pattern below. "one of " is optional
    # before "the following" (mirrors the sibling pattern above) so "try one of the following types
    # of restaurants: Hot pot" -- the reversed word order of the same lead-in -- also matches
    # (2026-08-07, P20).
    m = re.search(r"(?:try|visit)\s+(?:one\s+of\s+)?(?:the\s+following\s+)?types?\s+of\s+restaurants?[:\s]+(.+?)" + _CUISINE_LIST_TERM, text, re.I)
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
        r"restaurants?\s+of\s+(?:the\s+)?(?:following\s+)?types?[:\s]+(.+?)" + _CUISINE_LIST_TERM, text, re.I
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

    if not cuisines:
        # Free-prose fallback (P20, see the block above this function): only when every anchored
        # pattern above found nothing.
        cuisines = _free_prose_type_mentions(text, _CUISINE_FREE_PROSE_TRIGGER, _CUISINE_FREE_PROSE_VALUES)

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
        # "do not want to try any restaurants of the cafe type" -- the value sits BEFORE "type"
        # here, the mirror image of the pattern above (2026-08-06, P15: local_released_150 uid
        # 20250322141653938197). Bounded to a short run of words so it can't swallow a whole
        # trailing clause when "type" never appears in the sentence at all.
        _NEG_TRY + r"(?:any\s+)?restaurants?\s+of\s+(?:the\s+)?(\w[\w\s-]{0,40}?)\s+type\b",
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
        # Only the explicit "the following hotel feature types:" list template respects a
        # negated lead-in ("do not want to include ..." is an exclusion, never a requirement).
        # The "hotel with/that offers/of type X" amenity-mention patterns below have no
        # negative-amenity family in the oracle at all -- "we do not want to stay in hotels
        # with a Sunbathing area" is still encoded as required_hotel_all_types, so those
        # patterns must fire regardless of a preceding "do not want".
        patterns_check_negation = (
            (r"(?:include\s+)?the\s+following\s+hotel\s+feature\s+types?[:\s]+(.+?)(?:\.|;|$)", True),
            (r"hotels?\s+of\s+(?:the\s+)?type[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)", False),
            (r"stay\s+(?:at|in)\s+(?:a\s+)?hotels?\s+of\s+(?:the\s+)?type[:\s]+(.+?)(?:\.|;|,\s*(?:and|we)|$)", False),
            (r"hotels?\s+(?:that\s+)?offer(?:s|ing)?\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)", False),
            (r"hotels?\s+with\s+(.+?)(?:\.|;|,\s*(?:and|we)|$)", False),
        )
        for pat, check_negation in patterns_check_negation:
            m = re.search(pat, text, re.I)
            if not m:
                continue
            if check_negation and _negated_before(text, m.start()):
                continue
            all_types = _split_types(m.group(1))
            break
    return any_types, all_types


def _hhmm_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


# Required visit ordering ("visit X first, then Y", "first go to X, then Y") -- roadmap P12.
# The oracle encodes this as an index comparison over allactivities(plan) (see _parse_single_logic
# below for the matching hard_logic_py shape); the NL always uses "first"/"then" for it in the
# released data, never "before"/"after" (those words are already claimed by the "leave/depart X
# before/after T" time-window family, so a generic "X before Y" pattern here would collide with
# that family instead of adding a new one).
_ORDER_PATTERNS = (
    re.compile(r"visit\s+(?P<first>.+?)\s+first,?\s*then\s+(?:to\s+)?(?P<rest>.+?)(?:\.|;|$)", re.I),
    re.compile(r"first\s+(?:go\s+to|visit)\s+(?P<first>.+?),\s*then\s+(?:to\s+)?(?P<rest>.+?)(?:\.|;|$)", re.I),
)


def parse_required_order(text):
    """Extract a required visit order as a list of >=2 POI names, earliest first, or None."""
    for pattern in _ORDER_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        first = m.group("first").strip().rstrip(".")
        rest = m.group("rest").strip().rstrip(".")
        # A chain longer than two stops repeats "then" ("X, then Y, then Z"); split the remainder
        # on further separators so those are captured too, though the released data only shows two.
        parts = re.split(r",?\s*(?:and\s+)?then\s+(?:to\s+)?", rest, flags=re.I)
        names = [first] + [p.strip() for p in parts if p.strip()]
        seen = set()
        ordered = []
        for name in names:
            name = re.sub(r"^to\s+", "", name, flags=re.I).strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                ordered.append(name)
        if len(ordered) >= 2:
            return ordered
    return None


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

    Every window also carries ``activity_types``: the itinerary activity types it can be satisfied
    by (``["attraction"]``, the three meal types, or ``["accommodation"]``), or ``None`` when the
    sentence does not name one. Consumers that ignore the key see exactly the previous behaviour.
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
            "activity_types": _window_activity_types(match.group("verb")),
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
                                    "end_after": None, "end_before": None,
                                    "activity_types": None})
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

    order = parse_required_order(text)
    if order:
        result["required_order"] = order

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
    # required_order names deliberately do NOT feed position_presence: that field is solver
    # guidance consumed as an *attraction* requirement pool (tpc_agent.py:5048,
    # `list(required_attractions) + list(constraints.get("position_presence", []) or [])`), and an
    # ordering pair is routinely a restaurant (real examples: "Chef's Wife in Charge (East Lake
    # Branch)", "The Boots Muddy Boots & MINI (Optics Valley Branch)") -- forcing a restaurant name
    # into attraction handling would make a solvable query infeasible. P12's scope is the checker;
    # solver-side guidance for required_order is future work, not a drive-by here.
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

    # --- Required visit ordering (roadmap P12) ---
    # Generated as a fixed index-comparison template: two named POIs, first found index compared
    # against second found index. The name capture runs to the last "':" on its line (greedy `.+`
    # backtracking) rather than the first, because the generated data itself contains at least one
    # POI name with an embedded, unescaped apostrophe inside the single-quoted literal.
    m = re.search(
        r"idx_activity0=0\s*\n\s*idx_activity1=0\s*\n\s*i=0\s*\n\s*for activity in allactivities\(plan\):\s*\n"
        r"\s*if activity_position\(activity\)=='(?P<first>.+)':\s*\n\s*idx_activity0=i\s*\n"
        r"\s*if activity_position\(activity\)=='(?P<second>.+)':\s*\n\s*idx_activity1=i\s*\n"
        r"\s*i\+=1\s*\n"
        r"if idx_activity0<idx_activity1:",
        logic,
    )
    if m:
        result["required_order"] = [m.group("first"), m.group("second")]

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
