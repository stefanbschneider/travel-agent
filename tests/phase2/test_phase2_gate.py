"""Unit tests for the Phase 2 regression gate.

A change is promoted only if its primary score does not drop and its parse-failure or timeout
counts do not increase versus the baseline.
"""

from __future__ import annotations

import phase2_gate as G


BASE = {"fpr": 90.0, "parse_failures": 3, "timeouts": 1}


def test_gate_passes_when_equal():
    res = G.check_gate(BASE, dict(BASE))
    assert res["passed"] is True
    assert res["reasons"] == []


def test_gate_passes_when_better():
    cand = {"fpr": 92.0, "parse_failures": 2, "timeouts": 0}
    assert G.check_gate(BASE, cand)["passed"] is True


def test_gate_fails_on_score_drop():
    cand = {"fpr": 88.0, "parse_failures": 3, "timeouts": 1}
    res = G.check_gate(BASE, cand)
    assert res["passed"] is False
    assert any("fpr" in r.lower() or "score" in r.lower() for r in res["reasons"])


def test_gate_fails_on_more_parse_failures():
    cand = {"fpr": 90.0, "parse_failures": 5, "timeouts": 1}
    res = G.check_gate(BASE, cand)
    assert res["passed"] is False
    assert any("parse" in r.lower() for r in res["reasons"])


def test_gate_fails_on_more_timeouts():
    cand = {"fpr": 90.0, "parse_failures": 3, "timeouts": 4}
    res = G.check_gate(BASE, cand)
    assert res["passed"] is False
    assert any("timeout" in r.lower() for r in res["reasons"])


def test_gate_tolerance_allows_tiny_score_dip():
    cand = {"fpr": 89.95, "parse_failures": 3, "timeouts": 1}
    assert G.check_gate(BASE, cand, tol=0.1)["passed"] is True


# --- continuous_score is primary when both rows provide it; FPR remains advisory ------------

BASE_CS = {"fpr": 82.35, "continuous_score": 86.43, "parse_failures": 0, "timeouts": 0}


def test_gate_uses_continuous_score_when_present_and_ignores_fpr_drop():
    """A large FPR drop must not fail the gate when continuous_score improves -- FPR is
    advisory-only once continuous_score is available in both rows."""
    cand = {"fpr": 56.47, "continuous_score": 88.20, "parse_failures": 0, "timeouts": 0}
    res = G.check_gate(BASE_CS, cand)
    assert res["passed"] is True
    assert res["reasons"] == []
    assert any("fpr" in a.lower() for a in res["advisories"])


def test_gate_fails_on_continuous_score_drop_even_if_fpr_improves():
    cand = {"fpr": 95.0, "continuous_score": 80.0, "parse_failures": 0, "timeouts": 0}
    res = G.check_gate(BASE_CS, cand)
    assert res["passed"] is False
    assert any("continuous_score" in r.lower() for r in res["reasons"])


def test_gate_continuous_score_tolerance_allows_tiny_dip():
    cand = {"fpr": 82.35, "continuous_score": 86.40, "parse_failures": 0, "timeouts": 0}
    assert G.check_gate(BASE_CS, cand, tol=0.1)["passed"] is True


def test_gate_falls_back_to_fpr_when_continuous_score_absent_from_either_row():
    """Backward compatibility: rows recorded before this field existed (or a candidate missing
    it) must gate on fpr exactly as before -- BASE has no continuous_score."""
    cand = {"fpr": 88.0, "parse_failures": 3, "timeouts": 1}
    res = G.check_gate(BASE, cand)
    assert res["passed"] is False
    assert any("fpr" in r.lower() or "score" in r.lower() for r in res["reasons"])
    assert res["advisories"] == []


def test_gate_reasons_and_advisories_keys_always_present():
    res = G.check_gate(BASE, dict(BASE))
    assert "reasons" in res and "advisories" in res


# --- evaluator_parity: refuse to compare rows straddling the 2026-07-28 evaluator sync -------


def test_gate_refuses_when_evaluator_parity_differs():
    base = {**BASE, "evaluator_parity": "764614c"}
    cand = {"fpr": 99.0, "parse_failures": 0, "timeouts": 0, "evaluator_parity": "old-sha"}
    res = G.check_gate(base, cand)
    assert res["passed"] is False
    assert any("evaluator_parity" in r for r in res["reasons"])


def test_gate_refuses_when_only_one_side_carries_evaluator_parity():
    """A pre-sync row never carries the marker; a post-sync row always does. One-sided presence
    is exactly the accidental-cross-boundary-comparison shape this guard exists to catch."""
    base = dict(BASE)  # no marker -- looks like a pre-sync row
    cand = {**BASE, "fpr": 99.0, "evaluator_parity": "764614c"}
    res = G.check_gate(base, cand)
    assert res["passed"] is False
    assert any("evaluator_parity" in r for r in res["reasons"])


def test_gate_allows_comparison_when_both_sides_omit_evaluator_parity():
    """Backward compatibility: every row recorded before this marker existed lacks it on both
    sides, and must keep gating exactly as before."""
    cand = {"fpr": 92.0, "parse_failures": 2, "timeouts": 0}
    assert G.check_gate(BASE, cand)["passed"] is True


def test_gate_allows_comparison_when_evaluator_parity_matches():
    base = {**BASE, "evaluator_parity": "764614c"}
    cand = {"fpr": 92.0, "parse_failures": 2, "timeouts": 0, "evaluator_parity": "764614c"}
    assert G.check_gate(base, cand)["passed"] is True
