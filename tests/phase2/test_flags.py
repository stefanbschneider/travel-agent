"""Tests for the flag-gated improvement hooks.

All flags default OFF and the deterministic path must be byte-identical to the current no-oracle
baseline. Disjunction/llm_parse route through named no-op-preserving stubs; llm_refine (Stage 3) is
a real acceptance-gated repair pass once a TPCAgent-backed solve_fn's ground_and_check hook is
present (see tests/phase2/test_llm_refine.py) but is still a pure no-op -- no LLM call -- against
the bare solve_fn stub these tests use, which exposes no such hook.
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


def test_llm_refine_flag_with_no_hook_is_noop_without_llm_call(one_query, fast_solve_fn, spy_llm, monkeypatch):
    # fast_solve_fn (the bare Stage-2 test stub) exposes no ground_and_check hook -- the shape a
    # real TPCAgent-backed solve_fn only gets from make_tpcagent_solve_fn -- so llm_refine must
    # degrade to a pure no-op even with the flag on and a real llm_client, exactly like the other
    # flag-gated stubs. See tests/phase2/test_llm_refine.py for llm_refine's own repair-path tests.
    calls = {"n": 0}
    orig = O.llm_refine

    def spy(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits,
            max_attempts=2):
        calls["n"] += 1
        return orig(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits,
                    max_attempts)

    monkeypatch.setattr(O, "llm_refine", spy)
    plan_off, _ = O.solve_phase2(one_query, budget_sec=10.0, solve_fn=fast_solve_fn)
    plan_on, _ = O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=fast_solve_fn, llm_client=spy_llm,
        flags=Flags(llm_refine=True),
    )
    assert calls["n"] == 1
    assert plan_on == plan_off
    assert spy_llm.calls == []


def test_llm_repair_loop_flag_alone_enables_stage_3_with_six_attempts(
    one_query, fast_solve_fn, spy_llm, monkeypatch,
):
    """TPC_P2_LLM_REPAIR_LOOP must be sufficient on its own (roadmap P6) -- no need to also set
    TPC_P2_LLM_REFINE -- and must raise max_attempts from llm_refine's default (2) to 6."""
    captured = {}
    orig = O.llm_refine

    def spy(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits,
            max_attempts=2):
        captured["max_attempts"] = max_attempts
        return orig(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits,
                    max_attempts)

    monkeypatch.setattr(O, "llm_refine", spy)
    O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=fast_solve_fn, llm_client=spy_llm,
        flags=Flags(llm_repair_loop=True),
    )
    assert captured["max_attempts"] == 6


def test_llm_refine_flag_alone_still_uses_two_attempts(one_query, fast_solve_fn, spy_llm, monkeypatch):
    """llm_refine=True without llm_repair_loop must keep today's round cap -- P6 only changes
    behaviour when its own flag is set."""
    captured = {}
    orig = O.llm_refine

    def spy(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits,
            max_attempts=2):
        captured["max_attempts"] = max_attempts
        return orig(plan, query, llm_client, budget_sec, ground_and_check, apply_refine_edits,
                    max_attempts)

    monkeypatch.setattr(O, "llm_refine", spy)
    O.solve_phase2(
        one_query, budget_sec=10.0, solve_fn=fast_solve_fn, llm_client=spy_llm,
        flags=Flags(llm_refine=True),
    )
    assert captured["max_attempts"] == 2


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
