"""Tests for the Phase 2 orchestrator skeleton (Task 5).

Uses an injected ``solve_fn`` so no real WorldEnv/solver is needed. Verifies:
- normal solve returns the plan + populated telemetry,
- a raising or slow solve degrades to a schema-valid fallback (never raises),
- the deterministic path never calls the LLM.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import jsonschema

from chinatravel.agent.phase2 import orchestrator as O

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json").read_text(encoding="utf-8")
)


def test_returns_plan_and_telemetry(one_query, fast_solve_fn):
    plan, telemetry = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn)
    assert plan["itinerary"] == [{"day": 1, "activities": []}]
    for stage in ("parse", "solve", "improve", "finalize"):
        assert stage in telemetry["stage_sec"]
        assert telemetry["stage_sec"][stage] >= 0
    assert telemetry["used_fallback"] is False
    assert telemetry["timed_out"] is False
    assert telemetry["llm_backend"] == "none"


def test_fallback_on_raise(one_query):
    def boom(query, variants, budget_sec):
        raise RuntimeError("solver blew up")

    plan, telemetry = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=boom)
    jsonschema.validate(plan, SCHEMA)
    assert plan["itinerary"] == []
    assert telemetry["used_fallback"] is True


def test_fallback_on_timeout(one_query):
    def slow(query, variants, budget_sec):
        time.sleep(5.0)
        return {"itinerary": [{"day": 1, "activities": []}]}

    plan, telemetry = O.solve_phase2(one_query, budget_sec=0.3, solve_fn=slow)
    jsonschema.validate(plan, SCHEMA)
    assert telemetry["timed_out"] is True
    assert telemetry["used_fallback"] is True


def test_flags_off_never_calls_llm(sample_queries, spy_llm, fast_solve_fn):
    for query in sample_queries.values():
        O.solve_phase2(query, budget_sec=10.0, solve_fn=fast_solve_fn, llm_client=spy_llm)
    assert spy_llm.calls == [], "deterministic path must not call the LLM"


def test_flags_default_all_off():
    flags = O.Flags.from_env(env={})
    assert flags.llm_backend == "none"
    assert flags.disjunction is False
    assert flags.llm_parse is False
    assert flags.llm_refine is False
