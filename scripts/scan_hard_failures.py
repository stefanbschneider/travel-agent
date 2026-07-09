#!/usr/bin/env python
"""READ-ONLY: scan results/best for queries that fail hard_logic_py constraints.

Prints uid, number of failing clauses, and the failing clause text.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

DATA_DIR = os.path.join(ROOT, "chinatravel", "data", "en")


def data_index():
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
    split = sys.argv[1] if len(sys.argv) > 1 else "tpc_phase1"
    method = sys.argv[2] if len(sys.argv) > 2 else "best"
    split_file = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits", split + ".txt")
    with open(split_file) as f:
        uids = [line.strip() for line in f if line.strip()]
    method_dir = os.path.join(ROOT, "results", method)
    idx = data_index()

    failures = []
    for uid in uids:
        qf = idx.get(uid)
        if not qf:
            print("NO_DATA", uid)
            continue
        with open(qf) as f:
            query = json.load(f)
        hard = query.get("hard_logic_py", []) or []
        pf = os.path.join(method_dir, uid + ".json")
        if not os.path.exists(pf):
            failures.append((uid, ["<missing plan>"]))
            continue
        with open(pf) as f:
            plan = json.load(f)
        try:
            res = evaluate_constraints_py(hard, plan)
        except Exception as e:
            failures.append((uid, ["<exception: %s>" % e]))
            continue
        failed = [hard[i] for i in range(len(res)) if not res[i]]
        if failed:
            failures.append((uid, failed))

    print("split=%s method=%s total=%d failing=%d" % (split, method, len(uids), len(failures)))
    for uid, failed in failures:
        print("\n===== %s : %d failing clause(s) =====" % (uid, len(failed)))
        for c in failed:
            print("---- clause ----")
            print(c.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
