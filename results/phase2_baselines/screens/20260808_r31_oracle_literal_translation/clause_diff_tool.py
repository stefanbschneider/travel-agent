"""R31 evaluation-only helper (not committed): produce per-uid, per-clause hard_logic_py
pass/fail for one method's plans scored against one split's oracle, and diff two such tables.

Reuses eval_tpc.py's own loaders/evaluators (load_query, load_result, evaluate_hard_constraints_v2)
so the per-clause table is scored by the exact same code path the official metrics come from --
this is not a reimplementation of the checker.

Usage:
  .venv/bin/python r31_clause_diff.py score --splits hf_medium_r31 --method phase2_e2e_r31_hf_medium \
      --lang en --out control.json
  .venv/bin/python r31_clause_diff.py score --splits hf_medium_en_oracle --method phase2_e2e_r31_hf_medium \
      --lang en --out translated.json
  .venv/bin/python r31_clause_diff.py diff control.json translated.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[0]
# repo root is /root/china-travel-agent; this script lives in scratchpad, so hardcode.
REPO_ROOT = Path("/root/china-travel-agent")
sys.path.insert(0, str(REPO_ROOT))

import os
os.chdir(REPO_ROOT)

from chinatravel.data.load_datasets import load_query
from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
from eval_tpc import load_result, _resolve_method_dir


def score(splits: str, method: str, lang: str, out_path: str):
    args = argparse.Namespace(splits=splits, method=method, lang=lang, index=None)
    query_index, query_data = load_query(args)
    args.method = _resolve_method_dir(args.method, args.lang)
    results_dir = os.path.join("results", args.method)
    method_list, result_data = load_result(args, query_index, results_dir)
    assert len(method_list) == 1
    m = method_list[0]

    # commonsense pass id is only used for the conditional (C-LPR) denominator; not needed for
    # the raw per-clause table, so pass an empty set.
    macro, micro, c_macro, c_micro, logi_result_agg, logi_pass_id = evaluate_hard_constraints_v2(
        query_index, query_data, result_data[m], env_pass_id=set(), verbose=False, lang=lang,
    )

    per_uid = {}
    for _, row in logi_result_agg.iterrows():
        uid = row["data_id"]
        clauses = query_data[uid]["hard_logic_py"]
        n = len(clauses)
        vals = [int(row[f"logic_py_{i}"]) for i in range(n)]
        per_uid[uid] = {"clauses": clauses, "results": vals}

    out = {
        "splits": splits, "method": method, "lang": lang,
        "macro": macro, "micro": micro,
        "n_uids": len(query_index),
        "per_uid": per_uid,
    }
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}: macro={macro:.4f} micro={micro:.4f} n={len(query_index)}")


def diff(a_path: str, b_path: str):
    a = json.loads(Path(a_path).read_text())
    b = json.loads(Path(b_path).read_text())
    a_uids, b_uids = set(a["per_uid"]), set(b["per_uid"])
    assert a_uids == b_uids, f"uid mismatch: {a_uids ^ b_uids}"

    flips_pass_to_fail = []
    flips_fail_to_pass = []
    clause_count_mismatch = []

    for uid in sorted(a_uids):
        ac, bc = a["per_uid"][uid], b["per_uid"][uid]
        if len(ac["results"]) != len(bc["results"]):
            clause_count_mismatch.append(uid)
            continue
        for i, (av, bv) in enumerate(zip(ac["results"], bc["results"])):
            if av == 1 and bv == 0:
                flips_pass_to_fail.append((uid, i, ac["clauses"][i], bc["clauses"][i]))
            elif av == 0 and bv == 1:
                flips_fail_to_pass.append((uid, i, ac["clauses"][i], bc["clauses"][i]))

    print(f"clause_count_mismatch: {len(clause_count_mismatch)} {clause_count_mismatch[:5]}")
    print(f"fail->pass flips (expected, from translation lifting the cap): {len(flips_fail_to_pass)}")
    print(f"pass->fail flips (RED if any -- translation changed a literal's meaning): {len(flips_pass_to_fail)}")
    if flips_pass_to_fail:
        print("\n=== RED: pass->fail flips ===")
        for uid, i, ca, cb in flips_pass_to_fail:
            print(f"uid={uid} clause#{i}\n  A(control):    {ca}\n  B(translated): {cb}")
    if flips_fail_to_pass:
        print("\n=== fail->pass flips (sample of 15) ===")
        for uid, i, ca, cb in flips_fail_to_pass[:15]:
            print(f"uid={uid} clause#{i}\n  A(control):    {ca}\n  B(translated): {cb}")

    return {
        "flips_fail_to_pass": len(flips_fail_to_pass),
        "flips_pass_to_fail": len(flips_pass_to_fail),
        "clause_count_mismatch": clause_count_mismatch,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("score")
    sp.add_argument("--splits", required=True)
    sp.add_argument("--method", required=True)
    sp.add_argument("--lang", default="en")
    sp.add_argument("--out", required=True)
    dp = sub.add_parser("diff")
    dp.add_argument("a")
    dp.add_argument("b")
    args = ap.parse_args()
    if args.cmd == "score":
        score(args.splits, args.method, args.lang, args.out)
    else:
        result = diff(args.a, args.b)
        Path("r31_clause_diff_result.json").write_text(json.dumps(result, indent=2))
