#!/usr/bin/env python
"""Resumable heavy search loop over the unsolved split.

Each round bumps TPC_SEED_SALT (so still-unsolved queries get fresh random params), solves the
current unsolved split (no --skip), then monotonically merges. All state lives on disk, so
re-running iterate.py resumes from the current results/best, results/constraints_solved and the
(shrunken) unsolved split. Stops when a round adds nothing, the split empties, or --rounds hit.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNSOLVED = "tpc_phase1_constraints_unsolved"
SOLVED_DIR = os.path.join(ROOT, "results", "constraints_solved")
UNSOLVED_FILE = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits", UNSOLVED + ".txt")


def _solved_count():
    if not os.path.isdir(SOLVED_DIR):
        return 0
    return sum(1 for n in os.listdir(SOLVED_DIR) if n.endswith(".json"))


def _remaining():
    if not os.path.exists(UNSOLVED_FILE):
        return 0
    with open(UNSOLVED_FILE) as f:
        return sum(1 for line in f if line.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--restarts", type=int, default=800)
    ap.add_argument("--budget", type=float, default=240)
    args = ap.parse_args()

    for r in range(args.rounds):
        if _remaining() == 0:
            print("[iterate] unsolved split empty; stopping at round {}".format(r))
            break
        before = _solved_count()
        solve = [sys.executable, os.path.join("scripts", "solve.py"), "--split", UNSOLVED,
                 "--restarts", str(args.restarts), "--budget", str(args.budget), "--seed-salt", str(r)]
        rc = subprocess.call(solve, cwd=ROOT)
        if rc != 0:
            print("[iterate] solve failed (rc={}) in round {}".format(rc, r), file=sys.stderr)
            return rc
        subprocess.call([sys.executable, os.path.join("scripts", "merge.py"), "--split", UNSOLVED], cwd=ROOT)
        newly = _solved_count() - before
        print("[iterate] round {}: newly_solved={} remaining_unsolved={}".format(r, newly, _remaining()))
        if newly <= 0:
            print("[iterate] no progress in round {}; stopping".format(r))
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
