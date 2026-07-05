"""Guaranteed-valid fallback plan for the Phase 2 harness.

The output schema requires only ``people_number``, ``start_city``, ``target_city`` and
``itinerary``; an empty ``itinerary`` is schema-valid. So the last-resort fallback is a minimal
schema-valid plan — strictly better than emitting a parse-failure zero. If a non-empty best-so-far
plan exists, prefer it.
"""

from __future__ import annotations


def _has_itinerary(plan) -> bool:
    if not isinstance(plan, dict):
        return False
    itinerary = plan.get("itinerary")
    return isinstance(itinerary, list) and len(itinerary) > 0


def minimal_plan(query: dict) -> dict:
    """A minimal schema-valid plan with an empty itinerary."""
    return {
        "people_number": query.get("people_number", 1),
        "start_city": query.get("start_city", ""),
        "target_city": query.get("target_city", ""),
        "itinerary": [],
    }


def fallback_plan(query: dict, best: dict | None = None) -> dict:
    """Return the best-so-far plan if it has a non-empty itinerary, else a minimal valid plan."""
    if _has_itinerary(best):
        return best
    return minimal_plan(query)
