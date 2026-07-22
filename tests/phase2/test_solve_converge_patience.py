"""Unit tests for TPCAgent._solve's TPC_SOLVE_CONVERGE_PATIENCE early-convergence stop
(roadmap Next step 5: "Study the solver budget/convergence").

Builds a *bare* TPCAgent (``__new__``, no WorldEnv/LLM) with every collaborator replaced by a
spy/fake, the same pattern as ``test_solve_early_exit.py``, so ``_solve``'s real control flow runs
against fast, deterministic stand-ins. The CP-SAT branch is disabled via ``TPC_USE_CP_SOLVER=0``
(irrelevant to this test, and heavy).

This is a distinct mechanism from ``TPC_SOLVE_STOP_AT_ACCEPT`` (tested in
``test_solve_early_exit.py``): that flag stops at the *first* accepted plan regardless of
preference score, while this one keeps polishing the accepted plan's preference score and only
stops once it has stalled (no improvement) for ``solve_converge_patience`` consecutive restarts.
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


def _bare_solve_agent(*, max_restarts=10, accept_on_call=1, converge_patience=0, key_sequence=None):
    """A bare TPCAgent with every _solve collaborator faked out.

    ``accept_on_call`` is the 1-indexed _build_plan call count at which the checker starts
    accepting (and keeps accepting thereafter). ``key_sequence`` is a list of scalar preference
    values indexed by (1-indexed build_plan call count - 1); the accepted-eval key returned for
    the plan built on call ``n`` is ``(key_sequence[n - 1], 0.0, 0.0, 0.0)`` (clamped to the last
    entry once ``n`` exceeds the sequence length), so tests can script an improving-then-plateauing
    (or ever-improving) search trajectory.
    """
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent

    agent = TPCAgent.__new__(TPCAgent)
    agent.seed_salt = 0
    agent.start_clock = time.time()
    agent.solve_budget_sec = 1000.0
    agent.max_restarts = max_restarts
    agent.solve_converge_patience = converge_patience
    agent._injected_variants = None

    calls = {"build_plan": 0, "pack_plan": 0}

    agent._constraint_variants = lambda query: [None]  # one variant, no disjunction
    agent._repair_params = lambda constraints: []  # skip the repair phase entirely
    agent._random_params = lambda rng, constraints: {}
    agent._accepted = lambda passed, total: total > 0 and passed == total
    agent._eval_proxy = lambda plan: 0.0
    agent._plan_total_cost = lambda plan: 0.0
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._set_timeout_recovery_plan = lambda plan: None
    agent.reset_timeout_recovery_plan = lambda: None
    agent._visit_minutes_candidates = lambda constraints: []

    def fake_accepted_eval_key(plan):
        n = calls["build_plan"]
        if key_sequence is not None and n > 0:
            v = key_sequence[min(n - 1, len(key_sequence) - 1)]
        else:
            v = 0.0
        return (float(v), 0.0, 0.0, 0.0)

    agent._accepted_eval_key = fake_accepted_eval_key

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
    monkeypatch.delenv("TPC_SOLVE_STOP_AT_ACCEPT", raising=False)


def test_patience_zero_is_byte_identical_floor():
    """Flag-off (default 0) byte-identical-behavior guard: even when the preference key plateaus
    immediately, _solve must keep restarting to max_restarts and still call _pack_plan -- exactly
    the pre-existing behavior with no early-convergence logic engaged."""
    agent, calls = _bare_solve_agent(
        max_restarts=5, accept_on_call=1, converge_patience=0, key_sequence=[1, 1, 1, 1, 1, 1]
    )
    plan = agent._solve({"uid": "u1"})
    # base build (1) + 5 random restarts (repair_params is empty) = 6 build_plan calls.
    assert calls["build_plan"] == 6
    assert calls["pack_plan"] == 1
    assert plan == {"itinerary": []}


def test_patience_stops_early_once_plateaued():
    """With convergence patience set, the restart loop should stop as soon as the accepted
    preference key has failed to improve for `converge_patience` consecutive restarts, well short
    of max_restarts."""
    agent, calls = _bare_solve_agent(
        max_restarts=10,
        accept_on_call=1,
        converge_patience=2,
        # call 1 (base) -> 1, call2 -> 2, call3 -> 3, then flat at 3.
        key_sequence=[1, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3],
    )
    plan = agent._solve({"uid": "u1"})
    # base(1) + restarts 1..4 improve/stall as scripted; 2 consecutive stalls (calls 4 and 5)
    # trip the patience counter -> 5 total build_plan calls, well short of 1 + 10 = 11.
    assert calls["build_plan"] == 5
    assert calls["build_plan"] < 1 + agent.max_restarts
    assert calls["pack_plan"] == 1
    assert plan == {"itinerary": []}


def test_patience_set_but_never_plateaus_runs_full_budget():
    """If the preference key keeps improving every restart, patience never trips and the loop
    runs exactly like the flag-off case (same build_plan count, bounded by max_restarts)."""
    agent, calls = _bare_solve_agent(
        max_restarts=5,
        accept_on_call=1,
        converge_patience=2,
        key_sequence=list(range(1, 50)),  # strictly increasing every call
    )
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 6  # base + 5 restarts, same as the patience=0 case
    assert calls["pack_plan"] == 1
    assert plan == {"itinerary": []}


def test_patience_set_but_never_accepted_runs_full_budget():
    """No accepted plan ever exists (accept_on_call unreachable), so the stall counter must never
    engage -- the loop explores exactly like the flag-off case, not cut short."""
    agent, calls = _bare_solve_agent(
        max_restarts=5, accept_on_call=999, converge_patience=1, key_sequence=[1, 1, 1, 1, 1, 1]
    )
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 6  # base + 5 restarts, nothing ever accepted
    assert plan == {"itinerary": []}
