#!/usr/bin/env python
"""READ-ONLY failure diagnosis.

For every uid in a split, load the method's plan and the query's hard_logic_py (read straight
from the data files, which always carry it), run evaluate_constraints_py, and tally the failing
clauses by the DSL functions they reference. The resulting tables show which Step-5 repair
operator to sharpen between search iterations. Writes nothing.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
from chinatravel.symbol_verification.concept_func import func_dict

DATA_DIR = os.path.join(ROOT, "chinatravel", "data", "en")


def _data_index():
    idx = {}
    for d in os.listdir(DATA_DIR):
        dd = os.path.join(DATA_DIR, d)
        if not os.path.isdir(dd):
            continue
        for fn in os.listdir(dd):
            if fn.endswith(".json"):
                idx[fn[:-5]] = os.path.join(dd, fn)
    return idx


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1_constraints_unsolved")
    ap.add_argument("--method", default="best")
    args = ap.parse_args()

    split_file = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits", args.split + ".txt")
    with open(split_file) as f:
        uids = [line.strip() for line in f if line.strip()]
    method_dir = os.path.join(ROOT, "results", args.method)
    data_idx = _data_index()
    funcs = sorted(func_dict.keys(), key=len, reverse=True)

    func_counter = Counter()
    sig_counter = Counter()
    queries_with_failure = 0
    failing_clauses = 0
    missing_plans = 0

    for uid in uids:
        qf = data_idx.get(uid)
        if not qf:
            continue
        with open(qf) as f:
            query = json.load(f)
        hard_logic = query.get("hard_logic_py", []) or []
        plan_file = os.path.join(method_dir, uid + ".json")
        if os.path.exists(plan_file):
            with open(plan_file) as f:
                plan = json.load(f)
        else:
            plan = {"itinerary": []}
            missing_plans += 1
        try:
            res = evaluate_constraints_py(hard_logic, plan)
        except Exception:
            res = [False] * len(hard_logic)
        failed = [hard_logic[i] for i in range(len(res)) if not res[i]]
        if failed:
            queries_with_failure += 1
        for clause in failed:
            failing_clauses += 1
            used = tuple(sorted({fn for fn in funcs if re.search(r"\b" + re.escape(fn) + r"\b", clause)}))
            sig_counter[used] += 1
            for fn in used:
                func_counter[fn] += 1

    print("split={} method={} uids={} queries_with_failure={} failing_clauses={} missing_plans={}".format(
        args.split, args.method, len(uids), queries_with_failure, failing_clauses, missing_plans))
    print("\nTop DSL functions in failing clauses:")
    for fn, c in func_counter.most_common(20):
        print("  {:4d}  {}".format(c, fn))
    print("\nTop failing-clause signatures:")
    for sig, c in sig_counter.most_common(25):
        print("  {:4d}  {}".format(c, ", ".join(sig) if sig else "(no DSL funcs)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
