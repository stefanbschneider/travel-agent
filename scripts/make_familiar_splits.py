#!/usr/bin/env python3
"""Partition the official familiar-100 development set into val / held-out-test splits.

The organizers' `tpc_phase2_familiar_100` set (100 records, drawn from the final distribution) is
our preferred development signal. To avoid overfitting *it* the way we could overfit any set we
tune on repeatedly, we split it once, deterministically, into:

- `tpc_phase2_familiar_100_val`  (80 records) — the split every screen and development gate runs on;
- `tpc_phase2_familiar_100_test` (20 records) — held out, touched only as an occasional overfitting
  tripwire (e.g. before a submission), never as a per-change signal.

The full `tpc_phase2_familiar_100` split file stays in place for backward comparison with the
already-committed 100-record baselines; new development rows use the val split.

The split is **stratified by trip length (`days`)** so val and test carry the same day-count mix --
day count is the strongest available difficulty signal on familiar-100 (`days` spans 1..5 with real
spread; the `hard_logic_py` clause count is a narrow `9..13` and barely discriminates), and it drives
solve difficulty and timeout rate, so balancing it makes a val gain more likely to carry to test.
Within each `days` stratum the choice is a seeded shuffle, and the overall test size is apportioned
across strata by largest remainder, so the split is deterministic and stable for a given seed and the
files are sorted for a stable diff. **The 20-record test set is still a coarse, high-variance
tripwire, not a precise estimate** -- stratification narrows the val↔test distribution gap but cannot
manufacture precision from 20 records; the organizer's final held-out set (unavailable locally)
remains the only true generalization measure (see docs/tpc_phase2_eval.md).

Idempotent: existing files are not overwritten unless `--force` is given, so the held-out test set
stays frozen once created.

Usage:
    python scripts/make_familiar_splits.py                 # create if missing
    python scripts/make_familiar_splits.py --force         # regenerate (breaks the freeze!)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from make_phase2_splits import DEFAULT_SPLITS_DIR, _write_lines, read_split  # noqa: E402

SOURCE_SPLIT = "tpc_phase2_familiar_100"
VAL_NAME = "tpc_phase2_familiar_100_val"
TEST_NAME = "tpc_phase2_familiar_100_test"
FAMILIAR_DATA_DIR = (
    PROJECT_ROOT / "chinatravel" / "data" / "en" / "TPC_IJCAI_2026_phase2_familiar_100_data"
)
DEFAULT_TEST_SIZE = 20  # 20% of the 100-record familiar set
DEFAULT_SEED = 20260723
STRATIFY_KEY = "days"  # trip length: the strongest available difficulty signal on familiar-100


def load_strata(uids: list[str], *, key: str = STRATIFY_KEY,
                data_dir: Path = FAMILIAR_DATA_DIR) -> dict[str, object]:
    """Map each uid to its stratum value (default: trip ``days``) from the familiar data files."""
    strata: dict[str, object] = {}
    wanted = set(uids)
    for f in data_dir.glob("*.json"):
        if f.name == "_provenance.json":
            continue
        uid = f.stem
        if uid not in wanted:
            continue
        strata[uid] = json.loads(f.read_text(encoding="utf-8")).get(key)
    missing = wanted - set(strata)
    if missing:
        raise RuntimeError(f"No stratum value for {len(missing)} uid(s), e.g. {sorted(missing)[:3]}")
    return strata


def stratified_split(
    uids: list[str], strata: dict[str, object], *, test_size: int, seed: int
) -> tuple[list[str], list[str]]:
    """Return ``(val, test)`` uid lists, stratified by ``strata[uid]``.

    Deterministic for a given ``seed``: each stratum is seeded-shuffled and the total ``test_size``
    is apportioned across strata by the largest-remainder method (so per-stratum test counts sum to
    exactly ``test_size`` and track each stratum's share). Output lists are sorted for stable files.
    """
    unique = sorted(set(uids))
    if test_size < 0 or test_size > len(unique):
        raise ValueError(f"test_size {test_size} out of range for {len(unique)} uids")
    groups: dict[object, list[str]] = defaultdict(list)
    for u in unique:
        groups[strata[u]].append(u)
    # Sort strata by key for a deterministic apportionment order (keys are comparable, e.g. ints).
    keys = sorted(groups, key=lambda k: (k is None, k))
    total = len(unique)
    ideal = {k: len(groups[k]) * test_size / total for k in keys}
    alloc = {k: int(ideal[k]) for k in keys}  # floor
    remaining = test_size - sum(alloc.values())
    # Hand out the leftover test slots to the largest fractional remainders (tie-break by key),
    # never exceeding a stratum's size.
    by_remainder = sorted(keys, key=lambda k: (-(ideal[k] - alloc[k]), (k is None, k)))
    i = 0
    while remaining > 0 and any(alloc[k] < len(groups[k]) for k in keys):
        k = by_remainder[i % len(by_remainder)]
        if alloc[k] < len(groups[k]):
            alloc[k] += 1
            remaining -= 1
        i += 1
    rng = random.Random(seed)
    test: set[str] = set()
    for k in keys:
        g = groups[k][:]
        rng.shuffle(g)
        test.update(g[: alloc[k]])
    if len(test) != test_size:  # guard: apportionment must be exact
        raise RuntimeError(f"stratified_split produced {len(test)} test, expected {test_size}")
    val_list = sorted(u for u in unique if u not in test)
    return val_list, sorted(test)


def write_familiar_splits(
    uids: list[str],
    strata: dict[str, object],
    *,
    out_dir: Path = DEFAULT_SPLITS_DIR,
    test_size: int = DEFAULT_TEST_SIZE,
    seed: int = DEFAULT_SEED,
    force: bool = False,
) -> bool:
    """Write the familiar val/test split files. Returns True if written, False if skipped.

    Idempotent unless ``force``: if *both* targets already exist and ``force`` is False, nothing is
    written (keeps the held-out familiar test set frozen). If exactly one exists, the split is in a
    broken/partial state (interrupted write, bad merge, manual deletion) -- raise rather than
    silently leave it half-written or claim it is complete; pass ``force=True`` to rewrite both.
    """
    out_dir = Path(out_dir)
    val_path = out_dir / f"{VAL_NAME}.txt"
    test_path = out_dir / f"{TEST_NAME}.txt"
    if not force:
        if val_path.exists() and test_path.exists():
            return False
        if val_path.exists() != test_path.exists():
            present = val_path if val_path.exists() else test_path
            missing = test_path if val_path.exists() else val_path
            raise RuntimeError(
                f"Partial familiar split: {present} exists but {missing} is missing. Refusing to "
                f"leave a half-written split -- rerun with force=True (or `--force`) to rewrite both."
            )
    val_list, test_list = stratified_split(uids, strata, test_size=test_size, seed=seed)
    _write_lines(val_path, val_list)
    _write_lines(test_path, test_list)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=SOURCE_SPLIT, help="Source split name to partition.")
    parser.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing split files (breaks the held-out freeze).")
    args = parser.parse_args()

    uids = read_split(args.source)
    strata = load_strata(uids)
    written = write_familiar_splits(
        uids, strata, test_size=args.test_size, seed=args.seed, force=args.force
    )
    val_path = DEFAULT_SPLITS_DIR / f"{VAL_NAME}.txt"
    test_path = DEFAULT_SPLITS_DIR / f"{TEST_NAME}.txt"
    if written:
        val_list, test_list = stratified_split(uids, strata, test_size=args.test_size, seed=args.seed)
        from collections import Counter
        val_mix = dict(sorted(Counter(strata[u] for u in val_list).items()))
        test_mix = dict(sorted(Counter(strata[u] for u in test_list).items()))
        print(f"Wrote {val_path} ({len(val_list)} val) and {test_path} ({len(test_list)} test) "
              f"from {len(uids)} familiar-100 uids, stratified by {STRATIFY_KEY} (seed={args.seed}).")
        print(f"  val  {STRATIFY_KEY} mix: {val_mix}")
        print(f"  test {STRATIFY_KEY} mix: {test_mix}")
    else:
        print(f"Split files already exist; not overwriting without --force:\n"
              f"  {val_path}\n  {test_path}")


if __name__ == "__main__":
    main()
