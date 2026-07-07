#!/usr/bin/env python3
"""Classify the residual DAV/DDR/ATT deficit in results/best by structural cause.

For each imperfect plan/day, decide whether the shortfall is:
  - travel-day bound: the day contains an intercity train/airplane leg that consumes
    most of the usable window (an attraction/meal cannot overlap it in time), or
  - idle: a non-travel day with a real free gap that could still hold more (addressable).
Also reports how many imperfect plans carry a dining-budget or cuisine hard constraint
(a structural cap on DDR/attraction spend), read from the query text.
"""
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEST = os.path.join(ROOT, "results", "best")
DATA = os.path.join(ROOT, "chinatravel", "data", "en")
MEALS = ("breakfast", "lunch", "dinner")
TRAVEL = ("airplane", "train")
BAND = {"breakfast": (6 * 60, 10 * 60), "lunch": (11 * 60, 14 * 60), "dinner": (16 * 60 + 30, 21 * 60)}


def mins(x):
    h, m = str(x).split(":")[:2]
    return int(h) * 60 + int(m)


def clamp(v):
    return max(0.0, min(1.0, v))


def gaps_of(acts):
    spans = []
    for a in acts:
        try:
            s, e = mins(a["start_time"]), mins(a["end_time"])
            if e > s:
                spans.append((s, e))
        except Exception:
            pass
    spans.sort()
    g = []
    cur = 0
    for s, e in spans:
        if s > cur:
            g.append((cur, s))
        cur = max(cur, e)
    if cur < 24 * 60:
        g.append((cur, 24 * 60))
    return g


_qcache = {}


def query_text(uid):
    if uid in _qcache:
        return _qcache[uid]
    txt = ""
    for d in os.listdir(DATA):
        p = os.path.join(DATA, d, uid + ".json")
        if os.path.exists(p):
            q = json.load(open(p))
            txt = str(q.get("nature_language", "") or q.get("nl", "") or "")
            break
    _qcache[uid] = txt
    return txt


def main():
    files = sorted(glob.glob(os.path.join(BEST, "*.json")))
    imperfect = 0
    by_days = {}
    dav_def_travelbound = dav_def_idle = 0.0
    ddr_def_travelbound = ddr_def_idle = 0.0
    dining_constrained = 0
    idle_attr_days = idle_meal_slots = 0
    idle_plan_examples = []
    for path in files:
        uid = os.path.basename(path)[:-5]
        plan = json.load(open(path))
        itin = plan.get("itinerary", []) or []
        dc = len(itin) or 1
        attrs = sum(1 for d in itin for a in d["activities"] if a.get("type") == "attraction")
        meals = sum(1 for d in itin for a in d["activities"] if a.get("type") in MEALS)
        dav = clamp(attrs / (4 * dc))
        ddr = clamp(meals / (3 * dc))
        if dav >= 0.999 and ddr >= 0.999:
            continue
        imperfect += 1
        by_days[dc] = by_days.get(dc, 0) + 1
        qt = query_text(uid)
        if re.search(r"dining", qt, re.I) and re.search(r"budget", qt, re.I):
            dining_constrained += 1
        plan_has_idle = False
        for day in itin:
            acts = day.get("activities", []) or []
            is_travel = any(a.get("type") in TRAVEL for a in acts)
            d_attr = sum(1 for a in acts if a.get("type") == "attraction")
            d_meals = {a.get("type") for a in acts if a.get("type") in MEALS}
            g = gaps_of(acts)
            # DAV shortfall this day (toward 4)
            attr_short = max(0, 4 - d_attr) / (4 * dc)
            # can we fit another attraction (>=75 min gap not overlapping travel)?
            free_big = any(ge - gs >= 75 for gs, ge in g)
            if d_attr < 4:
                if is_travel or not free_big:
                    dav_def_travelbound += attr_short
                else:
                    dav_def_idle += attr_short
                    idle_attr_days += 1
                    plan_has_idle = True
            # DDR shortfall
            for kind in MEALS:
                if kind in d_meals:
                    continue
                slot = 1.0 / (3 * dc)
                blo, bhi = BAND[kind]
                fits = any(min(ge, bhi) - max(gs, blo) >= 60 for gs, ge in g)
                if is_travel or not fits:
                    ddr_def_travelbound += slot
                else:
                    ddr_def_idle += slot
                    idle_meal_slots += 1
                    plan_has_idle = True
        if plan_has_idle and len(idle_plan_examples) < 20:
            idle_plan_examples.append(uid)

    n = len(files)
    print("imperfect plans (DAV or DDR <1): {}".format(imperfect))
    print("  by day-count: {}".format(dict(sorted(by_days.items()))))
    print("  imperfect plans with a dining-budget/cuisine constraint: {}".format(dining_constrained))
    print()
    print("DAV deficit decomposition (overall-pts if recovered, x0.05):")
    print("  travel-bound / no-gap (structural) = +{:.4f}".format(dav_def_travelbound / n * 100 * 0.05))
    print("  idle non-travel gap (ADDRESSABLE)   = +{:.4f}  across {} day(s)".format(
        dav_def_idle / n * 100 * 0.05, idle_attr_days))
    print("DDR deficit decomposition:")
    print("  travel-bound / no-gap (structural) = +{:.4f}".format(ddr_def_travelbound / n * 100 * 0.05))
    print("  idle non-travel gap (ADDRESSABLE)   = +{:.4f}  across {} slot(s)".format(
        ddr_def_idle / n * 100 * 0.05, idle_meal_slots))
    print()
    print("plans with any idle (addressable) headroom, e.g.: {}".format(idle_plan_examples))


if __name__ == "__main__":
    main()
