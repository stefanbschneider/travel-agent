#!/usr/bin/env python
"""Densify already-passing best plans without writing results/best directly.

The script reads results/best/<uid>.json, applies TPCAgent._densify_plan, and writes only
accepted improvements to results/<method>/<uid>.json. scripts/merge.py remains the sole writer
of results/best, so adoption stays score-monotonic.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
METHOD_ORACLE = "TPCAgent_TPCLLM_en_oracletranslation"
METHOD_NOORACLE = "TPCAgent_TPCLLM_en"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CHINATRAVEL_ROOT = os.path.join(ROOT, "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)


from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent
from chinatravel.agent.tpc_agent.tpc_llm import TPCLLM
from chinatravel.data.load_datasets import NpEncoder, load_query
from chinatravel.environment.world_env import WorldEnv


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, cls=NpEncoder)


def _run_parallel(args):
    uids = _read_uids(args.split)
    workers = max(1, min(args.workers, len(uids)))
    shards = [uids[i::workers] for i in range(workers)]
    prefix = "_tmp_{}_densify_shard".format(args.split)
    for stale in glob.glob(os.path.join(SPLIT_DIR, prefix + "*.txt")):
        os.remove(stale)

    log_dir = os.path.join(ROOT, "cache", "densify_logs")
    os.makedirs(log_dir, exist_ok=True)
    tmp_splits = []
    procs = []
    logs = []
    try:
        for k, shard in enumerate(shards):
            if not shard:
                continue
            name = "{}{}".format(prefix, k)
            path = _split_path(name)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(shard) + "\n")
            tmp_splits.append(path)
            log_path = os.path.join(log_dir, "shard{}.log".format(k))
            logf = open(log_path, "w", encoding="utf-8")
            logs.append(logf)
            cmd = [sys.executable, "scripts/densify.py", "--split", name, "--workers", "1"]
            if args.no_oracle:
                cmd.append("--no-oracle")
            procs.append((k, len(shard), subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)))
        print("densify: {} workers over {} queries (logs in {})".format(len(procs), len(uids), log_dir))
        rc = 0
        try:
            for k, n, proc in procs:
                r = proc.wait()
                print("  worker {}: {} queries rc={}".format(k, n, r))
                rc = rc or r
        except KeyboardInterrupt:
            for _, _, proc in procs:
                proc.terminate()
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


def _process(args):
    if args.no_oracle:
        os.environ["TPC_USE_ORACLE"] = "0"
    oracle = not args.no_oracle
    method = METHOD_NOORACLE if args.no_oracle else METHOD_ORACLE
    result_dir = os.path.join(ROOT, "results", method)
    best_dir = os.path.join(ROOT, "results", "best")
    os.makedirs(result_dir, exist_ok=True)

    query_args = SimpleNamespace(splits=args.split, lang="en", oracle_translation=oracle)
    uids, query_data = load_query(query_args)
    agent = TPCAgent(
        env=WorldEnv(lang="en"),
        backbone_llm=TPCLLM(),
        cache_dir=os.path.join(ROOT, "cache"),
        log_dir=os.path.join(ROOT, "cache", "densify"),
        debug=True,
        lang="en",
    )

    considered = improved = accepted = skipped = 0
    for uid in uids:
        best_path = os.path.join(best_dir, uid + ".json")
        if not os.path.exists(best_path):
            skipped += 1
            continue
        plan = _load_json(best_path)
        try:
            score = float(plan.get("_eval_score", 0.0))
        except Exception:
            score = 0.0
        if score < 85.0:
            skipped += 1
            continue
        query = query_data.get(uid)
        if query is None:
            skipped += 1
            continue
        plan.pop("_eval_score", None)
        considered += 1
        constraints = agent._collect_constraints(query)
        check = agent._make_checker(query, constraints)
        try:
            if not agent._accepted(*check(plan)):
                skipped += 1
                continue
            dense = agent._densify_plan(plan, query, constraints, check)
            if agent._accepted(*check(dense)):
                accepted += 1
                better_counts = agent._activity_counts(dense) > agent._activity_counts(plan)
                try:
                    base_pref = sum(agent._default_preference_components(plan))
                    dense_pref = sum(agent._default_preference_components(dense))
                except Exception:
                    base_pref = dense_pref = 0.0
                if better_counts or dense_pref > base_pref + 1e-9:
                    _save_json(os.path.join(result_dir, uid + ".json"), dense)
                    improved += 1
        except Exception as exc:
            print("densify: {} failed: {}".format(uid, exc))
            skipped += 1
    print("densify: considered={} accepted={} improved={} skipped={}".format(
        considered, accepted, improved, skipped))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1", help="split name under chinatravel/evaluation/default_splits")
    ap.add_argument("--no-oracle", dest="no_oracle", action="store_true", help="use the parsed-verifier/no-oracle method dir")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1, help="parallel densify subprocesses over disjoint shards")
    args = ap.parse_args()
    if args.workers > 1:
        return _run_parallel(args)
    return _process(args)


if __name__ == "__main__":
    sys.exit(main())
