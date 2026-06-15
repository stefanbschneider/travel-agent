#!/usr/bin/env python
"""Run the deterministic TPCAgent search over a split, writing one plan per query.

State lives entirely on disk (results/<method>/<uid>.json), so a killed run resumes with
--skip. The oracle path passes --oracle_translation so run_tpc keeps each query's
hard_logic_py in the query dict (the live parser, augment and acceptance checker all read
it). Use --no-oracle for the Phase-2 NL/parsed-verifier path.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", required=True, help="split name under chinatravel/evaluation/default_splits")
    ap.add_argument("--restarts", type=int, default=None, help="TPC_MAX_RESTARTS override")
    ap.add_argument("--budget", type=float, default=None, help="TPC_SOLVE_BUDGET_SEC override")
    ap.add_argument("--seed-salt", dest="seed_salt", default=None, help="TPC_SEED_SALT override")
    ap.add_argument("--skip", action="store_true", help="skip queries whose result file already exists")
    ap.add_argument("--no-oracle", dest="no_oracle", action="store_true",
                    help="run the NL/parsed-verifier path (TPC_USE_ORACLE=0)")
    args = ap.parse_args()

    env = dict(os.environ)
    if args.restarts is not None:
        env["TPC_MAX_RESTARTS"] = str(args.restarts)
    if args.budget is not None:
        env["TPC_SOLVE_BUDGET_SEC"] = str(args.budget)
    if args.seed_salt is not None:
        env["TPC_SEED_SALT"] = str(args.seed_salt)

    cmd = [sys.executable, "run_tpc.py", "--splits", args.split,
           "--agent", "TPCAgent", "--llm", "TPCLLM", "--lang", "en", "--timeout", "100000"]
    if args.no_oracle:
        env["TPC_USE_ORACLE"] = "0"
    else:
        # Keeps hard_logic_py in the query dict; without it run_tpc strips the oracle.
        cmd.append("--oracle_translation")
    if args.skip:
        cmd += ["--skip", "1"]

    print("solve:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT, env=env)


if __name__ == "__main__":
    sys.exit(main())
