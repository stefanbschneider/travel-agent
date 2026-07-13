"""Unit tests for TPCAgent._solve's TPC_SOLVE_STOP_AT_ACCEPT early-exit mode (plan-2 Step 3).

Builds a *bare* TPCAgent (``__new__``, no WorldEnv/LLM) with every collaborator replaced by a
spy/fake, the same pattern as ``test_agent_injection.py``, so ``_solve``'s real control flow runs
against fast, deterministic stand-ins. The CP-SAT branch is disabled via ``TPC_USE_CP_SOLVER=0``
(irrelevant to this test, and heavy).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _bare_solve_agent(*, max_restarts=3, accept_on_call=1):
    """A bare TPCAgent with every _solve collaborator faked out. ``accept_on_call`` is the
    1-indexed _build_plan call count at which the checker starts accepting (and keeps accepting
    thereafter), so tests can control exactly when ``consider()`` first sees an accepted plan."""
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent

    agent = TPCAgent.__new__(TPCAgent)
    agent.seed_salt = 0
    agent.start_clock = time.time()
    agent.solve_budget_sec = 1000.0
    agent.max_restarts = max_restarts
    agent._injected_variants = None

    calls = {"build_plan": 0, "pack_plan": 0}

    agent._constraint_variants = lambda query: [None]  # one variant, no disjunction
    agent._repair_params = lambda constraints: []  # skip the repair phase entirely
    agent._random_params = lambda rng, constraints: {}
    agent._accepted = lambda passed, total: total > 0 and passed == total
    agent._accepted_eval_key = lambda plan: (0.0, 0.0, 0.0, 0.0)
    agent._eval_proxy = lambda plan: 0.0
    agent._plan_total_cost = lambda plan: 0.0
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._set_timeout_recovery_plan = lambda plan: None
    agent.reset_timeout_recovery_plan = lambda: None
    agent._visit_minutes_candidates = lambda constraints: []

    def fake_make_checker(query, constraints):
        def check(plan):
            return (1, 1) if calls["build_plan"] >= accept_on_call else (0, 1)
        return check

    def fake_build_plan(query, constraints=None, params=None):
        calls["build_plan"] += 1
        return {"itinerary": []}

    def fake_pack_plan(plan, query, constraints, check, base_params):
        calls["pack_plan"] += 1
        return plan

    agent._make_checker = fake_make_checker
    agent._build_plan = fake_build_plan
    agent._pack_plan = fake_pack_plan

    return agent, calls


@pytest.fixture(autouse=True)
def _no_cp_solver(monkeypatch):
    monkeypatch.setenv("TPC_USE_CP_SOLVER", "0")


@pytest.fixture
def _stop_at_accept_off(monkeypatch):
    monkeypatch.delenv("TPC_SOLVE_STOP_AT_ACCEPT", raising=False)


@pytest.fixture
def _stop_at_accept_on(monkeypatch):
    monkeypatch.setenv("TPC_SOLVE_STOP_AT_ACCEPT", "1")


def test_flag_off_runs_all_restarts_and_packs(_stop_at_accept_off):
    """Byte-identical-behavior guard: with the flag off (the default, and the only mode the
    organizers' harness ever runs), _solve must keep restarting to max_restarts and must still
    call _pack_plan -- exactly the pre-Step-3 behavior."""
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    plan = agent._solve({"uid": "u1"})
    # base build (1) + 3 random restarts (repair_params is empty) = 4 build_plan calls
    assert calls["build_plan"] == 4
    assert calls["pack_plan"] == 1
    assert plan == {"itinerary": []}


def test_flag_on_stops_at_first_accept_and_skips_pack(_stop_at_accept_on):
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    plan = agent._solve({"uid": "u1"})
    # accepted on the very first (base) build -- no repair/restart calls, no packing.
    assert calls["build_plan"] == 1
    assert calls["pack_plan"] == 0
    assert plan == {"itinerary": []}


def test_flag_on_still_explores_until_first_accept(_stop_at_accept_on):
    """When acceptance doesn't happen on the base build, fastfpr must still explore the repair/
    restart loops -- it only stops the *moment* something is accepted, not before."""
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=3)
    plan = agent._solve({"uid": "u1"})
    # base build (1) + 2 random restarts before the 3rd build_plan call is accepted = 3 total.
    assert calls["build_plan"] == 3
    assert calls["pack_plan"] == 0
    assert plan == {"itinerary": []}


def test_flag_on_never_accepted_explores_full_budget_but_still_skips_pack(_stop_at_accept_on):
    """If nothing is ever accepted, there's no early exit to trigger, so fastfpr explores exactly
    like the normal path (same build_plan count) -- but packing is unconditionally skipped
    whenever the flag is on, regardless of whether an accept ever happened."""
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=999)
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 4  # base + 3 restarts, same count as the flag-off case
    assert calls["pack_plan"] == 0  # unconditional under stop_at_accept, not gated on acceptance
    assert plan == {"itinerary": []}
