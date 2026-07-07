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
