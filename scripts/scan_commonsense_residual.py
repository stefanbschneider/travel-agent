#!/usr/bin/env python
"""Stdlib-only structural scan for the two 2026-07-28 commonsense rules (repeated meal types,
intra-day chronology) plus the other structural families the official checker enforces.

No WorldEnv, no solve, no dependencies beyond the stdlib -- reads plan JSON directly out of
results/best (or an explicit split) and flags each plan against six structural families:

  repeated_meal                    -- more than one activity of the same meal type in one day
  overlap                          -- an activity's start_time precedes the previous activity's end_time
  transport_before_prev_end        -- an inbound transport leg starts before the previous activity ends
  single_day_trailing_stay         -- a single-day itinerary whose final activity is an accommodation
  missing_intercity_endpoint       -- itinerary missing an intercity head or tail activity
  missing_accommodation_nonfinal_day -- a multi-day itinerary with a non-final day lacking an accommodation

See docs/tpc_shortcomings_and_plan.md Appendix 7.1 for the finding this script reproduces.
"""
import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
BEST_DIR = os.path.join(ROOT, "results", "best")

FAMILIES = [
    "transport_before_prev_end",
    "overlap",
    "repeated_meal",
    "single_day_trailing_stay",
    "missing_intercity_endpoint",
    "missing_accommodation_nonfinal_day",
]

_MEAL_TYPES = ("breakfast", "lunch", "dinner")
_INTERCITY_TYPES = ("airplane", "train")


def _time_to_minutes(t):
    h, m = str(t).split(":")
    return int(h) * 60 + int(m)


def _read_uids(split):
    path = os.path.join(SPLIT_DIR, split + ".txt")
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def flag_plan(plan):
    """Return the set of structural families this plan violates."""
    families = set()
    itinerary = plan.get("itinerary", []) or []
    if not isinstance(itinerary, list):
        return families
    n_days = len(itinerary)

    all_acts = []
    for day_idx, day in enumerate(itinerary):
        activities = (day or {}).get("activities", []) or []
        if not isinstance(activities, list):
            continue
        all_acts.extend(activities)

        meal_counts = {t: 0 for t in _MEAL_TYPES}
        has_accommodation = False
        prev_end = None
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            atype = activity.get("type")
            if atype in _MEAL_TYPES:
                meal_counts[atype] += 1
                if meal_counts[atype] > 1:
                    families.add("repeated_meal")
            if atype == "accommodation":
                has_accommodation = True

            try:
                st_min = _time_to_minutes(activity["start_time"])
                ed_min = _time_to_minutes(activity["end_time"])
            except Exception:
                prev_end = None
                continue

            if prev_end is not None and st_min < prev_end:
                families.add("overlap")

            transports = activity.get("transports") or []
            if transports:
                try:
                    t_start = _time_to_minutes(transports[0]["start_time"])
                except Exception:
                    t_start = None
                if t_start is not None and prev_end is not None and t_start < prev_end:
                    families.add("transport_before_prev_end")

            prev_end = ed_min

        if day_idx < n_days - 1 and not has_accommodation:
            families.add("missing_accommodation_nonfinal_day")

    if not all_acts or all_acts[0].get("type") not in _INTERCITY_TYPES or all_acts[-1].get("type") not in _INTERCITY_TYPES:
        families.add("missing_intercity_endpoint")

    if n_days == 1 and all_acts and all_acts[-1].get("type") == "accommodation":
        families.add("single_day_trailing_stay")

    return families


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--best-dir", default=BEST_DIR, help="directory of <uid>.json plans (default: results/best)")
    ap.add_argument("--split", default=None, help="restrict to uids in this split file (default: every plan in --best-dir)")
    ap.add_argument("--out", default=None, help="write the union of flagged uids as a split file")
    args = ap.parse_args()

    if args.split:
        uids = [u for u in _read_uids(args.split) if os.path.exists(os.path.join(args.best_dir, u + ".json"))]
    else:
        uids = sorted(
            os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(args.best_dir, "*.json"))
        )

    counts = {f: 0 for f in FAMILIES}
    flagged = {}
    for uid in uids:
        with open(os.path.join(args.best_dir, uid + ".json"), encoding="utf-8") as f:
            plan = json.load(f)
        families = flag_plan(plan)
        for f in families:
            counts[f] += 1
        if families:
            flagged[uid] = families

    print("plans: {}".format(len(uids)))
    for family in FAMILIES:
        print("{:<35} {}".format(family, counts[family]))
    print("union of flagged uids: {}".format(len(flagged)))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for uid in sorted(flagged):
                f.write(uid + "\n")
        print("wrote {} uids to {}".format(len(flagged), args.out))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
