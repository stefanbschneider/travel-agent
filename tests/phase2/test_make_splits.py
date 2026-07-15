"""Tests for the Phase 2 validation and held-out-test split helper."""

from __future__ import annotations

import make_phase2_splits as mps


UIDS = [f"uid{i:04d}" for i in range(1000)]


def test_split_is_deterministic_for_same_seed():
    val_a, test_a = mps.make_splits(UIDS, test_size=150, seed=42)
    val_b, test_b = mps.make_splits(UIDS, test_size=150, seed=42)
    assert val_a == val_b
    assert test_a == test_b


def test_split_changes_with_seed():
    _, test_a = mps.make_splits(UIDS, test_size=150, seed=1)
    _, test_b = mps.make_splits(UIDS, test_size=150, seed=2)
    assert test_a != test_b


def test_split_partitions_all_uids_disjointly():
    val, test = mps.make_splits(UIDS, test_size=150, seed=7)
    assert len(test) == 150
    assert len(val) == 850
    assert set(val).isdisjoint(set(test))
    assert set(val) | set(test) == set(UIDS)


def test_split_output_is_sorted_and_stable():
    val, test = mps.make_splits(UIDS, test_size=150, seed=7)
    # Files are written in a stable (sorted) order regardless of shuffle order.
    assert val == sorted(val)
    assert test == sorted(test)


def test_write_splits_idempotent_without_force(tmp_path):
    out_dir = tmp_path
    created1 = mps.write_splits(UIDS, out_dir=out_dir, test_size=150, seed=7, force=False)
    assert created1 is True
    val_path = out_dir / "tpc_phase2_val.txt"
    test_path = out_dir / "tpc_phase2_test.txt"
    assert val_path.exists() and test_path.exists()
    original = test_path.read_text(encoding="utf-8")

    # Second call without force must not overwrite.
    created2 = mps.write_splits(UIDS, out_dir=out_dir, test_size=150, seed=999, force=False)
    assert created2 is False
    assert test_path.read_text(encoding="utf-8") == original


def test_write_splits_force_overwrites(tmp_path):
    out_dir = tmp_path
    mps.write_splits(UIDS, out_dir=out_dir, test_size=150, seed=7, force=False)
    test_path = out_dir / "tpc_phase2_test.txt"
    before = test_path.read_text(encoding="utf-8")
    mps.write_splits(UIDS, out_dir=out_dir, test_size=150, seed=999, force=True)
    after = test_path.read_text(encoding="utf-8")
    assert before != after
