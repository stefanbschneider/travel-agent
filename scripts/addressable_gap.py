#!/usr/bin/env python3
"""Estimate ADDRESSABLE preference gaps in results/best.

For DDR: count, per plan, how many of {breakfast,lunch,dinner} per day are MISSING and
whether a >=45min free gap exists inside the meal's allowed time band
  breakfast band 06:00-10:00, lunch band 11:00-14:00, dinner band 16:30-21:00.
A meal is "addressable" if missing AND a free gap overlaps its band.

For ATT: count walk-mode hops whose duration > 15 min (upgrade candidates).
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEST = os.path.join(ROOT, "results", "best")
BAND = {"breakfast": (6 * 60, 10 * 60), "lunch": (11 * 60, 14 * 60), "dinner": (16 * 60 + 30, 21 * 60)}


def mins(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def day_gaps(activities):
    spans = []
    for a in activities:
        try:
            s = mins(a.get("start_time"))
            e = mins(a.get("end_time"))
            if e > s:
                spans.append((s, e))
        except Exception:
            continue
    spans.sort()
    gaps = []
    cur = 0
    for s, e in spans:
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < 24 * 60:
        gaps.append((cur, 24 * 60))
    return gaps


def main():
    files = sorted(glob.glob(os.path.join(BEST, "*.json")))
    total_days = 0
    meals_missing_total = 0
    meals_addressable_total = 0
    walk_long_hops = 0
    walk_long_plan_count = 0
    per_plan_addr = []
    for path in files:
        with open(path) as f:
            plan = json.load(f)
        itin = plan.get("itinerary", []) or []
        addr_for_plan = 0
        for day in itin:
            total_days += 1
            acts = day.get("activities", []) or []
            present = {a.get("type") for a in acts}
            gaps = day_gaps(acts)
            for kind, (blo, bhi) in BAND.items():
                if kind in present:
                    continue
                meals_missing_total += 1
                for gs, ge in gaps:
                    os_, oe = max(gs, blo), min(ge, bhi)
                    if oe - os_ >= 45:
                        meals_addressable_total += 1
                        addr_for_plan += 1
                        break
            had_long = False
            for a in acts:
                for t in a.get("transports", []) or []:
                    if str(t.get("mode", "")).lower() == "walk":
                        try:
                            d = mins(t.get("end_time")) - mins(t.get("start_time"))
                        except Exception:
                            d = 0
                        if d > 15:
                            walk_long_hops += 1
                            had_long = True
            if had_long:
                walk_long_plan_count += 1
        if addr_for_plan:
            per_plan_addr.append((os.path.basename(path)[:-5], addr_for_plan))

    print("plans={} days={}".format(len(files), total_days))
    print("meals missing total   = {}".format(meals_missing_total))
    print("meals addressable     = {}  (free >=45min gap in band)".format(meals_addressable_total))
    ddr_uplift = meals_addressable_total / (3 * total_days) * 100
    print("  -> DDR uplift if all addressable meals added = +{:.3f} pts".format(ddr_uplift))
    print("  -> overall uplift (x0.05) = +{:.4f}".format(ddr_uplift * 0.05))
    print()
    print("walk hops >15min      = {} across {} plans".format(walk_long_hops, walk_long_plan_count))
    print()
    per_plan_addr.sort(key=lambda x: -x[1])
    print("top 15 plans by addressable meals:")
    for uid, c in per_plan_addr[:15]:
        print("  {}  +{} meals possible".format(uid, c))


if __name__ == "__main__":
    main()
