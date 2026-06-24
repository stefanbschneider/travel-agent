#!/usr/bin/env python
"""Rank low-performing queries by score gap and failure signature.

This script is intended for Phase-1 per-query optimization loops where most gain now
comes from lifting the low-score tail. It combines each query's current per-query
score (from results/best/<uid>.json _eval_score when available) with a weighted
hard-logic failure signature and writes a focused split for targeted reruns.

Outputs:
- Console table of top-priority query IDs.
- CSV report under cache/tail_rankings/.
- Optional split file under chinatravel/evaluation/default_splits/.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.data.load_datasets import load_query
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
from chinatravel.symbol_verification.concept_func import func_dict

SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_METHOD = "best"


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_split_ids(split_name):
    path = _split_path(split_name)
    if not os.path.exists(path):
        raise FileNotFoundError("Split file not found: {}".format(path))
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _extract_funcs_from_clause(clause, funcs):
    return sorted({fn for fn in funcs if re.search(r"\b" + re.escape(fn) + r"\b", clause)})


def _signature_weight(signature_funcs):
    """Heuristic severity weights for failure signatures.

    Emphasis: failures that are historically hard to recover with local packing should
    be prioritized in targeted solve rounds.
    """
    if not signature_funcs:
        return 10

    weights = {
        "activity_cost": 20,
        "innercity_transport_cost": 18,
        "total_cost": 20,
        "activity_position": 18,
        "attraction_type": 16,
        "restaurant_type": 16,
        "accommodation_type": 15,
        "room_type": 14,
        "activity_start_time": 16,
        "activity_end_time": 16,
        "activity_time": 16,
        "day_count": 18,
        "innercity_transport_type": 14,
        "taxi_cars": 14,
        "poi_distance": 15,
    }
    return sum(weights.get(fn, 8) for fn in signature_funcs)


def _compute_priority(score, failed_clause_count, signature_funcs):
    score_gap = max(0.0, 100.0 - score)
    sig_weight = _signature_weight(signature_funcs)
    # Gap dominates, but failure complexity and density are meaningful tie-breakers.
    return score_gap + 0.8 * sig_weight + 1.5 * failed_clause_count


def _is_accepted_score(score):
    """Accepted per-query results occupy the 85-100 range in eval_tpc.py.

    Non-accepted plans cannot reach 85 because they lose the 40-point FPR term,
    so this threshold is a cheap proxy for "all hard/schema/commonsense checks
    passed" without rerunning the full evaluator inside the ranker.
    """
    return score >= 85.0


def _include_row(mode, score, failed_clause_count):
    if mode == "preference":
        return _is_accepted_score(score)
    if mode == "unsolved":
        return not _is_accepted_score(score) or failed_clause_count > 0
    return True


def _row_priority(mode, score, failed_clause_count, signature_funcs):
    if mode == "preference":
        # Among fully valid plans, per-query score differs only by preference,
        # so rank directly by remaining score gap.
        return max(0.0, 100.0 - score)
    return _compute_priority(score, failed_clause_count, signature_funcs)


def _format_signature(sig):
    return ",".join(sig) if sig else "no_dsl_funcs"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1", help="source split name")
    ap.add_argument("--method", default=DEFAULT_METHOD, help="results directory under results/")
    ap.add_argument("--lang", choices=["en", "zh"], default="en")
    ap.add_argument(
        "--mode",
        choices=["tail", "unsolved", "preference"],
        default="tail",
        help="tail: current mixed low-score ranking; unsolved: prioritize constraint failures only; preference: prioritize already-solved low-preference queries",
    )
    ap.add_argument("--top-k", type=int, default=150, help="top K IDs to emit to focus split")
    ap.add_argument("--min-score", type=float, default=100.0,
                    help="only consider queries with score <= min-score")
    ap.add_argument("--focus-split", default=None,
                    help="output split name (default: <split>_tail_focus)")
    ap.add_argument("--report-name", default=None,
                    help="CSV basename (default: <split>_<method>_tail_ranking.csv)")
    args = ap.parse_args()

    split_ids = _read_split_ids(args.split)
    query_args = argparse.Namespace(splits=args.split, lang=args.lang, oracle_translation=True)
    query_index, query_data = load_query(query_args)
    query_set = set(query_index)

    missing_from_data = [uid for uid in split_ids if uid not in query_set]
    if missing_from_data:
        print("warning: {} IDs from split not present in loaded data".format(len(missing_from_data)), file=sys.stderr)

    funcs = sorted(func_dict.keys(), key=len, reverse=True)
    method_dir = os.path.join(ROOT, "results", args.method)
    rows = []

    for uid in split_ids:
        query = query_data.get(uid)
        if query is None:
            continue

        plan_path = os.path.join(method_dir, uid + ".json")
        plan = _load_json(plan_path)
        if not isinstance(plan, dict):
            plan = {"itinerary": []}

        score = _safe_float(plan.get("_eval_score", 0.0), 0.0)
        if score > args.min_score:
            continue

        hard_logic = query.get("hard_logic_py", []) or []
        try:
            checks = evaluate_constraints_py(hard_logic, plan)
        except Exception:
            checks = [False] * len(hard_logic)

        failed_indices = [i for i, ok in enumerate(checks) if not ok]
        failed_clauses = [hard_logic[i] for i in failed_indices if i < len(hard_logic)]
        fail_count = len(failed_clauses)

        if not _include_row(args.mode, score, fail_count):
            continue

        sig_counter = Counter()
        all_failed_funcs = []
        for clause in failed_clauses:
            sig = tuple(_extract_funcs_from_clause(clause, funcs))
            sig_counter[sig] += 1
            all_failed_funcs.extend(list(sig))

        top_sig, top_sig_count = (), 0
        if sig_counter:
            top_sig, top_sig_count = sig_counter.most_common(1)[0]

        top_funcs = []
        if all_failed_funcs:
            top_funcs = [name for name, _ in Counter(all_failed_funcs).most_common(3)]

        priority = _row_priority(args.mode, score, fail_count, list(top_sig))
        rows.append({
            "uid": uid,
            "score": score,
            "priority": priority,
            "failed_clauses": fail_count,
            "top_signature": _format_signature(top_sig),
            "top_signature_count": top_sig_count,
            "top_failed_funcs": ",".join(top_funcs),
            "plan_exists": int(os.path.exists(plan_path)),
            "mode": args.mode,
            "accepted_score": int(_is_accepted_score(score)),
        })

    rows.sort(key=lambda r: (-r["priority"], r["score"], -r["failed_clauses"], r["uid"]))

    if not rows:
        print("No queries matched the selection criteria.")
        return 0

    top_k = max(1, min(args.top_k, len(rows)))
    focus = rows[:top_k]
    focus_ids = [r["uid"] for r in focus]

    out_dir = os.path.join(ROOT, "cache", "tail_rankings")
    os.makedirs(out_dir, exist_ok=True)
    report_name = args.report_name or "{}_{}_tail_ranking.csv".format(args.split, args.method)
    report_path = os.path.join(out_dir, report_name)

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "uid",
                "score",
                "priority",
                "failed_clauses",
                "top_signature",
                "top_signature_count",
                "top_failed_funcs",
                "plan_exists",
                "mode",
                "accepted_score",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    focus_split = args.focus_split or "{}_tail_focus".format(args.split)
    focus_split_path = _split_path(focus_split)
    with open(focus_split_path, "w", encoding="utf-8") as f:
        f.write("\n".join(focus_ids) + "\n")

    print("tail-ranking report: {}".format(os.path.relpath(report_path, ROOT)))
    print("focus split: {} ({} IDs)".format(os.path.relpath(focus_split_path, ROOT), len(focus_ids)))
    print("\nTop 20 by priority (mode={}):".format(args.mode))
    for i, row in enumerate(focus[:20], start=1):
        print(
            "{idx:>2}. {uid} score={score:6.2f} priority={priority:7.2f} fails={fails:>2} sig={sig}".format(
                idx=i,
                uid=row["uid"],
                score=row["score"],
                priority=row["priority"],
                fails=row["failed_clauses"],
                sig=row["top_signature"],
            )
        )

    print("\nNext step:")
    print("  ./.venv/bin/python scripts/solve.py --split {} --restarts 1200 --budget 300 --workers $(sysctl -n hw.ncpu)".format(focus_split))
    print("  ./.venv/bin/python scripts/merge.py --split {}".format(focus_split))
    return 0


if __name__ == "__main__":
    sys.exit(main())
