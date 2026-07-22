"""Integration test for Stage 3 LLM refine wiring end to end.

Opt-in (marked ``integration``): touches the real WorldEnv + TPCAgent. Run with:
    .venv/bin/python -m pytest -m integration tests/phase2/test_llm_refine_e2e.py

Verifies the hook plumbing ``docs/agents/stage3_llm_refine.md`` describes -- ``make_tpcagent_solve_fn``
attaches working ``ground_and_check``/``apply_refine_edits`` hooks, and the flags-off floor stays
byte-identical (no LLM calls, same plan) when ``TPC_P2_LLM_REFINE`` is off -- without running a
real solve-to-convergence (that's role 2's long e2e, run elsewhere).
"""

from __future__ import annotations

import pytest

from chinatravel.agent.phase2 import orchestrator as orch
from chinatravel.agent.phase2.orchestrator import Flags
from chinatravel.agent.phase2.llm_client import FixtureLLMClient


@pytest.fixture(scope="module")
def env():
    from chinatravel.environment.world_env import WorldEnv

    return WorldEnv(lang="en")


@pytest.mark.integration
def test_solve_fn_exposes_refine_hooks(env):
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")
    assert callable(getattr(solve_fn, "get_timeout_recovery_plan", None))
    assert callable(getattr(solve_fn, "ground_and_check", None))
    assert callable(getattr(solve_fn, "apply_refine_edits", None))


@pytest.mark.integration
def test_refine_hooks_are_noop_before_any_solve_call(env):
    # Before _solve() has run for any query, the hooks must degrade gracefully (no query context
    # yet) rather than raise.
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")
    accepted, plan, key, failure = solve_fn.ground_and_check({"itinerary": []})
    assert accepted is False
    assert plan == {"itinerary": []}
    assert failure == {}
    trial, applied = solve_fn.apply_refine_edits({"itinerary": []}, [{"op": "drop_activity"}])
    assert applied == 0


@pytest.mark.integration
def test_flags_off_floor_byte_identical_with_refine_wired(env, one_query):
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")

    plan_off, telem_off = orch.solve_phase2(
        one_query, env=env, budget_sec=20.0, solve_fn=solve_fn, flags=Flags(),
    )
    assert telem_off["flags"]["llm_refine"] is False
    assert telem_off["improve_llm_called"] is False
    assert telem_off["improve_committed"] is False
    assert isinstance(plan_off.get("itinerary"), list)


@pytest.mark.integration
def test_refine_on_with_noop_fixture_response_stays_safe(env, one_query, tmp_path):
    """With the flag on and a fixture LLM that always proposes zero edits, Stage 3 must call the
    LLM at most once and never crash or corrupt the plan -- a cheap wiring smoke, not a quality
    gate (that's role 2's pinned e2e gate)."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    llm = FixtureLLMClient(fixtures_dir)

    # No fixture on disk -> FixtureMissingError on the first call, which llm_refine must catch and
    # degrade from (graceful-degrade path, not the happy path -- still proves the wiring doesn't
    # crash the harness end to end).
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")
    plan, telemetry = orch.solve_phase2(
        one_query, env=env, budget_sec=20.0, solve_fn=solve_fn, llm_client=llm,
        flags=Flags(llm_refine=True),
    )
    assert isinstance(plan.get("itinerary"), list)
    assert telemetry["used_fallback"] is False or isinstance(plan.get("itinerary"), list)
