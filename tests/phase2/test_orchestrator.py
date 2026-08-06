"""Tests for the Phase 2 orchestrator skeleton.

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
    assert telemetry["variants_source"] == "worker"


def test_variants_source_is_parent_when_variants_are_supplied(one_query, fast_solve_fn):
    """Roadmap P10: a caller that already ran the canonical parse (the sweep scheduler) supplies
    ``variants=`` and Stage 1 must be skipped entirely -- telemetry records which path ran so a
    row can prove it."""
    supplied = [{"required_attractions": ["Some POI"]}]
    seen_variants = {}

    def capturing_solve(query, variants, budget_sec):
        seen_variants["value"] = variants
        return {"itinerary": [{"day": 1, "activities": []}]}

    plan, telemetry = O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=capturing_solve, variants=supplied
    )
    assert telemetry["variants_source"] == "parent"
    assert telemetry["variants_count"] == 1
    assert seen_variants["value"] is supplied


def test_variants_source_worker_when_not_supplied(one_query, fast_solve_fn):
    plan, telemetry = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn)
    assert telemetry["variants_source"] == "worker"


def test_empty_variants_list_from_parent_reparses_like_none(one_query, fast_solve_fn):
    """Roadmap P13: an empty parent-supplied variants list must be treated the same as
    ``variants=None`` -- "the parent has nothing for you, parse it yourself" -- not as "the
    parent supplied variants, just zero of them".

    A prior version of this test (and the code) took the opposite position: ``variants=[]``
    skipped Stage 1 and reported ``variants_source == "parent"`` with ``variants_count == 0``,
    on the theory that solve and score would then agree on a shared "unconstrained" state. They
    did not: ``selfscore.score_plan`` already falls back to ``derive_parsed_constraints`` on any
    falsy ``variants`` (``if not variants:``), so that plan self-scored against real constraints
    while the solver searched with none -- reintroducing on the parent-parse-failure path exactly
    the solve/score divergence roadmap P10 exists to remove, and risking the false positive
    roadmap P12 exists to remove (a parse-failed query self-scoring ``logical_ok = True``
    vacuously and getting abandoned by the scheduler while still broken).

    The fix instead makes both sides re-parse independently on an empty list, exactly as they do
    on ``None`` -- not byte-identically, but both constrained. This is resolution (a) from the
    roadmap's own table of the two options; resolution (b) (make ``score_plan`` stop falling back
    on ``[]``) was rejected there for manufacturing the false positive above.
    """
    plan, telemetry = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn, variants=[])
    assert telemetry["variants_source"] == "worker"
    assert telemetry["variants_count"] > 0


def test_nonempty_variants_from_parent_still_skip_reparse(one_query, fast_solve_fn):
    """The counterpart to the test above: a genuinely non-empty parent-supplied list must still
    report ``variants_source == "parent"`` and skip Stage 1 -- P13 only changes the empty case."""
    supplied = [{"required_attractions": ["Some POI"]}]
    plan, telemetry = O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=fast_solve_fn, variants=supplied
    )
    assert telemetry["variants_source"] == "parent"
    assert telemetry["variants_count"] == 1


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


def test_search_telemetry_defaults_empty_when_solve_fn_lacks_the_hook(one_query, fast_solve_fn):
    """fast_solve_fn (and any injected test stub) exposes no get_search_telemetry, so the
    orchestrator must degrade to an empty dict rather than raising or fabricating numbers."""
    _plan, telemetry = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn)
    assert telemetry["search_telemetry"] == {}


def test_search_telemetry_surfaces_from_the_solve_fn_hook(one_query, fast_solve_fn):
    """roadmap W4 step 0: TPCAgent._solve's restarts_used/stop_reason/candidates_evaluated/
    best_found_at_restart, exposed by make_tpcagent_solve_fn's get_search_telemetry hook, must
    reach the orchestrator's returned telemetry unchanged."""
    stub_telemetry = {
        "restarts_used": 12,
        "stop_reason": "max_restarts",
        "candidates_evaluated": 13,
        "best_found_at_restart": 4,
    }
    fast_solve_fn.get_search_telemetry = lambda: dict(stub_telemetry)

    _plan, telemetry = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn)

    assert telemetry["search_telemetry"] == stub_telemetry


def test_improve_invalid_output_reverts_to_last_valid(one_query, fast_solve_fn, monkeypatch):
    def invalid_improve(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits):
        return {"not": "a plan"}

    monkeypatch.setattr(O, "llm_refine", invalid_improve)
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
    def slow_improve(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits):
        time.sleep(0.3)
        return {"itinerary": []}

    monkeypatch.setattr(O, "llm_refine", slow_improve)
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
    assert flags.dynamic_budget is False


def test_dynamic_budget_off_passes_static_solve_slice(one_query):
    from chinatravel.agent.phase2 import budget as B

    seen = {}

    def spy_solve(query, variants, budget_sec):
        seen["budget_sec"] = budget_sec
        return {"itinerary": [{"day": 1, "activities": []}]}

    O.solve_phase2(one_query, budget_sec=300.0, solve_fn=spy_solve, flags=O.Flags())
    assert seen["budget_sec"] == B.split_budget(300.0).solve_sec


def test_dynamic_budget_on_gives_solver_the_unused_parse_slice(one_query):
    seen = {}

    def spy_solve(query, variants, budget_sec):
        seen["budget_sec"] = budget_sec
        return {"itinerary": [{"day": 1, "activities": []}]}

    plan, telemetry = O.solve_phase2(
        one_query, budget_sec=300.0, solve_fn=spy_solve, flags=O.Flags(dynamic_budget=True),
    )
    # Parse of one_query is fast (deterministic, no LLM) -- solver should get most of the budget
    # minus the finalize reserve, comfortably more than the static ~165s slice.
    assert seen["budget_sec"] > 250.0
    assert telemetry["flags"]["dynamic_budget"] is True
    assert telemetry["dynamic_solve_sec"] == seen["budget_sec"]


def test_dynamic_budget_on_withholds_improve_reserve_when_llm_refine_on(one_query, spy_llm):
    seen = {}

    def spy_solve(query, variants, budget_sec):
        seen["budget_sec"] = budget_sec
        return {"itinerary": [{"day": 1, "activities": []}]}

    O.solve_phase2(
        one_query, budget_sec=300.0, solve_fn=spy_solve, llm_client=spy_llm,
        flags=O.Flags(dynamic_budget=True, llm_refine=True),
    )
    # Improve slice (30s of 300s) must be withheld from the solver when Stage 3 will run.
    assert seen["budget_sec"] < 270.0


def test_orchestrator_passes_parse_slice_as_llm_deadline(one_query, fast_solve_fn):
    from chinatravel.agent.phase2 import budget as B

    class SlowClient:
        timeout = 30.0

        def __init__(self):
            self.calls = 0

        def complete(self, prompt, *, system=None, cache_key=None):
            self.calls += 1
            return '{"constraint_text":"The budget for dining is 120."}'

    llm = SlowClient()
    # A total budget whose static parse slice (25% of post-finalize) is well under the client's
    # 30s timeout -- the call must be skipped, and the skip must surface in telemetry.
    plan, telemetry = O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=fast_solve_fn, llm_client=llm,
        flags=O.Flags(llm_parse=True),
    )
    assert llm.calls == 0
    assert telemetry["llm_parse_skipped_deadline"] is True
    assert B.split_budget(10.0).parse_sec < llm.timeout


def test_dynamic_budget_floors_at_static_slice_on_tiny_budget(one_query):
    """A total budget so small that parsing alone can plausibly eat past it must never push the
    dynamic solve slice below what the static split would have given."""
    from chinatravel.agent.phase2 import budget as B

    seen = {}

    def spy_solve(query, variants, budget_sec):
        seen["budget_sec"] = budget_sec
        return {"itinerary": [{"day": 1, "activities": []}]}

    O.solve_phase2(
        one_query, budget_sec=0.05, solve_fn=spy_solve, flags=O.Flags(dynamic_budget=True),
    )
    assert seen["budget_sec"] >= B.split_budget(0.05).solve_sec - 1e-9


def test_llm_parse_error_keeps_deterministic_parse_not_a_parse_failure(one_query):
    """A flaky LLM backend must degrade to the deterministic parse, not to zero variants.

    Previously parse_to_ir let llm_parse_stub's raise propagate, and this whole function wraps
    parse_to_ir in a try/except that discards ir entirely (variants=[]) on ANY parse-stage
    exception -- so an LLM hiccup was indistinguishable from a genuine parse bug. solve_fn is
    None here (no WorldEnv in this unit test), so used_fallback is still True for an unrelated
    reason (nothing can actually solve) -- but telemetry["error"] must not say "parse:", and the
    deterministic variant must have survived into variants_count.
    """
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
    assert "parse:" not in str(telemetry.get("error", ""))
    assert telemetry["variants_count"] == 1
