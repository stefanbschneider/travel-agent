#!/usr/bin/env python3
"""R23 ad hoc analysis: clause-density distributions, a dense-tail extraction-ceiling proxy, and
never-produced oracle families, across every released query set.

Read-only: imports the shipped parse path exactly like scripts/phase2_generalization_probe.py and
writes nothing outside --out (this script's own report file). Does not modify any shipped script.

Ad hoc, not a shipped tool: written for the one-off R23 analysis
(docs/tpc_phase2_eval.md#r23--what-else-separates-the-held-out-set-open-static-1-h) and committed
here for reproducibility rather than added to scripts/, per the same convention as P15's
find_flip2.py. Run from anywhere; it locates the repo root from its own path.

Usage:
    HF_HUB_OFFLINE=1 .venv/bin/python r23_density_probe.py --out density_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase2_generalization_probe as probe  # noqa: E402
from parser_vs_oracle import _families, query_variants  # noqa: E402

_CJK = re.compile(r"[一-鿿]")

SETS = [
    ("familiar_100 (control)", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]

# Every family name the schema knows about (covering side of CLAUSE_KIND_RULES, deduplicated) --
# this is the vocabulary a clause could possibly need.
ALL_KNOWN_FAMILIES = sorted({f for _kind, _markers, fams in probe.CLAUSE_KIND_RULES for f in fams})


def measure(label: str, kind: str, name: str) -> dict:
    ids, data = probe.load_local(name) if kind == "local" else probe.load_hf(name)

    per_query = []
    parsed_fams_ever: set[str] = set()
    oracle_fams_ever: set[str] = set()

    for uid in ids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        clauses = q.get("hard_logic_py") or []
        n = len(clauses)

        parsed_variants, oracle_variants = query_variants(q, disjunction=True)
        parsed_fams: set[str] = set()
        for v in parsed_variants:
            parsed_fams |= _families(v)
        oracle_fams: set[str] = set()
        for v in oracle_variants:
            oracle_fams |= _families(v)
        parsed_fams_ever |= parsed_fams
        oracle_fams_ever |= oracle_fams

        covered = 0
        covered_ascii = 0
        n_ascii = 0
        for clause in clauses:
            is_covered, _kinds = probe.clause_is_covered(clause, parsed_fams)
            ascii_only = not _CJK.search(clause)
            if is_covered:
                covered += 1
                if ascii_only:
                    covered_ascii += 1
            if ascii_only:
                n_ascii += 1

        per_query.append({
            "uid": uid,
            "n_clauses": n,
            "n_covered": covered,
            "n_ascii_clauses": n_ascii,
            "n_ascii_covered": covered_ascii,
        })

    clause_counts = [pq["n_clauses"] for pq in per_query]
    histogram = dict(sorted(Counter(clause_counts).items()))

    dense = [pq for pq in per_query if pq["n_clauses"] >= 10]
    dense_n_clauses = sum(pq["n_clauses"] for pq in dense)
    dense_n_covered = sum(pq["n_covered"] for pq in dense)
    dense_n_ascii = sum(pq["n_ascii_clauses"] for pq in dense)
    dense_n_ascii_covered = sum(pq["n_ascii_covered"] for pq in dense)

    never_produced = sorted(set(ALL_KNOWN_FAMILIES) - parsed_fams_ever)
    oracle_never_produced = sorted((oracle_fams_ever - parsed_fams_ever))

    return {
        "label": label,
        "n": len(ids),
        "clause_count_histogram": histogram,
        "clause_count_percentiles": {
            "p50": statistics.median(clause_counts) if clause_counts else 0,
            "p90": (statistics.quantiles(clause_counts, n=10)[8] if len(clause_counts) >= 10
                    else max(clause_counts, default=0)),
            "max": max(clause_counts, default=0),
        },
        "dense_tail_ge10": {
            "n_queries": len(dense),
            "pct_queries": round(100.0 * len(dense) / len(ids), 1) if ids else 0.0,
            "n_clauses": dense_n_clauses,
            "extraction_ceiling_proxy_pct": (
                round(100.0 * dense_n_covered / dense_n_clauses, 2) if dense_n_clauses else None
            ),
            "n_ascii_clauses": dense_n_ascii,
            "extraction_ceiling_proxy_ascii_only_pct": (
                round(100.0 * dense_n_ascii_covered / dense_n_ascii, 2) if dense_n_ascii else None
            ),
        },
        "oracle_families_used_but_never_parsed_anywhere": oracle_never_produced,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    report = {"sets": [measure(*s) for s in SETS]}

    # Global: families present in ANY set's schema-known covering list, but never produced by the
    # parser on ANY of the six sets combined (a genuine "we cannot express this at all" family).
    all_parsed_ever: set[str] = set()
    all_oracle_ever: set[str] = set()
    for label, kind, name in SETS:
        ids, data = probe.load_local(name) if kind == "local" else probe.load_hf(name)
        for uid in ids:
            q = dict(data[uid])
            q.setdefault("uid", uid)
            parsed_variants, oracle_variants = query_variants(q, disjunction=True)
            for v in parsed_variants:
                all_parsed_ever |= _families(v)
            for v in oracle_variants:
                all_oracle_ever |= _families(v)
    report["global"] = {
        "all_known_families": ALL_KNOWN_FAMILIES,
        "families_ever_parsed_any_set": sorted(all_parsed_ever),
        "families_ever_required_by_oracle_any_set": sorted(all_oracle_ever),
        "known_families_never_parsed_anywhere": sorted(set(ALL_KNOWN_FAMILIES) - all_parsed_ever),
        "oracle_required_families_never_parsed_anywhere": sorted(all_oracle_ever - all_parsed_ever),
    }

    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for s in report["sets"]:
        print(s["label"], "dense_tail:", s["dense_tail_ge10"])
    print("global never-parsed (known):", report["global"]["known_families_never_parsed_anywhere"])
    print("global never-parsed (oracle-required):",
          report["global"]["oracle_required_families_never_parsed_anywhere"])


if __name__ == "__main__":
    main()
