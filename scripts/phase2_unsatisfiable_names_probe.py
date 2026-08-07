"""Count constraints our own parser emits that **no plan can satisfy**.

Static, read-only, no solve, no LLM, no held-out artifact. Instrument for
`docs/tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints`.

Two classes, both reported:

**1. Required POI names with no catalog match.** The solver can only place POIs that exist in the
target city's catalog. So a `required_attractions` / `required_restaurants` / `required_hotels` /
`position_presence` entry that resolves to **nothing** in that catalog is not a hard constraint we
might fail — it is a constraint with **no feasible point**. Every query carrying one is pinned at
`FPR = 0` and at zero on all three preference terms, and it stays in the scheduler's repair queue
burning envelope on an objective that cannot be met.

Resolution uses exactly the deterministic matchers `chinatravel/agent/phase2/normalize.py` already
ships (`_exact_catalog_match`, then the fuzzy `_match_catalog_name`), against the union of the
attraction/restaurant/hotel catalogs — deliberately the *most* generous test available, so a name
counted here is unresolvable even under cross-category rerouting.

**2. Category values with no grounded candidate in that city** (`--types`). Same infeasibility class
for `required_attraction_types` / `cuisine_preference` / `required_hotel_*_types`: a value that matches
no row of the target city's own `database_en/` vocabulary cannot be satisfied there, even when the
value is a perfectly canonical label that exists in *other* cities. This half answers the open question
[R26](../docs/tpc_phase2_eval.md#r26--gate-p20-on-the-registers-it-targets) left about P20's free-prose
fallback. Matching uses `parsed_verifier._match_text`, the matcher the acceptance gate itself uses, so
a value counted here really does fail the gate.

Run all arms; `--entity-resolution` reports the residual that `TPC_P2_ENTITY_RESOLUTION=1` alone
leaves (the part only a drop rule can reach), and `--drop-unsatisfiable-names` reports the residual
after P22's drop rule (`TPC_P2_DROP_UNSATISFIABLE_NAMES=1`) -- a definitional check, since the drop
rule uses these same matchers: it should always measure `0`.

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py \
        --out-dir results/phase2_baselines/screens/<date>_unsatisfiable_names
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --entity-resolution
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --drop-unsatisfiable-names
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --types
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_unsatisfiable_names_probe.py --types --drop-unsatisfiable-names
"""

from __future__ import annotations

import argparse
import glob
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

# Category-bearing families, with the (database subdirectory, column) holding their closed
# vocabulary. Scoped per city: the same label can exist in one city's catalog and not another's.
TYPE_FIELDS = {
    "required_attraction_types": ("attractions", "type"),
    "cuisine_preference": ("restaurants", "cuisine"),
    "required_hotel_all_types": ("accommodations", "featurehoteltype"),
    "required_hotel_any_types": ("accommodations", "featurehoteltype"),
}

DEFAULT_SETS = [
    ("familiar_100 (control)", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]

_TYPE_VOCAB_CACHE: dict[tuple[str, str, str], set[str]] = {}


def _city_dir(city) -> str:
    """The environment's own on-disk city directory name (lowercase, no spaces)."""
    return str(city or "").strip().lower().replace(" ", "")


def type_vocab(city, subdir: str, column: str) -> set[str]:
    """Every distinct value of ``column`` in ``city``'s English catalog for ``subdir``."""
    import pandas as pd

    key = (_city_dir(city), subdir, column)
    if key in _TYPE_VOCAB_CACHE:
        return _TYPE_VOCAB_CACHE[key]
    values: set[str] = set()
    pattern = str(REPO_ROOT / "chinatravel" / "environment" / "database_en" / subdir
                  / _city_dir(city) / "*.csv")
    for path in glob.glob(pattern):
        frame = pd.read_csv(path)
        if column in frame.columns:
            values |= {str(v).strip() for v in frame[column] if isinstance(v, str)}
    _TYPE_VOCAB_CACHE[key] = values
    return values


def load_local(split: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    return load_query(argparse.Namespace(splits=split, lang=lang, oracle_translation=True))


def load_hf(hf_split: str):
    from parser_vs_oracle import load_hf_queries

    return load_hf_queries("default", [hf_split])


def measure_set(label: str, kind: str, name: str, *, entity_resolution: bool,
                drop_unsatisfiable_names: bool = False,
                types: bool = False, limit: int | None = None, n_examples: int = 10) -> dict:
    from chinatravel.agent.phase2.normalize import (_exact_catalog_match, _match_catalog_name,
                                                    load_city_entity_catalog)
    from chinatravel.agent.tpc_agent.parsed_verifier import _match_text
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
                                                entity_resolution=entity_resolution,
                                                drop_unsatisfiable_names=drop_unsatisfiable_names)
        except Exception:
            continue

        query_bad = False
        for variant in parsed_variants:
            fields = TYPE_FIELDS if types else {f: None for f in NAME_FIELDS}
            for field, source in fields.items():
                values = variant.get(field) or []
                if isinstance(values, str):  # a category family may hold a bare string
                    values = [values]
                vocab = type_vocab(query.get("target_city"), *source) if types else None
                for value in values:
                    if not isinstance(value, str):
                        continue
                    if types:
                        if any(_match_text(known, value) for known in vocab):
                            continue
                    elif _exact_catalog_match(value, pool) or _match_catalog_name(value, pool):
                        continue
                    by_field[field] += 1
                    query_bad = True
                    if len(examples) < n_examples:
                        examples.append({"uid": str(uid), "field": field, "value": value,
                                         "target_city": query.get("target_city")})
        if query_bad:
            n_queries_bad += 1
            bad_uids.append(str(uid))

    return {
        "label": label,
        "source": f"{kind}:{name}",
        "entity_resolution": entity_resolution,
        "drop_unsatisfiable_names": drop_unsatisfiable_names,
        "measured": "category_values" if types else "required_names",
        "n": n,
        "queries_with_unsatisfiable_constraint": n_queries_bad,
        "share_of_queries": round(n_queries_bad / n, 4) if n else 0.0,
        "unsatisfiable_values_by_field": dict(by_field.most_common()),
        "examples": examples,
        "uids": bad_uids,
    }


def render_markdown(report: dict) -> str:
    what = ("Category values with no grounded candidate in the target city"
            if report["types"] else "Provably unsatisfiable required-POI-name constraints")
    lines = [
        f"# {what}",
        "",
        f"`entity_resolution={report['entity_resolution']}` · "
        f"`drop_unsatisfiable_names={report['drop_unsatisfiable_names']}` · "
        "static parse-only measurement, no solve.",
        "",
        "| set | n | queries with >=1 unsatisfiable constraint | share | by field |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["sets"]:
        if row.get("skipped"):
            lines.append(f"| {row['label']} | — | skipped: {row['skipped']} | | |")
            continue
        lines.append(
            f"| {row['label']} | {row['n']} | {row['queries_with_unsatisfiable_constraint']} | "
            f"{100 * row['share_of_queries']:.0f} % | {row['unsatisfiable_values_by_field'] or '{}'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entity-resolution", action="store_true",
                        help="route the parse through TPC_P2_ENTITY_RESOLUTION's deterministic "
                             "name canonicalization first, to report the residual it leaves")
    parser.add_argument("--drop-unsatisfiable-names", action="store_true",
                        help="route the parse through P22's TPC_P2_DROP_UNSATISFIABLE_NAMES drop "
                             "rule; a definitional check -- this should always measure 0")
    parser.add_argument("--types", action="store_true",
                        help="measure category-valued families against each city's closed "
                             "vocabulary instead of required POI names (answers R26's open question)")
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
            rows.append(measure_set(label, kind, name, entity_resolution=args.entity_resolution,
                                    drop_unsatisfiable_names=args.drop_unsatisfiable_names,
                                    types=args.types, limit=args.limit))
        except Exception as exc:  # a missing HF cache must skip, not fail the whole probe
            rows.append({"label": label, "source": f"{kind}:{name}", "skipped": repr(exc)})

    report = {
        "measurement_kind": "screen",
        "entity_resolution": args.entity_resolution,
        "drop_unsatisfiable_names": args.drop_unsatisfiable_names,
        "types": args.types,
        "fields": list(TYPE_FIELDS) if args.types else list(NAME_FIELDS),
        "sets": rows,
    }
    text = render_markdown(report)
    print(text)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        suffix = (("_types" if args.types else "") + ("_er" if args.entity_resolution else "")
                  + ("_drop" if args.drop_unsatisfiable_names else ""))
        (out / f"report{suffix}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"summary{suffix}.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
