#!/usr/bin/env python3
"""Per-clause C-LPR / FPR for a produced plan directory, split by oracle-literal language.

Same method as the 2026-08-06 generalization probe's
``e2e/cjk_artifact_correction.json``: the HF sets' ``hard_logic_py`` literals are native Chinese
(``自然风光``) while ``nature_language_en`` is English, and under ``en`` scoring the verifier's
``attraction_type()`` / ``restaurant_type()`` return English labels -- so a CJK-literal clause can
never pass whatever the parser does. Splitting the per-clause result by literal language separates
"our extractor missed it" from "this clause is unpassable in this language".

Usage::

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_clause_language_split.py \
        --split hf_medium_probe30 --method probe2_hfmedium30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from chinatravel.data.load_datasets import load_query
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    ids, data = load_query(argparse.Namespace(splits=args.split, lang=args.lang,
                                              oracle_translation=True))
    plan_dir = PROJECT_ROOT / "results" / args.method

    n_all = pass_all = 0
    n_ascii = pass_ascii = 0
    q_pass_all = q_pass_ascii = 0
    n_q = n_q_with_cjk = 0
    per_query = []
    for uid in ids:
        path = plan_dir / f"{uid}.json"
        if not path.exists():
            continue
        plan = json.loads(path.read_text(encoding="utf-8"))
        clauses = data[uid].get("hard_logic_py") or []
        try:
            results = evaluate_constraints_py(clauses, plan, verbose=False)
        except Exception:
            results = [False] * len(clauses)
        n_q += 1
        has_cjk = False
        ok_all = ok_ascii = True
        for clause, ok in zip(clauses, results):
            ascii_only = not _CJK.search(clause)
            has_cjk |= not ascii_only
            n_all += 1
            pass_all += bool(ok)
            ok_all &= bool(ok)
            if ascii_only:
                n_ascii += 1
                pass_ascii += bool(ok)
                ok_ascii &= bool(ok)
        n_q_with_cjk += has_cjk
        q_pass_all += ok_all
        q_pass_ascii += ok_ascii
        per_query.append({"uid": uid, "n_clauses": len(clauses),
                          "n_failed": sum(1 for r in results if not r)})

    out = {
        "split": args.split,
        "method": args.method,
        "n_queries": n_q,
        "n_queries_with_cjk_clause": n_q_with_cjk,
        "n_clauses": n_all,
        "n_clauses_cjk_literal": n_all - n_ascii,
        "clpr_all_clauses": round(100.0 * pass_all / n_all, 2) if n_all else 100.0,
        "clpr_ascii_only": round(100.0 * pass_ascii / n_ascii, 2) if n_ascii else 100.0,
        "fpr_all_clauses": round(100.0 * q_pass_all / n_q, 2) if n_q else 0.0,
        "fpr_ascii_only": round(100.0 * q_pass_ascii / n_q, 2) if n_q else 0.0,
        "per_query": per_query,
    }
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text[:1200])


if __name__ == "__main__":
    main()
