"""Paired parse-diff arms for `TPC_P2_ENTITY_RESOLUTION`, with **no LLM in either arm**.

Static, read-only, no solve, no network. Instrument for
`docs/tpc_phase2_roadmap.md#p21--promote-deterministic-entity-resolution`.

Why this script exists: every previous measurement of `TPC_P2_ENTITY_RESOLUTION` ran it *composed
with* `TPC_P2_LLM_PARSE_MODE=extract_fill` (see
`results/phase2_baselines/screens/20260807_p16_entity_resolution_probe/`, whose three arms are all
`mode: extract_fill` with a DeepInfra backend). So the flag's value on the **shipped deterministic
path** — the one that makes zero LLM calls — had never been isolated. This script isolates it:
identical parse in both arms, one flag differing.

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_entity_resolution_arms_probe.py \
        --out-dir results/phase2_baselines/screens/<date>_entity_resolution_arms

Reads as a **static** parse-diff only. Promoting the flag additionally needs a paired end-to-end
A/B on both registers (familiar-100 control and free prose) — see
`docs/tpc_phase2_eval.md#r29--does-deterministic-entity-resolution-convert-end-to-end`.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

DEFAULT_SETS = [
    ("familiar_100 (control)", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]

COUNT_KEYS = ("matched", "missing", "wrong_value", "spurious", "defaulted")


def load_local(split: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    return load_query(argparse.Namespace(splits=split, lang=lang, oracle_translation=True))


def load_hf(hf_split: str):
    from parser_vs_oracle import load_hf_queries

    return load_hf_queries("default", [hf_split])


def measure_arm(ids, data, *, entity_resolution: bool) -> dict:
    from parser_vs_oracle import _aggregate_family_stats, _f1, compute_query_diff

    rows = []
    for uid in ids:
        query = dict(data[uid])
        query.setdefault("uid", uid)
        rows.append(compute_query_diff(query, disjunction=True, branch_aware=True,
                                       entity_resolution=entity_resolution))

    totals = Counter()
    for row in rows:
        for key in COUNT_KEYS:
            totals[key] += row.get(key, 0)
    precision = statistics.mean(r["precision"] for r in rows) if rows else 0.0
    recall = statistics.mean(r["recall"] for r in rows) if rows else 0.0
    families = {r["family"]: {k: r[k] for k in ("matched", "missing", "wrong_value", "spurious")}
                for r in _aggregate_family_stats(rows)}
    return {
        "entity_resolution": entity_resolution,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_f1(precision, recall), 4),
        "totals": dict(totals),
        "families": families,
    }


def measure_set(label: str, kind: str, name: str, *, limit: int | None = None) -> dict:
    ids, data = load_local(name) if kind == "local" else load_hf(name)
    if limit:
        ids = ids[:limit]
    off = measure_arm(ids, data, entity_resolution=False)
    on = measure_arm(ids, data, entity_resolution=True)
    changed = {}
    for family in sorted(set(off["families"]) | set(on["families"])):
        a, b = off["families"].get(family, {}), on["families"].get(family, {})
        if a != b:
            changed[family] = {"off": a, "on": b}
    return {
        "label": label,
        "source": f"{kind}:{name}",
        "n": len(ids),
        "off": off,
        "on": on,
        "delta": {
            "f1": round(on["f1"] - off["f1"], 4),
            **{k: on["totals"].get(k, 0) - off["totals"].get(k, 0) for k in COUNT_KEYS},
        },
        "families_changed": changed,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# `TPC_P2_ENTITY_RESOLUTION` paired parse arms (deterministic, zero LLM calls)",
        "",
        "| set | n | F1 off | F1 on | matched | wrong_value | spurious |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["sets"]:
        if row.get("skipped"):
            lines.append(f"| {row['label']} | — | skipped | {row['skipped']} | | |")
            continue
        off, on, delta = row["off"], row["on"], row["delta"]
        lines.append(
            f"| {row['label']} | {row['n']} | {off['f1']} | **{on['f1']}** | "
            f"{off['totals']['matched']} -> {on['totals']['matched']} | "
            f"{off['totals']['wrong_value']} -> {on['totals']['wrong_value']} | "
            f"{off['totals']['spurious']} -> {on['totals']['spurious']} |"
        )
    lines += ["", "Acceptance for a static GREEN: no set's `spurious` rises materially and F1 does "
                  "not fall on any set; familiar-100 must not regress.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="first N queries per set (smoke)")
    parser.add_argument("--out-dir", default=None, help="write report.json / summary.md here")
    parser.add_argument("--sets", default=None, help="comma-separated subset of set labels")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    wanted = {s.strip() for s in args.sets.split(",")} if args.sets else None
    rows = []
    for label, kind, name in DEFAULT_SETS:
        if wanted and label not in wanted and name not in wanted:
            continue
        try:
            rows.append(measure_set(label, kind, name, limit=args.limit))
        except Exception as exc:  # a missing HF cache must skip, not fail the whole probe
            rows.append({"label": label, "source": f"{kind}:{name}", "skipped": repr(exc)})

    report = {"measurement_kind": "screen", "flag": "TPC_P2_ENTITY_RESOLUTION",
              "llm_backend": "none", "sets": rows}
    text = render_markdown(report)
    print(text)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        (out / "summary.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
