#!/usr/bin/env python3
"""Sweep Phase 2 per-query budgets and export attribution metrics.

Runs `scripts/rehearse_phase2.py` programmatically in `--mode both` for each budget
and writes one CSV row per budget:

- solver_only_fpr
- end_to_end_fpr
- ceiling_fpr
- solver_headroom (ceiling - solver_only)
- parsing_loss (solver_only - end_to_end)

Usage:
    .venv/bin/python scripts/phase2_budget_sweep.py
    .venv/bin/python scripts/phase2_budget_sweep.py --budgets 30,60,120,300,900 --limit 20
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHINATRAVEL_ROOT = PROJECT_ROOT / "chinatravel"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(CHINATRAVEL_ROOT) not in sys.path:
    # Some solver-only imports use `from agent...`; include chinatravel/ on sys.path.
    sys.path.insert(0, str(CHINATRAVEL_ROOT))

import rehearse_phase2 as rehearse_mod  # noqa: E402


def parse_budgets(raw: str) -> list[float]:
    values: list[float] = []
    for token in raw.split(","):
        text = token.strip()
        if not text:
            continue
        value = float(text)
        if value <= 0:
            raise ValueError(f"budget must be > 0, got {value}")
        values.append(value)
    if not values:
        raise ValueError("No budgets provided")
    return values


def one_row(report: dict, *, budget_sec: float) -> dict:
    ceiling = float(report.get("ceiling", {}).get("fpr", 0.0))
    solver_only = float(report.get("modes", {}).get("solver-only", {}).get("fpr", 0.0))
    end_to_end = float(report.get("modes", {}).get("end-to-end", {}).get("fpr", 0.0))
    return {
        "budget_sec": budget_sec,
        "split_name": report.get("split_name", ""),
        "fold": int(report.get("fold", 0)),
        "folds": int(report.get("folds", 0)),
        "n": int(report.get("n", 0)),
        "ceiling_fpr": ceiling,
        "solver_only_fpr": solver_only,
        "end_to_end_fpr": end_to_end,
        "solver_headroom": ceiling - solver_only,
        "parsing_loss": solver_only - end_to_end,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budgets", default="30,60,120,300,900")
    p.add_argument("--split-set", choices=["val", "test"], default="val")
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--folds", type=int, default=rehearse_mod.DEFAULT_FOLDS)
    p.add_argument("--seed", type=int, default=rehearse_mod.DEFAULT_SEED)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--lang", choices=["en", "zh"], default="en")
    p.add_argument(
        "--out-csv",
        default=str(PROJECT_ROOT / "cache" / "phase2_budget_sweep" / "budget_sweep.csv"),
        help="CSV path for sweep rows",
    )
    p.add_argument(
        "--out-json",
        default=str(PROJECT_ROOT / "cache" / "phase2_budget_sweep" / "budget_sweep.json"),
        help="JSON path for full reports",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    budgets = parse_budgets(args.budgets)
    rows: list[dict] = []
    reports: list[dict] = []

    for budget_sec in budgets:
        print(f"[budget={budget_sec:.1f}s] running both modes...")
        report = rehearse_mod.rehearse(
            modes=("end-to-end", "solver-only"),
            split_set=args.split_set,
            fold=args.fold,
            folds=args.folds,
            seed=args.seed,
            budget_sec=budget_sec,
            limit=args.limit,
            lang=args.lang,
        )
        reports.append(report)
        row = one_row(report, budget_sec=budget_sec)
        rows.append(row)
        print(
            "  "
            f"ceiling={row['ceiling_fpr']:.1f} "
            f"solver={row['solver_only_fpr']:.1f} "
            f"e2e={row['end_to_end_fpr']:.1f} "
            f"headroom={row['solver_headroom']:.1f} "
            f"parse_loss={row['parsing_loss']:.1f}"
        )

    out_csv = Path(args.out_csv)
    out_json = Path(args.out_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "budget_sec",
        "split_name",
        "fold",
        "folds",
        "n",
        "ceiling_fpr",
        "solver_only_fpr",
        "end_to_end_fpr",
        "solver_headroom",
        "parsing_loss",
    ]
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    out_json.write_text(json.dumps({"rows": rows, "reports": reports}, indent=2), encoding="utf-8")
    print(f"Wrote CSV: {out_csv}")
    print(f"Wrote JSON: {out_json}")


if __name__ == "__main__":
    main()
