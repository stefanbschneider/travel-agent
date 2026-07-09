#!/usr/bin/env python
"""READ-ONLY: evaluate a single plan file against a uid's constraints.

Usage: eval_one.py <uid> <plan_file>
Prints schema/commonsense/logic pass booleans, failing commonsense checks,
DAV/ATT/DDR, and the per-query weighted score (same formula as eval_tpc).
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
from eval_tpc import DEFAULT_PR
from chinatravel.evaluation.utils import load_json_file
from chinatravel.symbol_verification.concept_func import func_dict
from copy import deepcopy

DATA_DIR = os.path.join(ROOT, "chinatravel", "data", "en")


def find_query(uid):
    for d in os.listdir(DATA_DIR):
        p = os.path.join(DATA_DIR, d, uid + ".json")
        if os.path.exists(p):
            return p
    return None


def per_query_pr(plan):
    def clamp(v):
        return max(0.0, min(1.0, v))
    out = []
    for constraint in DEFAULT_PR:
        vars_dict = deepcopy(func_dict)
        vars_dict["plan"] = plan
        try:
            exec(constraint, {"__builtins__": {"set": set}}, vars_dict)
            out.append(clamp(vars_dict.get("result", False)))
        except Exception:
            out.append(0.0)
    return out


def evaluate(uid, plan):
    q = load_json_file(find_query(uid))
    uids = [uid]
    query_data = {uid: q}
    result_data = {uid: plan}
    schema = load_json_file(os.path.join(ROOT, "chinatravel", "evaluation", "output_schema.json"))
    _, _, schema_pass = evaluate_schema_constraints(uids, result_data, schema=schema)
    _, _, comm_agg, comm_pass = evaluate_commonsense_constraints(uids, query_data, result_data, lang="en")
    _, _, _, _, _, logi_pass = evaluate_hard_constraints_v2(
        uids, query_data, result_data, env_pass_id=comm_pass, lang="en")

    schema_ok = uid in set(schema_pass)
    comm_ok = uid in set(comm_pass)
    logi_ok = uid in set(logi_pass)
    all_ok = schema_ok and comm_ok and logi_ok

    fail_cols = []
    comm_agg = comm_agg.set_index("data_id")
    if uid in comm_agg.index:
        row = comm_agg.loc[uid]
        for c in comm_agg.columns:
            try:
                if row[c] and float(row[c]) != 0:
                    fail_cols.append(c)
            except Exception:
                pass

    if all_ok:
        pr = per_query_pr(plan)
    else:
        pr = [0.0, 0.0, 0.0]
    comm_score = 100.0 if comm_ok else 0.0
    logic_score = 100.0 if logi_ok else 0.0
    all_pass_score = 100.0 if all_ok else 0.0
    dav, att, ddr = pr[0] * 100, pr[1] * 100, pr[2] * 100
    weighted = (0.1 * comm_score + 0.1 * comm_score + 0.25 * logic_score
                + 0.05 * dav + 0.05 * att + 0.05 * ddr + 0.4 * all_pass_score)
    return {
        "schema": schema_ok, "commonsense": comm_ok, "logic": logi_ok, "all_pass": all_ok,
        "fail_cols": fail_cols, "DAV": dav, "ATT": att, "DDR": ddr, "weighted": weighted,
    }


def main():
    uid = sys.argv[1]
    plan_file = sys.argv[2]
    plan = load_json_file(plan_file)
    res = evaluate(uid, plan)
    print(json.dumps(res, indent=2, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
