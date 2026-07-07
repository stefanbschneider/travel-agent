"""Tests for the Phase 2 per-query time budgeting (Task 5)."""

from __future__ import annotations

from chinatravel.agent.phase2 import budget as B


def test_split_budget_positive_slices_sum_to_total():
    b = B.split_budget(100.0)
    assert b.parse_sec > 0 and b.solve_sec > 0 and b.improve_sec > 0 and b.finalize_sec > 0
    total = b.parse_sec + b.solve_sec + b.improve_sec + b.finalize_sec
    assert abs(total - 100.0) < 1e-6


def test_solve_gets_the_largest_slice():
    b = B.split_budget(100.0)
    assert b.solve_sec >= b.parse_sec
    assert b.solve_sec >= b.improve_sec
    assert b.solve_sec >= b.finalize_sec


def test_hard_finalization_buffer_reserved():
    # A comfortably large budget must reserve at least the hard finalization buffer.
    b = B.split_budget(100.0)
    assert b.finalize_sec >= B.MIN_FINALIZE_BUFFER_SEC


def test_tiny_budget_still_reserves_some_finalization():
    b = B.split_budget(0.2)
    assert b.finalize_sec > 0
    assert b.finalize_sec <= 0.2
