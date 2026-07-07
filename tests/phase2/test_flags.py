"""Tests for the flag-gated improvement stubs (Task 11).

All three flags default OFF and the deterministic path must be byte-identical to the current
no-oracle baseline. When a flag is ON, the pipeline routes through a named no-op stub that does not
change results (and, in the skeleton, still does not call the LLM).
"""

from __future__ import annotations

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

from chinatravel.agent.phase2 import normalize, orchestrator as O
from chinatravel.agent.phase2.orchestrator import Flags


def _baseline_variants(query):
    raw = parse_constraints.parse_query_no_oracle(query)
    return solver_constraint_variants(query, raw, use_oracle=False)


def test_flags_off_variants_byte_identical(sample_queries):
    off = Flags()
    for uid, q in sample_queries.items():
        ir = normalize.parse_to_ir(q, flags=off)
        got = normalize.ir_to_solver_variants(ir, q, flags=off)
        assert got == _baseline_variants(q), uid


def test_disjunction_flag_routes_through_stub_without_change(sample_queries, monkeypatch):
    calls = {"n": 0}
    orig = normalize.disjunction_stub

    def spy(variants, ir, query):
        calls["n"] += 1
        return orig(variants, ir, query)

    monkeypatch.setattr(normalize, "disjunction_stub", spy)
    flags = Flags(disjunction=True)
    q = next(iter(sample_queries.values()))
    ir = normalize.parse_to_ir(q, flags=flags)
    got = normalize.ir_to_solver_variants(ir, q, flags=flags)
    assert calls["n"] == 1
    assert got == _baseline_variants(q)  # stub is a no-op


def test_llm_parse_flag_routes_through_stub_without_llm_call(sample_queries, spy_llm, monkeypatch):
    calls = {"n": 0}
    orig = normalize.llm_parse_stub

    def spy(ir, query, llm_client):
        calls["n"] += 1
        return orig(ir, query, llm_client)

    monkeypatch.setattr(normalize, "llm_parse_stub", spy)
    flags = Flags(llm_parse=True)
    q = next(iter(sample_queries.values()))
    ir = normalize.parse_to_ir(q, llm_client=spy_llm, flags=flags)
    got = normalize.ir_to_solver_variants(ir, q, flags=flags)
    assert calls["n"] == 1
    assert got == _baseline_variants(q)
    assert len(spy_llm.calls) == 1


def test_llm_refine_flag_routes_through_stub_without_change(one_query, fast_solve_fn, spy_llm, monkeypatch):
    calls = {"n": 0}
    orig = O.llm_refine_stub

    def spy(plan, query, llm_client, budget_sec):
        calls["n"] += 1
        return orig(plan, query, llm_client, budget_sec)

    monkeypatch.setattr(O, "llm_refine_stub", spy)
    plan_off, _ = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn)
    plan_on, _ = O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=fast_solve_fn, llm_client=spy_llm,
        flags=Flags(llm_refine=True),
    )
    assert calls["n"] == 1
    assert plan_on == plan_off  # stub is a no-op
    assert spy_llm.calls == []


def test_all_flags_off_no_stub_calls(sample_queries, monkeypatch):
    seen = {"disj": 0, "parse": 0}
    monkeypatch.setattr(normalize, "disjunction_stub",
                        lambda v, ir, q: (seen.__setitem__("disj", seen["disj"] + 1) or v))
    monkeypatch.setattr(normalize, "llm_parse_stub",
                        lambda ir, q, c: (seen.__setitem__("parse", seen["parse"] + 1) or ir))
    q = next(iter(sample_queries.values()))
    ir = normalize.parse_to_ir(q, flags=Flags())
    normalize.ir_to_solver_variants(ir, q, flags=Flags())
    assert seen == {"disj": 0, "parse": 0}
