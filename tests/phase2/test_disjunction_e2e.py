"""Integration test for end-to-end no-oracle disjunction wiring (Task 5).

Opt-in (marked ``integration``): touches the real WorldEnv + TPCAgent. Run with:
    .venv/bin/python -m pytest -m integration tests/phase2/test_disjunction_e2e.py

Verifies that when ``TPC_P2_DISJUNCTION`` is on, the harness expands a recoverable disjunctive
query into >1 branch-local variant and injects them into the agent (telemetry ``variants_count``),
producing a schema-valid plan; and that with the flag off the same query stays a single variant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants
from chinatravel.agent.phase2 import orchestrator as orch
from chinatravel.agent.phase2.orchestrator import Flags

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EN_DATA_DIR = PROJECT_ROOT / "chinatravel" / "data" / "en" / "TPC_IJCAI_2026_phase1_EN"
SPLIT_FILE = PROJECT_ROOT / "chinatravel" / "evaluation" / "default_splits" / "tpc_phase1.txt"


def _recoverable_arm_count(q) -> int:
    text = q.get("nature_language", "") or ""
    if not parse_constraints.detect_disjunctive(text):
        return 0
    groups = parse_constraints.split_disjunctive_groups(text)
    if not groups or len(groups) < 2:
        return 0
    arms = [parse_constraints.parse_single_constraint_text(g) for g in groups]
    return len([a for a in arms if a])


def _find_recoverable_disjunctive_query():
    for uid in SPLIT_FILE.read_text(encoding="utf-8").split():
        path = EN_DATA_DIR / f"{uid}.json"
        if not path.exists():
            continue
        q = json.loads(path.read_text(encoding="utf-8"))
        q.setdefault("uid", uid)
        try:
            oracle = solver_constraint_variants(q, parse_constraints.parse_query(q), use_oracle=True)
        except Exception:
            continue
        if len(oracle) > 1 and _recoverable_arm_count(q) >= 2:
            return q
    return None


@pytest.mark.integration
def test_disjunction_flag_injects_multiple_variants_end_to_end():
    from chinatravel.environment.world_env import WorldEnv

    q = _find_recoverable_disjunctive_query()
    if q is None:
        pytest.skip("No deterministically-recoverable disjunctive query found locally.")

    env = WorldEnv(lang="en")
    solve_fn = orch.make_tpcagent_solve_fn(env, lang="en")

    # Flag ON: harness expands to >1 branch and injects them.
    plan_on, telem_on = orch.solve_phase2(
        q, env=env, budget_sec=30.0, solve_fn=solve_fn, flags=Flags(disjunction=True)
    )
    assert telem_on["variants_count"] > 1, telem_on
    assert isinstance(plan_on.get("itinerary"), list)  # schema-valid floor
    assert telem_on["llm_backend"] == "none"

    # Flag OFF: same query stays a single (flattened) variant.
    plan_off, telem_off = orch.solve_phase2(
        q, env=env, budget_sec=30.0, solve_fn=solve_fn, flags=Flags()
    )
    assert telem_off["variants_count"] == 1, telem_off
    assert isinstance(plan_off.get("itinerary"), list)
