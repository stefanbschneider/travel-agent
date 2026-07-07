"""Unit tests for the TPCAgent variant-injection seam (Task 4).

The harness owns parsing: when ``agent._injected_variants`` is a non-empty list, the agent must use
it directly instead of re-parsing the query. When it is ``None`` or empty, behavior is unchanged
(byte-identical to the internal no-oracle parse).

These are fast unit tests: they build a *bare* TPCAgent via ``__new__`` and exercise only
``_constraint_variants`` / ``_collect_constraints`` — no WorldEnv, LLM, or filesystem.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The TPCAgent module uses internal ``from agent.base import ...`` imports, which require the
# ``chinatravel`` directory on sys.path (the app adds it lazily via chinatravel.evaluation.*).
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import parse_constraints  # noqa: E402
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants  # noqa: E402

EN_DATA_DIR = PROJECT_ROOT / "chinatravel" / "data" / "en" / "TPC_IJCAI_2026_phase1_EN"
SPLIT_FILE = PROJECT_ROOT / "chinatravel" / "evaluation" / "default_splits" / "tpc_phase1.txt"


def _bare_agent(use_oracle=False):
    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent

    agent = TPCAgent.__new__(TPCAgent)  # skip heavy __init__ (WorldEnv/LLM/log dir)
    agent.use_oracle = use_oracle
    agent._injected_variants = None
    return agent


@pytest.fixture(scope="module")
def a_query():
    uid = next(
        u for u in SPLIT_FILE.read_text(encoding="utf-8").split()
        if (EN_DATA_DIR / f"{u}.json").exists()
    )
    q = json.loads((EN_DATA_DIR / f"{uid}.json").read_text(encoding="utf-8"))
    q.setdefault("uid", uid)
    return q


def test_no_injection_matches_internal_parse(a_query):
    agent = _bare_agent(use_oracle=False)
    baseline = solver_constraint_variants(
        a_query, parse_constraints.parse_query_no_oracle(a_query), use_oracle=False
    )
    assert agent._constraint_variants(a_query) == baseline


def test_injected_variants_are_used_verbatim(a_query):
    agent = _bare_agent(use_oracle=False)
    sentinel = [{"required_attractions": ["A"]}, {"required_attraction_types": ["park"]}]
    agent._injected_variants = sentinel
    assert agent._constraint_variants(a_query) is sentinel
    # _collect_constraints picks the first variant.
    assert agent._collect_constraints(a_query) == sentinel[0]


def test_empty_injection_falls_back_to_internal_parse(a_query):
    agent = _bare_agent(use_oracle=False)
    baseline = agent._constraint_variants(a_query)  # None -> internal parse
    agent._injected_variants = []
    assert agent._constraint_variants(a_query) == baseline
    agent._injected_variants = None
    assert agent._constraint_variants(a_query) == baseline
