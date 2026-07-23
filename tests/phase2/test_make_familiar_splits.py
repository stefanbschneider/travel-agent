"""Tests for the familiar-100 val/test split helper (scripts/make_familiar_splits.py).

The split is stratified by trip ``days``. Includes a guard that the *committed* split files still
partition the committed familiar-100 split 80/20, disjointly, and with the frozen stratified seed --
if someone regenerates them with a different seed/size/key or edits a file by hand, this fails
loudly (the held-out test set is supposed to stay frozen).
"""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

import make_familiar_splits as mfs
from make_phase2_splits import read_split

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Synthetic strata for the tmp-path tests: 100 uids across 4 day-length strata of uneven size
# (33/27/24/16), so 20% apportionment has real fractional remainders to exercise.
SYNTH_UIDS = [f"phase2_familiar_{i:05d}" for i in range(100)]
_SYNTH_SIZES = {2: 33, 3: 27, 4: 24, 5: 16}
SYNTH_STRATA = {}
_i = 0
for _stratum, _size in _SYNTH_SIZES.items():
    for _ in range(_size):
        SYNTH_STRATA[SYNTH_UIDS[_i]] = _stratum
        _i += 1


def test_stratified_split_is_deterministic_and_exact():
    val_a, test_a = mfs.stratified_split(SYNTH_UIDS, SYNTH_STRATA, test_size=20, seed=7)
    val_b, test_b = mfs.stratified_split(SYNTH_UIDS, SYNTH_STRATA, test_size=20, seed=7)
    assert (val_a, test_a) == (val_b, test_b)
    assert len(test_a) == 20 and len(val_a) == 80
    assert set(val_a).isdisjoint(test_a)
    assert set(val_a) | set(test_a) == set(SYNTH_UIDS)


def test_stratified_split_balances_each_stratum():
    import math

    _, test = mfs.stratified_split(SYNTH_UIDS, SYNTH_STRATA, test_size=20, seed=7)
    per = collections.Counter(SYNTH_STRATA[u] for u in test)
    assert sum(per.values()) == 20
    # Each stratum's test count is its 20% share rounded to an adjacent integer (largest remainder).
    for stratum, size in _SYNTH_SIZES.items():
        ideal = size * 20 / 100
        assert math.floor(ideal) <= per[stratum] <= math.ceil(ideal), (stratum, ideal, per[stratum])


def test_stratified_split_changes_with_seed():
    _, test_a = mfs.stratified_split(SYNTH_UIDS, SYNTH_STRATA, test_size=20, seed=1)
    _, test_b = mfs.stratified_split(SYNTH_UIDS, SYNTH_STRATA, test_size=20, seed=2)
    assert test_a != test_b  # different members...
    assert collections.Counter(SYNTH_STRATA[u] for u in test_a) == \
        collections.Counter(SYNTH_STRATA[u] for u in test_b)  # ...same per-stratum counts


def test_write_familiar_splits_idempotent_without_force(tmp_path):
    created1 = mfs.write_familiar_splits(SYNTH_UIDS, SYNTH_STRATA, out_dir=tmp_path, force=False)
    assert created1 is True
    test_path = tmp_path / f"{mfs.TEST_NAME}.txt"
    assert (tmp_path / f"{mfs.VAL_NAME}.txt").exists() and test_path.exists()
    original = test_path.read_text(encoding="utf-8")

    created2 = mfs.write_familiar_splits(SYNTH_UIDS, SYNTH_STRATA, out_dir=tmp_path, seed=999,
                                         force=False)
    assert created2 is False  # frozen: not overwritten without force
    assert test_path.read_text(encoding="utf-8") == original


def test_write_familiar_splits_raises_on_partial_state(tmp_path):
    mfs.write_familiar_splits(SYNTH_UIDS, SYNTH_STRATA, out_dir=tmp_path, force=False)
    (tmp_path / f"{mfs.TEST_NAME}.txt").unlink()  # simulate a broken/partial split
    with pytest.raises(RuntimeError):
        mfs.write_familiar_splits(SYNTH_UIDS, SYNTH_STRATA, out_dir=tmp_path, force=False)
    assert mfs.write_familiar_splits(SYNTH_UIDS, SYNTH_STRATA, out_dir=tmp_path, force=True) is True
    assert (tmp_path / f"{mfs.TEST_NAME}.txt").exists()


def test_committed_familiar_splits_partition_the_committed_source():
    """The committed val/test files must be a disjoint, covering 80/20 partition of familiar-100."""
    full = set(read_split("tpc_phase2_familiar_100"))
    val = set(read_split("tpc_phase2_familiar_100_val"))
    test = set(read_split("tpc_phase2_familiar_100_test"))
    assert len(full) == 100 and len(val) == 80 and len(test) == 20
    assert val.isdisjoint(test)
    assert val | test == full


def test_committed_familiar_splits_match_the_frozen_stratified_seed():
    """Regenerating with the frozen defaults + real strata reproduces the committed files exactly."""
    uids = read_split("tpc_phase2_familiar_100")
    strata = mfs.load_strata(uids)
    val_list, test_list = mfs.stratified_split(
        uids, strata, test_size=mfs.DEFAULT_TEST_SIZE, seed=mfs.DEFAULT_SEED
    )
    assert val_list == read_split("tpc_phase2_familiar_100_val")
    assert test_list == read_split("tpc_phase2_familiar_100_test")


def test_committed_test_split_is_stratified_by_days():
    """Each day-length stratum contributes ~20% (+-1 record) to the held-out test split."""
    uids = read_split("tpc_phase2_familiar_100")
    strata = mfs.load_strata(uids)
    test = set(read_split("tpc_phase2_familiar_100_test"))
    full_mix = collections.Counter(strata[u] for u in uids)
    test_mix = collections.Counter(strata[u] for u in test)
    for stratum, total in full_mix.items():
        expected = round(0.2 * total)
        assert abs(test_mix.get(stratum, 0) - expected) <= 1, (stratum, total, test_mix.get(stratum))
