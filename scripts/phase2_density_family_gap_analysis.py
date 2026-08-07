#!/usr/bin/env python3
"""P19 — find the unidentified half of the held-out gap.

Why this exists: the 2026-08-07 leaderboard breakdown put held-out C-LPR at ``55.20``, **below our
worst local free-prose measurement** (``72.5`` raw / ``78.4`` English-literal, *before* the phrasing
fix landed). The phrasing diagnosis ([P15](../docs/tpc_phase2_roadmap.md#p15)) is real and measured,
but it does not fully explain the held-out number, so this script prices three candidate causes from
**released data only** -- no held-out artifact beyond the seven already-published aggregate metrics,
and no solve (everything here is static parse/coverage analysis, the same primitives
``scripts/phase2_generalization_probe.py`` already uses).

1. **Higher constraint density.** ``FPR = 0.0000`` independently implies a query needs ``>= ~10``
   clauses (see the roadmap's threshold argument). For each released set this script reports the
   clause-count *distribution* (not just the mean) and a density-restricted C-LPR proxy: the
   coverage ceiling (``clpr_ceiling_parse_gap_only``, no-solve, matches the historical correlation
   with measured e2e C-LPR documented in the 2026-08-06 phrasing-fix screen) computed only over
   queries with >= ``--dense-threshold`` (default 10) oracle clauses.
2. **Families we cannot express at all.** Families present in *any* released set's oracle solver-
   dict that our extractor has produced (matched or wrong_value) on **zero** of the six sets.
3. **Families we express but get wrong at scale.** Families ranked by ``instances * miss_rate``
   (not miss_rate alone) across all six sets combined, so a family missed 30% of the time on 400
   instances outranks one missed 100% of the time on 20.

**Kill criterion, fixed in advance**: if (1) reproduces C-LPR ~= 55 on the dense tail of a
free-prose set, stop -- do not pursue (2) or (3); density explains the residual and the response is
re-tuning against dense queries, not family hunting.

Usage::

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_density_family_gap_analysis.py \
        --out-dir results/phase2_baselines/screens/20260807_p19_unidentified_gap

Measurement only: read-only, no LLM calls, no WorldEnv, no solver, writes nothing outside
``--out-dir``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HELD_OUT_C_LPR = 55.20
DENSE_THRESHOLD_DEFAULT = 10


def per_query_records(kind: str, name: str, *, limit: int | None = None) -> list[dict]:
    """One record per query: clause count, parse-gap count, and the diff row (for family stats)."""
    from parser_vs_oracle import _families, compute_query_diff, query_variants
    from phase2_generalization_probe import clause_gap_kind, clause_is_covered, load_hf, load_local

    ids, data = load_local(name) if kind == "local" else load_hf(name)
    if limit:
        ids = ids[:limit]

    records = []
    for uid in ids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        clauses = q.get("hard_logic_py") or []

        row = compute_query_diff(q, disjunction=True, branch_aware=True)

        parsed_variants, oracle_variants = query_variants(q, disjunction=True)
        parsed_fams: set[str] = set()
        for v in parsed_variants:
            parsed_fams |= _families(v)
        oracle_fams: set[str] = set()
        for v in oracle_variants:
            oracle_fams |= _families(v)

        n_parse_gap = 0
        for clause in clauses:
            covered, _kinds = clause_is_covered(clause, parsed_fams)
            if not covered and clause_gap_kind(clause, parsed_fams, oracle_fams) == "parse_gap":
                n_parse_gap += 1

        records.append({
            "uid": uid,
            "n_clauses": len(clauses),
            "n_parse_gap": n_parse_gap,
            "diff_row": row,
        })
    return records


def density_report(label: str, records: list[dict], *, dense_threshold: int) -> dict:
    counts = [r["n_clauses"] for r in records]

    def ceiling(subset: list[dict]) -> dict:
        total = sum(r["n_clauses"] for r in subset)
        gaps = sum(r["n_parse_gap"] for r in subset)
        return {
            "n_queries": len(subset),
            "n_oracle_clauses": total,
            "n_parse_gap": gaps,
            "clpr_ceiling_parse_gap_only": round(100.0 * (total - gaps) / total, 2) if total else None,
        }

    dense = [r for r in records if r["n_clauses"] >= dense_threshold]
    sparse = [r for r in records if r["n_clauses"] < dense_threshold]

    quantiles = {}
    if counts:
        sorted_counts = sorted(counts)
        n = len(sorted_counts)
        for label_q, frac in (("p50", 0.50), ("p75", 0.75), ("p90", 0.90)):
            idx = min(n - 1, int(round(frac * (n - 1))))
            quantiles[label_q] = sorted_counts[idx]
        quantiles["max"] = sorted_counts[-1]
        quantiles["min"] = sorted_counts[0]

    return {
        "label": label,
        "n": len(records),
        "clause_count_mean": round(statistics.mean(counts), 2) if counts else 0,
        "clause_count_quantiles": quantiles,
        "dense_threshold": dense_threshold,
        "pct_queries_dense": round(100.0 * len(dense) / len(records), 1) if records else 0.0,
        "overall": ceiling(records),
        "dense_tail": ceiling(dense),
        "sparse_rest": ceiling(sparse),
    }


def family_gap_report(all_rows_by_set: dict[str, list[dict]]) -> dict:
    """Candidates 2 and 3: families never produced anywhere, and families ranked by
    instances * miss_rate across all sets combined."""
    from parser_vs_oracle import _aggregate_family_stats

    combined: dict[str, dict] = {}
    per_set_family_instances: dict[str, Counter] = {}
    for set_label, rows in all_rows_by_set.items():
        stats = _aggregate_family_stats(rows)
        counter = Counter()
        for s in stats:
            fam = s["family"]
            instances = s["matched"] + s["missing"] + s["wrong_value"]
            counter[fam] = instances
            acc = combined.setdefault(fam, {
                "family": fam, "matched": 0, "missing": 0, "spurious": 0, "wrong_value": 0,
                "sets_present_in_oracle": set(), "sets_ever_produced": set(),
            })
            acc["matched"] += s["matched"]
            acc["missing"] += s["missing"]
            acc["spurious"] += s["spurious"]
            acc["wrong_value"] += s["wrong_value"]
            if instances > 0:
                acc["sets_present_in_oracle"].add(set_label)
            if s["matched"] + s["wrong_value"] > 0:
                acc["sets_ever_produced"].add(set_label)
        per_set_family_instances[set_label] = counter

    never_produced = []
    ranked = []
    for fam, acc in combined.items():
        oracle_instances = acc["matched"] + acc["missing"] + acc["wrong_value"]
        produced = acc["matched"] + acc["wrong_value"]
        miss_rate = round(acc["missing"] / oracle_instances, 4) if oracle_instances else 0.0
        entry = {
            "family": fam,
            "oracle_instances": oracle_instances,
            "matched": acc["matched"],
            "missing": acc["missing"],
            "wrong_value": acc["wrong_value"],
            "spurious": acc["spurious"],
            "miss_rate": miss_rate,
            "score_instances_x_miss_rate": round(oracle_instances * miss_rate, 2),
            "sets_present_in_oracle": sorted(acc["sets_present_in_oracle"]),
        }
        if oracle_instances > 0 and produced == 0:
            never_produced.append(entry)
        if oracle_instances > 0:
            ranked.append(entry)

    never_produced.sort(key=lambda e: -e["oracle_instances"])
    ranked.sort(key=lambda e: -e["score_instances_x_miss_rate"])

    return {
        "never_produced_on_any_set": never_produced,
        "ranked_by_instances_x_miss_rate": ranked[:20],
    }


DEFAULT_SETS = [
    # (label, kind, name) -- identical to phase2_generalization_probe.DEFAULT_SETS, repeated here
    # (rather than imported) so this script's set list is self-contained and doesn't shift if the
    # probe's own default list ever changes for an unrelated reason.
    ("familiar_100_control", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]


def render_markdown(report: dict) -> str:
    lines = [
        f"Held-out C-LPR (published): **{HELD_OUT_C_LPR}**. Dense threshold: "
        f"`>= {report['dense_threshold']}` oracle clauses.",
        "",
        "## 1. Density",
        "",
        "| set | n | clauses mean | p50 | p75 | p90 | max | % dense | overall ceiling | "
        "dense-tail ceiling | sparse-rest ceiling |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in report["density"]:
        q = d["clause_count_quantiles"]
        lines.append(
            f"| {d['label']} | {d['n']} | {d['clause_count_mean']} | {q.get('p50','-')} | "
            f"{q.get('p75','-')} | {q.get('p90','-')} | {q.get('max','-')} | "
            f"{d['pct_queries_dense']}% | {d['overall']['clpr_ceiling_parse_gap_only']} | "
            f"{d['dense_tail']['clpr_ceiling_parse_gap_only']} "
            f"(n={d['dense_tail']['n_queries']}) | "
            f"{d['sparse_rest']['clpr_ceiling_parse_gap_only']} |"
        )
    lines += ["", "## 2. Families never produced on any set", ""]
    np_list = report["family_gaps"]["never_produced_on_any_set"]
    if np_list:
        lines += ["| family | oracle instances | sets present in oracle |", "| --- | --- | --- |"]
        for e in np_list:
            lines.append(f"| {e['family']} | {e['oracle_instances']} | "
                         f"{', '.join(e['sets_present_in_oracle'])} |")
    else:
        lines.append("None -- every oracle family is produced (matched or wrong_value) on at "
                     "least one set.")
    lines += ["", "## 3. Families ranked by instances x miss_rate (top 20)", "",
              "| family | oracle instances | missing | miss_rate | score |",
              "| --- | --- | --- | --- | --- |"]
    for e in report["family_gaps"]["ranked_by_instances_x_miss_rate"]:
        lines.append(f"| {e['family']} | {e['oracle_instances']} | {e['missing']} | "
                     f"{e['miss_rate']} | {e['score_instances_x_miss_rate']} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dense-threshold", type=int, default=DENSE_THRESHOLD_DEFAULT)
    ap.add_argument("--limit", type=int, default=None, help="First N queries of each set (debug).")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    density_out = []
    rows_by_set: dict[str, list[dict]] = {}
    for label, kind, name in DEFAULT_SETS:
        print(f"[p19] {label} ...", flush=True)
        records = per_query_records(kind, name, limit=args.limit)
        density_out.append(density_report(label, records, dense_threshold=args.dense_threshold))
        rows_by_set[label] = [r["diff_row"] for r in records]
        print(f"[p19] {label}: n={len(records)} done", flush=True)

    family_out = family_gap_report(rows_by_set)

    report = {
        "measurement_kind": "screen",
        "held_out_c_lpr_published": HELD_OUT_C_LPR,
        "dense_threshold": args.dense_threshold,
        "density": density_out,
        "family_gaps": family_out,
    }

    if args.out_dir:
        d = Path(args.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "p19_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        (d / "p19_summary.md").write_text(render_markdown(report), encoding="utf-8")
        print(f"[p19] wrote {d}/p19_report.json, p19_summary.md", flush=True)

    print()
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
