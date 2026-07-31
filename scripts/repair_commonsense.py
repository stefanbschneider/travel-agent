#!/usr/bin/env python
"""Repair the Phase 1 commonsense-tail plans (docs/tpc_shortcomings_and_plan.md W1).

Reads results/best/<uid>.json, applies four ordered deterministic repair moves (R1-R4 below) on a
deepcopy, and writes the repaired plan to results/<method>/<uid>.json only when the full oracle
schema/commonsense checker accepts it -- scripts/merge.py remains the sole writer of results/best,
so adoption stays score-monotonic (merge.py's own strictly-greater score gate is a second,
independent guard).

The four moves, applied in order on the same working copy, then gated once at the end
(docs/tpc_shortcomings_and_plan.md section 3.3):

  R1 -- drop duplicate meal types (repeated_meal)
  R2 -- restore chronological list order (overlap: list-order-only cases)
  R3 -- re-space overlapping activities, dropping one if it can't fit (overlap: real time conflicts)
  R4 -- re-ground an inbound leg that starts before the previous activity ends
        (transport_before_prev_end), then R3 runs once more to absorb any ripple it creates

Every leg recomputation reuses TPCAgent's existing grounding helpers (_get_transport,
_lookup_poi_open_bounds, _activity_end_position/_activity_start_position) -- no new geometry.
Intercity (airplane/train) activities are never moved, dropped, or re-timed by any move.
"""
import argparse
import glob
import json
import os
import sys
from copy import deepcopy
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_SPLIT = "p1_commonsense_tail"
DEFAULT_METHOD = "repair_commonsense"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CHINATRAVEL_ROOT = os.path.join(ROOT, "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent, time_to_minutes, minutes_to_time
from chinatravel.agent.tpc_agent.tpc_llm import TPCLLM
from chinatravel.data.load_datasets import NpEncoder, load_query
from chinatravel.environment.world_env import WorldEnv
from scan_commonsense_residual import flag_plan

MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, cls=NpEncoder)


def _day_is_chronological(activities):
    """Structural-only chronology check over one day's activity list (mirrors the official
    Is_time_correct rules this repair targets, without needing WorldEnv)."""
    prev_end = None
    for activity in activities:
        try:
            start_min = time_to_minutes(activity["start_time"])
            end_min = time_to_minutes(activity["end_time"])
        except Exception:
            return False
        if prev_end is not None and start_min < prev_end:
            return False
        transports = activity.get("transports") or []
        if transports:
            try:
                t_start_min = time_to_minutes(transports[0]["start_time"])
            except Exception:
                t_start_min = None
            if t_start_min is not None and prev_end is not None and t_start_min < prev_end:
                return False
        prev_end = end_min
    return True


def _shift_activity(activity, new_start_min):
    """Shift `activity` later to start at new_start_min, preserving its own duration.

    Never moves an activity earlier -- a no-op if new_start_min is not later than its current
    start. Returns True if the activity's times changed.
    """
    old_start_min = time_to_minutes(activity["start_time"])
    if new_start_min <= old_start_min:
        return False
    old_end_min = time_to_minutes(activity["end_time"])
    delta = new_start_min - old_start_min
    activity["start_time"] = minutes_to_time(old_start_min + delta)
    activity["end_time"] = minutes_to_time(old_end_min + delta)
    return True


def _lookup_transport(agent, city, from_pos, to_pos, depart_time, people):
    """Shortest-time valid inner-city leg from from_pos to to_pos departing at depart_time.

    Uses the shortest-time valid mode (``_best_transport_via_get_transport``, the same lookup the
    Task 3 packing passes use for ATT protection) rather than ``_get_transport``'s default
    metro-first mode order: a repair should fix a broken *timing*, not silently swap a plan's
    existing fast taxi/walk hop for a much slower multi-leg metro detour just because that
    happens to be the generic default.

    Falls back to a forced free walk, with the query's derived inner-transport-mode exclusion
    temporarily lifted, when that lookup finds no route at all: a solver-time "metro only"
    heuristic derived from the query can make no route reachable for a short hop even when the
    stored plan already walked it for free, and walking never costs money, so retrying with it
    cannot break a budget-style oracle clause the exclusion was derived from -- unlike falling
    back to taxi/metro, which could. Never falls back to a paid mode. Returns (transports,
    arrival), possibly (None, None).
    """
    try:
        transports, arrival = agent._best_transport_via_get_transport(city, from_pos, to_pos, depart_time, people)
    except Exception:
        transports, arrival = None, None
    if transports is not None:
        return transports, arrival
    saved_forced = getattr(agent, "_forced_inner_mode", None)
    saved_excluded = agent._transport_constraints.get("excluded_inner_transport")
    try:
        agent._forced_inner_mode = "walk"
        agent._transport_constraints["excluded_inner_transport"] = []
        return agent._get_transport(agent.env, city, from_pos, to_pos, depart_time, people)
    except Exception:
        return None, None
    finally:
        agent._forced_inner_mode = saved_forced
        agent._transport_constraints["excluded_inner_transport"] = saved_excluded


def _reground_inbound(agent, city, people, prev_activity, activity, *, clamp):
    """Recompute `activity`'s inbound leg from `prev_activity`'s end position/time via
    ``_lookup_transport``. When `clamp` is set, also shifts `activity` later (preserving its
    duration) if the recomputed arrival is later than its current start -- except an intercity
    (airplane/train) activity, whose own ticketed start_time/end_time is never moved; its inbound
    leg (the hop to the boarding station/airport) is still recomputed and re-timed against
    ``prev_activity``, since that leg is exactly what ``transport_before_prev_end`` flags when it
    starts too early. Returns True if anything changed."""
    from_pos = agent._activity_end_position(prev_activity)
    to_pos = agent._activity_start_position(activity)
    depart_time = str(prev_activity.get("end_time", ""))
    if not (from_pos and to_pos and depart_time):
        return False
    transports, arrival = _lookup_transport(agent, city, from_pos, to_pos, depart_time, people)
    if transports is None:
        return False
    is_intercity = agent._is_intercity_activity(activity)
    if is_intercity and arrival:
        # The activity's own start_time is a fixed ticketed departure that can never move, so a
        # regrounded leg is only an improvement if it still arrives in time -- otherwise we would
        # trade "departs before the previous activity ends" for "arrives after its own
        # departure," an equally invalid chronology this repair cannot fix by shifting.
        try:
            arrival_min = time_to_minutes(arrival)
            own_start_min = time_to_minutes(activity["start_time"])
        except Exception:
            return False
        if arrival_min > own_start_min:
            return False
    changed = False
    if activity.get("transports") != transports:
        activity["transports"] = transports
        changed = True
    if clamp and arrival and not is_intercity:
        try:
            arrival_min = time_to_minutes(arrival)
        except Exception:
            arrival_min = None
        if arrival_min is not None and _shift_activity(activity, arrival_min):
            changed = True
    return changed


def _repair_duplicate_meals(agent, plan, query, city, people):
    """R1: keep exactly one activity per meal type per day, dropping the rest."""
    changed = False
    hard_logic_text = "\n".join(str(c) for c in (query.get("hard_logic_py") or [])).lower()
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        for meal_type in MEAL_TYPES:
            indices = [i for i, a in enumerate(activities) if isinstance(a, dict) and a.get("type") == meal_type]
            if len(indices) <= 1:
                continue
            keep = None
            for i in indices:
                pos = str(activities[i].get("position", ""))
                if pos and pos.lower() in hard_logic_text:
                    keep = i
                    break
            if keep is None:
                for i in indices:
                    trial_day = [a for j, a in enumerate(activities) if j == i or j not in indices]
                    if _day_is_chronological(trial_day):
                        keep = i
                        break
            if keep is None:
                keep = indices[0]
            for idx in sorted((i for i in indices if i != keep), reverse=True):
                prev_act = activities[idx - 1] if idx > 0 else None
                del activities[idx]
                changed = True
                if prev_act is not None and idx < len(activities):
                    _reground_inbound(agent, city, people, prev_act, activities[idx], clamp=True)
    return changed


def _restore_chronological_order(agent, plan, query, city, people):
    """R2: sort each day's activities by start_time, holding an intercity head/tail fixed."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        if len(activities) < 2:
            continue
        head_fixed = agent._is_intercity_activity(activities[0])
        tail_fixed = agent._is_intercity_activity(activities[-1])
        start = 1 if head_fixed else 0
        end = len(activities) - 1 if tail_fixed else len(activities)
        middle = activities[start:end]
        if len(middle) < 2:
            continue
        sorted_middle = sorted(middle, key=lambda a: time_to_minutes(a["start_time"]))
        if [id(a) for a in sorted_middle] == [id(a) for a in middle]:
            continue
        new_activities = activities[:start] + sorted_middle + activities[end:]
        day["activities"] = new_activities
        activities = new_activities
        changed = True
        for idx in range(1, len(activities)):
            _reground_inbound(agent, city, people, activities[idx - 1], activities[idx], clamp=False)
    return changed


def _respace_overlaps(agent, plan, query, city, people):
    """R3: walk each day forward: shift an overlapping activity later (preserving its duration),
    or drop it if the shift would miss its POI closing time or a fixed intercity tail."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        idx = 1
        while idx < len(activities):
            activity = activities[idx]
            prev_activity = activities[idx - 1]
            if agent._is_intercity_activity(activity):
                idx += 1
                continue
            try:
                prev_end_min = time_to_minutes(prev_activity["end_time"])
                start_min = time_to_minutes(activity["start_time"])
            except Exception:
                idx += 1
                continue
            if start_min >= prev_end_min:
                idx += 1
                continue

            from_pos = agent._activity_end_position(prev_activity)
            to_pos = agent._activity_start_position(activity)
            transports, arrival = _lookup_transport(
                agent, city, from_pos, to_pos, str(prev_activity["end_time"]), people)
            if transports is None or arrival is None:
                idx += 1
                continue

            new_start_min = max(start_min, time_to_minutes(arrival))
            duration = time_to_minutes(activity["end_time"]) - start_min
            new_end_min = new_start_min + duration

            fits = True
            try:
                bounds = agent._lookup_poi_open_bounds(
                    city, agent._activity_start_position(activity), activity.get("type"), activity.get("tickets"))
            except Exception:
                bounds = None
            if bounds is not None and new_end_min > bounds[1]:
                fits = False
            if idx + 1 < len(activities) and agent._is_intercity_activity(activities[idx + 1]):
                next_start_min = time_to_minutes(activities[idx + 1]["start_time"])
                if new_start_min > next_start_min:
                    fits = False

            if not fits:
                del activities[idx]
                changed = True
                if idx < len(activities):
                    _reground_inbound(agent, city, people, prev_activity, activities[idx], clamp=True)
                continue

            activity["transports"] = transports
            activity["start_time"] = minutes_to_time(new_start_min)
            activity["end_time"] = minutes_to_time(new_end_min)
            changed = True
            idx += 1
    return changed


def _reground_early_transport(agent, plan, query, city, people):
    """R4: an inbound leg that starts before the previous activity ends is re-requested from the
    previous activity's actual end_time, and the activity is shifted to the returned arrival."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        for idx in range(1, len(activities)):
            activity = activities[idx]
            prev_activity = activities[idx - 1]
            transports = activity.get("transports") or []
            if not transports:
                continue
            try:
                t_start_min = time_to_minutes(transports[0]["start_time"])
                prev_end_min = time_to_minutes(prev_activity["end_time"])
            except Exception:
                continue
            if t_start_min >= prev_end_min:
                continue
            if _reground_inbound(agent, city, people, prev_activity, activity, clamp=True):
                changed = True
    return changed


def repair_plan(agent, plan, query):
    """Apply R1-R4 in order on a deepcopy; caller gates commit with the full checker."""
    trial = deepcopy(plan)
    city = str(query.get("target_city", ""))
    people = int(query.get("people_number", 1) or 1)
    agent._set_transport_context(agent._collect_constraints(query))
    _repair_duplicate_meals(agent, trial, query, city, people)
    _restore_chronological_order(agent, trial, query, city, people)
    _respace_overlaps(agent, trial, query, city, people)
    _reground_early_transport(agent, trial, query, city, people)
    _respace_overlaps(agent, trial, query, city, people)  # absorb any ripple R4 introduced
    return trial


def _residual_reason(query, plan):
    families = flag_plan(plan)
    return ",".join(sorted(families)) if families else "logical_clause_failure"


def _process(args):
    method = args.method or DEFAULT_METHOD
    result_dir = os.path.join(ROOT, "results", method)
    best_dir = os.path.join(ROOT, "results", "best")
    os.makedirs(result_dir, exist_ok=True)

    query_args = SimpleNamespace(splits=args.split, lang="en", oracle_translation=True)
    uids, query_data = load_query(query_args)
    if args.limit:
        uids = uids[: args.limit]

    considered = repaired = written = unresolved = 0
    unresolved_uids = []

    if args.dry_run:
        for uid in uids:
            best_path = os.path.join(best_dir, uid + ".json")
            if not os.path.exists(best_path):
                continue
            plan = _load_json(best_path)
            considered += 1
            families = flag_plan(plan)
            print("repair_commonsense: {} applicable repairs: {}".format(
                uid, ",".join(sorted(families)) if families else "none"))
        print("repair_commonsense: dry-run considered={}".format(considered))
        return 0

    agent = TPCAgent(
        env=WorldEnv(lang="en"),
        backbone_llm=TPCLLM(),
        cache_dir=os.path.join(ROOT, "cache"),
        log_dir=os.path.join(ROOT, "cache", "repair_commonsense"),
        debug=True,
        lang="en",
    )

    for uid in uids:
        best_path = os.path.join(best_dir, uid + ".json")
        if not os.path.exists(best_path):
            continue
        plan = _load_json(best_path)
        query = query_data.get(uid)
        if query is None:
            continue
        plan.pop("_eval_score", None)
        considered += 1
        constraints = agent._collect_constraints(query)
        check = agent._make_checker(query, constraints)
        try:
            trial = repair_plan(agent, plan, query)
        except Exception as exc:
            print("repair_commonsense: {} raised during repair: {}".format(uid, exc))
            unresolved += 1
            unresolved_uids.append((uid, "exception:{}".format(exc)))
            continue

        try:
            accepted = agent._accepted(*check(trial))
        except Exception:
            accepted = False
        if accepted:
            repaired += 1
            _save_json(os.path.join(result_dir, uid + ".json"), trial)
            written += 1
        else:
            unresolved += 1
            unresolved_uids.append((uid, _residual_reason(query, trial)))

    print("repair_commonsense: considered={} repaired={} written={} unresolved={}".format(
        considered, repaired, written, unresolved))
    if unresolved_uids:
        print("repair_commonsense: unresolved uids (uid, residual):")
        for uid, reason in unresolved_uids:
            print("  {}  {}".format(uid, reason))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default=DEFAULT_SPLIT, help="split file of uids to process")
    ap.add_argument("--method", default=None, help="results/ output directory (default: repair_commonsense)")
    ap.add_argument("--limit", type=int, default=None, help="process at most N uids")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="report the repair each plan would receive, write nothing")
    args = ap.parse_args()
    return _process(args)


if __name__ == "__main__":
    sys.exit(main())
