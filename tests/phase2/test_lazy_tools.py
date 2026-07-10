"""Regression tests for the lazy tool singletons (Phase 2 plan Step 2).

Accommodations/Restaurants/Attractions/... each read every city's CSV into a
pandas DataFrame at construction time. hard_constraint/commonsense_constraint/
preference (and the nesy_verifier + evaluation counterparts) used to build these
eagerly at import time, so merely importing one of these modules paid that cost
even if none of its functions were ever called. LazyTool defers construction to
first attribute access.
"""

from __future__ import annotations

from chinatravel.environment.tools._lazy import LazyTool
from chinatravel.symbol_verification import hard_constraint, commonsense_constraint


def test_hard_constraint_tools_not_built_at_import():
    hard_constraint._tools_for_lang.cache_clear()
    assert isinstance(hard_constraint.accommodation, LazyTool)
    assert hard_constraint._tools_for_lang.cache_info().currsize == 0


def test_hard_constraint_tools_build_once_on_first_use():
    hard_constraint._tools_for_lang.cache_clear()
    _ = hard_constraint.accommodation.data
    assert hard_constraint._tools_for_lang.cache_info().currsize == 1
    _ = hard_constraint.restaurants.data
    _ = hard_constraint.attractions.data
    # Same lang -> same cached tuple, no rebuild.
    assert hard_constraint._tools_for_lang.cache_info().currsize == 1


def test_commonsense_constraint_tools_not_built_at_import():
    commonsense_constraint._tools_for_lang.cache_clear()
    assert isinstance(commonsense_constraint.accommodation, LazyTool)
    assert commonsense_constraint._tools_for_lang.cache_info().currsize == 0
