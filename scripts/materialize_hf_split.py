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

**P23 -- ``--translate-oracle-literals``.** The HF splits' ``hard_logic_py`` literals are native
Chinese (see ``scripts/phase2_oracle_literal_translation.py``), which caps every free-prose FPR/C-LPR
measurement below 100 regardless of solver quality. This flag rewrites the materialized split's
``hard_logic_py`` through the verified zh->en map (derived from the row-parallel ``database`` /
``database_en`` CSVs; the builder raises rather than guesses if that ever stops holding) and reports
what it could and could not translate. **Evaluation-only, and the result must never ship**: the flag
forces ``--name`` to end in ``_en_oracle`` and that suffix is gitignored, on top of the existing rule
to delete a materialized split after scoring. A translated-oracle split is a new register -- never
comparable with an untranslated HF row -- so label it distinctly (the forced suffix does this) and
record the map's entry count, which this script always does in its returned/printed report.

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/materialize_hf_split.py --hf-split medium \
        --name hf_medium_en_oracle --translate-oracle-literals \
        --report-out results/phase2_baselines/screens/<date>_p23.../translation_report.json
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

# A translated-oracle split must never ship (P23: evaluation-only, delete after scoring) and must
# never be mistaken for an untranslated HF row (a different, non-comparable register). Enforcing
# the suffix makes both guarantees structural instead of relying on the operator to remember: see
# the matching .gitignore rule (`*_en_oracle`).
TRANSLATED_NAME_SUFFIX = "_en_oracle"


def materialize(hf_split: str, name: str, *, limit: int | None = None,
                project_root: Path = PROJECT_ROOT,
                translate_oracle_literals: bool = False) -> dict:
    from parser_vs_oracle import load_hf_queries

    if translate_oracle_literals and not name.endswith(TRANSLATED_NAME_SUFFIX):
        raise ValueError(
            f"--translate-oracle-literals requires --name to end with "
            f"{TRANSLATED_NAME_SUFFIX!r} (got {name!r}) -- this labels the output as the new, "
            f"non-comparable register it is, and is what the matching .gitignore rule keys off "
            f"of to keep it from ever being committed."
        )

    ids, data = load_hf_queries("default", [hf_split])
    if limit:
        ids = ids[: int(limit)]

    translation_report = None
    mapping: dict[str, str] = {}
    if translate_oracle_literals:
        from phase2_oracle_literal_translation import build_map, translate_hard_logic

        mapping, map_meta = build_map()
        translation_report = {
            "map_entries": map_meta["entries"],
            "queries_changed": 0,
            "clauses_changed": 0,
            "queries_with_unmapped_residual": 0,
            "unmapped_residual_samples": {},  # uid -> sorted unmapped CJK runs, capped below
        }

    data_dir = project_root / "chinatravel" / "data" / "en" / name
    data_dir.mkdir(parents=True, exist_ok=True)
    for uid in ids:
        q = dict(data[uid])
        q["uid"] = uid
        out = {k: q.get(k) for k in KEEP if q.get(k) is not None}
        if translate_oracle_literals and out.get("hard_logic_py"):
            result = translate_hard_logic(out["hard_logic_py"], mapping)
            out["hard_logic_py"] = result["clauses"]
            if result["changed"]:
                translation_report["queries_changed"] += 1
                translation_report["clauses_changed"] += result["changed"]
            if result["unmapped"]:
                translation_report["queries_with_unmapped_residual"] += 1
                if len(translation_report["unmapped_residual_samples"]) < 50:
                    translation_report["unmapped_residual_samples"][uid] = result["unmapped"]
        (data_dir / f"{uid}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    split_file = project_root / "chinatravel" / "evaluation" / "default_splits" / f"{name}.txt"
    split_file.parent.mkdir(parents=True, exist_ok=True)
    split_file.write_text("\n".join(ids) + "\n", encoding="utf-8")
    out = {"name": name, "hf_split": hf_split, "n": len(ids),
           "data_dir": str(data_dir), "split_file": str(split_file)}
    if translation_report is not None:
        out["translation_report"] = translation_report
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hf-split", required=True,
                    choices=["easy", "medium", "human", "preference_base50"])
    ap.add_argument("--name", required=True, help="Local split name to create.")
    ap.add_argument("--limit", type=int, default=None, help="Take the first N uids (deterministic).")
    ap.add_argument("--translate-oracle-literals", action="store_true",
                    help="P23: rewrite hard_logic_py's Chinese literals through the verified "
                         "zh->en map. Evaluation-only; requires --name to end with "
                         f"'{TRANSLATED_NAME_SUFFIX}'.")
    ap.add_argument("--report-out", default=None,
                    help="With --translate-oracle-literals, also write the full per-query "
                         "translation report as JSON here (the printed summary caps residual "
                         "samples at 50 queries).")
    args = ap.parse_args()
    result = materialize(args.hf_split, args.name, limit=args.limit,
                          translate_oracle_literals=args.translate_oracle_literals)
    print(json.dumps(result, indent=2))
    if args.report_out and "translation_report" in result:
        Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_out).write_text(
            json.dumps(result["translation_report"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
