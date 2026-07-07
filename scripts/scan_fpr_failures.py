#!/usr/bin/env python
"""READ-ONLY: find FPR-failing queries in results/best and explain why.

Runs schema + commonsense + logic on each query and prints the ones that don't
pass all three, with the failing commonsense check columns.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
from chinatravel.evaluation.utils import load_json_file

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

    query_data = {}
    result_data = {}
    for uid in uids:
        query_data[uid] = load_json_file(idx[uid])
        pf = os.path.join(method_dir, uid + ".json")
        result_data[uid] = load_json_file(pf) if os.path.exists(pf) else {}

    schema = load_json_file(os.path.join(ROOT, "chinatravel", "evaluation", "output_schema.json"))
    _, _, schema_pass = evaluate_schema_constraints(uids, result_data, schema=schema)
    _, _, comm_agg, comm_pass = evaluate_commonsense_constraints(uids, query_data, result_data, lang="en")
    _, _, _, _, _, logi_pass = evaluate_hard_constraints_v2(
        uids, query_data, result_data, env_pass_id=comm_pass, lang="en")

    schema_pass = set(schema_pass)
    comm_pass = set(comm_pass)
    logi_pass = set(logi_pass)
    all_pass = schema_pass & comm_pass & logi_pass

    fail = [u for u in uids if u not in all_pass]
    print("total=%d all_pass=%d failing=%d" % (len(uids), len(all_pass), len(fail)))

    # index comm_agg by data_id
    comm_agg = comm_agg.set_index("data_id")
    for u in fail:
        reasons = []
        if u not in schema_pass:
            reasons.append("SCHEMA")
        if u not in comm_pass:
            cols = []
            if u in comm_agg.index:
                row = comm_agg.loc[u]
                for c in comm_agg.columns:
                    try:
                        if row[c] and float(row[c]) != 0:
                            cols.append(c)
                    except Exception:
                        pass
            reasons.append("COMMONSENSE:" + ",".join(cols) if cols else "COMMONSENSE:(exception?)")
        if u not in logi_pass:
            reasons.append("LOGIC")
        print("%s  ->  %s" % (u, " | ".join(reasons)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
