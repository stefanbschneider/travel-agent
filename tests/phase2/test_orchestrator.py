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


def test_timeout_recovers_best_plan_from_solve_hook(one_query):
    recovered_plan = {
        "people_number": one_query.get("people_number", 1),
        "start_city": one_query.get("start_city", ""),
        "target_city": one_query.get("target_city", ""),
        "itinerary": [{"day": 1, "activities": []}],
    }

    def slow_with_recovery(query, variants, budget_sec):
        time.sleep(5.0)
        return {"itinerary": []}

    slow_with_recovery.get_timeout_recovery_plan = lambda: recovered_plan

    plan, telemetry = O.solve_phase2(one_query, budget_sec=0.3, solve_fn=slow_with_recovery)
    jsonschema.validate(plan, SCHEMA)
    assert telemetry["timed_out"] is True
    assert telemetry["solve_recovered_from_timeout"] is True
    assert telemetry["used_fallback"] is False
    assert plan["itinerary"] == [{"day": 1, "activities": []}]


def test_improve_invalid_output_reverts_to_last_valid(one_query, fast_solve_fn, monkeypatch):
    def invalid_improve(plan, query, llm_client, budget_sec):
        return {"not": "a plan"}

    monkeypatch.setattr(O, "llm_refine_stub", invalid_improve)
    plan, telemetry = O.solve_phase2(
        one_query,
        budget_sec=10.0,
        solve_fn=fast_solve_fn,
        flags=O.Flags(llm_refine=True),
    )
    jsonschema.validate(plan, SCHEMA)
    assert plan["itinerary"] == [{"day": 1, "activities": []}]
    assert telemetry["improve_reverted_to_last_valid"] is True
    assert telemetry["used_fallback"] is False


def test_improve_timeout_reverts_to_last_valid(one_query, fast_solve_fn, monkeypatch):
    def slow_improve(plan, query, llm_client, budget_sec):
        time.sleep(0.3)
        return {"itinerary": []}

    monkeypatch.setattr(O, "llm_refine_stub", slow_improve)
    plan, telemetry = O.solve_phase2(
        one_query,
        budget_sec=1.0,
        solve_fn=fast_solve_fn,
        flags=O.Flags(llm_refine=True),
    )
    jsonschema.validate(plan, SCHEMA)
    assert telemetry["timed_out"] is True
    assert telemetry["improve_timed_out"] is True
    assert telemetry["improve_reverted_to_last_valid"] is True
    assert telemetry["used_fallback"] is False
    assert plan["itinerary"] == [{"day": 1, "activities": []}]


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


def test_llm_parse_error_degrades_to_fallback(one_query):
    class BadLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return "{not-json}"

    plan, telemetry = O.solve_phase2(
        one_query,
        budget_sec=10.0,
        solve_fn=None,
        llm_client=BadLLM(),
        flags=O.Flags(llm_parse=True),
    )
    jsonschema.validate(plan, SCHEMA)
    assert telemetry["used_fallback"] is True
    assert "parse:" in str(telemetry.get("error", ""))
