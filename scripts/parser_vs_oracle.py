#!/usr/bin/env python3
"""Parser-vs-oracle attribution (Axis 1 of docs/tpc_phase2_eval.md).

Compares the no-oracle parser output against the oracle constraints **in the shared solver-dict
schema** and reports, per constraint family: precision / recall / value-accuracy, with failure
buckets: missing, spurious, wrong_value, disjunction_flattened.

This module (Task 8a) provides the pure diff core. The CLI over a split + behavioral-equivalence
check are added in Task 8b.
"""

from __future__ import annotations


def _present(value) -> bool:
    """A constraint family counts as present only if it carries a non-empty value."""
    return value not in (None, [], {}, "", ())


def _canon(value):
    """Canonicalize for order-insensitive equality of list-valued constraints."""
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        canon_items = [_canon(v) for v in value]
        try:
            return sorted(canon_items, key=lambda x: repr(x))
        except Exception:
            return canon_items
    return value


def _families(d: dict) -> set:
    if not isinstance(d, dict):
        return set()
    return {k for k, v in d.items() if _present(v)}


def diff_constraints(parsed: dict, oracle: dict) -> dict:
    """Structural diff of one parsed vs one oracle solver-constraint dict.

    Returns counts, per-bucket family lists, and precision/recall/value-accuracy.
    """
    p_fams = _families(parsed)
    o_fams = _families(oracle)

    missing, spurious, wrong_value, matched = [], [], [], []
    for fam in o_fams - p_fams:
        missing.append(fam)
    for fam in p_fams - o_fams:
        spurious.append(fam)
    for fam in p_fams & o_fams:
        if _canon(parsed.get(fam)) == _canon(oracle.get(fam)):
            matched.append(fam)
        else:
            wrong_value.append(fam)

    n_matched = len(matched)
    n_missing = len(missing)
    n_spurious = len(spurious)
    n_wrong = len(wrong_value)

    predicted = n_matched + n_spurious + n_wrong
    relevant = n_matched + n_missing + n_wrong
    precision = n_matched / predicted if predicted else 1.0
    recall = n_matched / relevant if relevant else 1.0
    shared = n_matched + n_wrong
    value_accuracy = n_matched / shared if shared else 1.0

    return {
        "counts": {
            "matched": n_matched,
            "missing": n_missing,
            "spurious": n_spurious,
            "wrong_value": n_wrong,
        },
        "buckets": {
            "matched": sorted(matched),
            "missing": sorted(missing),
            "spurious": sorted(spurious),
            "wrong_value": sorted(wrong_value),
        },
        "precision": precision,
        "recall": recall,
        "value_accuracy": value_accuracy,
    }


def _best_oracle_index(parsed_variant: dict, oracle_variants: list[dict]) -> int:
    """Pick the oracle branch the parsed variant matches best (most matched families)."""
    best_i, best_matched = 0, -1
    for i, ov in enumerate(oracle_variants or [{}]):
        d = diff_constraints(parsed_variant, ov)
        if d["counts"]["matched"] > best_matched:
            best_matched, best_i = d["counts"]["matched"], i
    return best_i


def _match_pairs(parsed_variants: list[dict], oracle_variants: list[dict]):
    """Greedy one-to-one matching of oracle branches to parsed branches.

    Returns (pairs, unmatched_oracle_idx, unmatched_parsed_idx) where pairs is a list of
    (oracle_idx, parsed_idx) chosen by descending matched-family count without reusing a branch.
    """
    candidates = []
    for oi, ov in enumerate(oracle_variants):
        for pj, pv in enumerate(parsed_variants):
            m = diff_constraints(pv, ov)["counts"]["matched"]
            candidates.append((m, oi, pj))
    # Highest matched first; ties broken deterministically by (oracle_idx, parsed_idx).
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_o, used_p, pairs = set(), set(), []
    for _m, oi, pj in candidates:
        if oi in used_o or pj in used_p:
            continue
        used_o.add(oi); used_p.add(pj); pairs.append((oi, pj))
    unmatched_o = [oi for oi in range(len(oracle_variants)) if oi not in used_o]
    unmatched_p = [pj for pj in range(len(parsed_variants)) if pj not in used_p]
    return pairs, unmatched_o, unmatched_p


def _branch_aware_diff(parsed_variants: list[dict], oracle_variants: list[dict]) -> dict:
    """Matched-pair diff aggregated across all OR branches (micro-averaged counts).

    Each oracle branch is matched to a distinct parsed branch; per-pair family counts are summed.
    Unmatched oracle branches contribute their families as recall misses (``missing``); extra
    parsed branches contribute theirs as precision misses (``spurious``). This credits correct
    multi-branch parsing that the single-branch diff (parsed_variants[0] only) cannot.
    """
    pairs, unmatched_o, unmatched_p = _match_pairs(parsed_variants, oracle_variants)
    tot = {"matched": 0, "missing": 0, "spurious": 0, "wrong_value": 0}
    buckets = {"matched": [], "missing": [], "spurious": [], "wrong_value": []}
    for oi, pj in pairs:
        d = diff_constraints(parsed_variants[pj], oracle_variants[oi])
        for k in tot:
            tot[k] += d["counts"][k]
            buckets[k].extend(d["buckets"][k])
    for oi in unmatched_o:  # whole oracle branch missing from the parse
        fams = sorted(_families(oracle_variants[oi]))
        tot["missing"] += len(fams)
        buckets["missing"].extend(fams)
    for pj in unmatched_p:  # extra parsed branch the oracle does not have
        fams = sorted(_families(parsed_variants[pj]))
        tot["spurious"] += len(fams)
        buckets["spurious"].extend(fams)

    predicted = tot["matched"] + tot["spurious"] + tot["wrong_value"]
    relevant = tot["matched"] + tot["missing"] + tot["wrong_value"]
    shared = tot["matched"] + tot["wrong_value"]
    return {
        "counts": tot,
        "buckets": buckets,
        "precision": tot["matched"] / predicted if predicted else 1.0,
        "recall": tot["matched"] / relevant if relevant else 1.0,
        "value_accuracy": tot["matched"] / shared if shared else 1.0,
    }


def diff_variants(*, parsed_variants: list[dict], oracle_variants: list[dict],
                  branch_aware: bool = False) -> dict:
    """Diff parsed vs oracle at the variant-list level, flagging disjunction flattening.

    ``disjunction_flattened`` is True when the oracle encodes multiple OR branches but the parser
    collapsed them into fewer variants.

    Two scoring modes:
    - default (``branch_aware=False``): **single-branch** diff — scores only ``parsed_variants[0]``
      against its best-matching oracle branch. This UNDER-REPORTS correct multi-branch parsing: a
      perfectly split N-branch query is credited for at most one branch, so its recall/precision
      look low even when every branch is parsed correctly. Prefer ``disjunction_flattened`` and the
      disjunction-aware behavioral check as the trustworthy signals for disjunctive queries.
    - ``branch_aware=True``: matched-pair diff over all branches (see ``_branch_aware_diff``), which
      credits multi-branch parsing and subsumes ``disjunction_flattened`` (a flattened query shows
      unmatched oracle branches as recall misses).
    """
    parsed_variants = parsed_variants or [{}]
    oracle_variants = oracle_variants or [{}]
    flattened = len(oracle_variants) > 1 and len(parsed_variants) < len(oracle_variants)

    if branch_aware:
        diff = _branch_aware_diff(parsed_variants, oracle_variants)
    else:
        pv = parsed_variants[0]
        oi = _best_oracle_index(pv, oracle_variants)
        diff = diff_constraints(pv, oracle_variants[oi])

    return {
        "disjunction_flattened": flattened,
        "parsed_branches": len(parsed_variants),
        "oracle_branches": len(oracle_variants),
        "diff": diff,
    }


# --- Split-level report (CLI) ---------------------------------------------

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_queries(split: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    args = argparse.Namespace(splits=split, lang=lang, oracle_translation=True)
    return load_query(args)


def query_variants(query: dict, *, disjunction: bool = False):
    """Return (parsed_no_oracle_variants, oracle_variants) in the shared solver-dict schema.

    When ``disjunction`` is True, the parsed side is produced through the Phase 2 normalize layer
    with ``TPC_P2_DISJUNCTION`` on, so disjunctive queries expand into one branch-local variant per
    OR arm (the same path the harness feeds the solver). Default (False) keeps the flat single-
    variant no-oracle parse, so existing reports are unchanged.
    """
    import parse_constraints
    from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

    if disjunction:
        from chinatravel.agent.phase2 import normalize
        from chinatravel.agent.phase2.orchestrator import Flags

        flags = Flags(disjunction=True)
        ir = normalize.parse_to_ir(query, flags=flags)
        parsed = normalize.ir_to_solver_variants(ir, query, flags=flags)
    else:
        parsed = solver_constraint_variants(
            query, parse_constraints.parse_query_no_oracle(query), use_oracle=False
        )
    oracle = solver_constraint_variants(
        query, parse_constraints.parse_query(query), use_oracle=True
    )
    return parsed, oracle


def compute_query_diff(query: dict, *, disjunction: bool = False, branch_aware: bool = False) -> dict:
    parsed_variants, oracle_variants = query_variants(query, disjunction=disjunction)
    dv = diff_variants(parsed_variants=parsed_variants, oracle_variants=oracle_variants,
                       branch_aware=branch_aware)
    precision = dv["diff"]["precision"]
    recall = dv["diff"]["recall"]
    row = {
        "uid": query.get("uid"),
        "oracle_branches": dv["oracle_branches"],
        "parsed_branches": dv["parsed_branches"],
        "disjunction_flattened": dv["disjunction_flattened"],
        **{k: dv["diff"]["counts"][k] for k in ("matched", "missing", "spurious", "wrong_value")},
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_f1(precision, recall), 4),
        "value_accuracy": round(dv["diff"]["value_accuracy"], 4),
        # Per-family bucket membership (which constraint families were matched/missing/spurious/
        # wrong_value for this uid). Not written to the per-uid CSV (see run_report) -- consumed by
        # _aggregate_family_stats to attribute precision/recall loss to specific families.
        "buckets": dv["diff"]["buckets"],
    }
    return row


def behavioral_check(query: dict, plan: dict, *, disjunction: bool = False) -> dict:
    """Do parsed vs oracle constraints accept/reject the plan identically?

    With ``disjunction=True`` the parsed side uses OR semantics over disjunction-expanded variants
    (accept if ANY branch's constraints all pass) — matching how the agent actually accepts plans
    (``TPCAgent._solve`` keeps a plan that satisfies any one variant). The flat default ANDs OR-arm
    constraints and therefore under-reports agreement on disjunctive queries.
    """
    from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    parsed_variants, _ = query_variants(query, disjunction=disjunction)
    target_city = query.get("target_city", "")
    try:
        if disjunction:
            parsed_pass = any(
                all(evaluate_parsed_constraints(v, plan, target_city)) for v in parsed_variants
            )
        else:
            parsed_pass = all(evaluate_parsed_constraints(parsed_variants[0], plan, target_city))
    except Exception:
        parsed_pass = False
    try:
        oracle_res = evaluate_constraints_py(query.get("hard_logic_py", []) or [], plan, verbose=False)
        oracle_pass = all(bool(r) for r in oracle_res)
    except Exception:
        oracle_pass = False
    return {"uid": query.get("uid"), "oracle_pass": oracle_pass, "parsed_pass": parsed_pass,
            "agree": oracle_pass == parsed_pass}


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _f1(precision: float, recall: float) -> float:
    denom = precision + recall
    return (2.0 * precision * recall / denom) if denom else 0.0


def _aggregate_family_stats(rows: list[dict], *, max_examples: int = 5) -> list[dict]:
    """Roll the per-uid bucket membership up to per-family counts, sorted by spurious count
    (the dominant loss per docs/tpc_phase2_eval.md) so the top of the list is where to look first
    for regex over-extraction fixes. Each family also carries a few example uids per failure
    bucket to jump straight to a repro."""
    stats: dict[str, dict] = {}
    for row in rows:
        uid = row.get("uid")
        buckets = row.get("buckets", {})
        for bucket in ("matched", "missing", "spurious", "wrong_value"):
            for fam in buckets.get(bucket, []):
                fam_stats = stats.setdefault(
                    fam,
                    {
                        "family": fam,
                        "matched": 0,
                        "missing": 0,
                        "spurious": 0,
                        "wrong_value": 0,
                        "example_missing_uids": [],
                        "example_spurious_uids": [],
                        "example_wrong_value_uids": [],
                    },
                )
                fam_stats[bucket] += 1
                example_key = f"example_{bucket}_uids"
                if example_key in fam_stats and len(fam_stats[example_key]) < max_examples:
                    fam_stats[example_key].append(uid)
    return sorted(stats.values(), key=lambda s: (-s["spurious"], -s["missing"], s["family"]))


def run_report(split: str, *, uids=None, limit=None, behavioral=False, lang="en",
               results_best=None, out_dir=None, disjunction=False, branch_aware=False) -> dict:
    query_ids, query_data = _load_queries(split, lang=lang)
    selected = list(uids) if uids else (query_ids[: int(limit)] if limit else query_ids)

    rows = []
    behav_rows = []
    results_best = Path(results_best) if results_best else PROJECT_ROOT / "results" / "best"
    for uid in selected:
        q = query_data[uid]
        q.setdefault("uid", uid)
        row = compute_query_diff(q, disjunction=disjunction, branch_aware=branch_aware)
        rows.append(row)
        if behavioral:
            plan_path = results_best / f"{uid}.json"
            if plan_path.exists():
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                behav_rows.append(behavioral_check(q, plan, disjunction=disjunction))

    mean_precision = _mean(r["precision"] for r in rows)
    mean_recall = _mean(r["recall"] for r in rows)
    agg = {
        "split": split,
        "n": len(rows),
        "precision": round(mean_precision, 4),
        "recall": round(mean_recall, 4),
        "f1": round(_f1(mean_precision, mean_recall), 4),
        "value_accuracy": round(_mean(r["value_accuracy"] for r in rows), 4),
        "disjunction_flattened": sum(1 for r in rows if r["disjunction_flattened"]),
        "totals": {k: sum(r[k] for r in rows) for k in ("matched", "missing", "spurious", "wrong_value")},
        "family_stats": _aggregate_family_stats(rows),
    }
    if behavioral:
        agg["behavioral"] = {
            "n": len(behav_rows),
            "agreement_rate": round(_mean(1.0 if b["agree"] else 0.0 for b in behav_rows), 4),
            "disagreements": [b["uid"] for b in behav_rows if not b["agree"]],
        }

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"parser_vs_oracle_{split}.csv"
        csv_rows = [{k: v for k, v in r.items() if k != "buckets"} for r in rows]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["uid"])
            w.writeheader()
            w.writerows(csv_rows)
        (out_dir / f"parser_vs_oracle_{split}.json").write_text(
            json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return agg


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default=None, help="Explicit split name (overrides --split-set).")
    p.add_argument("--split-set", choices=["val", "test"], default="val")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--behavioral", action="store_true", help="Also run the behavioral-equivalence check.")
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument("--disjunction", action="store_true",
                   help="Expand disjunctive queries via the Phase 2 normalize layer "
                        "(TPC_P2_DISJUNCTION) instead of the flat single-variant parse.")
    p.add_argument("--branch-aware", action="store_true",
                   help="Score precision/recall with a matched-pair diff across all OR branches "
                        "(credits multi-branch parsing) instead of the single-branch "
                        "parsed_variants[0] diff. Best combined with --disjunction.")
    p.add_argument("--out-dir", default=str(PROJECT_ROOT / "cache" / "phase2_parser_vs_oracle"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    split = args.split or ("tpc_phase2_test" if args.split_set == "test" else "tpc_phase2_val")
    agg = run_report(split, limit=args.limit, behavioral=args.behavioral, lang=args.lang,
                     out_dir=args.out_dir, disjunction=args.disjunction,
                     branch_aware=args.branch_aware)
    print(json.dumps(agg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
