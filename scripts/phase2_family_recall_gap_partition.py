#!/usr/bin/env python3
"""P20 (docs/tpc_phase2_roadmap.md#p20--close-the-two-dominant-family-recall-gaps): partition every
released ``required_attraction_types``/``cuisine_preference`` miss by whether its *oracle value* is
an English literal or a CJK literal.

Why this exists: P19 ranked these two families the largest family-recall residual by
``instances x miss_rate``, but that ranking does not say whether a fix can be *measured* as
``matched`` locally. ``diff_constraints`` requires ``_canon(parsed) == _canon(oracle)`` -- emitting
an English value against a CJK oracle literal moves a clause from ``missing`` to ``wrong_value``,
never to ``matched`` (the same wall P16's own screen already measured: "``missing`` converts into
``wrong_value`` almost one-for-one"). Local sets split cleanly on this: ``tpc_phase2_test`` (and
``tpc_phase2_familiar_100``) carry a *physically separate, pre-translated* English ``hard_logic_py``
(``chinatravel/data/en/``); the four HF sets (``easy``/``medium``/``human``/``preference_base50``)
never translate ``hard_logic_py`` regardless of the query's English ``nature_language_en`` -- not a
loader bug, verified against ``parser_vs_oracle.load_hf_queries`` and
``chinatravel/data/load_datasets.py`` directly.

Writes ``target_uids.txt`` (the English-literal-measurable universe -- what P20's screen was
developed against and what R26 gates) and prints the full CJK/English breakdown per set to stdout.

Usage::

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_family_recall_gap_partition.py \
        --out results/phase2_baselines/screens/20260807_p20_family_recall/target_uids.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TARGET_FAMILIES = {"required_attraction_types", "cuisine_preference"}

_CJK_RE = re.compile(r"[一-鿿]")

SETS = [
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]


def _load_local(split):
    import argparse as ap

    from chinatravel.data.load_datasets import load_query

    return load_query(ap.Namespace(splits=split, lang="en", oracle_translation=True))


def _load_hf(hf_split):
    from parser_vs_oracle import load_hf_queries

    return load_hf_queries("default", [hf_split])


def _has_cjk(value) -> bool:
    return bool(_CJK_RE.search(repr(value)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="path to write target_uids.txt")
    args = ap.parse_args()

    from parser_vs_oracle import diff_variants, query_variants

    counts = Counter()
    english_rows = []

    for label, kind, name in SETS:
        ids, data = _load_local(name) if kind == "local" else _load_hf(name)
        for uid in ids:
            q = dict(data[uid])
            q.setdefault("uid", uid)
            parsed_variants, oracle_variants = query_variants(q, disjunction=True)
            dv = diff_variants(
                parsed_variants=parsed_variants, oracle_variants=oracle_variants,
                branch_aware=True, people_number=q.get("people_number"),
            )
            missing = set(dv["diff"]["buckets"].get("missing", []))
            for fam in missing & TARGET_FAMILIES:
                oval = None
                for ov in oracle_variants:
                    if fam in ov and ov.get(fam):
                        oval = ov[fam]
                        break
                english = not _has_cjk(oval)
                counts[(label, fam, english)] += 1
                if english:
                    english_rows.append((label, uid, fam, oval))

    print("=== miss counts by (set, family, english-literal?) ===")
    for key in sorted(counts):
        print(key, counts[key])

    print()
    print(f"=== English-literal-measurable universe: {len(english_rows)} instance(s) ===")
    for row in english_rows:
        print(row)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            f.write(
                "# P20 target_uids.txt -- released English-visible required_attraction_types/"
                "cuisine_preference misses used to develop the change, per\n"
                "# docs/tpc_phase2_roadmap.md#p20--close-the-two-dominant-family-recall-gaps.\n"
                "# Regenerate: HF_HUB_OFFLINE=1 .venv/bin/python "
                "scripts/phase2_family_recall_gap_partition.py --out <path>\n"
                "# set\tuid\tfamily\toracle_value\n"
            )
            for label, uid, fam, oval in english_rows:
                f.write(f"{label}\t{uid}\t{fam}\t{oval!r}\n")
        print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
