"""Tests for the familiar-100 val/test split helper (scripts/make_familiar_splits.py).

Includes a guard that the *committed* split files actually partition the committed familiar-100
split 80/20 and disjointly -- if someone regenerates them with a different seed/size or edits a
file by hand, this fails loudly (the held-out test set is supposed to stay frozen).
"""

from __future__ import annotations

from pathlib import Path

import make_familiar_splits as mfs
from make_phase2_splits import read_split

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPLITS_DIR = PROJECT_ROOT / "chinatravel" / "evaluation" / "default_splits"


def test_write_familiar_splits_idempotent_without_force(tmp_path):
    uids = [f"phase2_familiar_{i:05d}" for i in range(100)]
    created1 = mfs.write_familiar_splits(uids, out_dir=tmp_path, force=False)
    assert created1 is True
    val_path = tmp_path / f"{mfs.VAL_NAME}.txt"
    test_path = tmp_path / f"{mfs.TEST_NAME}.txt"
    assert val_path.exists() and test_path.exists()
    original = test_path.read_text(encoding="utf-8")

    created2 = mfs.write_familiar_splits(uids, out_dir=tmp_path, seed=999, force=False)
    assert created2 is False  # frozen: not overwritten without force
    assert test_path.read_text(encoding="utf-8") == original


def test_write_familiar_splits_raises_on_partial_state(tmp_path):
    import pytest

    uids = [f"phase2_familiar_{i:05d}" for i in range(100)]
    mfs.write_familiar_splits(uids, out_dir=tmp_path, force=False)
    # Delete one file to simulate a broken/partial split; a plain rerun must fail loudly.
    (tmp_path / f"{mfs.TEST_NAME}.txt").unlink()
    with pytest.raises(RuntimeError):
        mfs.write_familiar_splits(uids, out_dir=tmp_path, force=False)
    # force=True rewrites both cleanly.
    assert mfs.write_familiar_splits(uids, out_dir=tmp_path, force=True) is True
    assert (tmp_path / f"{mfs.TEST_NAME}.txt").exists()


def test_write_familiar_splits_default_is_80_20(tmp_path):
    uids = [f"phase2_familiar_{i:05d}" for i in range(100)]
    mfs.write_familiar_splits(uids, out_dir=tmp_path, force=False)
    val = (tmp_path / f"{mfs.VAL_NAME}.txt").read_text().split()
    test = (tmp_path / f"{mfs.TEST_NAME}.txt").read_text().split()
    assert len(val) == 80
    assert len(test) == 20
    assert set(val).isdisjoint(set(test))
    assert set(val) | set(test) == set(uids)


def test_committed_familiar_splits_partition_the_committed_source():
    """The committed val/test files must be a disjoint, covering 80/20 partition of familiar-100."""
    full = set(read_split("tpc_phase2_familiar_100"))
    val = set(read_split("tpc_phase2_familiar_100_val"))
    test = set(read_split("tpc_phase2_familiar_100_test"))
    assert len(full) == 100
    assert len(val) == 80
    assert len(test) == 20
    assert val.isdisjoint(test)
    assert val | test == full


def test_committed_familiar_splits_match_the_frozen_seed():
    """Regenerating with the frozen defaults reproduces exactly the committed files."""
    uids = read_split("tpc_phase2_familiar_100")
    from make_phase2_splits import make_splits
    val_list, test_list = make_splits(uids, test_size=mfs.DEFAULT_TEST_SIZE, seed=mfs.DEFAULT_SEED)
    assert val_list == read_split("tpc_phase2_familiar_100_val")
    assert test_list == read_split("tpc_phase2_familiar_100_test")
