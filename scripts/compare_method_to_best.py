#!/usr/bin/env python
"""Compare a sparse smoke method directory against results/best.

This is read-only. It computes eval_tpc's DAV/ATT/DDR formulas directly from plan JSON and
estimates full-leaderboard overall delta using denominator=1000 by default. Densify/solve
smoke outputs are already checker-gated by the producer; this script only quantifies preference
changes before deciding whether to run a full merge/score.
"""
import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEST = os.path.join(ROOT, "results", "best")


def _minutes(t):
    h, m = str(t).split(":")[:2]
    return int(h) * 60 + int(m)


def _leg_minutes(leg):
    try:
        return _minutes(leg["end_time"]) - _minutes(leg["start_time"])
    except Exception:
        return 0


def _pref(plan):
    days = len(plan.get("itinerary", []) or [])
    if days <= 0:
        return 0.0, 0.0, 0.0, 0, 0, -1.0
    attrs = meals = 0
    hops = []
    for day in plan.get("itinerary", []) or []:
        for act in day.get("activities", []) or []:
            typ = act.get("type")
            if typ == "attraction":
                attrs += 1
            elif typ in ("breakfast", "lunch", "dinner"):
                meals += 1
            transports = act.get("transports", []) or []
            if transports:
                hops.append(sum(_leg_minutes(leg) for leg in transports))
    dav = max(0.0, min(1.0, attrs / (4.0 * days)))
    ddr = max(0.0, min(1.0, meals / (3.0 * days)))
    avg = sum(hops) / len(hops) if hops else -1.0
    # Upstream PR #30: no innercity transport scores 0, not 1.0.
    att = max(0.0, min(1.0, (-1.0 / 105.0) * avg + 8.0 / 7.0)) if avg >= 0 else 0.0
    return dav, att, ddr, attrs, meals, avg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--method", required=True, help="method dir name under results/")
    ap.add_argument("--denominator", type=int, default=1000, help="leaderboard plan denominator")
    ap.add_argument("--examples", type=int, default=20)
    args = ap.parse_args()

    method_dir = os.path.join(ROOT, "results", args.method)
    rows = []
    for path in sorted(glob.glob(os.path.join(method_dir, "*.json"))):
        uid = os.path.basename(path)[:-5]
        best_path = os.path.join(BEST, uid + ".json")
        if not os.path.exists(best_path):
            continue
        with open(path, encoding="utf-8") as f:
            cand = json.load(f)
        with open(best_path, encoding="utf-8") as f:
            base = json.load(f)
        cp = _pref(cand)
        bp = _pref(base)
        delta = (cp[0] - bp[0], cp[1] - bp[1], cp[2] - bp[2])
        rows.append((sum(delta), uid, delta, cp, bp))

    rows.sort(reverse=True)
    sdav = sum(r[2][0] for r in rows)
    satt = sum(r[2][1] for r in rows)
    sddr = sum(r[2][2] for r in rows)
    overall = 5.0 * (sdav + satt + sddr) / float(args.denominator)
    print(f"method={args.method} compared={len(rows)} denominator={args.denominator}")
    print(f"sum_delta_components dav={sdav:.6f} att={satt:.6f} ddr={sddr:.6f}")
    print(f"estimated_full_overall_delta={overall:.6f}")
    print("top_examples:")
    for _score, uid, delta, cp, bp in rows[: args.examples]:
        print(
            f"  {uid} dDAV={delta[0]*100:.3f} dATT={delta[1]*100:.3f} dDDR={delta[2]*100:.3f} "
            f"cand(attrs={cp[3]}, meals={cp[4]}, avg={cp[5]:.1f}) "
            f"base(attrs={bp[3]}, meals={bp[4]}, avg={bp[5]:.1f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
