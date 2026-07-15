#!/usr/bin/env python3
"""Phase 2 timing + reliability telemetry (Axis 3 of docs/tpc_phase2_eval.md).

Aggregates the per-stage timings the orchestrator emits (``telemetry.json`` per query) into
per-stage p50/p95, flags budget overruns, and reports reliability counts (timed-out, used-fallback,
valid-output rate). ``score_variance`` summarizes run-to-run variance across repeated local runs;
record the repeat count with each measurement.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]

STAGES = ("parse", "solve", "improve", "finalize")


def percentile(values, p: float) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(np.percentile(values, p))


def aggregate_timings(telemetries: list[dict], *, budget_sec: float | None = None) -> dict:
    """Aggregate a list of telemetry dicts into per-stage p50/p95 + reliability counts."""
    n = len(telemetries)
    per_stage = {}
    for stage in STAGES:
        vals = [t.get("stage_sec", {}).get(stage, 0.0) for t in telemetries]
        per_stage[stage] = {
            "p50": percentile(vals, 50),
            "p95": percentile(vals, 95),
            "mean": float(statistics.fmean(vals)) if vals else 0.0,
            "max": max(vals) if vals else 0.0,
        }

    totals = [sum(t.get("stage_sec", {}).get(s, 0.0) for s in STAGES) for t in telemetries]
    overruns = 0
    for t, total in zip(telemetries, totals):
        b = budget_sec if budget_sec is not None else t.get("budget_sec")
        if b is not None and total > float(b):
            overruns += 1

    valid = sum(1 for t in telemetries if t.get("valid_output"))
    return {
        "n": n,
        "per_stage": per_stage,
        "total_p50": percentile(totals, 50),
        "total_p95": percentile(totals, 95),
        "budget_overruns": overruns,
        "timed_out": sum(1 for t in telemetries if t.get("timed_out")),
        "used_fallback": sum(1 for t in telemetries if t.get("used_fallback")),
        "valid_output_rate": (valid / n) if n else 0.0,
        "llm_parse_attempted": sum(1 for t in telemetries if t.get("flags", {}).get("llm_parse")),
        "llm_parse_failed": sum(1 for t in telemetries if t.get("llm_parse_error")),
    }


def aggregate_from_dir(work_dir: str, *, budget_sec: float | None = None) -> dict:
    """Read every ``telemetry.json`` under ``work_dir`` and aggregate."""
    telems = []
    for path in sorted(Path(work_dir).glob("**/telemetry.json")):
        try:
            telems.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return aggregate_timings(telems, budget_sec=budget_sec)


def score_variance(scores: list[float]) -> dict:
    """Run-to-run variance summary of a per-run score (e.g. FPR or valid-output rate)."""
    scores = [float(s) for s in scores]
    n = len(scores)
    return {
        "n": n,
        "mean": statistics.fmean(scores) if scores else 0.0,
        "stdev": statistics.pstdev(scores) if n >= 2 else 0.0,
        "min": min(scores) if scores else 0.0,
        "max": max(scores) if scores else 0.0,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-dir", required=True, help="Directory containing per-query telemetry.json files.")
    p.add_argument("--budget-sec", type=float, default=None, help="Override budget for overrun flagging.")
    p.add_argument(
        "--repeat-dirs", nargs="*", default=None,
        help="Optional extra run dirs; reports valid-output-rate variance across all runs.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    agg = aggregate_from_dir(args.work_dir, budget_sec=args.budget_sec)
    out = {"timing": agg}
    if args.repeat_dirs:
        dirs = [args.work_dir, *args.repeat_dirs]
        rates = [aggregate_from_dir(d, budget_sec=args.budget_sec)["valid_output_rate"] for d in dirs]
        out["valid_output_rate_variance"] = score_variance(rates)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
