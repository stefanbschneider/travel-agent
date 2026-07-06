"""Tests for true no-oracle disjunctive branch generation (TPC_P2_DISJUNCTION).

When the flag is ON, a disjunctive ("satisfy either A or B") query must expand into one
branch-local solver variant per OR arm — mirroring the oracle path — instead of collapsing both
arms into a single over-constrained ("A and B") variant.

When the flag is OFF, the output must stay byte-identical to the current no-oracle baseline.

Fixtures anchor on *real* disjunctive queries: uids where the oracle emits >1 branch AND the
deterministic NL detector recognizes the disjunction (the ~90 NL-undetectable ones are the
deferred LLM-assist territory and are intentionally out of scope here).
"""

from __future__ import annotations

import json

import pytest

import parse_constraints
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2.orchestrator import Flags

# Reuse the parser-vs-oracle diff core for the disjunction-flattening assertion.
import parser_vs_oracle as pvo

_MAX_DISJUNCTIVE = 6


def _present(value) -> bool:
    return value not in (None, [], {}, "", ())


def _families(d: dict) -> set:
    return {k for k, v in d.items() if _present(v)}


def _baseline_variants(query):
    raw = parse_constraints.parse_query_no_oracle(query)
    return solver_constraint_variants(query, raw, use_oracle=False)


def _oracle_variants(query):
    return solver_constraint_variants(query, parse_constraints.parse_query(query), use_oracle=True)


def _recoverable_arms(query) -> list[dict]:
    """Deterministically recoverable OR arms: >=2 arms that each parse to a non-empty constraint.

    Queries with an arm the no-oracle parser cannot resolve (e.g. an unlisted attraction name) are
    out of scope here — they are the deferred LLM-assist territory — so they are excluded from the
    fixture rather than asserted on.
    """
    text = query.get("nature_language", "") or ""
    if not parse_constraints.detect_disjunctive(text):
        return []
    groups = parse_constraints.split_disjunctive_groups(text)
    if not groups or len(groups) < 2:
        return []
    arms = [parse_constraints.parse_single_constraint_text(g) for g in groups]
    return [a for a in arms if a]


@pytest.fixture(scope="module")
def disjunctive_queries(all_phase1_uids):
    """Real queries that are disjunctive (oracle >1 branch) AND deterministically recoverable.

    "Recoverable" = NL-detectable disjunction that splits into >=2 arms, each parsing to a
    non-empty constraint dict. These are exactly the queries the deterministic no-oracle path is
    expected to expand correctly.
    """
    from tests.phase2.conftest import EN_DATA_DIR  # local data dir

    found: dict[str, dict] = {}
    for uid in all_phase1_uids:
        path = EN_DATA_DIR / f"{uid}.json"
        if not path.exists():
            continue
        q = json.loads(path.read_text(encoding="utf-8"))
        q.setdefault("uid", uid)
        try:
            oracle = _oracle_variants(q)
        except Exception:
            continue
        if len(oracle) <= 1:
            continue
        if len(_recoverable_arms(q)) < 2:
            continue
        found[uid] = q
        if len(found) >= _MAX_DISJUNCTIVE:
            break
    if not found:
        pytest.skip("No deterministically-recoverable disjunctive tpc_phase1 queries found locally.")
    return found


def test_flag_on_expands_to_one_variant_per_branch(disjunctive_queries):
    flags = Flags(disjunction=True)
    for uid, q in disjunctive_queries.items():
        oracle = _oracle_variants(q)
        ir = normalize.parse_to_ir(q, flags=flags)
        got = normalize.ir_to_solver_variants(ir, q, flags=flags)
        assert len(got) == len(oracle), (
            f"{uid}: expected {len(oracle)} branch variants, got {len(got)}"
        )


def test_flag_on_no_disjunction_flattening(disjunctive_queries):
    flags = Flags(disjunction=True)
    for uid, q in disjunctive_queries.items():
        oracle = _oracle_variants(q)
        ir = normalize.parse_to_ir(q, flags=flags)
        got = normalize.ir_to_solver_variants(ir, q, flags=flags)
        dv = pvo.diff_variants(parsed_variants=got, oracle_variants=oracle)
        assert dv["disjunction_flattened"] is False, f"{uid}: disjunction still flattened"


def test_flag_on_each_branch_carries_a_local_constraint(disjunctive_queries):
    """Every expanded branch must carry >=1 branch-local family.

    A vacuous (base-only) branch would make the whole disjunction trivially satisfiable and
    over-permissive. This asserts the disjunction *structure* is sound; it deliberately does not
    assert the no-oracle NL parser categorizes each family identically to the oracle DSL parser
    (per-field NL parsing accuracy is a separate concern / a later effort).
    """
    from chinatravel.agent.tpc_agent.solver_constraints import _BRANCH_LOCAL_KEYS

    flags = Flags(disjunction=True)
    for uid, q in disjunctive_queries.items():
        ir = normalize.parse_to_ir(q, flags=flags)
        got = normalize.ir_to_solver_variants(ir, q, flags=flags)
        for i, v in enumerate(got):
            local = {k for k in _families(v) if k in _BRANCH_LOCAL_KEYS}
            assert local, f"{uid}: branch {i} has no branch-local constraint (vacuous branch)"


def test_flag_on_no_cross_arm_contamination(disjunctive_queries):
    """A branch-local constraint from one arm must not leak into every other arm.

    For a genuinely disjunctive query the arms differ, so the parsed variants must not all be
    identical (that would mean both arms were merged / flattened).
    """
    flags = Flags(disjunction=True)
    for uid, q in disjunctive_queries.items():
        ir = normalize.parse_to_ir(q, flags=flags)
        got = normalize.ir_to_solver_variants(ir, q, flags=flags)
        if len(got) < 2:
            continue
        assert any(got[0] != v for v in got[1:]), (
            f"{uid}: all parsed branches identical — arms were flattened together"
        )


def test_flag_off_byte_identical(disjunctive_queries):
    off = Flags()
    for uid, q in disjunctive_queries.items():
        ir = normalize.parse_to_ir(q, flags=off)
        got = normalize.ir_to_solver_variants(ir, q, flags=off)
        assert got == _baseline_variants(q), f"{uid}: flag-off output changed"


def test_flag_off_single_variant(disjunctive_queries):
    """Flag OFF keeps the current behavior: exactly one (flattened) variant."""
    off = Flags()
    for uid, q in disjunctive_queries.items():
        ir = normalize.parse_to_ir(q, flags=off)
        got = normalize.ir_to_solver_variants(ir, q, flags=off)
        assert len(got) == 1, f"{uid}: flag-off produced {len(got)} variants"
