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

This is a seeded random 80/20 split, so both files are stable for a given seed and the output is
sorted for a stable diff. **The 20-record test set is a coarse, high-variance tripwire, not a
precise estimate** — the organizer's final held-out set (unavailable locally) remains the only true
generalization measure (see docs/tpc_phase2_eval.md). Stratifying by constraint-family/day-count
signature is a possible later refinement.

Idempotent: existing files are not overwritten unless `--force` is given, so the held-out test set
stays frozen once created.

Usage:
    python scripts/make_familiar_splits.py                 # create if missing
    python scripts/make_familiar_splits.py --force         # regenerate (breaks the freeze!)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from make_phase2_splits import DEFAULT_SPLITS_DIR, _write_lines, make_splits, read_split  # noqa: E402

SOURCE_SPLIT = "tpc_phase2_familiar_100"
VAL_NAME = "tpc_phase2_familiar_100_val"
TEST_NAME = "tpc_phase2_familiar_100_test"
DEFAULT_TEST_SIZE = 20  # 20% of the 100-record familiar set
DEFAULT_SEED = 20260723


def write_familiar_splits(
    uids: list[str],
    *,
    out_dir: Path = DEFAULT_SPLITS_DIR,
    test_size: int = DEFAULT_TEST_SIZE,
    seed: int = DEFAULT_SEED,
    force: bool = False,
) -> bool:
    """Write the familiar val/test split files. Returns True if written, False if skipped.

    Idempotent unless ``force``: if either target already exists and ``force`` is False, nothing is
    written (keeps the held-out familiar test set frozen).
    """
    out_dir = Path(out_dir)
    val_path = out_dir / f"{VAL_NAME}.txt"
    test_path = out_dir / f"{TEST_NAME}.txt"
    if not force and (val_path.exists() or test_path.exists()):
        return False
    val_list, test_list = make_splits(uids, test_size=test_size, seed=seed)
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
    written = write_familiar_splits(
        uids, test_size=args.test_size, seed=args.seed, force=args.force
    )
    val_path = DEFAULT_SPLITS_DIR / f"{VAL_NAME}.txt"
    test_path = DEFAULT_SPLITS_DIR / f"{TEST_NAME}.txt"
    if written:
        val_list, test_list = make_splits(uids, test_size=args.test_size, seed=args.seed)
        print(f"Wrote {val_path} ({len(val_list)} val) and {test_path} ({len(test_list)} test) "
              f"from {len(uids)} familiar-100 uids (seed={args.seed}).")
    else:
        print(f"Split files already exist; not overwriting without --force:\n"
              f"  {val_path}\n  {test_path}")


if __name__ == "__main__":
    main()
