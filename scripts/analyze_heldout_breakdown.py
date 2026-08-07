#!/usr/bin/env python3
"""Analyse the organizers' per-metric held-out breakdown, and price a coverage fix.

The Phase 2 leaderboard published the seven official metrics behind our aggregate, not just the
aggregate. That turns the earlier bounded inversion into a measurement, and it answers a question
the aggregate could not: **which weight are we earning, and what would it take to earn the rest?**

Three things this establishes, each printed with the arithmetic that supports it:

1. The published breakdown reproduces the published aggregate exactly, so the number is internally
   consistent and there is nothing to suspect about the scoring itself.
2. ``FPR = 0.0000`` is the *arithmetic consequence* of ``C-LPR = 55.2`` at familiar-100's clause
   density, not a separate failure. A query needs every clause to pass, so a 58% per-clause rate
   over ~11 clauses gives a fraction of a query per hundred. Do not go hunting for a second bug.
3. Because FPR carries weight 0.40 and gates all three preference terms, **55% of the total weight
   currently yields exactly zero**, and it stays near zero until the per-clause pass rate reaches
   roughly 0.75. That makes partial coverage fixes worth much less than a linear reading suggests,
   and full recovery worth much more.

The projection is a **sensitivity tool, not a prediction**. It has one fitted parameter (the
correlation factor between clause failures) calibrated at a single point, assumes clause
independence otherwise, and assumes the held-out clause density equals familiar-100's. Treat its
shape as informative and its absolute values as illustrative.

Usage::

    .venv/bin/python scripts/analyze_heldout_breakdown.py
    .venv/bin/python scripts/analyze_heldout_breakdown.py --clauses-per-query 8
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELDOUT = REPO / "results" / "phase2_baselines" / "heldout" / "20260807_v1_leaderboard.json"

#: Weights of the official aggregate (eval_tpc.py).
WEIGHTS = {
    "MicEPR": 0.10,
    "MacEPR": 0.10,
    "C-LPR": 0.25,
    "FPR": 0.40,
    "DAV": 0.05,
    "ATT": 0.05,
    "DDR": 0.05,
}

#: Clauses per query, measured on familiar-100 through load_query(oracle_translation=True).
FAMILIAR_CLAUSES_PER_QUERY = 11.09

#: (DAV+ATT+DDR)/FPR measured on R17. Preference terms are zeroed per failing query, so they
#: scale with FPR rather than varying independently.
PREF_SUM_PER_FPR_POINT = 1.95

#: The phrasing fix's measured effect on free prose, restricted to English-literal clauses -
#: the only clauses an English held-out set can contain.
FREE_PROSE_CLPR_BEFORE = 78.38
FREE_PROSE_CLPR_AFTER = 93.24


def aggregate(scores: dict[str, float]) -> float:
    """The official weighted sum."""
    return sum(WEIGHTS[k] * scores[k] for k in WEIGHTS)


def clause_pass_rate(clpr: float, macepr: float) -> float:
    """Per-clause pass rate on a commonsense-valid plan.

    C-LPR is the *conditional* logical micro: a plan failing commonsense contributes 0 regardless
    of how many clauses it satisfies. So the rate among plans that actually got scored is
    ``C-LPR / EPR-macro``.
    """
    return clpr / macepr


def project(
    p: float,
    *,
    macepr: float,
    micepr: float,
    clauses_per_query: float,
    correlation: float,
) -> tuple[float, float, float]:
    """Project (C-LPR, FPR, overall) from a per-clause pass rate.

    ``correlation`` scales the independence estimate of FPR. Clause failures cluster within a
    query (a missed budget breaks one clause, not a random one), so independence under-predicts
    FPR; the factor is calibrated on familiar-100.
    """
    clpr = 100.0 * p * (macepr / 100.0)
    fpr = min(100.0, 100.0 * (p**clauses_per_query) * correlation)
    scores = {
        "MicEPR": micepr,
        "MacEPR": macepr,
        "C-LPR": clpr,
        "FPR": fpr,
        "DAV": PREF_SUM_PER_FPR_POINT * fpr / 3.0,
        "ATT": PREF_SUM_PER_FPR_POINT * fpr / 3.0,
        "DDR": PREF_SUM_PER_FPR_POINT * fpr / 3.0,
    }
    return clpr, fpr, aggregate(scores)


def calibrate_correlation(local: dict[str, float], clauses_per_query: float) -> float:
    """Fit the one free parameter so the model reproduces the local row's FPR."""
    p = clause_pass_rate(local["C-LPR"], local["MacEPR"])
    independent = 100.0 * (p**clauses_per_query)
    return local["FPR"] / independent if independent > 0 else 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clauses-per-query",
        type=float,
        default=FAMILIAR_CLAUSES_PER_QUERY,
        help="assumed held-out clause density (default: familiar-100's measured %(default)s)",
    )
    args = parser.parse_args()
    k = args.clauses_per_query

    doc = json.loads(HELDOUT.read_text())
    held = doc["official_scores"]
    local = doc["comparable_local_row"]["official_scores"]

    print("=" * 78)
    print("1. The published breakdown is internally consistent")
    print("=" * 78)
    recomputed = aggregate(held)
    print(f"   recomputed {recomputed:.4f}   published {doc['best_score']:.4f}   "
          f"delta {abs(recomputed - doc['best_score']):.6f}")
    print("   -> nothing to suspect about the scoring; the breakdown explains the aggregate.")

    print()
    print("=" * 78)
    print("2. Which weight we earn, and which yields exactly zero")
    print("=" * 78)
    earned = 0.0
    for name, weight in WEIGHTS.items():
        value = held[name]
        if value > 0:
            earned += weight
        print(f"   {name:<8} weight {weight:.2f}   value {value:8.4f}   "
              f"contributes {weight * value:6.3f}")
    print(f"   -> we earn from {earned:.2f} of the weight; {1 - earned:.2f} yields exactly zero.")
    print("      FPR is 0.40 of the total AND gates all three preference terms (0.15),")
    print("      because a failing query scores 0 on every preference term.")

    print()
    print("=" * 78)
    print("3. Grounding generalised; constraint satisfaction did not")
    print("=" * 78)
    print(f"   {'metric':<10} {'held-out':>10} {'familiar-100':>14} {'delta':>9}")
    for name in ("MicEPR", "MacEPR", "C-LPR", "FPR"):
        print(f"   {name:<10} {held[name]:>10.4f} {local[name]:>14.4f} "
              f"{held[name] - local[name]:>+9.2f}")
    print("   -> EPR-micro is essentially unchanged: every fact we emit still grounds in the")
    print("      environment, on queries we have never seen. The collapse is entirely in")
    print("      knowing WHAT to satisfy, which is the constraint-extraction diagnosis.")
    print("      It also rules out an empty-plan or crashed-run explanation: empty plans")
    print("      cannot score EPR-micro 99.5.")

    p_held = clause_pass_rate(held["C-LPR"], held["MacEPR"])
    print()
    print("=" * 78)
    print("4. FPR = 0.0000 is a consequence of C-LPR, not a separate bug")
    print("=" * 78)
    print(f"   per-clause pass rate on a scored plan: p = {p_held:.4f}")
    print(f"   {'clauses/query':>14} {'p^k':>10} {'expected all-pass per 100':>27}")
    for kk in (5, 8, 11, 14):
        print(f"   {kk:>14} {p_held**kk:>10.5f} {100 * p_held**kk:>27.2f}")
    k_needed = math.log(0.005) / math.log(p_held)
    print(f"   -> FPR rounds to 0.0000 once k > {k_needed:.1f}; familiar-100 measures "
          f"{FAMILIAR_CLAUSES_PER_QUERY} clauses/query.")
    print("      So do not hunt for a second failure: one clause per query is enough to")
    print("      zero the query, and we miss ~42% of clauses.")

    correlation = calibrate_correlation(local, k)
    print()
    print("=" * 78)
    print(f"5. Projection (k={k} clauses/query, correlation factor {correlation:.3f})")
    print("=" * 78)
    c, f, o = project(
        clause_pass_rate(local["C-LPR"], local["MacEPR"]),
        macepr=local["MacEPR"], micepr=local["MicEPR"],
        clauses_per_query=k, correlation=correlation,
    )
    print(f"   calibration point (familiar-100): predicted C-LPR {c:.2f} FPR {f:.1f} "
          f"overall {o:.2f}")
    print(f"                                     measured  C-LPR {local['C-LPR']:.2f} "
          f"FPR {local['FPR']:.1f} overall {aggregate(local):.2f}")
    print("   ONE fitted parameter at ONE point: this is a sensitivity tool, not a prediction.")

    fail_before = 1 - FREE_PROSE_CLPR_BEFORE / 100
    fail_after = 1 - FREE_PROSE_CLPR_AFTER / 100
    removed = 1 - fail_after / fail_before
    print()
    print(f"   The phrasing fix removed {removed:.0%} of failing clauses on free prose")
    print(f"   (English-literal clause failure {fail_before:.1%} -> {fail_after:.1%}).")
    print("   How much of that transfers to the held-out set is unknown, so vary it:")
    print()
    print(f"   {'transfer of that reduction':>28} {'p':>7} {'C-LPR':>7} {'FPR':>7} "
          f"{'overall':>8} {'vs v1':>8}")
    fail_now = 1 - p_held
    rows = [("none (0%)", 0.0), ("15%", 0.15), ("35%", 0.35),
            ("69% - as measured", removed), ("full familiar-100 parity", None)]
    for label, frac in rows:
        p = clause_pass_rate(local["C-LPR"], local["MacEPR"]) if frac is None \
            else 1 - fail_now * (1 - frac)
        c, f, o = project(p, macepr=held["MacEPR"], micepr=held["MicEPR"],
                          clauses_per_query=k, correlation=correlation)
        print(f"   {label:>28} {p:>7.3f} {c:>7.2f} {f:>7.1f} {o:>8.2f} "
              f"{o - doc['best_score']:>+8.2f}")

    print()
    print("   Where the 0.40 FPR weight starts paying at all:")
    print(f"   {'p':>6} {'C-LPR':>7} {'FPR':>7} {'overall':>8}")
    for p in (0.60, 0.70, 0.75, 0.80, 0.85, 0.90):
        c, f, o = project(p, macepr=held["MacEPR"], micepr=held["MicEPR"],
                          clauses_per_query=k, correlation=correlation)
        print(f"   {p:>6.2f} {c:>7.2f} {f:>7.1f} {o:>8.2f}")
    print("   -> FPR is flat below p~0.75 and steep above it. A fix that lifts p a little")
    print("      buys only its C-LPR share (weight 0.25); one that lifts p past ~0.8 also")
    print("      unlocks the 0.55 of weight that is currently dead.")

    print()
    print("=" * 78)
    print("6. The cheap, certain part")
    print("=" * 78)
    cs_fail = 100 - held["MacEPR"]
    upside = 0.10 * cs_fail + 0.25 * (cs_fail / 100) * p_held * 100
    print(f"   EPR-macro {held['MacEPR']:.1f} means {cs_fail:.0f}% of plans fail commonsense and")
    print(f"   therefore also score 0 on C-LPR. Fixing all of them is worth at most "
          f"{upside:.2f} overall.")
    print("   Small, but it is the one component with no phrasing dependency at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
