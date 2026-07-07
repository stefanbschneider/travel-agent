#!/usr/bin/env python3
"""Phase 2 monotonic regression gate (docs/tpc_phase2_eval.md).

Reuses the monotonic philosophy of scripts/merge.py: a candidate is promoted only if, on the
rehearsal fold, it does NOT drop official score (FPR) or increase parse-failure / timeout counts
vs the baseline.

Metric dict shape: {"fpr": float, "parse_failures": int, "timeouts": int}.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check_gate(baseline: dict, candidate: dict, *, tol: float = 0.0) -> dict:
    """Return {'passed': bool, 'reasons': [...]}. Passes when candidate is no worse than baseline."""
    reasons = []

    base_fpr = float(baseline.get("fpr", 0.0))
    cand_fpr = float(candidate.get("fpr", 0.0))
    if cand_fpr < base_fpr - tol:
        reasons.append(f"score/fpr dropped: {cand_fpr:.2f} < {base_fpr:.2f} (tol {tol})")

    base_pf = int(baseline.get("parse_failures", 0))
    cand_pf = int(candidate.get("parse_failures", 0))
    if cand_pf > base_pf:
        reasons.append(f"more parse_failures: {cand_pf} > {base_pf}")

    base_to = int(baseline.get("timeouts", 0))
    cand_to = int(candidate.get("timeouts", 0))
    if cand_to > base_to:
        reasons.append(f"more timeouts: {cand_to} > {base_to}")

    return {"passed": not reasons, "reasons": reasons}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, help="Baseline metrics JSON file.")
    p.add_argument("--candidate", required=True, help="Candidate metrics JSON file.")
    p.add_argument("--tol", type=float, default=0.0, help="Allowed score dip tolerance.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    res = check_gate(baseline, candidate, tol=args.tol)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
