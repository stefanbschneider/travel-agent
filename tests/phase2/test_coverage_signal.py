"""Focused tests for the P17(a) coverage signal (chinatravel/agent/phase2/coverage_signal.py)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for path in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if path not in sys.path:
        sys.path.insert(0, path)

from chinatravel.agent.phase2 import coverage_signal  # noqa: E402


# --- budget / currency ------------------------------------------------------------------------

def test_budget_fires_on_a_currency_amount_with_no_budget_family():
    fired = coverage_signal.uncovered_mentions(
        "Please keep the trip within 3000 RMB total.", variants=[{}])
    assert "budget" in fired


def test_budget_fires_on_bare_budget_word_near_a_digit_with_no_family():
    fired = coverage_signal.uncovered_mentions(
        "Our budget is 4000 for the whole trip.", variants=[{}])
    assert "budget" in fired


def test_budget_does_not_fire_when_the_budgets_family_is_present():
    fired = coverage_signal.uncovered_mentions(
        "Please keep the trip within 3000 RMB total.",
        variants=[{"budgets": {"total": 3000.0}}])
    assert "budget" not in fired


def test_budget_does_not_fire_when_covered_by_any_or_branch():
    """Existential OR: any variant carrying the family is enough."""
    fired = coverage_signal.uncovered_mentions(
        "Our budget is 4000.",
        variants=[{}, {"budgets": {"total": 4000.0}}])
    assert "budget" not in fired


def test_budget_does_not_fire_on_prose_with_no_amount_at_all():
    fired = coverage_signal.uncovered_mentions(
        "We want a relaxing trip with plenty of free time.", variants=[{}])
    assert "budget" not in fired


# --- room type ---------------------------------------------------------------------------------

def test_room_type_fires_on_a_room_noun_with_no_room_type_family():
    fired = coverage_signal.uncovered_mentions(
        "Please book two twin rooms for us.", variants=[{}])
    assert "room_type" in fired


def test_room_type_does_not_fire_when_room_type_family_is_present():
    fired = coverage_signal.uncovered_mentions(
        "Please book two twin rooms for us.",
        variants=[{"room_type": "twin"}])
    assert "room_type" not in fired


def test_room_type_does_not_fire_on_bare_room_without_a_qualifier():
    """Precision guard: bare "room" (an idiom, or "living room") must not fire -- see the P12
    rejection this item's docstring cites: an imprecise phrase heuristic manufactures false
    negatives on already-correctly-parsed queries."""
    fired = coverage_signal.uncovered_mentions(
        "There's room in the schedule for one more stop.", variants=[{}])
    assert "room_type" not in fired


def test_room_type_fires_on_suite():
    fired = coverage_signal.uncovered_mentions(
        "We'd like to stay in a suite if possible.", variants=[{}])
    assert "room_type" in fired


# --- cuisine: attempted and rejected, not shipped ---------------------------------------------
#
# A closed-vocabulary substring cuisine detector was built and measured (see coverage_signal's
# module docstring) before this file existed in its current form: 58/100 familiar-100 triggers,
# almost all false positives from a cuisine word appearing inside a restaurant *name* the query
# correctly named in an entirely different family (e.g. excluded_restaurants). Not implemented
# here; no "cuisine" category exists to test.


# --- top-level contract ---------------------------------------------------------------------------

def test_empty_text_never_fires():
    assert coverage_signal.uncovered_mentions("", variants=[{}]) == ()
    assert coverage_signal.uncovered_mentions(None, variants=[{}]) == ()


def test_none_or_empty_variants_treated_as_uncovered():
    fired = coverage_signal.uncovered_mentions("Our budget is 4000.", variants=None)
    assert "budget" in fired
    fired = coverage_signal.uncovered_mentions("Our budget is 4000.", variants=[])
    assert "budget" in fired


def test_malformed_variant_entries_do_not_raise():
    fired = coverage_signal.uncovered_mentions(
        "Our budget is 4000.", variants=[None, "not a dict", {}])
    assert "budget" in fired


def test_ordinary_familiar_100_style_query_never_fires():
    """The templated register already parses everything correctly, so a fully-covered query
    (every mentioned category has its family) must produce no triggers at all."""
    text = (
        "Please plan a 2-day trip to Beijing for 2 people. Keep the total budget within 3000 RMB. "
        "We would like to stay in a double room."
    )
    variants = [{
        "budgets": {"total": 3000.0},
        "room_type": "double",
    }]
    assert coverage_signal.uncovered_mentions(text, variants) == ()


def test_familiar_100_real_split_triggers_at_or_near_zero():
    """The measured precondition this item's own bar requires (P13's precedent), pinned as a
    regression test rather than only a one-off manual measurement: reads the real committed
    familiar-100 split and asserts neither shipped category fires more than a couple of times.
    Skips cleanly if the split/parser stack is unavailable in this environment."""
    try:
        import sys as _sys
        from pathlib import Path as _Path

        _scripts = str(_Path(__file__).resolve().parents[2] / "scripts")
        if _scripts not in _sys.path:
            _sys.path.insert(0, _scripts)
        from parser_vs_oracle import query_variants  # noqa: E402
        from chinatravel.data.load_datasets import load_query  # noqa: E402
        import argparse

        args = argparse.Namespace(
            splits="tpc_phase2_familiar_100", lang="en", oracle_translation=True)
        ids, data = load_query(args)
    except Exception as exc:  # pragma: no cover - environment-dependent
        import pytest
        pytest.skip(f"familiar-100 split/parser stack unavailable: {exc}")

    triggered = 0
    for uid in ids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        text = q.get("nature_language") or ""
        parsed_variants, _oracle_variants = query_variants(q, disjunction=True)
        if coverage_signal.uncovered_mentions(text, parsed_variants):
            triggered += 1
    # P13's precedent is exactly 0/100; a couple of points of slack absorbs a future dataset
    # tweak without this test flapping on noise unrelated to the signal's own precision.
    assert triggered <= 2, f"{triggered}/100 familiar-100 queries triggered the coverage signal"
