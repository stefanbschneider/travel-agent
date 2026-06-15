#!/usr/bin/env python
"""Run the deterministic TPCAgent search over a split, writing one plan per query.

State lives entirely on disk (results/<method>/<uid>.json), so a killed run resumes with
--skip. The oracle path passes --oracle_translation so run_tpc keeps each query's
hard_logic_py in the query dict (the live parser, augment and acceptance checker all read
it). Use --no-oracle for the Phase-2 NL/parsed-verifier path.

--workers N runs N run_tpc.py processes over disjoint shards of the split concurrently
(queries are independent and write disjoint files, so this is a clean ~N x speedup on a
multi-core box). Each worker's output goes to cache/solve_logs/shard<k>.log.
"""
import argparse
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split)) as f:
        return [line.strip() for line in f if line.strip()]


def _run_cmd(split, oracle, skip):
    cmd = [sys.executable, "run_tpc.py", "--splits", split,
           "--agent", "TPCAgent", "--llm", "TPCLLM", "--lang", "en", "--timeout", "100000"]
    if oracle:
        cmd.append("--oracle_translation")  # keep hard_logic_py for the oracle path
    if skip:
        cmd += ["--skip", "1"]
    return cmd


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", required=True, help="split name under chinatravel/evaluation/default_splits")
    ap.add_argument("--restarts", type=int, default=None, help="TPC_MAX_RESTARTS override")
    ap.add_argument("--budget", type=float, default=None, help="TPC_SOLVE_BUDGET_SEC override")
    ap.add_argument("--seed-salt", dest="seed_salt", default=None, help="TPC_SEED_SALT override")
    ap.add_argument("--skip", action="store_true", help="skip queries whose result file already exists")
    ap.add_argument("--no-oracle", dest="no_oracle", action="store_true",
                    help="run the NL/parsed-verifier path (TPC_USE_ORACLE=0)")
    ap.add_argument("--workers", type=int, default=1, help="parallel run_tpc processes over disjoint shards")
    args = ap.parse_args()

    env = dict(os.environ)
    if args.restarts is not None:
        env["TPC_MAX_RESTARTS"] = str(args.restarts)
    if args.budget is not None:
        env["TPC_SOLVE_BUDGET_SEC"] = str(args.budget)
    if args.seed_salt is not None:
        env["TPC_SEED_SALT"] = str(args.seed_salt)
    oracle = not args.no_oracle
    if args.no_oracle:
        env["TPC_USE_ORACLE"] = "0"

    if args.workers <= 1:
        cmd = _run_cmd(args.split, oracle, args.skip)
        print("solve:", " ".join(cmd))
        return subprocess.call(cmd, cwd=ROOT, env=env)

    uids = _read_uids(args.split)
    workers = max(1, min(args.workers, len(uids)))
    shards = [uids[i::workers] for i in range(workers)]  # round-robin balances slow queries

    prefix = "_tmp_{}_shard".format(args.split)
    for stale in glob.glob(os.path.join(SPLIT_DIR, prefix + "*.txt")):
        os.remove(stale)

    log_dir = os.path.join(ROOT, "cache", "solve_logs")
    os.makedirs(log_dir, exist_ok=True)

    tmp_splits, procs, logs = [], [], []
    try:
        for k, shard in enumerate(shards):
            if not shard:
                continue
            name = "{}{}".format(prefix, k)
            path = _split_path(name)
            with open(path, "w") as f:
                f.write("\n".join(shard) + "\n")
            tmp_splits.append(path)
            log_path = os.path.join(log_dir, "shard{}.log".format(k))
            logf = open(log_path, "w")
            logs.append(logf)
            cmd = _run_cmd(name, oracle, args.skip)
            procs.append((k, len(shard), subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)))

        print("solve: {} workers over {} queries (logs in {})".format(len(procs), len(uids), log_dir))
        rc = 0
        try:
            for k, n, p in procs:
                r = p.wait()
                print("  worker {}: {} queries rc={}".format(k, n, r))
                rc = rc or r
        except KeyboardInterrupt:
            for _, _, p in procs:
                p.terminate()
            raise
        return rc
    finally:
        for logf in logs:
            logf.close()
        for path in tmp_splits:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
