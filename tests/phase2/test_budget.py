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


def test_dynamic_solve_sec_gives_unused_parse_time_to_solve():
    b = B.split_budget(300.0)  # solve_sec=165, parse_sec=75, improve_sec=30, finalize_sec=30
    got = B.dynamic_solve_sec(b, elapsed_sec=2.0, improve_reserved=False)
    # total - elapsed - finalize - 0 improve reserve = 300 - 2 - 30 = 268
    assert abs(got - 268.0) < 1e-6
    assert got > b.solve_sec


def test_dynamic_solve_sec_withholds_improve_reserve_when_llm_refine_on():
    b = B.split_budget(300.0)
    got = B.dynamic_solve_sec(b, elapsed_sec=2.0, improve_reserved=True)
    # total - elapsed - finalize - improve_sec = 300 - 2 - 30 - 30 = 238
    assert abs(got - 238.0) < 1e-6


def test_dynamic_solve_sec_never_goes_below_static_floor():
    b = B.split_budget(300.0)
    # A slow parse that ate almost the whole budget must not shrink solve below the static slice.
    got = B.dynamic_solve_sec(b, elapsed_sec=290.0, improve_reserved=False)
    assert got == b.solve_sec
