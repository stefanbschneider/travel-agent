"""R18: build the four-cell official x parsed cross-tab for tpc_phase2_test.

official = pass iff uid in (schema_pass_id & commonsense_pass_id & logi_pass_id),
           computed exactly as eval_tpc.py computes all_pass_id (oracle-fed, local-only).
parsed   = pass iff the run's own per-query telemetry self_score reports
           schema_ok and commonsense_ok and logical_ok all true (the scheduler's own
           accept-gate check -- selfscore.score_plan's PlanScore.constraints_ok -- as
           actually computed against the exact variants the solver searched against).

Deliverable: the uids where official=fail, parsed=pass (P12's residual false-positive half).
"""
import argparse
import json
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
# results/phase2_baselines/screens/<this dir>/ -> repo root is four levels up.
project_root = os.path.abspath(os.path.join(script_dir, "..", "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
os.chdir(project_root)

from chinatravel.data.load_datasets import load_query
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
from chinatravel.evaluation.utils import load_json_file

METHOD = "phase2_e2e_r18_test150"
SPLIT = "tpc_phase2_test"


def load_result(query_index, path):
    """Load every query's plan; raise rather than silently scoring a partial artifact.

    A missing or corrupt plan file would otherwise score as {} -- which the schema/commonsense/
    logical evaluators will likely (but not reliably) fail -- skewing the cross-tab without any
    signal that anything was wrong. Collect every problem uid and fail with the full list instead.
    """
    plans = {}
    missing = []
    corrupt = []
    for query_id in query_index:
        result_file = os.path.join(path, "{}.json".format(query_id))
        if not os.path.exists(result_file):
            missing.append(query_id)
            continue
        try:
            plans[query_id] = load_json_file(result_file)
        except Exception as exc:
            corrupt.append("{} ({})".format(query_id, exc))
    if missing or corrupt:
        raise RuntimeError(
            "cannot build the cross-tab from partial artifacts: {} missing plan file(s) {}; "
            "{} corrupt/unreadable plan file(s) {}".format(
                len(missing), missing, len(corrupt), corrupt
            )
        )
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en")
    args = argparse.Namespace(splits=SPLIT, method=METHOD, lang=ap.parse_args().lang, index=None)

    query_index, query_data = load_query(args)
    missing = [q for q in query_index if q not in query_data]
    if missing:
        raise RuntimeError("missing query data for {} ids: {}".format(len(missing), missing[:5]))

    results_dir = os.path.join("results", METHOD)
    result_data = load_result(query_index, results_dir)

    schema_file_path = "chinatravel/evaluation/output_schema.json"
    schema = load_json_file(schema_file_path)
    _schema_rate, _schema_agg, schema_pass_id = evaluate_schema_constraints(
        query_index, result_data, schema=schema
    )
    _macro_comm, _micro_comm, _common_agg, commonsense_pass_id = evaluate_commonsense_constraints(
        query_index, query_data, result_data, verbose=False, lang=args.lang
    )
    (
        _macro_logi,
        _micro_logi,
        _cond_macro_logi,
        _cond_micro_logi,
        _logi_agg,
        logi_pass_id,
    ) = evaluate_hard_constraints_v2(
        query_index, query_data, result_data, env_pass_id=commonsense_pass_id, verbose=False, lang=args.lang
    )
    official_pass = set(schema_pass_id) & set(commonsense_pass_id) & set(logi_pass_id)

    telemetry_root = os.path.join("agent_env", "runs", METHOD)
    parsed_pass = set()
    parsed_missing = []
    for uid in query_index:
        tpath = os.path.join(telemetry_root, uid, "telemetry.json")
        if not os.path.exists(tpath):
            parsed_missing.append(uid)
            continue
        t = load_json_file(tpath)
        ss = t.get("self_score") or {}
        if ss.get("schema_ok") and ss.get("commonsense_ok") and ss.get("logical_ok"):
            parsed_pass.add(uid)

    all_uids = set(query_index)
    cell_pp = sorted(official_pass & parsed_pass)
    cell_pf = sorted(official_pass - parsed_pass)
    cell_fp = sorted(parsed_pass - official_pass)  # official=fail, parsed=pass -- the deliverable
    cell_ff = sorted(all_uids - official_pass - parsed_pass)

    print("split:", SPLIT, "method:", METHOD, "n:", len(all_uids))
    print("telemetry missing for", len(parsed_missing), "uids:", parsed_missing[:5])
    print()
    print("official=pass, parsed=pass  (agree, pass):", len(cell_pp))
    print("official=pass, parsed=fail  (self-score under-counts):", len(cell_pf))
    print("official=fail, parsed=pass  (residual false positive -- THE DELIVERABLE):", len(cell_fp))
    print("official=fail, parsed=fail  (agree, fail):", len(cell_ff))
    print()
    print("official pass rate (FPR-equivalent on this split): {:.1f} ({}/{})".format(
        100.0 * len(official_pass) / len(all_uids), len(official_pass), len(all_uids)))
    print("parsed (self-score) pass rate: {:.1f} ({}/{})".format(
        100.0 * len(parsed_pass) / len(all_uids), len(parsed_pass), len(all_uids)))
    print()
    print("uids in official=fail, parsed=pass:")
    for uid in cell_fp:
        print(" -", uid)

    out = {
        "split": SPLIT,
        "method": METHOD,
        "n": len(all_uids),
        "telemetry_missing": parsed_missing,
        "cross_tab": {
            "official_pass_parsed_pass": cell_pp,
            "official_pass_parsed_fail": cell_pf,
            "official_fail_parsed_pass": cell_fp,
            "official_fail_parsed_fail": cell_ff,
        },
        "official_pass_rate": 100.0 * len(official_pass) / len(all_uids),
        "parsed_pass_rate": 100.0 * len(parsed_pass) / len(all_uids),
    }
    out_path = os.path.join(script_dir, "crosstab.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", out_path)


if __name__ == "__main__":
    main()
