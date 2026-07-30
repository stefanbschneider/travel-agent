#!/usr/bin/env python3
"""Per-query DAV/ATT/DDR diagnostic replicating eval_tpc.py DEFAULT_PR formulas.

DAV = attraction_count / (4*day_count)
ATT = clamp((-1/105)*avg_transport_time + 8/7), or 0 when the plan has no innercity transport
DDR = meal_count / (3*day_count)

All values clamped to [0,1]; here we also report the *unclamped* target gap so we can
see exactly which plans drag the mean down and by how much.
"""
import argparse
import glob
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clamp(v):
    return max(0.0, min(1.0, v))


def _mins(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def _trans_time(transports):
    total = 0
    for t in transports:
        total += _mins(t["end_time"]) - _mins(t["start_time"])
    return total


def score_plan(plan):
    days = len(plan["itinerary"])
    acts = [a for d in plan["itinerary"] for a in d["activities"]]
    n_attr = sum(1 for a in acts if a.get("type") == "attraction")
    n_meal = sum(1 for a in acts if a.get("type") in ("breakfast", "lunch", "dinner"))
    # transport hops: any activity whose `transports` is non-empty
    hops = [a for a in acts if a.get("transports")]
    trans_count = len(hops)
    time_cost = sum(_trans_time(a["transports"]) for a in hops)
    avg_time = time_cost / trans_count if trans_count > 0 else -1

    dav_raw = n_attr / (4 * days)
    ddr_raw = n_meal / (3 * days)
    # Upstream PR #30: a plan with no innercity transport scores 0, not 8/7.
    att_raw = ((-1.0 / 105.0) * avg_time + 8.0 / 7.0) if trans_count > 0 else 0.0
    return {
        "days": days,
        "n_attr": n_attr,
        "n_meal": n_meal,
        "n_hops": trans_count,
        "avg_trans_min": round(avg_time, 2) if trans_count > 0 else -1,
        "attr_per_day": round(n_attr / days, 3),
        "meal_per_day": round(n_meal / days, 3),
        "dav_raw": dav_raw,
        "ddr_raw": ddr_raw,
        "att_raw": att_raw,
        "dav": _clamp(dav_raw),
        "ddr": _clamp(ddr_raw),
        "att": _clamp(att_raw),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=os.path.join(ROOT, "results", "best"))
    ap.add_argument("--top", type=int, default=40, help="how many worst per metric to list")
    ap.add_argument("--metric", choices=["dav", "att", "ddr", "all"], default="all")
    ap.add_argument("--json", action="store_true", help="dump per-query rows to stdout as json")
    args = ap.parse_args()

    rows = []
    for path in glob.glob(os.path.join(args.dir, "*.json")):
        uid = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path) as f:
                plan = json.load(f)
        except Exception as e:
            print("skip", uid, e)
            continue
        s = score_plan(plan)
        s["uid"] = uid
        rows.append(s)

    n = len(rows)
    if n == 0:
        print("no plans found in", args.dir)
        return

    mean_dav = sum(r["dav"] for r in rows) / n * 100
    mean_att = sum(r["att"] for r in rows) / n * 100
    mean_ddr = sum(r["ddr"] for r in rows) / n * 100
    overall = 0.10 * 100 + 0.10 * 100 + 0.25 * 100 + 0.40 * 100 + 0.05 * mean_dav + 0.05 * mean_att + 0.05 * mean_ddr
    print("=" * 70)
    print(f"plans={n}  DAV={mean_dav:.4f}  ATT={mean_att:.4f}  DDR={mean_ddr:.4f}")
    print(f"overall(FPR=100 assumption) = {overall:.4f}")
    print(f"  DAV gap contrib = {0.05*(100-mean_dav):.4f}")
    print(f"  ATT gap contrib = {0.05*(100-mean_att):.4f}")
    print(f"  DDR gap contrib = {0.05*(100-mean_ddr):.4f}")
    print("=" * 70)

    # distribution histograms of per-day targets
    def histo(values, label, bins):
        c = Counter()
        for v in values:
            for lo, hi in bins:
                if lo <= v < hi:
                    c[(lo, hi)] += 1
                    break
        print(f"\n{label} distribution:")
        for lo, hi in bins:
            print(f"  [{lo:5.2f},{hi:5.2f}) : {c.get((lo,hi),0):4d}")

    histo([r["attr_per_day"] for r in rows], "attractions/day",
          [(0, 1), (1, 2), (2, 3), (3, 3.5), (3.5, 3.75), (3.75, 3.999), (3.999, 100)])
    histo([r["meal_per_day"] for r in rows], "meals/day",
          [(0, 1), (1, 2), (2, 2.5), (2.5, 2.667), (2.667, 2.999), (2.999, 100)])
    histo([r["avg_trans_min"] for r in rows if r["avg_trans_min"] >= 0], "avg_trans_min",
          [(0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 40), (40, 60), (60, 1000)])

    def show_worst(metric, top):
        rows_sorted = sorted(rows, key=lambda r: r[metric])[:top]
        print(f"\n--- worst {top} by {metric} (raw, per-day targets) ---")
        print(f"{'uid':22s} {'days':>4s} {'attr/d':>6s} {'meal/d':>6s} {'atmin':>6s} {'dav':>5s} {'att':>5s} {'ddr':>5s}")
        for r in rows_sorted:
            print(f"{r['uid']:22s} {r['days']:4d} {r['attr_per_day']:6.2f} {r['meal_per_day']:6.2f} "
                  f"{r['avg_trans_min']:6.1f} {r['dav']*100:5.1f} {r['att']*100:5.1f} {r['ddr']*100:5.1f}")

    if args.metric in ("dav", "all"):
        show_worst("dav", args.top)
    if args.metric in ("att", "all"):
        show_worst("att", args.top)
    if args.metric in ("ddr", "all"):
        show_worst("ddr", args.top)

    if args.json:
        print(json.dumps(rows))


if __name__ == "__main__":
    main()
