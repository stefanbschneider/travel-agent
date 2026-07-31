"""Unit tests for TPCAgent._solve's early-exit modes: TPC_SOLVE_STOP_AT_ACCEPT (stop at first
accept, skip finalization) and TPC_SOLVE_STOP_AT_ACCEPT_PACKED (stop at first accept but still run
_pack_plan, for fast FPR measurement in a longer budget regime without skipping the repair passes).

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
    monkeypatch.delenv("TPC_SOLVE_STOP_AT_ACCEPT_PACKED", raising=False)


@pytest.fixture
def _stop_at_accept_on(monkeypatch):
    monkeypatch.setenv("TPC_SOLVE_STOP_AT_ACCEPT", "1")


@pytest.fixture
def _stop_at_accept_packed_on(monkeypatch):
    # Explicitly clear the plain stop-at-accept so this exercises the packed variant alone.
    monkeypatch.delenv("TPC_SOLVE_STOP_AT_ACCEPT", raising=False)
    monkeypatch.setenv("TPC_SOLVE_STOP_AT_ACCEPT_PACKED", "1")


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


def test_packed_flag_stops_at_first_accept_but_still_packs(_stop_at_accept_packed_on):
    """The distinguishing behavior vs TPC_SOLVE_STOP_AT_ACCEPT: the packed variant stops the search
    at the first accept (build_plan == 1 here) *and still runs* _pack_plan, so the deterministic
    repair passes under measurement (pin/transport-repair) execute."""
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 1  # stops the moment the base build is accepted
    assert calls["pack_plan"] == 1  # ...but finalization still runs, unlike stop_at_accept
    assert plan == {"itinerary": []}


def test_packed_flag_explores_until_first_accept_then_packs(_stop_at_accept_packed_on):
    """When the base build isn't accepted, the packed variant keeps exploring until the first
    accept, then packs -- it stops the moment something is accepted, not before."""
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=3)
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 3  # base + 2 restarts before the 3rd build is accepted
    assert calls["pack_plan"] == 1
    assert plan == {"itinerary": []}


def test_packed_flag_never_accepted_explores_full_budget_and_still_packs(_stop_at_accept_packed_on):
    """If nothing is ever accepted, there's no early exit, so it explores the full restart budget
    exactly like the flag-off path -- and, unlike stop_at_accept, it still packs the best plan (so
    pin/transport-repair can flip a produced-but-invalid plan to accepted at finalization)."""
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=999)
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 4  # base + 3 restarts, same count as the flag-off case
    assert calls["pack_plan"] == 1  # finalization always runs under the packed variant
    assert plan == {"itinerary": []}


def test_plain_stop_at_accept_takes_precedence_over_packed(monkeypatch):
    """If both flags are set (a nonsensical combo), the plain stop-at-accept's pack-skip wins: the
    docstring says do not set both, and the guard at the pack step keys off stop_at_accept."""
    monkeypatch.setenv("TPC_SOLVE_STOP_AT_ACCEPT", "1")
    monkeypatch.setenv("TPC_SOLVE_STOP_AT_ACCEPT_PACKED", "1")
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    plan = agent._solve({"uid": "u1"})
    assert calls["build_plan"] == 1
    assert calls["pack_plan"] == 0  # stop_at_accept's pack-skip wins
    assert plan == {"itinerary": []}


# --- Search telemetry (roadmap W4 step 0) ------------------------------------------------------
#
# Pure observation, no behavior change: restarts_used, stop_reason, candidates_evaluated,
# best_found_at_restart, exposed via agent.last_search_telemetry after _solve returns.


def test_telemetry_max_restarts_stop(_stop_at_accept_off):
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    agent._solve({"uid": "u1"})
    t = agent.last_search_telemetry
    assert t["restarts_used"] == 3
    assert t["stop_reason"] == "max_restarts"
    assert t["candidates_evaluated"] == calls["build_plan"] == 4  # base + 3 restarts
    assert t["best_found_at_restart"] == 0  # accepted on the very first (base, pre-restart) build


def test_telemetry_best_found_at_restart_tracks_the_restart_that_won(_stop_at_accept_off):
    agent, calls = _bare_solve_agent(max_restarts=3, accept_on_call=3)
    agent._solve({"uid": "u1"})
    t = agent.last_search_telemetry
    # base build (restarts=0) + 2 random restarts before the 3rd build_plan call (restarts=2)
    # is the one that gets accepted.
    assert t["best_found_at_restart"] == 2
    # Flag off means all max_restarts=3 restarts still run regardless of acceptance.
    assert t["candidates_evaluated"] == calls["build_plan"] == 4


def test_telemetry_accepted_stop_reason(_stop_at_accept_on):
    agent, _calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    agent._solve({"uid": "u1"})
    assert agent.last_search_telemetry["stop_reason"] == "accepted_stop"


def test_telemetry_budget_stop_reason(_stop_at_accept_off):
    agent, calls = _bare_solve_agent(max_restarts=1000, accept_on_call=1)
    agent.solve_budget_sec = 0.0
    agent.start_clock = time.time() - 10.0  # already over budget before _solve even starts
    agent._solve({"uid": "u1"})
    t = agent.last_search_telemetry
    assert t["stop_reason"] == "budget"
    assert t["restarts_used"] == 0
    assert t["candidates_evaluated"] == 0  # out_of_budget() short-circuits before any consider()
    # Nothing was ever built/considered, so _solve falls back to one guaranteed unconsidered
    # build (line ~1160) to still return a plan -- that call bypasses consider() entirely.
    assert calls["build_plan"] == 1


def test_telemetry_converged_stop_reason(_stop_at_accept_off):
    agent, calls = _bare_solve_agent(max_restarts=100, accept_on_call=1)
    agent.solve_converge_patience = 2
    agent._solve({"uid": "u1"})
    t = agent.last_search_telemetry
    # Every accepted candidate shares the same (constant) _accepted_eval_key in this fixture, so
    # the preference key never improves once accepted -- stall_restarts reaches patience=2 after
    # exactly 2 non-improving restarts past the first accept.
    assert t["stop_reason"] == "converged"
    assert t["restarts_used"] == 2
    assert calls["build_plan"] == 3  # base (accepted) + 2 non-improving restarts


class _SimulatedAsyncKill(BaseException):
    """Stands in for func_timeout's asynchronous thread kill: a BaseException (not Exception)
    subclass, so it propagates past every `except Exception` in the restart loop and out of
    _solve entirely -- exactly like a real timeout kill, which can land at any bytecode point."""


def test_telemetry_survives_a_mid_loop_kill_instead_of_staying_empty(_stop_at_accept_off):
    """roadmap W4 step 0 follow-up: before this fix, self.last_search_telemetry was assigned only
    once, at the very end of _solve -- so a func_timeout kill (which lands mid-restart-loop, before
    that line ever runs) always left {} behind, silently discarding telemetry for exactly the
    budget-bound queries this instrumentation exists to explain (confirmed against real queries: 2
    of 8 familiar-100-val solves at a 150s budget came back with search_telemetry == {}). Now every
    leader-improving consider() call snapshots last_search_telemetry immediately, mirroring
    _set_timeout_recovery_plan's own snapshot, so a kill after any restart leaves a real partial
    record instead of an empty one."""
    agent, calls = _bare_solve_agent(max_restarts=1000, accept_on_call=1)
    # Strictly-increasing eval_proxy forces every restart to improve the leader, so consider()
    # updates last_search_telemetry on every call, not just the first.
    agent._eval_proxy = lambda plan: calls["build_plan"]

    orig_build_plan = agent._build_plan

    def killed_build_plan(query, constraints=None, params=None):
        plan = orig_build_plan(query, constraints=constraints, params=params)
        if calls["build_plan"] == 4:
            raise _SimulatedAsyncKill()
        return plan

    agent._build_plan = killed_build_plan

    with pytest.raises(_SimulatedAsyncKill):
        agent._solve({"uid": "u1"})

    # Call #4 is killed before its own consider() ever runs, so the surviving snapshot is from
    # call #3 (the base build is call #1 at restarts=0; while-loop calls #2/#3 land at restarts=1/2).
    t = agent.last_search_telemetry
    assert t  # not {} -- the whole point of this fix
    assert t["stop_reason"] == "interrupted"
    assert t["candidates_evaluated"] == 3
    assert t["restarts_used"] == 2
    assert t["best_found_at_restart"] == 2


def test_telemetry_reset_at_start_of_solve_never_leaks_a_prior_calls_dict(_stop_at_accept_off):
    """A harness-level timeout kills _solve before it reaches its own final assignment (that path
    can't be exercised from inside this bare-agent harness, since every internal exception here is
    already caught and the loop runs to completion). What is testable, and is the actual guard:
    _solve resets last_search_telemetry to a fresh dict at the top of every call, rather than
    mutating/reusing the previous call's dict, so a genuinely-killed call can never leave the
    previous query's numbers looking like they belong to the new one."""
    agent, _calls = _bare_solve_agent(max_restarts=3, accept_on_call=1)
    agent._solve({"uid": "u1"})
    first = agent.last_search_telemetry
    assert first  # sanity: the first call did populate it

    agent._solve({"uid": "u2"})
    second = agent.last_search_telemetry
    assert second is not first
