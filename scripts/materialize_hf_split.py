#!/usr/bin/env python3
"""Materialize a Hugging Face ``LAMDA-NeSy/ChinaTravel`` split as a local split directory.

Why this exists: the free-prose HF query sets (``easy`` / ``medium`` / ``human``) are the only
locally available released data phrased *differently* from familiar-100, but the solver entry points
only consume splits that resolve through ``chinatravel/data/load_datasets.py``. This writes the two
things that loader needs -- one ``<uid>.json`` per query under ``chinatravel/data/en/<name>/`` and a
UID list at ``chinatravel/evaluation/default_splits/<name>.txt`` -- so an end-to-end diagnostic can
run the real harness against free-prose phrasing (see
``results/phase2_baselines/screens/20260806_generalization_probe/``).

The English text (``nature_language_en``) becomes ``nature_language`` and city names are mapped to
their English forms, matching ``scripts/parser_vs_oracle.load_hf_queries`` exactly, so the parser
report and the end-to-end run see byte-identical inputs. ``hard_logic_py`` is written through for
*scoring only*: the agent path strips oracle fields, as on every other split.

Deterministic: uids are taken in HF row order, and ``--limit`` takes a prefix, so the same command
reproduces the same subset. Released data only; writes nothing outside the two paths named above.

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split human \
        --name hf_human_probe30 --limit 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Only the visible query fields the harness needs, plus hard_logic_py for the scorer.
KEEP = ("uid", "nature_language", "start_city", "target_city", "days", "people_number",
        "hard_logic_py")


def materialize(hf_split: str, name: str, *, limit: int | None = None,
                project_root: Path = PROJECT_ROOT) -> dict:
    from parser_vs_oracle import load_hf_queries

    ids, data = load_hf_queries("default", [hf_split])
    if limit:
        ids = ids[: int(limit)]

    data_dir = project_root / "chinatravel" / "data" / "en" / name
    data_dir.mkdir(parents=True, exist_ok=True)
    for uid in ids:
        q = dict(data[uid])
        q["uid"] = uid
        out = {k: q.get(k) for k in KEEP if q.get(k) is not None}
        (data_dir / f"{uid}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    split_file = project_root / "chinatravel" / "evaluation" / "default_splits" / f"{name}.txt"
    split_file.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return {"name": name, "hf_split": hf_split, "n": len(ids),
            "data_dir": str(data_dir), "split_file": str(split_file)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hf-split", required=True,
                    choices=["easy", "medium", "human", "preference_base50"])
    ap.add_argument("--name", required=True, help="Local split name to create.")
    ap.add_argument("--limit", type=int, default=None, help="Take the first N uids (deterministic).")
    args = ap.parse_args()
    print(json.dumps(materialize(args.hf_split, args.name, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
