"""Tests for the Phase 2 guaranteed-valid fallback plan (Task 5)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from chinatravel.agent.phase2 import fallback as F

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json").read_text(encoding="utf-8")
)


def test_fallback_plan_is_schema_valid(one_query):
    plan = F.fallback_plan(one_query)
    jsonschema.validate(plan, SCHEMA)
    assert plan["itinerary"] == []
    assert plan["start_city"] == one_query["start_city"]
    assert plan["target_city"] == one_query["target_city"]
    assert plan["people_number"] == one_query["people_number"]


def test_fallback_prefers_nonempty_best(one_query):
    best = {
        "people_number": one_query["people_number"],
        "start_city": one_query["start_city"],
        "target_city": one_query["target_city"],
        "itinerary": [{"day": 1, "activities": []}],
    }
    plan = F.fallback_plan(one_query, best=best)
    assert plan is best


def test_fallback_ignores_empty_best(one_query):
    best = {"itinerary": []}
    plan = F.fallback_plan(one_query, best=best)
    assert plan["itinerary"] == []
    assert plan["target_city"] == one_query["target_city"]
