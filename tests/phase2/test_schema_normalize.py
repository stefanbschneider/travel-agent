"""Tests for the Phase 2 two-layer schema + normalization skeleton (Task 4).

The skeleton must be a faithful passthrough: turning a query into a ParsedIR and back into solver
constraint variants must equal exactly what the current no-oracle path produces today, i.e.
``solver_constraint_variants(query, parse_query_no_oracle(query), use_oracle=False)``.
"""

from __future__ import annotations

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2.schema import ParsedIR


def _baseline_variants(query):
    raw = parse_constraints.parse_query_no_oracle(query)
    return solver_constraint_variants(query, raw, use_oracle=False)


def test_parse_to_ir_returns_parsed_ir(one_query):
    ir = normalize.parse_to_ir(one_query)
    assert isinstance(ir, ParsedIR)
    # Skeleton IR carries at least one variant (the flat deterministic parse).
    assert len(ir.variants) >= 1


def test_passthrough_matches_current_no_oracle_variants(sample_queries):
    for uid, query in sample_queries.items():
        ir = normalize.parse_to_ir(query)
        got = normalize.ir_to_solver_variants(ir, query)
        expected = _baseline_variants(query)
        assert got == expected, f"variant mismatch for uid {uid}"


def test_parse_to_ir_does_not_call_llm_by_default(sample_queries, spy_llm):
    for query in sample_queries.values():
        normalize.parse_to_ir(query, llm_client=spy_llm)
    assert spy_llm.calls == [], "parse_to_ir must not call the LLM on the default path"


def test_llm_parse_adds_missing_constraint_without_overwriting_existing(one_query):
    class FakeLLM:
        def __init__(self, response):
            self.response = response
            self.calls = []

        def complete(self, prompt, *, system=None, cache_key=None):
            self.calls.append({"prompt": prompt, "cache_key": cache_key})
            return self.response

    # dining budget is often absent in deterministic parse for generic queries; use LLM hint text.
    llm = FakeLLM('{"constraint_text":"The budget for dining is 120."}')
    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    ir = normalize.parse_to_ir(one_query, llm_client=llm, flags=flags)

    assert len(llm.calls) == 1
    budgets = ir.raw.get("budgets", {})
    assert budgets.get("dining") == 120.0


def test_llm_parse_invalid_json_raises(one_query):
    class BadLLM:
        def complete(self, prompt, *, system=None, cache_key=None):
            return "not-json"

    flags = type("Flags", (), {"disjunction": False, "llm_parse": True})()
    try:
        normalize.parse_to_ir(one_query, llm_client=BadLLM(), flags=flags)
    except ValueError as exc:
        assert "llm_parse invalid JSON" in str(exc)
    else:
        raise AssertionError("Expected llm_parse invalid JSON to raise")
