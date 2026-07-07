#!/usr/bin/env python3
"""Estimate the ACHIEVABLE preference ceiling for results/best.

Separates the DAV/DDR deficit into structural (bound by intercity travel time,
an activity cannot overlap an intercity train/flight) vs addressable (a real free
time gap exists where an attraction/meal could still be inserted). Heuristic upper
bound; the real evaluator (space/time/open-hours + hard constraints) is stricter.
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEST = os.path.join(ROOT, "results", "best")
MEALS = ("breakfast", "lunch", "dinner")
BAND = {"breakfast": (6 * 60, 10 * 60), "lunch": (11 * 60, 14 * 60), "dinner": (16 * 60 + 30, 21 * 60)}


def mins(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def clamp(v):
    return max(0.0, min(1.0, v))


def day_spans(acts):
    spans = []
    for a in acts:
        try:
            s = mins(a.get("start_time"))
            e = mins(a.get("end_time"))
            if e > s:
                spans.append((s, e))
        except Exception:
            continue
    spans.sort()
    return spans


def free_gaps(spans):
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
    n = len(files)
    dav_now = ddr_now = att_now = 0.0
    dav_ceil = ddr_ceil = 0.0
    addr_attr_slots = addr_meal_slots = 0
    for path in files:
        with open(path) as f:
            plan = json.load(f)
        itin = plan.get("itinerary", []) or []
        dc = len(itin) or 1
        attrs = meals = 0
        hop_times = []
        cap_attr = cap_meal = 0
        for day in itin:
            acts = day.get("activities", []) or []
            d_attr = sum(1 for a in acts if a.get("type") == "attraction")
            d_meals = {a.get("type") for a in acts if a.get("type") in MEALS}
            attrs += d_attr
            meals += len(d_meals)
            for a in acts:
                for t in a.get("transports", []) or []:
                    try:
                        hop_times.append(mins(t["end_time"]) - mins(t["start_time"]))
                    except Exception:
                        pass
            gaps = free_gaps(day_spans(acts))
            free_min = sum(ge - gs for gs, ge in gaps)
            insertable = 0
            remaining = free_min
            while d_attr + insertable < 4 and remaining >= 75:
                insertable += 1
                remaining -= 75
            cap_attr += min(4, d_attr + insertable)
            addr_attr_slots += max(0, min(4, d_attr + insertable) - d_attr)
            day_cap_meals = len(d_meals)
            for kind in MEALS:
                if kind in d_meals:
                    continue
                blo, bhi = BAND[kind]
                for gs, ge in gaps:
                    if min(ge, bhi) - max(gs, blo) >= 60:
                        day_cap_meals += 1
                        addr_meal_slots += 1
                        break
            cap_meal += min(3, day_cap_meals)
        dav_now += clamp(attrs / (4 * dc))
        ddr_now += clamp(meals / (3 * dc))
        dav_ceil += clamp(cap_attr / (4 * dc))
        ddr_ceil += clamp(cap_meal / (3 * dc))
        att_now += clamp((-1 / 105) * (sum(hop_times) / len(hop_times)) + 8 / 7) if hop_times else clamp(8 / 7)

    print("plans={}".format(n))
    print("DAV now={:.4f}  heuristic ceiling={:.4f}  addressable attr-slots={}".format(
        dav_now / n * 100, dav_ceil / n * 100, addr_attr_slots))
    print("DDR now={:.4f}  heuristic ceiling={:.4f}  addressable meal-slots={}".format(
        ddr_now / n * 100, ddr_ceil / n * 100, addr_meal_slots))
    print("ATT now={:.4f}".format(att_now / n * 100))
    dav_gain = (dav_ceil - dav_now) / n * 100
    ddr_gain = (ddr_ceil - ddr_now) / n * 100
    print("max DAV overall uplift = +{:.4f}".format(dav_gain * 0.05))
    print("max DDR overall uplift = +{:.4f}".format(ddr_gain * 0.05))
    print("heuristic addressable overall headroom (DAV+DDR) = +{:.4f}".format((dav_gain + ddr_gain) * 0.05))


if __name__ == "__main__":
    main()
