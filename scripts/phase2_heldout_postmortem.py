#!/usr/bin/env python3
"""Post-competition held-out postmortem: per-constraint-family pass rates and familiar-100 coverage.

Retrospective, evaluation-only (R38 in docs/tpc_phase2_eval.md). The official held-out CSV
(``LAMDA-NeSy/ChinaTravel`` ``phase2/competition_test.csv``, see
``scripts/materialize_official_heldout_test.py``) carries a ``constraint_keys`` column -- one of the
organizers' 53 generator template keys per ``hard_logic_py`` clause -- which the materialized
per-query JSON drops. This script uses it to answer three questions the leaderboard cannot:

1. **Distribution:** which of the 53 keys does familiar-100 exercise at all? Familiar-100 has no
   ``constraint_keys``, so each of its clauses is mapped to a key by the clause's code *shape*
   (literals stripped, activity-type literals kept), learned from the held-out CSV.
2. **Where the points went:** per key, how many held-out clauses a produced plan directory passes.
3. **Near misses:** for each query failing exactly one clause, which key it is (the P28 question).

    .venv/bin/python scripts/materialize_official_heldout_test.py
    .venv/bin/python scripts/phase2_heldout_postmortem.py --csv <competition_test.csv> \\
        --plans <results/<method>> --out <file.json>

``--plans`` is optional; without it only the distribution comparison is produced. Never commit the
CSV or the materialized split: they are the competition answer key (``hf_*`` .gitignore rule).
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAMILIAR_DIR = PROJECT_ROOT / "chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data"
_ACTIVITY_WORDS = {"attraction", "accommodation", "breakfast", "lunch", "dinner", "airplane",
                   "train", "metro", "taxi", "walk"}


def clause_shape(code: str) -> str:
    """The clause's code with entity/number literals abstracted, activity-type literals kept."""

    def lit(m: re.Match) -> str:
        inner = m.group(0)[1:-1]
        return m.group(0) if inner in _ACTIVITY_WORDS else "S"

    s = re.sub(r'"[^"]*"|\'[^\']*\'', lit, code)
    s = re.sub(r"\{S(, S)*\}", "{S}", s)
    s = re.sub(r"\[S(, S)*\]", "[S]", s)
    s = re.sub(r"\d+(\.\d+)?", "N", s)
    return re.sub(r"\s+", " ", s).strip()


def load_csv_rows(path: Path) -> list[dict]:
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["hard_logic_py"] = json.loads(r["hard_logic_py"])
        r["constraint_keys"] = json.loads(r["constraint_keys"])
    return rows


def shape_to_key(rows: list[dict]) -> dict[str, str]:
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in rows:
        for code, key in zip(r["hard_logic_py"], r["constraint_keys"]):
            votes[clause_shape(code)][key] += 1
    return {s: c.most_common(1)[0][0] for s, c in votes.items()}


def familiar_keys(mapping: dict[str, str]) -> tuple[collections.Counter, int]:
    counts: collections.Counter = collections.Counter()
    unmapped = 0
    for f in sorted(glob.glob(str(FAMILIAR_DIR / "*.json"))):
        if f.endswith("_provenance.json"):
            continue
        for code in json.loads(Path(f).read_text(encoding="utf-8")).get("hard_logic_py", []):
            key = mapping.get(clause_shape(code))
            if key is None:
                unmapped += 1
            else:
                counts[key] += 1
    return counts, unmapped


def score_plans(rows: list[dict], plan_dir: Path) -> dict:
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    per_key = collections.defaultdict(lambda: [0, 0])  # key -> [passed, total]
    sole = collections.Counter()
    n_failed_hist = collections.Counter()
    missing = 0
    for r in rows:
        path = plan_dir / f"{r['uid']}.json"
        if not path.exists():
            missing += 1
            results = [False] * len(r["hard_logic_py"])
        else:
            plan = json.loads(path.read_text(encoding="utf-8"))
            try:
                results = evaluate_constraints_py(r["hard_logic_py"], plan, verbose=False)
            except Exception:
                results = [False] * len(r["hard_logic_py"])
        failed = [k for k, ok in zip(r["constraint_keys"], results) if not ok]
        for k, ok in zip(r["constraint_keys"], results):
            per_key[k][0] += bool(ok)
            per_key[k][1] += 1
        n_failed_hist[len(failed)] += 1
        if len(failed) == 1:
            sole[failed[0]] += 1
    total_pass = sum(p for p, _ in per_key.values())
    total = sum(t for _, t in per_key.values())
    return {
        "missing_plans": missing,
        "clause_pass_rate": round(100.0 * total_pass / total, 2) if total else None,
        "queries_all_pass": n_failed_hist.get(0, 0),
        "failed_clauses_per_query_histogram": dict(sorted(n_failed_hist.items())),
        "sole_failure_key": dict(sole.most_common()),
        "per_key": {k: {"passed": p, "total": t, "rate": round(100.0 * p / t, 1)}
                    for k, (p, t) in sorted(per_key.items(), key=lambda kv: -kv[1][1])},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, type=Path, help="phase2/competition_test.csv")
    ap.add_argument("--plans", type=Path, default=None, help="directory of <uid>.json plans")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rows = [r for r in load_csv_rows(args.csv)
            if r.get("official_phase2_evaluation", "true").strip().lower() == "true"]
    mapping = shape_to_key(rows)
    heldout = collections.Counter(k for r in rows for k in r["constraint_keys"])
    fam, fam_unmapped = familiar_keys(mapping)
    n_clauses = sum(heldout.values())
    unseen = {k: v for k, v in heldout.items() if k not in fam}
    out = {
        "heldout": {
            "queries": len(rows),
            "clauses": n_clauses,
            "clauses_per_query": round(n_clauses / len(rows), 2),
            "distinct_keys": len(heldout),
            "or_clauses": heldout.get("either_requirement", 0),
        },
        "familiar_100": {
            "clauses": sum(fam.values()) + fam_unmapped,
            "unmapped_clauses": fam_unmapped,
            "distinct_keys": len(fam),
            "or_clauses": fam.get("either_requirement", 0),
        },
        "heldout_clauses_in_keys_absent_from_familiar": sum(unseen.values()),
        "heldout_share_in_keys_absent_from_familiar": round(100.0 * sum(unseen.values()) / n_clauses, 1),
        "keys": {k: {"heldout": v, "familiar": fam.get(k, 0)} for k, v in heldout.most_common()},
    }
    if args.plans is not None:
        out["plans"] = str(args.plans)
        out["scored"] = score_plans(rows, args.plans)
        per_key = out["scored"]["per_key"]
        seen_p = sum(v["passed"] for k, v in per_key.items() if k in fam)
        seen_t = sum(v["total"] for k, v in per_key.items() if k in fam)
        un_p = sum(v["passed"] for k, v in per_key.items() if k not in fam)
        un_t = sum(v["total"] for k, v in per_key.items() if k not in fam)
        out["scored"]["pass_rate_keys_seen_in_familiar"] = round(100.0 * seen_p / seen_t, 1)
        out["scored"]["pass_rate_keys_absent_from_familiar"] = round(100.0 * un_p / un_t, 1)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
