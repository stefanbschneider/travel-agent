#!/usr/bin/env python
"""Read-only preference-deficit analysis over results/best.

Replicates eval_tpc's DAV/ATT/DDR formulas exactly from plan JSON (no chinatravel imports)
to locate where each preference metric loses points and whether the deficit is structural
(travel days, <4 POIs feasible) or addressable (search left score on the table).
"""
import glob
import json
import math
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEST = os.path.join(ROOT, "results", "best")
TRAVEL = ("airplane", "train")
MEALS = ("breakfast", "lunch", "dinner")


def clamp(v):
    return max(0.0, min(1.0, v))


def leg_minutes(tr):
    e, s = tr["end_time"], tr["start_time"]
    eh, em = int(e.split(":")[0]), int(e.split(":")[1])
    sh, sm = int(s.split(":")[0]), int(s.split(":")[1])
    return (eh - sh) * 60 + (em - sm)


def hop_minutes(transports):
    return sum(leg_minutes(t) for t in transports)


def analyze(plan):
    itin = plan.get("itinerary", []) or []
    dc = len(itin)
    if dc == 0:
        return None
    attrs = meals = 0
    hop_times = []
    per_day = []
    for di, day in enumerate(itin):
        acts = day.get("activities", []) or []
        d_attr = 0
        d_meals = set()
        for a in acts:
            t = a.get("type", "")
            if t == "attraction":
                attrs += 1
                d_attr += 1
            elif t in MEALS:
                meals += 1
                d_meals.add(t)
            tr = a.get("transports", []) or []
            if tr:
                hop_times.append(hop_minutes(tr))
        first_t = acts[0].get("type", "") if acts else ""
        last_t = acts[-1].get("type", "") if acts else ""
        per_day.append({
            "attr": d_attr,
            "meals": sorted(d_meals),
            "arrival_day": first_t in TRAVEL,
            "departure_day": last_t in TRAVEL,
        })
    dav = clamp(attrs / (4 * dc))
    if hop_times:
        avg = sum(hop_times) / len(hop_times)
        att = clamp((-1 / 105) * avg + 8 / 7)
    else:
        avg = -1
        att = clamp((-1 / 105) * avg + 8 / 7)
    ddr = clamp((meals / dc) / 3)
    return {
        "dc": dc, "attrs": attrs, "meals": meals,
        "dav": dav, "att": att, "ddr": ddr,
        "avg_hop": avg, "hop_times": hop_times, "per_day": per_day,
    }


def main():
    files = sorted(glob.glob(os.path.join(BEST, "*.json")))
    rows = {}
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                plan = json.load(fh)
        except Exception:
            continue
        r = analyze(plan)
        if r is not None:
            rows[os.path.basename(f)[:-5]] = r
    n = len(rows)
    print(f"plans={n}")
    for k in ("dav", "att", "ddr"):
        vals = [r[k] for r in rows.values()]
        mean = sum(vals) / len(vals)
        n_perfect = sum(1 for v in vals if v >= 0.999)
        deficit = sum(1 - v for v in vals)
        print(f"\n=== {k.upper()} mean={mean*100:.4f} perfect={n_perfect}/{n} "
              f"total_deficit={deficit:.3f} (=> +{deficit/n*0.05*100:.4f} overall if all->1)")

    # DAV detail: attractions per day
    print("\n--- DAV: attr/day buckets (per plan: attrs/dc) ---")
    apd = Counter()
    for r in rows.values():
        ratio = r["attrs"] / r["dc"]
        apd[round(ratio, 1)] += 1
    for kk in sorted(apd):
        print(f"  attr/day~{kk}: {apd[kk]}")
    short = [(k, r) for k, r in rows.items() if r["attrs"] < 4 * r["dc"]]
    print(f"  plans with <4 attr/day: {len(short)}")

    # DDR detail: which meals missing, and whether on travel days
    print("\n--- DDR: missing-meal days ---")
    miss_travel = miss_nontravel = 0
    miss_by_meal = Counter()
    total_missing_slots = 0
    for r in rows.values():
        for d in r["per_day"]:
            missing = [m for m in MEALS if m not in d["meals"]]
            total_missing_slots += len(missing)
            for m in missing:
                miss_by_meal[m] += 1
            if missing:
                if d["arrival_day"] or d["departure_day"]:
                    miss_travel += 1
                else:
                    miss_nontravel += 1
    print(f"  total missing meal-slots: {total_missing_slots}")
    print(f"  missing-meal days on travel days: {miss_travel}")
    print(f"  missing-meal days on NON-travel days: {miss_nontravel}  <-- addressable")
    print(f"  missing by meal type: {dict(miss_by_meal)}")

    # ATT detail
    print("\n--- ATT: hop time distribution ---")
    allhops = [h for r in rows.values() for h in r["hop_times"]]
    allhops.sort()
    if allhops:
        import statistics
        print(f"  hops={len(allhops)} mean={statistics.mean(allhops):.1f} "
              f"median={statistics.median(allhops):.1f} "
              f"p90={allhops[int(0.9*len(allhops))]:.0f} max={allhops[-1]:.0f}")
        over15 = sum(1 for h in allhops if h > 15)
        over30 = sum(1 for h in allhops if h > 30)
        print(f"  hops>15min: {over15} ({over15/len(allhops)*100:.1f}%)  "
              f"hops>30min: {over30} ({over30/len(allhops)*100:.1f}%)")
    n_att_imperfect = sum(1 for r in rows.values() if r["att"] < 0.999)
    print(f"  plans with ATT<1 (avg hop>15): {n_att_imperfect}")

    # worst tail per metric
    for k in ("dav", "att", "ddr"):
        worst = sorted(rows.items(), key=lambda kv: kv[1][k])[:8]
        print(f"\n--- worst {k.upper()} ---")
        for uid, r in worst:
            print(f"  {uid} {k}={r[k]:.3f} dc={r['dc']} attrs={r['attrs']} "
                  f"meals={r['meals']} avg_hop={r['avg_hop']:.1f}")


if __name__ == "__main__":
    main()
