#!/usr/bin/env python3
"""Does an LLM recover the constraint-extraction gaps the regex parser has on unfamiliar phrasing?

Why this exists: the 2026-08-06 generalization probe measured that the deterministic extractor is
phrasing-brittle -- clean on familiar-100's numbered template, 8-14 % clause-level parse gaps on
every differently-phrased released set. Two named families (budgets, room_type) were closed with
regex alternatives; the residual is dominated by the *name/type* families (attraction_type,
restaurant_type, attraction_name, accommodation_type), which are open-vocabulary and therefore the
natural candidates for LLM extraction rather than more regex.

This script measures exactly that, statically (no solver, no plans, one LLM call per query):

    regex arm : the shipped no-oracle parse                    (TPC_P2_LLM_PARSE off)
    llm arm   : LLM-first structured extraction + validation   (TPC_P2_LLM_PARSE=1, mode=extract)

Both arms are scored against the same oracle solver-dict with the same instrument as
``scripts/phase2_generalization_probe.py`` (clause-level parse gaps, family-level precision/recall),
so the numbers are directly comparable to that screen's table.

It reports, per set: parse-gap clauses and per-query gap counts for each arm, the implied C-LPR /
FPR ceilings, family-level P/R/F1/value-accuracy, which families the LLM *recovered*, which it
*broke* (regex had it right, LLM overwrote it wrong), and LLM error/timeout counts.

Measurement only: writes nothing outside ``--out-dir``. Never enables a flag in the shipped path.

Usage::

    TPC_P2_LLM_BACKEND=deepinfra HF_HUB_OFFLINE=1 .venv/bin/python \
        scripts/phase2_llm_extraction_probe.py --limit 30 \
        --sets familiar_100 hf_medium hf_human \
        --out-dir results/phase2_baselines/screens/<screen>/llm_extraction
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SETS = {
    # label -> (kind, name)
    "familiar_100": ("local", "tpc_phase2_familiar_100"),
    "local_released_150": ("local", "tpc_phase2_test"),
    "hf_easy": ("hf", "easy"),
    "hf_medium": ("hf", "medium"),
    "hf_human": ("hf", "human"),
    "hf_preference_base50": ("hf", "preference_base50"),
}


def _load(kind: str, name: str):
    from phase2_generalization_probe import load_hf, load_local

    return load_local(name) if kind == "local" else load_hf(name)


def _build_client(model: str | None, timeout: float, cache_dir: str | None):
    from chinatravel.agent.phase2.llm_client import build_llm_client

    config: dict = {"timeout": timeout}
    if model:
        config["model"] = model
    if cache_dir:
        config["cache_dir"] = cache_dir
    return build_llm_client(config)


def _regex_variants(query: dict):
    from parser_vs_oracle import query_variants

    return query_variants(query, disjunction=True)


def _llm_variants(query: dict, llm_client, mode: str):
    """LLM arm: same normalize path the harness uses with TPC_P2_LLM_PARSE=1, mode selectable.

    Returns (variants, error_repr_or_None). parse_to_ir swallows LLM failures into
    ``ir.llm_parse_error`` and degrades to the deterministic parse, so a failure shows up as "no
    better than regex", never as a crash.
    """
    from chinatravel.agent.phase2 import normalize
    from chinatravel.agent.phase2.orchestrator import Flags

    flags = Flags(disjunction=True, llm_parse=True, llm_parse_mode=mode, llm_backend="deepinfra")
    ir = normalize.parse_to_ir(query, llm_client=llm_client, flags=flags)
    variants = normalize.ir_to_solver_variants(ir, query, flags=flags)
    return variants, getattr(ir, "llm_parse_error", None)


def _arm_stats(query: dict, variants: list[dict], oracle_variants: list[dict]) -> dict:
    """Clause-level gaps + family-level diff for one arm of one query."""
    from parser_vs_oracle import _families, diff_variants
    from phase2_generalization_probe import clause_gap_kind, clause_is_covered

    fams: set[str] = set()
    for v in variants:
        fams |= _families(v)
    ofams: set[str] = set()
    for v in oracle_variants:
        ofams |= _families(v)

    gaps = Counter()
    n_gap = 0
    for clause in query.get("hard_logic_py") or []:
        covered, kinds = clause_is_covered(clause, fams)
        if covered or clause_gap_kind(clause, fams, ofams) != "parse_gap":
            continue
        n_gap += 1
        for kind in kinds:
            gaps[kind] += 1

    dv = diff_variants(parsed_variants=variants, oracle_variants=oracle_variants,
                       branch_aware=True, people_number=query.get("people_number"))
    d = dv["diff"]
    return {
        "families": sorted(fams),
        "n_parse_gap": n_gap,
        "gap_by_kind": dict(gaps),
        "precision": d["precision"],
        "recall": d["recall"],
        "value_accuracy": d["value_accuracy"],
        "counts": dict(d["counts"]),
        "buckets": {k: sorted(v) for k, v in d["buckets"].items()},
    }


def _fill_only(regex_variants: list[dict], llm_variants: list[dict]) -> list[dict]:
    """Third arm: the LLM may only fill families the regex left ABSENT, never overwrite one it
    found. This is *not* the shipped merge policy (``normalize.llm_extract_stub`` lets a validated
    LLM value overwrite the deterministic one, and merges dict families at sub-key level) -- it is
    the counterfactual this screen exists to price, because the shipped policy was measured here to
    overwrite correct familiar-100 values.

    Approximation, stated plainly: OR-arm lists can differ in length between the two arms, so
    branch i of the regex arm is paired with branch i of the LLM arm (falling back to branch 0).
    Sub-key merging inside dict families (e.g. adding budgets["total"] to an existing
    budgets={"dining": N}) is deliberately NOT done -- a family the regex touched at all is left
    exactly as the regex left it, which is the strictest form of the policy.
    """
    if not llm_variants:
        return [dict(v) for v in regex_variants]
    out = []
    for i, rv in enumerate(regex_variants or [{}]):
        lv = llm_variants[i] if i < len(llm_variants) else llm_variants[0]
        merged = dict(rv)
        for key, value in lv.items():
            if key not in merged:
                merged[key] = value
        out.append(merged)
    return out


def measure_query(uid: str, query: dict, llm_client, mode: str) -> dict:
    query = dict(query)
    query.setdefault("uid", uid)
    _, oracle_variants = _regex_variants(query)
    regex_variants, _ = _regex_variants(query)

    t0 = time.time()
    try:
        llm_variants, llm_error = _llm_variants(query, llm_client, mode)
    except Exception as exc:  # defensive: a client construction/JSON failure must not kill the run
        llm_variants, llm_error = regex_variants, repr(exc)
    llm_sec = time.time() - t0

    row = {
        "uid": uid,
        "n_clauses": len(query.get("hard_logic_py") or []),
        "llm_error": llm_error,
        "llm_sec": round(llm_sec, 2),
        "regex": _arm_stats(query, regex_variants, oracle_variants),
        "llm": _arm_stats(query, llm_variants, oracle_variants),
        "llm_fill": _arm_stats(query, _fill_only(regex_variants, llm_variants), oracle_variants),
    }
    r, l = row["regex"], row["llm"]
    # Recovered: a family the oracle has, the regex missed, and the LLM matched (right value).
    row["recovered_families"] = sorted(set(l["buckets"].get("matched", []))
                                       - set(r["buckets"].get("matched", [])))
    # Broke: the regex had it matched, the LLM arm no longer does.
    row["broke_families"] = sorted(set(r["buckets"].get("matched", []))
                                    - set(l["buckets"].get("matched", [])))
    f = row["llm_fill"]
    row["fill_recovered_families"] = sorted(set(f["buckets"].get("matched", []))
                                            - set(r["buckets"].get("matched", [])))
    row["fill_broke_families"] = sorted(set(r["buckets"].get("matched", []))
                                         - set(f["buckets"].get("matched", [])))
    row["gap_delta"] = l["n_parse_gap"] - r["n_parse_gap"]
    row["fill_gap_delta"] = f["n_parse_gap"] - r["n_parse_gap"]
    return row


def measure_set(label: str, kind: str, name: str, *, limit: int | None, llm_client, mode: str,
                workers: int) -> dict:
    ids, data = _load(kind, name)
    if limit:
        ids = ids[:limit]

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(measure_query, uid, data[uid], llm_client, mode) for uid in ids]
        for i, fut in enumerate(futures, 1):
            rows.append(fut.result())
            if i % 10 == 0:
                print(f"[llm-probe] {label}: {i}/{len(ids)}", file=sys.stderr)

    n = len(rows)
    n_clauses = sum(r["n_clauses"] for r in rows)

    def arm(key: str) -> dict:
        gap = sum(r[key]["n_parse_gap"] for r in rows)
        q_gap = sum(1 for r in rows if r[key]["n_parse_gap"] > 0)
        by_kind = Counter()
        for r in rows:
            by_kind.update(r[key]["gap_by_kind"])
        counts = Counter()
        for r in rows:
            counts.update(r[key]["counts"])
        p = statistics.mean(r[key]["precision"] for r in rows) if rows else 0.0
        rc = statistics.mean(r[key]["recall"] for r in rows) if rows else 0.0
        return {
            "n_parse_gap": gap,
            "parse_gap_rate": round(gap / n_clauses, 4) if n_clauses else 0.0,
            "queries_with_gap": q_gap,
            "clpr_ceiling": round(100.0 * (n_clauses - gap) / n_clauses, 2) if n_clauses else 100.0,
            "fpr_ceiling": round(100.0 * (n - q_gap) / n, 2) if n else 100.0,
            "precision": round(p, 4),
            "recall": round(rc, 4),
            "f1": round(2 * p * rc / (p + rc), 4) if (p + rc) else 0.0,
            "value_accuracy": round(statistics.mean(r[key]["value_accuracy"] for r in rows), 4)
            if rows else 0.0,
            "family_counts": dict(counts),
            "gap_by_kind": dict(by_kind.most_common()),
        }

    recovered = Counter()
    broke = Counter()
    fill_recovered = Counter()
    fill_broke = Counter()
    for r in rows:
        recovered.update(r["recovered_families"])
        broke.update(r["broke_families"])
        fill_recovered.update(r["fill_recovered_families"])
        fill_broke.update(r["fill_broke_families"])

    return {
        "label": label,
        "source": {"kind": kind, "name": name},
        "n": n,
        "n_clauses": n_clauses,
        "regex": arm("regex"),
        "llm": arm("llm"),
        "llm_fill": arm("llm_fill"),
        "recovered_families": dict(recovered.most_common()),
        "broke_families": dict(broke.most_common()),
        "fill_recovered_families": dict(fill_recovered.most_common()),
        "fill_broke_families": dict(fill_broke.most_common()),
        "llm_errors": sum(1 for r in rows if r["llm_error"]),
        "llm_error_examples": [
            {"uid": r["uid"], "error": r["llm_error"]} for r in rows if r["llm_error"]
        ][:5],
        "llm_sec_mean": round(statistics.mean(r["llm_sec"] for r in rows), 2) if rows else 0.0,
        "queries_improved": sum(1 for r in rows if r["gap_delta"] < 0),
        "queries_regressed": sum(1 for r in rows if r["gap_delta"] > 0),
        "fill_queries_improved": sum(1 for r in rows if r["fill_gap_delta"] < 0),
        "fill_queries_regressed": sum(1 for r in rows if r["fill_gap_delta"] > 0),
        "rows": rows,
    }


def summary_md(report: dict) -> str:
    out = ["| set | n | clauses | arm | parse-gap | C-LPR ceiling | FPR ceiling | family F1 |"
           " value acc |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in report["sets"]:
        for key, name in (("regex", "regex (shipped)"), ("llm", "LLM extract (shipped merge)"),
                          ("llm_fill", "regex + LLM fill-only")):
            a = s[key]
            out.append(f"| {s['label']} | {s['n']} | {s['n_clauses']} | {name} | "
                       f"{a['n_parse_gap']} ({a['queries_with_gap']} queries) | {a['clpr_ceiling']} |"
                       f" {a['fpr_ceiling']} | {a['f1']} | {a['value_accuracy']} |")
    out.append("")
    out.append("| set | arm | queries improved | queries regressed | families recovered |"
               " families broken | LLM errors |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for s in report["sets"]:
        out.append(f"| {s['label']} | LLM extract | {s['queries_improved']} | "
                   f"{s['queries_regressed']} | {s['recovered_families']} | "
                   f"{s['broke_families']} | {s['llm_errors']} |")
        out.append(f"| {s['label']} | fill-only | {s['fill_queries_improved']} | "
                   f"{s['fill_queries_regressed']} | {s['fill_recovered_families']} | "
                   f"{s['fill_broke_families']} | {s['llm_errors']} |")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", nargs="*", default=["familiar_100", "hf_medium", "hf_human"],
                    choices=sorted(SETS), help="Which query sets to measure.")
    ap.add_argument("--limit", type=int, default=30, help="First N queries per set.")
    ap.add_argument("--mode", default="extract", choices=["extract", "audit"],
                    help="LLM parse strategy (normalize.llm_extract_stub vs llm_parse_stub).")
    ap.add_argument("--model", default=None, help="Override TPC_P2_LLM_MODEL.")
    ap.add_argument("--timeout-sec", type=float, default=90.0, help="Per-call LLM timeout.")
    ap.add_argument("--workers", type=int, default=6, help="Concurrent LLM calls.")
    ap.add_argument("--cache-dir", default=None, help="On-disk LLM response cache directory.")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    backend = os.environ.get("TPC_P2_LLM_BACKEND", "none")
    if backend == "none":
        print("refusing to run: set TPC_P2_LLM_BACKEND=deepinfra (or openai/fixture) first",
              file=sys.stderr)
        raise SystemExit(2)

    client = _build_client(args.model, args.timeout_sec, args.cache_dir)
    report = {
        "backend": backend,
        "model": getattr(client, "model", None) or getattr(getattr(client, "inner", None),
                                                           "model", None),
        "mode": args.mode,
        "limit": args.limit,
        "contract": "DIAGNOSTIC SCREEN - static parse-quality comparison, no solver runs, no "
                    "promotion. Default flags unchanged.",
        "sets": [],
    }
    for label in args.sets:
        kind, name = SETS[label]
        print(f"[llm-probe] measuring {label} ({kind}:{name}) mode={args.mode} ...", file=sys.stderr)
        report["sets"].append(measure_set(label, kind, name, limit=args.limit,
                                          llm_client=client, mode=args.mode,
                                          workers=args.workers))

    md = summary_md(report)
    if args.out_dir:
        d = Path(args.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "llm_extraction.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        (d / "llm_extraction_summary.md").write_text(md, encoding="utf-8")
        print(f"[llm-probe] wrote {d}/llm_extraction.json, llm_extraction_summary.md",
              file=sys.stderr)
    print(md)


if __name__ == "__main__":
    main()
