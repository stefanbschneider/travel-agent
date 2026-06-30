#!/usr/bin/env python
"""Query-by-query optimizer loop for exact per-query score 100.

For each target query:
1) run TPCAgent with aggressive search/CP settings
2) evaluate only that query with eval_tpc --update_best
3) auto-maintain results/optimal and <split>_suboptimal via eval_tpc

Stops when at least --target-optimal queries in results/best have _eval_score >= 100,
or when no further progress is observed across rounds.
"""

import argparse
import json
import os
import subprocess
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLITS_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
BEST_DIR = os.path.join(ROOT, "results", "best")


def _split_path(split_name):
    return os.path.join(SPLITS_DIR, "{}.txt".format(split_name))


def _read_split_ids(split_name):
    path = _split_path(split_name)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _score_for(uid):
    path = os.path.join(BEST_DIR, "{}.json".format(uid))
    if not os.path.exists(path):
        return -1.0
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return float(obj.get("_eval_score", -1.0))
    except Exception:
        return -1.0


def _count_optimal(split_ids):
    n = 0
    for uid in split_ids:
        if _score_for(uid) >= (100.0 - 1e-9):
            n += 1
    return n


def _candidate_ids(split_ids):
    rows = []
    for uid in split_ids:
        score = _score_for(uid)
        if score < (100.0 - 1e-9):
            rows.append((score, uid))
    rows.sort(reverse=True)
    return [uid for _, uid in rows]


def _run(cmd, env=None):
    return subprocess.call(cmd, cwd=ROOT, env=env)


def _append_log(path, payload):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1")
    ap.add_argument("--target-optimal", type=int, default=100)
    ap.add_argument("--max-rounds", type=int, default=20)
    ap.add_argument("--max-no-progress-rounds", type=int, default=3)
    ap.add_argument("--per-round-limit", type=int, default=300,
                    help="max query attempts per round (in score-desc order)")
    ap.add_argument("--timeout", type=int, default=100000)
    ap.add_argument("--restarts", type=int, default=2400)
    ap.add_argument("--budget", type=float, default=420.0)
    ap.add_argument("--cp-time-limit", type=float, default=90.0)
    ap.add_argument("--cp-attr-cap", type=int, default=90)
    ap.add_argument("--cp-rest-cap", type=int, default=70)
    ap.add_argument("--cp-hotel-cap", type=int, default=90)
    ap.add_argument("--cp-four-slot-share", type=float, default=0.9)
    ap.add_argument("--cp-four-slot-rounds", type=int, default=4)
    ap.add_argument("--cp-search-workers", type=int, default=1)
    args = ap.parse_args()

    split_ids = _read_split_ids(args.split)
    if not split_ids:
        print("[opt-loop] split '{}' is empty or missing".format(args.split))
        return 1

    run_ts = time.strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(ROOT, "cache", "densify_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "optimal_loop_{}_{}.jsonl".format(args.split, run_ts))

    initial_optimal = _count_optimal(split_ids)
    print("[opt-loop] split={} size={} initial_optimal={} target_optimal={}".format(
        args.split, len(split_ids), initial_optimal, args.target_optimal
    ))

    no_progress_rounds = 0
    total_attempts = 0

    for round_idx in range(args.max_rounds):
        current_optimal = _count_optimal(split_ids)
        if current_optimal >= args.target_optimal:
            print("[opt-loop] target reached before round {}: {} optimal".format(round_idx, current_optimal))
            break

        seed_salt = "opt_r{}".format(round_idx)
        candidates = _candidate_ids(split_ids)
        if not candidates:
            print("[opt-loop] no non-optimal queries remain")
            break

        if args.per_round_limit > 0:
            candidates = candidates[:args.per_round_limit]

        print("[opt-loop] round={} candidates={} seed_salt={}".format(
            round_idx, len(candidates), seed_salt
        ))

        env = dict(os.environ)
        env.update({
            "TPC_MAX_RESTARTS": str(args.restarts),
            "TPC_SOLVE_BUDGET_SEC": str(args.budget),
            "TPC_SEED_SALT": seed_salt,
            "TPC_USE_CP_SOLVER": "1",
            "TPC_CP_AFTER_PASS": "1",
            "TPC_CP_TIME_LIMIT_SEC": str(args.cp_time_limit),
            "TPC_CP_ATTR_CAP": str(args.cp_attr_cap),
            "TPC_CP_REST_CAP": str(args.cp_rest_cap),
            "TPC_CP_HOTEL_CAP": str(args.cp_hotel_cap),
            "TPC_CP_FOUR_SLOT_SHARE": str(args.cp_four_slot_share),
            "TPC_CP_FOUR_SLOT_ROUNDS": str(args.cp_four_slot_rounds),
            "TPC_CP_SEARCH_WORKERS": str(args.cp_search_workers),
        })

        round_before = _count_optimal(split_ids)
        newly_optimal = 0

        for i, uid in enumerate(candidates, start=1):
            before_score = _score_for(uid)
            print("[opt-loop] round={} {}/{} uid={} score_before={:.6f}".format(
                round_idx, i, len(candidates), uid, before_score
            ))

            rc_run = _run([
                sys.executable,
                "run_tpc.py",
                "--splits", args.split,
                "--index", uid,
                "--agent", "TPCAgent",
                "--llm", "TPCLLM",
                "--lang", "en",
                "--timeout", str(args.timeout),
                "--oracle_translation",
            ], env=env)

            rc_eval = _run([
                sys.executable,
                "eval_tpc.py",
                "--splits", args.split,
                "--index", uid,
                "--method", "TPCAgent_TPCLLM_en_oracletranslation",
                "--lang", "en",
                "--update_best",
            ], env=env)

            after_score = _score_for(uid)
            became_optimal = before_score < (100.0 - 1e-9) and after_score >= (100.0 - 1e-9)
            if became_optimal:
                newly_optimal += 1

            total_attempts += 1
            _append_log(log_path, {
                "round": round_idx,
                "idx": i,
                "uid": uid,
                "score_before": before_score,
                "score_after": after_score,
                "became_optimal": became_optimal,
                "rc_run": int(rc_run),
                "rc_eval": int(rc_eval),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

            current_optimal = _count_optimal(split_ids)
            if current_optimal >= args.target_optimal:
                print("[opt-loop] target reached mid-round: {} optimal".format(current_optimal))
                break

        round_after = _count_optimal(split_ids)
        delta = round_after - round_before
        print("[opt-loop] round={} done: optimal {} -> {} (delta={})".format(
            round_idx, round_before, round_after, delta
        ))

        if delta <= 0:
            no_progress_rounds += 1
        else:
            no_progress_rounds = 0

        if no_progress_rounds >= args.max_no_progress_rounds:
            print("[opt-loop] stopping after {} no-progress rounds".format(no_progress_rounds))
            break

    final_optimal = _count_optimal(split_ids)
    print("[opt-loop] finished: optimal={} total_attempts={} log={}".format(
        final_optimal, total_attempts, os.path.relpath(log_path, ROOT)
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
