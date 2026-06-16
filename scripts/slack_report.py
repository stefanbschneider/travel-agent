#!/usr/bin/env python
"""READ-ONLY DAV-slack analysis over the submission set.

For every passing plan in a method dir, walk the itinerary and estimate per-day "fillable" slack:
idle daytime minutes (morning gap + afternoon gap before 18:00) large enough for one more
attraction, on a day that is not already at 4 attractions. Cross-tabs fillable days by whether
the query carries a budget/time hard constraint (constraint-free fillable days are guaranteed-safe
DAV; constrained ones are gated by acceptance). Projects the DAV ceiling reachable by packing one
attraction into each constraint-free fillable day. Writes nothing.

Passing is read from each best plan's stored `_eval_score` (>=60 <=> all-pass: the non-all-pass
ceiling is 45 and the all-pass floor is 85, so the gap is empty and the proxy is exact).
"""
import argparse
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "chinatravel", "data", "en")
ATTR_CAP = 4          # DAV saturates at 4 attractions/day
SLOT_MIN = 130        # ~20 min transport + ~110 min visit: minimum idle for one more attraction
DAY_START, DAY_END = 9 * 60, 18 * 60   # daytime packing window


def t2m(t):
    try:
        h, m = map(int, str(t).split(":"))
        return h * 60 + m
    except Exception:
        return None


def data_index():
    idx = {}
    for d in os.listdir(DATA_DIR):
        dd = os.path.join(DATA_DIR, d)
        if not os.path.isdir(dd):
            continue
        for fn in os.listdir(dd):
            if fn.endswith(".json"):
                idx[fn[:-5]] = os.path.join(dd, fn)
    return idx


def day_slack(activities):
    """Return (attractions_today, fillable) for one day's activity list."""
    attrs = sum(1 for a in activities if a.get("type") == "attraction")
    starts = [t2m(a.get("start_time")) for a in activities if t2m(a.get("start_time")) is not None]
    ends = [t2m(a.get("end_time")) for a in activities if t2m(a.get("end_time")) is not None]
    if not starts:
        idle = DAY_END - DAY_START
    else:
        morning = max(0, min(starts) - DAY_START)
        last_day_end = max([e for e in ends if e <= DAY_END] or [DAY_START])
        afternoon = max(0, DAY_END - last_day_end)
        idle = morning + afternoon
    return attrs, (attrs < ATTR_CAP and idle >= SLOT_MIN)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--method", default="best")
    ap.add_argument("--split", default="tpc_phase1")
    ap.add_argument("--top", type=int, default=15, help="show this many highest-slack plans")
    args = ap.parse_args()

    split_file = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits", args.split + ".txt")
    with open(split_file) as f:
        uids = [l.strip() for l in f if l.strip()]
    method_dir = os.path.join(ROOT, "results", args.method)
    didx = data_index()

    passing = 0
    apd_hist = Counter()
    fillable_free = fillable_constrained = 0
    plans_with_free_slack = 0
    cur_attr_total = days_total = 0
    proj_attr_total = 0
    ranked = []

    for uid in uids:
        pf = os.path.join(method_dir, uid + ".json")
        if not os.path.exists(pf):
            continue
        with open(pf) as f:
            plan = json.load(f)
        if float(plan.get("_eval_score", 0)) < 60:   # not all-pass; excluded from DAV mean
            continue
        passing += 1
        itin = plan.get("itinerary", []) or []
        days = len(itin) or 1
        q = json.load(open(didx[uid])) if uid in didx else {}
        hl = " ".join(q.get("hard_logic_py", []) or [])
        constrained = ("cost" in hl) or ("budget" in hl) or ("time" in hl)

        attrs = free_days = 0
        for day in itin:
            a, fillable = day_slack(day.get("activities", []) or [])
            attrs += a
            if fillable:
                if constrained:
                    fillable_constrained += 1
                else:
                    fillable_free += 1
                    free_days += 1
        cur_attr_total += attrs
        days_total += days
        # project +1 attraction per constraint-free fillable day (capped at 4/day overall)
        proj_attr_total += min(ATTR_CAP * days, attrs + free_days)
        apd_hist[min(4, round(attrs / days))] += 1
        if free_days:
            plans_with_free_slack += 1
            ranked.append((free_days, attrs / days, days, uid))

    dav_now = 100.0 * cur_attr_total / (ATTR_CAP * days_total) if days_total else 0.0
    dav_proj = 100.0 * proj_attr_total / (ATTR_CAP * days_total) if days_total else 0.0

    print("method={} split={} passing_plans={}".format(args.method, args.split, passing))
    print("attractions/day rounded histogram (passing): {}".format(dict(sorted(apd_hist.items()))))
    print("\ncurrent DAV (passing)          : {:.2f}".format(dav_now))
    print("fillable days (constraint-free): {}".format(fillable_free))
    print("fillable days (budget/time-constrained, acceptance-gated): {}".format(fillable_constrained))
    print("passing plans with >=1 free fillable day: {} / {}".format(plans_with_free_slack, passing))
    print("projected DAV if each free fillable day gets +1 attraction: {:.2f}  (+{:.2f})".format(
        dav_proj, dav_proj - dav_now))
    print("=> overall-score headroom from constraint-free DAV packing: +{:.2f}".format(
        0.05 * (dav_proj - dav_now)))

    ranked.sort(reverse=True)
    print("\ntop {} highest-slack plans (free_fillable_days, attractions/day, days, uid):".format(args.top))
    for fd, apd, dy, uid in ranked[: args.top]:
        print("  {:2d}  {:.2f}  {}d  {}".format(fd, apd, dy, uid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
