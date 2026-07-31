#!/usr/bin/env python3
"""Phase 2 monotonic regression gate (docs/tpc_phase2_eval.md).

Reuses the monotonic philosophy of scripts/merge.py: a candidate is promoted only if, on the
rehearsal fold, it does NOT drop the primary score metric or increase parse-failure / timeout
counts vs the baseline.

Metric dict shape: {"fpr": float, "continuous_score": float (optional), "parse_failures": int,
"timeouts": int}.

Primary score metric: when ``continuous_score`` is present in *both* rows, it is the blocking
check and ``fpr`` (if present) is advisory-only, not gating. Binary FPR can be dominated by
timeout-boundary nondeterminism at tight budgets or small folds, so it is not a reliable sole
promotion gate in that case. When ``continuous_score`` is absent from either row (older ledger
rows, or a caller that only has FPR), the gate falls back to FPR blocking. See
``docs/tpc_phase2_eval.md`` for the measurement contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check_gate(baseline: dict, candidate: dict, *, tol: float = 0.0) -> dict:
    """Return {'passed': bool, 'reasons': [...], 'advisories': [...]}.

    Passes when candidate is no worse than baseline on the blocking metrics. ``advisories``
    holds non-blocking notes (e.g. an FPR move that isn't gating because continuous_score took
    over as the primary metric) -- always present, may be empty.

    Refuses the comparison outright when the two rows carry a different (or one-sided)
    ``evaluator_parity`` marker: rows straddling the 2026-07-28 upstream evaluator change are
    never comparable (docs/tpc_phase2_eval.md#ledger-comparability, CLAUDE.md's upstream
    evaluator parity invariant), whatever the score deltas say. Rows that both omit the marker
    (every row recorded before it existed) fall through unchanged for backward compatibility.
    """
    reasons: list[str] = []
    advisories: list[str] = []

    base_parity = baseline.get("evaluator_parity")
    cand_parity = candidate.get("evaluator_parity")
    if (base_parity or cand_parity) and base_parity != cand_parity:
        reasons.append(
            "evaluator_parity mismatch: baseline="
            f"{base_parity!r} candidate={cand_parity!r} -- rows on different evaluator "
            "contracts are never comparable"
        )
        return {"passed": False, "reasons": reasons, "advisories": advisories}

    use_continuous = "continuous_score" in baseline and "continuous_score" in candidate
    if use_continuous:
        base_cs = float(baseline["continuous_score"])
        cand_cs = float(candidate["continuous_score"])
        if cand_cs < base_cs - tol:
            reasons.append(
                f"continuous_score dropped: {cand_cs:.2f} < {base_cs:.2f} (tol {tol})"
            )
        if "fpr" in baseline and "fpr" in candidate:
            base_fpr = float(baseline["fpr"])
            cand_fpr = float(candidate["fpr"])
            if cand_fpr < base_fpr - tol:
                advisories.append(
                    f"fpr dropped (advisory, not gating -- continuous_score is primary): "
                    f"{cand_fpr:.2f} < {base_fpr:.2f} (tol {tol})"
                )
    else:
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

    return {"passed": not reasons, "reasons": reasons, "advisories": advisories}


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
