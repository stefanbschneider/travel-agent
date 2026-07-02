#!/usr/bin/env python
"""Maintain results/per_query_scores.json: a query -> score cache for results/<method>.

Scores are on the eval_tpc per-query weighted scale (0-100). Each entry stores the
sha256 of the plan file bytes at scoring time, so refreshes only touch changed files.
For a changed/new plan the embedded _eval_score is trusted when present; otherwise the
full evaluation pipeline (schema + commonsense + hard logic + DEFAULT_PR) is run.

Usage:
  ./.venv/bin/python scripts/score_cache.py                 # refresh cache
  ./.venv/bin/python scripts/score_cache.py --worst 10      # refresh, print 10 worst
"""
import argparse
import hashlib
import json
import os
import sys
import time
from copy import deepcopy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_CACHE = os.path.join(ROOT, "results", "per_query_scores.json")


def _read_split_ids(split):
    with open(os.path.join(SPLIT_DIR, split + ".txt")) as f:
        return [line.strip() for line in f if line.strip()]


def _load_cache(path):
    try:
        with open(path) as f:
            payload = json.load(f)
        return payload.get("scores", {}) if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _full_eval_score(uid, plan, query_data, schema):
    """Per-query weighted score, identical to eval_tpc per_query_weighted_scores."""
    import numpy as np
    import eval_tpc
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
    from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
    from chinatravel.symbol_verification.concept_func import func_dict

    idx, rd = [uid], {uid: plan}
    _, _, schema_pass = evaluate_schema_constraints(idx, rd, schema=schema)
    _, _, _, comm_pass = evaluate_commonsense_constraints(idx, query_data, rd, verbose=False, lang="en")
    *_, logi_pass = evaluate_hard_constraints_v2(idx, query_data, rd, env_pass_id=comm_pass, verbose=False, lang="en")
    all_pass = uid in set(schema_pass) & set(comm_pass) & set(logi_pass)
    comm = 100.0 if uid in set(comm_pass) else 0.0
    logic = 100.0 if uid in set(logi_pass) else 0.0
    pr = np.zeros(len(eval_tpc.DEFAULT_PR))
    if all_pass:
        vals = []
        for constraint in eval_tpc.DEFAULT_PR:
            v = deepcopy(func_dict)
            v["plan"] = plan
            try:
                exec(constraint, {"__builtins__": {"set": set}}, v)
                vals.append(max(0.0, min(1.0, v.get("result", False))))
            except Exception:
                vals.append(0.0)
        pr = np.array(vals)
    return 0.2 * comm + 0.25 * logic + 0.05 * pr.sum() * 100 + 0.4 * (100.0 if all_pass else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1")
    ap.add_argument("--method", default="best", help="results directory under results/")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--worst", type=int, default=0, help="print the N worst-scoring queries")
    args = ap.parse_args()

    uids = _read_split_ids(args.split)
    cache = _load_cache(args.cache)
    method_dir = os.path.join(ROOT, "results", args.method)

    query_data = schema = None  # loaded lazily, only if a full eval is needed
    entries, reused, from_embedded, recomputed, missing = {}, 0, 0, 0, []
    for uid in uids:
        path = os.path.join(method_dir, uid + ".json")
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            missing.append(uid)
            continue
        digest = hashlib.sha256(raw).hexdigest()
        ent = cache.get(uid)
        if ent is not None and ent.get("sha256") == digest:
            entries[uid] = ent
            reused += 1
            continue
        plan = json.loads(raw)
        score = plan.get("_eval_score")
        if score is not None:
            from_embedded += 1
        else:
            if query_data is None:
                from chinatravel.data.load_datasets import load_query
                from chinatravel.evaluation.utils import load_json_file
                qargs = argparse.Namespace(splits=args.split, lang="en", oracle_translation=True)
                _, query_data = load_query(qargs)
                schema = load_json_file(os.path.join(ROOT, "chinatravel", "evaluation", "output_schema.json"))
            score = _full_eval_score(uid, plan, query_data, schema)
            recomputed += 1
        entries[uid] = {"score": round(float(score), 4), "sha256": digest}

    payload = {
        "_meta": {
            "split": args.split,
            "method": args.method,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "per-query weighted scores (eval_tpc per_query_weighted_scores scale, 0-100); "
                    "sha256 of the plan file bytes at scoring time. Rebuild: scripts/score_cache.py",
        },
        "scores": entries,
    }
    tmp = args.cache + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    os.replace(tmp, args.cache)

    print("score-cache: {} entries (reused {}, embedded {}, recomputed {}, missing {}) -> {}".format(
        len(entries), reused, from_embedded, recomputed, len(missing), os.path.relpath(args.cache, ROOT)))
    if missing:
        print("missing plan files: {}".format(", ".join(missing[:10])))
    if args.worst:
        ranked = sorted(entries.items(), key=lambda kv: kv[1]["score"])[: args.worst]
        for i, (uid, ent) in enumerate(ranked, 1):
            print("{:>3}. {} score={:8.4f}".format(i, uid, ent["score"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
