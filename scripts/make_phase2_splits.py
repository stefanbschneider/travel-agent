#!/usr/bin/env python3
"""Create the Phase 2 validation / held-out-test split of the tpc_phase1 queries.

We hold the 1000 released ``tpc_phase1`` queries with oracle constraints. For Phase 2 we split
them once into:

- a larger **validation** split used to iterate and improve the Phase 2 agent, and
- a smaller **held-out test** split used sparingly at the end to check we did not overfit.

The split is deterministic (seeded) and written to stable, sorted split files under
``chinatravel/evaluation/default_splits/``. It is idempotent: existing files are not overwritten
unless ``--force`` is given, so the held-out test set stays frozen once created.

Usage:
    python scripts/make_phase2_splits.py                # create if missing
    python scripts/make_phase2_splits.py --test-size 150 --seed 20260705
    python scripts/make_phase2_splits.py --force        # regenerate (breaks the freeze!)

Note: this is a seeded random split. Stratification by constraint-family/difficulty signature is
a later improvement (see docs/tpc_phase2_eval.md).
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SPLITS_DIR = PROJECT_ROOT / "chinatravel" / "evaluation" / "default_splits"
SOURCE_SPLIT = "tpc_phase1"
VAL_NAME = "tpc_phase2_val"
TEST_NAME = "tpc_phase2_test"
DEFAULT_TEST_SIZE = 150
DEFAULT_SEED = 20260705


def read_split(name: str, splits_dir: Path = DEFAULT_SPLITS_DIR) -> list[str]:
    path = splits_dir / f"{name}.txt"
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def make_splits(
    uids: list[str], *, test_size: int = DEFAULT_TEST_SIZE, seed: int = DEFAULT_SEED
) -> tuple[list[str], list[str]]:
    """Return ``(validation, test)`` uid lists.

    Deterministic for a given ``seed``. Output lists are sorted for stable file contents; the
    randomness only chooses *which* uids land in the test set.
    """
    unique = sorted(set(uids))
    if test_size < 0 or test_size > len(unique):
        raise ValueError(f"test_size {test_size} out of range for {len(unique)} uids")
    rng = random.Random(seed)
    shuffled = unique[:]
    rng.shuffle(shuffled)
    test = set(shuffled[:test_size])
    val_list = sorted(u for u in unique if u not in test)
    test_list = sorted(test)
    return val_list, test_list


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_splits(
    uids: list[str],
    *,
    out_dir: Path = DEFAULT_SPLITS_DIR,
    test_size: int = DEFAULT_TEST_SIZE,
    seed: int = DEFAULT_SEED,
    force: bool = False,
) -> bool:
    """Write the val/test split files. Returns True if written, False if skipped (already exist).

    Idempotent unless ``force`` is set: if either target file already exists and ``force`` is
    False, nothing is written and False is returned (keeps the held-out test set frozen).
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=SOURCE_SPLIT, help="Source split name to partition.")
    parser.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing split files (breaks the held-out freeze).",
    )
    args = parser.parse_args()

    uids = read_split(args.source)
    written = write_splits(
        uids, test_size=args.test_size, seed=args.seed, force=args.force
    )
    val_path = DEFAULT_SPLITS_DIR / f"{VAL_NAME}.txt"
    test_path = DEFAULT_SPLITS_DIR / f"{TEST_NAME}.txt"
    if written:
        val_list, test_list = make_splits(uids, test_size=args.test_size, seed=args.seed)
        print(
            f"Wrote {val_path} ({len(val_list)} val) and {test_path} "
            f"({len(test_list)} test) from {len(uids)} source uids (seed={args.seed})."
        )
    else:
        print(
            f"Split files already exist; not overwriting without --force:\n"
            f"  {val_path}\n  {test_path}"
        )


if __name__ == "__main__":
    main()
