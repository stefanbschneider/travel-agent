#!/usr/bin/env python
"""Monotonically merge fresh solver outputs into results/best and results/constraints_solved.

Delegates to eval_tpc.py --update_best, which overwrites results/best/<uid>.json only when the
new per-query weighted score is strictly higher, copies into results/constraints_solved/ only
when every hard constraint passes, and prunes solved ids from the unsolved split. No step can
regress an already-solved query.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHOD_ORACLE = "TPCAgent_TPCLLM_en_oracletranslation"
METHOD_NOORACLE = "TPCAgent_TPCLLM_en"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1", help="split to evaluate/merge from")
    ap.add_argument("--no-oracle", dest="no_oracle", action="store_true",
                    help="merge from the no-oracle results dir")
    ap.add_argument("--method", default=None,
                    help="merge from this specific results subdir; overrides --no-oracle")
    args = ap.parse_args()

    method = args.method or (METHOD_NOORACLE if args.no_oracle else METHOD_ORACLE)
    cmd = [sys.executable, "eval_tpc.py", "--splits", args.split,
           "--method", method, "--lang", "en", "--update_best"]
    print("merge:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
