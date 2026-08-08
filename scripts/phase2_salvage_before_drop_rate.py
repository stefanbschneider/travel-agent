"""How many provably-unsatisfiable required-name values does the P22 R30 salvage-before-drop step
(`chinatravel.agent.phase2.normalize._salvage_catalog_name`) recover, versus how many still fall
through to a full drop?

Static, read-only, no solve, no LLM. Reuses
`scripts/phase2_unsatisfiable_names_probe.py`'s own `measure_set` to find the "unsatisfiable"
values (pre-drop) -- the exact same definition the drop rule and its probe already use
(`_exact_catalog_match`/`_match_catalog_name` both failing) -- then checks each one against the
salvage step. Instrument for
`docs/tpc_phase2_roadmap.md#p22--drop-provably-unsatisfiable-required-name-constraints`'s R30
follow-up.

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_salvage_before_drop_rate.py \\
        --out-dir results/phase2_baselines/screens/<date>_p22_salvage_before_drop
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SETS = (
    ("familiar_100 (control)", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
)


def measure() -> list[dict]:
    from chinatravel.agent.phase2.normalize import (_ENTITY_CATEGORY_FOR_FIELD,
                                                     _effective_catalog_names,
                                                     _salvage_catalog_name,
                                                     load_city_entity_catalog)
    from phase2_unsatisfiable_names_probe import measure_set

    rows = []
    for label, kind, name in SETS:
        report = measure_set(label, kind, name, entity_resolution=False,
                             drop_unsatisfiable_names=False, n_examples=10_000)
        salvaged, still_dropped, salvage_examples = 0, 0, []
        for ex in report["examples"]:
            catalog = load_city_entity_catalog(ex["target_city"])
            category = _ENTITY_CATEGORY_FOR_FIELD.get(ex["field"])
            pool = _effective_catalog_names(catalog, category) if category else []
            hit = _salvage_catalog_name(ex["value"], pool)
            if hit:
                salvaged += 1
                if len(salvage_examples) < 10:
                    salvage_examples.append({"uid": ex["uid"], "field": ex["field"],
                                             "before": ex["value"], "after": hit})
            else:
                still_dropped += 1
        rows.append({
            "set": label, "n": report["n"],
            "unsatisfiable_values_pre_fix": len(report["examples"]),
            "salvaged": salvaged, "still_dropped": still_dropped,
            "salvage_rate": round(salvaged / len(report["examples"]), 4) if report["examples"] else None,
            "salvage_examples": salvage_examples,
        })
    return rows


def render_markdown(rows: list[dict]) -> str:
    lines = [
        "# P22 R30 follow-up: salvage-before-drop rate",
        "",
        "| set | n | unsatisfiable values (pre-fix) | salvaged | still dropped | salvage rate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(f"| {r['set']} | {r['n']} | {r['unsatisfiable_values_pre_fix']} | "
                     f"{r['salvaged']} | {r['still_dropped']} | {r['salvage_rate']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=None, help="write report.json / summary.md here")
    args = ap.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    rows = measure()
    text = render_markdown(rows)
    print(text)
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        (out / "summary.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
