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
