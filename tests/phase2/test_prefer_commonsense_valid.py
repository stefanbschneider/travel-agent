"""Unit tests for the commonsense-valid finalization preference (``TPC_COMMONSENSE_FIRST``).

Why the mechanism exists: ``eval_tpc`` scores C-LPR as the *conditional* logical micro
(``evaluate_hard_constraints_v2(..., env_pass_id=commonsense_pass_id)``), so a query's per-clause
logical credit counts only when its plan also passes the commonsense checker, and EPR-macro is
all-or-nothing per query. ``_solve`` used to emit the parsed-pass leader whenever nothing was fully
accepted, making commonsense validity of the emitted plan incidental -- on the promoted row
``20260724T192503Z`` that cost 21 of 80 end-to-end queries their whole logical credit while each of
them passed 8/9..11/13 clauses.

Built on the bare-``TPCAgent`` pattern of ``test_solve_converge_patience.py``: ``__new__``, no
WorldEnv/LLM, every ``_solve`` collaborator faked, CP-SAT disabled.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _plan(marker):
    """Minimal but structurally plausible plan, so ``_fast_commonsense_prefilter`` lets it through.

    One activity, valid times, no position change -> no inbound leg required.
    """
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {
                        "type": "attraction",
                        "position": marker,
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "price": 0,
                        "cost": 0,
                        "tickets": 1,
                        "transports": [],
                    }
                ],
            }
        ]
    }


LEADER = _plan("leader")
VALID = _plan("commonsense-valid")
ACCEPTED = _plan("accepted")


def _bare_solve_agent(*, plans, passed_by_plan, commonsense_ok_plans, max_restarts=3):
    """Bare agent whose scripted candidate stream is ``plans`` (one per ``_build_plan`` call).

    ``passed_by_plan`` maps a plan's marker string to its parsed-constraint pass count out of 2, so
    a plan with ``2`` is fully accepted and anything lower is not. ``commonsense_ok_plans`` is the
    set of markers whose plan passes schema+commonsense.
    """
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent

    agent = TPCAgent.__new__(TPCAgent)
    agent.seed_salt = 0
    agent.start_clock = time.time()
    agent.solve_budget_sec = 1000.0
    agent.max_restarts = max_restarts
    agent.solve_converge_patience = 0
    agent._injected_variants = None

    calls = {"build_plan": 0, "pack_plan": 0, "commonsense_ok": 0, "recovery": []}

    def marker(plan):
        return (plan.get("itinerary") or [{}])[0].get("activities", [{}])[0].get("position", "")

    agent._constraint_variants = lambda query: [None]
    agent._repair_params = lambda constraints: []
    agent._random_params = lambda rng, constraints: {}
    agent._accepted = lambda passed, total: total > 0 and passed == total
    agent._eval_proxy = lambda plan: 0.0
    agent._plan_total_cost = lambda plan: 0.0
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent.reset_timeout_recovery_plan = lambda: None
    agent._visit_minutes_candidates = lambda constraints: []
    agent._accepted_eval_key = lambda plan: (0.0, 0.0, 0.0, 0.0)
    agent._schema_ok = lambda query, plan: True

    def fake_commonsense_ok(query, plan):
        calls["commonsense_ok"] += 1
        return marker(plan) in commonsense_ok_plans

    agent._commonsense_ok = fake_commonsense_ok
    agent._set_timeout_recovery_plan = lambda plan: calls["recovery"].append(marker(plan))

    def fake_make_checker(query, constraints):
        def check(plan):
            return (passed_by_plan.get(marker(plan), 0), 2)
        return check

    agent._make_checker = fake_make_checker

    def fake_build_plan(query, constraints=None, params=None):
        idx = min(calls["build_plan"], len(plans) - 1)
        calls["build_plan"] += 1
        return plans[idx]

    agent._build_plan = fake_build_plan
    agent._pack_plan = lambda plan, query, constraints, check, base_params: (
        calls.__setitem__("pack_plan", calls["pack_plan"] + 1) or plan
    )
    return agent, calls


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("TPC_USE_CP_SOLVER", "0")
    monkeypatch.delenv("TPC_SOLVE_STOP_AT_ACCEPT", raising=False)
    monkeypatch.delenv("TPC_SOLVE_STOP_AT_ACCEPT_PACKED", raising=False)
    monkeypatch.delenv("TPC_COMMONSENSE_FIRST", raising=False)
    monkeypatch.delenv("TPC_CS_CHECK_BUDGET", raising=False)


def _unaccepted_stream():
    """Leader passes more parsed clauses but fails commonsense; the runner-up is valid."""
    return dict(
        plans=[LEADER, VALID],
        passed_by_plan={"leader": 1, "commonsense-valid": 0},
        commonsense_ok_plans={"commonsense-valid"},
    )


def test_flag_off_emits_the_parsed_pass_leader():
    agent, calls = _bare_solve_agent(**_unaccepted_stream())

    plan = agent._solve({"uid": "u1"})

    assert plan is LEADER
    # No probing at all when the flag is off: the floor must not pay for extra evaluator calls.
    assert calls["commonsense_ok"] == 0


def test_flag_on_emits_the_commonsense_valid_candidate(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent, calls = _bare_solve_agent(**_unaccepted_stream())

    plan = agent._solve({"uid": "u1"})

    assert plan is VALID
    assert calls["pack_plan"] == 1  # the chosen bucket still goes through _pack_plan


def test_flag_on_keeps_the_leader_when_it_is_already_valid(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent, _ = _bare_solve_agent(
        plans=[LEADER, VALID],
        passed_by_plan={"leader": 1, "commonsense-valid": 0},
        commonsense_ok_plans={"leader", "commonsense-valid"},
    )

    plan = agent._solve({"uid": "u1"})

    assert plan is LEADER


def test_accepted_plan_still_wins_over_a_valid_unaccepted_one(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent, _ = _bare_solve_agent(
        plans=[VALID, ACCEPTED],
        passed_by_plan={"commonsense-valid": 0, "accepted": 2},
        commonsense_ok_plans={"commonsense-valid", "accepted"},
    )

    plan = agent._solve({"uid": "u1"})

    assert plan is ACCEPTED


def test_check_budget_zero_behaves_like_flag_off(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_CS_CHECK_BUDGET", "0")
    agent, calls = _bare_solve_agent(**_unaccepted_stream())

    plan = agent._solve({"uid": "u1"})

    assert plan is LEADER
    assert calls["commonsense_ok"] == 0


def test_check_budget_bounds_the_evaluator_calls(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_CS_CHECK_BUDGET", "1")
    # Every candidate improves the search key, so without the bound each one would be probed.
    plans = [_plan(f"c{i}") for i in range(4)]
    agent, calls = _bare_solve_agent(
        plans=plans,
        passed_by_plan={f"c{i}": i for i in range(4)},
        commonsense_ok_plans={"c0"},
        max_restarts=3,
    )

    agent._solve({"uid": "u1"})

    # One probe for the first key leader, plus the single verdict on the final leader in the
    # selection step. The unbounded version would probe every one of the four leaders.
    assert calls["commonsense_ok"] <= 2


def test_verdicts_are_memoized_per_plan(monkeypatch):
    """The leader's verdict is consulted on every improvement event, so it must be cached."""
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_CS_CHECK_BUDGET", "40")
    agent, calls = _bare_solve_agent(**_unaccepted_stream(), max_restarts=8)

    agent._solve({"uid": "u1"})

    # Two distinct plan objects are recycled across ~10 build calls; each may be evaluated once.
    assert calls["commonsense_ok"] <= 2


def test_malformed_check_budget_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_CS_CHECK_BUDGET", "not-a-number")
    agent, _ = _bare_solve_agent(**_unaccepted_stream())

    assert agent._solve({"uid": "u1"}) is VALID


def test_timeout_recovery_export_prefers_the_commonsense_valid_plan(monkeypatch):
    """A timeout must recover the same quality of plan the full solve would have emitted."""
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent, calls = _bare_solve_agent(**_unaccepted_stream())

    agent._solve({"uid": "u1"})

    assert calls["recovery"][-1] == "commonsense-valid"


def test_timeout_recovery_export_unchanged_when_flag_off():
    agent, calls = _bare_solve_agent(**_unaccepted_stream())

    agent._solve({"uid": "u1"})

    assert set(calls["recovery"]) == {"leader"}


def test_commonsense_probe_failure_degrades_to_the_leader(monkeypatch):
    """A raising evaluator must not crash or silently promote an unvalidated plan."""
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent, _ = _bare_solve_agent(**_unaccepted_stream())

    def boom(query, plan):
        raise RuntimeError("evaluator exploded")

    agent._commonsense_ok = boom

    assert agent._solve({"uid": "u1"}) is LEADER


# --- structural pre-filter --------------------------------------------------------------------
#
# The official commonsense evaluator costs ~300 ms per call, and inside a wall-clock-bounded solve
# every call is paid for with a restart that does not happen. The pre-filter rejects the candidates
# that cannot pass -- above all the transport-less plan the search leader actually takes on the
# dominant failure family -- for free.


def _agent_for_prefilter():
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent

    return TPCAgent.__new__(TPCAgent)


def test_prefilter_accepts_a_well_formed_plan():
    assert _agent_for_prefilter()._fast_commonsense_prefilter(_plan("ok")) is True


def test_prefilter_rejects_transport_less_position_change():
    """The real shape of the dominant residual: positions change, no legs anywhere."""
    plan = {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "position": "Park", "start_time": "09:00",
                     "end_time": "10:00", "transports": []},
                    {"type": "lunch", "position": "Restaurant", "start_time": "10:00",
                     "end_time": "11:00", "transports": []},
                ]
            }
        ]
    }
    assert _agent_for_prefilter()._fast_commonsense_prefilter(plan) is False


def test_prefilter_rejects_overlapping_activities():
    plan = {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "position": "Park", "start_time": "09:00",
                     "end_time": "11:00", "transports": []},
                    {"type": "attraction", "position": "Park", "start_time": "10:00",
                     "end_time": "12:00", "transports": []},
                ]
            }
        ]
    }
    assert _agent_for_prefilter()._fast_commonsense_prefilter(plan) is False


def test_prefilter_allows_back_to_back_same_position_activities():
    """No stricter than the official checks: touching (not overlapping) activities are fine."""
    plan = {
        "itinerary": [
            {
                "activities": [
                    {"type": "breakfast", "position": "Hotel", "start_time": "08:00",
                     "end_time": "09:00", "transports": []},
                    {"type": "attraction", "position": "Hotel", "start_time": "09:00",
                     "end_time": "10:00", "transports": []},
                ]
            }
        ]
    }
    assert _agent_for_prefilter()._fast_commonsense_prefilter(plan) is True


def test_prefilter_rejects_activity_starting_before_its_leg_arrives():
    plan = {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "position": "Park", "start_time": "09:00",
                     "end_time": "10:00", "transports": []},
                    {"type": "lunch", "position": "Restaurant", "start_time": "10:10",
                     "end_time": "11:00",
                     "transports": [{"start": "Park", "end": "Restaurant",
                                     "start_time": "10:00", "end_time": "10:30"}]},
                ]
            }
        ]
    }
    assert _agent_for_prefilter()._fast_commonsense_prefilter(plan) is False


def test_prefilter_rejects_malformed_plans():
    agent = _agent_for_prefilter()
    assert agent._fast_commonsense_prefilter({}) is False
    assert agent._fast_commonsense_prefilter({"itinerary": []}) is False
    assert agent._fast_commonsense_prefilter({"itinerary": [{"activities": []}]}) is False


def test_prefilter_spends_no_evaluator_call_on_a_hopeless_candidate(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    broken = {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "position": "Park", "start_time": "09:00",
                     "end_time": "10:00", "transports": []},
                    {"type": "lunch", "position": "Restaurant", "start_time": "10:00",
                     "end_time": "11:00", "transports": []},
                ]
            }
        ]
    }
    agent, calls = _bare_solve_agent(
        plans=[broken],
        passed_by_plan={"Park": 1},
        commonsense_ok_plans=set(),
    )

    agent._solve({"uid": "u1"})

    assert calls["commonsense_ok"] == 0


def test_probe_time_cap_stops_confirmations(monkeypatch):
    """A slow evaluator must not eat the solve budget: the time cap ends probing."""
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_CS_CHECK_TIME_FRAC", "0")  # no time allowed for confirmations
    agent, calls = _bare_solve_agent(**_unaccepted_stream())

    plan = agent._solve({"uid": "u1"})

    assert plan is LEADER
    assert calls["commonsense_ok"] == 0
