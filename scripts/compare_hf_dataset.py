#!/usr/bin/env python3
"""Compare the Hugging Face LAMDA-NeSy/ChinaTravel dataset against local tpc_phase1.

Answers: is HF a usable independent generalization/held-out rehearsal set? Reports uid overlap,
field presence (esp. hard_logic_py / nature_language_en), city coverage vs local, and day/people
distributions. See docs/tpc_phase2_eval.md.

The comparison core is pure over lists of query dicts (unit-tested). The CLI loads the HF dataset
via the ``datasets`` library and local queries via load_datasets.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CHECK_FIELDS = (
    "hard_logic_py",
    "nature_language",
    "nature_language_en",
    "start_city",
    "target_city",
    "days",
    "people_number",
)


def _present(v) -> bool:
    return v not in (None, "", [], {}, ())


def _field_presence(rows: list[dict]) -> dict:
    counts = {f: 0 for f in CHECK_FIELDS}
    for r in rows:
        for f in CHECK_FIELDS:
            if _present(r.get(f)):
                counts[f] += 1
    return counts


def _dist(rows: list[dict], key: str) -> dict:
    return dict(Counter(r.get(key) for r in rows if r.get(key) is not None))


def compare(local_rows: list[dict], hf_rows: list[dict]) -> dict:
    """Pure comparison of local vs HF query dicts. Returns a report dict."""
    local_uids = {r.get("uid") for r in local_rows}
    hf_uids = {r.get("uid") for r in hf_rows}
    overlap = sorted(u for u in (local_uids & hf_uids) if u is not None)

    local_start = {r.get("start_city") for r in local_rows if r.get("start_city")}
    local_target = {r.get("target_city") for r in local_rows if r.get("target_city")}
    hf_start = {r.get("start_city") for r in hf_rows if r.get("start_city")}
    hf_target = {r.get("target_city") for r in hf_rows if r.get("target_city")}

    hf_presence = _field_presence(hf_rows)

    # Usable as a generalization set if HF adds queries not in local and carries oracle + EN text.
    adds_new_queries = len(hf_uids - local_uids) > 0
    has_oracle = hf_presence.get("hard_logic_py", 0) > 0
    has_en = hf_presence.get("nature_language_en", 0) > 0
    usable = bool(adds_new_queries and has_oracle)

    return {
        "local_n": len(local_rows),
        "hf_n": len(hf_rows),
        "uid_overlap": len(overlap),
        "overlap_uids": overlap[:50],
        "hf_only_uids": len(hf_uids - local_uids),
        "hf_field_presence": hf_presence,
        "local_field_presence": _field_presence(local_rows),
        "hf_only_start_cities": sorted(c for c in (hf_start - local_start) if c),
        "hf_only_target_cities": sorted(c for c in (hf_target - local_target) if c),
        "local_days_distribution": _dist(local_rows, "days"),
        "hf_days_distribution": _dist(hf_rows, "days"),
        "local_people_distribution": _dist(local_rows, "people_number"),
        "hf_people_distribution": _dist(hf_rows, "people_number"),
        "usable_as_generalization_set": usable,
        "notes": {
            "adds_new_queries": adds_new_queries,
            "hf_has_hard_logic_py": has_oracle,
            "hf_has_nature_language_en": has_en,
        },
    }


# --- Loaders (CLI) --------------------------------------------------------


def load_local(split: str = "tpc_phase1", lang: str = "en") -> list[dict]:
    import argparse as ap

    from chinatravel.data.load_datasets import load_query

    _ids, data = load_query(ap.Namespace(splits=split, lang=lang, oracle_translation=True))
    rows = []
    for uid, q in data.items():
        q = dict(q)
        q.setdefault("uid", uid)
        rows.append(q)
    return rows


def load_hf(config: str = "default", splits: list[str] | None = None) -> list[dict]:
    from datasets import load_dataset

    ds = load_dataset("LAMDA-NeSy/ChinaTravel", name=config)
    splits = splits or list(ds.keys())
    rows = []
    for sp in splits:
        rows.extend(ds[sp].to_list())
    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--local-split", default="tpc_phase1")
    p.add_argument("--hf-config", default="default", help="HF subset: default | preference | test")
    p.add_argument("--hf-splits", nargs="*", default=None)
    p.add_argument("--out", default=str(PROJECT_ROOT / "cache" / "phase2_hf_compare.json"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    local_rows = load_local(args.local_split)
    hf_rows = load_hf(args.hf_config, args.hf_splits)
    report = compare(local_rows, hf_rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
