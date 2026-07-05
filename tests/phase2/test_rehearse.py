"""Unit tests for rehearse_phase2 pure helpers (Task 7).

The heavy end-to-end / solver-only runs are exercised via an opt-in integration test; here we test
the deterministic fold selection, the held-out-test guard, and attribution formatting.
"""

from __future__ import annotations

import pytest

import rehearse_phase2 as R


UIDS = [f"uid{i:04d}" for i in range(100)]


def test_select_fold_deterministic():
    a = R.select_fold(UIDS, fold=0, folds=5, seed=1)
    b = R.select_fold(UIDS, fold=0, folds=5, seed=1)
    assert a == b


def test_folds_are_disjoint_and_cover_all():
    seen = []
    for f in range(5):
        seen.extend(R.select_fold(UIDS, fold=f, folds=5, seed=1))
    assert sorted(seen) == sorted(UIDS)
    assert len(seen) == len(set(seen))  # disjoint


def test_select_fold_subset_of_input():
    fold = R.select_fold(UIDS, fold=2, folds=5, seed=1)
    assert set(fold).issubset(set(UIDS))
    assert 0 < len(fold) <= len(UIDS)


def test_resolve_split_set_defaults_to_val():
    name, is_test = R.resolve_split_set("val")
    assert name == "tpc_phase2_val"
    assert is_test is False


def test_resolve_split_set_test_is_flagged(capsys):
    name, is_test = R.resolve_split_set("test")
    assert name == "tpc_phase2_test"
    assert is_test is True
    warning = capsys.readouterr().out.lower()
    assert "held-out" in warning or "warning" in warning


def test_format_attribution_orders_ceiling_solver_e2e():
    line = R.format_attribution(ceiling=95.0, solver_only=90.0, end_to_end=70.0)
    assert "95.0" in line and "90.0" in line and "70.0" in line
    # parsing loss = solver_only - end_to_end; solver headroom = ceiling - solver_only
    assert "20.0" in line  # parsing loss
    assert "5.0" in line   # solver headroom
