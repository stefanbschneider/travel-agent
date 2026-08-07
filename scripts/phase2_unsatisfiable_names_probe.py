"""Count required-POI-name constraints our own parser emits that **no POI can satisfy**.

Static, read-only, no solve, no LLM, no held-out artifact. Instrument for
`docs/tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints`.

The solver can only place POIs that exist in the target city's catalog. So a
`required_attractions` / `required_restaurants` / `required_hotels` / `position_presence` entry that
resolves to **nothing** in that catalog is not a hard constraint we might fail — it is a constraint
we can *never* satisfy, at any budget, with any search. Every query carrying one is pinned at
`FPR = 0` and at zero on all three preference terms, and it stays in the scheduler's repair queue
burning envelope on an objective with no feasible point.

Resolution uses exactly the deterministic matchers `chinatravel/agent/phase2/normalize.py` already
ships (`_exact_catalog_match`, then the fuzzy `_match_catalog_name`), against the union of the
attraction/restaurant/hotel catalogs — deliberately the *most* generous test available, so a name
counted here is unresolvable even under cross-category rerouting.

Run both arms; `--entity-resolution` reports the residual that `TPC_P2_ENTITY_RESOLUTION=1` leaves,
which is the part only a drop rule can reach:

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py \
        --out-dir results/phase2_baselines/screens/<date>_unsatisfiable_names
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --entity-resolution
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

# Name-bearing families whose values must denote a real POI. `position_presence` is included
# because entity resolution reroutes a misrouted name into it, so a garbage value can land there.
NAME_FIELDS = ("required_attractions", "required_restaurants", "required_hotels",
               "position_presence")

DEFAULT_SETS = [
    ("familiar_100 (control)", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]


def load_local(split: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    return load_query(argparse.Namespace(splits=split, lang=lang, oracle_translation=True))


def load_hf(hf_split: str):
    from parser_vs_oracle import load_hf_queries

    return load_hf_queries("default", [hf_split])


def measure_set(label: str, kind: str, name: str, *, entity_resolution: bool,
                limit: int | None = None, n_examples: int = 10) -> dict:
    from chinatravel.agent.phase2.normalize import (_exact_catalog_match, _match_catalog_name,
                                                    load_city_entity_catalog)
    from parser_vs_oracle import query_variants

    ids, data = load_local(name) if kind == "local" else load_hf(name)
    if limit:
        ids = ids[:limit]

    n = 0
    n_queries_bad = 0
    by_field = Counter()
    examples: list[dict] = []
    bad_uids: list[str] = []

    for uid in ids:
        query = dict(data[uid])
        query.setdefault("uid", uid)
        catalog = load_city_entity_catalog(query.get("target_city"))
        pool = [poi for category in ("attraction", "restaurant", "hotel")
                for poi in (catalog.get(category) or [])]
        if not pool:
            continue  # unknown city / no catalog -- nothing to resolve against
        n += 1

        try:
            parsed_variants, _ = query_variants(query, disjunction=True,
                                                entity_resolution=entity_resolution)
        except Exception:
            continue

        query_bad = False
        for variant in parsed_variants:
            for field in NAME_FIELDS:
                for value in (variant.get(field) or []):
                    if not isinstance(value, str):
                        continue
                    if _exact_catalog_match(value, pool) or _match_catalog_name(value, pool):
                        continue
                    by_field[field] += 1
                    query_bad = True
                    if len(examples) < n_examples:
                        examples.append({"uid": str(uid), "field": field, "value": value})
        if query_bad:
            n_queries_bad += 1
            bad_uids.append(str(uid))

    return {
        "label": label,
        "source": f"{kind}:{name}",
        "entity_resolution": entity_resolution,
        "n": n,
        "queries_with_unsatisfiable_required_name": n_queries_bad,
        "share_of_queries": round(n_queries_bad / n, 4) if n else 0.0,
        "unsatisfiable_values_by_field": dict(by_field.most_common()),
        "examples": examples,
        "uids": bad_uids,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Provably unsatisfiable required-POI-name constraints",
        "",
        f"`entity_resolution={report['entity_resolution']}` · static parse-only measurement, no solve.",
        "",
        "| set | n | queries with >=1 unsatisfiable required name | share | by field |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["sets"]:
        lines.append(
            f"| {row['label']} | {row['n']} | {row['queries_with_unsatisfiable_required_name']} | "
            f"{100 * row['share_of_queries']:.0f} % | {row['unsatisfiable_values_by_field'] or '{}'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entity-resolution", action="store_true",
                        help="route the parse through TPC_P2_ENTITY_RESOLUTION's deterministic "
                             "name canonicalization first, to report the residual it leaves")
    parser.add_argument("--limit", type=int, default=None, help="first N queries per set (smoke)")
    parser.add_argument("--out-dir", default=None, help="write report.json / summary.md here")
    parser.add_argument("--sets", default=None,
                        help="comma-separated subset of set labels to measure")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    wanted = {s.strip() for s in args.sets.split(",")} if args.sets else None
    rows = []
    for label, kind, name in DEFAULT_SETS:
        if wanted and label not in wanted and name not in wanted:
            continue
        try:
            rows.append(measure_set(label, kind, name,
                                    entity_resolution=args.entity_resolution, limit=args.limit))
        except Exception as exc:  # a missing HF cache must skip, not fail the whole probe
            rows.append({"label": label, "source": f"{kind}:{name}", "skipped": repr(exc)})

    report = {
        "measurement_kind": "screen",
        "entity_resolution": args.entity_resolution,
        "name_fields": list(NAME_FIELDS),
        "sets": rows,
    }
    text = render_markdown(report)
    print(text)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        suffix = "_er" if args.entity_resolution else ""
        (out / f"report{suffix}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"summary{suffix}.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
