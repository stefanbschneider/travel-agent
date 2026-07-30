#!/usr/bin/env python3
"""Compare per-plan DAV/ATT/DDR between two result dirs over a set of UIDs.

Usage:
  python3 scripts/compare_dirs.py --uids split.txt --old results/best --new results/..._method
  python3 scripts/compare_dirs.py --new results/..._method   # new vs best by default

Reports, for the UIDs present in --new, the metric delta vs --old (default results/best),
plus the aggregate mean delta and the implied overall-score delta on the full 1000-plan set.
"""
import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEST = os.path.join(ROOT, "results", "best")


def clamp(v):
    return max(0.0, min(1.0, v))


def mins(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def score_plan(plan):
    days = len(plan["itinerary"])
    acts = [a for d in plan["itinerary"] for a in d["activities"]]
    n_attr = sum(1 for a in acts if a.get("type") == "attraction")
    n_meal = sum(1 for a in acts if a.get("type") in ("breakfast", "lunch", "dinner"))
    hops = [a for a in acts if a.get("transports")]
    tc = len(hops)
    tt = 0
    for a in hops:
        for t in a["transports"]:
            try:
                tt += mins(t["end_time"]) - mins(t["start_time"])
            except Exception:
                pass
    avg = tt / tc if tc > 0 else -1
    dav = clamp(n_attr / (4 * days))
    ddr = clamp(n_meal / (3 * days))
    # Upstream PR #30: no innercity transport scores 0, not 1.0.
    att = clamp((-1.0 / 105.0) * avg + 8.0 / 7.0) if tc > 0 else 0.0
    return dav, att, ddr


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", required=True, help="new method dir")
    ap.add_argument("--old", default=BEST, help="old dir (default results/best)")
    ap.add_argument("--uids", default=None, help="split file; default = all uids in --new")
    args = ap.parse_args()

    if args.uids:
        with open(args.uids) as f:
            uids = [l.strip() for l in f if l.strip()]
    else:
        uids = [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(args.new, "*.json"))]

    n_better = n_worse = n_same = 0
    sum_dav = sum_att = sum_ddr = 0.0
    old_sum_dav = old_sum_att = old_sum_ddr = 0.0
    shown = 0
    for uid in uids:
        new_path = os.path.join(args.new, uid + ".json")
        old_path = os.path.join(args.old, uid + ".json")
        if not os.path.exists(new_path):
            continue
        new_plan = json.load(open(new_path))
        nd, na, ndd = score_plan(new_plan)
        if os.path.exists(old_path):
            old_plan = json.load(open(old_path))
            od, oa, odd = score_plan(old_plan)
        else:
            od = oa = odd = 0.0
        ddav = nd - od
        datt = na - oa
        dddr = ndd - odd
        # weighted per-query overall delta (0.05 each)
        dover = 0.05 * (ddav + datt + dddr) * 100
        sum_dav += nd; sum_att += na; sum_ddr += ndd
        old_sum_dav += od; old_sum_att += oa; old_sum_ddr += odd
        if dover > 1e-9:
            n_better += 1
        elif dover < -1e-9:
            n_worse += 1
        else:
            n_same += 1
        # show plans with notable change
        if abs(ddav) > 0.001 or abs(datt) > 0.001 or abs(dddr) > 0.001:
            if shown < 40:
                print("{:22s} DAV {:+6.1f} ATT {:+6.1f} DDR {:+6.1f}  (overall {:+.4f})".format(
                    uid, ddav * 100, datt * 100, dddr * 100, dover))
                shown += 1

    m = len(uids) or 1
    # Implied impact on the FULL 1000-plan mean: each plan's delta moves the global mean by delta/1000
    full_n = 1000
    gdav = (sum_dav - old_sum_dav) / full_n * 100
    gatt = (sum_att - old_sum_att) / full_n * 100
    gddr = (sum_ddr - old_sum_ddr) / full_n * 100
    gover = 0.05 * (gdav + gatt + gddr)
    print("=" * 64)
    print("plans compared: {}  better={} worse={} same={}".format(len(uids), n_better, n_worse, n_same))
    print("implied FULL-SET mean delta (these {} plans applied to 1000):".format(n_better + n_worse + n_same))
    print("  DAV {:+.4f}  ATT {:+.4f}  DDR {:+.4f}  -> overall {:+.5f}".format(gdav, gatt, gddr, gover))


if __name__ == "__main__":
    main()
