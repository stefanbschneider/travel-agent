"""Unit tests for the Phase 2 regression gate (Task 10).

A change is promoted only if, on the fold, it does not drop official score (FPR) or increase
parse-failure / timeout counts vs the baseline.
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


# --- continuous_score as primary metric (2026-07-14: FPR found noise-dominated at repeats=2 on
# a tight budget -- see docs/tpc_phase2_plan3.md's "Next steps" section) -------------------------

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
